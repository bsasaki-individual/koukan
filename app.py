import streamlit as st
import datetime
import os
import pandas as pd
import base64
import boto3
from botocore.config import Config
import psycopg2
from psycopg2.extras import RealDictCursor

# 画面設定
st.set_page_config(page_title="現場DXツール", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 🔒 シークレット情報 (Streamlit CloudのSecretsから読み込み)
# ==========================================
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]
DB_PASSWORD = st.secrets["DB_PASSWORD"]

AWS_REGION = "ap-northeast-3"
BUCKET_NAME = "koukan-images-sasaki-2026"

# S3クライアント初期化
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION,
    config=Config(signature_version='s3v4')
)

# RDS設定
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

# ==========================================
# 🗄️ データベース初期化
# ==========================================
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # ベンダーマスタ
    c.execute('''
        CREATE TABLE IF NOT EXISTS vendors (
            id SERIAL PRIMARY KEY,
            vendor_id TEXT UNIQUE,
            vendor_name TEXT,
            password TEXT
        )
    ''')
    # 日報テーブル (vendor_idを使用)
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_reports (
            id SERIAL PRIMARY KEY,
            vendor_id TEXT,
            work_date TEXT,
            image_path TEXT,
            status TEXT DEFAULT '未確認',
            feedback TEXT DEFAULT ''
        )
    ''')
    # エリア申請テーブル (vendor_idを使用)
    c.execute('''
        CREATE TABLE IF NOT EXISTS area_requests (
            id SERIAL PRIMARY KEY,
            vendor_id TEXT,
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

# ステータス更新用関数
def update_status(table, record_id, new_status, feedback):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE {table} SET status = %s, feedback = %s WHERE id = %s", (new_status, feedback, record_id))
    conn.commit()
    conn.close()

# ログイン認証用関数
def login_vendor(vendor_id, password):
    conn = get_db_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM vendors WHERE vendor_id = %s AND password = %s", (vendor_id, password))
    user = c.fetchone()
    conn.close()
    return user

# ==========================================
# 🌟 メインメニュー
# ==========================================
st.sidebar.title("Buildee Clone")

if "login_user" not in st.session_state:
    st.session_state.login_user = None

if st.session_state.login_user:
    if st.sidebar.button("🚪 ログアウト"):
        st.session_state.login_user = None
        st.rerun()

page = st.sidebar.radio("ワークスペースを選択", ["👷 現場用ツール（ベンダー）", "🏢 管理ダッシュボード（発注者）"])

# ==========================================
# 画面1：ベンダー用ツール
# ==========================================
if page == "👷 現場用ツール（ベンダー）":
    if st.session_state.login_user is None:
        st.title("ベンダーログイン")
        with st.form("login_form"):
            v_id = st.text_input("ログインID")
            v_pw = st.text_input("パスワード", type="password")
            if st.form_submit_button("ログイン"):
                user = login_vendor(v_id, v_pw)
                if user:
                    st.session_state.login_user = user
                    st.rerun()
                else:
                    st.error("IDまたはパスワードが違います")
        st.stop()

    user = st.session_state.login_user
    st.title(f"ようこそ、{user['vendor_name']} 様")
    
    col_left, col_right = st.columns([1, 1.2])

    with col_left:
        st.subheader("📝 本日の作業日報提出")
        with st.form("daily_report_form"):
            work_date = st.date_input("作業日", datetime.date.today())
            uploaded_file = st.file_uploader("完了写真をアップロード", type=["jpg", "png", "jpeg"])
            
            if st.form_submit_button("日報を提出する 🚀", use_container_width=True):
                s_file_name = ""
                if uploaded_file is not None:
                    s_file_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
                    s3_client.upload_fileobj(uploaded_file, BUCKET_NAME, s_file_name, ExtraArgs={'ContentType': uploaded_file.type})
                
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO daily_reports (vendor_id, work_date, image_path) VALUES (%s, %s, %s)", (user['vendor_id'], str(work_date), s_file_name))
                conn.commit()
                conn.close()
                st.success("日報を提出しました！")

    with col_right:
        st.subheader("🗺️ 次週のエリア申請")
        with st.form("area_form"):
            t_floor = st.radio("フロア", ["1F", "2F", "3F", "4F", "5F"], horizontal=True)
            # エリア選択 (簡略化表示)
            sel_grids = st.multiselect("作業エリア選択", [f"{c}-{r}" for r in ['1','2','3','4','5'] for c in ['A','B','C','D','E']])
            if st.form_submit_button("エリア申請を提出 🚀"):
                if sel_grids:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("INSERT INTO area_requests (vendor_id, target_floor, selected_grids) VALUES (%s, %s, %s)", (user['vendor_id'], t_floor, ",".join(sel_grids)))
                    conn.commit()
                    conn.close()
                    st.success("エリア申請を完了しました")
                else:
                    st.error("エリアを選択してください")

    st.divider()
    st.subheader("🔔 自社の提出・承認状況")
    conn = get_db_connection()
    df_status = pd.read_sql_query("SELECT * FROM daily_reports WHERE vendor_id = %s ORDER BY id DESC LIMIT 5", conn, params=(user['vendor_id'],))
    conn.close()
    if not df_status.empty:
        for _, r in df_status.iterrows():
            st.write(f"【{r['status']}】 {r['work_date']} 提出分 (フィードバック: {r['feedback']})")

# ==========================================
# 画面2：発注者用ダッシュボード
# ==========================================
elif page == "🏢 管理ダッシュボード（発注者）":
    st.title("HQ ダッシュボード")
    if st.sidebar.text_input("🔑 セキュリティキー", type="password") != "12345":
        st.warning("セキュリティキーを入力してください")
        st.stop()

    tab1, tab2, tab3 = st.tabs(["📋 承認待ち日報", "🚨 バッティング監視", "👥 ベンダー管理"])

    with tab1:
        st.subheader("📋 承認待ちリスト")
        conn = get_db_connection()
        # JOINを使用して会社名を取得
        query = """
            SELECT dr.*, v.vendor_name 
            FROM daily_reports dr
            LEFT JOIN vendors v ON dr.vendor_id = v.vendor_id
            WHERE dr.status = '未確認' OR dr.status = '差し戻し'
            ORDER BY dr.id DESC
        """
        df_p = pd.read_sql_query(query, conn)
        conn.close()
        
        if df_p.empty:
            st.success("未確認の日報はありません")
        else:
            for _, r in df_p.iterrows():
                with st.expander(f"確認待ち: {r['work_date']} | {r['vendor_name'] or '不明'}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        if r['image_path']:
                            try:
                                res = s3_client.get_object(Bucket=BUCKET_NAME, Key=r['image_path'])
                                st.image(res['Body'].read(), use_container_width=True)
                            except: st.write("画像読み込み失敗")
                    with c2:
                        fb = st.text_area("コメント", key=f"f_{r['id']}")
                        if st.button("✅ 承認", key=f"a_{r['id']}"):
                            update_status('daily_reports', r['id'], '承認済', fb)
                            st.rerun()
                        if st.button("❌ 差戻", key=f"r_{r['id']}"):
                            update_status('daily_reports', r['id'], '差し戻し', fb)
                            st.rerun()

    with tab2:
        st.subheader("🚨 リアルタイム監視")
        conn = get_db_connection()
        # こちらもJOINして会社名を取得
        df_a = pd.read_sql_query("SELECT ar.*, v.vendor_name FROM area_requests ar LEFT JOIN vendors v ON ar.vendor_id = v.vendor_id", conn)
        conn.close()
        # (以前のグリッド表示ロジックをここに配置)
        st.write("※バッティング状況は、各エリア申請データを元に集計されます。")
        st.dataframe(df_a)

    with tab3:
        st.subheader("👥 ベンダーアカウント管理")
        with st.form("v_reg"):
            nv_name = st.text_input("会社名")
            nv_id = st.text_input("ログインID")
            nv_pw = st.text_input("パスワード")
            if st.form_submit_button("新規登録"):
                conn = get_db_connection()
                c = conn.cursor()
                try:
                    c.execute("INSERT INTO vendors (vendor_id, vendor_name, password) VALUES (%s, %s, %s)", (nv_id, nv_name, nv_pw))
                    conn.commit()
                    st.success(f"{nv_name} を登録しました")
                except: st.error("登録エラー（ID重複の可能性）")
                conn.close()
        
        st.divider()
        conn = get_db_connection()
        df_v = pd.read_sql_query("SELECT vendor_id, vendor_name, password FROM vendors", conn)
        conn.close()
        st.dataframe(df_v, use_container_width=True)