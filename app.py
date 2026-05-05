import streamlit as st
import datetime
import os
import pandas as pd
import base64
import boto3
from botocore.config import Config
import psycopg2

st.set_page_config(page_title="現場DXツール", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 🔒 シークレット情報（クラウドの設定画面から安全に読み込む）
# ==========================================
# st.secrets を使って、コードに直書きせずにパスワードを呼び出します
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]
DB_PASSWORD = st.secrets["DB_PASSWORD"]

AWS_REGION = "ap-northeast-3"
BUCKET_NAME = "koukan-images-sasaki-2026"

s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION,
    config=Config(signature_version='s3v4')
)

DB_HOST = "koukan-database-1.c3gioua8mw4u.ap-northeast-3.rds.amazonaws.com"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres"

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

COLS = ['A', 'B', 'C', 'D', 'E']
ROWS = ['1', '2', '3', '4', '5']

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_reports (
            id SERIAL PRIMARY KEY,
            vendor_name TEXT,
            work_date TEXT,
            image_path TEXT,
            status TEXT DEFAULT '未確認',
            feedback TEXT DEFAULT ''
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS area_requests (
            id SERIAL PRIMARY KEY,
            vendor_name TEXT,
            target_floor TEXT,
            selected_grids TEXT,
            submit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT '未確認',
            feedback TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def update_status(table, record_id, new_status, feedback):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE {table} SET status = %s, feedback = %s WHERE id = %s", (new_status, feedback, record_id))
    conn.commit()
    conn.close()

# ==========================================
# 🌟 UI部分（変更なし）
# ==========================================
st.sidebar.title("Buildee Clone")
st.sidebar.caption("スマート施工管理システム プロトタイプ")
st.sidebar.divider()
page = st.sidebar.radio("ワークスペースを選択", ["👷 現場用ツール（ベンダー）", "🏢 管理ダッシュボード（発注者）"])

if page == "👷 現場用ツール（ベンダー）":
    st.title("現場ワークスペース")
    st.caption("本日の業務と、次週の予定を申請してください。")
    
    col_left, col_right = st.columns([1, 1.2])

    with col_left:
        st.subheader("📝 本日の作業日報")
        with st.form("daily_report_form"):
            vendor_name = st.selectbox("会社名", ["A設備工業", "B電気通信", "Cマテリアル", "D空調設備"])
            work_date = st.date_input("作業日", datetime.date.today())
            uploaded_file = st.file_uploader("完了写真をアップロード", type=["jpg", "png", "jpeg"])
            
            submit_report = st.form_submit_button("日報を提出する 🚀", use_container_width=True)
            if submit_report:
                s3_file_name = ""
                if uploaded_file is not None:
                    s3_file_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
                    try:
                        s3_client.upload_fileobj(
                            uploaded_file, 
                            BUCKET_NAME, 
                            s3_file_name,
                            ExtraArgs={'ContentType': uploaded_file.type}
                        )
                    except Exception as e:
                        st.error(f"S3アップロードエラー: {e}")
                
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO daily_reports (vendor_name, work_date, image_path, status) VALUES (%s, %s, %s, '未確認')", (vendor_name, str(work_date), s3_file_name))
                conn.commit()
                conn.close()
                st.success("日報の提出が完了しました！")

    with col_right:
        st.subheader("🗺️ 次週の作業エリア申請")
        with st.form("area_request_form"):
            req_vendor_name = st.selectbox("会社名（エリア申請）", ["A設備工業", "B電気通信", "Cマテリアル", "D空調設備"])
            target_floor = st.radio("対象フロア", ["1F", "2F", "3F", "4F", "5F"], horizontal=True)
            
            st.divider()
            st.markdown("##### 📍 作業するエリア（マス）を選択")
            
            checkbox_states = {}
            with st.container():
                for r in ROWS:
                    cols = st.columns(len(COLS))
                    for i, c in enumerate(COLS):
                        with cols[i]:
                            checkbox_states[f"{c}-{r}"] = st.checkbox(f"{c}-{r}", key=f"chk_{c}_{r}")
            
            st.divider()
            submit_area = st.form_submit_button("エリア申請を提出する 🚀", use_container_width=True)
            
            if submit_area:
                selected_cells = [cell for cell, is_checked in checkbox_states.items() if is_checked]
                if not selected_cells:
                    st.error("エラー：作業エリアが選択されていません！")
                else:
                    grids_str = ",".join(selected_cells)
                    conn = get_db_connection()
                    db_c = conn.cursor()
                    db_c.execute("INSERT INTO area_requests (vendor_name, target_floor, selected_grids, status) VALUES (%s, %s, %s, '未確認')", (req_vendor_name, target_floor, grids_str))
                    conn.commit()
                    conn.close()
                    st.success(f"申請完了: {grids_str}")

    st.divider()
    st.subheader("📬 提出状況・発注者からのフィードバック")
    
    conn = get_db_connection()
    df_my_reports = pd.read_sql_query("SELECT * FROM daily_reports ORDER BY id DESC LIMIT 5", conn)
    conn.close()
    
    if not df_my_reports.empty:
        for index, row in df_my_reports.iterrows():
            status_color = "🟢" if row['status'] == "承認済" else "🔴" if row['status'] == "差し戻し" else "⚪"
            with st.expander(f"{status_color} 【{row['status']}】 {row['work_date']} | {row['vendor_name']} の日報"):
                if row['status'] == "差し戻し":
                    st.error(f"**発注者からのコメント:** {row['feedback']}")
                elif row['status'] == "承認済":
                    st.success("この日報は承認されました。")
                else:
                    st.info("現在、発注者の確認待ちです。")

elif page == "🏢 管理ダッシュボード（発注者）":
    st.title("HQ ダッシュボード")
    
    password = st.sidebar.text_input("🔑 セキュリティキー", type="password")
    if password != "12345":
        st.warning("👈 サイドバーから正しいセキュリティキーを入力してください。")
        st.stop()

    st.sidebar.divider()
    bg_file = st.sidebar.file_uploader("背景図面の変更", type=["jpg", "png"])
    bg_path = "uploaded_images/floor_plan_bg.jpg"
    if bg_file is not None:
        if not os.path.exists("uploaded_images"):
            os.makedirs("uploaded_images")
        with open(bg_path, "wb") as f:
            f.write(bg_file.getbuffer())

    st.subheader("📋 承認待ちアクション")
    
    conn = get_db_connection()
    df_pending_reports = pd.read_sql_query("SELECT * FROM daily_reports WHERE status='未確認' OR status='差し戻し'", conn)
    conn.close()
    
    if df_pending_reports.empty:
        st.success("現在、未確認の日報はありません。")
    else:
        for index, row in df_pending_reports.iterrows():
            with st.expander(f"⚠️ 確認待ち: {row['work_date']} | {row['vendor_name']}", expanded=True):
                col_img, col_action = st.columns(2)
                
                with col_img:
                    if row['image_path'] and row['image_path'] != "":
                        try:
                            response = s3_client.get_object(Bucket=BUCKET_NAME, Key=row['image_path'])
                            image_data = response['Body'].read()
                            st.image(image_data, use_container_width=True, caption=f"S3から直接取得: {row['image_path']}")
                        except Exception as e:
                            st.error(f"S3からの画像読み込みに失敗しました: {e}")
                    else:
                        st.write("※写真なし")
                        
                with col_action:
                    feedback_msg = st.text_area("フィードバック・是正指示", key=f"fb_{row['id']}")
                    btn_col1, btn_col2 = st.columns(2)
                    if btn_col1.button("✅ 承認する", key=f"app_{row['id']}", use_container_width=True):
                        update_status('daily_reports', row['id'], '承認済', feedback_msg)
                        st.rerun()
                    if btn_col2.button("❌ 差し戻し", type="primary", key=f"rej_{row['id']}", use_container_width=True):
                        update_status('daily_reports', row['id'], '差し戻し', feedback_msg)
                        st.rerun()

    st.divider()
    st.subheader("🚨 リアルタイム・エリアバッティング監視")
    
    conn = get_db_connection()
    df_areas = pd.read_sql_query("SELECT * FROM area_requests", conn)
    conn.close()

    selected_floor = st.selectbox("監視フロアを切り替え", ["1F", "2F", "3F", "4F", "5F"])
    df_floor = df_areas[df_areas['target_floor'] == selected_floor]
    
    grid_map = {f"{c}-{r}": [] for c in COLS for r in ROWS}
    
    for index, row in df_floor.iterrows():
        if pd.notna(row['selected_grids']) and row['selected_grids'] != "":
            covered_cells = row['selected_grids'].split(',')
            for cell in covered_cells:
                if row['vendor_name'] not in grid_map[cell]: 
                    grid_map[cell].append(row['vendor_name'])

    bg_base64 = ""
    if os.path.exists(bg_path):
        with open(bg_path, "rb") as img_file:
            bg_base64 = base64.b64encode(img_file.read()).decode()

    if bg_base64:
        bg_style = f"background-image: url('data:image/jpeg;base64,{bg_base64}'); background-size: cover; background-position: center;"
    else:
        bg_style = "background: radial-gradient(circle, #f0f2f6 0%, #d9dce3 100%);" 

    st.markdown("""
    <style>
    .modern-grid { display: grid; grid-template-columns: repeat(5, 1fr); grid-template-rows: repeat(5, 1fr); gap: 12px; padding: 24px; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.15); border: 1px solid rgba(255, 255, 255, 0.4); position: relative; }
    .grid-cell { aspect-ratio: 1 / 1; border-radius: 16px; display: flex; flex-direction: column; justify-content: center; align-items: center; font-family: 'Helvetica Neue', Arial, sans-serif; transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); }
    .grid-cell:hover { transform: translateY(-5px) scale(1.03); box-shadow: 0 12px 24px rgba(0,0,0,0.2); z-index: 10; }
    .cell-empty { background-color: rgba(255, 255, 255, 0.25); border: 2px dashed rgba(255,255,255,0.6); color: rgba(0,0,0,0.6); }
    .cell-safe { background: linear-gradient(135deg, rgba(32, 201, 151, 0.85) 0%, rgba(25, 135, 84, 0.85) 100%); border: 1px solid rgba(255,255,255,0.5); color: white; text-shadow: 0 1px 3px rgba(0,0,0,0.5); box-shadow: 0 4px 10px rgba(32, 201, 151, 0.3); }
    .cell-danger { background: linear-gradient(135deg, rgba(255, 65, 108, 0.9) 0%, rgba(255, 75, 43, 0.9) 100%); border: 1px solid rgba(255,255,255,0.5); color: white; text-shadow: 0 1px 3px rgba(0,0,0,0.5); animation: pulse-red 2s infinite; }
    @keyframes pulse-red { 0% { box-shadow: 0 0 0 0 rgba(255, 65, 108, 0.7); } 70% { box-shadow: 0 0 0 15px rgba(255, 65, 108, 0); } 100% { box-shadow: 0 0 0 0 rgba(255, 65, 108, 0); } }
    .cell-title { font-size: 1.5rem; font-weight: 800; margin-bottom: 4px; letter-spacing: 1px; }
    .vendor-badge { font-size: 0.75rem; font-weight: 600; background: rgba(0, 0, 0, 0.25); padding: 4px 10px; border-radius: 12px; margin-top: 3px; backdrop-filter: blur(4px); }
    </style>
    """, unsafe_allow_html=True)

    html_content = f'<div class="modern-grid" style="{bg_style}">'
    for r in ROWS:
        for c in COLS:
            cell_name = f"{c}-{r}"
            vendors = grid_map[cell_name]
            vendor_count = len(vendors)
            
            if vendor_count == 0:
                css_class = "cell-empty"
                content = f'<div class="cell-title" style="font-size: 1.2rem; opacity: 0.7;">{cell_name}</div>'
            elif vendor_count == 1:
                css_class = "cell-safe"
                content = f'<div class="cell-title">{cell_name}</div><div class="vendor-badge">{vendors[0]}</div>'
            else:
                css_class = "cell-danger"
                v_list = "".join([f'<div class="vendor-badge">{v}</div>' for v in vendors])
                content = f'<div class="cell-title">{cell_name} ⚠️</div>{v_list}'
            
            html_content += f'<div class="grid-cell {css_class}">{content}</div>'
    
    html_content += '</div>'
    st.markdown(html_content.replace('\n', ''), unsafe_allow_html=True)