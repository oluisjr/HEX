# ╔══════════════════════════════════════════════════════════════╗
# ║   Power Apps Training — v4.0                                 ║
# ║   Autor: LUIS IGNACIO JUNIOR                                 ║
# ║   Fixes: cookies, quiz por seção, sidebar, busca, picker     ║
# ╚══════════════════════════════════════════════════════════════╝

import streamlit as st
import sqlite3
import hashlib
import os
import random
import re
import colorsys
import datetime
import json
import secrets
import math
from typing import Optional, Tuple

# ─────────────────────────────────────────────
# 1. PAGE CONFIG (must be first)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Power Apps Training",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# 2. DATABASE
# ─────────────────────────────────────────────
DB_PATH = "training_data.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            password    TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS progress (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            page        TEXT NOT NULL,
            visited_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, page)
        );
        CREATE TABLE IF NOT EXISTS quiz_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            correct     INTEGER NOT NULL,
            answered_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ── Auth helpers ──
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def register_user(username: str, email: str, name: str, pw: str) -> Tuple[bool, str]:
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO users (username, email, name, password) VALUES (?,?,?,?)",
            (username.strip().lower(), email.strip().lower(), name.strip(), hash_pw(pw))
        )
        conn.commit()
        conn.close()
        return True, "ok"
    except sqlite3.IntegrityError:
        return False, "Usuário ou e-mail já cadastrado."

