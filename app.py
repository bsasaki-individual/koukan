import streamlit as st
import datetime
import os
import pandas as pd
import base64
import boto3
from botocore.config import Config
import psycopg2
from psycopg2.extras import RealDictCursor

st.set_page_config(page_title="現場DXツール", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 🔒 シークレット情報
# ==========================================
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

# ==========================================
# 🗄️ データベース初期化
# ==========================================
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # 🌟 一時的に追加：古いテーブルを一度削除してリセットする
    c.execute("DROP TABLE IF EXISTS daily_reports")
    c.execute("DROP TABLE IF EXISTS area_requests")
    c.execute("DROP TABLE IF EXISTS vendors")
    
    # 以下、新しい構造で作成（変更なし）
    c.execute('''
        CREATE TABLE IF NOT EXISTS vendors (
            id SERIAL PRIMARY KEY,
            vendor_id TEXT UNIQUE,
            vendor_name TEXT,
            password TEXT
        )
    ''')
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

# ==========================================
# 🔑 認証システム
# ==========================================
def login_vendor(vendor_id, password):
    conn = get_db_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM vendors WHERE vendor_id = %s AND password = %s", (vendor_id, password))
    user = c.fetchone()
    conn.close()
    return user

# ==========================================
# 🌟 サイドバーメニュー
# ==========================================
st.sidebar.title("Buildee Clone")

if "login_user" not in st.session_state:
    st.session_state.login_user = None

# ログアウト処理
if st.session_state.login_user:
    if st.sidebar.button("🚪 ログアウト"):
        st.session_state.login_user = None
        st.rerun()

page = st.sidebar.radio("ワークスペースを選択", ["👷 現場用ツール（ベンダー）", "🏢 管理ダッシュボード（発注者）"])

# ==========================================
# 画面1：ベンダー向けツール（ログイン必須）
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
        st.subheader("📝 本日の作業日報")
        with st.form("daily_report_form"):
            work_date = st.date_input("作業日", datetime.date.today())
            uploaded_file = st.file_uploader("完了写真をアップロード", type=["jpg", "png", "jpeg"])
            
            if st.form_submit_button("日報を提出する 🚀", use_container_width=True):
                s3_file_name = ""
                if uploaded_file is not None:
                    s3_file_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
                    s3_client.upload_fileobj(uploaded_file, BUCKET_NAME, s3_file_name, ExtraArgs={'ContentType': uploaded_file.type})
                
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO daily_reports (vendor_id, work_date, image_path) VALUES (%s, %s, %s)", (user['vendor_id'], str(work_date), s3_file_name))
                conn.commit()
                conn.close()
                st.success("日報を提出しました")

    with col_right:
        st.subheader("📬 フィードバック")
        conn = get_db_connection()
        df_my = pd.read_sql_query("SELECT * FROM daily_reports WHERE vendor_id = %s ORDER BY id DESC LIMIT 5", conn, params=(user['vendor_id'],))
        conn.close()
        for idx, row in df_my.iterrows():
            st.info(f"【{row['status']}】 {row['work_date']} 日報")

# ==========================================
# 画面2：管理ダッシュボード
# ==========================================
elif page == "🏢 管理ダッシュボード（発注者）":
    st.title("HQ ダッシュボード")
    if st.sidebar.text_input("🔑 セキュリティキー", type="password") != "12345":
        st.warning("セキュリティキーを入力してください")
        st.stop()

    # --- 🌟 新機能：ベンダー管理タブ ---
    tab1, tab2, tab3 = st.tabs(["📋 承認待ち", "🚨 バッティング監視", "👥 ベンダー管理"])

    with tab3:
        st.subheader("ベンダーアカウントの発行")
        with st.form("add_vendor_form"):
            new_v_name = st.text_input("会社名 (例: A設備工業)")
            new_v_id = st.text_input("ログインID (例: vendorA)")
            new_v_pw = st.text_input("パスワード")
            if st.form_submit_button("新規登録"):
                conn = get_db_connection()
                c = conn.cursor()
                try:
                    c.execute("INSERT INTO vendors (vendor_id, vendor_name, password) VALUES (%s, %s, %s)", (new_v_id, new_v_name, new_v_pw))
                    conn.commit()
                    st.success(f"{new_v_name} を登録しました")
                except:
                    st.error("そのIDは既に使われています")
                conn.close()

        st.divider()
        st.subheader("登録済みベンダー一覧")
        conn = get_db_connection()
        df_v = pd.read_sql_query("SELECT id, vendor_id, vendor_name, password FROM vendors", conn)
        conn.close()
        st.dataframe(df_v, use_container_width=True)

    # (タブ1, タブ2 の中身は以前の承認・監視ロジックを配置)
    with tab1:
        # ...（承認待ちロジックをここに配置）
        pass