def login_user(username: str, pw: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE (username=? OR email=?) AND password=?",
        (username.strip().lower(), username.strip().lower(), hash_pw(pw))
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def create_session_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.execute("INSERT INTO sessions (user_id, token) VALUES (?,?)", (user_id, token))
    conn.commit()
    conn.close()
    return token

def get_user_by_token(token: str) -> Optional[dict]:
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        """SELECT u.* FROM users u
           JOIN sessions s ON u.id = s.user_id
           WHERE s.token = ?
           AND datetime(s.created_at) > datetime('now', '-30 days')""",
        (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def invalidate_token(token: str):
    if token:
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()

def mark_page_visited(user_id: int, page: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO progress (user_id, page) VALUES (?,?)",
        (user_id, page)
    )
    conn.commit()
    conn.close()

def get_visited(user_id: int) -> set:
    conn = get_db()
    rows = conn.execute("SELECT page FROM progress WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return {r["page"] for r in rows}

def save_quiz_answer(user_id: int, question_id: int, correct: bool):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO quiz_results (user_id, question_id, correct) VALUES (?,?,?)",
        (user_id, question_id, int(correct))
    )
    conn.commit()
    conn.close()

def get_quiz_stats(user_id: int) -> dict:
    conn = get_db()
    rows = conn.execute(
        "SELECT question_id, correct FROM quiz_results WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()
    answered = {r["question_id"]: bool(r["correct"]) for r in rows}
    return {
        "answered": answered,
        "total": len(answered),
        "correct": sum(1 for v in answered.values() if v),
    }

# Pages that require quiz to count toward progress
QUIZ_PAGES = {"controles","formulas","navegacao","validacao","performance","seguranca","conectores","variaveis","automate_fundamentos","automate_expressoes","automate_conectores","automate_aprovacoes","automate_erros","copilot_topicos","copilot_entidades","copilot_ia","copilot_integracao","dataverse_tabelas","dataverse_seguranca","dataverse_formulas","dataverse_apps"}
TOTAL_PAGES = len(QUIZ_PAGES)  # 8

def get_progress(user_id: int) -> int:
    visited = get_visited(user_id)
    quiz_done = visited & QUIZ_PAGES
    return min(100, int(len(quiz_done) / TOTAL_PAGES * 100))

# ─────────────────────────────────────────────
# 3. SESSION STATE INIT
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        "user":                   None,
        "page":                   "home",
        "auth_tab":               "login",
        "ctx_popup":              False,
        "gbl_user":               "",
        "my_col":                 [],
        "quiz_session":           None,
        "quiz_session_answers":   {},
        "busca_query":            "",      # FIX: separate from widget key
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── AUTO-RESTORE SESSION FROM TOKEN (cookie via query_params) ──
    if st.session_state["user"] is None:
        token = st.query_params.get("token", "")
        if token:
            user = get_user_by_token(token)
            if user:
                st.session_state["user"] = user

init_session()

def current_user() -> Optional[dict]:
    return st.session_state.get("user")

def require_login():
    return current_user() is None

# ─────────────────────────────────────────────
# 4. CSS — PREMIUM DESIGN SYSTEM v4
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --brand:       #0078d4;
    --brand-dark:  #004e8c;
    --brand-light: #eff6fc;
    --text-1:      #111827;
    --text-2:      #4b5563;
    --text-3:      #9ca3af;
    --border:      #e5e7eb;
    --surface:     #f9fafb;
    --white:       #ffffff;
    --success:     #059669;
    --warn:        #d97706;
    --danger:      #dc2626;
    --radius-sm:   6px;
    --radius-md:   10px;
    --radius-lg:   14px;
    --radius-xl:   20px;
    --shadow-sm:   0 1px 3px rgba(0,0,0,0.08),0 1px 2px rgba(0,0,0,0.04);
    --shadow-md:   0 4px 12px rgba(0,0,0,0.08),0 2px 4px rgba(0,0,0,0.04);
    --shadow-lg:   0 10px 30px rgba(0,0,0,0.10),0 4px 8px rgba(0,0,0,0.05);
}

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', 'Segoe UI', system-ui, sans-serif !important;
    color: var(--text-1) !important;
    -webkit-font-smoothing: antialiased;
}
#MainMenu, footer, header { visibility: hidden; }

/* FIX: padding adequado entre sidebar e conteúdo */
.block-container {
    padding: 1.5rem 2rem 4rem 2rem !important;
    max-width: 100% !important;
}
section[data-testid="stSidebar"] > div { padding-top: 0 !important; }

/* ══ SIDEBAR ══ */
[data-testid="stSidebar"] {
    background: #0f172a !important;
    min-width: 260px !important;
    max-width: 260px !important;
}
/* Ocultar botão de colapsar sidebar (cobre variações entre versões do Streamlit) */
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
button[aria-label="Close sidebar"],
button[aria-label="Collapse sidebar"],
section[data-testid="stSidebar"] > div:first-child > div > button:first-child { display: none !important; }
[data-testid="stSidebar"] .stButton { margin-bottom: -8px !important; }
[data-testid="stSidebar"] button {
    padding: 9px 14px !important;
    height: auto !important;
    border: none !important;
    border-radius: var(--radius-md) !important;
    text-align: left !important;
    width: 100% !important;
    background: transparent !important;
    color: #94a3b8 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
    box-shadow: none !important;
    letter-spacing: 0.01em !important;
}
[data-testid="stSidebar"] button:hover {
    background: rgba(255,255,255,0.06) !important;
    color: #f1f5f9 !important;
}
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stMarkdown div,
[data-testid="stSidebar"] .stMarkdown span {
    color: #64748b !important;
}

/* ══ CODE BLOCKS ══ */
[data-testid="stCode"],
[data-testid="stCode"] *,
[data-testid="stCode"]:hover *,
[data-testid="stCode"] pre,
[data-testid="stCode"] pre *,
[data-testid="stCode"] code,
[data-testid="stCode"] span { background-color: #0d1117 !important; color: #e6edf3 !important; }
[data-testid="stCode"] > div {
    border-radius: var(--radius-md) !important;
    border: 1px solid #30363d !important;
    overflow: hidden !important;
}
[data-testid="stCode"] pre { padding: 14px 16px !important; margin: 0 !important; }
[data-testid="stCode"] .hljs-keyword   { color: #ff7b72 !important; background: transparent !important; }
[data-testid="stCode"] .hljs-string    { color: #a5d6ff !important; background: transparent !important; }
[data-testid="stCode"] .hljs-function,
[data-testid="stCode"] .hljs-title     { color: #d2a8ff !important; background: transparent !important; }
[data-testid="stCode"] .hljs-comment   { color: #8b949e !important; background: transparent !important; }
[data-testid="stCode"] .hljs-number,
[data-testid="stCode"] .hljs-literal   { color: #79c0ff !important; background: transparent !important; }
[data-testid="stCode"] .hljs-variable,
[data-testid="stCode"] .hljs-attr      { color: #ffa657 !important; background: transparent !important; }
[data-testid="stCode"] button,
[data-testid="stCode"] button:hover    { background: rgba(255,255,255,0.08) !important; color: #e6edf3 !important; }

/* ── TABS ── */
[data-baseweb="tab-list"] { background: transparent !important; border-bottom: 1px solid var(--border) !important; gap: 0 !important; overflow-x: auto !important; }
[data-baseweb="tab"]      { font-size: 13px !important; padding: 10px 16px !important; border-radius: 0 !important; font-weight: 500 !important; color: var(--text-2) !important; white-space: nowrap !important; }
[aria-selected="true"]    { color: var(--brand) !important; border-bottom: 2px solid var(--brand) !important; font-weight: 700 !important; background: transparent !important; }
[data-baseweb="tab-highlight"] { display: none !important; }
[data-baseweb="tab-border"]    { display: none !important; }

/* ── INPUTS ── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    border-radius: var(--radius-md) !important; border: 1.5px solid var(--border) !important;
    font-size: 14px !important; padding: 10px 14px !important; background: var(--white) !important;
    transition: border-color .15s !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: var(--brand) !important; box-shadow: 0 0 0 3px rgba(0,120,212,.12) !important;
}
[data-testid="stSelectbox"] > div > div { border-radius: var(--radius-md) !important; border: 1.5px solid var(--border) !important; font-size: 13px !important; }

/* ── SLIDER ── */
[data-testid="stSlider"] [role="slider"] { background: var(--brand) !important; border-color: var(--brand) !important; }

/* ── METRICS ── */
[data-testid="stMetric"]  { background: var(--white); border-radius: var(--radius-lg) !important; padding: 18px 20px !important; border: 1px solid var(--border); box-shadow: var(--shadow-sm); }
[data-testid="stMetric"] label { font-size: 11px !important; color: var(--text-3) !important; font-weight: 600 !important; text-transform: uppercase !important; letter-spacing: .8px !important; }
[data-testid="stMetricValue"] { font-size: 28px !important; color: var(--brand) !important; font-weight: 800 !important; }

/* ── ALERT ── */
[data-testid="stAlert"] { border-radius: var(--radius-md) !important; border: none !important; }

/* ── EXPANDER ── */
[data-testid="stExpander"] { border-radius: var(--radius-md) !important; border: 1px solid var(--border) !important; box-shadow: var(--shadow-sm) !important; }

/* ── PROGRESS BAR ── */
.prog-bar  { height: 6px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
.prog-fill { height: 100%; background: linear-gradient(90deg, var(--brand), #3b82f6); border-radius: 3px; transition: width .5s cubic-bezier(.4,0,.2,1); }

/* ── FORMULA CARD ── */
.fcard { border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; margin-bottom: 18px; box-shadow: var(--shadow-sm); transition: box-shadow .2s, transform .2s; }
.fcard:hover { box-shadow: var(--shadow-lg); transform: translateY(-2px); }
.fcard-header { padding: 14px 20px; display: flex; align-items: center; justify-content: space-between; }
.fcard-name { font-size: 15px; font-weight: 700; color: white; font-family: 'JetBrains Mono', monospace; }
.fcard-tag  { font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; background: rgba(255,255,255,.18); color: white; }
.fcard-body { padding: 16px 20px; background: #fafafa; }
.fcard-lbl  { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--text-3); margin: 10px 0 4px; }
.fcard-lbl:first-child { margin-top: 0; }
.fcard-txt  { font-size: 13px; color: var(--text-2); line-height: 1.65; }

/* ── LAB ── */
.lab-hdr       { padding: 14px 22px; background: linear-gradient(135deg,#0f172a,#1e293b); border-radius: var(--radius-lg) var(--radius-lg) 0 0; display: flex; align-items: center; gap: 12px; }
.lab-hdr-title { color: white; font-size: 14px; font-weight: 700; }
.lab-hdr-sub   { color: #94a3b8; font-size: 12px; margin-top: 1px; }
.lab-col-lbl   { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--text-3); margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.lab-wrap      { border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; margin-bottom: 20px; box-shadow: var(--shadow-md); }

/* ── HOME NAV CARD ── */
.hnc { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; background: var(--white); box-shadow: var(--shadow-sm); transition: all .2s cubic-bezier(.4,0,.2,1); height: 100%; position: relative; overflow: hidden; }
.hnc:before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, var(--brand), #60a5fa); transform: scaleX(0); transition: transform .2s; transform-origin: left; }
.hnc:hover { border-color: rgba(0,120,212,.3); box-shadow: var(--shadow-lg); transform: translateY(-3px); }
.hnc:hover:before { transform: scaleX(1); }

/* ── BREADCRUMB ── */
.bc { font-size: 12px; color: var(--text-3); margin-bottom: 18px; display: flex; align-items: center; gap: 6px; padding-top: 4px; }
.bc .cur { color: var(--brand); font-weight: 600; }

/* ── CHEAT SHEET ── */
.cs-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.cs-tbl th { background: var(--surface); padding: 11px 16px; text-align: left; font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--text-3); border-bottom: 2px solid var(--border); }
.cs-tbl td { padding: 11px 16px; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }
.cs-tbl tr:last-child td { border-bottom: none; }
.cs-tbl tr:hover td { background: #f9fafb; }
.fn-nm { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: var(--brand); font-size: 13px; }
.dy { color: #059669; font-weight: 700; font-size: 12px; }
.dn { color: #dc2626; font-weight: 700; font-size: 12px; }
.dp { color: #d97706; font-weight: 700; font-size: 12px; }

/* ── CONN TABLE ── */
.conn-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.conn-tbl th { background: var(--surface); padding: 10px 14px; text-align: left; font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--text-3); border-bottom: 2px solid var(--border); }
.conn-tbl td { padding: 10px 14px; border-bottom: 1px solid #f3f4f6; font-size: 12.5px; vertical-align: top; }
.conn-tbl tr:last-child td { border-bottom: none; }
.conn-tbl tr:hover td { background: #f9fafb; }
.conn-nm { font-weight: 700; color: var(--text-1); }

/* ── QUIZ ── */
.quiz-card { background: var(--white); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 24px; margin-bottom: 14px; box-shadow: var(--shadow-sm); }
.quiz-q    { font-size: 15px; font-weight: 700; color: var(--text-1); margin-bottom: 16px; line-height: 1.55; }
.quiz-num  { color: var(--brand); font-size: 12px; font-weight: 700; display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: .8px; }

/* ── COLOR PREVIEW ── */
.clr-prev { border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-md); }

/* ── SEARCH RESULT ── */
.sr       { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 13px 16px; margin-bottom: 8px; background: var(--white); transition: all .15s; box-shadow: var(--shadow-sm); }
.sr:hover { border-color: var(--brand); background: var(--brand-light); }
.sr-nm    { font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 600; color: var(--brand); }
.sr-ds    { font-size: 12px; color: var(--text-2); margin-top: 2px; }

/* ── BADGES ── */
.badge      { display: inline-block; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: .5px; }
.badge-init { background: #d1fae5; color: #065f46; }
.badge-mid  { background: #fef3c7; color: #92400e; }
.badge-adv  { background: #fee2e2; color: #991b1b; }
.badge-new  { background: #e0f2fe; color: #075985; }

/* ── INFO BOX ── */
.ib         { border-radius: var(--radius-md); padding: 13px 16px; margin: 14px 0; font-size: 13px; line-height: 1.65; border-left: 4px solid; }
.ib-info    { background: #eff6ff; border-color: var(--brand);   color: #1e40af; }
.ib-success { background: #f0fdf4; border-color: var(--success); color: #14532d; }
.ib-warn    { background: #fffbeb; border-color: var(--warn);    color: #78350f; }
.ib-danger  { background: #fef2f2; border-color: var(--danger);  color: #7f1d1d; }

/* ── SIDEBAR BRAND ── */
.sb-brand     { padding: 22px 18px 18px; border-bottom: 1px solid rgba(255,255,255,.07); margin-bottom: 6px; }
.sb-logo      { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.sb-logo-box  { width: 34px; height: 34px; background: linear-gradient(135deg,#0078d4,#60a5fa); border-radius: 9px; display: flex; align-items: center; justify-content: center; font-size: 16px; }
.sb-logo-text { font-size: 15px; font-weight: 800; color: #f1f5f9; }
.sb-logo-sub  { font-size: 11px; color: #64748b; }
.sb-sec-lbl   { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #475569; padding: 12px 18px 6px; }
.sb-divider   { height: 1px; background: rgba(255,255,255,.06); margin: 8px 0; }
.sb-prog-wrap { padding: 12px 18px 18px; }
.sb-user-chip { margin: 0 10px 8px; background: rgba(255,255,255,.05); border-radius: var(--radius-md); padding: 10px 12px; display: flex; align-items: center; gap: 10px; }
.sb-user-av   { width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg,#0078d4,#60a5fa); display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; color: white; flex-shrink: 0; }
.sb-user-name { font-size: 13px; font-weight: 600; color: #e2e8f0; }
.sb-user-email{ font-size: 11px; color: #64748b; }

/* ── QUIZ SECTION (per-page) ── */
.sq-header { background: linear-gradient(135deg,#0f172a,#1e293b); border-radius: 16px; padding: 20px 24px; margin: 28px 0 20px; }
.sq-title  { font-size: 16px; font-weight: 800; color: white; margin-bottom: 4px; }
.sq-sub    { font-size: 13px; color: #94a3b8; }

/* ── APP BACKGROUND ── */
/* Só o container raiz recebe cor; todo o resto fica transparente para evitar camadas visíveis */
.stApp                               { background: #f8fafc !important; }
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
.block-container                     { background: transparent !important; }

/* Login styles são injetados dentro de page_login() e sobrescrevem o acima */

/* Left side features */
.lf-row        { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 20px; }
.lf-icon-box   { width: 44px; height: 44px; border-radius: 13px; background: linear-gradient(135deg, rgba(0,120,212,.25), rgba(96,165,250,.15)); display: flex; align-items: center; justify-content: center; font-size: 21px; flex-shrink: 0; border: 1px solid rgba(96,165,250,.25); backdrop-filter: blur(4px); }
.lf-text-title { font-size: 14px; font-weight: 700; color: white; margin-bottom: 3px; }
.lf-text-desc  { font-size: 12px; color: #94a3b8; line-height: 1.55; }
.lf-highlight  { color: #60a5fa; }

/* ── MAIN CONTENT ── */
.main-wrap { padding: 8px 12px 56px; max-width: 1080px; }

/* Animated live dot */
@keyframes pulse-dot { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:.6; transform:scale(1.3); } }
.live-dot { display:inline-block; width:6px; height:6px; border-radius:50%; background:#10b981; animation:pulse-dot 2s infinite; margin-right:6px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 5. HELPER UI COMPONENTS
# ─────────────────────────────────────────────
HERO_BG = {
    "home":        "linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%)",
    "controles":   "linear-gradient(135deg,#3b0764,#5b21b6)",
    "formulas":    "linear-gradient(135deg,#064e3b,#065f46)",
    "navegacao":   "linear-gradient(135deg,#14532d,#15803d)",
    "validacao":   "linear-gradient(135deg,#7f1d1d,#b91c1c)",
    "performance": "linear-gradient(135deg,#451a03,#92400e)",
    "seguranca":   "linear-gradient(135deg,#500724,#9d174d)",
    "conectores":  "linear-gradient(135deg,#0c2344,#1e40af)",
    "variaveis":   "linear-gradient(135deg,#1c3828,#166534)",
    "cheatsheet":  "linear-gradient(135deg,#0f172a,#1e3a5f)",
    "picker":      "linear-gradient(135deg,#2e1065,#6d28d9)",
    "quiz":        "linear-gradient(135deg,#450a0a,#991b1b)",
    "busca":       "linear-gradient(135deg,#0c2344,#1e40af)",
    # Power Automate
    "automate_fundamentos":  "linear-gradient(135deg,#0050d0,#1e40af)",
    "automate_expressoes":   "linear-gradient(135deg,#0c2344,#0050d0)",
    # Copilot Studio
    "copilot_topicos":       "linear-gradient(135deg,#5c2d91,#7c3aed)",
    "copilot_entidades":     "linear-gradient(135deg,#3b0764,#6d28d9)",
    # Dataverse
    "dataverse_tabelas":     "linear-gradient(135deg,#134e4a,#0d9488)",
    "dataverse_seguranca":   "linear-gradient(135deg,#14532d,#059669)",
    "automate_conectores":   "linear-gradient(135deg,#0c2344,#0050d0)",
    "automate_aprovacoes":   "linear-gradient(135deg,#1a1a2e,#3b0764)",
    "automate_erros":        "linear-gradient(135deg,#450a0a,#7f1d1d)",
    "copilot_ia":            "linear-gradient(135deg,#1a1a2e,#5c2d91)",
    "copilot_integracao":    "linear-gradient(135deg,#0c2344,#5c2d91)",
    "dataverse_formulas":    "linear-gradient(135deg,#052e16,#14532d)",
    "dataverse_apps":        "linear-gradient(135deg,#0c2344,#134e4a)",
}
DIFF = {
    "Iniciante":     ("badge-init", "Iniciante"),
    "Intermediário": ("badge-mid",  "Intermediário"),
    "Avançado":      ("badge-adv",  "Avançado"),
}

def hero(page: str, icon: str, title: str, desc: str, diff: str = "Iniciante"):
    bg = HERO_BG.get(page, HERO_BG["home"])
    bc, bl = DIFF.get(diff, DIFF["Iniciante"])
    st.markdown(f"""
    <div style="background:{bg};border-radius:16px;padding:32px 36px 28px;
                margin-bottom:26px;position:relative;overflow:hidden;">
        <div style="position:absolute;top:-60px;right:-60px;width:220px;height:220px;
                    background:rgba(255,255,255,.04);border-radius:50%;"></div>
        <div style="position:absolute;bottom:-40px;right:120px;width:140px;height:140px;
                    background:rgba(255,255,255,.03);border-radius:50%;"></div>
        <div style="font-size:36px;margin-bottom:10px;line-height:1;">{icon}</div>
        <div style="font-size:24px;font-weight:800;color:white;margin-bottom:8px;
                    letter-spacing:-.02em;line-height:1.2;">{title}</div>
        <div style="font-size:14px;color:rgba(255,255,255,.7);max-width:540px;
                    line-height:1.65;margin-bottom:14px;">{desc}</div>
        <span class="badge {bc}">{bl}</span>
    </div>
    """, unsafe_allow_html=True)

def breadcrumb(section: str, page: str):
    st.markdown(f'<div class="bc">Power Apps Training <span style="opacity:.4">›</span> {section} <span style="opacity:.4">›</span> <span class="cur">{page}</span></div>', unsafe_allow_html=True)

def lab_header(title: str, sub: str = ""):
    s = f'<div class="lab-hdr-sub">{sub}</div>' if sub else ""
    st.markdown(f'<div class="lab-hdr"><div><div class="lab-hdr-title">{title}</div>{s}</div></div>', unsafe_allow_html=True)

def col_label(text: str):
    st.markdown(f'<div class="lab-col-lbl">{text}</div>', unsafe_allow_html=True)

def info_box(text: str, kind: str = "info"):
    cls = {"info":"ib-info","success":"ib-success","warning":"ib-warn","danger":"ib-danger"}.get(kind,"ib-info")
    st.markdown(f'<div class="ib {cls}">{text}</div>', unsafe_allow_html=True)

def formula_card(name, desc, when, example, deleg=None, color="#0078d4", tags=None):
    dtag = f'<span class="fcard-tag">{deleg}</span>' if deleg else ""
    taghtml = " ".join(f'<span style="font-size:10px;background:rgba(255,255,255,.15);color:white;padding:2px 8px;border-radius:10px;font-weight:600">{t}</span>' for t in (tags or []))
    st.markdown(f"""<div class="fcard">
        <div class="fcard-header" style="background:{color}">
            <div>
                <span class="fcard-name">{name}</span>
                <div style="margin-top:4px">{taghtml}</div>
            </div>{dtag}
        </div>
        <div class="fcard-body">
            <div class="fcard-lbl">Descrição</div><div class="fcard-txt">{desc}</div>
            <div class="fcard-lbl">Quando usar</div><div class="fcard-txt">{when}</div>
        </div>
    </div>""", unsafe_allow_html=True)
    st.code(example, language="powerapps")

def sp(n=1):
    st.markdown("<div style='height:8px'></div>" * n, unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 6. COLOR TOOL HELPERS
# ─────────────────────────────────────────────
HEX_RE = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

def hex_to_rgba(h):
    if not HEX_RE.match(h): raise ValueError("Hex inválido.")
    h = h.lower()
    r,g,b = int(h[1:3],16), int(h[3:5],16), int(h[5:7],16)
    a = int(h[7:9],16)/255.0 if len(h)==9 else 1.0
    return r,g,b,a

def rgba_to_hex(r,g,b,a,with_alpha=True):
    r,g,b = max(0,min(255,int(r))), max(0,min(255,int(g))), max(0,min(255,int(b)))
    a = max(0.0,min(1.0,float(a)))
    return f"#{r:02x}{g:02x}{b:02x}{int(round(a*255)):02x}" if with_alpha else f"#{r:02x}{g:02x}{b:02x}"

def rgb_to_hsl(r,g,b):
    h,l,s = colorsys.rgb_to_hls(r/255,g/255,b/255)
    return h*360,s,l

def rgb_to_hsv(r,g,b):
    h,s,v = colorsys.rgb_to_hsv(r/255,g/255,b/255)
    return h*360,s,v

def hsv_to_rgb(h,s,v):
    r,g,b = colorsys.hsv_to_rgb(h/360,s,v)
    return int(round(r*255)), int(round(g*255)), int(round(b*255))

def format_rgba(r,g,b,a): return f"rgba({r},{g},{b},{a:.1f})"
def format_rgb(r,g,b):    return f"rgb({r},{g},{b})"
def format_hsl(h,s,l,a=None):
    return f"hsla({h:.1f},{s*100:.1f}%,{l*100:.1f}%,{a:.1f})" if a is not None else f"hsl({h:.1f},{s*100:.1f}%,{l*100:.1f}%)"
def format_hsv(h,s,v): return f"hsv({h:.1f},{s*100:.1f}%,{v*100:.1f}%)"

def color_preview(r,g,b,a,h=120):
    checker = "background-image:linear-gradient(45deg,#ccc 25%,transparent 25%),linear-gradient(-45deg,#ccc 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#ccc 75%),linear-gradient(-45deg,transparent 75%,#ccc 75%);background-size:16px 16px;background-position:0 0,0 8px,8px -8px,-8px 0;"
    st.markdown(f'<div class="clr-prev" style="height:{h}px;position:relative;{checker}"><div style="position:absolute;inset:0;background:rgba({r},{g},{b},{a:.3f});"></div></div>', unsafe_allow_html=True)

def color_codes(r,g,b,a,pfx="c"):
    h_hsl,s_hsl,l_hsl = rgb_to_hsl(r,g,b)
    h_hsv,s_hsv,v_hsv = rgb_to_hsv(r,g,b)
    c1,c2 = st.columns(2)
    with c1:
        st.caption("HEX");        st.code(rgba_to_hex(r,g,b,a,False))
        st.caption("HSL");        st.code(format_hsl(h_hsl,s_hsl,l_hsl))
        st.caption("RGB");        st.code(format_rgb(r,g,b))
    with c2:
        st.caption("HEX + Alpha"); st.code(rgba_to_hex(r,g,b,a,True))
        st.caption("RGBA");        st.code(format_rgba(r,g,b,a))
        st.caption("Power Apps");  st.code(f"RGBA({r},{g},{b},{a:.1f})", language="powerapps")

# ─────────────────────────────────────────────
# 7. QUIZ DATA — 35 QUESTIONS
# ─────────────────────────────────────────────
ALL_QUESTIONS = [
    # ── DADOS ──
    {"id":0,"cat":"Dados","q":"Qual fórmula cria ou edita um registro diretamente na fonte de dados?",
     "opts":["Collect()","Patch()","Set()","Navigate()"],"ans":1,
     "exp":"**Patch()** cria ou edita registros na fonte. Collect() adiciona apenas em coleções locais."},
    {"id":1,"cat":"Dados","q":"Como remover TODOS os registros com Status = 'Inativo' de uma vez?",
     "opts":["Remove(Tabela, Filter(Tabela, Status='Inativo'))","RemoveIf(Tabela, Status='Inativo')","Delete(Tabela, Status='Inativo')","ClearIf(Tabela, Status='Inativo')"],"ans":1,
     "exp":"**RemoveIf()** remove todos os registros que atendem à condição."},
    {"id":2,"cat":"Dados","q":"O que ClearCollect() faz diferente de Collect()?",
     "opts":["São idênticos","ClearCollect() limpa a coleção antes de adicionar","ClearCollect() é mais rápido","Collect() limpa, ClearCollect() adiciona"],"ans":1,
     "exp":"**ClearCollect()** zera a coleção e a repopula. Collect() apenas adiciona."},
    {"id":3,"cat":"Dados","q":"Qual fórmula retorna APENAS O PRIMEIRO registro que atende a uma condição?",
     "opts":["Filter()","Search()","LookUp()","First(Filter(...))"],"ans":2,
     "exp":"**LookUp()** retorna exatamente um registro — o primeiro que satisfaz a condição."},
    {"id":4,"cat":"Dados","q":"AddColumns() é delegável no SharePoint?",
     "opts":["Sim, sempre","Sim, mas apenas leitura","Não, nunca é delegável","Depende da coluna"],"ans":2,
     "exp":"**AddColumns() nunca é delegável.** Processa localmente os dados já carregados."},
    {"id":5,"cat":"Dados","q":"Como ordenar uma Gallery do mais recente para o mais antigo?",
     "opts":["Sort(Lista, Data)","SortByColumns(Lista, 'Data', Descending)","OrderBy(Lista, Data, Desc)","Filter(Lista) ordenado por default"],"ans":1,
     "exp":"**SortByColumns()** é a forma delegável de ordenar."},
    {"id":6,"cat":"Dados","q":"Qual fórmula calcula a SOMA de uma coluna em uma tabela?",
     "opts":["Total(Pedidos, Valor)","Sum(Pedidos, Valor)","Calculate(Pedidos, Valor)","Aggregate(Pedidos, Valor)"],"ans":1,
     "exp":"**Sum(Tabela, Coluna)** retorna a soma. É delegável no SharePoint."},
    {"id":7,"cat":"Dados","q":"O que Distinct() retorna?",
     "opts":["Registros sem duplicatas (tabela completa)","Valores únicos de uma coluna específica","O primeiro registro de cada grupo","Tabela ordenada sem repetições"],"ans":1,
     "exp":"**Distinct(Tabela, Coluna)** retorna valores únicos — perfeito para Dropdowns com categorias."},
    # ── FILTER / SEARCH ──
    {"id":8,"cat":"Filter/Search","q":"Qual a diferença principal entre Filter() e Search()?",
     "opts":["Filter() é mais rápido que Search()","Search() é para critérios lógicos; Filter() para texto livre","Filter() aceita critérios lógicos; Search() faz busca de texto livre","São idênticos, apenas sintaxe diferente"],"ans":2,
     "exp":"**Filter()** aceita condições lógicas. **Search()** faz busca de texto em colunas."},
    {"id":9,"cat":"Filter/Search","q":"Como combinar Filter() e Search() na mesma fórmula?",
     "opts":["Não é possível combinar","Filter(Search(Tabela, busca, 'col'), condicao)","Search(Filter(Tabela, cond), busca, 'col') apenas","UseFilterSearch(Tabela, busca, cond)"],"ans":1,
     "exp":"O correto é **Filter(Search(...), condição)** — busca texto primeiro, depois aplica filtro lógico."},
    {"id":10,"cat":"Filter/Search","q":"StartsWith() é delegável no SharePoint?",
     "opts":["Não, nunca","Sim, é delegável","Só com Dataverse","Depende do tipo de coluna"],"ans":1,
     "exp":"**StartsWith()** é delegável no SharePoint."},
    # ── VARIÁVEIS ──
    {"id":11,"cat":"Variáveis","q":"Qual é a diferença entre Set() e UpdateContext()?",
     "opts":["Não há diferença","Set() cria variável global (todas as telas); UpdateContext() é local (tela atual)","UpdateContext() cria variável global; Set() é local","UpdateContext() persiste após fechar o app"],"ans":1,
     "exp":"**Set()** cria variável global. **UpdateContext()** é local à tela atual."},
    {"id":12,"cat":"Variáveis","q":"Como atualizar MÚLTIPLAS variáveis locais de uma vez?",
     "opts":["Set({var1: val1, var2: val2})","UpdateContext({var1: val1, var2: val2})","Não é possível — deve ser um a um","SetContext(var1: val1); SetContext(var2: val2)"],"ans":1,
     "exp":"**UpdateContext()** aceita um objeto com múltiplas chaves, atualizando todas de uma vez."},
    {"id":13,"cat":"Variáveis","q":"Qual é o PREFIXO recomendado por convenção para variáveis globais?",
     "opts":["var_","global_","gbl","_global"],"ans":2,
     "exp":"Por convenção da Microsoft, use **gbl** para variáveis globais, **loc** para locais, **col** para coleções."},
    {"id":14,"cat":"Variáveis","q":"Collections são delegáveis quando usadas com Filter()?",
     "opts":["Sim, sempre delegáveis","Não — coleções estão na memória local, não há delegação","Depende do conector de origem","Sim, se criadas com ClearCollect()"],"ans":1,
     "exp":"**Collections são locais.** Filter() em uma collection processa localmente."},
    # ── NAVEGAÇÃO ──
    {"id":15,"cat":"Navegação","q":"Como passar dados de uma tela para outra no Navigate()?",
     "opts":["Não é possível passar dados","Terceiro parâmetro do Navigate(): Navigate(Tela, Transition, {chave: valor})","Apenas via variáveis globais Set()","Adicionando parâmetros na URL da tela"],"ans":1,
     "exp":"**Navigate()** aceita um objeto de contexto como terceiro parâmetro."},
    {"id":16,"cat":"Navegação","q":"Qual transição é recomendada para máxima PERFORMANCE?",
     "opts":["ScreenTransition.Fade","ScreenTransition.Cover","ScreenTransition.None","ScreenTransition.Slide"],"ans":2,
     "exp":"**ScreenTransition.None** não renderiza animação — a navegação é instantânea."},
    {"id":17,"cat":"Navegação","q":"O que faz Back() se não há histórico de navegação?",
     "opts":["Fecha o aplicativo","Vai para a primeira tela","Não faz nada (sem efeito)","Exibe um erro"],"ans":0,
     "exp":"Se não há tela anterior, **Back() fecha o aplicativo**."},
    # ── VALIDAÇÃO ──
    {"id":18,"cat":"Validação","q":"Qual fórmula exibe uma notificação banner para o usuário?",
     "opts":["Alert()","Notify()","ShowMessage()","Toast()"],"ans":1,
     "exp":"**Notify()** exibe um banner nativo com NotificationType.Success/Error/Warning/Information."},
    {"id":19,"cat":"Validação","q":"Qual a diferença entre IsBlank() e IsEmpty()?",
     "opts":["São idênticos","IsBlank() para valores; IsEmpty() para tabelas e coleções sem registros","IsEmpty() para valores; IsBlank() para tabelas","IsBlank() verifica null; IsEmpty() verifica string vazia"],"ans":1,
     "exp":"**IsBlank()** verifica valores nulos/vazios. **IsEmpty()** verifica se tabela não tem registros."},
    {"id":20,"cat":"Validação","q":"Como validar formato de e-mail com IsMatch()?",
     "opts":["IsMatch(Email.Text, 'email')","IsMatch(Email.Text, Match.Email)","ValidateEmail(Email.Text)","IsEmail(Email.Text)"],"ans":1,
     "exp":"**IsMatch(valor, Match.Email)** usa o padrão built-in do Power Apps para e-mail."},
    {"id":21,"cat":"Validação","q":"Onde é a melhor prática para colocar a lógica de validação?",
     "opts":["No OnChange de cada campo","No OnVisible da tela","No OnSelect do botão Salvar","Nas propriedades de cada controle"],"ans":2,
     "exp":"A **melhor prática** é validar no **OnSelect do botão Salvar** com If() encadeado."},
    # ── PERFORMANCE ──
    {"id":22,"cat":"Performance","q":"Qual é o limite padrão de delegação no SharePoint?",
     "opts":["500 registros","1.000 registros","2.000 registros","5.000 registros"],"ans":2,
     "exp":"O SharePoint retorna no máximo **2.000 registros** (configurável em App.DataRowLimit)."},
    {"id":23,"cat":"Performance","q":"Concurrent() é usado para quê?",
     "opts":["Executar fórmulas em sequência garantida","Executar múltiplas fórmulas em paralelo, reduzindo tempo de carga","Executar fórmulas assíncronas com callback","Bloquear a UI durante operações longas"],"ans":1,
     "exp":"**Concurrent()** executa fórmulas em paralelo — essencial para o OnStart do App."},
    {"id":24,"cat":"Performance","q":"ForAll() tem delegação no SharePoint?",
     "opts":["Sim, sempre","Sim, para operações de leitura","Não, nunca tem delegação","Depende dos dados"],"ans":2,
     "exp":"**ForAll() nunca é delegável.** Para operações em lote, considere Power Automate."},
    {"id":25,"cat":"Performance","q":"Qual é o melhor lugar para carregar dados pesados de uma vez?",
     "opts":["OnVisible da primeira tela","App.OnStart com Concurrent()","No OnSelect de um botão 'Carregar'","Lazy loading em cada tela"],"ans":1,
     "exp":"**App.OnStart** com **Concurrent()** carrega tudo em paralelo uma única vez."},
    # ── SEGURANÇA ──
    {"id":26,"cat":"Segurança","q":"Como obter o e-mail do usuário logado?",
     "opts":["CurrentUser.Email","Office365Users.MyProfile().Mail","User().Email","LoggedUser()"],"ans":2,
     "exp":"**User().Email** é a função nativa mais simples e não requer conector."},
    {"id":27,"cat":"Segurança","q":"Como exibir um botão apenas para administradores?",
     "opts":["btnAdmin.Disabled = true","btnAdmin.Visible = gblPerfil.Cargo = 'Admin'","If(Admin, Show(btnAdmin))","btnAdmin.Hidden = !IsAdmin()"],"ans":1,
     "exp":"Use a propriedade **Visible** com condição: `btnAdmin.Visible = gblPerfil.NivelAcesso = \"Admin\"`."},
    {"id":28,"cat":"Segurança","q":"Qual conector permite buscar usuários do diretório corporativo (AD)?",
     "opts":["SharePoint Users","Office 365 Users","Azure Active Directory (Premium)","Microsoft Graph"],"ans":1,
     "exp":"**Office 365 Users** é Standard (gratuito no M365) e permite buscar usuários do AD."},
    # ── CONECTORES ──
    {"id":29,"cat":"Conectores","q":"Qual conector é RECOMENDADO como banco de dados oficial da Power Platform?",
     "opts":["SharePoint Online","Excel no OneDrive","Microsoft Dataverse","SQL Server local"],"ans":2,
     "exp":"**Microsoft Dataverse** é o banco nativo da Power Platform: relacional, ALM, delegação total."},
    {"id":30,"cat":"Conectores","q":"Usar Excel no OneDrive como banco de dados em produção é recomendado?",
     "opts":["Sim, é a opção mais simples","Sim, para apps com menos de 500 registros","Não — é instável, sem delegação e propenso a corrupção","Sim, se combinado com Power Automate"],"ans":2,
     "exp":"**Nunca use Excel como banco em produção.** É instável, sem delegação, propenso a conflitos."},
    {"id":31,"cat":"Conectores","q":"O conector HTTP requer qual tipo de licença?",
     "opts":["Standard — incluído no M365","Premium — Per App ou Per User","Depende do endpoint","Gratuito para qualquer usuário"],"ans":1,
     "exp":"**HTTP é Premium** — requer licença Per App ou Per User."},
    # ── CONTROLES ──
    {"id":32,"cat":"Controles","q":"Qual controle é mais adequado para exibir uma lista de registros repetidos com template personalizado?",
     "opts":["DataTable","Gallery","Dropdown","ListBox"],"ans":1,
     "exp":"**Gallery** é o controle principal para listas repetidas com template totalmente personalizado."},
    {"id":33,"cat":"Controles","q":"Como limitar um TextInput a 100 caracteres?",
     "opts":["TextInput1.MaxChars = 100","TextInput1.MaxLength = 100","TextInput1.Limit = 100","Não é possível nativamente"],"ans":1,
     "exp":"A propriedade **MaxLength** do TextInput limita o número de caracteres que o usuário pode digitar."},
    {"id":34,"cat":"Controles","q":"Como habilitar/desabilitar um botão com base no preenchimento de campos?",
     "opts":["Button1.Enabled = true/false","Button1.DisplayMode = If(condicao, DisplayMode.Edit, DisplayMode.Disabled)","Button1.Active = IsBlank(campo)","If(IsBlank(campo), Hide(Button1))"],"ans":1,
     "exp":"Use **DisplayMode**: `If(!IsBlank(Campo.Text), DisplayMode.Edit, DisplayMode.Disabled)`."},
]

N_QUIZ_SESSION = 12  # questões por sessão global

def init_quiz_session():
    if st.session_state.quiz_session is None:
        indices = list(range(len(ALL_QUESTIONS)))
        random.shuffle(indices)
        st.session_state.quiz_session = indices[:N_QUIZ_SESSION]
        st.session_state.quiz_session_answers = {}

# ─────────────────────────────────────────────
# 8. CHEAT SHEET DATA
# ─────────────────────────────────────────────
FORMULAS = [
    {"nome":"Filter()",        "cat":"Dados",   "desc":"Filtra registros de uma fonte de dados.",              "deleg":"✅",  "ex":"Filter(Vendas, Regiao = \"Sul\" && Ativo = true)"},
    {"nome":"Search()",        "cat":"Dados",   "desc":"Busca texto livre em colunas de texto.",               "deleg":"✅",  "ex":"Search(Clientes, BuscaInput.Text, \"Nome\", \"Email\")"},
    {"nome":"Patch()",         "cat":"Dados",   "desc":"Cria ou edita um registro na fonte de dados.",         "deleg":"✅",  "ex":"Patch(Func_TB, Defaults(Func_TB), {Nome: inp.Text})"},
    {"nome":"Collect()",       "cat":"Dados",   "desc":"Adiciona itens a uma coleção local.",                  "deleg":"❌",  "ex":"Collect(colCarrinho, {Prod: drp.Selected.Value, Qtd: 1})"},
    {"nome":"ClearCollect()",  "cat":"Dados",   "desc":"Limpa e repopula uma coleção.",                        "deleg":"❌",  "ex":"ClearCollect(colDados, Filter(Tabela, Ativo = true))"},
    {"nome":"Remove()",        "cat":"Dados",   "desc":"Remove um registro específico.",                       "deleg":"✅",  "ex":"Remove(Tarefas_TB, Gallery1.Selected)"},
    {"nome":"RemoveIf()",      "cat":"Dados",   "desc":"Remove registros que atendem a uma condição.",         "deleg":"⚠️", "ex":"RemoveIf(colLista, Status = \"Concluído\")"},
    {"nome":"ForAll()",        "cat":"Dados",   "desc":"Executa uma fórmula para cada registro.",              "deleg":"❌",  "ex":"ForAll(colSel, Patch(TB, ThisRecord, {Ativo: false}))"},
    {"nome":"AddColumns()",    "cat":"Dados",   "desc":"Retorna tabela com colunas calculadas extras.",        "deleg":"❌",  "ex":"AddColumns(Pedidos, \"Total\", Qtd * Preco)"},
    {"nome":"SortByColumns()", "cat":"Dados",   "desc":"Ordena tabela por uma ou mais colunas.",               "deleg":"✅",  "ex":"SortByColumns(Produtos, \"Nome\", Ascending)"},
    {"nome":"Distinct()",      "cat":"Dados",   "desc":"Retorna valores únicos de uma coluna.",                "deleg":"⚠️", "ex":"Distinct(Funcionarios, Departamento)"},
    {"nome":"LookUp()",        "cat":"Dados",   "desc":"Retorna o primeiro registro que atende a condição.",   "deleg":"✅",  "ex":"LookUp(Clientes, Email = User().Email)"},
    {"nome":"CountRows()",     "cat":"Dados",   "desc":"Conta registros de uma tabela.",                       "deleg":"✅",  "ex":"CountRows(Filter(Tarefas, Concluida = true))"},
    {"nome":"Sum()/Avg()",     "cat":"Dados",   "desc":"Soma ou média de uma coluna.",                         "deleg":"✅",  "ex":"Sum(Pedidos, ValorTotal) | Average(Notas, Valor)"},
    {"nome":"Max()/Min()",     "cat":"Dados",   "desc":"Maior ou menor valor de uma coluna.",                  "deleg":"✅",  "ex":"Max(Vendas, ValorVenda) | Min(Estoque, Quantidade)"},
    {"nome":"If()",            "cat":"Lógica",  "desc":"Condição simples se/então/senão.",                     "deleg":"N/A", "ex":"If(IsBlank(Input.Text), \"Vazio\", \"Preenchido\")"},
    {"nome":"Switch()",        "cat":"Lógica",  "desc":"Condição múltipla (como select/case).",                "deleg":"N/A", "ex":"Switch(drp.Selected.Value, \"A\", 10, \"B\", 20, 0)"},
    {"nome":"IsBlank()",       "cat":"Lógica",  "desc":"Verifica se valor é vazio ou nulo.",                   "deleg":"N/A", "ex":"IsBlank(TextInput1.Text)"},
    {"nome":"IsEmpty()",       "cat":"Lógica",  "desc":"Verifica se tabela/coleção está vazia.",               "deleg":"N/A", "ex":"IsEmpty(Filter(Pedidos, Status = \"Aberto\"))"},
    {"nome":"IsMatch()",       "cat":"Lógica",  "desc":"Verifica se texto segue um padrão/regex.",             "deleg":"N/A", "ex":"IsMatch(Email.Text, Match.Email)"},
    {"nome":"And() / &&",      "cat":"Lógica",  "desc":"Operador lógico E.",                                   "deleg":"N/A", "ex":"If(!IsBlank(A.Text) && !IsBlank(B.Text), true, false)"},
    {"nome":"Or() / ||",       "cat":"Lógica",  "desc":"Operador lógico OU.",                                  "deleg":"N/A", "ex":"If(A = \"X\" || A = \"Y\", DoThis, DoThat)"},
    {"nome":"Navigate()",      "cat":"Nav.",    "desc":"Navega para outra tela.",                              "deleg":"N/A", "ex":"Navigate(Tela2, ScreenTransition.Fade, {rec: ThisItem})"},
    {"nome":"Back()",          "cat":"Nav.",    "desc":"Volta para a tela anterior.",                          "deleg":"N/A", "ex":"Back()"},
    {"nome":"Launch()",        "cat":"Nav.",    "desc":"Abre URL externa ou outro aplicativo.",                 "deleg":"N/A", "ex":"Launch(\"https://teams.microsoft.com/...\")"},
    {"nome":"Set()",           "cat":"Vars",    "desc":"Define variável global acessível em todas as telas.",  "deleg":"N/A", "ex":"Set(gblUser, LookUp(Perfis, Email = User().Email))"},
    {"nome":"UpdateContext()", "cat":"Vars",    "desc":"Define variável local somente na tela atual.",         "deleg":"N/A", "ex":"UpdateContext({locPopup: !locPopup, locCarreg: false})"},
    {"nome":"Notify()",        "cat":"UI",      "desc":"Exibe banner de notificação.",                         "deleg":"N/A", "ex":"Notify(\"Salvo!\", NotificationType.Success, 3000)"},
    {"nome":"Reset()",         "cat":"UI",      "desc":"Redefine controle ao valor padrão.",                   "deleg":"N/A", "ex":"Reset(TextInput_Nome); Reset(TextInput_Email)"},
    {"nome":"SetFocus()",      "cat":"UI",      "desc":"Move o foco para um controle.",                        "deleg":"N/A", "ex":"SetFocus(TextInput_Busca)"},
    {"nome":"Concurrent()",    "cat":"UI",      "desc":"Executa múltiplas fórmulas em paralelo.",              "deleg":"N/A", "ex":"Concurrent(ClearCollect(colA, TbA), Set(gblX, LookUp(...)))"},
    {"nome":"Concatenate()/&", "cat":"Texto",   "desc":"Une strings.",                                         "deleg":"N/A", "ex":"\"Olá, \" & User().FullName & \"!\""},
    {"nome":"Text()",          "cat":"Texto",   "desc":"Formata número ou data como texto.",                   "deleg":"N/A", "ex":"Text(Now(), \"dd/mm/yyyy hh:mm\")"},
    {"nome":"Value()",         "cat":"Texto",   "desc":"Converte texto em número.",                            "deleg":"N/A", "ex":"Value(TextInput_Preco.Text)"},
    {"nome":"Len()",           "cat":"Texto",   "desc":"Comprimento de um texto.",                             "deleg":"N/A", "ex":"If(Len(Campo.Text) < 3, \"Mínimo 3 chars\", \"\")"},
    {"nome":"Upper()/Lower()", "cat":"Texto",   "desc":"Maiúsculo ou minúsculo.",                              "deleg":"✅",  "ex":"Upper(inp.Text) | Lower(Email.Text) | Proper(Nome.Text)"},
    {"nome":"DateAdd()",       "cat":"Datas",   "desc":"Adiciona unidades de tempo a uma data.",               "deleg":"N/A", "ex":"DateAdd(Today(), 30, TimeUnit.Days)"},
    {"nome":"DateDiff()",      "cat":"Datas",   "desc":"Calcula diferença entre duas datas.",                  "deleg":"N/A", "ex":"DateDiff(DataNasc.SelectedDate, Today(), TimeUnit.Years)"},
    {"nome":"Today()/Now()",   "cat":"Datas",   "desc":"Data atual / Data e hora atuais.",                     "deleg":"N/A", "ex":"Today() | Now() | Patch(TB, Defaults(TB), {Criado: Now()})"},
    {"nome":"Round()",         "cat":"Números", "desc":"Arredonda número para N casas decimais.",              "deleg":"N/A", "ex":"Round(12.567, 2)  // → 12.57"},
    {"nome":"User()",          "cat":"Segur.",  "desc":"Retorna info do usuário logado.",                      "deleg":"N/A", "ex":"User().Email | User().FullName | User().Image"},
]

# ─────────────────────────────────────────────
# 9. SECTION QUIZ — quiz no fim de cada painel
# ─────────────────────────────────────────────
PAGE_QUIZ_CATS = {
    "controles":   ["Controles"],
    "formulas":    ["Dados", "Filter/Search"],
    "navegacao":   ["Navegação"],
    "validacao":   ["Validação"],
    "performance": ["Performance"],
    "seguranca":   ["Segurança"],
    "conectores":  ["Conectores"],
    "variaveis":   ["Variáveis"],
    # Power Automate
    "automate_fundamentos":  ["Automate-Fundamentos"],
    "automate_expressoes":   ["Automate-Expressões"],
    # Copilot Studio
    "copilot_topicos":       ["Copilot-Tópicos"],
    "copilot_entidades":     ["Copilot-Entidades"],
    # Dataverse
    "dataverse_tabelas":     ["Dataverse-Tabelas"],
    "dataverse_seguranca":   ["Dataverse-Segurança"],
    # Extra Automate pages
    "automate_conectores":   ["Automate-Conectores"],
    "automate_aprovacoes":   ["Automate-Aprovações"],
    "automate_erros":        ["Automate-Erros"],
    # Extra Copilot pages
    "copilot_ia":            ["Copilot-IA"],
    "copilot_integracao":    ["Copilot-Integração"],
    # Extra Dataverse pages
    "dataverse_formulas":    ["Dataverse-Fórmulas"],
    "dataverse_apps":        ["Dataverse-Apps"],
}
N_SECTION_QUIZ = 5  # máx de questões por quiz de seção

CAT_COLORS = {
    "Dados":"#065f46","Filter/Search":"#065f46","Variáveis":"#1e3a5f",
    "Navegação":"#14532d","Validação":"#7f1d1d","Performance":"#92400e",
    "Segurança":"#500724","Conectores":"#1e3a5f","Controles":"#3b0764"
}

def section_quiz(page_key: str):
    """
    Renderiza quiz de seção ao final de uma página.
    Marca progresso apenas se aprovado (≥80%).
    """
    u = current_user()
    if not u:
        return
    user_id = u["id"]
    visited = get_visited(user_id)
    already_passed = page_key in visited

    cats = PAGE_QUIZ_CATS.get(page_key, [])
    pool = [q for q in ALL_QUESTIONS if q["cat"] in cats]
    n = min(N_SECTION_QUIZ, len(pool))
    if n == 0:
        return

    threshold = max(1, math.ceil(n * 0.8))

    st.divider()

    if already_passed:
        st.markdown(f"""
        <div class="sq-header">
            <div class="sq-title">📝 Quiz desta seção</div>
            <div class="sq-sub">
                ✅ <span style="color:#4ade80;font-weight:700">Seção concluída!</span>
                Você passou no quiz — progresso salvo.
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    st.markdown(f"""
    <div class="sq-header">
        <div class="sq-title">📝 Quiz desta seção</div>
        <div class="sq-sub">
            Responda as questões abaixo e acerte
            <span style="color:#60a5fa;font-weight:700">{threshold}/{n}</span>
            para marcar esta seção como ✅ concluída
        </div>
    </div>
    """, unsafe_allow_html=True)

    sq_key = f"sq_{page_key}"
    if sq_key not in st.session_state:
        selected = random.sample(pool, n)
        st.session_state[sq_key] = {
            "questions": selected,
            "answers":   {},
            "submitted": False,
            "passed":    False,
            "score":     0,
        }

    sq = st.session_state[sq_key]
    questions = sq["questions"]

    if sq["submitted"]:
        score = sq["score"]
        pct = int(score / n * 100)
        if sq["passed"]:
            st.success(f"🎉 **Aprovado!** {score}/{n} corretas ({pct}%) — Seção desbloqueada e marcada como ✅")
        else:
            st.error(f"❌ **{score}/{n}** corretas ({pct}%) — Precisa de **{threshold}/{n}** para passar.")
            if st.button("🔄 Tentar novamente", key=f"retry_{page_key}", type="primary"):
                del st.session_state[sq_key]
                st.rerun()

        for q in questions:
            user_ans = sq["answers"].get(q["id"], -1)
            st.markdown(f'<div style="font-size:14px;font-weight:700;color:#111827;margin:16px 0 8px">{q["q"]}</div>', unsafe_allow_html=True)
            for j, opt in enumerate(q["opts"]):
                if j == q["ans"]:
                    st.success(f"✅ {opt}")
                elif j == user_ans and user_ans != q["ans"]:
                    st.error(f"❌ {opt}")
                else:
                    st.markdown(f'<div style="padding:3px 0 1px 10px;font-size:13px;color:#9ca3af">◦ {opt}</div>', unsafe_allow_html=True)
            info_box(f"💡 {q['exp']}", "info")
    else:
        for i, q in enumerate(questions):
            cc = CAT_COLORS.get(q["cat"], "#1e3a5f")
            st.markdown(f"""
            <div class="quiz-card">
                <span class="quiz-num" style="background:{cc};color:white;padding:2px 9px;border-radius:10px;font-size:10px">
                    Questão {i+1} · {q['cat']}
                </span>
                <div class="quiz-q" style="margin-top:12px">{q['q']}</div>
            </div>""", unsafe_allow_html=True)
            choice = st.radio("", q["opts"], key=f"sq_{page_key}_{q['id']}", index=None, label_visibility="collapsed")
            if choice is not None:
                sq["answers"][q["id"]] = q["opts"].index(choice)

        answered_count = len(sq["answers"])
        all_answered = answered_count >= n

        st.markdown(f'<div style="font-size:12px;color:#9ca3af;margin-top:8px">{answered_count}/{n} questões respondidas</div>', unsafe_allow_html=True)

        if st.button(
            "📤 Confirmar respostas" if all_answered else f"📤 Confirmar ({answered_count}/{n})",
            key=f"submit_sq_{page_key}",
            disabled=not all_answered,
            type="primary",
            use_container_width=True
        ):
            score = sum(1 for q in questions if sq["answers"].get(q["id"]) == q["ans"])
            passed = score >= threshold
            sq["submitted"] = True
            sq["passed"] = passed
            sq["score"] = score
            st.session_state[sq_key] = sq
            if passed:
                mark_page_visited(user_id, page_key)
            st.rerun()

# ─────────────────────────────────────────────
# 10. PAGE FUNCTIONS
# ─────────────────────────────────────────────

def page_home():
    u = current_user()
    user_id = u["id"]
    visited = get_visited(user_id)
    prog    = get_progress(user_id)
    qstats  = get_quiz_stats(user_id)
    # home não precisa de quiz
    mark_page_visited(user_id, "home")

    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="background:linear-gradient(145deg,#0f172a 0%,#1e3a5f 50%,#0f172a 100%);
                border-radius:20px;padding:44px 48px 40px;margin-bottom:28px;position:relative;overflow:hidden;">
        <div style="position:absolute;top:-80px;right:-80px;width:300px;height:300px;
                    background:rgba(0,120,212,.1);border-radius:50%;"></div>
        <div style="font-size:11px;color:#60a5fa;text-transform:uppercase;letter-spacing:3px;
                    font-weight:700;margin-bottom:12px;">MICROSOFT POWER APPS</div>
        <div style="font-size:38px;font-weight:800;color:white;margin-bottom:12px;
                    letter-spacing:-.03em;line-height:1.15;">
            Treinamento Interativo<br>
            <span style="color:#60a5fa">Power FX</span>
        </div>
        <div style="font-size:15px;color:#94a3b8;max-width:520px;line-height:1.75;margin-bottom:24px;">
            Laboratórios ao vivo, fórmulas interativas e exemplos reais.
            Ajuste os controles e veja o código sendo gerado em tempo real.
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <span style="background:rgba(255,255,255,.1);color:#e2e8f0;padding:6px 16px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid rgba(255,255,255,.1);">⚡ {len(FORMULAS)}+ Fórmulas</span>
            <span style="background:rgba(255,255,255,.1);color:#e2e8f0;padding:6px 16px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid rgba(255,255,255,.1);">🎛️ 8 Controles</span>
            <span style="background:rgba(255,255,255,.1);color:#e2e8f0;padding:6px 16px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid rgba(255,255,255,.1);">🧠 {len(ALL_QUESTIONS)} Questões</span>
            <span style="background:rgba(255,255,255,.1);color:#e2e8f0;padding:6px 16px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid rgba(255,255,255,.1);">📋 Cheat Sheet</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("📚 Seções concluídas", len(visited & QUIZ_PAGES))
    c2.metric("🎯 Progresso", f"{prog}%")
    c3.metric("🧠 Acertos no quiz", qstats["correct"])
    c4.metric("⚡ Fórmulas disponíveis", len(FORMULAS))

    st.markdown(f"""
    <div style="margin:6px 0 28px;">
        <div style="font-size:11px;color:#9ca3af;font-weight:600;text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px;">Progresso do treinamento</div>
        <div class="prog-bar"><div class="prog-fill" style="width:{prog}%"></div></div>
        <div style="font-size:11px;color:#6b7280;margin-top:6px;">
            {len(visited & QUIZ_PAGES)}/{TOTAL_PAGES} seções desbloqueadas · Complete o quiz ao final de cada seção para marcar como ✅
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="font-size:18px;font-weight:800;color:#111827;letter-spacing:-.02em;margin-bottom:16px;">📘 Documentação & Laboratórios</div>', unsafe_allow_html=True)
    nav = [
        ("controles",   "🎛️", "Controles",        "TextInput, Gallery, Button, Toggle, Timer e mais.", "Iniciante",     "#e0f2fe","#075985"),
        ("formulas",    "∑",  "Fórmulas",          "Filter, Patch, ForAll, LookUp e todas as essenciais.", "Iniciante",  "#d1fae5","#065f46"),
        ("navegacao",   "🧭", "Navegação",         "Navigate(), contexto, deep link no Teams.", "Intermediário",          "#fef9c3","#854d0e"),
        ("validacao",   "✅", "Validação",          "IsBlank, IsMatch, Notify e erros visuais.", "Intermediário",         "#fee2e2","#991b1b"),
        ("performance", "⚡", "Performance",        "Delegação, limites, Concurrent() e boas práticas.", "Avançado",      "#fef3c7","#92400e"),
        ("seguranca",   "🔐", "Segurança",          "User(), perfis, grupos e controle de acesso.", "Intermediário",     "#fce7f3","#9d174d"),
        ("conectores",  "🔌", "Conectores",         "Standard e Premium com casos de uso reais.", "Iniciante",           "#ede9fe","#5b21b6"),
        ("variaveis",   "📦", "Variáveis",          "Set vs UpdateContext vs Collections.", "Iniciante",                 "#d1fae5","#065f46"),
    ]
    cols = st.columns(4)
    for i, (pg, ic, title, desc, diff, bg, tc) in enumerate(nav):
        bclass, _ = DIFF.get(diff, DIFF["Iniciante"])
        is_done = pg in visited
        badge_done = '&nbsp;&nbsp;<span style="background:#d1fae5;color:#059669;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px">✅ Concluído</span>' if is_done else ''
        with cols[i % 4]:
            st.markdown(f"""
            <div class="hnc">
                <div style="font-size:26px;margin-bottom:10px;">{ic}</div>
                <div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:5px;">{title}{badge_done}</div>
                <div style="font-size:12px;color:#6b7280;line-height:1.6;margin-bottom:10px;">{desc}</div>
                <span class="badge {bclass}">{diff}</span>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Acessar →", key=f"hn_{pg}"):
                st.session_state.page = pg; st.rerun()
            sp()

    # ── Power Automate section ──
    st.markdown('<div style="font-size:18px;font-weight:800;color:#111827;letter-spacing:-.02em;margin:28px 0 8px;">🔄 Power Automate</div><div style="font-size:13px;color:#6b7280;margin-bottom:16px">Automatize processos, conecte sistemas e crie flows de aprovação sem código.</div>', unsafe_allow_html=True)
    automate_nav = [
        ("automate_fundamentos",  "🔄","Fundamentos","Tipos de flow, triggers e ações essenciais.","Iniciante","#e0f2fe","#075985"),
        ("automate_expressoes",   "🧮","Expressões","Texto, datas, lógica e JSON.","Intermediário","#fef9c3","#854d0e"),
        ("automate_conectores",   "🔌","Conectores","SharePoint, Teams, Outlook, HTTP, SQL.","Intermediário","#ede9fe","#5b21b6"),
        ("automate_aprovacoes",   "✅","Aprovações","Sequencial, paralela, cards adaptáveis.","Avançado","#fce7f3","#9d174d"),
        ("automate_erros",        "🐛","Erros & Debug","Scope try/catch, retry, histórico.","Avançado","#fee2e2","#991b1b"),
    ]
    cols_at = st.columns(min(4, len(automate_nav)))
    for i,(pg,ic,title,desc,diff,bg,tc) in enumerate(automate_nav):
        bclass,_ = DIFF.get(diff, DIFF["Iniciante"])
        is_done = pg in visited
        badge_done = '&nbsp;&nbsp;<span style="background:#d1fae5;color:#059669;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px">✅</span>' if is_done else ''
        with cols_at[i % len(cols_at)]:
            st.markdown(f'''<div class="hnc" style="border-top:3px solid #0050d0"><div style="font-size:26px;margin-bottom:10px">{ic}</div><div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:5px">{title}{badge_done}</div><div style="font-size:12px;color:#6b7280;line-height:1.6;margin-bottom:10px">{desc}</div><span class="badge {bclass}">{diff}</span></div>''', unsafe_allow_html=True)
            if st.button(f"Acessar →", key=f"hat_{pg}"):
                st.session_state.page = pg; st.rerun()
            sp()

    # ── Copilot Studio section ──
    st.markdown('<div style="font-size:18px;font-weight:800;color:#111827;letter-spacing:-.02em;margin:28px 0 8px;">🤖 Copilot Studio</div><div style="font-size:13px;color:#6b7280;margin-bottom:16px">Crie agentes de IA conversacionais integrados ao Microsoft 365 e Power Platform.</div>', unsafe_allow_html=True)
    copilot_nav = [
        ("copilot_topicos",      "🤖","Tópicos & Diálogos","Trigger phrases, nós e fluxo de diálogo.","Intermediário","#ede9fe","#5c2d91"),
        ("copilot_entidades",    "🧩","Entidades & Variáveis","Extração de dados e estado da conversa.","Intermediário","#fce7f3","#9d174d"),
        ("copilot_ia",           "🧠","IA Generativa","Respostas por IA, fontes de conhecimento.","Avançado","#e0f2fe","#075985"),
        ("copilot_integracao",   "🌐","Integração & Canais","Teams, embed, SSO, Direct Line API.","Avançado","#fef3c7","#92400e"),
    ]
    cols_cp = st.columns(min(4, len(copilot_nav)))
    for i,(pg,ic,title,desc,diff,bg,tc) in enumerate(copilot_nav):
        bclass,_ = DIFF.get(diff, DIFF["Iniciante"])
        is_done = pg in visited
        badge_done = '&nbsp;&nbsp;<span style="background:#d1fae5;color:#059669;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px">✅</span>' if is_done else ''
        with cols_cp[i % len(cols_cp)]:
            st.markdown(f'''<div class="hnc" style="border-top:3px solid #7c3aed"><div style="font-size:26px;margin-bottom:10px">{ic}</div><div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:5px">{title}{badge_done}</div><div style="font-size:12px;color:#6b7280;line-height:1.6;margin-bottom:10px">{desc}</div><span class="badge {bclass}">{diff}</span></div>''', unsafe_allow_html=True)
            if st.button(f"Acessar →", key=f"hcp_{pg}"):
                st.session_state.page = pg; st.rerun()
            sp()

    # ── Dataverse section ──
    st.markdown('<div style="font-size:18px;font-weight:800;color:#111827;letter-spacing:-.02em;margin:28px 0 8px;">🗄️ Dataverse</div><div style="font-size:13px;color:#6b7280;margin-bottom:16px">O banco de dados nativo da Power Platform — relações reais, segurança e ALM.</div>', unsafe_allow_html=True)
    dataverse_nav = [
        ("dataverse_tabelas",    "🗄️","Tabelas & Relações","Tipos de tabela, colunas, relações N:1/1:N.","Intermediário","#d1fae5","#065f46"),
        ("dataverse_seguranca",  "🔒","Segurança & Ambientes","Security Roles, BU, Column Security, ALM.","Avançado","#fef3c7","#92400e"),
        ("dataverse_formulas",   "📐","Fórmulas & Calculadas","Calculated, Rollup, Power FX, FetchXML.","Avançado","#ede9fe","#5b21b6"),
        ("dataverse_apps",       "⚡","Power Apps + Dataverse","CRUD padrão, delegação, performance.","Avançado","#e0f2fe","#075985"),
    ]
    cols_dv = st.columns(min(4, len(dataverse_nav)))
    for i,(pg,ic,title,desc,diff,bg,tc) in enumerate(dataverse_nav):
        bclass,_ = DIFF.get(diff, DIFF["Iniciante"])
        is_done = pg in visited
        badge_done = '&nbsp;&nbsp;<span style="background:#d1fae5;color:#059669;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px">✅</span>' if is_done else ''
        with cols_dv[i % len(cols_dv)]:
            st.markdown(f'''<div class="hnc" style="border-top:3px solid #0d9488"><div style="font-size:26px;margin-bottom:10px">{ic}</div><div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:5px">{title}{badge_done}</div><div style="font-size:12px;color:#6b7280;line-height:1.6;margin-bottom:10px">{desc}</div><span class="badge {bclass}">{diff}</span></div>''', unsafe_allow_html=True)
            if st.button(f"Acessar →", key=f"hdv_{pg}"):
                st.session_state.page = pg; st.rerun()
            sp()

    st.markdown('<div style="font-size:18px;font-weight:800;color:#111827;letter-spacing:-.02em;margin:28px 0 16px;">🛠️ Ferramentas & Recursos</div>', unsafe_allow_html=True)
    tools = [
        ("cheatsheet","📋","Cheat Sheet",   "40+ fórmulas com filtro e busca"),
        ("busca",     "🔍","Busca Global",  "Encontre qualquer fórmula"),
        ("quiz",      "🧠","Quiz",          f"{len(ALL_QUESTIONS)} questões, 12 por sessão aleatória"),
        ("picker",    "🎨","Color Picker",  "RGBA, HSL, HSV + fórmula Power Apps"),
    ]
    cols2 = st.columns(4)
    for i,(pg,ic,title,desc) in enumerate(tools):
        with cols2[i]:
            st.markdown(f"""
            <div class="hnc" style="border-top:3px solid #0078d4;">
                <div style="font-size:26px;margin-bottom:10px;">{ic}</div>
                <div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:5px;">{title}</div>
                <div style="font-size:12px;color:#6b7280;line-height:1.6;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Abrir →", key=f"ht_{pg}"):
                st.session_state.page = pg; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


def page_controles():
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Documentação", "Laboratório de Controles")
    hero("controles","🎛️","Laboratório de Controles","Configure propriedades e veja o código Power FX gerado em tempo real.","Iniciante")

    tabs = st.tabs(["📝 Text Input","📋 Dropdown","📅 Date Picker","🖼️ Gallery","🔘 Button","🔀 Toggle","⏱️ Timer","📊 DataTable"])

    with tabs[0]:
        lab_header("Text Input","O controle de digitação principal")
        c1,c2 = st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            df=st.text_input("Default","Texto Exemplo",key="ti_df")
            ht=st.text_input("HintText","Digite aqui...",key="ti_ht")
            mode=st.selectbox("Mode",["TextMode.SingleLine","TextMode.MultiLine","TextMode.Password"],key="ti_md")
            ml=st.number_input("MaxLength",0,500,100,10,key="ti_ml")
            ro=st.checkbox("DisplayMode.View (somente leitura)",key="ti_ro")
        with c2:
            col_label("👁️ Preview & Código")
            it="password" if "Password" in mode else ("textarea" if "Multi" in mode else "text")
            if it=="textarea":
                st.markdown(f'<textarea placeholder="{ht}" style="width:100%;padding:10px 14px;border:1.5px solid #d1d5db;border-radius:8px;font-size:13px;height:80px;resize:none;font-family:inherit">{df}</textarea>',unsafe_allow_html=True)
            else:
                st.markdown(f'<input type="{it}" value="{df}" placeholder="{ht}" style="width:100%;padding:9px 14px;border:1.5px solid #d1d5db;border-radius:8px;font-size:13px;font-family:inherit">',unsafe_allow_html=True)
            sp()
            dm="DisplayMode.View" if ro else "DisplayMode.Edit"
            st.code(f'TextInput1.Default     = "{df}"\nTextInput1.HintText    = "{ht}"\nTextInput1.Mode        = {mode}\nTextInput1.MaxLength   = {ml}\nTextInput1.DisplayMode = {dm}',language="powerapps")
        info_box("💡 Use <code>TextMode.Password</code> para campos sensíveis — o texto é mascarado automaticamente.","info")

    with tabs[1]:
        lab_header("Dropdown, Radio & ComboBox","Controles de seleção com Items dinâmicos")
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            ct=st.radio("Tipo",["Dropdown","Radio Button","ComboBox"],horizontal=True,key="drp_t")
            ir=st.text_input("Items (separados por vírgula)","Alto, Médio, Baixo",key="drp_ir")
            items=[x.strip() for x in ir.split(",") if x.strip()] or ["Opção 1"]
        with c2:
            col_label("👁️ Preview & Código")
            ic='", "'.join(items)
            if ct=="Dropdown":
                st.selectbox("Simulação",items,key="drp_s")
                st.code(f'Dropdown1.Items = ["{ic}"]\n// Valor: Dropdown1.Selected.Value',language="powerapps")
            elif ct=="Radio Button":
                st.radio("Simulação",items,key="rad_s",horizontal=True)
                st.code(f'Radio1.Items = ["{ic}"]\n// Valor: Radio1.Selected.Value',language="powerapps")
            else:
                st.multiselect("Simulação (multi)",items,key="cmb_s")
                st.code(f'ComboBox1.Items = Distinct(Tabela, ColunaCategoria)\nComboBox1.SelectMultiple = true\n// Valores: ComboBox1.SelectedItems',language="powerapps")

    with tabs[2]:
        lab_header("Date Picker","Seleção de datas com formatação")
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            dv=st.date_input("DefaultDate",datetime.date.today(),key="dp_dv")
            fmt=st.selectbox("Format",["DateTimeFormat.ShortDate","DateTimeFormat.LongDate","DateTimeFormat.ShortDateTime24"],key="dp_fmt")
        with c2:
            col_label("👁️ Preview & Código")
            meses=["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
            if "Long" in fmt: disp=f"{dv.day} de {meses[dv.month-1]} de {dv.year}"
            elif "24" in fmt: disp=f"{dv.strftime('%d/%m/%Y')} 00:00"
            else: disp=dv.strftime('%d/%m/%Y')
            st.markdown(f'<div style="border:1.5px solid #d1d5db;border-radius:8px;padding:9px 14px;font-size:13px;background:white;display:flex;justify-content:space-between;"><span>{disp}</span><span>📅</span></div>',unsafe_allow_html=True)
            sp()
            st.code(f'DatePicker1.DefaultDate = Date({dv.year},{dv.month},{dv.day})\nDatePicker1.Format = {fmt}\n// Ler: DatePicker1.SelectedDate',language="powerapps")

    with tabs[3]:
        lab_header("Gallery","O controle mais importante do Power Apps")
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            gn=st.slider("Quantidade de itens",1,8,4,key="gal_n")
            ts=st.slider("TemplateSize (altura px)",50,160,80,key="gal_ts")
            show_s=st.checkbox("Mostrar item selecionado",True,key="gal_ss")
        with c2:
            col_label("👁️ Preview & Código")
            sel_i=2 if show_s else -1
            hi=""
            for i in range(1,gn+1):
                ss="border-left:3px solid #0078d4;background:#eff6fc;" if i==sel_i else "background:white;"
                hi+=f'<div style="border:1px solid #e5e7eb;height:{ts}px;padding:10px 14px;margin-bottom:4px;display:flex;align-items:center;{ss}border-radius:8px;gap:12px;"><div style="width:34px;height:34px;background:#0078d4;border-radius:50%;color:white;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0">{i}</div><div><div style="font-weight:600;font-size:12px">Item {i}</div><div style="font-size:11px;color:#6b7280">Subtítulo...</div></div><div style="margin-left:auto;color:#9ca3af">›</div></div>'
            st.markdown(f'<div style="background:#f9fafb;padding:8px;border-radius:10px;height:260px;overflow-y:auto;">{hi}</div>',unsafe_allow_html=True)
            sp()
            st.code(f'Gallery1.Items        = Filter(MinhaTabela, Ativo = true)\nGallery1.TemplateSize = {ts}\n// Item selecionado:   Gallery1.Selected\n// Navegar ao clicar:  Navigate(Tela2, None, {{rec: ThisItem}})',language="powerapps")
        info_box("⚠️ <b>Performance:</b> Sempre use Filter() no Items do Gallery — nunca carregue toda a tabela com ClearCollect() apenas para exibir.","warning")

    with tabs[4]:
        lab_header("Button","Personalizando botões")
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            bt=st.text_input("Text","Salvar",key="btn_bt")
            bf=st.color_picker("Fill","#0078d4",key="btn_bf")
            br=st.slider("BorderRadius",0,50,8,key="btn_br")
            bd=st.checkbox("Disabled",key="btn_bd")
        with c2:
            col_label("👁️ Preview & Código")
            op="0.45" if bd else "1"
            cur="not-allowed" if bd else "pointer"
            dm="DisplayMode.Disabled" if bd else "DisplayMode.Edit"
            st.markdown(f'<button style="background:{bf};color:white;border:none;padding:11px 26px;border-radius:{br}px;font-size:14px;font-weight:700;opacity:{op};cursor:{cur};font-family:inherit">{bt}</button>',unsafe_allow_html=True)
            sp()
            st.code(f'Button1.Text           = "{bt}"\nButton1.Fill           = ColorValue("{bf}")\nButton1.RadiusTopLeft  = {br}\nButton1.RadiusTopRight = {br}\nButton1.RadiusBottomLeft  = {br}\nButton1.RadiusBottomRight = {br}\nButton1.DisplayMode    = {dm}',language="powerapps")

    with tabs[5]:
        lab_header("Toggle & Rating","Controles de estado e avaliação")
        c1,c2=st.columns(2,gap="large")
        with c1:
            col_label("🔀 Toggle")
            tog=st.toggle("Ativo / Inativo",value=True,key="tog_d")
            st.code(f'Toggle1.Default   = {str(tog).lower()}\nToggle1.TrueText  = "Ativo"\nToggle1.FalseText = "Inativo"\n// Valor: Toggle1.Value → {str(tog).lower()}',language="powerapps")
        with c2:
            col_label("⭐ Rating")
            rat=st.slider("Valor (1-5)",1,5,4,key="rat_v")
            stars="⭐"*rat+"☆"*(5-rat)
            st.markdown(f'<div style="font-size:24px;margin:8px 0">{stars}</div>',unsafe_allow_html=True)
            st.code(f'Rating1.Default = {rat}\nRating1.Max     = 5\n// Valor: Rating1.Value → {rat}\nText(Rating1.Value) & " de 5 estrelas"',language="powerapps")

    with tabs[6]:
        lab_header("Timer","Executar ações com atraso ou repetidamente")
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            dur=st.number_input("Duration (ms)",500,60000,3000,500,key="tmr_d")
            aut=st.checkbox("AutoStart",False,key="tmr_a")
            rep=st.checkbox("Repeat (loop)",False,key="tmr_r")
        with c2:
            col_label("👁️ Código")
            info_box("⚠️ Timer é invisível por padrão (Visible = false). Use para polling, auto-refresh ou ações com atraso.","warning")
            st.code(f'Timer1.Duration  = {dur}\nTimer1.AutoStart = {str(aut).lower()}\nTimer1.Repeat    = {str(rep).lower()}\nTimer1.Visible   = false\n// Atualizar a cada {dur/1000:.1f}s:\nTimer1.OnTimerEnd = ClearCollect(colDados, MinhaTabela)',language="powerapps")

    with tabs[7]:
        lab_header("Data Table","Exibição tabular com colunas configuráveis")
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            col_label("⚙️ Configurações")
            cr=st.text_input("Colunas","Nome, Cargo, Departamento",key="dt_cr")
            dc=[c.strip() for c in cr.split(",") if c.strip()]
            dr=st.slider("Linhas de exemplo",2,6,3,key="dt_dr")
        with c2:
            col_label("👁️ Preview & Código")
            import pandas as pd
            data={col:[f"{col} {i+1}" for i in range(dr)] for col in dc}
            st.dataframe(pd.DataFrame(data),use_container_width=True)
            cb="\n".join([f'DataTableColumn{i+1}.FieldName = "{c}"' for i,c in enumerate(dc)])
            st.code(f'DataTable1.Items = Filter(MinhaTabela, Ativo = true)\n{cb}\n// Somente leitura — use Gallery para edição inline',language="powerapps")

    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("controles")


def page_formulas():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Laboratório de Fórmulas")
    hero("formulas","∑","Laboratório de Fórmulas Power FX","As fórmulas mais usadas — com exemplos interativos e casos reais.","Iniciante")

    tabs=st.tabs(["📊 Dados (CRUD)","🔍 Filter & Search","🧭 Navegação","✅ Validação","📅 Datas","🔢 Números & Texto"])

    with tabs[0]:
        info_box("🎯 <b>Patch() é a fórmula mais importante</b> do Power Apps. Dominá-la resolve 80% dos casos de CRUD.","info")
        c1,c2=st.columns(2)
        with c1:
            col_db=st.text_input("Fonte de dados","Funcionarios_TB",key="p_db")
            f1=st.text_input("Campo: Nome","TextInput_Nome.Text",key="p_n")
            f2=st.text_input("Campo: Cargo","Dropdown_Cargo.Selected.Value",key="p_c")
            f3=st.text_input("Campo: Departamento","Dropdown_Dept.Selected.Value",key="p_d")
            modo=st.radio("Modo",["Criar (Defaults)","Editar (Gallery)"],horizontal=True,key="p_m")
        with c2:
            rp=f"Defaults({col_db})" if "Criar" in modo else "Gallery1.Selected"
            st.code(f"""If(
    IsBlank({f1}),
    Notify("Nome obrigatório", NotificationType.Error),
    Patch(
        {col_db},
        {rp},
        {{
            Nome:          {f1},
            Cargo:         {f2},
            Departamento:  {f3},
            DataRegistro:  Now(),
            CriadoPor:     User().Email
        }}
    );
    Notify("Salvo!", NotificationType.Success);
    Navigate(Tela_Lista, ScreenTransition.Fade)
)""",language="powerapps")

    with tabs[1]:
        info_box("🔍 <b>Filter vs Search:</b> Filter() para critérios lógicos (=, >, &&). Search() para texto livre em múltiplas colunas.","info")
        c1,c2=st.columns(2)
        with c1:
            formula_card("Filter()","Retorna registros que atendem condições lógicas.",
                "Galleries com filtros, ComboBoxes condicionais, totais calculados.",
                'Filter(Vendas_TB,\n    Regiao = Dropdown_Reg.Selected.Value,\n    Ativo = true,\n    DataVenda >= DatePicker_Ini.SelectedDate\n)',
                deleg="✅ Delegável",color="#065f46",tags=["SharePoint ✓","Dataverse ✓","SQL ✓"])
        with c2:
            formula_card("Search()","Busca texto livre em uma ou mais colunas.",
                "Campo de busca em tempo real. Combine com Filter() para refinar.",
                'Search(\n    Clientes_TB,\n    TextInput_Busca.Text,\n    "Nome", "Email", "Telefone"\n)',
                deleg="✅ Delegável",color="#065f46",tags=["Texto livre","Multi-coluna"])
        c3,c4=st.columns(2)
        with c3:
            formula_card("LookUp()","Retorna o primeiro registro que atende a condição.",
                "Buscar configuração por chave, verificar existência, dados relacionados.",
                'Set(gblPerfil,\n    LookUp(Perfis_TB, Email = User().Email)\n)\n// Usar: gblPerfil.Cargo',
                deleg="✅ Delegável",color="#0c2344")
        with c4:
            formula_card("SortByColumns()","Ordena tabela por uma ou mais colunas.",
                "Ordenar Galleries por data, nome ou valor. Delegável no SharePoint.",
                'SortByColumns(\n    Filter(Pedidos_TB, ClienteID = gblCliente.ID),\n    "DataPedido",\n    Descending\n)',
                deleg="✅ Delegável",color="#0c2344")

    with tabs[2]:
        c1,c2=st.columns(2)
        with c1:
            formula_card("Navigate() com contexto","Navega passando dados para a próxima tela.",
                "Ao clicar em item de Gallery, ao salvar form, ao clicar em menu.",
                'Navigate(\n    Tela_Detalhe,\n    ScreenTransition.Fade,\n    {\n        recSel:     Gallery1.Selected,\n        modoEdicao: true,\n        tituloPag:  "Editar Funcionário"\n    }\n)\n// Na Tela_Detalhe:\n// recSel, modoEdicao, tituloPag são variáveis locais',
                color="#14532d")
        with c2:
            formula_card("Concurrent() no App.OnStart","Carrega múltiplas fontes em paralelo.",
                "Sempre que o app tem 2+ fontes de dados. Reduz tempo de carga em 60-80%.",
                '// App.OnStart — carrega em paralelo:\nConcurrent(\n    Set(gblUsuario, LookUp(Perfis, Email = User().Email)),\n    ClearCollect(colClientes, Clientes_TB),\n    ClearCollect(colProdutos, Produtos_TB),\n    Set(gblConfigs,  LookUp(Configs, Ativa = true))\n)',
                color="#14532d")

    with tabs[3]:
        formula_card("Padrão completo de validação","Validação encadeada antes do Patch().",
            "Use este padrão em todos os formulários de cadastro e edição.",
            """If(
    IsBlank(inp_Nome.Text),
    Notify("Nome obrigatório", NotificationType.Error),

    IsBlank(inp_Email.Text),
    Notify("E-mail obrigatório", NotificationType.Error),

    !IsMatch(inp_Email.Text, Match.Email),
    Notify("E-mail inválido", NotificationType.Error),

    Len(inp_Tel.Text) < 10,
    Notify("Telefone incompleto", NotificationType.Error),

    // ✅ Tudo válido
    Patch(Funcionarios_TB, Defaults(Funcionarios_TB), {
        Nome: inp_Nome.Text, Email: inp_Email.Text
    });
    Notify("Cadastro realizado!", NotificationType.Success);
    Reset(inp_Nome); Reset(inp_Email)
)""",color="#7f1d1d",tags=["IsBlank","IsMatch","Notify","Reset"])
        c1,c2=st.columns(2)
        with c1:
            st.markdown("##### Demo IsBlank()")
            dv=st.text_input("Digite algo (ou deixe vazio):",key="ib_demo")
            if not dv.strip(): st.error("⚠️ IsBlank() = TRUE — campo obrigatório!")
            else: st.success("✅ IsBlank() = FALSE — campo preenchido.")
        with c2:
            st.markdown("##### Demo IsMatch(Email)")
            de=st.text_input("Digite um e-mail:","user@empresa.com",key="im_demo")
            ok=bool(re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$',de))
            if ok: st.success("✅ IsMatch(Match.Email) = TRUE")
            else:  st.error("❌ IsMatch(Match.Email) = FALSE")

    with tabs[4]:
        c1,c2=st.columns(2)
        with c1:
            st.markdown("##### DateAdd()")
            db=st.date_input("Data base",datetime.date.today(),key="da_b")
            dq=st.number_input("Quantidade",value=30,key="da_q")
            du=st.selectbox("Unidade",["TimeUnit.Days","TimeUnit.Months","TimeUnit.Years"],key="da_u")
            if "Days" in du: res=db+datetime.timedelta(days=int(dq))
            elif "Months" in du:
                nm=(db.month-1+int(dq))%12+1; ny=db.year+(db.month-1+int(dq))//12
                try: res=db.replace(year=ny,month=nm)
                except: res=db
            else:
                try: res=db.replace(year=db.year+int(dq))
                except: res=db
            st.success(f"Resultado: **{res.strftime('%d/%m/%Y')}**")
            st.code(f'DateAdd(Date({db.year},{db.month},{db.day}), {int(dq)}, {du})\n// → {res.strftime("%d/%m/%Y")}',language="powerapps")
        with c2:
            st.markdown("##### DateDiff()")
            da=st.date_input("Data inicial",datetime.date(1995,1,1),key="dd_a")
            db2=st.date_input("Data final",datetime.date.today(),key="dd_b")
            diff_d=(db2-da).days; diff_y=diff_d//365
            st.info(f"Diferença: **{diff_d:,} dias** (~{diff_y} anos)")
            st.code(f'DateDiff(Date({da.year},{da.month},{da.day}), Today(), TimeUnit.Days)  // → {diff_d}\n// Calcular idade:\nDateDiff(DataNasc.SelectedDate, Today(), TimeUnit.Years)',language="powerapps")

    with tabs[5]:
        c1,c2=st.columns(2)
        with c1:
            st.markdown("##### Round()")
            vn=st.number_input("Valor",value=12.567,format="%.3f",key="rnd_v")
            dc=st.slider("Casas decimais",0,4,2,key="rnd_d")
            st.info(f"Round: **{round(vn,dc)}**")
            st.code(f'Round({vn}, {dc})      // → {round(vn,dc)}\nRoundUp({vn}, {dc})    // arredonda para cima\nRoundDown({vn}, {dc})  // arredonda para baixo\nInt({vn})              // → {int(vn)} (trunca)',language="powerapps")
        with c2:
            st.markdown("##### Concatenate() / Text()")
            nm=st.text_input("Nome","Maria Silva",key="cc_n")
            cr=st.text_input("Cargo","Analista",key="cc_c")
            st.info(f"**Olá, {nm}! Cargo: {cr}**")
            st.code(f'"Olá, " & inp_Nome.Text & "! Cargo: " & inp_Cargo.Text\n\nText(1234.5, "R$ #.##0,00")  // → R$ 1.234,50\nText(Now(), "dd/mm/yyyy hh:mm")\n\nUpper(inp_Nome.Text)   // MARIA SILVA\nLower(inp_Email.Text)  // maria@empresa.com\nProper(inp_Nome.Text)  // Maria Silva',language="powerapps")

    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("formulas")


def page_navegacao():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Navegação entre Telas")
    hero("navegacao","🧭","Navegação entre Telas","Navigate(), Back(), contexto e deep link com Microsoft Teams.","Intermediário")
    c1,c2=st.columns(2)
    with c1:
        formula_card("Navigate() com contexto","Passa dados para a próxima tela sem variáveis globais.",
            "Sempre prefira contexto local ao Navigate() em vez de Set() quando o dado é só para a próxima tela.",
            'Navigate(\n    Tela_Form,\n    ScreenTransition.Fade,\n    {\n        locRegistro: Gallery1.Selected,\n        locEdicao:   true,\n        locTitulo:   "Editar"\n    }\n)\n// Na Tela_Form:\nTextInput_Nome.Default = locRegistro.Nome',color="#14532d")
        formula_card("Menu lateral com tela ativa","Indicar visualmente qual tela está ativa.",
            "Use variável global gblTela para destacar o item do menu atual.",
            '// No OnVisible de cada tela:\nSet(gblTela, "Dashboard")\n\n// Fill do item do menu:\nIf(gblTela = "Dashboard",\n    RGBA(0,120,212,.12),\n    RGBA(0,0,0,0)\n)',color="#14532d")
    with c2:
        formula_card("Deep Link para Teams & SharePoint","Abrir URLs, iniciar chats e chamadas direto do app.",
            "Integração nativa com Microsoft 365 — sem conectores premium.",
            'Launch("https://teams.microsoft.com/l/chat/0/0?users=" & Gallery1.Selected.Email)\nLaunch("https://teams.microsoft.com/l/call/0/0?users=" & User().Email)\nLaunch(Gallery1.Selected.LinkDoArquivo)',color="#14532d")
        formula_card("Back() e proteção de saída","Controlar o botão voltar e confirmar antes de sair.",
            "Quando há formulário com alterações não salvas, confirme antes de voltar.",
            'If(\n    !IsBlank(inp_Nome.Text),\n    UpdateContext({locConfirmSaida: true}),\n    Back()\n)\n// Popup de confirmação:\nlocConfirmSaida = true → mostrar modal\n// Botão "Descartar":\nReset(inp_Nome); Navigate(Tela_Lista, None)',color="#14532d")
    info_box("💡 <b>Dica de arquitetura:</b> Em apps com 10+ telas, considere usar uma única tela com Containers e visibilidade condicional — navegação instantânea sem animação.","info")
    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("navegacao")


def page_validacao():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Validação de Formulários")
    hero("validacao","✅","Validação de Formulários","IsBlank, IsMatch, Notify e feedback visual profissional.","Intermediário")
    c1,c2=st.columns(2)
    with c1:
        formula_card("IsBlank() — Campos obrigatórios","Verifica se um campo está vazio ou nulo.",
            "Valide no OnSelect do botão Salvar. Use em Visible de labels de erro.",
            '// Habilitar Salvar apenas se campos preenchidos:\nButton_Salvar.DisplayMode =\nIf(\n    !IsBlank(inp_Nome.Text) &&\n    !IsBlank(inp_Email.Text),\n    DisplayMode.Edit,\n    DisplayMode.Disabled\n)',color="#7f1d1d")
        formula_card("IsMatch() — Formatos e padrões","Valida se texto segue padrão built-in ou regex.",
            "E-mails, CPF, telefone, CEP e qualquer formato específico.",
            'IsMatch(Email.Text, Match.Email)\nIsMatch(URL.Text, Match.URL)\nIsMatch(Num.Text, Match.Digit)\n\n// CPF:\nIsMatch(CPF.Text, "\\d{3}\\.\\d{3}\\.\\d{3}-\\d{2}")\n\n// Telefone BR:\nIsMatch(Tel.Text, "\\(\\d{2}\\)\\s?\\d{4,5}-\\d{4}")',color="#7f1d1d")
    with c2:
        formula_card("Notify() — Feedback ao usuário","Exibe banner nativo com duração configurável.",
            "Sempre após Patch() para confirmar sucesso ou informar erros.",
            'Notify("Salvo!", NotificationType.Success)\nNotify("Atenção!", NotificationType.Warning)\nNotify("Erro ao salvar", NotificationType.Error)\nNotify("Info...", NotificationType.Information, 2000)',color="#b91c1c")
        formula_card("Erros visuais nos campos","Bordas vermelhas e labels de erro por campo.",
            "Padrão UX profissional — feedback contextual sem popup.",
            '// Border color do TextInput:\nTextInput_Email.BorderColor =\nIf(!IsMatch(TextInput_Email.Text, Match.Email),\n    RGBA(185,28,28,1),    // vermelho\n    RGBA(209,213,219,1)   // cinza\n)\n\n// Contador: "12/100"\nlbl_Count.Text = Text(Len(inp.Text)) & "/100"',color="#b91c1c")
    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("validacao")


def page_performance():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Performance & Delegação")
    hero("performance","⚡","Performance & Delegação","Limites de cada conector e como evitar o aviso azul de delegação.","Avançado")
    info_box("<b>Delegação:</b> Quando delegável, o filtro vai para o servidor → sem limite de registros. Quando não é delegável, o app baixa até 2.000 registros e filtra localmente — registros além do limite são silenciosamente ignorados. ⚠️","warning")
    c1,c2=st.columns(2)
    with c1:
        st.markdown("#### ✅ Delegáveis no SharePoint")
        st.code('Filter(Lista, Coluna = "valor")     // ✅\nFilter(Lista, Coluna >= 100)         // ✅\nFilter(Lista, StartsWith(Col,"A"))   // ✅\nSearch(Lista, busca, "Col")          // ✅\nSortByColumns(Lista, "Col")          // ✅\nCountRows(Filter(Lista, cond))       // ✅\nSum(Lista, Coluna)                   // ✅',language="powerapps")
        st.markdown("#### ❌ NÃO delegáveis")
        st.code('Filter(Lista, IsBlank(Col))         // ❌\nFilter(Lista, Mid(Col,1,3)="ABC")   // ❌\nFilter(Lista, Len(Col)>5)            // ❌\nForAll(...)                          // ❌ nunca\nAddColumns(...)                      // ❌ nunca\nSort(...)                            // ❌ use SortByColumns',language="powerapps")
    with c2:
        st.markdown("#### 📊 Limites por conector")
        st.markdown("""<table class="conn-tbl">
<thead><tr><th>Conector</th><th>Padrão</th><th>Máximo</th></tr></thead>
<tbody>
<tr><td class="conn-nm">SharePoint Online</td><td>500</td><td>2.000</td></tr>
<tr><td class="conn-nm">Microsoft Dataverse</td><td>500</td><td>100k+</td></tr>
<tr><td class="conn-nm">SQL Server / Azure SQL</td><td>500</td><td>2k+</td></tr>
<tr><td class="conn-nm">Excel (OneDrive)</td><td>500</td><td>2.000 ❌</td></tr>
<tr><td class="conn-nm">Coleções locais</td><td>—</td><td>RAM</td></tr>
</tbody></table>""",unsafe_allow_html=True)
        st.code('// ✅ Carregar em paralelo no OnStart:\nConcurrent(\n    Set(gblUser, LookUp(Perfis, Email=User().Email)),\n    ClearCollect(colClientes, Clientes_TB),\n    ClearCollect(colProdutos, Produtos_TB)\n)\n// Concurrent() reduz tempo de carga em 60-80%!',language="powerapps")
    info_box("💡 <b>Regra de ouro:</b> Se sua lista tem mais de 500 itens, teste sempre com delegação real e observe o aviso azul ⚠️ no Power Apps Studio.","info")
    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("performance")


def page_seguranca():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Segurança por Perfil")
    hero("seguranca","🔐","Segurança por Perfil","Controle de acesso com User(), perfis no SharePoint e grupos do AD.","Intermediário")
    c1,c2=st.columns(2)
    with c1:
        formula_card("User() — Usuário logado","Função nativa com dados do usuário autenticado.",
            "Carregar perfil no App.OnStart e usar gblPerfil em todas as telas.",
            'Set(gblPerfil,\n    LookUp(Perfis_TB, Email = User().Email)\n)\n// Propriedades:\nUser().Email       // usuario@empresa.com\nUser().FullName    // Maria da Silva\nUser().Image       // Foto (Base64)',color="#500724")
        formula_card("Visibilidade condicional","Controlar quais controles cada perfil vê.",
            "Use Visible e DisplayMode nas propriedades dos controles.",
            '// Botão excluir — só admins:\nbtnExcluir.Visible =\n    gblPerfil.NivelAcesso = "Admin"\n\n// Formulário — leitura para Viewers:\nForm1.Mode = If(\n    gblPerfil.NivelAcesso = "Viewer",\n    FormMode.View,\n    FormMode.Edit\n)',color="#500724")
    with c2:
        formula_card("Office 365 Users — Busca de colegas","Buscar usuários do diretório corporativo.",
            "Autocomplete de pessoas, foto e dados de contato. Conector Standard.",
            'Office365Users.SearchUser({searchTerm: inp.Text, top: 10})\nOffice365Users.UserPhoto(Gallery1.Selected.Mail)\nOffice365Users.DirectReports(User().Email)',color="#9d174d")
        formula_card("Lista de Perfis no SharePoint","Controle de acesso sem licenças extras.",
            "Crie uma lista 'Perfis_TB' com Email e NivelAcesso. Simples e eficaz.",
            '// App.OnStart:\nSet(gblNivel,\n    LookUp(Perfis_TB,\n           Email = User().Email).NivelAcesso\n)\n// Valores possíveis: "Admin", "Editor", "Viewer"\n// Uso:\nbtnConf.Visible = gblNivel = "Admin"',color="#9d174d")
    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("seguranca")


def page_conectores():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Conectores")
    hero("conectores","🔌","Conectores Suportados","Standard (M365) e Premium — casos de uso e limitações.","Iniciante")
    t1,t2=st.tabs(["✅ Standard (Gratuitos)","💲 Premium (Licença adicional)"])
    with t1:
        st.success("**Inclusos na licença Microsoft 365 Business/Enterprise** — sem custo adicional")
        st.markdown("""<table class="conn-tbl">
<thead><tr><th>Conector</th><th>Uso principal</th><th>Limitações importantes</th></tr></thead>
<tbody>
<tr><td class="conn-nm">📋 SharePoint Online</td><td>Listas como banco de dados</td><td>Delegação até 2k. Sem relacionamentos. Excel = instável ❌</td></tr>
<tr><td class="conn-nm">👤 Office 365 Users</td><td>Foto, cargo, email, subordinados</td><td>Essencial em todo app. Sem limitações.</td></tr>
<tr><td class="conn-nm">📧 Outlook / Office 365</td><td>Emails, calendário, eventos</td><td>Limite de envio por minuto. Cuidado com loops.</td></tr>
<tr><td class="conn-nm">📁 OneDrive (Business)</td><td>Ler Excel, PDF, imagens</td><td>Excel como DB = instável e sem delegação ❌</td></tr>
<tr><td class="conn-nm">✅ Microsoft Planner</td><td>Tarefas, buckets, kanban</td><td>API limitada. Sem campos personalizados.</td></tr>
<tr><td class="conn-nm">💬 Microsoft Teams</td><td>Postar em canais, deep link, tabs</td><td>Melhor canal de distribuição de apps.</td></tr>
</tbody></table>""",unsafe_allow_html=True)
    with t2:
        st.warning("**Requer Per App (~R$25/app/user/mês) ou Per User (~R$50/user/mês)**")
        st.markdown("""<table class="conn-tbl">
<thead><tr><th>Conector</th><th>Uso principal</th><th>Por que vale</th></tr></thead>
<tbody>
<tr><td class="conn-nm">🏢 Microsoft Dataverse</td><td>Banco oficial da Power Platform</td><td>Segurança, relacionamentos, ALM, delegação total. <b>Recomendado para produção.</b></td></tr>
<tr><td class="conn-nm">🗄️ SQL Server / Azure SQL</td><td>Bancos legados ou Azure</td><td>Robustez máxima, delegação quase total.</td></tr>
<tr><td class="conn-nm">🌐 HTTP / Web API</td><td>Qualquer API REST/JSON</td><td>Conecta com qualquer sistema moderno.</td></tr>
<tr><td class="conn-nm">☁️ Salesforce</td><td>Dados de CRM</td><td>Leitura/escrita direta nos objetos.</td></tr>
<tr><td class="conn-nm">📄 Adobe PDF Services</td><td>Criar, mesclar, manipular PDFs</td><td>Relatórios PDF profissionais direto do app.</td></tr>
<tr><td class="conn-nm">✍️ DocuSign</td><td>Assinatura digital</td><td>Enviar e acompanhar envelopes.</td></tr>
</tbody></table>""",unsafe_allow_html=True)
    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("conectores")


def page_variaveis():
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Documentação","Variáveis na Prática")
    hero("variaveis","📦","Variáveis na Prática","Set() global vs UpdateContext() local vs Collections — demo interativa.","Iniciante")
    c1,c2,c3=st.columns(3)
    for col,title,desc,items,bg,bc in [
        (c1,"📡 Set() — Global","Acessível em todas as telas",["Use para: Usuário logado","Configurações do app","Flag de administrador","Dados carregados no OnStart"],"#eff6ff","#bfdbfe"),
        (c2,"📍 UpdateContext() — Local","Só existe na tela atual",["Use para: Popup aberto/fechado","Loading spinner","Modo edição vs visualização","Estado de formulário local"],"#f5f3ff","#ddd6fe"),
        (c3,"📚 Collections — Tabela","Em memória, perdida ao fechar",["Use para: Carrinho de compras","Seleção múltipla de itens","Dados offline temporários","Cache de fonte de dados"],"#f0fdf4","#bbf7d0"),
    ]:
        with col:
            il="".join(f'<div style="font-size:12px;color:#4b5563;padding:3px 0">• {it}</div>' for it in items)
            st.markdown(f'<div style="background:{bg};border:1px solid {bc};border-radius:12px;padding:16px;height:100%"><div style="font-weight:700;color:#111827;margin-bottom:8px">{title}</div><div style="font-size:12px;color:#6b7280;margin-bottom:10px;font-weight:500">{desc}</div>{il}</div>',unsafe_allow_html=True)
    st.divider()
    c1,c2=st.columns(2)
    with c1:
        st.markdown("#### Demo: UpdateContext()")
        if st.button("Alternar popup (locPopup)",type="primary"):
            st.session_state.ctx_popup=not st.session_state.ctx_popup
        if st.session_state.ctx_popup: st.info("🟦 **locPopup = TRUE**")
        else: st.markdown("⬜ **locPopup = FALSE**")
        st.code(f'UpdateContext({{locPopup: !locPopup}})\n// Valor atual: {str(st.session_state.ctx_popup).lower()}',language="powerapps")
    with c2:
        st.markdown("#### Demo: Set() global")
        ui=st.text_input("Nome do usuário:","Maria",key="set_d")
        if st.button("Set(gblUser, ...)",type="primary"):
            st.session_state.gbl_user=ui
        if st.session_state.gbl_user:
            st.success(f'✅ gblUser = **"{st.session_state.gbl_user}"**')
        st.code(f'Set(gblUser, "{st.session_state.gbl_user}")',language="powerapps")
    st.divider()
    st.markdown("#### Demo: Collections")
    c1,c2=st.columns([1,3])
    with c1:
        if st.button("➕ Collect()",key="col_add"):
            n=len(st.session_state.my_col)+1
            st.session_state.my_col.append({"Produto":f"Prod {n}","Valor":random.randint(10,99),"Qtd":random.randint(1,5)})
        if st.button("🗑️ Clear()",key="col_clr"):
            st.session_state.my_col=[]
    with c2:
        if st.session_state.my_col:
            import pandas as pd
            df=pd.DataFrame(st.session_state.my_col)
            df["Total"]=df["Valor"]*df["Qtd"]
            st.dataframe(df,use_container_width=True)
            st.caption(f"Total: R$ {df['Total'].sum()}")
    st.markdown('</div>',unsafe_allow_html=True)
    section_quiz("variaveis")


def page_cheatsheet():
    u = current_user()
    if u: mark_page_visited(u["id"], "cheatsheet")
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Ferramentas","Cheat Sheet")
    hero("cheatsheet","📋",f"Cheat Sheet — Power FX",f"{len(FORMULAS)} fórmulas com delegação, categoria e exemplos.","Iniciante")

    cats=["Todas"]+sorted(set(f["cat"] for f in FORMULAS))
    c1,c2,c3=st.columns([2,1.5,2])
    with c1: cat=st.selectbox("Categoria:",cats,key="cs_c")
    with c2: del_f=st.selectbox("Delegação:",["Todas","✅","⚠️","❌","N/A"],key="cs_d")
    with c3: bsc=st.text_input("🔍 Buscar:","",placeholder="Ex: filter, patch...",key="cs_b")

    filt=FORMULAS
    if cat!="Todas": filt=[f for f in filt if f["cat"]==cat]
    if del_f!="Todas": filt=[f for f in filt if f["deleg"]==del_f]
    if bsc: q=bsc.lower(); filt=[f for f in filt if q in f["nome"].lower() or q in f["desc"].lower()]

    st.caption(f"Exibindo {len(filt)} de {len(FORMULAS)} fórmulas")
    rows="".join(f'<tr><td><span class="fn-nm">{f["nome"]}</span></td><td><span style="font-size:10px;background:#f3f4f6;padding:2px 8px;border-radius:10px;color:#6b7280;font-weight:600">{f["cat"]}</span></td><td style="color:#374151">{f["desc"]}</td><td><span class="{"dy" if f["deleg"]=="✅" else "dp" if f["deleg"]=="⚠️" else "dn" if f["deleg"]=="❌" else ""}">{f["deleg"]}</span></td></tr>' for f in filt)
    st.markdown(f'<table class="cs-tbl"><thead><tr><th>Fórmula</th><th>Categoria</th><th>Descrição</th><th>Delegável</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)

    if filt:
        st.divider()
        sel_n=st.selectbox("Ver exemplo de:",[f["nome"] for f in filt],key="cs_ex")
        sel=next((f for f in filt if f["nome"]==sel_n),None)
        if sel: st.code(sel["ex"],language="powerapps")
    st.markdown('</div>',unsafe_allow_html=True)


def page_busca():
    # FIX: usar busca_query separado do key do widget
    u = current_user()
    if u: mark_page_visited(u["id"], "busca")

    # Se há um termo pendente de um botão de sugestão, aplique antes do widget
    if "busca_pending" in st.session_state:
        st.session_state["busca_query"] = st.session_state.pop("busca_pending")

    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Ferramentas","Busca Global")
    hero("busca","🔍","Busca Global","Encontre qualquer fórmula, controle ou seção do treinamento.","Iniciante")

    q = st.text_input(
        "", value=st.session_state.busca_query,
        placeholder="Digite o nome de uma fórmula ou conceito...",
        key="busca_input", label_visibility="collapsed"
    )
    st.session_state.busca_query = q  # sync back

    if q and len(q) >= 2:
        ql = q.lower()
        rf = [f for f in FORMULAS if ql in f["nome"].lower() or ql in f["desc"].lower() or ql in f["cat"].lower()]
        ep = [
            ("🎛️ Controles","controles","TextInput, Gallery, Button, Toggle, Timer, DatePicker"),
            ("🧭 Navegação","navegacao","Navigate(), Back(), contexto, deep link Teams"),
            ("✅ Validação","validacao","IsBlank, IsMatch, Notify, erros visuais nos campos"),
            ("⚡ Performance","performance","Delegação, ClearCollect, Concurrent, limites"),
            ("🔐 Segurança","seguranca","User().Email, perfis, grupos, visibilidade condicional"),
            ("📦 Variáveis","variaveis","Set, UpdateContext, Collections, Collect, Clear"),
        ]
        pr = [(t,pg,d) for t,pg,d in ep if ql in t.lower() or ql in d.lower()]
        total = len(rf)+len(pr)
        if total == 0:
            st.warning(f'Nenhum resultado para **"{q}"**.')
        else:
            st.caption(f"{total} resultado(s) para \"{q}\"")
            if rf:
                st.markdown("##### Fórmulas Power FX")
                for f in rf[:10]:
                    di = {"✅":"✅","⚠️":"⚠️","❌":"❌"}.get(f["deleg"],"")
                    st.markdown(f'<div class="sr"><div style="display:flex;align-items:center;justify-content:space-between"><div><div class="sr-nm">{f["nome"]}</div><div class="sr-ds">{f["desc"]}</div></div><span style="font-size:12px">{di}</span></div></div>',unsafe_allow_html=True)
            if pr:
                st.markdown("##### Seções do treinamento")
                for t,pg,d in pr:
                    st.markdown(f'<div class="sr"><div class="sr-nm" style="font-family:inherit">{t}</div><div class="sr-ds">{d}</div></div>',unsafe_allow_html=True)
                    if st.button(f"→ Ir para {t.split(' ',1)[1]}",key=f"bg_{pg}"):
                        st.session_state.page = pg; st.rerun()
    else:
        st.markdown('<div style="color:#9ca3af;font-size:13px;margin-bottom:14px">Termos populares:</div>',unsafe_allow_html=True)
        terms = ["filter","patch","navigate","isblank","notify","user()","gallery","collection","delegação","concurrent"]
        cols = st.columns(5)
        for i, t in enumerate(terms):
            with cols[i % 5]:
                if st.button(t, key=f"pop_{t}"):
                    st.session_state["busca_pending"] = t
                    st.rerun()

    st.markdown('</div>',unsafe_allow_html=True)


def page_quiz():
    u = current_user()
    if u: mark_page_visited(u["id"], "quiz")
    init_quiz_session()
    user_id = u["id"]
    qstats = get_quiz_stats(user_id)

    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Ferramentas","Quiz Global")
    hero("quiz","🧠","Quiz — Power Apps",f"{len(ALL_QUESTIONS)} questões no banco. {N_QUIZ_SESSION} aleatórias por sessão. Progresso salvo por usuário.","Intermediário")

    session_qs = st.session_state.quiz_session
    sess_ans = st.session_state.quiz_session_answers
    answered_this = len(sess_ans)
    correct_this = sum(1 for v in sess_ans.values() if v)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Questões na sessão",f"{answered_this}/{N_QUIZ_SESSION}")
    c2.metric("Acertos na sessão",correct_this)
    c3.metric("Total respondidas",qstats["total"])
    c4.metric("Total acertos",qstats["correct"])

    if answered_this == N_QUIZ_SESSION:
        pct = int(correct_this/N_QUIZ_SESSION*100)
        if pct >= 80: st.success(f"🎉 **Excelente!** {correct_this}/{N_QUIZ_SESSION} ({pct}%)")
        elif pct >= 60: st.warning(f"👍 **Bom!** {correct_this}/{N_QUIZ_SESSION} ({pct}%)")
        else: st.error(f"📚 **Continue estudando!** {correct_this}/{N_QUIZ_SESSION} ({pct}%)")
        if st.button("🔄 Nova sessão (questões diferentes)",type="primary"):
            st.session_state.quiz_session = None
            st.session_state.quiz_session_answers = {}
            st.rerun()
        st.divider()

    for idx, q_idx in enumerate(session_qs):
        q = ALL_QUESTIONS[q_idx]
        q_id = q["id"]
        sess_key = f"sess_{q_idx}"
        answered = sess_key in sess_ans
        user_ans = sess_ans.get(sess_key)

        cc = CAT_COLORS.get(q["cat"],"#1e3a5f")
        st.markdown(f"""<div class="quiz-card">
            <span class="quiz-num" style="background:{cc};color:white;padding:2px 9px;border-radius:10px;font-size:10px">#{idx+1} &nbsp;{q["cat"]}</span>
            <div class="quiz-q" style="margin-top:12px">{q["q"]}</div>
        </div>""",unsafe_allow_html=True)

        if answered:
            for j,opt in enumerate(q["opts"]):
                if j == q["ans"]: st.success(f"✅ {opt}")
                elif j == user_ans and user_ans != q["ans"]: st.error(f"❌ {opt}")
                else: st.markdown(f'<div style="padding:6px 0;font-size:13px;color:#6b7280">　　{opt}</div>',unsafe_allow_html=True)
            st.markdown(f'<div class="ib ib-info" style="margin-top:8px">💡 {q["exp"]}</div>',unsafe_allow_html=True)
        else:
            choice = st.radio("",q["opts"],key=f"qr_{q_idx}_{idx}",index=None,label_visibility="collapsed")
            if st.button("Confirmar",key=f"qb_{q_idx}_{idx}",disabled=(choice is None)):
                ci = q["opts"].index(choice)
                is_correct = (ci == q["ans"])
                sess_ans[sess_key] = is_correct
                st.session_state.quiz_session_answers = sess_ans
                save_quiz_answer(user_id, q_id, is_correct)
                st.rerun()
        sp()
    st.markdown('</div>',unsafe_allow_html=True)


def page_picker():
    u = current_user()
    if u: mark_page_visited(u["id"], "picker")
    st.markdown('<div class="main-wrap">',unsafe_allow_html=True)
    breadcrumb("Ferramentas","Color Picker RGBA")
    hero("picker","🎨","Color Picker RGBA","Escolha cores e converta entre HEX, RGB, HSL, HSV e a fórmula Power Apps RGBA().","Iniciante")

    tabs = st.tabs(["🎨 Picker","🔄 Conversor","🎡 Roda HSV","🎲 Aleatória"])

    with tabs[0]:
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            hv=st.color_picker("Cor:","#0078d4",key="pk_h")
            al=st.slider("Alpha:",0.0,1.0,1.0,0.01,key="pk_a")
            r,g,b,_=hex_to_rgba(hv)
            r2=st.number_input("R",0,255,r,key="pk_r")
            g2=st.number_input("G",0,255,g,key="pk_g")
            b2=st.number_input("B",0,255,b,key="pk_b")
        with c2:
            color_preview(r2,g2,b2,al)
            color_codes(r2,g2,b2,al)

    with tabs[1]:
        c1,c2=st.columns(2,gap="large")
        with c1:
            st.subheader("Hex → RGBA")
            hx=st.text_input("Hex (#RRGGBB):","#1a73e8",key="cv_hx")
            if st.button("Converter",type="primary",key="cv_b1"):
                try:
                    r,g,b,a=hex_to_rgba(hx)
                    color_preview(r,g,b,a,80); color_codes(r,g,b,a,"cv1")
                except Exception as e: st.error(str(e))
        with c2:
            st.subheader("RGBA → Hex")
            rc=st.number_input("R",0,255,26,key="cv_r")
            gc=st.number_input("G",0,255,115,key="cv_g")
            bc=st.number_input("B",0,255,232,key="cv_b")
            ac=st.slider("Alpha",0.0,1.0,1.0,0.01,key="cv_a")
            wa=st.checkbox("Incluir alpha",True,key="cv_wa")
            if st.button("Converter",type="primary",key="cv_b2"):
                ho=rgba_to_hex(rc,gc,bc,ac,wa)
                st.success(f"Hex: `{ho}`")
                color_preview(rc,gc,bc,ac,80)

    with tabs[2]:
        c1,c2=st.columns([1,1.5],gap="large")
        with c1:
            hu=st.slider("Hue 0-360°",0,360,210,key="hw_h")
            sa=st.slider("Saturação",0.0,1.0,0.85,0.01,key="hw_s")
            va=st.slider("Brilho",0.0,1.0,0.9,0.01,key="hw_v")
            alh=st.slider("Alpha",0.0,1.0,1.0,0.01,key="hw_a")
        with c2:
            r,g,b=hsv_to_rgb(hu,sa,va)
            color_preview(r,g,b,alh)
            color_codes(r,g,b,alh,"hw")
            st.markdown("**Paletas relacionadas:**")
            # FIX: não desempacotar a tupla no zip — manter como tuple
            palette_colors = [
                hsv_to_rgb((hu+180)%360, sa, va),
                hsv_to_rgb((hu+30)%360,  sa, va),
                hsv_to_rgb((hu-30)%360,  sa, va),
            ]
            palette_labels = ["Complementar","Análoga +30°","Análoga -30°"]
            pcols = st.columns(3)
            for pcol, rgb_t, lbl in zip(pcols, palette_colors, palette_labels):
                with pcol:
                    pr2, pg2, pb2 = rgb_t
                    st.caption(lbl)
                    color_preview(pr2, pg2, pb2, alh, 60)

    with tabs[3]:
        if st.button("🎲 Gerar",type="primary",key="rnd_b"):
            st.session_state["rnd_r"]=random.randint(0,255)
            st.session_state["rnd_g"]=random.randint(0,255)
            st.session_state["rnd_b"]=random.randint(0,255)
        r=st.session_state.get("rnd_r",42)
        g=st.session_state.get("rnd_g",135)
        b=st.session_state.get("rnd_b",193)
        color_preview(r,g,b,1.0)
        color_codes(r,g,b,1.0,"rnd")

    st.markdown('</div>',unsafe_allow_html=True)



# ─────────────────────────────────────────────
# 11. LOGIN PAGE
# ─────────────────────────────────────────────
def page_login():
    tab_sel  = st.session_state.auth_tab
    is_login = (tab_sel == "login")

    st.markdown("""
    <style>
    /* ── Dark gradient full-page ──────────────────── */
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main {
        background: linear-gradient(145deg,#060d1a 0%,#0b2040 50%,#060d1a 100%) !important;
        min-height: 100vh !important;
    }

    .block-container           { padding: 3vh 4vw 0 !important; max-width:100% !important; }

    /* ── White card: the border-container in right col ── */
    [data-testid="stColumn"]:nth-child(3)
    [data-testid="stVerticalBlock"] {
        background    : white !important;
        border-radius : 28px !important;
        border        : none !important;
        padding       : 44px 48px !important;
        box-shadow    : 0 40px 100px rgba(0,0,0,.55),
                        0 8px 30px rgba(0,0,0,.25) !important;
    }
    /* remove any internal padding Streamlit adds */
    [data-testid="stColumn"]:nth-child(3)
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        padding: 0 !important;
        gap: 0 !important;
    }

    /* ── Tab pill buttons ─────────────────────────── */
    .pill-wrap [data-testid="stHorizontalBlock"] {
        background    : #f1f5f9;
        border-radius : 14px;
        padding       : 5px;
        gap           : 5px !important;
    }
    .pill-inactive button {
        background   : transparent !important;
        color        : #64748b !important;
        border       : none !important;
        border-radius: 10px !important;
        font-size    : 13.5px !important;
        font-weight  : 600 !important;
        height       : 42px !important;
        box-shadow   : none !important;
    }
    .pill-inactive button:hover {
        background: rgba(255,255,255,.7) !important;
        color: #374151 !important;
    }
    .pill-active button {
        background   : white !important;
        color        : #0078d4 !important;
        border       : none !important;
        border-radius: 10px !important;
        font-size    : 13.5px !important;
        font-weight  : 700 !important;
        height       : 42px !important;
        box-shadow   : 0 1px 8px rgba(0,0,0,.12),
                       0 0 0 1.5px rgba(0,120,212,.14) !important;
    }

    /* ── Labels dark ──────────────────────────────── */
    [data-testid="stColumn"]:nth-child(3) label {
        color          : #374151 !important;
        font-size      : 11px !important;
        font-weight    : 700 !important;
        text-transform : uppercase !important;
        letter-spacing : .7px !important;
    }

    /* ── Text inputs ──────────────────────────────── */
    [data-testid="stColumn"]:nth-child(3) input {
        background    : #f8fafc !important;
        border        : 1.5px solid #e2e8f0 !important;
        border-radius : 12px !important;
        padding       : 11px 15px !important;
        font-size     : 14px !important;
        color         : #0f172a !important;
    }
    [data-testid="stColumn"]:nth-child(3) input:focus {
        border-color : #0078d4 !important;
        box-shadow   : 0 0 0 3px rgba(0,120,212,.09) !important;
        background   : white !important;
    }

    /* ── Submit button ────────────────────────────── */
    [data-testid="stColumn"]:nth-child(3)
    [data-testid="stFormSubmitButton"] button {
        background    : linear-gradient(135deg,#0078d4,#0057a8) !important;
        border        : none !important;
        border-radius : 12px !important;
        padding       : 13px !important;
        font-size     : 14px !important;
        font-weight   : 700 !important;
        letter-spacing: .3px !important;
        box-shadow    : 0 4px 18px rgba(0,120,212,.38) !important;
        margin-top    : 10px !important;
    }
    [data-testid="stColumn"]:nth-child(3)
    [data-testid="stFormSubmitButton"] button:hover {
        transform  : translateY(-1px) !important;
        box-shadow : 0 6px 22px rgba(0,120,212,.50) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    if current_user() is None:
        st.markdown("""
        <style>
        [data-testid="stSidebar"]  { display: none !important; }
        </style>
        """, unsafe_allow_html=True)

    left_col, _, right_col = st.columns([1.1, 0.06, 0.94])

    # ── LEFT: hero ──────────────────────────────────
    with left_col:
        st.markdown("""
        <div style="padding: 6vh 16px 0 4px">
            <div style="font-size:10px;font-weight:800;letter-spacing:3.5px;
                        text-transform:uppercase;color:#60a5fa;margin-bottom:22px;
                        display:flex;align-items:center;gap:10px">
                <span style="width:28px;height:2px;background:#60a5fa;border-radius:1px;display:block"></span>
                MICROSOFT POWER PLATFORM
            </div>
            <div style="font-size:50px;font-weight:900;color:white;line-height:1.02;
                        letter-spacing:-0.045em;margin-bottom:20px">
                Treinamento<br>
                <span style="background:linear-gradient(90deg,#60a5fa,#a5b4fc);
                    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                    background-clip:text">Interativo</span>
            </div>
            <div style="font-size:14.5px;color:#94a3b8;line-height:1.85;max-width:400px;
                        margin-bottom:40px;border-left:3px solid rgba(96,165,250,.3);
                        padding-left:16px">
                Power Apps, Power Automate, Copilot Studio e Dataverse —
                laboratórios ao vivo, quiz por seção e progresso salvo.
            </div>
            <div class="lf-row"><div class="lf-icon-box">⚡</div><div>
                <div class="lf-text-title"><span class="lf-highlight">Power Apps</span> — Fórmulas &amp; Controles</div>
                <div class="lf-text-desc">40+ fórmulas Power FX interativas com laboratório ao vivo.</div>
            </div></div>
            <div class="lf-row"><div class="lf-icon-box">🔄</div><div>
                <div class="lf-text-title"><span class="lf-highlight">Power Automate</span> — Flows &amp; Conectores</div>
                <div class="lf-text-desc">Aprovações, expressões e integrações com exemplos reais.</div>
            </div></div>
            <div class="lf-row"><div class="lf-icon-box">🤖</div><div>
                <div class="lf-text-title"><span class="lf-highlight">Copilot Studio</span> — Agentes de IA</div>
                <div class="lf-text-desc">Tópicos, fontes de conhecimento e publicação no Teams.</div>
            </div></div>
            <div class="lf-row"><div class="lf-icon-box">🗄️</div><div>
                <div class="lf-text-title"><span class="lf-highlight">Dataverse</span> — Banco de Dados</div>
                <div class="lf-text-desc">Tabelas, relações, segurança por linha e fórmulas.</div>
            </div></div>
        </div>
        """, unsafe_allow_html=True)

    # ── RIGHT: card via st.container(border=True) ───
    with right_col:
        with st.container(border=True):

            # Header
            title_txt = "Bem-vindo de volta 👋" if is_login else "Criar sua conta ✨"
            sub_txt   = ("Entre com seu usuário ou e-mail para continuar"
                         if is_login else
                         "Registre-se gratuitamente para salvar seu progresso")

            st.markdown(f"""
            <div style="margin-bottom:24px">
                <div style="font-size:10px;font-weight:800;letter-spacing:2.5px;
                            text-transform:uppercase;color:#313131;
                            margin-bottom:10px;display:flex;align-items:center;gap:8px">
                    <span style="width:18px;height:2px;background:#313131;
                                 border-radius:1px;display:block"></span>
                    Power Platform Training
                </div>
                <div style="font-size:27px;font-weight:900;color:#646464;
                            letter-spacing:-0.04em;line-height:1.2;margin-bottom:5px">
                    {title_txt}</div>
                <div style="font-size:13.5px;color:#969696;line-height:1.5">{sub_txt}</div>
            </div>
            """, unsafe_allow_html=True)

            # Tab pills
            st.markdown('<div class="pill-wrap">', unsafe_allow_html=True)
            pc1, pc2 = st.columns(2)
            with pc1:
                st.markdown(f'<div class="{"pill-active" if is_login else "pill-inactive"}">', unsafe_allow_html=True)
                if st.button("🔑  Entrar", key="tab_login", use_container_width=True):
                    st.session_state.auth_tab = "login"; st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with pc2:
                st.markdown(f'<div class="{"pill-active" if not is_login else "pill-inactive"}">', unsafe_allow_html=True)
                if st.button("✨  Criar conta", key="tab_reg", use_container_width=True):
                    st.session_state.auth_tab = "register"; st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

            # Form
            if is_login:
                with st.form("login_form", clear_on_submit=False):
                    u_in = st.text_input("Usuário ou e-mail", placeholder="usuario ou email@empresa.com")
                    p_in = st.text_input("Senha", type="password", placeholder="••••••••")
                    sub  = st.form_submit_button("→  Entrar na plataforma",
                                                 use_container_width=True, type="primary")
                    if sub:
                        if not u_in or not p_in:
                            st.error("Preencha todos os campos.")
                        else:
                            user = login_user(u_in, p_in)
                            if user:
                                token = create_session_token(user["id"])
                                st.session_state.user = user
                                st.session_state.page = "home"
                                st.query_params["token"] = token
                                st.rerun()
                            else:
                                st.error("Usuário ou senha incorretos.")
            else:
                with st.form("reg_form", clear_on_submit=False):
                    n_in  = st.text_input("Nome completo", placeholder="Maria da Silva")
                    u_in  = st.text_input("Usuário (sem espaços)", placeholder="maria.silva")
                    e_in  = st.text_input("E-mail", placeholder="maria@empresa.com")
                    p_in  = st.text_input("Senha (mín. 6 caracteres)", type="password", placeholder="••••••••")
                    p2_in = st.text_input("Confirmar senha", type="password", placeholder="••••••••")
                    sub   = st.form_submit_button("→  Criar conta gratuita",
                                                  use_container_width=True, type="primary")
                    if sub:
                        if not all([n_in, u_in, e_in, p_in, p2_in]):
                            st.error("Preencha todos os campos.")
                        elif len(p_in) < 6:
                            st.error("Senha deve ter no mínimo 6 caracteres.")
                        elif p_in != p2_in:
                            st.error("Senhas não coincidem.")
                        elif " " in u_in:
                            st.error("Usuário não pode ter espaços.")
                        else:
                            ok, msg = register_user(u_in, e_in, n_in, p_in)
                            if ok:
                                user = login_user(u_in, p_in)
                                token = create_session_token(user["id"])
                                st.session_state.user = user
                                st.session_state.page = "home"
                                st.query_params["token"] = token
                                st.rerun()
                            else:
                                st.error(msg)

            # Footer
            st.markdown("""
            <div style="text-align:center;margin-top:18px;padding-top:14px;
                        border-top:1px solid #f1f5f9">
                <span style="font-size:11px;color:#94a3b8">
                    🔒 Sessão persistida automaticamente &nbsp;·&nbsp; Sem re-login no F5
                </span>
            </div>
            """, unsafe_allow_html=True)
def page_automate_fundamentos():
    mark_page_visited(current_user()["id"], "automate_fundamentos")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Power Automate","Fundamentos de Flows")
    hero("automate_fundamentos","🔄","Fundamentos — Power Automate","Triggers, ações e tipos de flow. O motor de automação da Power Platform.","Iniciante")

    tabs = st.tabs(["🔵 Tipos de Flow","⚡ Triggers","🎬 Ações Essenciais","🏗️ Boas Práticas"])

    with tabs[0]:
        st.markdown("#### Os 4 Tipos de Flow")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Cloud Flow — Automatizado","Disparado por um evento externo (email, SharePoint, Form).",
                "Quando alguém preenche um formulário, envie aprovação por e-mail.",
                '// Trigger: "Quando um item é criado" (SharePoint)\n// Ação 1: Enviar e-mail de aprovação\n// Ação 2: Aguardar resposta\n// Ação 3: Atualizar campo Status',
                color="#0050d0", tags=["Automatizado","Event-driven"])
            formula_card("Cloud Flow — Instantâneo","Disparado manualmente pelo usuário ou pelo Power Apps.",
                "Botão no Power Apps aciona flow que faz operações complexas.",
                '// Trigger: "Para um item selecionado" (Power Apps)\n// Input: ID do registro\n// Ação: Processar e retornar resultado\noutputs(\'Parse_JSON\')?[\'Status\']',
                color="#0050d0", tags=["Manual","Power Apps"])
        with c2:
            formula_card("Cloud Flow — Agendado","Executa em intervalos definidos (diário, semanal, mensal).",
                "Relatório de pendências todo dia às 8h. Limpeza de dados semanais.",
                '// Trigger: Recorrência\n//   Frequência: Dia\n//   Intervalo: 1\n//   Às: 08:00 (UTC-3)\n// Ação: Obter itens vencidos\n// Ação: Enviar resumo por e-mail',
                color="#0050d0", tags=["Agendado","Recorrência"])
            formula_card("Desktop Flow — RPA","Automatiza tarefas em aplicativos desktop e web.",
                "Preencher formulários legados, extrair dados de sistemas sem API.",
                '// Requer: Power Automate Desktop\n// Compatível: Windows apps, SAP, Web\n// Licença: Premium (Power Automate)\n// Caso de uso: ERP sem API REST',
                color="#7c3aed", tags=["RPA","Desktop","Premium"])

    with tabs[1]:
        st.markdown("#### Triggers mais usados")
        triggers = [
            ("📋 SharePoint","Quando item é criado","Trigger Standard. Use 'Quando um item é criado ou modificado' para cobrir ambos."),
            ("📧 Outlook","Quando e-mail chega","Filtre por assunto, pasta ou remetente para evitar loops."),
            ("📝 Microsoft Forms","Quando resposta é enviada","Ideal para fluxos de aprovação e onboarding."),
            ("📱 Power Apps","Ao chamar flow manualmente","Permite enviar parâmetros e receber resposta (tipo função)."),
            ("⏰ Recorrência","Em intervalo fixo","Especifique timezone para evitar horário de verão incorreto."),
            ("🗂️ Dataverse","Quando linha é criada/modificada","Mais confiável que SharePoint para dados críticos."),
            ("🔗 HTTP","Webhook externo","Premium. Recebe chamadas de qualquer sistema externo."),
        ]
        for ic, t, d in triggers:
            st.markdown(f'<div class="sr"><div style="display:flex;align-items:center;gap:10px"><div style="font-size:20px">{ic}</div><div><div class="sr-nm" style="font-family:inherit;color:#111827">{t}</div><div class="sr-ds">{d}</div></div></div></div>', unsafe_allow_html=True)

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Condição (If/Else)","Bifurca o flow conforme uma condição.",
                "Aprovação vs. rejeição. Urgente vs. normal.",
                '// Condição:\n//   Status is equal to "Aprovado"\n// Sim → Enviar e-mail aprovação\n// Não → Notificar rejeição\n\n// Tip: aninhe até 8 condições',
                color="#0050d0")
            formula_card("Aplicar a cada (For Each)","Itera sobre uma lista de itens.",
                "Processar cada aprovador, cada linha de planilha, cada arquivo.",
                '// Apply to each: items(\'Obter_itens\')?[\'value\']\n//   → Ação por item\n\n// ⚠️ Desative "Execução em série"\n//    para paralelismo automático (até 50x)',
                color="#0050d0")
        with c2:
            formula_card("Aprovação","Fluxo de aprovação nativo com Teams/e-mail.",
                "Aprovação de compras, férias, publicações. Resposta direto no Teams.",
                'Start and wait for an approval:\n  Título: "Aprovação: " & triggerBody()?[\'Title\']\n  Atribuído a: gerente@empresa.com\n  Detalhes: triggerBody()?[\'Descricao\']\n\n// Resposta: outputs?[\'body/outcome\']',
                color="#0d7a0d")
            formula_card("Parse JSON","Processa resposta de APIs e Power Apps.",
                "Sempre use após chamadas HTTP ou Power Apps para acessar campos.",
                '// Esquema gerado automaticamente:\n// Clique "Gerar a partir de amostra"\n// Cole o JSON de exemplo\n// → Campos ficam disponíveis como tokens\n\nbody(\'Parse_JSON\')?[\'campo\']',
                color="#0d7a0d")

    with tabs[3]:
        info_box("⚠️ <b>Erros comuns:</b> (1) Nunca use \"Obter itens\" sem filtro — baixa tudo. (2) Evite loops de trigger: um item atualizado dispara flow que atualiza o item. Use condicional para checar se mudou de fato.","warning")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### ✅ Boas práticas")
            st.markdown("""
- **Nomeie** cada ação descritivamente (não \"HTTP 2\")
- Use **variáveis** em vez de expressões aninhadas longas
- Sempre configure **'Executar após'** para erros
- Prefira **Dataverse** ao SharePoint para dados críticos
- Use **Scope** para agrupar e capturar erros por bloco
- Ative **Histórico de execuções** para debug
- Filtre triggers: `@equals(triggerBody()?['Status'], 'Novo')`
            """)
        with c2:
            st.markdown("##### 📊 Limites importantes")
            st.markdown("""<table class="conn-tbl">
<thead><tr><th>Limite</th><th>Valor</th></tr></thead>
<tbody>
<tr><td>Execuções/dia (Standard)</td><td>10.000</td></tr>
<tr><td>Execuções/dia (Premium)</td><td>500.000</td></tr>
<tr><td>Timeout de ação</td><td>2 horas</td></tr>
<tr><td>Timeout de flow</td><td>30 dias</td></tr>
<tr><td>Itens por "Obter itens"</td><td>5.000 máx.</td></tr>
<tr><td>Paralelismo (Apply to each)</td><td>até 50</td></tr>
</tbody></table>""", unsafe_allow_html=True)

    section_quiz("automate_fundamentos")
    st.markdown('</div>', unsafe_allow_html=True)


def page_automate_expressoes():
    mark_page_visited(current_user()["id"], "automate_expressoes")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Power Automate","Expressões & Funções")
    hero("automate_expressoes","🧮","Expressões & Funções","Transforme dados com expressões — texto, data, lógica e JSON.","Intermediário")

    tabs = st.tabs(["📝 Texto","📅 Datas","🔢 Lógica","📦 Arrays & JSON","🔗 Utilitários"])

    with tabs[0]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Funções de texto")
            st.code("""// Concatenar
concat('Olá, ', triggerBody()?['Nome'], '!')

// Maiúsculo / Minúsculo
toUpper(triggerBody()?['Email'])
toLower(triggerBody()?['Email'])

// Substring
substring('Power Automate', 6, 8)  // → Automate

// Contém
contains(body('HTML')?['assunto'], 'URGENTE')

// Substituir
replace(body()?['Texto'], '\\n', '<br>')

// Comprimento
length(triggerBody()?['Descricao'])

// Remover espaços
trim(triggerBody()?['Nome'])""", language="javascript")
        with c2:
            st.markdown("#### Formatação e split")
            st.code("""// Formatar número
formatNumber(12345.6, '##,###.00', 'pt-BR')
// → 12.345,60

// Split string
split(triggerBody()?['Emails'], ';')
// → array de e-mails

// Join array
join(variables('arrNomes'), ', ')
// → "Ana, Bruno, Carlos"

// Primeiro / Último
first(split(body()?['NomeCompleto'], ' '))
last(split(body()?['NomeCompleto'], ' '))

// Índice
indexOf(variables('arrStatus'), 'Aprovado')""", language="javascript")

    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Funções de data")
            st.code("""// Data atual (UTC)
utcNow()                        // ISO 8601
utcNow('dd/MM/yyyy')            // 13/03/2026
utcNow('dd/MM/yyyy HH:mm')      // 13/03/2026 15:30

// Converter timezone
convertTimeZone(
  utcNow(),
  'UTC',
  'E. South America Standard Time'
)

// Adicionar tempo
addDays(utcNow(), 30)
addHours(utcNow(), -3)
addMinutes(utcNow(), 90)

// Diferença entre datas
dateDifference(
  triggerBody()?['DataInicio'],
  utcNow()
)""", language="javascript")
        with c2:
            st.markdown("#### Formatação de datas")
            st.code("""// Parse de string para data
parseDateTime('13/03/2026', 'dd/MM/yyyy')

// Formatos úteis
formatDateTime(utcNow(), 'yyyy-MM-dd')     // ISO
formatDateTime(utcNow(), 'dd/MM/yyyy')     // BR
formatDateTime(utcNow(), 'MMMM yyyy')      // Março 2026
formatDateTime(utcNow(), 'dddd')           // Sexta-feira

// Comparar datas
less(
  triggerBody()?['Vencimento'],
  utcNow()
)  // → vencido?

// Dia da semana (0=domingo)
dayOfWeek(utcNow())""", language="javascript")

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Condicionais e lógica")
            st.code("""// If inline (ternário)
if(
  equals(triggerBody()?['Status'], 'Urgente'),
  'Alta',
  'Normal'
)

// And / Or
and(
  equals(body()?['Aprovado'], true),
  greater(body()?['Valor'], 1000)
)

// Not
not(empty(triggerBody()?['Descricao']))

// Nulo → valor padrão
coalesce(triggerBody()?['Observacao'], 'Sem observação')

// Verificar nulo
equals(triggerBody()?['Campo'], null)
empty(triggerBody()?['Campo'])""", language="javascript")
        with c2:
            st.markdown("#### Tipos e conversão")
            st.code("""// String para número
int(triggerBody()?['Quantidade'])
float(triggerBody()?['Preco'])

// Número para string
string(variables('numTotal'))

// Boolean
bool(triggerBody()?['Ativo'])

// Tipo do valor
equals(
  string(type(triggerBody()?['ID'])),
  'Integer'
)

// JSON para objeto
json(body('HTTP')?['body'])

// Objeto para JSON string
string(variables('objConfig'))""", language="javascript")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Arrays")
            st.code("""// Criar array
createArray('Ana', 'Bruno', 'Carlos')

// Comprimento
length(body('Obter_itens')?['value'])

// Filtrar array
filter(
  body('Obter_itens')?['value'],
  item()?['Status'] == 'Ativo'
)

// Selecionar coluna
select(
  body('Obter_itens')?['value'],
  item()?['Email']
)

// Unir arrays
union(variables('arr1'), variables('arr2'))

// Intersecção
intersection(variables('arr1'), variables('arr2'))""", language="javascript")
        with c2:
            st.markdown("#### Acessar JSON")
            st.code("""// Propriedade simples
triggerBody()?['Nome']
body('Parse_JSON')?['ID']

// Propriedade aninhada
body('Parse_JSON')?['Endereco']?['Cidade']

// Item de array (índice 0)
body('Obter_itens')?['value'][0]?['Titulo']

// ? = null-safe (não quebra se nulo)

// OData filter em Obter itens:
Status eq 'Ativo' and Valor gt 100

// Expand para lookup:
$expand=Responsavel($select=Email,Title)""", language="javascript")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("guid()","Gera um GUID único.",
                "ID único para registros, nomes de arquivos únicos.",
                "guid()  // → 'f8a3c2d1-...'", color="#0050d0")
            formula_card("base64() / decodeBase64()","Encoding/decoding Base64.",
                "Envio de arquivos em payloads HTTP, armazenamento de imagens.",
                "base64(body('Obter_conteúdo_do_arquivo')?['$content'])\ndecodeBase64(triggerBody()?['data'])",
                color="#0050d0")
        with c2:
            formula_card("uriComponent()","Encode de parâmetros de URL.",
                "Passar strings com caracteres especiais em query strings.",
                "concat('https://api.exemplo.com/busca?q=',\n  uriComponent(triggerBody()?['Termo']))",
                color="#7c3aed")
            formula_card("xpath()","Extrai dados de XML.",
                "Integração com sistemas legados que retornam XML/SOAP.",
                "xpath(xml(body('HTTP')?['body']),\n  '//NomeElemento/text()')",
                color="#7c3aed")

    section_quiz("automate_expressoes")
    st.markdown('</div>', unsafe_allow_html=True)



# ─────────────────────────────────────────────
# EXTEND ALL_QUESTIONS with Power Platform topics
# ─────────────────────────────────────────────
ALL_QUESTIONS.extend([
    # ── AUTOMATE FUNDAMENTOS ──
    {"id":35,"cat":"Automate-Fundamentos","q":"Qual tipo de flow é disparado automaticamente por um evento externo?",
     "opts":["Flow Instantâneo","Flow Agendado","Flow Automatizado","Desktop Flow"],"ans":2,
     "exp":"**Cloud Flow Automatizado** dispara por eventos: item criado no SharePoint, e-mail recebido, form enviado."},
    {"id":36,"cat":"Automate-Fundamentos","q":"Como enviar parâmetros do Power Apps para um Flow e receber resposta?",
     "opts":["Não é possível","Trigger 'Instantâneo' com inputs/outputs definidos","Apenas via variáveis globais","Via HTTP connector"],"ans":1,
     "exp":"Use o trigger **Para um Power App ou fluxo** — defina inputs no trigger e outputs no 'Responder ao Power App'."},
    {"id":37,"cat":"Automate-Fundamentos","q":"O que acontece se 'Executar após' não for configurado e uma ação falhar?",
     "opts":["O flow continua normalmente","O flow para e marca como falha sem executar ações seguintes","O flow reinicia do início","Aparece popup de erro para o usuário"],"ans":1,
     "exp":"Sem **Executar após** configurado, uma falha para o flow. Configure 'Executar após: com falha' para tratamento de erros."},
    {"id":38,"cat":"Automate-Fundamentos","q":"Apply to Each com 'Execução em série' DESATIVADA faz o quê?",
     "opts":["Executa um item por vez em sequência","Executa itens em paralelo (até 50 simultâneos)","Ignora erros automaticamente","Aumenta o limite de itens"],"ans":1,
     "exp":"Desativar a execução em série ativa o **paralelismo** — até 50 itens simultâneos, muito mais rápido."},
    {"id":39,"cat":"Automate-Fundamentos","q":"Qual é o limite padrão de execuções/dia em um plano Standard?",
     "opts":["1.000","5.000","10.000","100.000"],"ans":2,
     "exp":"Planos **Standard** têm 10.000 execuções/dia. Planos Premium chegam a 500.000."},

    # ── AUTOMATE EXPRESSÕES ──
    {"id":40,"cat":"Automate-Expressões","q":"Como acessar uma propriedade aninhada de forma null-safe em uma expressão?",
     "opts":["body('Acao').prop.subprop","body('Acao')?['prop']?['subprop']","get(body('Acao'), 'prop.subprop')","null(body('Acao'), 'prop')"],"ans":1,
     "exp":"O operador **?** torna o acesso null-safe — se a propriedade não existir, retorna null em vez de erro."},
    {"id":41,"cat":"Automate-Expressões","q":"Qual função retorna a data/hora atual em UTC?",
     "opts":["now()","today()","utcNow()","currentDate()"],"ans":2,
     "exp":"**utcNow()** retorna a data/hora atual em UTC. Use formatDateTime() para formatar."},
    {"id":42,"cat":"Automate-Expressões","q":"Como fornecer um valor padrão quando uma expressão retorna null?",
     "opts":["ifNull(expr, 'padrão')","defaultValue(expr, 'padrão')","coalesce(expr, 'padrão')","or(expr, 'padrão')"],"ans":2,
     "exp":"**coalesce()** retorna o primeiro valor não-nulo da lista — perfeito para valores padrão."},
    {"id":43,"cat":"Automate-Expressões","q":"Para iterar sobre resultados de 'Obter itens' do SharePoint, qual é o caminho correto?",
     "opts":["outputs('Obter_itens')","body('Obter_itens')","body('Obter_itens')?['value']","items('Obter_itens')"],"ans":2,
     "exp":"Resultados de 'Obter itens' ficam em **body('Acao')?['value']** — um array de objetos."},
    {"id":44,"cat":"Automate-Expressões","q":"Como converter uma string para número inteiro em uma expressão?",
     "opts":["number(expr)","parse(expr)","int(expr)","toInteger(expr)"],"ans":2,
     "exp":"**int(expr)** converte string para inteiro. Use **float(expr)** para decimais."},

    # ── COPILOT TÓPICOS ──
    {"id":45,"cat":"Copilot-Tópicos","q":"O que é um Tópico no Copilot Studio?",
     "opts":["Um banco de dados de perguntas","Uma unidade de conversa com trigger phrases e nós de diálogo","Um conector externo","Um modelo de linguagem separado"],"ans":1,
     "exp":"Um **Tópico** é a unidade básica de conversa — contém frases de ativação e um fluxo de nós de diálogo."},
    {"id":46,"cat":"Copilot-Tópicos","q":"Qual nó é usado para coletar informação do usuário e armazenar em variável?",
     "opts":["Nó de Mensagem","Nó de Pergunta","Nó de Ação","Nó de Condição"],"ans":1,
     "exp":"O **Nó de Pergunta** exibe uma mensagem, aguarda a resposta e armazena na variável especificada."},
    {"id":47,"cat":"Copilot-Tópicos","q":"Como chamar um Power Automate flow a partir do Copilot Studio?",
     "opts":["Via Nó HTTP","Via Nó de Ação → 'Chamar uma ação'","Não é possível integrar","Via código personalizado"],"ans":1,
     "exp":"Use **Nó de Ação → Chamar uma ação** — selecione o flow, mapeie inputs/outputs."},
    {"id":48,"cat":"Copilot-Tópicos","q":"O que são Trigger Phrases?",
     "opts":["Palavras reservadas do sistema","Frases de exemplo que ativam o tópico quando ditas pelo usuário","Comandos de administrador","Palavras-chave de SEO"],"ans":1,
     "exp":"**Trigger Phrases** são frases de exemplo — o AI reconhece variações similares automaticamente."},
    {"id":49,"cat":"Copilot-Tópicos","q":"Qual é o tópico especial disparado quando nenhum outro tópico é reconhecido?",
     "opts":["Fallback","Default Topic","On Error","Conversa não reconhecida"],"ans":0,
     "exp":"O tópico **Fallback** (ou 'Escalonamento') é acionado quando a intenção do usuário não é reconhecida."},

    # ── COPILOT ENTIDADES ──
    {"id":50,"cat":"Copilot-Entidades","q":"Para que servem as Entidades no Copilot Studio?",
     "opts":["Conectar com bancos de dados","Extrair informações específicas das mensagens do usuário","Criar novos tópicos automaticamente","Configurar permissões de acesso"],"ans":1,
     "exp":"**Entidades** extraem dados estruturados da fala do usuário (email, número, data, opção personalizada)."},
    {"id":51,"cat":"Copilot-Entidades","q":"Qual entidade built-in reconhece automaticamente datas como 'amanhã' ou 'próxima semana'?",
     "opts":["Entidade Texto","Entidade Número","Entidade Data e Hora","Entidade Personalizada"],"ans":2,
     "exp":"A entidade **Data e Hora** resolve expressões relativas como 'amanhã', 'próxima segunda', '14h'."},
    {"id":52,"cat":"Copilot-Entidades","q":"Como publicar um agente do Copilot Studio para o Microsoft Teams?",
     "opts":["Não é possível integrar com Teams","Via Publicar → Canais → Microsoft Teams","Via Power Apps","Manualmente via manifest.json"],"ans":1,
     "exp":"Em **Publicar → Canais → Microsoft Teams** — em poucos cliques o agente vira um app de Teams."},

    # ── DATAVERSE TABELAS ──
    {"id":53,"cat":"Dataverse-Tabelas","q":"Qual é a vantagem principal do Dataverse sobre o SharePoint?",
     "opts":["É gratuito para todos","Suporta relações reais, segurança por linha e delegação completa","Tem mais colunas disponíveis","É mais fácil de usar"],"ans":1,
     "exp":"Dataverse oferece **relações relacionais reais**, segurança granular por linha e delegação quase total."},
    {"id":54,"cat":"Dataverse-Tabelas","q":"O que é a coluna 'Primary Name' em uma tabela Dataverse?",
     "opts":["O ID numérico auto-incrementado","A coluna de texto principal que identifica o registro","A chave estrangeira","Uma coluna calculada obrigatória"],"ans":1,
     "exp":"**Primary Name** é a coluna de texto principal — aparece em lookups e é usada como rótulo do registro."},
    {"id":55,"cat":"Dataverse-Tabelas","q":"Qual tipo de tabela Dataverse tem linhas que PERTENCEM a um usuário ou equipe específicos?",
     "opts":["Tabela Padrão","Tabela de Atividade","Tabela de Propriedade do Usuário/Equipe","Tabela Virtual"],"ans":2,
     "exp":"Tabelas com **propriedade de Usuário ou Equipe** habilitam segurança por linha baseada em dono do registro."},
    {"id":56,"cat":"Dataverse-Tabelas","q":"Como acessar dados do Dataverse em uma Power App sem criar collection?",
     "opts":["Não é possível direto","Adicionando a tabela como fonte de dados e usando Filter/LookUp diretamente","Apenas via Power Automate","Via SharePoint sync"],"ans":1,
     "exp":"Basta **adicionar a tabela como fonte** — Filter/LookUp/Patch funcionam diretamente com delegação."},

    # ── DATAVERSE SEGURANÇA ──
    {"id":57,"cat":"Dataverse-Segurança","q":"O que é um Security Role no Dataverse?",
     "opts":["Uma senha de acesso","Um conjunto de permissões para tabelas e campos (Create/Read/Update/Delete)","Um grupo do Azure AD","Uma licença especial"],"ans":1,
     "exp":"**Security Role** define quais operações (CRUD) um usuário pode fazer em cada tabela — granularidade por linha."},
    {"id":58,"cat":"Dataverse-Segurança","q":"Qual recurso permite que um usuário veja apenas seus PRÓPRIOS registros?",
     "opts":["Column Security Profile","Business Unit","Row-Level Security (RLS) via Security Role","Apenas via código personalizado"],"ans":2,
     "exp":"**Row-Level Security** via Security Role — configure 'User' no nível de acesso de leitura."},
    {"id":59,"cat":"Dataverse-Segurança","q":"Para que serve o Column Security Profile no Dataverse?",
     "opts":["Criptografar colunas","Ocultar ou restringir acesso a colunas específicas por usuário/perfil","Definir validações de campo","Criar índices de busca"],"ans":1,
     "exp":"**Column Security Profile** controla quem pode ler/atualizar colunas sensíveis (ex: salário, CPF)."},
])

# Extend PAGE_QUIZ_CATS with new category colors
CAT_COLORS.update({
    "Automate-Fundamentos":"#0050d0",
    "Automate-Expressões":"#0c2344",
    "Copilot-Tópicos":"#5c2d91",
    "Copilot-Entidades":"#3b0764",
    "Dataverse-Tabelas":"#134e4a",
    "Dataverse-Segurança":"#14532d",
})


# ─────────────────────────────────────────────
# COPILOT STUDIO — Tópicos & Diálogos
# ─────────────────────────────────────────────
def page_copilot_topicos():
    mark_page_visited(current_user()["id"], "copilot_topicos")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Copilot Studio","Tópicos & Diálogos")
    hero("copilot_topicos","🤖","Tópicos & Diálogos","Construa conversas inteligentes com trigger phrases, nós de diálogo e integração com Power Automate.","Intermediário")

    tabs = st.tabs(["🗣️ Tópicos","🔀 Nós de Diálogo","⚡ Ações & Flows","🌐 Canais de Publicação"])

    with tabs[0]:
        info_box("🤖 <b>Copilot Studio</b> (antigo Power Virtual Agents) permite criar agentes de IA conversacionais sem código, integrados a toda a Power Platform e Microsoft 365.","info")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Criando um Tópico","Cada tópico é uma unidade de conversa autônoma.",
                "Crie tópicos para cada intenção do usuário: consultar pedido, abrir chamado, solicitar férias.",
                '''// Estrutura de um tópico:
// 1. Nome: "Consultar Status de Pedido"
// 2. Trigger Phrases (mínimo 5):
//    - "onde está meu pedido"
//    - "status do pedido"
//    - "rastrear compra"
//    - "quando chega meu produto"
//    - "meu pedido foi enviado?"
// 3. Nós de diálogo
// 4. Encerramento da conversa''',
                color="#5c2d91", tags=["NLP","Sem código"])
            formula_card("Tópicos do Sistema","Tópicos especiais que gerenciam o comportamento global.",
                "Customize o tópico Fallback para orientar usuários quando não são compreendidos.",
                '''// Tópicos do sistema importantes:
// • Saudação — primeira mensagem
// • Fallback — intenção não reconhecida
// • Escalonamento — transferir p/ humano
// • Fim da conversa — encerramento
// • Erro — quando algo falha
// Acesse: Tópicos → Sistema''',
                color="#5c2d91")
        with c2:
            formula_card("Trigger Phrases & NLP","O modelo de IA reconhece variações naturais.",
                "Não precisa listar todas as variações — o NLP entende similar. Foque em frases diversas.",
                '''// ✅ Boas trigger phrases (diversas):
"quero abrir um chamado"
"preciso de suporte técnico"
"tem algum problema com meu acesso"
"não consigo entrar no sistema"

// ❌ Ruins (muito similares):
"abrir chamado"
"criar chamado"
"novo chamado"
"fazer chamado"''',
                color="#7c3aed")
            formula_card("Variáveis em Tópicos","Armazene e reutilize informações do usuário.",
                "Variáveis de tópico (locais) vs. globais. Use globais para compartilhar entre tópicos.",
                '''// Nó de Pergunta → salva em variável:
// Pergunta: "Qual é o número do seu pedido?"
// Salvar em: Topic.NumeroPedido (local)
//   ou:      Global.NumeroPedido (global)

// Usar em mensagem:
// "Procurando o pedido {Topic.NumeroPedido}..."

// Condição:
// Topic.NumeroPedido is not blank''',
                color="#7c3aed")

    with tabs[1]:
        st.markdown("#### Tipos de Nós de Diálogo")
        nos = [
            ("💬","Mensagem","Envia texto, imagem, card adaptativo ou vídeo para o usuário. Suporta Markdown."),
            ("❓","Pergunta","Faz uma pergunta e aguarda resposta. Salva em variável com tipo (texto, número, data, opção, etc.)."),
            ("🔀","Condição","Bifurca o fluxo com If/Else baseado em variável ou expressão. Suporta múltiplas ramificações."),
            ("⚡","Ação","Chama Power Automate flow, HTTP externo, conector ou skill. Mapeia inputs/outputs."),
            ("📌","Ir para outro tópico","Redireciona para outro tópico mantendo contexto. Útil para autenticação ou sub-fluxos."),
            ("🏁","Encerrar conversa","Finaliza a sessão. Pode perguntar satisfação (thumbs up/down)."),
            ("👤","Transferir p/ agente","Escala para atendente humano via Omnichannel for Customer Service."),
            ("📊","Variável","Define ou modifica o valor de uma variável diretamente, sem perguntar ao usuário."),
        ]
        for ic, t, d in nos:
            st.markdown(f'<div class="sr"><div style="display:flex;align-items:center;gap:12px"><div style="font-size:22px;width:30px">{ic}</div><div><div class="sr-nm" style="font-family:inherit;color:#111827;font-size:13px">{t}</div><div class="sr-ds">{d}</div></div></div></div>', unsafe_allow_html=True)

        st.markdown("#### Exemplo: Fluxo de aprovação de férias")
        st.code('''[Trigger] "quero solicitar férias" / "tirar férias" / "pedir folga"
    ↓
[Mensagem] "Olá {Global.NomeUsuario}! Vou te ajudar com a solicitação de férias."
    ↓
[Pergunta] "Qual a data de início?" → Topic.DataInicio (tipo: Data)
    ↓
[Pergunta] "Quantos dias?" → Topic.QtdDias (tipo: Número)
    ↓
[Condição] Topic.QtdDias > 30?
    │ Sim → [Mensagem] "Máximo de 30 dias por solicitação."
    │        → [Ir para] Solicitar Férias (recomeça)
    └ Não → [Ação] Chamar Flow "Criar Solicitação de Férias"
                Inputs:  DataInicio = Topic.DataInicio
                         QtdDias    = Topic.QtdDias
                         Email      = Global.EmailUsuario
                Outputs: Topic.NumeroSolicitacao
    ↓
[Mensagem] "✅ Solicitação {Topic.NumeroSolicitacao} criada! Seu gestor receberá o e-mail de aprovação."
    ↓
[Encerrar conversa]''', language="text")

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Chamar Power Automate","Integre qualquer sistema via flow.",
                "Crie o flow com trigger 'Para um Power App ou fluxo' — aparece automaticamente no Copilot Studio.",
                '''// No Copilot Studio → Nó de Ação:
// "Chamar uma ação" → selecione o flow

// Inputs mapeados (Copilot → Flow):
//   numeroPedido: Topic.NumeroPedido

// Outputs mapeados (Flow → Copilot):
//   statusPedido: Topic.StatusPedido
//   previsaoEntrega: Topic.Previsao

// Usar na mensagem seguinte:
// "Seu pedido está: {Topic.StatusPedido}"''',
                color="#0050d0")
            formula_card("Autenticação com Azure AD","Identifique quem está falando com o agente.",
                "Configure SSO com Azure AD para obter nome e e-mail sem perguntar ao usuário.",
                '''// Configuração → Segurança → Autenticação:
// Tipo: Azure Active Directory v2

// Variáveis disponíveis automaticamente:
// System.User.DisplayName  → "Maria Silva"
// System.User.Email        → "maria@emp.com"
// System.User.Id           → OID do usuário

// Use para personalizar mensagens:
// "Olá, {System.User.DisplayName}!"''',
                color="#0050d0")
        with c2:
            formula_card("Cards Adaptáveis","UI rica nas respostas do agente.",
                "Use Adaptive Cards para exibir tabelas, botões de ação e formulários inline.",
                '''// Nó de Mensagem → Adicionar → Adaptive Card
// Designer: https://adaptivecards.io/designer

// Exemplo simples (JSON):
{
  "type": "AdaptiveCard",
  "body": [{
    "type": "TextBlock",
    "text": "Pedido: ${numeroPedido}",
    "weight": "Bolder"
  }, {
    "type": "FactSet",
    "facts": [
      {"title": "Status", "value": "${status}"}
    ]
  }]
}''',
                color="#7c3aed")
            formula_card("Escalação para humano","Transfira para atendente quando necessário.",
                "Configure condição para escalar: fora do horário, problema complexo, solicitação do usuário.",
                '''// Nó de Transferência p/ agente:
// Mensagem de contexto para o agente:
// "Cliente {System.User.DisplayName} com
//  problema: {Topic.DescricaoProblema}
//  Tentativas: {Topic.Tentativas}"

// Integra com:
// • Omnichannel for Customer Service
// • Genesys / Nuance
// • ServiceNow''',
                color="#7c3aed")

    with tabs[3]:
        st.markdown("#### Canais de publicação disponíveis")
        canais = [
            ("💬","Microsoft Teams","Instale como app de Teams — distribuição pelo admin center. Mais usado em empresas.","Standard"),
            ("🌐","Site (Web Chat)","Embed via snippet de código em qualquer página HTML.","Standard"),
            ("📱","App Mobile","Via Direct Line API + SDK nativo iOS/Android.","Standard"),
            ("📧","E-mail","Responde e-mails recebidos — configuração via Exchange/Outlook.","Standard"),
            ("📞","Telefonia","Integra com Azure Communication Services para voz.","Premium"),
            ("🔗","API Direta (Direct Line)","Integre com qualquer sistema via REST API.","Standard"),
        ]
        for ic, canal, desc, tier in canais:
            color = "#d1fae5" if tier=="Standard" else "#fef3c7"
            tcolor = "#065f46" if tier=="Standard" else "#92400e"
            st.markdown(f'<div class="sr" style="display:flex;align-items:center;gap:14px"><div style="font-size:24px">{ic}</div><div style="flex:1"><div style="font-weight:700;color:#111827;font-size:13px">{canal}</div><div style="font-size:12px;color:#6b7280;margin-top:2px">{desc}</div></div><span style="background:{color};color:{tcolor};font-size:10px;font-weight:700;padding:3px 9px;border-radius:10px;white-space:nowrap">{tier}</span></div>', unsafe_allow_html=True)

    section_quiz("copilot_topicos")
    st.markdown('</div>', unsafe_allow_html=True)


def page_copilot_entidades():
    mark_page_visited(current_user()["id"], "copilot_entidades")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Copilot Studio","Entidades & Variáveis")
    hero("copilot_entidades","🧩","Entidades & Variáveis","Extraia dados estruturados das mensagens e gerencie estado da conversa.","Intermediário")

    tabs = st.tabs(["📦 Entidades Built-in","✏️ Entidades Personalizadas","📊 Variáveis","🔧 Tópicos do Sistema"])

    with tabs[0]:
        st.markdown("#### Entidades nativas do Copilot Studio")
        entidades = [
            ("📅","Data e Hora","Reconhece: 'amanhã', 'próxima sexta', '15/03', '14h30', 'daqui a 2 horas'","Data/Hora"),
            ("🔢","Número","Reconhece dígitos por extenso: 'cinco', '5', 'cinco mil'","Número"),
            ("📧","Email","Extrai endereços de e-mail válidos da frase do usuário","Texto"),
            ("📞","Telefone","Números de telefone em vários formatos nacionais/internacionais","Texto"),
            ("🌐","URL","Endereços web (http, https, www)","Texto"),
            ("💰","Moeda","Valores monetários: 'R$ 150', 'cinquenta reais', '$20'","Número"),
            ("📍","CEP / Endereço","Reconhece padrões de CEP e logradouros (en-US e pt-BR)","Texto"),
            ("⏱️","Duração","'2 horas', 'meia hora', 'três dias'","Duração"),
            ("🌡️","Temperatura","'30 graus', '100°F'","Número"),
            ("📊","Porcentagem","'50%', 'cinquenta por cento'","Número"),
        ]
        for ic, nome, desc, tipo in entidades:
            st.markdown(f'<div class="sr"><div style="display:flex;align-items:center;gap:12px"><div style="font-size:20px">{ic}</div><div style="flex:1"><div class="sr-nm" style="font-family:inherit;color:#111827">{nome}</div><div class="sr-ds">{desc}</div></div><span style="background:#ede9fe;color:#5c2d91;font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px">{tipo}</span></div></div>', unsafe_allow_html=True)

    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Lista Fechada","O usuário escolhe entre opções pré-definidas.",
                "Categorias, departamentos, tipos de problema — qualquer conjunto fixo de valores.",
                '''// Criar entidade personalizada:
// Tipo: Lista Fechada
// Nome: "Departamento"
// Itens:
//   • TI (sinônimos: tecnologia, suporte)
//   • RH (sinônimos: recursos humanos, pessoal)
//   • Financeiro (sinônimos: finanças, fiscal)
//   • Jurídico (sinônimos: juridico, legal)

// No Nó de Pergunta:
// "Para qual departamento?" → Entidade: Departamento
// → salva em Topic.Departamento''',
                color="#5c2d91")
        with c2:
            formula_card("Expressão Regular","Extrai padrões específicos de texto.",
                "Números de matrícula, códigos de pedido, placas de veículo — qualquer padrão fixo.",
                '''// Tipo: Expressão Regular
// Nome: "NumeroPedido"
// Padrão: PED-\\d{6}
// Exemplo de match: "PED-123456"

// Outros exemplos úteis:
// CPF:   \\d{3}\\.\\d{3}\\.\\d{3}-\\d{2}
// CNPJ:  \\d{2}\\.\\d{3}\\.\\d{3}/\\d{4}-\\d{2}
// Matrícula: [A-Z]{2}\\d{5}
// Placa: [A-Z]{3}\\d[A-Z0-9]\\d{2}''',
                color="#7c3aed")
        info_box("💡 <b>Dica:</b> Sempre adicione sinônimos nas entidades de lista. O usuário pode dizer 'TI', 'tecnologia', 'suporte técnico' — todos devem mapear para o mesmo valor.","info")

    with tabs[2]:
        st.markdown("#### Escopo das variáveis")
        c1,c2,c3 = st.columns(3)
        for col, nome, scope, cor, desc, ex in [
            (c1,"Topic.*","Local ao tópico","#ede9fe","Criada no nó de Pergunta. Perdida ao sair do tópico.",
             "Topic.NumeroPedido\nTopic.DataSelecionada\nTopic.Confirmado"),
            (c2,"Global.*","Disponível em todos os tópicos","#d1fae5","Persistente durante toda a conversa. Defina no início.",
             "Global.NomeUsuario\nGlobal.EmailUsuario\nGlobal.Perfil"),
            (c3,"System.*","Gerada pelo sistema","#e0f2fe","Preenchida automaticamente (auth, hora, canal).",
             "System.User.DisplayName\nSystem.User.Email\nSystem.Channel"),
        ]:
            with col:
                st.markdown(f'<div style="background:{cor};border-radius:12px;padding:16px;height:100%"><div style="font-weight:800;color:#111827;font-size:13px;margin-bottom:4px">{nome}</div><div style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">{scope}</div><div style="font-size:12px;color:#374151;margin-bottom:10px">{desc}</div></div>', unsafe_allow_html=True)
                st.code(ex, language="text")

        st.markdown("#### Operações com variáveis")
        st.code('''// Definir variável (Nó de Variável):
Topic.TentativasRestantes = 3

// Decrementar:
Topic.TentativasRestantes = Topic.TentativasRestantes - 1

// Concatenar:
Topic.MensagemFinal = "Olá, " + System.User.DisplayName + "!"

// Verificar em Condição:
Topic.Confirmado is equal to true
Topic.NumeroPedido is not blank
Topic.TentativasRestantes is less than 1''', language="text")

    with tabs[3]:
        st.markdown("#### Customizando tópicos do sistema")
        topicos_sis = [
            ("🙋","Saudação","Primeira mensagem ao iniciar conversa. Personalize com nome do usuário (System.User.DisplayName) e opções de menu rápido."),
            ("🤷","Fallback","Disparado quando o NLP não reconhece a intenção. Ofereça sugestões, escale para humano ou peça para reformular."),
            ("👋","Fim da Conversa","Exiba pesquisa de satisfação, ofereça resumo do atendimento ou direcione para autoatendimento."),
            ("⬆️","Escalonamento","Defina a mensagem antes de transferir para humano e informe o contexto ao agente."),
            ("🔐","Login Necessário","Exibida quando a ação requer autenticação e o usuário ainda não está logado."),
            ("⚠️","Erro","Fallback para erros técnicos. Sempre ofereça alternativa de contato."),
        ]
        for ic, nome, desc in topicos_sis:
            st.markdown(f'<div class="sr"><div style="display:flex;gap:12px"><div style="font-size:22px">{ic}</div><div><div style="font-weight:700;color:#111827;font-size:13px">{nome}</div><div style="font-size:12px;color:#6b7280;margin-top:2px;line-height:1.5">{desc}</div></div></div></div>', unsafe_allow_html=True)

    section_quiz("copilot_entidades")
    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# DATAVERSE — Tabelas & Relações
# ─────────────────────────────────────────────
def page_dataverse_tabelas():
    mark_page_visited(current_user()["id"], "dataverse_tabelas")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Dataverse","Tabelas & Relações")
    hero("dataverse_tabelas","🗄️","Tabelas & Relações","O banco de dados nativo da Power Platform — relações reais, delegação total e segurança por linha.","Intermediário")

    tabs = st.tabs(["📋 Conceitos","🔗 Relações","🏗️ Boas Práticas","⚡ Uso no Power Apps"])

    with tabs[0]:
        info_box("🗄️ <b>Microsoft Dataverse</b> é o banco de dados relacional nativo da Power Platform. Substitui SharePoint em qualquer projeto de médio/grande porte. Requer licença Premium.","info")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Tipos de tabela")
            tipos = [
                ("Padrão","A maioria das tabelas customizadas. Tem dono (usuário ou equipe). Segurança por linha nativa.","#d1fae5","#065f46"),
                ("Atividade","Emails, tarefas, compromissos — integram com o Timeline. Especializada para interações.","#e0f2fe","#075985"),
                ("Virtual","Conecta com dados externos (SQL, OData) sem copiar. Leitura apenas via provider.","#fef9c3","#854d0e"),
                ("Elástica","Para volumes massivos (bilhões de linhas). Partition key obrigatória.","#ede9fe","#5c2d91"),
            ]
            for nome, desc, bg, tc in tipos:
                st.markdown(f'<div style="background:{bg};border-radius:10px;padding:12px 14px;margin-bottom:8px"><div style="font-weight:700;color:{tc};font-size:13px">{nome}</div><div style="font-size:12px;color:#374151;margin-top:3px">{desc}</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("#### Tipos de coluna principais")
            st.code('''// Texto
Text             → até 4.000 chars
Multiline Text   → campo longo
URL, Email, Phone → validados nativamente

// Números
Whole Number     → int
Decimal Number   → float
Currency         → com moeda e troca

// Datas
Date Only        → sem hora
Date and Time    → com hora e timezone

// Opções
Choice           → lista fixa (1 opção)
Choices          → lista fixa (múltiplos)
Yes/No           → booleano

// Relacionamento
Lookup           → N:1 para outra tabela
Customer         → polimórfico (Account ou Contact)
Owner            → usuário ou equipe

// Fórmula                → calculada
Rollup           → agrega linhas filhas
Autonumber       → ID sequencial/custom''', language="text")

    with tabs[1]:
        st.markdown("#### Tipos de relação no Dataverse")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Many-to-One (N:1) — Lookup","A relação mais comum — muitos filhos para um pai.",
                "Pedido → Cliente. Tarefa → Projeto. Funcionário → Departamento.",
                '''// Coluna Lookup na tabela filho:
// "cr123_clienteid" → aponta para "account"

// No Power Apps:
LookUp(Pedidos_TB,
  cr123_clienteid.accountid = selCliente.accountid
)

// Expandir em OData (Power Automate):
$expand=cr123_clienteid($select=name,emailaddress1)

// Filtrar por pai:
Filter(Pedidos_TB,
  cr123_clienteid.accountid = varCliente.accountid
)''',
                color="#134e4a", tags=["Delegável","Mais comum"])
            formula_card("Many-to-Many (N:N)","Relação bidirecional via tabela de intersecção.",
                "Funcionário ↔ Habilidade. Produto ↔ Categoria. Projeto ↔ Tag.",
                '''// Criada automaticamente com tabela de intersecção
// Acesso via Relate/Unrelate no Power Apps:

Relate(Projeto.Membros, Gallery_Func.Selected)
Unrelate(Projeto.Membros, Gallery_Func.Selected)

// Ou via Power Automate:
// Associar — "Associar linhas"
// Operação: POST
// URL: /api/data/v9.2/projetos(id)/membros/$ref''',
                color="#0d9488")
        with c2:
            formula_card("One-to-Many (1:N) — Cascade","Um pai com muitos filhos — regras de cascade.",
                "Projeto tem Tarefas. Cliente tem Pedidos. Configure cascade ao criar a relação.",
                '''// Comportamentos cascade configuráveis:
// Atribuir:   propaga dono ao filho
// Compartilhar: propaga compartilhamento
// Cancelar ref: exclui filhos ao deletar pai
// Remover ref: desvincula (null) ao deletar pai
// Não cascatear: nada acontece

// No Power Apps (filhos do Gallery1.Selected):
Filter(Tarefas_TB,
  cr123_projetoid.cr123_projetoid
  = Gallery1.Selected.cr123_projetoid
)''',
                color="#0d9488", tags=["Cascade","Hierarquia"])
            st.markdown("##### Vantagens sobre SharePoint")
            vantagens = [
                ("✅","Delegação quase total","Filter, Search, Sort, aggregate — tudo vai para o servidor"),
                ("✅","Relações reais","JOINs nativos com expand OData — sem lookups manuais"),
                ("✅","Segurança por linha","Security Role define o que cada user vê/edita/deleta"),
                ("✅","Regras de negócio","Validações server-side sem código — sempre executadas"),
                ("✅","ALM nativo","Soluções, ambientes, CI/CD, controle de versão"),
                ("✅","Auditoria completa","Log de quem criou/editou/deletou cada linha"),
            ]
            for ic, t, d in vantagens:
                st.markdown(f'<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #f3f4f6"><span style="color:#059669;font-weight:700">{ic}</span><div><div style="font-size:12px;font-weight:700;color:#111827">{t}</div><div style="font-size:11px;color:#6b7280">{d}</div></div></div>', unsafe_allow_html=True)

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### ✅ Convenções de nomenclatura")
            st.code('''// Prefixo do publicador (ex: "cr123_")
// Tabelas:
cr123_projeto          // Publisher prefix
cr123_tarefa
cr123_funcionario

// Colunas:
cr123_nome             // texto principal
cr123_status           // choice
cr123_datainicio       // date
cr123_projetoid        // lookup p/ projeto
cr123_valorestimado    // currency

// Choices (global ou local):
cr123_statusopcoes
// Valores: Não iniciado, Em andamento, Concluído

// ⚠️ Nunca use espaços ou acentos em nomes técnicos
// ✅ Display Name pode ter espaços e acentos''', language="text")
        with c2:
            st.markdown("##### 📐 Regras de Negócio (Business Rules)")
            st.code('''// Business Rules rodam server-side
// Sempre executam — independente do app

// Exemplos de uso:
// 1. Tornar campo obrigatório condicionalmente
//    SE Status = "Em Aprovação"
//    ENTÃO Justificativa é obrigatória

// 2. Definir valor padrão
//    SE Tipo = "Urgente"
//    ENTÃO Prioridade = "Alta"

// 3. Mostrar/ocultar campo
//    SE Categoria = "Externo"
//    ENTÃO Mostrar campo "Fornecedor"

// 4. Validação com mensagem customizada
//    SE DataFim < DataInicio
//    ENTÃO Erro: "Data fim inválida"

// Acesso: Tabela → Business Rules → + Nova''', language="text")

    with tabs[3]:
        st.markdown("#### Padrões de uso no Power Apps")
        c1,c2 = st.columns(2)
        with c1:
            st.code('''// ── CRUD completo Dataverse ──

// CREATE
Patch(cr123_projetos, Defaults(cr123_projetos), {
    cr123_nome:        inp_Nome.Text,
    cr123_status:      drp_Status.Selected.Value,
    cr123_datainicio:  dp_Inicio.SelectedDate,
    cr123_responsavel: {
        systemuserid: gblUser.systemuserid
    }
})

// READ (delegável totalmente)
ClearCollect(colProjetos,
    Filter(cr123_projetos,
        cr123_status <> "Cancelado" &&
        createdon >= DateAdd(Today(), -30, TimeUnit.Days)
    )
)

// UPDATE (editar registro existente)
Patch(cr123_projetos, Gallery1.Selected, {
    cr123_status: "Em Andamento",
    modifiedon:   Now()
})

// DELETE
Remove(cr123_projetos, Gallery1.Selected)''', language="powerapps")
        with c2:
            st.code('''// ── Lookup e Expand ──

// Acessar campo da tabela pai (lookup):
Gallery1.Selected.cr123_clienteid.name
Gallery1.Selected.cr123_clienteid.emailaddress1

// Filtrar por lookup:
Filter(cr123_pedidos,
    cr123_clienteid.accountid = varCliente.accountid
)

// ── Choices (opções) ──

// Preencher Dropdown:
Choices(cr123_projetos.cr123_status)

// Usar em Patch:
Patch(cr123_projetos, Defaults(cr123_projetos), {
    cr123_status: drp_Status.Selected
})
// (não use .Value — passe o objeto inteiro)

// ── Aggregate (delegável no Dataverse) ──
CountRows(Filter(cr123_tarefas,
    cr123_status = "Concluída"
))
Sum(cr123_pedidos, cr123_valor)''', language="powerapps")

        info_box("💡 <b>Dataverse vs SharePoint:</b> Use Dataverse quando precisar de relações reais, mais de 5.000 registros, segurança por linha, regras de negócio server-side ou integração com Dynamics 365.","info")

    section_quiz("dataverse_tabelas")
    st.markdown('</div>', unsafe_allow_html=True)


def page_dataverse_seguranca():
    mark_page_visited(current_user()["id"], "dataverse_seguranca")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Dataverse","Segurança & Ambientes")
    hero("dataverse_seguranca","🔒","Segurança & Ambientes","Security Roles, Business Units, Column Security e estratégia de ambientes ALM.","Avançado")

    tabs = st.tabs(["🛡️ Security Roles","🏢 Business Units","🔑 Column Security","🌐 Ambientes & ALM"])

    with tabs[0]:
        info_box("🛡️ <b>Security Roles</b> definem o que cada usuário pode fazer no Dataverse — Create/Read/Write/Delete/Append/Append To/Assign/Share para cada tabela, com escopo configurável.","info")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Escopos de acesso (profundidade)")
            escopos = [
                ("👤","Usuário (User)","Acessa apenas seus próprios registros (Owner = eu)"),
                ("👥","Business Unit","Acessa registros da sua BU e filhos"),
                ("🏢","Pai/Filho","Acessa BU própria + todas as BUs filhas"),
                ("🌍","Organização","Acessa todos os registros da org — cuidado!"),
                ("🚫","Nenhum","Sem acesso para essa operação"),
            ]
            for ic, e, d in escopos:
                st.markdown(f'<div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #f3f4f6"><div style="font-size:18px">{ic}</div><div><div style="font-weight:700;font-size:12px;color:#111827">{e}</div><div style="font-size:12px;color:#6b7280">{d}</div></div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("#### Operações por Security Role")
            st.code('''// Cada tabela tem 8 operações configuráveis:

Create     → Criar novas linhas
Read       → Visualizar registros
Write      → Editar campos
Delete     → Excluir registros
Append     → Relacionar com outra tabela
Append To  → Ser relacionado por outra tabela
Assign     → Mudar o dono do registro
Share      → Compartilhar com outro usuário

// Cada operação tem os 5 escopos acima
// Usuário recebe UNION de todos os roles

// Roles padrão úteis:
// Basic User     → leitura da org, escrita só do user
// System Admin   → tudo (org)
// System Customizer → customizar sem dados

// Criar role customizado:
// Configurações → Segurança → Funções de Segurança''', language="text")

        formula_card("Compartilhamento de registros","Além dos Security Roles, registros podem ser compartilhados individualmente.",
            "Use quando um usuário precisa acessar um registro específico sem mudar o security role.",
            '''// No Power Apps:
// Acesso: Patch(cr123_projetos, varProjeto, {
//   ... campos ...
// })
// Após: chame flow para Sharing API

// Via Power Automate:
// HTTP POST .../api/data/v9.2/GrantAccess
// Body: {
//   "Target": {"@odata.id": "cr123_projetos(id)"},
//   "Grantee": {"@odata.id": "systemusers(userId)"},
//   "AccessMask": "ReadAccess, WriteAccess"
// }''',
            color="#134e4a")

    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Hierarquia de Business Units")
            st.code('''// Organização (raiz)
//   └── BU: Brasil
//         ├── BU: São Paulo
//         │     ├── BU: Vendas SP
//         │     └── BU: TI SP
//         └── BU: Rio de Janeiro

// Cada usuário pertence a uma BU
// Security Role "Business Unit" scope:
//   → acessa registros da BU do usuário

// Security Role "Parent:Child" scope:
//   → acessa BU do usuário + todos os filhos

// Mover usuário de BU:
// Admin → Usuários → Selecionar → Mover p/ BU

// Usar BU para isolar regiões, filiais
// ou departamentos com dados sensíveis''', language="text")
        with c2:
            st.markdown("#### Teams e agrupamento")
            st.code('''// Teams no Dataverse:
// Owner Team   → pode ser dono de registros
// Access Team  → compartilhamento dinâmico

// Atribuir registro a uma equipe (Owner Team):
Patch(cr123_projetos, varProjeto, {
    ownerid: {
        "@odata.type": "Microsoft.Dynamics.CRM.team",
        teamid: varEquipeId
    }
})

// Access Team — adicionar usuário dinamicamente:
// Flow: HTTP POST
// /api/data/v9.2/AddMembersTeam
// {
//   "Teammates": [{"@odata.id": "systemusers(id)"}],
//   "Team": {"@odata.id": "teams(teamId)"}
// }

// Uso: projetos onde múltiplos usuários
// precisam de acesso sem mudar o dono''', language="text")

    with tabs[2]:
        formula_card("Column Security Profile","Controle de acesso por coluna (campo) específico.",
            "Salário, CPF, dados médicos, informações confidenciais — restrinja independente do Security Role.",
            '''// Criar Column Security Profile:
// Admin → Column Security Profiles → + Novo
// Nome: "Dados Financeiros Confidenciais"

// Adicionar usuários/equipes ao perfil
// Configurar permissão por coluna:
//   cr123_salario:  Leitura = Não, Atualização = Não
//   cr123_cpf:      Leitura = Sim, Atualização = Não

// ⚠️ Column Security substitui Security Role
// para essa coluna específica.
// Mesmo Admin não vê sem estar no perfil.

// No Power Apps: campo aparece vazio
// e o Patch ignora silenciosamente.''',
            color="#5c2d91")
        info_box("⚠️ <b>Atenção:</b> Column Security tem precedência sobre Security Roles. Um usuário System Admin NÃO vê colunas protegidas a menos que esteja no Column Security Profile.","warning")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Estratégia de ambientes")
            st.code('''// Modelo recomendado (3 ambientes):

// 🧪 DEV (Desenvolvimento)
//    • Dados fictícios
//    • Todos os devs com System Customizer
//    • Iterações rápidas, sem aprovação

// 🔬 TEST/UAT (Homologação)
//    • Dados anonimizados ou espelho prod
//    • Testes funcionais e de aceitação
//    • Deploy via Solution (managed)
//    • Acesso restrito a testadores

// 🚀 PROD (Produção)
//    • Dados reais
//    • Apenas System Admin faz deploy
//    • Solution managed (não editável diretamente)
//    • Backup e auditoria habilitados

// Regra de ouro:
// NUNCA desenvolva direto em produção''', language="text")
        with c2:
            st.markdown("#### Solutions & ALM")
            st.code('''// Solução = pacote de customizações

// Criar: make.powerapps.com → Soluções → Nova
// Adicionar: Apps, Flows, Tabelas, Choices...

// Exportar (DEV → TEST):
// Tipo: Managed (produção) ou Unmanaged (dev)
// Managed: protegido, sem edição direta
// Unmanaged: editável, para dev apenas

// Importar no ambiente alvo:
// Soluções → Importar → .zip

// Publisher (prefixo):
// Sempre crie seu publisher antes das tabelas
// Prefixo define o cr123_ das colunas
// Não mude após criação!

// Pipeline de CI/CD:
// Power Platform Build Tools (Azure DevOps)
// GitHub Actions para Power Platform''', language="text")

    section_quiz("dataverse_seguranca")
    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SIDEBAR — full Power Platform navigation
# ─────────────────────────────────────────────
def render_sidebar():
    u = current_user()
    if not u: return

    user_id  = u["id"]
    prog     = get_progress(user_id)
    visited  = get_visited(user_id)
    initials = "".join(p[0].upper() for p in u["name"].split()[:2])

    st.sidebar.markdown(f"""
<style>
@keyframes pulse-dot {{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.6;transform:scale(1.3)}}}}
.live-dot{{display:inline-block;width:6px;height:6px;border-radius:50%;background:#10b981;animation:pulse-dot 2s infinite;margin-right:6px}}
</style>
<div class="sb-brand">
  <div class="sb-logo">
    <div class="sb-logo-box">⚡</div>
    <div>
      <div class="sb-logo-text">Power Platform</div>
      <div class="sb-logo-sub"><span class="live-dot"></span>Training v5.0</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    st.sidebar.markdown(f"""
<div class="sb-user-chip">
  <div class="sb-user-av">{initials}</div>
  <div>
    <div class="sb-user-name">{u["name"]}</div>
    <div class="sb-user-email">{u["email"]}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    if st.sidebar.button("🏠  Início", key="sb_home"):
        st.session_state.page = "home"; st.rerun()

    # ── Power Apps ──
    st.sidebar.markdown('<div class="sb-sec-lbl">⚡ POWER APPS</div>', unsafe_allow_html=True)
    for pg, ic, lbl in [
        ("controles",   "🎛️", "Controles"),
        ("formulas",    "∑",  "Fórmulas Power FX"),
        ("navegacao",   "🧭", "Navegação"),
        ("validacao",   "✅", "Validação"),
        ("performance", "⚡", "Performance"),
        ("seguranca",   "🔐", "Segurança"),
        ("conectores",  "🔌", "Conectores"),
        ("variaveis",   "📦", "Variáveis"),
    ]:
        mark = "  ✅" if pg in visited else ""
        if st.sidebar.button(f"{ic}  {lbl}{mark}", key=f"sb_{pg}"):
            st.session_state.page = pg; st.rerun()

    # ── Power Automate ──
    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="sb-sec-lbl">🔄 POWER AUTOMATE</div>', unsafe_allow_html=True)
    for pg, ic, lbl in [
        ("automate_fundamentos",  "🔄", "Fundamentos"),
        ("automate_expressoes",   "🧮", "Expressões"),
        ("automate_conectores",   "🔌", "Conectores"),
        ("automate_aprovacoes",   "✅", "Aprovações"),
        ("automate_erros",        "🐛", "Erros & Debug"),
    ]:
        mark = "  ✅" if pg in visited else ""
        if st.sidebar.button(f"{ic}  {lbl}{mark}", key=f"sb_{pg}"):
            st.session_state.page = pg; st.rerun()

    # ── Copilot Studio ──
    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="sb-sec-lbl">🤖 COPILOT STUDIO</div>', unsafe_allow_html=True)
    for pg, ic, lbl in [
        ("copilot_topicos",      "🤖", "Tópicos & Diálogos"),
        ("copilot_entidades",    "🧩", "Entidades & Variáveis"),
        ("copilot_ia",           "🧠", "IA Generativa"),
        ("copilot_integracao",   "🌐", "Integração & Canais"),
    ]:
        mark = "  ✅" if pg in visited else ""
        if st.sidebar.button(f"{ic}  {lbl}{mark}", key=f"sb_{pg}"):
            st.session_state.page = pg; st.rerun()

    # ── Dataverse ──
    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="sb-sec-lbl">🗄️ DATAVERSE</div>', unsafe_allow_html=True)
    for pg, ic, lbl in [
        ("dataverse_tabelas",    "🗄️", "Tabelas & Relações"),
        ("dataverse_seguranca",  "🔒", "Segurança & Ambientes"),
        ("dataverse_formulas",   "📐", "Fórmulas & Calculadas"),
        ("dataverse_apps",       "⚡", "Power Apps + Dataverse"),
    ]:
        mark = "  ✅" if pg in visited else ""
        if st.sidebar.button(f"{ic}  {lbl}{mark}", key=f"sb_{pg}"):
            st.session_state.page = pg; st.rerun()

    # ── Tools ──
    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="sb-sec-lbl">🛠️ FERRAMENTAS</div>', unsafe_allow_html=True)
    for pg, ic, lbl in [
        ("cheatsheet", "📋", "Cheat Sheet"),
        ("busca",      "🔍", "Busca Global"),
        ("quiz",       "🧠", f"Quiz  ({len(ALL_QUESTIONS)} questões)"),
        ("picker",     "🎨", "Color Picker RGBA"),
    ]:
        if st.sidebar.button(f"{ic}  {lbl}", key=f"sb_{pg}"):
            st.session_state.page = pg; st.rerun()

    # ── Progress ──
    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    st.sidebar.markdown(f"""
<div class="sb-prog-wrap">
  <div style="display:flex;justify-content:space-between;font-size:11px;color:#64748b;font-weight:600;margin-bottom:8px">
    <span>Progresso geral</span><span style="color:#60a5fa">{prog}%</span>
  </div>
  <div class="prog-bar"><div class="prog-fill" style="width:{prog}%"></div></div>
  <div style="font-size:10px;color:#475569;margin-top:5px">{len(visited & QUIZ_PAGES)}/{len(QUIZ_PAGES)} seções com quiz aprovado</div>
</div>
""", unsafe_allow_html=True)

    if st.sidebar.button("⬅  Sair da conta", key="sb_logout"):
        token = st.query_params.get("token", "")
        invalidate_token(token)
        st.session_state.user = None
        st.session_state.page = "home"
        st.session_state.quiz_session = None
        st.session_state.quiz_session_answers = {}
        st.query_params.clear()
        st.rerun()


# ─────────────────────────────────────────────
# ROUTER — MAIN ENTRY
# ─────────────────────────────────────────────
# ── Extra quiz questions for new pages ──
ALL_QUESTIONS.extend([
    # AUTOMATE CONECTORES
    {"id":60,"cat":"Automate-Conectores","q":"Qual conector é necessário para CRIAR um item no SharePoint via Power Automate?",
     "opts":["HTTP Request","SharePoint — Criar item","Office 365 Sharepoint","Dataverse — Criar linha"],"ans":1,
     "exp":"O conector **SharePoint → Criar item** é Standard e cria registros em listas SharePoint."},
    {"id":61,"cat":"Automate-Conectores","q":"Como chamar uma API REST externa sem conector dedicado no Power Automate?",
     "opts":["Não é possível","Conector HTTP (Premium)","Webhook trigger","Office 365 HTTP"],"ans":1,
     "exp":"O conector **HTTP** (Premium) faz qualquer chamada REST/SOAP para APIs externas."},
    {"id":62,"cat":"Automate-Conectores","q":"Qual é a diferença entre conectores Standard e Premium no Power Automate?",
     "opts":["Não há diferença","Premium exige licença adicional (Power Automate Premium ou Power Apps Premium)","Premium é mais rápido","Standard tem menos ações"],"ans":1,
     "exp":"Conectores **Premium** exigem licença Power Automate Premium. Standard estão incluídos no M365."},
    {"id":63,"cat":"Automate-Conectores","q":"Para enviar uma mensagem no Teams via flow, qual conector é usado?",
     "opts":["Office 365 Outlook","Microsoft Teams","SharePoint","HTTP"],"ans":1,
     "exp":"O conector **Microsoft Teams** tem ações como 'Publicar mensagem no chat' e 'Publicar card adaptável'."},
    {"id":64,"cat":"Automate-Conectores","q":"Qual ação do conector SharePoint retorna até 5.000 itens com filtro OData?",
     "opts":["Obter item","Obter itens","Listar arquivos","HTTP SharePoint"],"ans":1,
     "exp":"**Obter itens** retorna uma lista com filtro OData, ordenação e até 5.000 registros por chamada."},

    # AUTOMATE APROVAÇÕES
    {"id":65,"cat":"Automate-Aprovações","q":"Qual tipo de aprovação envia para TODOS os aprovadores e exige resposta de TODOS?",
     "opts":["Aprovação básica","Todos devem aprovar","Primeiro a responder","Aprovação sequencial"],"ans":1,
     "exp":"**'Todos devem aprovar'** — o flow só avança quando todos os aprovadores responderem 'Aprovado'."},
    {"id":66,"cat":"Automate-Aprovações","q":"Como criar aprovação em SEQUÊNCIA (gerente → diretor → VP)?",
     "opts":["Usar aprovação paralela","Colocar 3 ações 'Iniciar e aguardar aprovação' em sequência","Definir 3 aprovadores na mesma ação","Usar loop com aprovadores"],"ans":1,
     "exp":"Coloque múltiplas ações **'Iniciar e aguardar aprovação'** em sequência — cada uma só avança após a anterior."},
    {"id":67,"cat":"Automate-Aprovações","q":"Onde o aprovador pode responder à solicitação de aprovação do Power Automate?",
     "opts":["Apenas no portal flow.microsoft.com","Apenas no e-mail","No Teams, no Outlook e no portal (todos os três)","Apenas no Teams"],"ans":2,
     "exp":"O aprovador pode responder diretamente no **Teams, Outlook ou portal** — a resposta sincroniza automaticamente."},
    {"id":68,"cat":"Automate-Aprovações","q":"Qual expressão verifica se a aprovação foi APROVADA?",
     "opts":["outputs('Aprovacao')?['approved']","equals(outputs('Iniciar_e_aguardar_uma_aprovação')?['body/outcome'], 'Approve')","body('Aprovacao')?['status'] == 'Done'","triggerOutputs()?['approved']"],"ans":1,
     "exp":"A expressão correta é **equals(outputs(…)?['body/outcome'], 'Approve')** — outcome é 'Approve' ou 'Reject'."},

    # AUTOMATE ERROS
    {"id":69,"cat":"Automate-Erros","q":"O que é 'Executar após' (Run After) no Power Automate?",
     "opts":["Agendamento de horário","Configuração que define quando uma ação executa baseado no resultado da anterior","Nome de usuário executor","Timeout da ação"],"ans":1,
     "exp":"**Run After** define se uma ação executa após Êxito, Falha, Ignorado ou Timeout da ação anterior."},
    {"id":70,"cat":"Automate-Erros","q":"Para que serve o nó 'Escopo' (Scope) no Power Automate?",
     "opts":["Limitar acesso ao flow","Agrupar ações para capturar erros em bloco com try/catch","Criar variáveis locais","Configurar timeout global"],"ans":1,
     "exp":"**Scope** agrupa ações — configure um Scope de erro com 'Executar após: com falha' para capturar erros."},
    {"id":71,"cat":"Automate-Erros","q":"Qual expressão retorna a mensagem de erro da ação anterior?",
     "opts":["error()","outputs('Acao')?['error']","result('NomeDoScope')?[0]['error']['message']","triggerBody()?['error']"],"ans":2,
     "exp":"Use **result('NomeDoScope')?[0]['error']['message']** para extrair a mensagem de erro de um escopo com falha."},

    # COPILOT IA
    {"id":72,"cat":"Copilot-IA","q":"O que é 'Respostas Generativas' (Generative Answers) no Copilot Studio?",
     "opts":["Uma fórmula do Power FX","Recurso que usa IA para responder com base em fontes de conhecimento sem criar tópico","Nome do modelo GPT","Uma integração com o Bing"],"ans":1,
     "exp":"**Respostas Generativas** usa IA (Azure OpenAI) para buscar e sintetizar respostas de suas fontes de conhecimento."},
    {"id":73,"cat":"Copilot-IA","q":"Quais fontes podem ser adicionadas como conhecimento no Copilot Studio?",
     "opts":["Apenas SharePoint","Sites públicos, SharePoint, documentos carregados e Dataverse","Apenas PDFs","Apenas bases de dados SQL"],"ans":1,
     "exp":"Fontes suportadas: **sites públicos, SharePoint Online, arquivos carregados, Dataverse** e mais."},
    {"id":74,"cat":"Copilot-IA","q":"O que é um Plugin Action no Copilot Studio?",
     "opts":["Um conector de API","Ação que expõe capacidades do agente para o Microsoft 365 Copilot (Chat, Teams, Outlook)","Um tópico especial","Um tipo de entidade"],"ans":1,
     "exp":"**Plugin Actions** permitem que seu agente seja chamado pelo Microsoft 365 Copilot em qualquer app M365."},

    # COPILOT INTEGRAÇÃO
    {"id":75,"cat":"Copilot-Integração","q":"Como embed um agente Copilot Studio em um site externo?",
     "opts":["Não é possível","Via snippet de código iframe/JS disponível em Publicar → Sites personalizados","Via API REST apenas","Copiando o HTML do portal"],"ans":1,
     "exp":"Em **Publicar → Sites personalizados** gere o snippet de código e cole no HTML da sua página."},
    {"id":76,"cat":"Copilot-Integração","q":"Para autenticar usuários via Azure AD no Copilot Studio, o que deve ser configurado?",
     "opts":["Nada — é automático","Azure AD v2 em Configurações → Segurança → Autenticação","Uma variável global de token","Um flow de autenticação separado"],"ans":1,
     "exp":"Configure **Azure AD v2** em Configurações → Segurança → Autenticação para SSO e acesso às variáveis System.User.*"},

    # DATAVERSE FÓRMULAS
    {"id":77,"cat":"Dataverse-Fórmulas","q":"O que é uma Coluna Calculada (Calculated Column) no Dataverse?",
     "opts":["Uma coluna editável manualmente","Coluna cujo valor é calculado automaticamente por uma fórmula server-side a cada leitura","Uma coluna do tipo número","Uma coluna que agrega filhos"],"ans":1,
     "exp":"**Calculated Column** usa fórmula server-side, recalculada a cada leitura — ex: concatenar nome+sobrenome."},
    {"id":78,"cat":"Dataverse-Fórmulas","q":"Para que serve uma Coluna Rollup no Dataverse?",
     "opts":["Calcular texto","Agregar valores de registros filhos (soma, contagem, média) na tabela pai","Criar links de URL","Formatar datas"],"ans":1,
     "exp":"**Rollup Column** agrega (Sum, Count, Min, Max, Avg) valores de registros relacionados — atualizada de hora em hora."},
    {"id":79,"cat":"Dataverse-Fórmulas","q":"O que são Power FX Formulas nas colunas do Dataverse?",
     "opts":["Fórmulas do Excel","Colunas calculadas usando a mesma linguagem do Power Apps (Power FX) com suporte a funções como If, Concatenate, DateAdd","Uma feature do Power BI","Expressões do Power Automate"],"ans":1,
     "exp":"**Power FX nas colunas** permite usar a mesma sintaxe do Power Apps para calcular valores no Dataverse."},

    # DATAVERSE APPS
    {"id":80,"cat":"Dataverse-Apps","q":"Qual é a principal vantagem de usar Dataverse em vez de SharePoint no Power Apps?",
     "opts":["Mais barato","Delegação quase total, relações reais e segurança por linha — sem limite efetivo de registros","Mais fácil de criar","Tem mais templates"],"ans":1,
     "exp":"Dataverse oferece **delegação quase total, relações JOIN, segurança por linha** — escalável a bilhões de registros."},
    {"id":81,"cat":"Dataverse-Apps","q":"Como fazer Patch em uma coluna de Choice (lista de opções) no Dataverse?",
     "opts":["Patch(Tabela, rec, {coluna: drp.Selected.Value})","Patch(Tabela, rec, {coluna: drp.Selected}) — passe o objeto inteiro, não o .Value","Patch(Tabela, rec, {coluna: Text(drp.Selected)})","Patch(Tabela, rec, {coluna: drp.Selected.Id})"],"ans":1,
     "exp":"Para Choice no Dataverse, passe **o objeto inteiro** do Selected (sem .Value) — o Dataverse precisa do objeto com metadados."},
])

CAT_COLORS.update({
    "Automate-Conectores":"#0c2344",
    "Automate-Aprovações":"#3b0764",
    "Automate-Erros":"#7f1d1d",
    "Copilot-IA":"#5c2d91",
    "Copilot-Integração":"#0c2344",
    "Dataverse-Fórmulas":"#052e16",
    "Dataverse-Apps":"#134e4a",
})

# ══════════════════════════════════════════════
# POWER AUTOMATE — Conectores & Integrações
# ══════════════════════════════════════════════
def page_automate_conectores():
    mark_page_visited(current_user()["id"], "automate_conectores")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Power Automate","Conectores & Integrações")
    hero("automate_conectores","🔌","Conectores & Integrações","SharePoint, Teams, Outlook, HTTP, Dataverse e SQL — com exemplos reais de flows.","Intermediário")

    tabs = st.tabs(["📋 SharePoint","💬 Teams & Outlook","🗄️ Dataverse & SQL","🌐 HTTP & APIs","🔗 Guia de Conectores"])

    with tabs[0]:
        st.markdown("#### SharePoint — Ações essenciais")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Criar item","Adiciona registro em lista SharePoint.",
                "Formulário de solicitação, onboarding, registro de ocorrência.",
                '''Trigger: "Quando um item é criado"
Site: https://empresa.sharepoint.com/sites/RH
Lista: Solicitacoes

Criar item:
  Site: https://empresa.sharepoint.com/sites/RH
  Lista: Aprovacoes
  Titulo: triggerBody()?['Title']
  Status: 'Pendente'
  Solicitante: triggerBody()?['Author']?['Email']
  DataSolicitacao: utcNow()''',
                color="#0050d0", tags=["Standard","Mais usado"])
            formula_card("Obter itens com filtro OData","Busca registros com condições avançadas.",
                "Relatórios, verificações de duplicata, buscas complexas.",
                '''Obter itens:
  Site: https://empresa.sharepoint.com/sites/RH
  Lista: Funcionarios
  Filtrar consulta:
    Status eq 'Ativo' and
    Departamento eq 'TI' and
    DataAdmissao ge '2024-01-01T00:00:00Z'
  Ordenar por: Nome asc
  Máximo de itens: 500
  Expandir consulta:
    Gestor($select=Title,Email)

// Acessar resultado:
// body('Obter_itens')?['value']''',
                color="#0050d0")
        with c2:
            formula_card("Atualizar item","Edita campos de um item existente.",
                "Aprovação/rejeição, mudança de status, preenchimento de datas.",
                '''// Obter o ID via trigger ou 'Obter itens':
Atualizar item:
  Site: https://empresa.sharepoint.com/sites/RH
  Lista: Solicitacoes
  Id: triggerBody()?['ID']  // ou outputs de 'Obter itens'
  Status: 'Aprovado'
  DataAprovacao: utcNow('dd/MM/yyyy')
  AprovadoPor:
    DisplayName: outputs('Obter_meu_perfil')?['body/displayName']
    Email: outputs('Obter_meu_perfil')?['body/mail']''',
                color="#0050d0")
            formula_card("Gerenciar arquivos","Upload, download, mover e obter metadados.",
                "Arquivar PDFs, mover entre pastas, ler conteúdo de arquivos.",
                '''// Criar arquivo:
Criar arquivo:
  Caminho da pasta: /Shared Documents/Contratos/2026
  Nome do arquivo: concat(triggerBody()?['NomeCliente'], '.pdf')
  Conteúdo: base64ToBinary(triggerBody()?['ArquivoPDF'])

// Obter conteúdo:
Obter conteúdo do arquivo usando o caminho:
  Site: https://...
  Caminho: /Shared Documents/Contratos/doc.pdf

// Resultado: body(...)?['$content'] (base64)''',
                color="#0050d0")

        st.markdown("#### Padrão: flow de aprovação com SharePoint")
        st.code('''// ════════════════════════════════════
// Flow: Aprovação de Compras
// ════════════════════════════════════

// [TRIGGER] Quando item criado na lista "Compras"
//   → Filtro: Status eq 'Novo'

// [INICIAR APROVAÇÃO]
//   Tipo: Todos devem aprovar
//   Título: concat('Aprovação: ', triggerBody()?['Title'])
//   Atribuído a: triggerBody()?['Gestor']?['Email']
//   Detalhes: concat(
//     'Valor: R$ ', string(triggerBody()?['Valor']),
//     '\\nFornecedor: ', triggerBody()?['Fornecedor'],
//     '\\nJustificativa: ', triggerBody()?['Justificativa']
//   )
//   Link de item: triggerBody()?['{Link}']

// [CONDIÇÃO] outcome == 'Approve'?
//   ├─ SIM → [ATUALIZAR ITEM] Status = 'Aprovado', DataAprovacao = utcNow()
//   │         [ENVIAR EMAIL] notificação de aprovação ao solicitante
//   └─ NÃO → [ATUALIZAR ITEM] Status = 'Rejeitado', MotivoRejeicao = body()?['comments']
//             [ENVIAR EMAIL] notificação de rejeição com motivo''', language="text")

    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Postar mensagem no Teams","Envia para canal, chat ou meeting.",
                "Notificações de aprovação, alertas de erro, relatórios automáticos.",
                '''// Postar no canal:
Postar mensagem em canal:
  Equipe: id da equipe (ou nome)
  Canal: id do canal
  Mensagem: <p>
    <strong>Nova solicitação:</strong> @{triggerBody()?['Title']}<br>
    Solicitante: @{triggerBody()?['Author']?['DisplayName']}<br>
    Valor: R$ @{triggerBody()?['Valor']}
  </p>

// Mencionar usuário: <at id="0">Nome</at>
// Card adaptável: use "Postar card adaptável"''',
                color="#6264a7", tags=["Standard","Teams"])
            formula_card("Enviar e-mail com Outlook","E-mails formatados com HTML e anexos.",
                "Confirmações, notificações, relatórios em PDF como anexo.",
                '''// Enviar um email (V2):
Para: triggerBody()?['Solicitante']?['Email']
Assunto: concat('[', triggerBody()?['Status'], '] Sua solicitação foi processada')
Corpo:
  <h2>Olá, @{triggerBody()?['Nome']}!</h2>
  <p>Sua solicitação <strong>@{triggerBody()?['Title']}</strong>
  foi <strong>@{triggerBody()?['Status']}</strong>.</p>

// Anexos:
[{
  "Name": "relatorio.pdf",
  "ContentBytes": "@{body('Criar_PDF')?['$content']}"
}]''',
                color="#0078d4", tags=["Standard","Outlook"])
        with c2:
            formula_card("Obter perfil do usuário","Dados do usuário via Azure AD / Office 365.",
                "Email, nome, gestor, departamento, foto — para personalizar flows.",
                '''// Obter perfil do meu próprio usuário:
Obter meu perfil (V2)
→ displayName, mail, department, jobTitle

// Obter perfil de qualquer usuário:
Obter perfil de usuário (V2):
  Id: maria@empresa.com

// Campos disponíveis:
outputs('Obter_perfil')?['body/displayName']
outputs('Obter_perfil')?['body/mail']
outputs('Obter_perfil')?['body/department']
outputs('Obter_perfil')?['body/manager']?['mail']''',
                color="#0078d4")
            formula_card("Criar evento no Calendar","Agenda reuniões automaticamente.",
                "Onboarding, agendamento de review, lembretes de vencimento.",
                '''Criar evento (V4):
  Calendário: Calendar
  Assunto: concat('Review: ', triggerBody()?['Projeto'])
  Início: addDays(utcNow(), 7)
  Término: addHours(addDays(utcNow(), 7), 1)
  Fuso horário: E. South America Standard Time
  Conteúdo: <p>Agenda automática gerada pelo sistema</p>
  Participantes necessários:
    triggerBody()?['GestorEmail']
  Local: Teams / Online''',
                color="#0078d4")

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Dataverse — Criar / Atualizar linha","CRUD no banco de dados nativo.",
                "Dados críticos, relações complexas, regras de negócio server-side.",
                '''// Adicionar nova linha (Premium):
Adicionar uma nova linha:
  Nome da tabela: cr123_projetos
  cr123_nome: triggerBody()?['Title']
  cr123_status: 'Em Andamento'
  cr123_clienteid@odata.bind:
    /accounts(@{triggerBody()?['ClienteId']})

// Atualizar linha:
Atualizar linha:
  Nome da tabela: cr123_projetos
  ID da linha: triggerBody()?['ID']
  cr123_valorreal: outputs('Calc')?['body/total']''',
                color="#134e4a", tags=["Premium","Dataverse"])
            formula_card("SQL Server — Query e Insert","Integração com bancos relacionais.",
                "Sistemas legados, ERP, bases corporativas com SQL Server/Azure SQL.",
                '''// Executar consulta SQL (Premium):
Executar consulta SQL:
  Servidor: servidor.database.windows.net
  Banco: MinhaBD
  Query: SELECT TOP 100 ID, Nome, Status
    FROM dbo.Pedidos
    WHERE DataCriacao >= GETDATE()-30
    ORDER BY DataCriacao DESC

// Resultado: body('SQL')?['ResultSets']?['Table1']

// Inserir linha:
Inserir linha (V2):
  Servidor: ...
  Tabela: [dbo].[Pedidos]
  {campos do registro}''',
                color="#134e4a", tags=["Premium","SQL"])
        with c2:
            formula_card("Listar itens Dataverse com OData","Consultas avançadas no Dataverse.",
                "Filtros relacionais, expand de lookups, paginação.",
                '''// Listar linhas:
Listar linhas:
  Nome da tabela: cr123_projetos
  Filtrar linhas:
    cr123_status eq 'Em Andamento' and
    createdon ge 2026-01-01T00:00:00Z
  Expandir consulta:
    cr123_clienteid($select=name,emailaddress1)
  Ordenar por: createdon desc
  Limite de linhas: 50

// Resultado:
body('Listar_linhas')?['value']
// Item[N] campo:
item()?['cr123_nome']
item()?['cr123_clienteid']?['name']''',
                color="#0d9488")
            info_box("💡 <b>Paginação automática:</b> Ative 'Paginação' nas configurações da ação 'Listar linhas' do Dataverse para buscar TODOS os registros automaticamente, contornando o limite de página.", "info")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("HTTP — Chamar API REST","Integre com qualquer API externa (Premium).",
                "SAP, Totvs, sistemas sem conector dedicado, APIs internas.",
                '''// Ação HTTP:
Método: POST
URI: https://api.exemplo.com/v1/pedidos
Cabeçalhos:
  Content-Type: application/json
  Authorization: concat('Bearer ', variables('token'))
  X-API-Key: parameters('ApiKey')
Corpo:
{
  "numeroPedido": "@{triggerBody()?['NumeroPedido']}",
  "cliente": "@{triggerBody()?['Cliente']}",
  "valor": @{triggerBody()?['Valor']},
  "dataVencimento": "@{formatDateTime(utcNow(), 'yyyy-MM-dd')}"
}

// Resposta:
body('HTTP')?['id']
body('HTTP')?['status']''',
                color="#dc2626", tags=["Premium","REST"])
            formula_card("Responder a um webhook","Receba chamadas externas no flow.",
                "Integração bidirecional — sistemas externos disparam seu flow via HTTP.",
                '''// Trigger: "Ao receber uma solicitação HTTP"
// → Gera URL única e automática
// → Defina o esquema JSON esperado

// Schema de exemplo:
{
  "type": "object",
  "properties": {
    "evento": {"type": "string"},
    "dados": {
      "type": "object",
      "properties": {
        "id": {"type": "integer"},
        "status": {"type": "string"}
      }
    }
  }
}

// Responder:
Resposta: Código 200
Corpo: {"resultado": "processado", "id": "@{variables('novoId')}"}''',
                color="#dc2626")
        with c2:
            formula_card("Autenticar com OAuth2","Token Bearer para APIs seguras.",
                "SAP OAuth2, Salesforce, APIs Microsoft com token de serviço.",
                '''// Obter token (Client Credentials):
HTTP:
  Método: POST
  URI: https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token
  Cabeçalho: Content-Type: application/x-www-form-urlencoded
  Corpo:
    grant_type=client_credentials
    &client_id=@{parameters('ClientId')}
    &client_secret=@{parameters('ClientSecret')}
    &scope=https://api.exemplo.com/.default

// Extrair token:
body('HTTP_Token')?['access_token']

// Usar nas próximas chamadas:
Authorization: concat('Bearer ', body('HTTP_Token')?['access_token'])''',
                color="#dc2626")
            info_box("🔐 <b>Segurança:</b> Nunca coloque credenciais diretamente no flow. Use <b>Parâmetros de ambiente</b> (Environment Variables) ou <b>Azure Key Vault</b> para armazenar chaves e secrets.", "warning")

    with tabs[4]:
        st.markdown("#### Mapa de conectores por produto")
        conectores = [
            ("📋","SharePoint","Standard","Listas, bibliotecas, arquivos, metadados, permissões"),
            ("💬","Microsoft Teams","Standard","Mensagens, canais, chats, meetings, cards adaptáveis"),
            ("📧","Office 365 Outlook","Standard","E-mails, calendário, contatos, categorias"),
            ("👤","Office 365 Users","Standard","Perfil, foto, gestor, subordinados, busca de usuário"),
            ("📝","Microsoft Forms","Standard","Respostas de formulários, detalhes de resposta"),
            ("🗄️","Dataverse","Premium","CRUD completo, FetchXML, actions, batch"),
            ("🌐","HTTP","Premium","REST, SOAP, qualquer API externa, webhooks"),
            ("🗃️","SQL Server","Premium","Query, insert, update, stored procedures"),
            ("☁️","Azure Blob Storage","Premium","Upload/download arquivos, containers"),
            ("🔑","Azure Key Vault","Premium","Segredos, chaves, certificados"),
            ("📊","Excel Online","Standard","Tabelas, ler/escrever linhas, scripts"),
            ("🤖","AI Builder","Premium","OCR, detecção de objetos, processamento NLP"),
            ("📱","Power Apps","Standard","Trigger manual, responder ao app"),
            ("🔄","Aprovações","Standard","Workflow de aprovação nativo com Teams/Outlook"),
        ]
        for ic, nome, tier, desc in conectores:
            color = "#d1fae5" if tier=="Standard" else "#fef3c7"
            tcolor = "#065f46" if tier=="Standard" else "#92400e"
            st.markdown(f'<div class="sr" style="display:flex;align-items:center;gap:12px"><div style="font-size:20px;width:28px">{ic}</div><div style="flex:1"><div style="font-weight:700;color:#111827;font-size:13px">{nome}</div><div style="font-size:12px;color:#6b7280;margin-top:1px">{desc}</div></div><span style="background:{color};color:{tcolor};font-size:10px;font-weight:700;padding:3px 9px;border-radius:10px;white-space:nowrap;flex-shrink:0">{tier}</span></div>', unsafe_allow_html=True)

    section_quiz("automate_conectores")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# POWER AUTOMATE — Aprovações & Workflows
# ══════════════════════════════════════════════
def page_automate_aprovacoes():
    mark_page_visited(current_user()["id"], "automate_aprovacoes")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Power Automate","Aprovações & Workflows")
    hero("automate_aprovacoes","✅","Aprovações & Workflows Complexos","Aprovação sequencial, paralela, com prazo e cards adaptáveis no Teams.","Avançado")

    tabs = st.tabs(["✅ Tipos de Aprovação","🔀 Aprovação Sequencial","⚡ Paralela & Delegação","🃏 Cards Adaptáveis","📊 Padrões Avançados"])

    with tabs[0]:
        info_box("✅ O conector <b>Aprovações</b> é Standard (incluso no M365) e permite aprovações sofisticadas diretamente no Teams ou Outlook — sem necessidade de portal externo.", "info")
        c1,c2 = st.columns(2)
        with c1:
            for tipo, desc, ex in [
                ("Aprovação básica (um aprovador)",
                 "Envia para um único aprovador. Ideal para workflows simples como despesas até R$500.",
                 "Iniciar e aguardar aprovação\n  Tipo: Aprovação básica\n  Título: 'Aprovação de despesa'\n  Atribuído a: gerente@empresa.com\n  Detalhes: 'Valor: R$250 | Motivo: Material'"),
                ("Todos devem aprovar",
                 "Aguarda resposta de TODOS antes de avançar. Para decisões críticas que exigem unanimidade.",
                 "Tipo: Todos devem aprovar\n  Atribuído a:\n    - cfo@empresa.com\n    - juridico@empresa.com\n    - coo@empresa.com\n// Flow só avança quando os 3 aprovarem"),
            ]:
                formula_card(tipo, desc, "", ex, color="#0050d0")
        with c2:
            for tipo, desc, ex in [
                ("Primeiro a responder",
                 "Qualquer um dos aprovadores pode responder. Ideal para equipes com múltiplos aprovadores equivalentes.",
                 "Tipo: Primeiro a responder\n  Atribuído a:\n    - supervisor1@empresa.com\n    - supervisor2@empresa.com\n    - supervisor3@empresa.com\n// O primeiro que responder define o resultado"),
                ("Aprovação personalizada (custom)",
                 "Inicie a aprovação e aguarde separadamente — permite lógica entre início e fim.",
                 "// Ação 1:\nIniciar uma aprovação:\n  Tipo: Aprovação básica\n  ...\n  → Obtém 'approvalId'\n\n// Ação 2 (após outras ações):\nAguardar uma aprovação:\n  Id de aprovação: outputs('Iniciar')?['body/approvalId']"),
            ]:
                formula_card(tipo, desc, "", ex, color="#5c2d91")

    with tabs[1]:
        st.markdown("#### Aprovação em 3 níveis — Gestor → Diretor → VP")
        st.code('''// ════════════════════════════════════════════════
// FLOW: Aprovação Sequencial de Investimento
// Regra: Cada nível só vê se o anterior aprovou
// ════════════════════════════════════════════════

[TRIGGER] Quando item criado em "Investimentos"
  Condição: Status eq 'Novo'

[INICIALIZAR VARIÁVEL] aprovacaoFinal = 'Aprovado'
[INICIALIZAR VARIÁVEL] comentarioFinal = ''

// ── NÍVEL 1: Gestor Imediato ──────────────────
[INICIAR E AGUARDAR APROVAÇÃO]
  Título: concat('[N1-Gestor] ', triggerBody()?['Title'])
  Atribuído a: triggerBody()?['Gestor']?['Email']
  Detalhes: concat('Valor: ', triggerBody()?['Valor'], ' | Área: ', triggerBody()?['Area'])
  → outcome1, comments1

[CONDIÇÃO] outcome1 is equal to 'Approve'
  SIM → continua para nível 2
  NÃO → [SET variável] aprovacaoFinal = 'Rejeitado N1'
         [SET variável] comentarioFinal = outputs('N1')?['body/responses'][0]['comments']
         → pula para [FIM]

// ── NÍVEL 2: Diretoria ────────────────────────
[INICIAR E AGUARDAR APROVAÇÃO]
  Título: concat('[N2-Diretoria] ', triggerBody()?['Title'])
  Atribuído a: triggerBody()?['Diretor']?['Email']
  Detalhes: concat('✅ Aprovado N1 por: ',
    outputs('N1')?['body/responses'][0]['responder']['email'])
  → outcome2, comments2

[CONDIÇÃO] outcome2 is equal to 'Approve'
  SIM → continua para nível 3 (se valor > 50k)
  NÃO → [SET] aprovacaoFinal = 'Rejeitado N2'

// ── NÍVEL 3: VP (apenas se valor > R$50.000) ──
[CONDIÇÃO] triggerBody()?['Valor'] is greater than 50000
  SIM → [INICIAR E AGUARDAR APROVAÇÃO VP]
  NÃO → pula para [FIM]

// ── FIM ───────────────────────────────────────
[ATUALIZAR ITEM SHAREPOINT]
  Status: variables('aprovacaoFinal')
  Comentario: variables('comentarioFinal')
  DataFechamento: utcNow()

[ENVIAR EMAIL] ao solicitante com resultado final''', language="text")

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Aprovação Paralela","Múltiplos aprovadores simultâneos com lógica de maioria.",
                "Comitê de aprovação, múltiplos departamentos aprovando ao mesmo tempo.",
                '''// Execute "Iniciar aprovação" para CADA aprovador
// usando "Aplicar a cada" com paralelismo

// Variáveis iniciais:
aprovacoes = 0 (inteiro)
rejeicoes = 0 (inteiro)
aprovadores = ["cfo@", "coo@", "cto@"]

// Para cada aprovador (em paralelo):
[Apply to Each - Concorrência: 50]
  [Iniciar aprovação para item()?['email']]
  [Aguardar aprovação]
  [Condição] outcome == 'Approve'
    SIM → [Incrementar aprovacoes += 1]
    NÃO → [Incrementar rejeicoes += 1]

// Decisão final (maioria simples):
[Condição] aprovacoes > rejeicoes
  SIM → Aprovado
  NÃO → Rejeitado''',
                color="#0050d0")
        with c2:
            formula_card("Prazo de Aprovação (Timeout)","Aprovação automática ou escalonamento após prazo.",
                "SLA de aprovação: se não respondeu em X horas, escala ou aprova automaticamente.",
                '''// Use "Iniciar uma aprovação" (não aguardar)
// + "Atraso até" em paralelo

// Branch 1: Aguardar resposta do aprovador
[Aguardar aprovação]
  Id: outputs('Iniciar')?['body/approvalId']

// Branch 2 (paralelo): Timeout de 48h
[Atraso até]
  Timestamp: addHours(utcNow(), 48)
  
// Verificar qual terminou primeiro:
[Condição] empty(outputs('Aguardar')?['body/outcome'])
  SIM (timeout!) →
    [Cancelar aprovação]
    [Escalamento automático]
    [Enviar alerta ao gestor]
  NÃO → processar resposta normal''',
                color="#7c3aed")
        formula_card("Delegar Aprovação","Aprovador redireciona para outra pessoa.",
            "O aprovador pode reassinar dentro do portal de aprovações — sem configuração extra no flow.",
            '''// No portal flow.microsoft.com/approvals:
// → Aprovador clica "Reatribuir"
// → Informa o novo aprovador

// Para delegar PROGRAMATICAMENTE no flow:
// Use a API de Aprovações (Premium):
// POST .../approvals/{id}/reassign
// Body: {"assignedTo": "novoaprovador@empresa.com"}

// Ou simplesmente: ao criar a aprovação,
// inclua no campo "Atribuído a" a lógica
// de quem deve receber baseado em cargo/nível
// usando "Obter perfil de usuário" + manager''',
            color="#0d9488")

    with tabs[3]:
        st.markdown("#### Card Adaptável de Aprovação no Teams")
        st.code('''{
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "🔔 Solicitação de Aprovação",
      "weight": "Bolder",
      "size": "Large",
      "color": "Accent"
    },
    {
      "type": "FactSet",
      "facts": [
        {"title": "Solicitante", "value": "${solicitante}"},
        {"title": "Tipo",        "value": "${tipo}"},
        {"title": "Valor",       "value": "R$ ${valor}"},
        {"title": "Prazo",       "value": "${prazo}"},
        {"title": "Justificativa","value":"${justificativa}"}
      ]
    },
    {
      "type": "ActionSet",
      "actions": [
        {
          "type": "Action.Submit",
          "title": "✅ Aprovar",
          "style": "positive",
          "data": {"acao": "aprovado", "approvalId": "${approvalId}"}
        },
        {
          "type": "Action.Submit",
          "title": "❌ Rejeitar",
          "style": "destructive",
          "data": {"acao": "rejeitado", "approvalId": "${approvalId}"}
        },
        {
          "type": "Action.OpenUrl",
          "title": "📋 Ver detalhes",
          "url": "${linkItem}"
        }
      ]
    }
  ]
}''', language="json")
        info_box("💡 Use o <a href='https://adaptivecards.io/designer' target='_blank'>Adaptive Cards Designer</a> para criar cards visuais sem escrever JSON manualmente. O Power Automate tem um card designer integrado também.", "info")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### Padrão: Aprovação com lembretes")
            st.code('''// Enviar lembrete após 24h sem resposta:
// Use "Executar em paralelo" ou branch separado

[Do Until] outcome não está vazio
  [Atraso] 24 horas
  [Condição] aprovação ainda pendente?
    SIM → [Enviar email de lembrete]
          [Incrementar contador de lembretes]
          Condição: lembretes >= 3?
            SIM → [Escalar para gerente]
                  [Sair do loop]
    NÃO → [Sair do loop]

// Limite do Do Until: sempre defina
// Count: 10 (máx 10 iterações)
// Timeout: PT72H (3 dias em ISO 8601)''', language="text")
        with c2:
            st.markdown("##### Padrão: Aprovação condicional por valor")
            st.code('''// Diferentes aprovadores por faixa de valor

[Condição] triggerBody()?['Valor']
  < 500    → [Aprovação automática]
             Status = 'Pré-aprovado (auto)'
  500-5000 → [Aprovação Gestor]
  5001-50k → [Aprovação Diretor]
  > 50k    → [Aprovação Diretoria + CFO]

// Implementação com Switch/Switch-like:
[Condição] Valor < 500 → auto
[Condição] Valor < 5000 → gestor
[Condição] Valor < 50000 → diretor
[Default] → comite executivo

// Dica: use variáveis para o email do
// aprovador e uma única ação de aprovação
// no final, evitando duplicação de código''', language="text")

    section_quiz("automate_aprovacoes")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# POWER AUTOMATE — Tratamento de Erros & Debug
# ══════════════════════════════════════════════
def page_automate_erros():
    mark_page_visited(current_user()["id"], "automate_erros")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Power Automate","Erros & Debug")
    hero("automate_erros","🐛","Tratamento de Erros & Debug","Scopes, Run After, retry, variáveis de erro e análise de histórico.","Avançado")

    tabs = st.tabs(["🛡️ Scope (Try/Catch)","⚙️ Run After","🔁 Retry & Timeout","🔍 Debug & Histórico","📋 Padrões"])

    with tabs[0]:
        info_box("🛡️ O padrão <b>Try/Catch com Scope</b> é a forma profissional de tratar erros no Power Automate. Agrupe ações num Scope de 'tentativa' e crie um segundo Scope de 'erro' que executa apenas se o primeiro falhar.", "info")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Estrutura Try/Catch/Finally")
            st.code('''// ── SCOPE: TRY ────────────────────────────────
[Scope] "TRY - Processar Pedido"
  [Obter item SharePoint]
  [Chamar API externa (HTTP)]
  [Criar item Dataverse]
  [Enviar email confirmação]
  → Se tudo OK, flow continua normalmente

// ── SCOPE: CATCH ──────────────────────────────
// Config: Executar após TRY → Com falha, Ignorado
[Scope] "CATCH - Tratar Erro"
  [Compor] mensagemErro =
    result('TRY_-_Processar_Pedido')?[0]['error']['message']

  [Compor] acaoQuefalhou =
    result('TRY_-_Processar_Pedido')?[0]['name']

  [Atualizar item SP] Status = 'Erro'
  [Enviar email TI] com detalhes do erro
  [Postar Teams] alerta no canal de operações

// ── SCOPE: FINALLY ────────────────────────────
// Config: Executar após CATCH → Êxito, Falha, Ignorado, Timeout
[Scope] "FINALLY - Limpeza"
  [Atualizar variável] flowConcluido = true
  [Log] registrar no Dataverse''', language="text")
        with c2:
            st.markdown("#### Expressões de diagnóstico")
            st.code('''// Capturar erro do Scope:
result('Nome_do_Scope')
// → array com status de cada ação interna

// Mensagem de erro:
result('Nome_do_Scope')?[0]['error']['message']

// Código de erro:
result('Nome_do_Scope')?[0]['error']['code']

// Nome da ação que falhou:
result('Nome_do_Scope')?[0]['name']

// Status da ação (Succeeded/Failed/Skipped):
result('Nome_do_Scope')?[0]['status']

// Verificar se o Scope inteiro falhou:
equals(
  result('Nome_do_Scope')?[0]['status'],
  'Failed'
)

// Verificar código HTTP de resposta:
outputs('HTTP')?['statusCode']
// 200=OK, 400=Bad Request, 401=Unauth, 500=Server Error''', language="text")

    with tabs[1]:
        st.markdown("#### Configurações de Run After")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("""
| Configuração | Quando executa |
|---|---|
| ✅ **Êxito** | Padrão — ação anterior OK |
| ❌ **Com falha** | Ação anterior falhou |
| ⏭️ **Ignorado** | Ação anterior foi pulada |
| ⏱️ **Atingiu o tempo limite** | Ação excedeu timeout |

**Combinações úteis:**
- `Com falha + Ignorado` → qualquer problema
- `Êxito + Com falha` → sempre executa exceto skip
- Todos os 4 marcados → executa sempre (Finally)
            """)
        with c2:
            st.code('''// Ação de notificação de erro:
// Run After: "Criar_item_Dataverse" → Com falha

[Enviar email de erro]
  Para: ti@empresa.com
  Assunto: concat('[ERRO FLOW] ', workflow()?['tags']?['flowDisplayName'])
  Corpo:
    Flow: @{workflow()?['tags']?['flowDisplayName']}
    Ambiente: @{workflow()?['tags']?['environmentName']}
    Run ID: @{workflow()?['run']?['name']}
    Hora: @{utcNow('dd/MM/yyyy HH:mm')}
    Ação: Criar_item_Dataverse
    Erro: @{outputs('Criar_item_Dataverse')?['body/error/message']}
    Link: https://flow.microsoft.com/manage/environments/...''', language="text")

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Política de Retry (Novas tentativas)")
            st.code('''// Em cada ação HTTP/conector, em Configurações:
// → Políticas de Tentativa Novamente

// Tipos:
// Padrão  → exponential, até 4 tentativas
// Nenhuma → sem retry
// Fixo    → intervalo fixo entre tentativas
// Exponencial → intervalo cresce exponencialmente

// Configuração manual (JSON):
{
  "type": "exponential",
  "count": 4,
  "interval": "PT7S",     // espera mínima (ISO 8601)
  "minimumInterval": "PT5S",
  "maximumInterval": "PT1H"
}

// Quando usar retry:
// ✅ APIs instáveis (rate limit 429)
// ✅ Conexões de rede instáveis
// ✅ Timeouts ocasionais
// ❌ Erros de negócio (400 Bad Request)''', language="text")
        with c2:
            st.markdown("#### Timeouts configuráveis")
            st.code('''// Timeout de ação individual:
// Configurações → Duração do Limite de Tempo
// Formato ISO 8601:
PT30S    = 30 segundos
PT5M     = 5 minutos
PT2H     = 2 horas
P1D      = 1 dia

// Timeout padrão por tipo:
// Ação normal:    2 horas
// Loop Do Until:  PT1H por padrão
// Flow total:     30 dias

// Limites do Loop Do Until:
// Count: máximo de iterações (recomendo: 20)
// Timeout: ex PT4H (4 horas máximo)

// Evitar loop infinito:
[Do Until]
  Condição: variables('concluido') equals true
  Limite: Count = 50, Timeout = PT2H
  [Ações...]
  [Atraso] PT5M (intervalo entre tentativas)''', language="text")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Analisar histórico de execuções")
            st.markdown("""
**Onde acessar:**
`flow.microsoft.com` → Meus flows → Selecionar flow → Histórico de execuções de 28 dias

**O que verificar:**
- Status: Êxito / Falha / Cancelado / Em execução
- Duração total da execução
- Qual ação falhou (clique na execução)
- Inputs e outputs de cada ação
- Mensagem de erro exata

**Dicas de debug:**
- Clique na ação com ❌ para ver os detalhes
- Copie os inputs/outputs para testar localmente
- Use **Testar** (manual) para re-executar com dados reais
- Ative **Histórico de execuções** em configurações do flow
            """)
        with c2:
            st.markdown("#### Logging personalizado")
            st.code('''// Registrar log em tabela Dataverse:
[Adicionar linha] na tabela cr123_flowlogs
  cr123_flow: workflow()?['tags']?['flowDisplayName']
  cr123_runid: workflow()?['run']?['name']
  cr123_status: 'Iniciado'
  cr123_data: utcNow()
  cr123_entrada: string(triggerBody())

// Ao final (escopo FINALLY):
[Atualizar linha] cr123_flowlogs
  cr123_status: 'Concluído'
  cr123_duracaoseg: div(
    sub(
      ticks(utcNow()),
      ticks(variables('dataInicio'))
    ), 10000000
  )
  cr123_erro: variables('mensagemErro')

// Link direto para a execução:
concat(
  'https://flow.microsoft.com/manage/environments/',
  workflow()?['tags']?['environmentName'],
  '/flows/', workflow()?['name'],
  '/runs/', workflow()?['run']?['name']
)''', language="text")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### ✅ Checklist de flow produção-ready")
            items = [
                ("🛡️","Try/Catch com Scope","Agrupa ações críticas com tratamento de erro"),
                ("📧","Notificação de erro","E-mail/Teams para TI com Run ID ao falhar"),
                ("🔁","Retry configurado","Para HTTP e conectores instáveis"),
                ("📝","Ações nomeadas","Nomes descritivos em todas as ações"),
                ("🔒","Sem credenciais hardcoded","Use parâmetros de ambiente"),
                ("📊","Log em tabela","Registrar início/fim/status/duração"),
                ("⏱️","Timeout definido","Em loops e ações de longa duração"),
                ("🧪","Testado em DEV","Nunca suba direto para produção"),
                ("📋","Comentários","Use ações 'Compor' como comentários visuais"),
                ("🔄","Idempotente","Flow re-executado não cria duplicatas"),
            ]
            for ic, t, d in items:
                st.markdown(f'<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #f3f4f6"><span style="font-size:16px">{ic}</span><div><div style="font-size:12px;font-weight:700;color:#111827">{t}</div><div style="font-size:11px;color:#6b7280">{d}</div></div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("##### 🚫 Erros mais comuns")
            erros = [
                ("Loop de trigger","Flow atualiza item → trigger dispara novamente. Fix: verificar se campo já tem valor antes de atualizar."),
                ("Obter itens sem filtro","Carrega todos os registros, lento e consome cota. Fix: sempre use filtro OData."),
                ("Parse JSON sem schema","Acesso a campos não funciona. Fix: gere sempre o schema via 'Gerar a partir de amostra'."),
                ("Timezone errado","utcNow() retorna UTC. Fix: use convertTimeZone() para fuso brasileiro."),
                ("Apply to Each em série","50x mais lento que em paralelo. Fix: desative 'Execução em série'."),
                ("Sem tratamento de 429","API retorna rate limit e flow falha. Fix: configure retry exponencial."),
                ("Credencial expirada","Conector usa conta pessoal que saiu da empresa. Fix: use service account dedicada."),
            ]
            for t, d in erros:
                st.markdown(f'<div style="background:#fef2f2;border-left:3px solid #dc2626;border-radius:6px;padding:8px 12px;margin-bottom:6px"><div style="font-weight:700;color:#7f1d1d;font-size:12px">⚠️ {t}</div><div style="font-size:11px;color:#991b1b;margin-top:2px">{d}</div></div>', unsafe_allow_html=True)

    section_quiz("automate_erros")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# COPILOT STUDIO — IA Generativa & Plugins
# ══════════════════════════════════════════════
def page_copilot_ia():
    mark_page_visited(current_user()["id"], "copilot_ia")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Copilot Studio","IA Generativa & Plugins")
    hero("copilot_ia","🧠","IA Generativa & Plugins","Respostas automáticas por IA, fontes de conhecimento, GPT e plugin actions.","Avançado")

    tabs = st.tabs(["✨ Respostas Generativas","📚 Fontes de Conhecimento","🔌 Plugin Actions","🤖 Prompt Customizado","📊 Qualidade & Monitoramento"])

    with tabs[0]:
        info_box("✨ <b>Respostas Generativas</b> (Generative Answers) usa Azure OpenAI para responder perguntas com base nas suas fontes de conhecimento — sem criar tópicos para cada pergunta.", "info")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Como funciona")
            st.code('''// Fluxo da Resposta Generativa:

// 1. Usuário pergunta algo não coberto por tópico
// 2. Copilot Studio busca nas fontes de conhecimento
// 3. Azure OpenAI sintetiza uma resposta com base
//    nos documentos encontrados
// 4. Resposta inclui citações das fontes
// 5. Se não encontrar informação: fallback configurável

// Habilitar:
// Configurações → IA Generativa → Ativar
// Selecionar fontes de conhecimento

// Configurar no tópico Fallback:
// Adicionar nó → "Respostas generativas"
// Entrada: System.Activity.Text (pergunta)
// Fontes: selecionar quais usar''', language="text")
            formula_card("Nó de Resposta Generativa","Use dentro de qualquer tópico para responder dinamicamente.",
                "FAQ de RH, manual do produto, política de TI — sem criar tópico por pergunta.",
                '''// No tópico, adicione nó:
// "Criar resposta generativa"
// Entrada de texto: Topic.PerguntaUsuario
//   ou: System.Activity.Text
// Fontes: [Seu SharePoint / Site]

// A IA retorna:
// Topic.RespostaIA
//   → use em nó de Mensagem

// Controles de qualidade:
// Nível de moderação: Baixo/Médio/Alto
// Citar fontes: Sim/Não
// Avisar quando não encontrar: Sim''',
                color="#5c2d91")
        with c2:
            st.markdown("#### Quando usar Generativa vs Tópico")
            itens = [
                ("Tópico", "Processo estruturado", "Aprovação de férias, abertura de chamado, pedido de compra — fluxo passo a passo"),
                ("Generativa", "FAQ / Consulta", "Política de benefícios, manual técnico, FAQ de produto — respostas abertas"),
                ("Tópico", "Coleta de dados", "Formulários, cadastros — quando precisa salvar em sistema"),
                ("Generativa", "Conteúdo extenso", "Documentação longa com muitas variações de pergunta"),
                ("Tópico", "Integração crítica", "Quando precisa chamar flow com dados específicos e confiáveis"),
                ("Generativa", "Conteúdo dinâmico", "Quando o conteúdo muda frequentemente (SharePoint sempre atualizado)"),
            ]
            for tipo, cenario, desc in itens:
                cor = "#e0f2fe" if tipo=="Generativa" else "#d1fae5"
                tc = "#075985" if tipo=="Generativa" else "#065f46"
                st.markdown(f'<div style="display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #f3f4f6;align-items:start"><span style="background:{cor};color:{tc};font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px;white-space:nowrap;margin-top:2px">{tipo}</span><div><div style="font-size:12px;font-weight:700;color:#111827">{cenario}</div><div style="font-size:11px;color:#6b7280">{desc}</div></div></div>', unsafe_allow_html=True)

    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("SharePoint como conhecimento","Indexa automaticamente documentos e páginas.",
                "Manuais, políticas, FAQs, wikis — o conteúdo é indexado e pesquisado automaticamente.",
                '''// Adicionar fonte:
// Configurações → Conhecimento → + Adicionar
// Tipo: SharePoint
// URL: https://empresa.sharepoint.com/sites/RH

// O Copilot indexa:
// ✅ Documentos (.docx, .pdf, .pptx)
// ✅ Páginas do SharePoint
// ✅ Listas (se habilitado)
// ❌ Conteúdo de subpastas (configure separado)

// Atualização: indexação acontece periodicamente
// Force re-index: remova e re-adicione a fonte

// Permissões: o agente acessa como Service
// Principal — garanta que tem leitura na biblioteca''',
                color="#0078d4", tags=["Standard","Popular"])
            formula_card("Sites públicos","Indexa conteúdo de websites externos.",
                "Documentação oficial, base de conhecimento pública, site institucional.",
                '''// Tipo: Sites públicos
// URL: https://docs.microsoft.com/power-apps/

// ⚠️ Apenas conteúdo PÚBLICO (sem login)
// Profundidade: até 2 níveis de links
// Frequência de atualização: semanal

// Casos de uso:
// • Documentação técnica (learn.microsoft.com)
// • FAQ do seu produto (site público)
// • Normas regulatórias (sites gov)

// Limite: 1 milhão de tokens por fonte
// Recomendação: use URLs específicas de seção
// em vez do domínio raiz inteiro''',
                color="#0078d4")
        with c2:
            formula_card("Dataverse como conhecimento","Consulta dados estruturados em tabelas.",
                "Catálogo de produtos, base de clientes, FAQ em tabela Dataverse.",
                '''// Tipo: Dataverse
// Tabela: cr123_faq (com colunas Pergunta + Resposta)

// A IA usa os dados para responder
// Atualização: em tempo real (dados sempre frescos)

// Estrutura recomendada da tabela FAQ:
// cr123_pergunta (texto) → pergunta original
// cr123_resposta (texto longo) → resposta detalhada
// cr123_categoria (choice) → área/departamento
// cr123_ativo (yes/no) → publicado ou não

// Vantagem sobre SharePoint:
// Controle granular de quais registros mostrar
// Filtro por categoria via configuração''',
                color="#134e4a")
            formula_card("Arquivos carregados","Upload direto de PDFs e documentos.",
                "Regulamentos, contratos, manuais de equipamento — documentos estáticos.",
                '''// Tipo: Arquivos
// Upload: até 512MB por arquivo
// Formatos: PDF, DOCX, PPTX, TXT, CSV

// Uso típico:
// • Contrato social da empresa
// • Manual de equipamento (PDF do fornecedor)
// • Regulamento interno
// • Tabela de preços (CSV)

// Atualização: manual (re-upload)
// → Para conteúdo dinâmico, prefira SharePoint

// Limite: 50 arquivos por agente
// Dica: use PDFs com texto pesquisável
// (não imagens escaneadas sem OCR)''',
                color="#5c2d91")

    with tabs[2]:
        info_box("🔌 <b>Plugin Actions</b> expõem capacidades do seu agente para o <b>Microsoft 365 Copilot</b> — qualquer usuário pode invocar seu agente dentro do Copilot no Teams, Outlook, Word etc.", "info")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Criar Plugin Action","Expõe ação do agente para M365 Copilot.",
                "O usuário digita 'Abrir chamado de TI' no Copilot do Teams e seu agente é chamado.",
                '''// Criar Plugin Action:
// Tópicos → Sistema → Plugin Actions → + Nova

// Configuração:
Nome: "Abrir Chamado de TI"
Descrição: "Abre um chamado de suporte técnico
  para o usuário. Use quando o usuário mencionar
  problema técnico, falha, erro ou suporte."

// Inputs (o M365 Copilot extrai da mensagem):
Input 1:
  Nome: titulo
  Tipo: Text
  Descrição: "Título ou assunto do problema"
  Obrigatório: Sim

Input 2:
  Nome: prioridade
  Tipo: Text
  Descrição: "Urgência: Alta, Média ou Baixa"
  Obrigatório: Não
  Valor padrão: "Média"

// Ação → Chamar flow "Criar Chamado"''',
                color="#5c2d91")
        with c2:
            formula_card("Tipos de Plugin Action","Conversational, Flow e Conector.",
                "Escolha o tipo baseado no que a ação precisa fazer e de onde vêm os dados.",
                '''// CONVERSATIONAL (recomendado para coleta):
// → Usa tópico do agente para coletar dados
// → Flexível, pode fazer perguntas adicionais
// → Integração com variáveis e fluxo

// FLOW (para ações diretas):
// → Chama flow diretamente sem diálogo
// → Mais rápido para ações simples
// → Power Automate faz o trabalho pesado

// CONNECTOR (para APIs externas):
// → Chama conector diretamente
// → Sem intermediário
// → Útil para consultas simples

// Publicação:
// → Copilot Studio → Publicar
// → Copilot Extensions no Teams Admin
// → Usuário vê o plugin em /apps do Teams''',
                color="#7c3aed")

    with tabs[3]:
        st.markdown("#### Customizar comportamento da IA")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### System Prompt (Instruções personalizadas)")
            st.code('''// Configurações → IA Generativa → Instruções personalizadas

// Exemplo de system prompt:
"""
Você é um assistente virtual da empresa ACME Corp,
especializado em suporte técnico e RH.

Diretrizes de comportamento:
- Sempre se apresente como "Assistente ACME"
- Responda apenas sobre temas de TI e RH
- Para outras perguntas, redirecione para
  o canal correto
- Seja objetivo e profissional
- Use "você" (não "tu" ou "vós")
- Se não souber, diga claramente e sugira
  contato com especialista

Quando mencionar sistemas internos:
- Sistema de chamados: ServiceDesk
- Portal RH: people.acme.com.br
"""''', language="text")
        with c2:
            st.markdown("##### Moderação e segurança de conteúdo")
            st.code('''// Configurações → IA Generativa → Moderação

// Níveis disponíveis:
// Baixo    → menos restrições, mais criativo
// Médio    → padrão recomendado
// Alto     → máximo controle, mais conservador

// O que a moderação bloqueia:
// - Conteúdo ofensivo ou inadequado
// - Informações fora do escopo configurado
// - Tentativas de jailbreak do modelo

// Tópicos sensíveis bloqueados por padrão:
// - Violência, conteúdo adulto
// - Informações de segurança nacional
// → Configure em: Configurações → Segurança de IA

// Auditoria de conversas:
// Analytics → Conversas
// → Filtre por "Não reconhecido" para ver lacunas
// → Use para criar novos tópicos ou fontes''', language="text")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Analytics do Copilot Studio")
            metricas = [
                ("📊","Taxa de resolução","% de conversas resolvidas sem escalonamento. Meta: >70%"),
                ("🎯","Taxa de engajamento","% de usuários que interagem além da primeira mensagem"),
                ("❓","Intenções não reconhecidas","Perguntas sem tópico — oportunidade de melhoria"),
                ("⏱️","Duração média","Tempo médio por conversa — conversas longas = tópico confuso"),
                ("⬆️","Taxa de escalonamento","% transferidas para humano — sinal de gaps no agente"),
                ("😊","CSAT","Satisfação do usuário (thumbs up/down no fim da conversa)"),
            ]
            for ic, m, d in metricas:
                st.markdown(f'<div style="display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #f3f4f6"><div style="font-size:18px">{ic}</div><div><div style="font-weight:700;font-size:12px;color:#111827">{m}</div><div style="font-size:11px;color:#6b7280">{d}</div></div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("#### Melhorias contínuas")
            st.markdown("""
**Ciclo de melhoria semanal:**

1. **Revisar** conversas marcadas como "Não resolvidas"
2. **Identificar** padrões de perguntas sem tópico
3. **Criar tópicos** para as top-5 lacunas da semana
4. **Adicionar** frases à Knowledge Source se for FAQ
5. **Testar** no emulador antes de publicar
6. **Publicar** e monitorar métricas por 48h

**Ferramentas disponíveis:**
- `Copilot Studio → Analytics → Conversas` — revisão de diálogos
- `Tópicos → Análise` — eficácia por tópico
- `Publicar → Validar` — testa antes de ir live
- `Emulador integrado` — testa em tempo real

**Dica:** Configure alertas de Teams quando a taxa
de resolução cair abaixo de 60% usando Power Automate.
            """)

    section_quiz("copilot_ia")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# COPILOT STUDIO — Integração & Canais
# ══════════════════════════════════════════════
def page_copilot_integracao():
    mark_page_visited(current_user()["id"], "copilot_integracao")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Copilot Studio","Integração & Canais")
    hero("copilot_integracao","🌐","Integração & Canais","Teams, SharePoint, site embed, autenticação SSO e boas práticas de deploy.","Avançado")

    tabs = st.tabs(["💬 Microsoft Teams","🌐 Site & Embed","🔐 Autenticação SSO","📡 Direct Line API","🚀 Deploy & ALM"])

    with tabs[0]:
        info_box("💬 <b>Microsoft Teams</b> é o canal principal para agentes corporativos. O agente pode ser distribuído como app de Teams para toda a organização via Admin Center.", "info")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Publicar no Teams","3 passos para o agente aparecer no Teams.",
                "Canal corporativo padrão — integração nativa com autenticação M365.",
                '''// Passo 1: Publicar o agente
// Copilot Studio → Publicar → Publicar

// Passo 2: Adicionar canal Teams
// Canais → Microsoft Teams → Ativar Teams

// Passo 3: Distribuir na organização
// Teams Admin Center:
//   apps.teams.microsoft.com/admin
//   → Aplicativos do Teams → Gerenciar aplicativos
//   → Carregar um aplicativo personalizado
//   → Upload do manifest.zip (baixar do Copilot Studio)
//   → Atribuir para usuários/departamentos/toda org

// Usuário: encontra o bot em Aplicativos do Teams
// ou você pode criar uma guia em canal de equipe''',
                color="#6264a7", tags=["Gratuito","Recomendado"])
            formula_card("Bot em guia de canal","Embed o agente como tab em canal de Teams.",
                "Central de ajuda de uma equipe, suporte integrado ao canal de projeto.",
                '''// Criar guia personalizada:
// Canal → + Adicionar guia → Website
// URL: URL do Web Chat do agente
//   (Canais → Web Chat → Copiar URL)

// Ou via Teams App (mais integrado):
// Manifestoapp → definir "contentUrl" como
// URL do Direct Line Web Chat

// Vantagem: contexto do usuário via SSO
// O agente já conhece quem está falando
// sem pedir login adicional''',
                color="#6264a7")
        with c2:
            formula_card("Notificações proativas","Agente envia mensagem sem o usuário iniciar.",
                "Alertas de aprovação, vencimentos, relatórios automáticos no Teams.",
                '''// Via Power Automate → conector Teams:
// "Publicar mensagem em chat ou canal"

// Para mensagem em chat (1:1 com usuário):
// Postar mensagem de chat ou no canal:
//   Tipo: Chat com bot
//   Bot: [Seu agente Copilot Studio]
//   Destinatário: usuario@empresa.com
//   Mensagem: card adaptável ou texto

// Para card de aprovação proativo:
// "Publicar card adaptável e aguardar resposta"
// → Integra com aprovações nativas do Teams

// ⚠️ Requer que o usuário tenha instalado
// o bot pelo menos uma vez antes''',
                color="#0050d0")
            st.markdown("#### Manifest do Teams App")
            st.code('''// Estrutura do manifest.json:
{
  "manifestVersion": "1.17",
  "id": "guid-do-seu-app",
  "name": {
    "short": "Assistente ACME",
    "full": "Assistente Virtual ACME Corp"
  },
  "description": {
    "short": "Suporte TI e RH",
    "full": "Assistente corporativo para suporte..."
  },
  "bots": [{
    "botId": "guid-do-bot-copilot-studio",
    "isNotificationOnly": false,
    "scopes": ["personal", "team", "groupChat"]
  }],
  "validDomains": ["token.botframework.com"]
}''', language="json")

    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Embed em site (Web Chat)","Adicione o agente em qualquer página HTML.",
                "Portal do cliente, intranet, site institucional, Power Pages.",
                '''// Copilot Studio → Canais → Web Chat → Copiar código

// Snippet gerado (cole no HTML):
<script src="https://cdn.botframework.com/
  botframework-webchat/latest/webchat.js"></script>
<div id="webchat"></div>
<script>
  const styleOptions = {
    botAvatarInitials: 'AC',
    accent: '#0078d4',
    botAvatarBackgroundColor: '#0078d4',
    userAvatarInitials: 'EU',
    backgroundColor: '#f8fafc',
    bubbleBorderRadius: 12,
    bubbleFromUserBorderRadius: 12,
  };
  window.WebChat.renderWebChat({
    directLine: window.WebChat.createDirectLine({
      token: 'SEU_TOKEN_AQUI'  // rotacione via API
    }),
    styleOptions,
    locale: 'pt-BR',
  }, document.getElementById('webchat'));
</script>''',
                color="#0078d4", tags=["HTML","Qualquer site"])
            formula_card("Embed em Power Pages","Integração nativa com Power Pages.",
                "Sites de atendimento ao cliente, portais self-service com Power Pages.",
                '''// Power Pages (make.powerpages.microsoft.com):
// Páginas → + Adicionar componente
// → Copilot

// Autenticação:
// Se o site usa autenticação Power Pages,
// o agente herda a identidade do usuário

// Configuração adicional:
// Copilot Studio → Segurança → Canais confiáveis
// Adicionar: domínio do seu Power Pages site

// Restrição de acesso:
// O chat pode ser configurado para aparecer
// apenas para usuários autenticados''',
                color="#0078d4")
        with c2:
            formula_card("Token de segurança","Nunca exponha a secret key no front-end.",
                "Endpoint back-end que gera tokens temporários para o Web Chat.",
                '''// NUNCA exponha a Direct Line Secret no front-end!
// Crie um endpoint que gera tokens temporários:

// Endpoint (Azure Function / seu back-end):
// GET /api/chattoken
// → Chama API do Bot Framework:
//   POST https://directline.botframework.com/
//          v3/directline/tokens/generate
//   Authorization: Bearer {DIRECT_LINE_SECRET}
// → Retorna token temporário (válido 30min)

// No front-end:
fetch('/api/chattoken')
  .then(r => r.json())
  .then(({token}) => {
    window.WebChat.renderWebChat({
      directLine: window.WebChat.createDirectLine({token})
    }, document.getElementById('webchat'));
  });''',
                color="#dc2626", tags=["Segurança","Obrigatório"])
            info_box("🔐 <b>Segurança crítica:</b> A Direct Line Secret Key é equivalente a uma senha. Sempre use tokens temporários gerados server-side. Nunca coloque a secret diretamente no JavaScript do browser.", "danger")

    with tabs[2]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Configurar Azure AD SSO")
            st.code('''// Passo 1: Registrar app no Azure AD
// portal.azure.com → Azure AD → App registrations
// → + Novo registro
// Nome: "Copilot Studio - SeuAgente"
// Tipo: Contas nesta organização apenas
// URL de redirecionamento:
//   https://token.botframework.com/.auth/web/redirect

// Passo 2: Criar client secret
// Certificates & Secrets → + Novo secret
// Copie o VALUE (não o ID)

// Passo 3: Configurar permissões
// API permissions → + Add permission
// → Microsoft Graph → Delegated:
//   User.Read, email, openid, profile

// Passo 4: Configurar no Copilot Studio
// Configurações → Segurança → Autenticação
// Tipo: Azure Active Directory v2
// Client ID: Application (client) ID do app
// Client Secret: secret criado no passo 2
// Tenant ID: seu tenant ID
// Scope: User.Read''', language="text")
        with c2:
            st.markdown("#### Variáveis SSO disponíveis")
            st.code('''// Após configurar Azure AD SSO,
// estas variáveis ficam disponíveis:

System.User.DisplayName
// "Maria da Silva"

System.User.Email
// "maria.silva@empresa.com"

System.User.FirstName
// "Maria"

System.User.LastName
// "Silva"

System.User.Id
// OID do Azure AD (GUID)

System.User.IsLoggedIn
// true / false

// Uso em mensagem:
// "Olá, {System.User.FirstName}!
//  Seu e-mail é {System.User.Email}."

// Uso em flow chamado pelo agente:
// Passe System.User.Email como input
// → flow acessa dados personalizados do usuário''', language="text")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Direct Line API")
            st.code('''// A Direct Line API permite integração com
// QUALQUER canal/aplicação via REST

// Autenticar:
POST https://directline.botframework.com/
       v3/directline/tokens/generate
Authorization: Bearer {DirectLineSecret}
// → Recebe token temporário

// Iniciar conversa:
POST https://directline.botframework.com/
       v3/directline/conversations
Authorization: Bearer {token}
// → conversationId, streamUrl

// Enviar mensagem:
POST .../conversations/{id}/activities
{
  "type": "message",
  "from": {"id": "user123", "name": "Maria"},
  "text": "Olá, quero abrir um chamado"
}

// Receber resposta (polling):
GET .../conversations/{id}/activities?watermark={wm}
// → activities[] com respostas do bot''', language="text")
        with c2:
            st.markdown("#### Enviar contexto inicial")
            st.code('''// Ao iniciar conversa, envie dados do usuário
// para o agente via InitPayload

// Após criar conversa:
POST .../conversations/{id}/activities
{
  "type": "event",
  "name": "InitPayload",
  "from": {"id": "system"},
  "value": {
    "userEmail":  "maria@empresa.com",
    "userName":   "Maria Silva",
    "userDept":   "TI",
    "userRole":   "Analista",
    "sessionId":  "sess-abc123",
    "language":   "pt-BR"
  }
}

// No Copilot Studio, capture via:
// Tópico "Saudação" → nó Variável:
// Global.UserEmail = System.Activity.Value.userEmail''', language="text")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### Checklist de publicação")
            items = [
                ("✅","Tópico Fallback configurado","Mensagem útil quando não entende"),
                ("✅","Tópico Saudação personalizado","Nome da empresa, opções de menu"),
                ("✅","System Prompt definido","Personalidade e limites do agente"),
                ("✅","Fontes de conhecimento testadas","Respostas corretas nas buscas"),
                ("✅","SSO configurado","Usuário não precisa fazer login separado"),
                ("✅","Moderação configurada","Nível adequado ao público"),
                ("✅","Analytics habilitado","Para monitorar uso pós-deploy"),
                ("✅","Testado no emulador","Principais fluxos validados"),
                ("✅","Aprovação IT Security","Revisão de segurança e privacidade"),
                ("✅","Treinamento dos usuários","Guia de uso e casos de uso"),
            ]
            for ic, t, d in items:
                st.markdown(f'<div style="display:flex;gap:10px;padding:5px 0;border-bottom:1px solid #f3f4f6"><span style="color:#059669;font-weight:700">{ic}</span><div><div style="font-size:12px;font-weight:700;color:#111827">{t}</div><div style="font-size:11px;color:#6b7280">{d}</div></div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("##### Ambientes e ALM")
            st.code('''// Copilot Studio usa Dataverse Solutions
// para ALM (transportar entre ambientes)

// Exportar agente:
// make.powerapps.com → Soluções
// → Adicionar o agente existente à solução
// → Exportar como Managed (produção) ou
//   Unmanaged (desenvolvimento)

// Ambientes recomendados:
// DEV: desenvolvimento e testes
// TEST/UAT: aprovação dos usuários finais
// PROD: publicado para todos

// ⚠️ Verificar antes de exportar:
// - Variáveis de ambiente configuradas
// - Conexões de flows atualizadas
// - Fontes de conhecimento apontando
//   para o ambiente correto (URLs de prod)
// - Client ID/Secret do Azure AD corretos''', language="text")

    section_quiz("copilot_integracao")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# DATAVERSE — Fórmulas & Colunas Calculadas
# ══════════════════════════════════════════════
def page_dataverse_formulas():
    mark_page_visited(current_user()["id"], "dataverse_formulas")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Dataverse","Fórmulas & Colunas Calculadas")
    hero("dataverse_formulas","📐","Fórmulas & Colunas Calculadas","Calculated, Rollup, Power FX e regras de negócio server-side.","Avançado")

    tabs = st.tabs(["📐 Calculated Columns","🔢 Rollup Columns","⚡ Power FX","📋 Business Rules","🔍 FetchXML & OData"])

    with tabs[0]:
        info_box("📐 <b>Calculated Columns</b> são calculadas <b>server-side a cada leitura</b> — o valor é sempre computado na hora, nunca armazenado. Perfeito para concatenações, datas derivadas e cálculos simples.", "info")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Concatenar campos","Combina múltiplos campos em um texto.",
                "Nome completo, código único, endereço formatado.",
                '''// Tipo de coluna: Texto Calculado
// Tipo de dado: Linha de Texto Única

// Fórmula — NomeCompleto:
CONCATENATE(
  cr123_nome,
  " ",
  cr123_sobrenome
)

// Fórmula — Código único:
CONCATENATE(
  "PROJ-",
  TEXT(cr123_ano, "0000"),
  "-",
  TEXT(cr123_sequencia, "000")
)
// → PROJ-2026-001

// Fórmula — Endereço formatado:
CONCATENATE(
  cr123_logradouro, ", ",
  TEXT(cr123_numero), " - ",
  cr123_bairro, ", ",
  cr123_cidade, " - ",
  cr123_estado
)''',
                color="#134e4a", tags=["Server-side","Leitura"])
            formula_card("Datas calculadas","Datas derivadas e diferenças de tempo.",
                "Prazo de vencimento, dias em aberto, data de previsão.",
                '''// Dias em aberto (desde criação):
DIFFINDAYS(createdon, NOW())

// Prazo de vencimento (30 dias após criação):
DATEADD(createdon, 30, "day")

// Status baseado em data:
IF(
  DIFFINDAYS(cr123_datavencimento, NOW()) < 0,
  "Vencido",
  IF(
    DIFFINDAYS(cr123_datavencimento, NOW()) <= 7,
    "Vence em breve",
    "No prazo"
  )
)

// Mês/Ano formatado:
CONCATENATE(
  TEXT(MONTH(cr123_datacompetencia), "00"),
  "/",
  TEXT(YEAR(cr123_datacompetencia), "0000")
)''',
                color="#134e4a")
        with c2:
            formula_card("Valores numéricos calculados","Percentuais, conversões, margens.",
                "Margem de lucro, imposto calculado, conversão de moeda.",
                '''// Margem de lucro (%):
IF(
  cr123_receita > 0,
  ROUND(
    DIVIDE(
      SUBTRACT(cr123_receita, cr123_custo),
      cr123_receita
    ) * 100,
    2
  ),
  0
)

// Desconto aplicado:
MULTIPLY(
  cr123_valorbruto,
  SUBTRACT(1, DIVIDE(cr123_desconto, 100))
)

// Classificação por score:
IF(cr123_score >= 80, "Alto",
  IF(cr123_score >= 60, "Médio",
    IF(cr123_score >= 40, "Baixo", "Crítico")
  )
)''',
                color="#0d9488")
            st.markdown("#### Funções disponíveis em Calculated")
            funcoes = [
                ("CONCATENATE(v1, v2, ...)","Concatena textos"),
                ("ADDDAYS(data, n)","Adiciona dias"),
                ("DIFFINDAYS(d1, d2)","Diferença em dias"),
                ("IF(cond, sim, não)","Condicional"),
                ("AND(c1, c2) / OR(c1, c2)","Lógica"),
                ("ROUND(n, decimais)","Arredondar"),
                ("MULTIPLY/DIVIDE/ADD/SUBTRACT","Aritmética"),
                ("NOW() / TODAY()","Data atual"),
                ("MONTH/YEAR/DAY(data)","Partes de data"),
                ("CONTAINS(texto, busca)","Verificar substring"),
                ("TRIM(texto)","Remover espaços"),
                ("UPPER/LOWER(texto)","Caixa do texto"),
            ]
            for func, desc in funcoes:
                st.markdown(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f3f4f6"><span style="font-family:JetBrains Mono,monospace;font-size:11px;color:#0078d4;font-weight:600">{func}</span><span style="font-size:11px;color:#6b7280">{desc}</span></div>', unsafe_allow_html=True)

    with tabs[1]:
        info_box("🔢 <b>Rollup Columns</b> agregam valores de registros <b>filhos</b> (tabela relacionada 1:N). São calculadas de hora em hora em background — não são em tempo real.", "info")
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Contar registros filhos","Total de registros na tabela relacionada.",
                "Total de tarefas por projeto, pedidos por cliente, chamados por usuário.",
                '''// Tabela PAI: cr123_projeto
// Tabela FILHO: cr123_tarefa
// Relação: cr123_projetoid (lookup no filho)

// Rollup Column em cr123_projeto:
// Nome: cr123_totaldetarefas
// Tipo: Número Inteiro
// Tipo de Rollup: COUNT
// Entidade relacionada: cr123_tarefa
// Relação: cr123_projetoid

// Com filtro (apenas tarefas concluídas):
// Filtro: cr123_status Igual a "Concluída"

// Resultado: projeto.cr123_totaldetarefas
// Atualização: a cada 1 hora
// Force-update: via botão ou flow''',
                color="#0d9488", tags=["1:N","Agrega filhos"])
            formula_card("Soma e Média","Agrega valores numéricos dos filhos.",
                "Valor total de pedidos, horas trabalhadas no projeto, média de scores.",
                '''// SUM — Total de pedidos do cliente:
// Coluna: cr123_totalvendas
// Tipo: Currency
// Rollup: SUM
// Campo a somar: cr123_pedido.cr123_valor
// Filtro: cr123_status != "Cancelado"

// AVG — NPS médio dos clientes:
// Coluna: cr123_npsmedio
// Tipo: Decimal
// Rollup: AVG
// Campo: cr123_avaliacao.cr123_nota

// MIN/MAX — Próximo vencimento:
// Coluna: cr123_proximovencimento
// Tipo: Data e Hora
// Rollup: MIN
// Campo: cr123_parcela.cr123_datavencimento
// Filtro: cr123_status Igual a "Pendente"''',
                color="#0d9488")
        with c2:
            formula_card("Rollup com filtros avançados","Condicione a agregação com filtros.",
                "Tarefas atrasadas por projeto, valor de pedidos em aberto, chamados críticos.",
                '''// Rollup: COUNT de tarefas ATRASADAS
// Filtros (AND):
//   cr123_status != "Concluída"
//   AND
//   cr123_dataprazo < [hoje]  (use "hoje" como valor dinâmico)

// ⚠️ Limitações de Rollup:
// • Atualização a cada 1 hora (não real-time)
// • Máximo de 3 níveis de relação
// • Não funciona com N:N (apenas 1:N)
// • Máximo de 100 condições de filtro

// Forçar recálculo via Power Automate:
// Conector Dataverse → Executar ação vinculada
// Ação: CalculateRollupField
// Tabela: cr123_projeto
// ID: row_id
// Campo: cr123_totaldetarefas''',
                color="#0d9488")
            info_box("⏱️ <b>Rollup não é real-time.</b> Para dados em tempo real, use Calculated Column (se for fórmula simples) ou compute no Power Apps/Automate na hora de salvar.", "warning")

    with tabs[2]:
        info_box("⚡ <b>Power FX nas colunas</b> é o recurso mais recente do Dataverse — permite usar a mesma sintaxe do Power Apps para criar colunas calculadas mais poderosas.", "info")
        c1,c2 = st.columns(2)
        with c1:
            st.code('''// Coluna Power FX — Status calculado:
If(
  ThisRecord.cr123_datavencimento < Today(),
  "Vencido",
  If(
    DateDiff(Today(), ThisRecord.cr123_datavencimento, TimeUnit.Days) <= 7,
    "Vence em " & Text(DateDiff(Today(), ThisRecord.cr123_datavencimento, TimeUnit.Days)) & " dias",
    "No prazo"
  )
)

// Concatenação com função:
Upper(Left(ThisRecord.cr123_nome, 1)) &
Lower(Mid(ThisRecord.cr123_nome, 2)) &
" " &
Upper(Left(ThisRecord.cr123_sobrenome, 1)) &
Lower(Mid(ThisRecord.cr123_sobrenome, 2))

// Acesso a lookup (tabela pai):
ThisRecord.cr123_clienteid.name &
" (" &
ThisRecord.cr123_clienteid.cr123_segmento &
")"''', language="powerapps")
        with c2:
            st.code('''// Switch para categorias:
Switch(
  ThisRecord.cr123_faixavalor,
  0, "Não definida",
  1, "Micro (até R$500)",
  2, "Pequena (R$500-5k)",
  3, "Média (R$5k-50k)",
  4, "Grande (acima R$50k)"
)

// Cálculo com relacionamento:
// (requer Rollup para buscar filhos)
Text(
  Round(
    (ThisRecord.cr123_totalconcluidas /
     Max(ThisRecord.cr123_totaltarefas, 1)) * 100,
    0
  )
) & "% concluído"

// Dica: Power FX é mais flexível que
// Calculated classic, mas ainda em preview
// Verifique disponibilidade no seu ambiente''', language="powerapps")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Business Rules — casos de uso reais")
            st.code('''// Business Rule: campo obrigatório condicional
// "Se Status = Em Aprovação, então Justificativa é obrigatória"

// Condição: Status Igual a "Em Aprovação"
//   ENTÃO:
//     Definir Nível de Recomendação do Campo:
//       Campo: cr123_justificativa
//       Nível: Obrigatório de Negócios

// Business Rule: valor padrão por tipo
// "Se Tipo = Urgente, Prioridade = Alta"

// Condição: cr123_tipo Igual a "Urgente"
//   ENTÃO:
//     Definir Valor do Campo:
//       Campo: cr123_prioridade
//       Valor: "Alta"
//     Mostrar Mensagem:
//       "Item marcado como prioridade Alta automaticamente."

// Business Rule: validação com erro
// "Valor não pode ser negativo"

// Condição: cr123_valor Menor que 0
//   ENTÃO:
//     Mostrar Mensagem de Erro:
//       "Valor deve ser maior ou igual a zero."
//     Definir Nível de Recomendação:
//       Campo: cr123_valor
//       Nível: Obrigatório''', language="text")
        with c2:
            st.markdown("#### Escopo das Business Rules")
            escopos = [
                ("Entidade","Executa SEMPRE — em qualquer app, flow, API","Use para validações críticas de integridade"),
                ("Todos os formulários","Em qualquer form do Dataverse","Para UI/UX padrão em todos os formulários"),
                ("Formulário específico","Apenas em um formulário","Para casos edge em formulário específico"),
                ("Power Apps","Apenas em apps Canvas","Mais flexível, mas não aplica em flows"),
            ]
            for e, quando, uso in escopos:
                st.markdown(f'<div style="background:#f8fafc;border-radius:8px;padding:10px 12px;margin-bottom:8px;border-left:3px solid #134e4a"><div style="font-weight:700;color:#111827;font-size:12px">{e}</div><div style="font-size:11px;color:#065f46;margin:2px 0">{quando}</div><div style="font-size:11px;color:#6b7280">{uso}</div></div>', unsafe_allow_html=True)
            info_box("⭐ <b>Regra de ouro:</b> Use escopo <b>Entidade</b> para validações críticas — elas executam em QUALQUER contexto (app, flow, API, importação). Não dependem de formulário.", "info")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### FetchXML — consultas avançadas")
            st.code('''<!-- FetchXML é a linguagem nativa do Dataverse -->
<!-- Mais poderoso que OData para joins complexos -->

<fetch top="50" aggregate="false">
  <entity name="cr123_projeto">
    <attribute name="cr123_nome" />
    <attribute name="cr123_status" />
    <attribute name="cr123_valorcontrato" />
    <link-entity name="account" 
                 from="accountid" 
                 to="cr123_clienteid"
                 link-type="inner"
                 alias="cliente">
      <attribute name="name" alias="clientenome" />
      <attribute name="cr123_segmento" alias="segmento" />
    </link-entity>
    <filter type="and">
      <condition attribute="cr123_status" 
                 operator="eq" value="Em Andamento" />
      <condition attribute="cr123_valorcontrato" 
                 operator="gt" value="10000" />
    </filter>
    <order attribute="cr123_valorcontrato" 
           descending="true" />
  </entity>
</fetch>

<!-- Gerar FetchXML: Advanced Find no modelo clássico
     ou XrmToolBox → FetchXML Builder -->''', language="xml")
        with c2:
            st.markdown("#### OData — filtros e expand")
            st.code('''// OData $filter
// Usar em Power Automate "Listar linhas" e HTTP

// Filtros simples:
cr123_status eq 'Em Andamento'
cr123_valor gt 1000
cr123_datavencimento lt 2026-12-31T00:00:00Z
cr123_ativo eq true

// Filtros compostos:
cr123_status eq 'Ativo' and cr123_valor gt 5000
cr123_status eq 'A' or cr123_status eq 'B'

// Texto (contains, startswith, endswith):
contains(cr123_nome,'Silva')
startswith(cr123_codigo,'PROJ-2026')

// Lookup (pelo ID):
_cr123_clienteid_value eq {guid-do-cliente}

// $expand (join com tabela pai):
?$expand=cr123_clienteid($select=name,emailaddress1)

// $select (colunas específicas):
?$select=cr123_nome,cr123_status,cr123_valor
&$expand=cr123_clienteid($select=name)
&$filter=cr123_status eq 'Ativo'
&$orderby=cr123_valor desc
&$top=100''', language="text")

    section_quiz("dataverse_formulas")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# DATAVERSE — Integração com Power Apps
# ══════════════════════════════════════════════
def page_dataverse_apps():
    mark_page_visited(current_user()["id"], "dataverse_apps")
    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    breadcrumb("Dataverse","Power Apps + Dataverse")
    hero("dataverse_apps","⚡","Power Apps + Dataverse","Padrões de desenvolvimento, delegação, forms e performance.","Avançado")

    tabs = st.tabs(["🏗️ Padrões CRUD","📊 Delegação Total","🎨 Model-Driven Apps","⚡ Performance","🔗 Solutions"])

    with tabs[0]:
        c1,c2 = st.columns(2)
        with c1:
            formula_card("Create — Patch com Defaults","Criar novo registro com valores padrão.",
                "Formulários de cadastro, novos registros a partir de Gallery.",
                '''// Criar com Defaults (melhor prática):
Patch(
  cr123_projetos,
  Defaults(cr123_projetos),
  {
    cr123_nome:         TextInput1.Text,
    cr123_descricao:    TextInput2.Text,
    cr123_status:       {Value: "Ativo"},  // Choice
    cr123_prioridade:   Dropdown1.Selected, // Choice objeto
    cr123_datainicio:   DatePicker1.SelectedDate,
    cr123_valor:        Value(TextInput3.Text),
    cr123_clienteid: {  // Lookup
      accountid: LookupCliente.Selected.accountid,
      "@odata.type": "Microsoft.Dynamics.CRM.account"
    },
    ownerid: {          // Atribuir a usuário
      systemuserid: gblUsuario.systemuserid,
      "@odata.type": "Microsoft.Dynamics.CRM.systemuser"
    }
  }
)''',
                color="#0078d4", tags=["CRUD","Padrão"])
            formula_card("Update — Patch em registro existente","Editar campos de registro selecionado.",
                "Aprovação inline, edição de registro, atualização de status.",
                '''// Atualizar o registro selecionado na Gallery:
Patch(
  cr123_projetos,
  Gallery1.Selected,  // registro existente
  {
    cr123_status:       {Value: "Em Andamento"},
    cr123_dataupdate:   Now(),
    cr123_responsavel:  {
      systemuserid: gblUsuario.systemuserid,
      "@odata.type": "Microsoft.Dynamics.CRM.systemuser"
    }
  }
);
Notify("✅ Atualizado com sucesso!", NotificationType.Success)

// Atualizar VÁRIOS de uma vez (ForAll):
ForAll(
  Filter(colSelecionados, Selecionado = true),
  Patch(cr123_projetos, ThisRecord,
    {cr123_status: {Value: "Arquivado"}}
  )
)''',
                color="#0078d4")
        with c2:
            formula_card("Read — ClearCollect com delegação","Carregar dados com filtros delegáveis.",
                "Lista principal, Gallery com filtros de usuário.",
                '''// Carga inicial (OnVisible da tela):
ClearCollect(
  colProjetos,
  Filter(
    cr123_projetos,
    // ✅ Todos os filtros abaixo são DELEGÁVEIS:
    cr123_status.Value <> "Cancelado" &&
    cr123_clienteid.accountid = varClienteSel.accountid &&
    cr123_datainicio >= DatePicker_Inicio.SelectedDate
  )
)

// Com lookup expandido (mais rápido que acesso em cadeia):
ClearCollect(
  colProjetos,
  ShowColumns(
    Filter(cr123_projetos, cr123_status.Value = "Ativo"),
    "cr123_nome", "cr123_status",
    "cr123_clienteid_Value"  // campo lookup expandido
  )
)

// Paginação manual:
ClearCollect(
  colPagina,
  FirstN(
    LastN(colProjetos, CountRows(colProjetos) - (varPagina-1)*20),
    20
  )
)''',
                color="#0d9488")
            formula_card("Delete — com confirmação","Exclusão segura com diálogo de confirmação.",
                "Exclusão de registros, com tratamento de erro.",
                '''// Botão Excluir — OnSelect:
UpdateContext({locConfirmar: true})

// Overlay de confirmação — OnSelect "Confirmar":
Remove(cr123_projetos, Gallery1.Selected);
If(
  IsError(Last(Errors(cr123_projetos))),
  Notify("❌ Erro ao excluir: " &
    Last(Errors(cr123_projetos)).Message,
    NotificationType.Error
  ),
  Notify("🗑️ Registro excluído.",
    NotificationType.Success
  )
);
UpdateContext({locConfirmar: false})

// Excluir múltiplos (ForAll):
ForAll(
  Filter(colProjetos, Checked),
  Remove(cr123_projetos, ThisRecord)
)''',
                color="#dc2626")

    with tabs[1]:
        st.markdown("#### Funções delegáveis no Dataverse")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("##### ✅ 100% Delegável")
            st.code('''// FILTER com condições:
Filter(Tabela, campo = valor)      // igualdade
Filter(Tabela, campo > valor)      // comparação
Filter(Tabela, campo >= valor)
Filter(Tabela, campo <> valor)
Filter(Tabela, campo1 && campo2)   // AND
Filter(Tabela, campo1 || campo2)   // OR
Filter(Tabela, lookup.campo = val) // via lookup
Filter(Tabela, StartsWith(campo, "X"))
Filter(Tabela, Contains(campo, "X")) // ✅ Dataverse!

// SORT — também delegável:
SortByColumns(Tabela, "campo", Ascending)
SortByColumns(Tabela, "campo", Descending)

// AGGREGATE — delegável no Dataverse:
CountRows(Filter(Tabela, condicao))
Sum(Filter(Tabela, cond), campo)
Min(Filter(Tabela, cond), campo)
Max(Filter(Tabela, cond), campo)
Average(Filter(Tabela, cond), campo)

// SEARCH — delegável:
Search(Tabela, TxtBusca.Text, "campo1", "campo2")''', language="powerapps")
        with c2:
            st.markdown("##### ⚠️ NÃO delegável — cuidado!")
            st.code('''// Funções que processam LOCALMENTE:
// (limitadas ao limite de delegação = 500-2000 reg)

// ❌ Verificar texto com funções complexas:
Filter(Tabela, Mid(campo, 2, 3) = "ABC") // ❌
Filter(Tabela, Len(campo) > 10)           // ❌

// ❌ Operações em coleções locais
//    (mas coleções são locais por natureza — OK)

// ❌ AddColumns / ShowColumns em fonte direta:
//    Use em collections, não em fonte direta
AddColumns(Tabela, "novo", formula)  // ❌ sem delegação

// ❌ First() / Last() sem Sort delegável:
Last(Filter(Tabela, cond))  // ❌ perigoso

// ✅ CORRETO — use LookUp:
LookUp(Tabela, ID = varId)  // ✅ delegável

// Configurar limite de delegação:
// Arquivo → Configurações → Avançado
// → Limite de linhas de dados: até 2000
// → Recomendado: sempre use filtros''', language="powerapps")

    with tabs[2]:
        info_box("🎨 <b>Model-Driven Apps</b> são geradas automaticamente pelo Dataverse — formulários, grids e navegação prontos, configurados via metadados. Ideal para processos empresariais complexos.", "info")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Canvas vs Model-Driven")
            itens = [
                ("Canvas","Design livre","Você cria cada tela, layout e interação. Flexibilidade total.","Portais do cliente, apps mobile, UX customizado"),
                ("Model-Driven","Gerado pelo modelo","Forms e grids gerados pelo Dataverse. Configuração via metadados.","CRM, ERP, gestão de processos complexos"),
                ("Canvas (embed)","Melhor dos dois","Canvas embutido dentro de Model-Driven para seções customizadas.","Dashboard custom dentro do Dynamics/Model-Driven"),
            ]
            for tipo, sub, desc, uso in itens:
                cor = "#e0f2fe" if "Canvas" in tipo else "#d1fae5"
                st.markdown(f'<div style="background:{cor};border-radius:10px;padding:12px 14px;margin-bottom:8px"><div style="font-weight:800;color:#111827;font-size:13px">{tipo} <span style="font-weight:400;font-size:11px;color:#6b7280">— {sub}</span></div><div style="font-size:12px;color:#374151;margin:4px 0">{desc}</div><div style="font-size:11px;color:#6b7280">💡 {uso}</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("#### Configurar formulário Model-Driven")
            st.code('''// Componentes configuráveis sem código:

// FORMULÁRIO (Form):
// • Campos: adicionar, reordenar, ocultar
// • Tabs: organizar em abas
// • Sections: agrupamentos visuais
// • Quick Forms: formulário resumido
// • Quick View: exibir dados do lookup

// GRADE (View):
// • Colunas exibidas e largura
// • Filtros padrão (System View)
// • Filtros do usuário (Personal View)
// • Ordenação padrão

// GRÁFICO (Chart):
// • Bar, Line, Pie, Funnel
// • Múltiplas séries
// • Vinculado à View ativa

// DASHBOARD:
// • Combina Views, Charts e iframes
// • Pessoal ou compartilhado
// • Power BI embed nativo

// Acesso: make.powerapps.com
// → Aplicativos → Model-Driven App
// → Personalizar tabela → Formulários''', language="text")

    with tabs[3]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Otimizações de performance")
            dicas = [
                ("🔁","Concurrent() para cargas paralelas",
                 "ClearCollect(A,..); ClearCollect(B,..) em sequência = lento.\nConcurrent(ClearCollect(A,..), ClearCollect(B,..)) = paralelo!"),
                ("📋","ShowColumns() para reduzir payload",
                 "Não baixe todas as colunas. Use ShowColumns() ou $select no OData para trazer só o necessário."),
                ("⚡","Salvar em coleção local antes de exibir",
                 "Nunca use a tabela Dataverse diretamente no Items da Gallery. Sempre ClearCollect → Gallery."),
                ("🔍","LookUp ao invés de Filter+First",
                 "LookUp(Tabela, ID=varId) é mais eficiente que First(Filter(Tabela, ID=varId))."),
                ("🏃","OnStart vs OnVisible",
                 "Dados raramente alterados: carregue no OnStart (uma vez). Dados dinâmicos: OnVisible ou explícito."),
                ("📏","Limite de delegação",
                 "Configure o máximo (2000) e use Always filtros no servidor — nunca traga tudo."),
            ]
            for ic, t, d in dicas:
                st.markdown(f'<div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #f3f4f6"><div style="font-size:18px">{ic}</div><div><div style="font-weight:700;font-size:12px;color:#111827">{t}</div><div style="font-size:11px;color:#6b7280;white-space:pre-line;margin-top:2px">{d}</div></div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown("#### Tratamento de erros no CRUD")
            st.code('''// Verificar erro após Patch:
Patch(cr123_projetos, Defaults(cr123_projetos), {
  cr123_nome: TextInput1.Text,
  ...
});
If(
  IsEmpty(Errors(cr123_projetos)),
  // Sucesso:
  Notify("✅ Salvo!", NotificationType.Success);
  Back(),
  // Erro:
  Notify(
    "❌ " & First(Errors(cr123_projetos)).Message,
    NotificationType.Error
  )
)

// Erros comuns e causas:
// "Required field missing" → campo obrigatório vazio
// "Duplicate detection" → regra de duplicata ativada
// "Insufficient privilege" → Security Role faltando
// "Record not found" → registro deletado por outro usuário
// "Principal user missing" → lookup de usuário inválido

// Refresh após salvar:
Refresh(cr123_projetos);
ClearCollect(colProjetos, Filter(...))''', language="powerapps")

    with tabs[4]:
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### Boas práticas com Solutions")
            st.code('''// Sempre desenvolva dentro de uma Solução!
// Tabelas, apps, flows, plugins — tudo na solution

// Criar antes de começar:
// make.powerapps.com → Soluções → + Nova solução
// Nome: "Projeto X"
// Publisher: SEU publisher (define o prefixo cr123_)
// Versão: 1.0.0.0

// Adicionar componentes existentes:
// Solução → Adicionar existente →
//   Tabelas, Apps, Flows, Web Resources

// Versionar:
// 1.0.0.0 → desenvolvimento inicial
// 1.0.1.0 → patches (bug fixes)
// 1.1.0.0 → novos recursos
// 2.0.0.0 → grande redesign

// Exportar para produção:
// Tipo: Managed (protegido)
// → não permite edição direta em prod
// → garante que mudanças vêm pela solution''', language="text")
        with c2:
            st.markdown("#### Variáveis de ambiente")
            st.code('''// Environment Variables → valores que mudam por ambiente
// Ex: URL do SharePoint em DEV é diferente de PROD

// Criar em make.powerapps.com:
// Soluções → sua solução →
// + Novo → Mais → Variável de ambiente
// Nome: cr123_sharepoint_url
// Tipo: Text
// Valor padrão: https://empresa.sharepoint.com/DEV

// Usar em Power Automate:
// Ação: "Obter variável de ambiente"
// Nome: cr123_sharepoint_url
// → retorna string com o valor do ambiente atual

// Usar em Power Apps:
// LookUp(
//   EnvironmentVariableValues,
//   EnvironmentVariableDefinitionId.schemaname =
//   "cr123_sharepoint_url"
// ).Value

// Ao importar em PROD:
// Preencha o valor de produção durante a importação
// → nunca hardcode URLs no código!''', language="text")

    section_quiz("dataverse_apps")
    st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# ROUTER — MAIN ENTRY (must be last — all defs above)
# ─────────────────────────────────────────────
if require_login():
    page_login()
else:
    render_sidebar()
    PAGE_MAP = {
        "home":                  page_home,
        # Power Apps
        "controles":             page_controles,
        "formulas":              page_formulas,
        "navegacao":             page_navegacao,
        "validacao":             page_validacao,
        "performance":           page_performance,
        "seguranca":             page_seguranca,
        "conectores":            page_conectores,
        "variaveis":             page_variaveis,
        # Power Automate
        "automate_fundamentos":  page_automate_fundamentos,
        "automate_expressoes":   page_automate_expressoes,
        "automate_conectores":   page_automate_conectores,
        "automate_aprovacoes":   page_automate_aprovacoes,
        "automate_erros":        page_automate_erros,
        # Copilot Studio
        "copilot_topicos":       page_copilot_topicos,
        "copilot_entidades":     page_copilot_entidades,
        "copilot_ia":            page_copilot_ia,
        "copilot_integracao":    page_copilot_integracao,
        # Dataverse
        "dataverse_tabelas":     page_dataverse_tabelas,
        "dataverse_seguranca":   page_dataverse_seguranca,
        "dataverse_formulas":    page_dataverse_formulas,
        "dataverse_apps":        page_dataverse_apps,
        # Tools
        "cheatsheet":            page_cheatsheet,
        "busca":                 page_busca,
        "quiz":                  page_quiz,
        "picker":                page_picker,
    }
    PAGE_MAP.get(st.session_state.get("page", "home"), page_home)()
