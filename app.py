import os
import re
import json
import html
import time
import random
import base64
import traceback
import unicodedata
import streamlit as st
import streamlit.components.v1 as components
from rag import (
    get_rag_chain,
    extract_article_info,
    clip_context_text,
    REFUSAL_MESSAGE,
    load_departments_config,
    rewrite_conversational_query,
    auto_sync_knowledge_base,
    sanitize_no_markdown_tables,
    is_greeting_or_chitchat,
    get_greeting_or_chitchat_reply,
)

st.set_page_config(
    page_title="VLUTEBOT - Trợ lý Lucas", 
    page_icon="🎓", 
    layout="centered"
)

st.markdown(
    """<style>html, body, .stApp { background-color: #f6f9f8 !important; } [data-testid="stToolbar"]:not(:has([data-testid="stExpandSidebarButton"])), [data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], .stAppDeployButton, [data-testid="stStatusWidget"], [data-testid="stSkeleton"], .stSkeleton, [class*="Skeleton"], [data-testid="stAppViewBlockContainer"] > div:empty { display: none !important; visibility: hidden !important; }</style>""",
    unsafe_allow_html=True,
)

# ==========================================
# CẤU HÌNH NHẬN DIỆN THƯƠNG HIỆU VLUTE
# ==========================================
@st.cache_data(show_spinner=False)
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

lucas_avatar_b64 = get_base64_image("lucas_avatar.png")
avatar_img_html = f'<img src="data:image/png;base64,{lucas_avatar_b64}" width="56" height="56" style="width: 56px; height: 56px; max-width: 56px; max-height: 56px; border-radius: 50%; vertical-align: middle; margin-right: 12px; object-fit: cover; box-shadow: 0 3px 8px rgba(0,0,0,0.25); display: inline-block; flex-shrink: 0;">' if lucas_avatar_b64 else '🎓 '

BOT_AVATAR = "lucas_avatar.png" if os.path.exists("lucas_avatar.png") else "🎓"

# Nạp logo trường dạng base64 để hiển thị tức thì, sắc nét
@st.cache_data
def load_logo_base64(logo_path="logo_vlute.png"):
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

LOGO_B64 = load_logo_base64()

# ==========================================
# CSS GIAO DIỆN CHUẨN CỔNG THÔNG TIN ĐIỆN TỬ VLUTE:
# 1. Header tinh gọn 110-120px: Logo TRÁI, Tiêu đề CANH GIỮA
# 2. 3 huy hiệu trạng thái & Banner lưu ý 1 dòng
# 3. Bong bóng chat max-width: 720px, bo tròn mềm mại
# 4. Sidebar framework chuẩn Dark Charcoal với 2 nhóm liên kết rõ ràng
# ==========================================
st.markdown("""
<style>
/* Vô hiệu hóa hiệu ứng làm mờ khi Streamlit đang tính toán hoặc re-run trên tất cả container lồng nhau */
[data-stale="true"],
[data-stale="true"] *,
.stale-element,
div[data-testid="stVerticalBlock"] {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
}

/* Ẩn hoàn toàn khung bong bóng chat của trợ lý khi chưa có nội dung hoặc đang rỗng */
div[data-testid="stChatMessage"]:has(img[src*="data:image"]) div[data-testid="stChatMessageContent"]:empty,
div[data-testid="stChatMessage"]:has(.avatar-assistant) div[data-testid="stChatMessageContent"]:empty,
div[data-testid="stChatMessageContent"]:not(:has(*)) {
    display: none !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}

#mainmenu_hide,
#MainMenu,
footer,
[data-testid="stDecoration"],
[data-testid="stToolbar"]:not(:has([data-testid="stExpandSidebarButton"])),
[data-testid="stToolbarActions"],
[data-testid="stMainMenu"],
[data-testid="stAppDeployButton"],
.stAppDeployButton,
div[data-testid="stStatusWidget"],
[data-testid="stSkeleton"],
.stSkeleton,
[class*="Skeleton"],
[data-testid="stAppViewBlockContainer"] > div:empty {
    display: none !important;
    visibility: hidden !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
    pointer-events: none !important;
}

header[data-testid="stHeader"] button,
[data-testid="collapsedControl"],
button[data-testid="stExpandSidebarButton"] {
    pointer-events: auto !important;
}

/* Tắt hoàn toàn scroll anchoring mặc định & smooth-scroll gốc của trình duyệt để tránh xung đột với lerp 60fps */
html, body, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"], .main {
    overflow-anchor: none !important;
    scroll-behavior: auto !important;
}

section[data-testid="stMain"] {
    overflow-anchor: none !important;
    scroll-behavior: auto !important;
}

:root {
    --fm-ease-out: cubic-bezier(0.22, 1, 0.36, 1);
    --fm-spring: cubic-bezier(0.34, 1.36, 0.64, 1);
}

div[data-testid="stChatMessage"],
.chat-row-user,
#chat-scroll-anchor {
    overflow-anchor: none !important;
}

#chat-scroll-anchor {
    height: 16px !important;
    width: 100% !important;
}

div.element-container:has(iframe),
div[data-testid="stElementContainer"]:has(iframe),
div[data-testid="stCustomComponentV1"]:has(iframe),
iframe[height="0"],
iframe {
    position: fixed !important;
    width: 0 !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
    overflow: hidden !important;
    line-height: 0 !important;
}

/* 0. Nền chung toàn trang & vùng nội dung chính */
.stApp {
    background-color: #f6f9f8 !important;
    background-image:
        radial-gradient(circle at 50% 0%, rgba(0, 112, 60, 0.055) 0%, transparent 56%),
        radial-gradient(rgba(15, 23, 42, 0.045) 1px, transparent 1px) !important;
    background-size: 100% 100%, 22px 22px !important;
    color: #1e293b !important;
}

.main .block-container,
div[data-testid="stAppViewBlockContainer"],
div[data-testid="stMainBlockContainer"] {
    max-width: 820px !important;
    padding-top: 1.75rem !important;
    padding-bottom: 200px !important;
}

div[data-testid="stMainBlockContainer"]:not(:has(.chat-row-user)),
div[data-testid="stAppViewBlockContainer"]:not(:has(.chat-row-user)),
.main .block-container:not(:has(.chat-row-user)) {
    padding-bottom: 24px !important;
}

/* 1. Khối Hero thống nhất Header + 3 huy hiệu & hiệu ứng GPU chuẩn Framer Motion 60fps */
.vlute-hero-shell {
    contain: layout paint;
    width: 100%;
}

@keyframes fmHeaderGlide {
    from {
        opacity: 0.85;
        transform: translate3d(0, -6px, 0);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0);
    }
}

@keyframes fmBadgeSpring {
    from {
        opacity: 0.85;
        transform: translate3d(0, -6px, 0);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0);
    }
}

.vlute-portal-header {
    background: linear-gradient(135deg, #005a30 0%, #00733c 100%);
    border-radius: 12px;
    padding: 12px 20px;
    margin-bottom: 12px;
    color: white;
    box-shadow: 0 4px 14px rgba(0, 104, 55, 0.22);
    border-bottom: 3px solid #00a65a;
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 110px;
    max-height: 120px;
    box-sizing: border-box;
    animation: fmHeaderGlide 0.26s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

/* Logo nằm bên TRÁI */
.header-logo-left {
    width: 72px;
    display: flex;
    justify-content: flex-start;
    align-items: center;
    flex-shrink: 0;
}

.vlute-logo-img {
    width: 66px;
    height: 66px;
    object-fit: contain;
    filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.3));
    transition: transform 0.25s ease;
}

.vlute-logo-img:hover {
    transform: scale(1.05);
}

/* Tiêu đề nằm chính GIỮA */
.header-center-text {
    flex: 1;
    min-width: 0;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 8px;
}

.vlute-portal-title {
    font-size: 1.25rem;
    font-weight: 800;
    margin: 0;
    color: #ffffff;
    letter-spacing: 0.3px;
    text-align: center;
    line-height: 1.35;
    word-break: keep-all;
}

.vlute-portal-subtitle {
    font-size: 0.88rem;
    color: #ecfdf5;
    margin-top: 4px;
    margin-bottom: 0px;
    font-weight: 500;
    text-align: center;
    line-height: 1.35;
    word-break: keep-all;
}

/* Khoảng trống bên phải để cân bằng đối xứng */
.header-right-spacer {
    width: 72px;
    flex-shrink: 0;
}

/* 2. Thanh 3 huy hiệu trạng thái */
.vlute-nav-ribbon {
    display: flex;
    gap: 10px;
    margin-bottom: 12px;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    width: 100%;
}

.vlute-nav-badge {
    background-color: #008d4c;
    color: white;
    font-size: 0.82rem;
    font-weight: 600;
    padding: 6px 14px;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    box-shadow: 0 2px 5px rgba(0, 141, 76, 0.18);
    transition: box-shadow 0.22s var(--fm-ease-out), border-color 0.2s ease, background-color 0.2s ease !important;
    animation: fmBadgeSpring 0.26s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

.vlute-nav-ribbon .vlute-nav-badge:nth-child(1) {
    animation-delay: 0ms;
}

.vlute-nav-ribbon .vlute-nav-badge:nth-child(2) {
    animation-delay: 30ms;
}

.vlute-nav-ribbon .vlute-nav-badge:nth-child(3) {
    animation-delay: 60ms;
}

.vlute-nav-badge:hover {
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.14);
}

.vlute-nav-badge.official {
    background-color: #e67e22;
    box-shadow: 0 2px 5px rgba(230, 126, 34, 0.18);
}

.vlute-nav-badge.verified {
    background-color: #0073b7;
    box-shadow: 0 2px 5px rgba(0, 115, 183, 0.18);
}

/* Hộp banner lưu ý 1 dòng */
.vlute-alert-box {
    background-color: #fffbe6;
    border: 1px solid #ffe58f;
    border-radius: 8px;
    padding: 9px 16px;
    color: #873800;
    font-size: 0.85rem;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 8px;
    box-shadow: 0 2px 5px rgba(250, 173, 20, 0.08);
    line-height: 1.4;
}

/* 3. NÚT KÉO MỞ SIDEBAR DẠNG 3 GẠCH (☰) */
button[data-testid="stExpandSidebarButton"] *,
[data-testid="stExpandSidebarButton"] *,
[data-testid="stSidebarCollapseButton"] button *,
[data-testid="stSidebarHeader"] button * {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    font-size: 0 !important;
    width: 0 !important;
    height: 0 !important;
    line-height: 0 !important;
    pointer-events: none !important;
}

button[data-testid="stExpandSidebarButton"]::after,
[data-testid="stExpandSidebarButton"]::after,
[data-testid="collapsedControl"]::after,
[data-testid="stSidebarCollapseButton"] button::after,
button[data-testid="stSidebarCollapseButton"]::after,
[data-testid="stSidebarHeader"] button::after {
    display: none !important;
    content: "" !important;
}

/* Khi sidebar THU GỌN - Nút 3 gạch mở ngoài góc trái */
button[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: #ffffff !important;
    border: 1px solid #d2d6de !important;
    border-radius: 6px !important;
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    min-height: 36px !important;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08) !important;
    cursor: pointer !important;
    margin: 6px 0 0 8px !important;
    padding: 0 !important;
    transition: background-color 0.18s ease, border-color 0.18s ease !important;
    font-size: 0 !important;
    color: transparent !important;
}

button[data-testid="stExpandSidebarButton"]:focus,
button[data-testid="stExpandSidebarButton"]:focus-visible,
[data-testid="stExpandSidebarButton"]:focus,
[data-testid="stExpandSidebarButton"]:focus-visible,
[data-testid="collapsedControl"]:focus,
[data-testid="collapsedControl"]:focus-visible {
    outline: none !important;
    box-shadow: none !important;
}

button[data-testid="stExpandSidebarButton"]:hover,
[data-testid="stExpandSidebarButton"]:hover,
[data-testid="collapsedControl"]:hover {
    background-color: #f0f7f3 !important;
    border-color: #008d4c !important;
}

button[data-testid="stExpandSidebarButton"]::before,
[data-testid="stExpandSidebarButton"]::before,
[data-testid="collapsedControl"]::before {
    content: "☰" !important;
    font-size: 20px !important;
    font-weight: 900 !important;
    color: #2c3b41 !important;
    line-height: 1 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
    visibility: visible !important;
    opacity: 1 !important;
}

button[data-testid="stExpandSidebarButton"]:hover::before,
[data-testid="stExpandSidebarButton"]:hover::before,
[data-testid="collapsedControl"]:hover::before {
    color: #008d4c !important;
}

/* Khi sidebar MỞ - Khung đen bao bọc tiêu đề và nút 3 gạch */
[data-testid="stSidebarHeader"] {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    padding: 8px 16px !important;
    background: #141a1d !important;
    border: 1px solid #2b3b42 !important;
    border-radius: 8px !important;
    min-height: 46px !important;
    width: 100% !important;
    box-sizing: border-box !important;
    margin-bottom: 10px !important;
    margin-top: 4px !important;
}

[data-testid="stSidebarHeader"]::before {
    content: "BẢNG ĐIỀU KHIỂN HỌC VỤ" !important;
    font-size: 0.73rem !important;
    font-weight: 700 !important;
    color: #b8c7ce !important;
    letter-spacing: 0.3px !important;
    text-transform: uppercase !important;
    white-space: nowrap !important;
    display: inline-flex !important;
    align-items: center !important;
    margin-right: auto !important;
}

[data-testid="stLogoSpacer"] {
    display: none !important;
}

[data-testid="stSidebarCollapseButton"] button,
button[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarHeader"] button {
    display: inline-flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: rgba(255, 255, 255, 0.08) !important;
    border: 1px solid rgba(255, 255, 255, 0.16) !important;
    border-radius: 6px !important;
    width: 30px !important;
    height: 30px !important;
    min-width: 30px !important;
    min-height: 30px !important;
    cursor: pointer !important;
    padding: 0 !important;
    transition: background-color 0.18s ease, border-color 0.18s ease !important;
    font-size: 0 !important;
    color: transparent !important;
}

[data-testid="stSidebarCollapseButton"] button:focus,
[data-testid="stSidebarCollapseButton"] button:focus-visible,
button[data-testid="stSidebarCollapseButton"]:focus,
button[data-testid="stSidebarCollapseButton"]:focus-visible,
[data-testid="stSidebarHeader"] button:focus,
[data-testid="stSidebarHeader"] button:focus-visible {
    outline: none !important;
    box-shadow: none !important;
}

[data-testid="stSidebarCollapseButton"] button:hover,
button[data-testid="stSidebarCollapseButton"]:hover,
[data-testid="stSidebarHeader"] button:hover {
    background-color: rgba(0, 166, 90, 0.25) !important;
    border-color: #00a65a !important;
}

[data-testid="stSidebarCollapseButton"] button::before,
button[data-testid="stSidebarCollapseButton"]::before,
[data-testid="stSidebarHeader"] button::before {
    content: "☰" !important;
    font-size: 18px !important;
    font-weight: 900 !important;
    color: #ffffff !important;
    line-height: 1 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
    visibility: visible !important;
    opacity: 1 !important;
}

/* 4. SIDEBAR MÀU DARK CHARCOAL */
section[data-testid="stSidebar"] {
    background-color: #222d32 !important;
    border-right: 1px solid #1a2226 !important;
    color: #b8c7ce !important;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.3) !important;
    transition: transform 0.36s var(--fm-ease-out), width 0.36s var(--fm-ease-out), box-shadow 0.36s var(--fm-ease-out) !important;
}

section[data-testid="stSidebar"] * {
    color: #b8c7ce !important;
}

section[data-testid="stSidebar"] strong, 
section[data-testid="stSidebar"] b {
    color: #ffffff !important;
}

/* Thẻ liên hệ phòng ban */
.sidebar-contact-card {
    background-color: #1e282c;
    border: 1px solid #374850;
    border-radius: 8px;
    padding: 12px;
    margin-top: 10px;
    color: #b8c7ce;
}

.sidebar-contact-card code {
    background-color: #141b1e !important;
    color: #a7f3d0 !important;
    border: 1px solid #2b3b42 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-size: 0.82rem !important;
}

/* Thẻ danh mục liên kết hệ thống */
.sidebar-links-card {
    background-color: #1e282c;
    border: 1px solid #374850;
    border-radius: 8px;
    padding: 12px;
    margin-top: 10px;
}

.sidebar-section-title {
    font-size: 0.78rem;
    font-weight: 700;
    color: #00a65a;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.sidebar-link-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
}

.sidebar-link-item {
    display: flex;
    align-items: center;
    gap: 5px;
    background: #141b1e;
    border: 1px solid #2b3b42;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 0.74rem;
    color: #cbd5e1 !important;
    text-decoration: none !important;
    transition: transform 0.18s var(--fm-ease-out), background-color 0.2s var(--fm-ease-out), border-color 0.2s ease, box-shadow 0.2s var(--fm-ease-out);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.sidebar-link-item:hover {
    background: #00a65a !important;
    border-color: #00a65a !important;
    color: #ffffff !important;
    transform: translate3d(0, -2px, 0);
    box-shadow: 0 4px 12px rgba(0, 166, 90, 0.24);
}

.sidebar-link-item:active {
    transform: translate3d(0, 0, 0) scale(0.97);
    transition-duration: 0.14s;
}

.sidebar-link-item svg {
    stroke: #00a65a;
    flex-shrink: 0;
    transition: stroke 0.2s ease, transform 0.2s var(--fm-ease-out);
}

.sidebar-link-item:hover svg {
    stroke: #ffffff !important;
    transform: translateX(2px) scale(1.08);
}

section[data-testid="stSidebar"] .stButton > button {
    border-radius: 8px !important;
    border: none !important;
    background-color: #00a65a !important;
    color: white !important;
    font-weight: 700 !important;
    transition: transform 0.14s var(--fm-ease-out), background-color 0.2s var(--fm-ease-out), box-shadow 0.22s var(--fm-ease-out) !important;
}

section[data-testid="stSidebar"] .stButton > button p {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 7px !important;
    margin: 0 !important;
}

section[data-testid="stSidebar"] .stButton > button p::before {
    content: "";
    display: inline-block;
    width: 15px;
    height: 15px;
    flex-shrink: 0;
    background-color: #ffffff;
    -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8'/%3E%3Cpath d='M3 3v5h5'/%3E%3C/svg%3E") no-repeat center / contain;
    mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8'/%3E%3Cpath d='M3 3v5h5'/%3E%3C/svg%3E") no-repeat center / contain;
}

section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #008d4c !important;
    color: white !important;
    transform: translate3d(0, -2px, 0) !important;
    box-shadow: 0 6px 16px rgba(0, 166, 90, 0.28) !important;
}

section[data-testid="stSidebar"] .stButton > button:active {
    transform: translate3d(0, 0, 0) scale(0.97) !important;
    transition-duration: 0.12s !important;
}

/* 5. KHUNG TIN NHẮN VÀ BONG BÓNG CHAT (MAX-WIDTH: 720PX) — FRAMER MOTION 60FPS KEYFRAMES */
@keyframes fmPromptCascade {
    from {
        opacity: 0;
        transform: translate3d(0, 14px, 0) scale(0.975);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0) scale(1);
    }
}

@keyframes fmUserBubbleIn {
    from {
        opacity: 0.72;
        transform: translate3d(0, 8px, 0) scale(0.99);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0) scale(1);
    }
}

@keyframes fmAssistantBubbleIn {
    from {
        opacity: 0.72;
        transform: translate3d(0, 8px, 0) scale(0.99);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0) scale(1);
    }
}

@keyframes fmContactGlideIn {
    from {
        opacity: 0.15;
        transform: translate3d(0, 8px, 0);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0);
    }
}

@keyframes fmFollowupCascade {
    from {
        opacity: 0.15;
        transform: translate3d(0, 8px, 0);
    }
    to {
        opacity: 1;
        transform: translate3d(0, 0, 0);
    }
}

@keyframes avatarPulse {
    0% {
        box-shadow: 0 0 0 0 rgba(0, 166, 90, 0.45);
    }
    70% {
        box-shadow: 0 0 0 8px rgba(0, 166, 90, 0);
    }
    100% {
        box-shadow: 0 0 0 0 rgba(0, 166, 90, 0);
    }
}

div[data-testid="stChatMessage"]:has(.typing-indicator) div[data-testid="stChatMessageAvatar"] img,
div[data-testid="stChatMessage"]:has(.typing-indicator) [data-testid="stChatMessageAvatarCustom"],
div[data-testid="stChatMessage"]:has(.typing-indicator) img {
    animation: avatarPulse 1.4s cubic-bezier(0.16, 1, 0.3, 1) infinite !important;
}

div[data-testid="stChatMessage"] {
    display: flex !important;
    align-items: flex-start !important;
    margin-bottom: 1.2rem !important;
    gap: 14px !important;
    width: 100% !important;
    background: transparent !important;
    padding: 0 !important;
}

div[data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) {
    flex-direction: row !important;
    justify-content: flex-start !important;
}

/* Avatar Trợ lý Lucas */
div[data-testid="stChatMessageAvatar"] {
    flex-shrink: 0 !important;
    width: 48px !important;
    height: 48px !important;
    min-width: 48px !important;
    min-height: 48px !important;
    aspect-ratio: 1 / 1 !important;
    margin-top: 2px !important;
    border-radius: 50% !important;
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 0 !important;
}

/* Cố định kích thước avatar bong bóng chat 48px, tròn trịa, không bị phóng to */
div[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarCustom"],
div[data-testid="stChatMessage"] img {
    width: 48px !important;
    height: 48px !important;
    min-width: 48px !important;
    min-height: 48px !important;
    max-width: 48px !important;
    max-height: 48px !important;
    aspect-ratio: 1 / 1 !important;
    border-radius: 50% !important;
    object-fit: cover !important;
    transform: none !important;
    border: none !important;
    background: transparent !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
    display: inline-block !important;
}

/* Khung tin nhắn của Lucas: Nền sáng dễ đọc kèm viền nhấn xanh lá VLUTE, MAX-WIDTH: 720px */
div[data-testid="stChatMessageContent"] {
    background-color: #ffffff !important;
    border: 1.5px solid #cbd5e1 !important;
    border-left: 4px solid #00703c !important;
    border-radius: 20px !important;
    padding: 13px 20px !important;
    max-width: 720px !important;
    min-height: 54px !important;
    width: fit-content !important;
    color: #1e293b !important;
    box-sizing: border-box !important;
    line-height: 1.65 !important;
    margin-left: 0px !important;
    box-shadow: 0 4px 14px rgba(0, 112, 60, 0.12) !important;
    word-break: normal !important;
    overflow-wrap: break-word !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease !important;
}

div[data-testid="stChatMessageContent"] ul {
    margin: 8px 0 8px 0 !important;
    padding-left: 20px !important;
}

div[data-testid="stChatMessageContent"] li {
    margin-bottom: 6px !important;
    line-height: 1.6 !important;
    color: #1e293b !important;
}

div[data-testid="stChatMessageContent"] li:last-child {
    margin-bottom: 0px !important;
}

div[data-testid="stChatMessageContent"] p,
div[data-testid="stChatMessageContent"] strong,
div[data-testid="stChatMessageContent"] b {
    color: #1e293b !important;
}

/* Khung tin nhắn Sinh viên (User): Màu xanh dương, MAX-WIDTH: 720px */
.chat-row-user {
    display: flex;
    justify-content: flex-end;
    width: 100%;
    margin-bottom: 1.2rem;
    box-sizing: border-box;
    padding-left: 48px;
}

.user-bubble {
    background-color: #0073b7 !important;
    border: 2px solid #005587 !important;
    color: #ffffff !important;
    border-radius: 20px !important;
    padding: 12px 20px !important;
    max-width: 720px !important;
    width: fit-content;
    white-space: pre-wrap !important;
    word-spacing: normal !important;
    letter-spacing: normal !important;
    word-break: normal !important;
    overflow-wrap: break-word !important;
    font-size: 1rem !important;
    line-height: 1.6 !important;
    box-shadow: 0 4px 14px rgba(0, 115, 183, 0.18) !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease !important;
}

/* Bong bóng người dùng mới nhất xuất hiện theo đường cong Framer Motion 60fps */
.chat-row-user:not(.chat-history-old) {
    animation: fmUserBubbleIn 0.26s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

/* Bong bóng trợ lý mới nhất lướt vào theo đường cong Framer Motion 60fps */
div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)) {
    animation: fmAssistantBubbleIn 0.26s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

/* Thác đổ (stagger) cuối câu trả lời mới: thẻ phòng ban (0.34s) -> đồng bộ tiêu đề + 2 nút gợi ý bằng CSS :has() trong 0.28s */
div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)) .contact-footer-card {
    animation: fmContactGlideIn 0.34s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)):not(:has(div[data-testid="stHorizontalBlock"] > div:nth-child(2) button)) .vlute-followup-title {
    opacity: 0 !important;
    visibility: hidden !important;
    height: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    animation: none !important;
}

div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)):has(div[data-testid="stHorizontalBlock"] > div:nth-child(2) button) .vlute-followup-title {
    animation: fmFollowupCascade 0.28s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)) div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"]:not(:has(> div:nth-child(2) button)) {
    opacity: 0 !important;
    visibility: hidden !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    transform: translate3d(0, 8px, 0) !important;
    animation: none !important;
    pointer-events: none !important;
}

div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)) div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2) button) {
    animation: fmFollowupCascade 0.28s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)) div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2) button) [class*="st-key-followup_"],
div[data-testid="stChatMessage"]:last-of-type:not(:has(.chat-history-old-marker)) div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2) button) [class*="st-key-followup_"] button {
    opacity: 1;
}

/* Triệt tiêu hoàn toàn hiện tượng nháy lại tin nhắn cũ và ẩn tức thì gợi ý cũ khi đang stream */
.chat-row-user.chat-history-old,
div[data-testid="stChatMessage"]:has(.chat-history-old-marker) {
    contain: layout style;
}

.chat-row-user.chat-history-old,
div[data-testid="stChatMessage"]:has(.chat-history-old-marker),
div[data-testid="stChatMessage"]:has(.chat-history-old-marker) .contact-footer-card {
    animation: none !important;
    animation-delay: 0s !important;
    opacity: 1 !important;
    transform: none !important;
    will-change: auto !important;
}

div[data-testid="stChatMessage"]:has(.chat-history-old-marker) .vlute-followup-title,
div[data-testid="stChatMessage"]:has(.chat-history-old-marker) div[data-testid="stHorizontalBlock"],
div[data-testid="stChatMessage"] [data-stale="true"]:has([class*="st-key-followup_"]),
div[data-testid="stChatMessage"] [data-stale="true"]:has(.vlute-followup-title) {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}

/* Thẻ chân trang liên hệ phòng ban có micro-interaction mượt */
.contact-footer-card {
    margin-top: 12px;
    padding: 12px 16px;
    background: #f8fafc;
    border-radius: 8px;
    border-left: 3.5px solid #ff9800;
    color: #334155 !important;
    transition: background-color 0.22s var(--fm-ease-out), box-shadow 0.22s var(--fm-ease-out), border-color 0.22s var(--fm-ease-out) !important;
}

.contact-footer-card:hover {
    box-shadow: 0 6px 16px rgba(0, 90, 48, 0.12);
    background: #f1f5f9;
}

.sidebar-contact-card {
    transition: all 0.2s ease !important;
}

.sidebar-contact-card:hover {
    border-color: #00a65a !important;
}

div[data-testid="stChatMessageContent"] p, .user-bubble p {
    margin-bottom: 0.45rem !important;
}
div[data-testid="stChatMessageContent"] p:last-child, .user-bubble p:last-child {
    margin-bottom: 0px !important;
}

/* Khối Căn cứ trích dẫn trong st.expander dưới câu trả lời */
div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] {
    background: #f8fafc !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 10px !important;
    margin-top: 10px !important;
    color: #1e293b !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] summary {
    color: #0f172a !important;
    font-weight: 700 !important;
    font-size: 0.84rem !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] * {
    color: #334155 !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] code {
    background-color: #e2e8f0 !important;
    color: #0f172a !important;
    font-weight: 600 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] blockquote {
    background-color: #f1f5f9 !important;
    border-left: 3.5px solid #00703c !important;
    padding: 8px 12px !important;
    margin: 6px 0 10px 0 !important;
    border-radius: 4px !important;
    font-size: 0.83rem !important;
    color: #1e293b !important;
    line-height: 1.5 !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] blockquote p,
div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] blockquote span {
    color: #1e293b !important;
    margin-bottom: 0px !important;
}

/* 6. Hoạt ảnh chấm nhảy Typing Indicator trong lúc chờ token đầu tiên */
.typing-indicator {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 4px 2px;
    min-height: 28px;
}

.typing-dots {
    display: inline-flex;
    align-items: center;
    gap: 5px;
}

.typing-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: #00703c;
    display: inline-block;
    animation: typingBounce 1.4s infinite ease-in-out both;
}

.typing-dot:nth-child(1) {
    animation-delay: -0.32s;
}

.typing-dot:nth-child(2) {
    animation-delay: -0.16s;
    background-color: #00a65a;
}

.typing-dot:nth-child(3) {
    animation-delay: 0s;
    background-color: #e67e22;
}

.typing-label {
    font-size: 0.88rem;
    color: #00703c;
    font-style: italic;
    font-weight: 500;
    white-space: nowrap;
}

@keyframes typingBounce {
    0%, 80%, 100% {
        transform: scale(0.55) translateY(0px);
        opacity: 0.4;
    }
    40% {
        transform: scale(1) translateY(-4px);
        opacity: 1;
    }
}

/* 7. Nút bấm câu hỏi gợi ý nhanh & Thẻ 4 nhóm chủ đề */
.quick-prompt-title {
    font-size: 0.92rem;
    font-weight: 700;
    color: #00703c;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.prompt-group-header {
    background: linear-gradient(135deg, #ecfdf5 0%, #f8fafc 100%);
    border: 1px solid #bbf7d0;
    border-left: 4px solid #00703c;
    border-radius: 10px;
    padding: 8px 12px;
    margin-top: 6px;
    margin-bottom: 8px;
    font-size: 0.88rem;
    font-weight: 700;
    color: #005a30;
    transition: all 0.2s ease;
}

.prompt-group-header:hover {
    border-color: #00703c;
    box-shadow: 0 2px 8px rgba(0, 112, 60, 0.1);
}

div[data-testid="stHorizontalBlock"] button {
    background-color: #ffffff !important;
    color: #00703c !important;
    border: 1.5px solid #00703c !important;
    border-radius: 18px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 7px 12px !important;
    text-align: left !important;
    box-shadow: 0 2px 4px rgba(0, 112, 60, 0.08) !important;
    transition: transform 0.22s var(--fm-spring), background-color 0.2s var(--fm-ease-out), box-shadow 0.22s var(--fm-ease-out), border-color 0.2s ease !important;
    white-space: normal !important;
    height: auto !important;
}

div[data-testid="stHorizontalBlock"] button p,
div[data-testid="stHorizontalBlock"] button span,
div[data-testid="stHorizontalBlock"] button [data-testid="stMarkdownContainer"] {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    font-size: 0.82rem !important;
    line-height: 1.35 !important;
}

div[data-testid="stHorizontalBlock"] button:hover {
    background-color: #00703c !important;
    color: #ffffff !important;
    box-shadow: 0 6px 16px rgba(0, 112, 60, 0.22) !important;
    transform: translate3d(0, -2px, 0) !important;
}

div[data-testid="stHorizontalBlock"] button:active {
    transform: translate3d(0, 0, 0) scale(0.97) !important;
    transition: transform 0.12s var(--fm-ease-out), box-shadow 0.12s var(--fm-ease-out), background-color 0.12s ease !important;
}

div[data-testid="stHorizontalBlock"] button:hover p,
div[data-testid="stHorizontalBlock"] button:hover span {
    color: #ffffff !important;
}

/* Hiệu ứng thác đổ chuẩn Framer Motion đồng bộ bằng :has() cho tiêu đề & 4 nút gợi ý chào mừng */
div[data-testid="stMainBlockContainer"]:not(:has(.chat-row-user)) div[data-testid="stHorizontalBlock"]:not(:has(> div:nth-child(2) button)) {
    opacity: 0 !important;
    transform: translate3d(0, 8px, 0) !important;
    animation: none !important;
    pointer-events: none !important;
}

div[data-testid="stMainBlockContainer"]:not(:has(.chat-row-user)) div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2) button) {
    animation: fmPromptCascade 0.42s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

div[data-testid="stMainBlockContainer"]:not(:has(.chat-row-user)) div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2) button) [class*="st-key-welcome_prompt_"] {
    animation: fmPromptCascade 0.42s var(--fm-ease-out) both;
    will-change: transform, opacity;
}

[class*="st-key-welcome_prompt_"][class*="_0"] { animation-delay: 60ms; }
[class*="st-key-welcome_prompt_"][class*="_1"] { animation-delay: 110ms; }
[class*="st-key-welcome_prompt_"][class*="_2"] { animation-delay: 160ms; }
[class*="st-key-welcome_prompt_"][class*="_3"] { animation-delay: 210ms; }

[class*="st-key-shuffle_welcome_btn"] button:active {
    transform: translate3d(0, 0, 0) scale(0.97) !important;
    transition: transform 0.12s var(--fm-ease-out) !important;
}

/* Giữ chiều cao cố định cho hàng 2 nút gợi ý cuối câu trả lời chỉ khi đủ 2 cột để tránh khoảng trắng hụt */
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2) button) {
    min-height: 46px;
}

/* Đảm bảo nút gợi ý bên trong tin nhắn bot có chữ rõ nét, không bị đè màu trắng */
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button p,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button span {
    color: #00703c !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button:hover,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button:hover p,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button:hover span {
    color: #ffffff !important;
}

/* Lớp chuyển sắc mờ ở đáy màn hình & khung chat input */
div[data-testid="stBottom"] {
    background: linear-gradient(to bottom, rgba(246, 249, 248, 0) 0%, rgba(246, 249, 248, 0.92) 32%, #f6f9f8 100%) !important;
}

div[data-testid="stBottom"] > div,
div[data-testid="stBottomBlockContainer"] {
    background: transparent !important;
}

div[data-testid="stChatInput"] {
    border-radius: 12px !important;
}

div[data-testid="stChatInput"] > div {
    transition: box-shadow 0.25s ease, border-color 0.25s ease !important;
}

div[data-testid="stChatInput"] > div:focus-within {
    border-color: #00703c !important;
    box-shadow: 0 0 0 3px rgba(0, 112, 60, 0.15), 0 6px 18px rgba(0, 112, 60, 0.10) !important;
}

div[data-testid="stChatInput"] textarea:focus {
    border-color: #00703c !important;
}

/* Sửa nút 3 gạch phản hồi tức thì sau 1 chạm */
button[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {
    touch-action: manipulation !important;
    -webkit-tap-highlight-color: transparent !important;
    z-index: 99999 !important;
}

@media (max-width: 768px) {
    /* 1. Sidebar chiếm 85% chiều rộng màn hình, không bị tràn hay quá hẹp */
    section[data-testid="stSidebar"] {
        width: 85vw !important;
        min-width: 85vw !important;
        max-width: 85vw !important;
    }
    
    /* 2. Thu gọn Header trên điện thoại để tiết kiệm diện tích cuộn */
    .vlute-portal-header {
        min-height: 85px !important;
        max-height: 95px !important;
        padding: 8px 12px !important;
    }
    .header-right-spacer {
        display: none !important;
    }
    .vlute-logo-img {
        width: 48px !important;
        height: 48px !important;
        max-width: 48px !important;
        max-height: 48px !important;
    }
    .vlute-portal-title {
        font-size: 0.95rem !important;
        line-height: 1.25 !important;
    }
    .vlute-portal-subtitle {
        font-size: 0.75rem !important;
    }

    /* 3. Tối ưu bong bóng chat hiển thị rộng rãi, vừa vặn khung hình */
    div[data-testid="stChatMessage"] {
        gap: 8px !important;
    }
    div[data-testid="stChatMessageAvatar"] {
        width: 34px !important;
        height: 34px !important;
        min-width: 34px !important;
        min-height: 34px !important;
    }
    div[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarCustom"],
    div[data-testid="stChatMessage"] img {
        width: 34px !important;
        height: 34px !important;
        min-width: 34px !important;
        min-height: 34px !important;
        max-width: 34px !important;
        max-height: 34px !important;
    }
    div[data-testid="stChatMessageContent"], .user-bubble {
        max-width: 92% !important;
        font-size: 0.92rem !important;
        padding: 10px 14px !important;
    }
    .chat-row-user {
        padding-left: 0px !important;
    }

    /* 4. Tinh gọn 4 nút gợi ý nhanh: chữ nhỏ gọn, viền mỏng để không chiếm hết màn hình */
    div[data-testid="stHorizontalBlock"] button {
        font-size: 0.78rem !important;
        padding: 6px 10px !important;
        border-radius: 12px !important;
        line-height: 1.3 !important;
    }
    .quick-prompt-title {
        font-size: 0.8rem !important;
        margin-bottom: 4px !important;
    }
}

.rag-status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #ecfdf5;
    border: 1px solid #6ee7b7;
    color: #047857;
    font-size: 0.8rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 18px;
    margin-bottom: 8px;
}
</style>
""", unsafe_allow_html=True)

THINKING_HTML = """
<div class="typing-indicator" aria-label="Lucas đang soạn câu trả lời">
    <div class="typing-dots">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
    </div>
    <span class="typing-label">Lucas đang tra cứu quy chế VLUTE...</span>
</div>
"""

# ==========================================
# KHỞI TẠO VÀ CACHE RAG CHAIN TRƯỚC KHI VẼ GIAO DIỆN
# ==========================================
ANSWER_CACHE_TTL = 1800


@st.cache_resource(show_spinner=False)
def get_answer_cache() -> dict:
    """Bộ nhớ đệm lưu câu trả lời đã đối soát thành công (khóa _strip_accents(rewritten_query), TTL 1800s)."""
    return {}


def ensure_kb_synced_and_fresh_cache() -> dict:
    """Kiểm tra đồng bộ thư mục data/ và xóa cache câu trả lời ngay nếu phát hiện văn bản thêm/sửa/xóa."""
    sync_res = auto_sync_knowledge_base()
    if isinstance(sync_res, dict) and sync_res.get("changed"):
        get_answer_cache().clear()
    return sync_res


@st.cache_resource(show_spinner=False)
def load_chain():
    """Nạp chuỗi RAG Lucas một lần duy nhất vào bộ nhớ cache toàn cục (Singleton)."""
    return get_rag_chain()


@st.cache_resource(show_spinner=False)
def init_rag_runtime_once():
    """Khởi tạo RAG chain và đồng bộ tri thức một lần duy nhất trong @st.cache_resource trước khi vẽ giao diện."""
    chain = load_chain()
    ensure_kb_synced_and_fresh_cache()
    return chain


try:
    if "qa_chain" not in st.session_state:
        st.session_state.qa_chain = init_rag_runtime_once()
    qa_chain = st.session_state.qa_chain
except Exception as e:
    st.error(f"Lỗi khởi tạo hệ thống: {e}")
    st.stop()

# ==========================================
# 1. HEADER TINH GỌN (110-120PX) & 3 HUY HIỆU TRONG CÙNG KHỐI THỐNG NHẤT
# ==========================================
logo_html_img = f'<img src="data:image/png;base64,{LOGO_B64}" class="vlute-logo-img" width="66" height="66" style="width: 66px; height: 66px; max-width: 66px; max-height: 66px; object-fit: contain; display: block; flex-shrink: 0;" alt="Logo VLUTE" />' if LOGO_B64 else '<span style="font-size:32px;">🎓</span>'

st.markdown(f"""
<div class="vlute-hero-shell" style="contain: layout paint;">
  <div class="vlute-portal-header">
    <div class="header-logo-left">
      {logo_html_img}
    </div>
    <div class="header-center-text">
      <div class="vlute-portal-title">
        {avatar_img_html}LUCAS – TRỢ LÝ QUY CHẾ & HỌC VỤ VLUTE
      </div>
      <div class="vlute-portal-subtitle">
        Hệ thống tra cứu từ văn bản chính thức của Nhà trường
      </div>
    </div>
    <div class="header-right-spacer"></div>
  </div>
  <div class="vlute-nav-ribbon">
    <div class="vlute-nav-badge">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      <span>Tra cứu học vụ</span>
    </div>
    <div class="vlute-nav-badge official">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>
      <span>Văn bản chính thức</span>
    </div>
    <div class="vlute-nav-badge verified">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>
      <span>Trả lời có căn cứ</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

def _outline_svg(paths_markup: str, size: int = 14, color: str = "currentColor") -> str:
    """Tạo icon SVG đường nét đơn sắc (stroke-width=2) dùng thống nhất cho Sidebar."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'style="flex-shrink: 0; display: inline-block; vertical-align: middle;">'
        f'{paths_markup}</svg>'
    )


SVG_PIN_ICON = _outline_svg(
    '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    size=14,
    color="#00a65a",
)
SVG_LINK_ICON = _outline_svg(
    '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
    '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    size=14,
    color="#00a65a",
)
SVG_LANDMARK_ICON = _outline_svg(
    '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/>'
    '<line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/>'
    '<line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    size=14,
    color="#00a65a",
)
SVG_SIDEBAR_PHONE_HEADER = _outline_svg(
    '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 '
    '19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 '
    '12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27'
    'a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    size=14,
    color="#00a65a",
)
SVG_SIDEBAR_PHONE_ROW = _outline_svg(
    '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 '
    '19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 '
    '12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27'
    'a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    size=12,
    color="#94a3b8",
)
SVG_SIDEBAR_MAIL_ROW = _outline_svg(
    '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    size=12,
    color="#94a3b8",
)
SVG_GLOBE_ICON = _outline_svg(
    '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    size=14,
)
SVG_FILE_EDIT_ICON = _outline_svg(
    '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
    '<path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62'
    'l.84-2.873a2 2 0 0 1 .506-.852z"/>',
    size=14,
)
SVG_MONITOR_ICON = _outline_svg(
    '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/>'
    '<line x1="12" x2="12" y1="17" y2="21"/>',
    size=14,
)
SVG_CARD_ICON = _outline_svg(
    '<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>',
    size=14,
)
SVG_COMPASS_ICON = _outline_svg(
    '<circle cx="12" cy="12" r="10"/>'
    '<polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    size=14,
)
SVG_CLIPBOARD_ICON = _outline_svg(
    '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/>'
    '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
    '<path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>',
    size=14,
)
SVG_USERS_ICON = _outline_svg(
    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
    '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    size=14,
)
SVG_WALLET_ICON = _outline_svg(
    '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/>'
    '<path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    size=14,
)


def reset_chat_history():
    """Callback làm mới hội thoại không cần gọi st.rerun() thủ công."""
    st.session_state.messages = []
    st.session_state.pending_user_query = None
    st.session_state.kb_synced = False
    st.session_state.greeting_turn_count = 0
    prev_queries = [
        p.get("query", "") for p in st.session_state.get("welcome_prompts", [])
        if isinstance(p, dict)
    ]
    st.session_state.welcome_prompts = get_random_welcome_prompts(previous_queries=prev_queries)
    st.session_state.welcome_shuffle_count = int(st.session_state.get("welcome_shuffle_count", 0)) + 1


VERIFY_BADGE_HTML = """<div style="display: inline-flex; align-items: center; background: #e8f5e9; color: #2e7d32; font-size: 13px; font-weight: 600; padding: 4px 12px; border-radius: 16px; margin-bottom: 8px;">
✅ Đã đối soát thành công - Được trích từ quy chế liên quan
</div>"""


def get_verify_badge_html(elapsed_time=None) -> str:
    """Kết xuất huy hiệu đối soát thành công có hiển thị thời gian xử lý (elapsed_time)."""
    if elapsed_time is not None:
        badge_label = f"✅ Đã đối soát thành công ({elapsed_time}s) - Được trích từ quy chế liên quan"
    else:
        badge_label = "✅ Đã đối soát thành công - Được trích từ quy chế liên quan"
    return f"""<div style="display: inline-flex; align-items: center; background: #e8f5e9; color: #2e7d32; font-size: 13px; font-weight: 600; padding: 4px 12px; border-radius: 16px; margin-bottom: 8px;">
{badge_label}
</div>"""


def _escape_unsafe_lt(text: str) -> str:
    """Escape dấu < không phải thẻ HTML hợp lệ để tránh trình duyệt nuốt chữ như <C, <2,5."""
    if not text:
        return ""
    return re.sub(
        r"<(?![/\s]*(?:strong|em|b|i|u|br|p|ul|ol|li|code|pre|blockquote|hr|h[1-6]|a\b|span\b|div\b))",
        "&lt;",
        text,
    )


def build_assistant_bubble_html(content: str, contact_html: str = "", elapsed_time=None, is_refusal: bool = False, is_welcome_or_greeting: bool = False) -> str:
    """Gộp Huy hiệu + Nội dung + Khối liên hệ vào chung 1 chuỗi Markdown/HTML duy nhất để cố định 1 DOM Slot."""
    cleaned_content = sanitize_no_markdown_tables((content or "").strip())
    body = _escape_unsafe_lt(cleaned_content)
    if is_welcome_or_greeting:
        return body
    if is_refusal:
        if not body:
            body = REFUSAL_MESSAGE
        body = re.sub(r"^[•\-\*]\s+", "", body)
        return f"{body}\n\n{contact_html}" if contact_html else body

    badge = get_verify_badge_html(elapsed_time)
    return f"{badge}\n\n{body}\n\n{contact_html}" if contact_html else f"{badge}\n\n{body}"

SVG_PHONE_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#005a30" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -3px; margin-right: 5px; flex-shrink: 0;"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>'
SVG_LIGHTBULB_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#00703c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -3px; margin-right: 4px; flex-shrink: 0;"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>'

CTSV_CONTACT_HTML = f"""<div class="contact-footer-card">
  <b style="color: #005a30 !important;">{SVG_PHONE_ICON}Phòng Công tác Sinh viên (VLUTE):</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;">Vị trí: Tòa nhà A (Phòng A1.102 - Tầng trệt)</li>
    <li style="color: #334155 !important;">Điện thoại: (0270) 3862 436 | Email: ctsv@vlute.edu.vn</li>
  </ul>
</div>"""

KHTC_CONTACT_HTML = f"""<div class="contact-footer-card">
  <b style="color: #005a30 !important;">{SVG_PHONE_ICON}Phòng Kế hoạch - Tài chính (VLUTE):</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;">Vị trí: Tòa nhà A (Tầng trệt)</li>
    <li style="color: #334155 !important;">Điện thoại: (0270) 3822 141 | Email: khtc@vlute.edu.vn</li>
  </ul>
</div>"""

RATE_LIMIT_MESSAGE = "⚠️ Hệ thống tra cứu đang nhận lượng truy cập cao trong cùng thời điểm. Bạn vui lòng đợi khoảng 30–60 giây rồi thử hỏi lại nhé!"


def _build_rag_prompt_and_sources(effective_query: str, docs: list, chain):
    """Chuẩn bị prompt ngữ cảnh giới hạn tối đa 5 đoạn trích (<= 560 ký tự/đoạn) và danh sách nguồn đối soát."""
    context_parts = []
    sources = []
    for doc in docs[:5]:
        src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
        title = doc.metadata.get("title", src_file)
        page = doc.metadata.get("page", 1)
        raw_content = doc.page_content.strip()
        article = extract_article_info(doc.page_content)

        header_line = f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
        context_parts.append(f"{header_line}\n{clip_context_text(raw_content)}")

        sources.append({
            "file": src_file,
            "title": title,
            "short_title": title,
            "dept": doc.metadata.get("dept_name", "VLUTE"),
            "dept_key": doc.metadata.get("dept_key", "ctsv"),
            "dept_name": doc.metadata.get("dept_name", "Phòng Công tác Sinh viên (VLUTE)"),
            "dept_location": doc.metadata.get("dept_location", "Tòa nhà A (Phòng A1.102 - Tầng trệt)"),
            "dept_phone": doc.metadata.get("dept_phone", "(0270) 3862 436"),
            "dept_email": doc.metadata.get("dept_email", "ctsv@vlute.edu.vn"),
            "page": page,
            "article": article,
            "snippet": raw_content
        })

    context_str = "\n\n".join(context_parts)
    formatted_prompt = chain.prompt.format(context=context_str, input=effective_query)
    return formatted_prompt, sources


def execute_rag_pipeline(query: str, chat_history: list | None = None):
    """Thực thi trực tiếp (live) pipeline RAG sử dụng chain đã cache."""
    effective_query = rewrite_conversational_query(query, chat_history) if chat_history else query
    chain = load_chain()
    docs = chain.filter_documents(effective_query, k=6)
    if not docs:
        return REFUSAL_MESSAGE, [], 0

    formatted_prompt, sources = _build_rag_prompt_and_sources(effective_query, docs, chain)

    try:
        response_obj = chain.llm.invoke(formatted_prompt)
        raw_answer = getattr(response_obj, "content", str(response_obj))
    except Exception as api_err:
        err_str = str(api_err)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
            raw_answer = RATE_LIMIT_MESSAGE
        else:
            traceback.print_exc()
            raise api_err

    return raw_answer, sources, len(docs)


def stream_rag_pipeline(query: str, chat_history: list | None = None):
    """Thực thi trực tiếp (live) luồng RAG streaming với k=6 đoạn trích từ chain đã cache."""
    effective_query = rewrite_conversational_query(query, chat_history) if chat_history else query
    chain = load_chain()
    docs = chain.filter_documents(effective_query, k=6)
    if not docs:
        return None, [], 0, []

    formatted_prompt, sources = _build_rag_prompt_and_sources(effective_query, docs, chain)

    def generate_content_stream():
        yielded_any = False
        try:
            for chunk in chain.llm.stream(formatted_prompt):
                chunk_text = getattr(chunk, "content", str(chunk))
                if isinstance(chunk_text, list):
                    chunk_text = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in chunk_text
                    )
                if chunk_text:
                    yielded_any = True
                    yield chunk_text
            if not yielded_any:
                resp_obj = chain.llm.invoke(formatted_prompt)
                fallback_text = getattr(resp_obj, "content", str(resp_obj))
                if fallback_text and str(fallback_text).strip():
                    yield str(fallback_text)
        except Exception as stream_err:
            if not yielded_any:
                raise stream_err
            err_str = str(stream_err)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
                yield f"\n\n{RATE_LIMIT_MESSAGE}"
            else:
                raise stream_err

    return generate_content_stream(), sources, len(docs), docs


def normalize_query_intent(query: str) -> str:
    """Làm sạch khoảng trắng, lọc từ gọi bot & mở rộng viết tắt quy chế ở câu hỏi ngắn."""
    if not query:
        return ""
    cleaned = re.sub(r"\s+", " ", query.strip())
    words = cleaned.split()
    if len(words) <= 5 and not is_greeting(cleaned):
        q_lower = cleaned.lower()
        has_vocative = any(
            re.search(rf"\b{v}\b", q_lower)
            for v in ("lucas", "alo", "ad", "chào", "ơi")
        )
        if has_vocative:
            q_punct = "?" if cleaned.endswith("?") else ""
            stripped = re.sub(
                r"\b(?:xin\s+chào|chào|hello|hi|hey|lucas|alo|ad|ơi)\b",
                " ",
                cleaned,
                flags=re.IGNORECASE,
            )
            stripped = re.sub(r"^[\s\,\.\:\!\?\-]+|[\s\,\.\:\!\?\-]+$", "", stripped)
            stripped = re.sub(r"\s+", " ", stripped).strip()
            if stripped:
                acronym_map = {
                    "ctxh": "Công tác xã hội (CTXH)",
                    "kkht": "Học bổng khuyến khích học tập (KKHT)",
                    "ctsv": "Công tác sinh viên (CTSV)",
                    "attt": "An toàn thông tin (ATTT)",
                    "khtc": "Kế hoạch tài chính (KHTC)",
                }
                for abbr, full_name in acronym_map.items():
                    stripped = re.sub(
                        rf"\b{abbr}\b",
                        full_name,
                        stripped,
                        flags=re.IGNORECASE,
                    )
                if len(stripped.split()) <= 6 and not re.search(r"(?i)\b(quy\s+định|quy\s+chế|về)\b", stripped):
                    stripped = f"Quy định về {stripped}"
                return f"{stripped}{q_punct}"
    return cleaned

# ==========================================
# 2. TINH GỌN LỜI CHÀO MỞ ĐẦU
# ==========================================
WELCOME_CONTENT = (
    "**Xin chào! Mình là Lucas** – trợ lý hỗ trợ tra cứu Quy chế Đào tạo & Quy định sinh viên VLUTE.\n\n"
    "Bạn có thể chọn nhanh một trong các câu hỏi gợi ý bên dưới hoặc nhập trực tiếp thắc mắc về học bổng, miễn giảm học phí, công tác xã hội, kỷ luật hay học vụ!"
)

if "messages" not in st.session_state or len(st.session_state.messages) == 0:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": WELCOME_CONTENT,
            "sources": [],
            "is_refusal": True
        }
    ]
elif len(st.session_state.messages) == 1 and st.session_state.messages[0]["role"] == "assistant":
    st.session_state.messages[0]["content"] = WELCOME_CONTENT
    st.session_state.messages[0]["is_refusal"] = True

PROMPTS_FILE = os.path.join(os.path.dirname(__file__), "prompts.json")


@st.cache_data
def load_prompts_config() -> dict:
    """Nạp danh sách câu hỏi gợi ý từ tệp prompts.json."""
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"initial_prompts": [], "categories": {}}


def get_random_welcome_prompts(previous_queries=None) -> list[dict]:
    """Lấy ngẫu nhiên 4 câu hỏi gợi ý từ 24 câu trong categories, luôn loại trừ bộ câu đang hiển thị."""
    config = load_prompts_config()
    categories = config.get("categories", {})
    prev_set = {str(q).strip() for q in (previous_queries or []) if str(q).strip()}
    selected = []
    remaining_pool = []

    for _cat_key, cat_data in categories.items():
        prompts = [
            p for p in cat_data.get("prompts", [])
            if isinstance(p, dict) and p.get("label") and p.get("query")
        ]
        if prompts:
            candidates = [p for p in prompts if str(p.get("query")).strip() not in prev_set]
            pool = candidates if candidates else prompts
            chosen = random.choice(pool)
            selected.append(chosen)
            for p in prompts:
                if p != chosen and str(p.get("query")).strip() not in prev_set:
                    remaining_pool.append(p)

    if len(selected) > 4:
        selected = random.sample(selected, 4)
    elif len(selected) < 4:
        fallback_pool = remaining_pool or [
            p for p in config.get("initial_prompts", [])
            if isinstance(p, dict) and p.get("label") and p.get("query") and str(p.get("query")).strip() not in prev_set
        ]
        need = 4 - len(selected)
        if fallback_pool:
            selected.extend(random.sample(fallback_pool, min(need, len(fallback_pool))))

    return selected[:4]


# Callback gán câu hỏi trực tiếp vào session_state trước khi rerun
if "pending_user_query" not in st.session_state:
    st.session_state.pending_user_query = None


def submit_user_query(query_text: str):
    st.session_state.pending_user_query = query_text


def shuffle_welcome_prompts():
    """Callback đổi nhanh 4 câu hỏi gợi ý mới (khác 100% 4 câu hiện tại) và tăng bộ đếm animation."""
    prev_queries = [
        p.get("query", "") for p in st.session_state.get("welcome_prompts", [])
        if isinstance(p, dict)
    ]
    st.session_state.welcome_prompts = get_random_welcome_prompts(previous_queries=prev_queries)
    st.session_state.welcome_shuffle_count = int(st.session_state.get("welcome_shuffle_count", 0)) + 1

def clean_snippet_text(text: str) -> str:
    """Làm sạch đoạn trích quy chế, loại bỏ các ký tự rác, dấu sao, lỗi chính tả từ quét PDF."""
    if not text:
        return ""
    cleaned = re.sub(r"^[\s\.\,\;\"\'\:\-\_\|\*\#\`\(\)]+", "", text)
    cleaned = re.sub(r"^[A-Z0-9\s]{4,35}[\,\.\:\;]\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

# ==========================================
# 3. ĐÍNH KÈM CĂN CỨ TRÍCH DẪN (SOURCE CARD)
# ==========================================
def render_sources(sources_list):
    """
    (Đã loại bỏ khối st.expander Căn cứ văn bản trích dẫn theo yêu cầu)
    """
    return
    # if not sources_list:
    #     return
    # 
    # grouped = {}
    # for item in sources_list:
    #     file_name = item.get("file", "")
    #     doc_info = DOC_CATALOG.get(file_name, {})
    #     title = item.get("title") or doc_info.get("title", file_name)
    #     dept = item.get("dept") or doc_info.get("dept", "ĐH Công nghệ Kỹ thuật Vĩnh Long")
    #     
    #     if file_name not in grouped:
    #         grouped[file_name] = {
    #             "title": title,
    #             "dept": dept,
    #             "items": []
    #         }
    #     
    #     page = item.get("page", 1)
    #     article = item.get("article", "")
    #     snippet = clean_snippet_text(item.get("snippet", ""))
    #     
    #     key = f"{page}_{article}"
    #     if not any(f"{it.get('page')}_{it.get('article')}" == key for it in grouped[file_name]["items"]):
    #         grouped[file_name]["items"].append({
    #             "page": page,
    #             "article": article,
    #             "snippet": snippet
    #         })
    # 
    # total_chunks = sum(len(g["items"]) for g in grouped.values())
    # expander_label = f"📑 CĂN CỨ VĂN BẢN TRÍCH DẪN ({total_chunks} đoạn trích đối chiếu)"
    # 
    # with st.expander(expander_label, expanded=False):
    #     for idx, (file_name, gdata) in enumerate(grouped.items(), 1):
    #         st.markdown(f"📄 **{gdata['title']}** — *({gdata['dept']})*")
    #         for sub in gdata["items"]:
    #             loc_parts = [f"Trang {sub['page']}"]
    #             if sub['article']:
    #                 clean_art = sub['article'].replace("*", "").replace("`", "").strip()
    #                 loc_parts.append(clean_art)
    #             loc_label = " - ".join(loc_parts)
    #             
    #             snippet_text = sub['snippet']
    #             st.markdown(f"📍 **Vị trí: {loc_label}**")
    #             quote_block = "\n> ".join(snippet_text.splitlines())
    #             st.markdown(f"> {quote_block}")
    #         if idx < len(grouped):
    #             st.markdown("<hr style='margin: 8px 0; border-color: rgba(0, 0, 0, 0.1);'>", unsafe_allow_html=True)

# ==========================================
# PHÂN LOẠI CÂU HỎI VÀ ĐẦU MỐI LIÊN HỆ
# ==========================================
GREETING_KEYWORDS = ["chào", "hello", "hi", "bạn là ai", "tên gì", "giới thiệu", "alo", "lucas", "xin chào", "hey", "ad"]
GREETING_REPLIES = [
    "Chào bạn! Mình là Lucas – trợ lý học vụ VLUTE. Hôm nay bạn muốn tra cứu quy định về học bổng, học phí, công tác xã hội hay học vụ? *(Bạn có thể bấm chọn nhanh gợi ý bên dưới hoặc nhập trực tiếp câu hỏi nhé!)*",
    "Xin chào! Rất vui được đồng hành cùng bạn. Bạn đang quan tâm đến chế độ chính sách, điểm rèn luyện hay quy chế đào tạo tại VLUTE? *(Hãy chọn một gợi ý bên dưới hoặc gõ câu hỏi cụ thể nhé!)*",
    "Chào bạn nhé! Lucas luôn sẵn sàng hỗ trợ bạn giải đáp các quy định về khóa luận, tốt nghiệp hay kỷ luật sinh viên VLUTE. *(Bạn có thể tham khảo các câu hỏi gợi ý bên dưới hoặc đặt câu hỏi trực tiếp cho mình!)*",
    "Chào bạn! Mình có thể giúp gì cho bạn hôm nay? Bạn cứ nhập thắc mắc về học vụ, miễn giảm học phí, học bổng hoặc chọn nhanh một chủ đề gợi ý ngay bên dưới nhé!",
]

def is_greeting(query: str) -> bool:
    """Nhận diện nhanh các câu chào hỏi xã giao bằng ranh giới từ (\\b) để tránh khớp nhầm."""
    clean = query.lower().strip()
    words = clean.split()
    duty_keywords = [
        "học bổng", "học phí", "tín chỉ", "cảnh báo", "điểm", "rút môn",
        "thôi học", "miễn giảm", "bảo hiểm", "quy chế", "điều",
        "ctxh", "công tác xã hội", "kỷ luật", "thi hộ", "thi thay",
        "học thay", "tốt nghiệp", "khóa luận", "rèn luyện", "hoàn trả",
        "hồ sơ", "thủ tục", "mật khẩu", "email", "trang phục", "ứng xử",
        "ban cán sự", "khiếu nại", "vượt khó", "đề cương", "học phần",
        "giảng viên", "tiên quyết", "chuẩn đầu ra", "giáo trình", "hệ số",
    ]
    if len(words) <= 4 and any(re.search(rf"\b{re.escape(k)}\b", clean) for k in GREETING_KEYWORDS):
        if not any(dk in clean for dk in duty_keywords):
            return True
    return False


def check_social_or_command_reply(query: str) -> str | None:
    """
    Nhận diện các câu cảm thán, cảm ơn, xác nhận hoặc câu lệnh ngắn không có nội dung tra cứu quy chế
    (như 'đặt câu hỏi đi', 'hỏi đi', 'nói đi', 'ok', 'cảm ơn', 'thanks') để phản hồi thân thiện
    và không gắn huy hiệu đối soát.
    """
    return get_greeting_or_chitchat_reply(query)

def is_refusal_answer(text: str) -> bool:
    """Kiểm tra xem phản hồi của mô hình có phải là câu từ chối ngoài phạm vi dữ liệu, quá tải hoặc bị gián đoạn giữa chừng hay không."""
    t = (text or "").lower().strip()
    if not t:
        return True
    if "phản hồi bị gián đoạn giữa chừng" in t:
        return True
    if "lượng truy cập cao" in t or "đợi khoảng 30–60 giây" in t:
        return True
    if "không được đề cập trong các văn bản quy định" in t or "nằm ngoài phạm vi dữ liệu quy chế" in t:
        return True
    has_legal_citation = bool(
        re.search(r"\b(?:điều|khoản|mục|chương|quyết\s+định|phụ\s+lục)\s+[ivxlcdm\d]+", t)
    )
    if len(t) < 220 and not has_legal_citation and any(kw in t for kw in ["không được đề cập", "ngoài phạm vi dữ liệu"]):
        return True
    return False

def _strip_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và chuyển khoảng trắng thành gạch dưới để so khớp với patterns trong departments.json."""
    if not text:
        return ""
    s = text.lower().replace("đ", "d")
    s = "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _build_contact_footer_html(dept_name: str, dept_location: str, dept_phone: str, dept_email: str) -> str:
    """Kết xuất khối HTML chân trang thông tin phòng ban theo chuẩn CSS giao diện nền sáng."""
    return f"""<div class="contact-footer-card">
  <b style="color: #005a30 !important;">{SVG_PHONE_ICON}{dept_name}:</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;">Vị trí: {dept_location}</li>
    <li style="color: #334155 !important;">Điện thoại: {dept_phone} | Email: {dept_email}</li>
  </ul>
</div>"""


def get_contact_footer(query: str, retrieved_docs=None, is_refusal: bool = False) -> str:
    """
    Kết xuất chân trang động ưu tiên theo chủ đề chính của câu hỏi:
    - Nếu câu hỏi chứa từ khóa học bổng, khen thưởng, rèn luyện, kỷ luật, công tác xã hội, ctxh:
      LUÔN định tuyến về Phòng Công tác Sinh viên (CTSV), kể cả khi có từ phụ 'học phí'.
    - Nếu câu hỏi về miễn giảm học phí, hỗ trợ chi phí học tập, trợ cấp xã hội:
      Hiển thị Phòng Công tác Sinh viên (A1.102) là đầu mối tiếp nhận chính kèm ghi chú phối hợp Phòng KHTC.
    - Chỉ định tuyến độc lập về Phòng Kế hoạch - Tài chính (KHTC) khi hỏi về hoàn trả học phí thừa,
      rút tiền học phí, nộp học phí, hóa đơn, biên lai.
    """
    if is_refusal:
        return ""
    departments = load_departments_config()
    q_raw = str(query or "").lower()
    q_slug = _strip_accents(q_raw)

    ctsv_dept = departments.get("ctsv", {
        "name": "Phòng Công tác Sinh viên (VLUTE)",
        "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
        "phone": "(0270) 3862 436",
        "email": "ctsv@vlute.edu.vn"
    })
    pdt_dept = departments.get("dao_tao") or departments.get("daotao") or {
        "name": "Phòng Đào tạo (VLUTE)",
        "location": "Tòa nhà A (Tầng 1)",
        "phone": "(0270) 3822 140",
        "email": "daotao@vlute.edu.vn"
    }
    khtc_dept = departments.get("khtc", {
        "name": "Phòng Kế hoạch - Tài chính (VLUTE)",
        "location": "Tòa nhà A (Tầng trệt)",
        "phone": "(0270) 3822 141",
        "email": "khtc@vlute.edu.vn"
    })

    def _build_hoan_tra_footer() -> str:
        return f"""<div class="contact-footer-card">
  <b style="color: #005a30 !important;">{SVG_PHONE_ICON}Tuyến phối hợp xử lý (CTSV – Đào tạo – KHTC):</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;"><b>1. {ctsv_dept['name']} (Tiếp nhận & tổng hợp đơn):</b> {ctsv_dept['location']} | ĐT: {ctsv_dept['phone']} | Email: {ctsv_dept['email']}</li>
    <li style="color: #334155 !important;"><b>2. {pdt_dept['name']} (Xác nhận học phí thừa):</b> {pdt_dept['location']} | ĐT: {pdt_dept['phone']} | Email: {pdt_dept['email']}</li>
    <li style="color: #334155 !important;"><b>3. {khtc_dept['name']} (Thanh toán hoàn trả):</b> {khtc_dept['location']} | ĐT: {khtc_dept['phone']} | Email: {khtc_dept['email']}</li>
  </ul>
</div>"""

    # 1. Ưu tiên cao nhất: Lấy trực tiếp thông tin phòng ban từ metadata của tài liệu truy xuất hàng đầu (retrieved_docs[0])
    if retrieved_docs and not is_refusal and isinstance(retrieved_docs, (list, tuple)) and len(retrieved_docs) > 0:
        first_item = retrieved_docs[0]
        meta = getattr(first_item, "metadata", None)
        if meta is None and isinstance(first_item, dict):
            meta = first_item
        if isinstance(meta, dict) and meta.get("dept_name"):
            src_file = os.path.basename(str(meta.get("source", "") or meta.get("file", ""))).lower()
            if "hoan_tra_hoc_phi" in src_file:
                return _build_hoan_tra_footer()
            if "mien_giam_hoc_phi" in src_file:
                return _build_contact_footer_html(
                    dept_name="Phòng Công tác Sinh viên (VLUTE) – Đầu mối tiếp nhận hồ sơ (Phối hợp Phòng Kế hoạch - Tài chính)",
                    dept_location=ctsv_dept["location"],
                    dept_phone=ctsv_dept["phone"],
                    dept_email=ctsv_dept["email"]
                )
            return _build_contact_footer_html(
                dept_name=meta.get("dept_name", ctsv_dept["name"]),
                dept_location=meta.get("dept_location", ctsv_dept["location"]),
                dept_phone=meta.get("dept_phone", ctsv_dept["phone"]),
                dept_email=meta.get("dept_email", ctsv_dept["email"])
            )

    # 2. Dự phòng theo từ khóa câu hỏi: Học bổng, khen thưởng, rèn luyện, kỷ luật, CTXH -> Phòng CTSV
    ctsv_priority_keywords = [
        "học bổng", "kkht", "khen thưởng", "rèn luyện", "điểm rèn luyện",
        "kỷ luật", "công tác xã hội", "ctxh", "nội quy", "ứng xử"
    ]
    if any(kw in q_raw for kw in ctsv_priority_keywords):
        return _build_contact_footer_html(
            dept_name=ctsv_dept["name"],
            dept_location=ctsv_dept["location"],
            dept_phone=ctsv_dept["phone"],
            dept_email=ctsv_dept["email"]
        )

    # 3. Miễn giảm học phí / Hỗ trợ chi phí học tập / Trợ cấp xã hội -> Đầu mối chính Phòng CTSV (A1.102) phối hợp Phòng KHTC
    mien_giam_keywords = [
        "miễn giảm học phí", "miễn giảm", "giảm học phí", "miễn học phí",
        "hỗ trợ chi phí học tập", "hỗ trợ chi phí", "trợ cấp xã hội"
    ]
    if any(kw in q_raw for kw in mien_giam_keywords):
        return _build_contact_footer_html(
            dept_name="Phòng Công tác Sinh viên (VLUTE) – Đầu mối tiếp nhận hồ sơ (Phối hợp Phòng Kế hoạch - Tài chính)",
            dept_location=ctsv_dept["location"],
            dept_phone=ctsv_dept["phone"],
            dept_email=ctsv_dept["email"]
        )

    # 4. Hoàn trả học phí thừa (QT-SV-04) -> Tuyến phối hợp CTSV – Đào tạo – KHTC
    hoan_tra_keywords = [
        "hoàn trả học phí", "học phí thừa", "hoàn phí", "hoàn tiền học phí",
        "rút tiền học phí", "nộp thừa", "hoàn trả"
    ]
    if any(kw in q_raw for kw in hoan_tra_keywords):
        return _build_hoan_tra_footer()

    # 4b. Chỉ định tuyến độc lập về Phòng KHTC khi hỏi về nộp học phí, hóa đơn, biên lai
    khtc_exclusive_keywords = [
        "rút tiền", "nộp học phí", "đóng học phí",
        "thu học phí", "hóa đơn", "biên lai"
    ]
    if any(kw in q_raw for kw in khtc_exclusive_keywords):
        return _build_contact_footer_html(
            dept_name=khtc_dept["name"],
            dept_location=khtc_dept["location"],
            dept_phone=khtc_dept["phone"],
            dept_email=khtc_dept["email"]
        )

    # 5. Quét các phòng ban còn lại (Đào tạo, CNTT...) trong departments.json
    for dept_key, dept_info in departments.items():
        if dept_key == "khtc":
            # Đã xử lý độc lập ở mục 3, tránh khớp nhầm từ khóa chung "hoc_phi"
            continue
        patterns = dept_info.get("patterns", [])
        for pat in patterns:
            pat_str = str(pat).lower().strip()
            if not pat_str:
                continue
            if pat_str == "mang":
                if "mạng" in q_raw or "an_ninh_mang" in q_slug or "mang_internet" in q_slug or "mang_wifi" in q_slug:
                    return _build_contact_footer_html(
                        dept_name=dept_info["name"],
                        dept_location=dept_info["location"],
                        dept_phone=dept_info["phone"],
                        dept_email=dept_info["email"]
                    )
            elif pat_str in q_slug or pat_str.replace("_", " ") in q_raw:
                return _build_contact_footer_html(
                    dept_name=dept_info["name"],
                    dept_location=dept_info["location"],
                    dept_phone=dept_info["phone"],
                    dept_email=dept_info["email"]
                )

    return _build_contact_footer_html(
        dept_name=ctsv_dept["name"],
        dept_location=ctsv_dept["location"],
        dept_phone=ctsv_dept["phone"],
        dept_email=ctsv_dept["email"]
    )

def check_department_inquiry(query: str):
    q = (query or "").lower()
    regulation_keywords = [
        "hồ sơ", "thủ tục", "điều kiện", "miễn giảm", "miễn, giảm", "học bổng",
        "quy trình", "quy định", "mức", "nộp ở đâu", "nộp đơn", "nộp hồ sơ",
        "hoàn trả", "hỗ trợ chi phí", "công tác xã hội", "ctxh", "tín chỉ",
        "kỷ luật", "rèn luyện", "xét tốt nghiệp", "chuẩn bị", "giấy tờ",
        "cấp phát", "sử dụng", "tên miền", "đổi mật khẩu", "mật khẩu",
        "khóa tài khoản", "tài khoản", "trách nhiệm", "nghĩa vụ", "báo cáo",
        "xử lý", "sự cố", "quyền", "trường hợp", "thời hạn", "bao lâu",
        "như thế nào", "thế nào", "ra sao", "cần làm gì", "bị cấm", "nghiêm cấm",
        "khen thưởng", "chủ trì", "lập danh sách", "phê duyệt", "bản chính",
        "bản photo", "lưu tại", "lưu trữ", "rút tiền", "đóng dư",
    ]
    if any(rw in q for rw in regulation_keywords):
        return None
    ask_contact_keywords = [
        "địa chỉ", "ở đâu", "vị trí", "nằm ở", "tòa nào", "phòng mấy",
        "liên hệ", "gặp ai", "số điện thoại", "sđt", "hotline",
        "địa chỉ email", "email của", "email liên hệ", "email phòng", "email trung tâm",
        "liên hệ phòng nào", "liên hệ đơn vị nào", "liên hệ bộ phận nào",
        "hỏi phòng nào", "tới phòng nào", "đến phòng nào", "qua phòng nào",
        "phòng nào hỗ trợ", "đơn vị nào hỗ trợ", "bộ phận nào hỗ trợ",
    ]
    if any(kw in q for kw in ask_contact_keywords):
        departments = load_departments_config()
        pdt = departments.get("daotao") or departments.get("dao_tao") or {
            "name": "Phòng Đào tạo (VLUTE)",
            "location": "Tòa nhà A (Tầng 1)",
            "phone": "(0270) 3822 140",
            "email": "daotao@vlute.edu.vn"
        }
        ctsv = departments.get("ctsv", {
            "name": "Phòng Công tác Sinh viên (VLUTE)",
            "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
            "phone": "(0270) 3862 436",
            "email": "ctsv@vlute.edu.vn"
        })
        khtc = departments.get("khtc", {
            "name": "Phòng Kế hoạch - Tài chính (VLUTE)",
            "location": "Tòa nhà A (Tầng trệt)",
            "phone": "(0270) 3822 141",
            "email": "khtc@vlute.edu.vn"
        })
        cntt = departments.get("cntt", {
            "name": "Trung tâm Công nghệ Thông tin (VLUTE)",
            "location": "Tòa nhà B",
            "phone": "(0270) 3862 250",
            "email": "ttcntt@vlute.edu.vn"
        })

        has_pdt = any(k in q for k in ["đào tạo", "đảm bảo chất lượng", "pdt", "học vụ"])
        has_ctsv = any(k in q for k in ["công tác sinh viên", "truyền thông", "ctsv"])
        has_khtc = any(k in q for k in ["tài chính", "kế hoạch", "khtc", "học phí"])
        has_cntt = any(k in q for k in ["cntt", "công nghệ thông tin", "tin học", "mật khẩu", "wifi", "internet", "mạng", "e-learning"])
        has_all = "các phòng ban" in q or (int(has_pdt) + int(has_ctsv) + int(has_khtc) + int(has_cntt) >= 2)

        if has_all:
            return (
                "Thông tin liên hệ các phòng ban hỗ trợ sinh viên tại **VLUTE** như sau:\n\n"
                f"• **{pdt['name']}:** {pdt['location']} | ĐT: {pdt['phone']} | Email: {pdt['email']}\n"
                f"• **{ctsv['name']}:** {ctsv['location']} | ĐT: {ctsv['phone']} | Email: {ctsv['email']}\n"
                f"• **{khtc['name']}:** {khtc['location']} | ĐT: {khtc['phone']} | Email: {khtc['email']}\n"
                f"• **{cntt['name']}:** {cntt['location']} | ĐT: {cntt['phone']} | Email: {cntt['email']}"
            )

        # 1. Trung tâm Công nghệ Thông tin (ưu tiên khi hỏi quên mật khẩu E-Learning / email)
        if has_cntt:
            return (
                f"Thông tin liên hệ của **{cntt['name']}** như sau:\n\n"
                f"• **Vị trí phòng làm việc:** {cntt['location']}\n"
                f"• **Số điện thoại:** {cntt['phone']}\n"
                f"• **Email tiếp nhận:** {cntt['email']}\n\n"
                f"Bạn có thể liên hệ để được hỗ trợ cấp lại mật khẩu cổng thông tin, tài khoản E-Learning, email sinh viên và sự cố kết nối mạng."
            )

        # 2. Phòng Đào tạo
        if has_pdt:
            return (
                f"Thông tin liên hệ của **{pdt['name']}** như sau:\n\n"
                f"• **Vị trí phòng làm việc:** {pdt['location']}\n"
                f"• **Số điện thoại:** {pdt['phone']}\n"
                f"• **Email tiếp nhận:** {pdt['email']}\n\n"
                f"Bạn có thể liên hệ trực tiếp trong giờ hành chính để được hướng dẫn giải quyết các thủ tục đào tạo, đăng ký môn học và học vụ."
            )

        # 3. Phòng Công tác Sinh viên
        if has_ctsv:
            return (
                f"Thông tin liên hệ của **{ctsv['name']}** như sau:\n\n"
                f"• **Vị trí phòng làm việc:** {ctsv['location']}\n"
                f"• **Số điện thoại:** {ctsv['phone']}\n"
                f"• **Email tiếp nhận:** {ctsv['email']}\n\n"
                f"Bạn có thể liên hệ trực tiếp để được hỗ trợ về học bổng, chính sách miễn giảm học phí, rèn luyện và các thủ tục sinh viên."
            )

        # 4. Phòng Kế hoạch - Tài chính
        if has_khtc:
            return (
                f"Thông tin liên hệ của **{khtc['name']}** như sau:\n\n"
                f"• **Vị trí phòng làm việc:** {khtc['location']}\n"
                f"• **Số điện thoại:** {khtc['phone']}\n"
                f"• **Email tiếp nhận:** {khtc['email']}\n\n"
                f"Bạn có thể liên hệ để giải quyết các vấn đề nộp học phí, hoàn trả học phí thừa hoặc thủ tục hóa đơn, biên lai."
            )
    return None


_FOLLOWUP_Q_STOPWORDS = frozenset({
    "ai", "nao", "nhung", "cac", "cua", "va", "hoac", "duoc", "la", "gi",
    "the", "ra", "sao", "bao", "nhieu", "theo", "hien", "hanh", "nhu", "co",
    "bi", "xin", "cho", "tai", "voi", "trong", "ve", "de", "den", "hay",
    "thi", "ma", "sinh", "vien", "nha", "truong", "quy", "dinh", "xem",
    "xet", "thuoc", "dien", "dieu", "o", "dau",
})


def _content_tokens(text: str) -> set[str]:
    """Trích tập từ khóa nội dung đã bỏ dấu và loại bỏ từ dừng câu hỏi chung."""
    return {t for t in _strip_accents(text).split("_") if t and t not in _FOLLOWUP_Q_STOPWORDS}


def _build_chronological_asked_turns(
    messages: list | None,
    query_or_content: str = "",
    asked_queries: list | set | None = None,
) -> list[dict]:
    """Tạo danh sách các lượt hỏi theo thứ tự thời gian từ cũ đến mới để phục vụ chống lặp & LRU recycling."""
    turns = []
    msg_list = messages or []
    idx = 0
    while idx < len(msg_list):
        msg = msg_list[idx]
        if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content"):
            texts = [str(msg.get("content", ""))]
            if idx + 1 < len(msg_list) and isinstance(msg_list[idx + 1], dict):
                nxt = msg_list[idx + 1]
                if nxt.get("role") == "assistant" and nxt.get("query"):
                    texts.append(str(nxt.get("query", "")))
            turns.append(texts)
        idx += 1

    # Gộp/bổ sung asked_queries truyền ngoài (nếu chưa trùng lượt nào hiện có)
    seen_all_norms = {_strip_accents(t) for grp in turns for t in grp if _strip_accents(t)}
    for extra in (asked_queries or []):
        en = _strip_accents(str(extra or ""))
        if en and en not in seen_all_norms:
            turns.append([str(extra)])
            seen_all_norms.add(en)

    # Đảm bảo câu hỏi hiện tại nằm ở lượt mới nhất
    cur_norm = _strip_accents(query_or_content)
    if cur_norm:
        if turns:
            last_norms = {_strip_accents(t) for t in turns[-1] if _strip_accents(t)}
            if cur_norm not in last_norms:
                turns[-1].append(query_or_content)
        else:
            turns.append([query_or_content])

    compiled = []
    for grp in turns:
        norms = {_strip_accents(t) for t in grp if _strip_accents(t)}
        token_sets = [_content_tokens(t) for t in grp if len(_content_tokens(t)) >= 3]
        if norms:
            compiled.append({"norms": norms, "token_sets": token_sets})
    return compiled


def _last_asked_turn_index(cand_q: str, cand_lbl: str, compiled_turns: list[dict]) -> int:
    """Trả về chỉ số lượt gần nhất đã hỏi câu ứng viên (cũ -> mới), hoặc -1 nếu chưa từng hỏi."""
    cq_norm = _strip_accents(cand_q)
    if not cq_norm:
        return -1
    cq_tokens = _content_tokens(cand_q)
    cl_tokens = _content_tokens(cand_lbl)

    for t_idx in range(len(compiled_turns) - 1, -1, -1):
        turn = compiled_turns[t_idx]
        t_norms = turn["norms"]
        if cq_norm in t_norms:
            return t_idx
        if any(min(len(cq_norm), len(an)) >= 18 and (cq_norm in an or an in cq_norm) for an in t_norms):
            return t_idx
        for atoks in turn["token_sets"]:
            if len(cq_tokens) >= 3:
                inter_q = len(cq_tokens & atoks)
                if (inter_q / min(len(cq_tokens), len(atoks))) >= 0.80 and (inter_q / max(len(cq_tokens), len(atoks))) >= 0.45:
                    return t_idx
            if len(cl_tokens) >= 3:
                inter_l = len(cl_tokens & atoks)
                if (inter_l / min(len(cl_tokens), len(atoks))) >= 0.85 and (inter_l / len(cl_tokens)) >= 0.60:
                    return t_idx
    return -1


def _select_followup_prompts(
    query_or_content: str,
    config: dict,
    messages: list | None = None,
    sources: list | None = None,
    assistant_reply: str = "",
    asked_queries: list | set | None = None,
    limit: int = 2,
) -> list[tuple[str, str]]:
    """Chọn 2 nút gợi ý theo 3 tầng: (1) chưa hỏi cùng nhóm, (2) chưa hỏi nhóm khác, (3) LRU Recycling câu cũ nhất."""
    q_text = (query_or_content or "").lower()
    reply_text = (assistant_reply or "").lower()

    doc_title = ""
    doc_snippet = ""
    doc_dept_key = ""
    if sources and isinstance(sources, list) and len(sources) > 0:
        src0 = sources[0]
        if isinstance(src0, dict):
            doc_title = str(src0.get("title") or src0.get("short_title") or "").lower()
            doc_snippet = str(src0.get("snippet") or "")[:400].lower()
            doc_dept_key = str(src0.get("dept_key") or "").lower().strip()
        else:
            meta = getattr(src0, "metadata", {}) or {}
            doc_title = str(meta.get("title") or "").lower()
            doc_snippet = str(getattr(src0, "page_content", "") or "")[:400].lower()
            doc_dept_key = str(meta.get("dept_key") or "").lower().strip()

    categories = config.get("categories", {})

    best_cat_key = None
    best_score = 0
    # Chấm điểm độ khớp từ khóa trên ngữ cảnh tổng hợp (ưu tiên trọng số cao cho title và query_or_content)
    for cat_key, cat_data in categories.items():
        kws = [str(kw).lower() for kw in cat_data.get("keywords", []) if kw]
        score = 0
        for kw in kws:
            if doc_title and kw in doc_title:
                score += 4
            if q_text and kw in q_text:
                score += 3
            if reply_text and kw in reply_text:
                score += 2
            if doc_snippet and kw in doc_snippet:
                score += 1
        if score > best_score:
            best_score = score
            best_cat_key = cat_key

    # Lớp dự phòng tổng quát theo dept_key tự động của sources[0] nếu chưa khớp rõ từ khóa
    if not best_cat_key and doc_dept_key:
        dept_to_category = {
            "dao_tao": "hoc_vu_tot_nghiep",
            "cntt": "hoc_vu_tot_nghiep",
            "khtc": "hoc_phi",
            "ctsv": "ctxh_ren_luyen",
        }
        mapped_cat = dept_to_category.get(doc_dept_key)
        if mapped_cat in categories:
            best_cat_key = mapped_cat

    if best_cat_key and best_cat_key in categories:
        primary_raw = [(p["label"], p["query"]) for p in categories[best_cat_key].get("prompts", [])]
    else:
        primary_raw = [(p["label"], p["query"]) for p in config.get("initial_prompts", [])]

    secondary_raw = []
    for ckey, cdata in categories.items():
        if ckey != best_cat_key:
            secondary_raw.extend((p["label"], p["query"]) for p in cdata.get("prompts", []))
    secondary_raw.extend((p["label"], p["query"]) for p in config.get("initial_prompts", []))

    compiled_turns = _build_chronological_asked_turns(messages, query_or_content, asked_queries)

    # Chuẩn hóa kho ứng viên không trùng lặp nội bộ (cat_priority: 0=cùng nhóm, 1=nhóm khác)
    all_candidates = []
    catalog_norms = set()
    for cat_prio, pool in ((0, primary_raw), (1, secondary_raw)):
        for order_idx, (lbl, q) in enumerate(pool):
            qn = _strip_accents(q)
            if qn and qn not in catalog_norms:
                catalog_norms.add(qn)
                last_idx = _last_asked_turn_index(q, lbl, compiled_turns)
                all_candidates.append((last_idx, cat_prio, order_idx, lbl, q, qn))

    prompts_to_show = []
    selected_norms = set()

    def _add_candidate(lbl: str, q: str, qn: str):
        prompts_to_show.append((lbl, q))
        selected_norms.add(qn)

    # Tầng 1 & Tầng 2: Ưu tiên các câu chưa từng hỏi (cùng nhóm trước, nhóm khác sau)
    for target_prio in (0, 1):
        for last_idx, cat_prio, _order_idx, lbl, q, qn in all_candidates:
            if cat_prio == target_prio and last_idx == -1 and qn not in selected_norms:
                _add_candidate(lbl, q, qn)
                if len(prompts_to_show) >= limit:
                    return prompts_to_show

    # Tầng 3 (LRU Recycling): Đã hỏi hết toàn kho -> lấy lại câu hỏi từ lâu nhất ở đầu phiên (trừ 4 câu gần nhất)
    total_turns = len(compiled_turns)
    recent_cutoff = max(0, total_turns - 4)
    remaining = [item for item in all_candidates if item[5] not in selected_norms]

    # 3a. Ứng viên hỏi trước recent_cutoff (ngoài 4 câu vừa hỏi gần nhất), xếp từ cũ nhất đến mới hơn
    lru_eligible = sorted(
        (item for item in remaining if 0 <= item[0] < recent_cutoff),
        key=lambda x: (x[0], x[1], x[2]),
    )
    for _last_idx, _cat_prio, _order_idx, lbl, q, qn in lru_eligible:
        _add_candidate(lbl, q, qn)
        if len(prompts_to_show) >= limit:
            return prompts_to_show

    # 3b. Dự phòng an toàn nếu phiên có <= 4 lượt mà vẫn chưa đủ 2 nút: tránh lượt mới nhất rồi mới tới toàn bộ còn lại
    fallback_sorted = sorted(
        remaining,
        key=lambda x: (1 if x[0] >= max(0, total_turns - 1) else 0, x[0], x[1], x[2]),
    )
    for _last_idx, _cat_prio, _order_idx, lbl, q, qn in fallback_sorted:
        _add_candidate(lbl, q, qn)
        if len(prompts_to_show) >= limit:
            break

    return prompts_to_show


def _preselect_followups(
    query_or_content: str,
    sources: list | None = None,
    assistant_reply: str = "",
) -> list[tuple[str, str]]:
    """Tính trước 2 câu hỏi gợi ý trước khi render thẻ liên hệ cuối cùng để triệt tiêu độ trễ hiển thị."""
    return _select_followup_prompts(
        query_or_content=query_or_content,
        config=load_prompts_config(),
        messages=st.session_state.get("messages", []),
        sources=sources,
        assistant_reply=assistant_reply,
        limit=2,
    )


def render_followup_suggestions(
    query_or_content: str,
    key_suffix: str = "",
    sources: list | None = None,
    assistant_reply: str = "",
    asked_queries: list | set | None = None,
    preselected_prompts: list[tuple[str, str]] | None = None,
):
    """Hiển thị luôn đủ 2 nút gợi ý liên quan theo cơ chế xoay vòng 3 tầng (cùng nhóm -> nhóm khác -> LRU Recycling)."""
    prompts_to_show = preselected_prompts if preselected_prompts is not None else _select_followup_prompts(
        query_or_content=query_or_content,
        config=load_prompts_config(),
        messages=st.session_state.get("messages", []),
        sources=sources,
        assistant_reply=assistant_reply,
        asked_queries=asked_queries,
        limit=2,
    )

    if not prompts_to_show:
        return

    st.markdown(f"<p class='vlute-followup-title' style='font-size: 0.88rem; color: #00703c !important; margin-top: 10px; margin-bottom: 6px; display: flex; align-items: center; gap: 4px;'>{SVG_LIGHTBULB_ICON}<b style='color: #00703c !important;'>Gợi ý câu hỏi liên quan bạn có thể quan tâm:</b></p>", unsafe_allow_html=True)
    cols = st.columns(len(prompts_to_show))
    for idx, (label, target_q) in enumerate(prompts_to_show):
        with cols[idx]:
            st.button(
                label,
                key=f"followup_{key_suffix}_{idx}",
                use_container_width=True,
                on_click=submit_user_query,
                args=(target_q,)
            )

# ==========================================
# 5. KHUNG NHẬP CÂU HỎI
# ==========================================
user_input_from_chat = st.chat_input("Hỏi về quy chế đào tạo, học bổng, học phí, học vụ VLUTE...")

user_query = None
if user_input_from_chat:
    user_query = user_input_from_chat
elif st.session_state.get("pending_user_query"):
    user_query = st.session_state.pending_user_query
    st.session_state.pending_user_query = None

if user_query:
    current_user_query = user_query.strip()
    filtered_history = []
    for m in st.session_state.messages[1:]:
        role = m.get("role")
        content = str(m.get("content", "") or "")
        if role == "user":
            filtered_history.append({"role": "user", "content": content})
        elif role == "assistant":
            is_excluded = (
                bool(m.get("is_greeting", False))
                or bool(m.get("is_refusal", False))
                or (REFUSAL_MESSAGE in content)
                or (RATE_LIMIT_MESSAGE in content)
                or is_refusal_answer(content)
            )
            if is_excluded:
                if filtered_history and filtered_history[-1].get("role") == "user":
                    filtered_history.pop()
                continue
            filtered_history.append({"role": "assistant", "content": content})
    recent_chat_history = filtered_history[-6:]
    if current_user_query and not (
        st.session_state.messages
        and st.session_state.messages[-1].get("role") == "user"
        and st.session_state.messages[-1].get("content") == current_user_query
    ):
        st.session_state.messages.append({"role": "user", "content": current_user_query})
else:
    current_user_query = ""
    recent_chat_history = []

# ==========================================
# HIỂN THỊ LỊCH SỬ TIN NHẮN (OPTIMISTIC RENDER TỨC THÌ < 0.3S)
# ==========================================
last_user_idx = max(
    (i for i, m in enumerate(st.session_state.messages) if m.get("role") == "user"),
    default=-1
)
last_assistant_idx = max(
    (i for i, m in enumerate(st.session_state.messages) if m.get("role") == "assistant"),
    default=-1
)

for idx, message in enumerate(st.session_state.messages):
    if message["role"] == "user":
        safe_content = html.escape(message["content"]).replace("\n", "<br>")
        row_cls = "chat-row-user chat-history-old" if idx < last_user_idx else "chat-row-user"
        st.markdown(
            f'<div class="{row_cls}"><div class="user-bubble">{safe_content}</div></div>',
            unsafe_allow_html=True
        )
    else:
        with st.chat_message("assistant", avatar=BOT_AVATAR):
            msg_content = str(message.get("content", "") or "").strip()
            is_welcome_or_greeting = (idx == 0) or bool(message.get("is_greeting", False))
            is_dept_inquiry = bool(message.get("is_dept_inquiry", False))
            msg_is_refusal = bool(message.get("is_refusal", is_refusal_answer(msg_content))) or is_refusal_answer(msg_content)
            old_marker_suffix = '\n\n<span class="chat-history-old-marker" style="display:none;"></span>' if (bool(current_user_query) or idx < last_assistant_idx) else ""

            q_text = message.get("query") or (st.session_state.messages[idx - 1].get("content") if idx > 0 else "")
            if is_welcome_or_greeting or is_dept_inquiry:
                st.markdown(build_assistant_bubble_html(msg_content, is_welcome_or_greeting=True) + old_marker_suffix, unsafe_allow_html=True)
            elif not msg_is_refusal:
                contact_html = message.get("contact") or get_contact_footer(q_text or "", retrieved_docs=message.get("sources"), is_refusal=False)
                st.markdown(
                    build_assistant_bubble_html(msg_content, contact_html=contact_html, elapsed_time=message.get("elapsed_time"), is_refusal=False) + old_marker_suffix,
                    unsafe_allow_html=True
                )
            else:
                contact_html = ""
                st.markdown(
                    build_assistant_bubble_html(msg_content or REFUSAL_MESSAGE, contact_html=contact_html, is_refusal=True) + old_marker_suffix,
                    unsafe_allow_html=True
                )

            if idx > 0 and idx == last_assistant_idx and not current_user_query:
                render_followup_suggestions(
                    q_text or msg_content,
                    key_suffix=str(idx),
                    sources=message.get("sources"),
                    assistant_reply=msg_content,
                )

# ==========================================
# KHỐI 4 CÂU HỎI GỢI Ý NGẪU NHIÊN (LƯỚI 2x2 KHI CHƯA BẮT ĐẦU HỎI)
# ==========================================
if len(st.session_state.messages) <= 1 and not current_user_query:
    if "welcome_shuffle_count" not in st.session_state:
        st.session_state.welcome_shuffle_count = 0
    if "welcome_prompts" not in st.session_state or not st.session_state.welcome_prompts:
        st.session_state.welcome_prompts = get_random_welcome_prompts()

    hdr_col1, hdr_col2 = st.columns([3, 1])
    with hdr_col1:
        st.markdown(
            f'<div class="quick-prompt-title" style="margin-bottom: 6px; padding-top: 6px;">{SVG_LIGHTBULB_ICON}Gợi ý câu hỏi nhanh dành cho bạn:</div>',
            unsafe_allow_html=True,
        )
    with hdr_col2:
        st.button(
            "↻ Đổi 4 gợi ý khác",
            key="shuffle_welcome_btn",
            use_container_width=True,
            on_click=shuffle_welcome_prompts,
        )

    welcome_items = st.session_state.welcome_prompts[:4]
    col1, col2 = st.columns(2)
    for i, item in enumerate(welcome_items):
        target_col = col1 if i % 2 == 0 else col2
        with target_col:
            st.button(
                item["label"],
                key=f"welcome_prompt_{i}",
                use_container_width=True,
                on_click=submit_user_query,
                args=(item["query"],)
            )

if current_user_query:
    new_msg_idx = len(st.session_state.messages)

    # Mở ngay bong bóng Lucas kèm Typing Dots TRƯỚC KHI rewrite/RAG để đạt Optimistic UI < 0.3s
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        status_placeholder = st.empty()
        status_placeholder.markdown(THINKING_HTML, unsafe_allow_html=True)

        if not re.search(r"[0-9a-zA-ZÀ-ỹ]", current_user_query):
            clarify_reply = "Bạn vui lòng nhập nội dung câu hỏi cụ thể về quy chế hoặc chọn một gợi ý bên dưới để Lucas hỗ trợ nhé!"
            pre_followups = _preselect_followups(current_user_query, sources=[], assistant_reply=clarify_reply)
            status_placeholder.markdown(
                build_assistant_bubble_html(clarify_reply, is_welcome_or_greeting=True),
                unsafe_allow_html=True
            )
            st.session_state.messages.append({
                "role": "assistant",
                "content": clarify_reply,
                "contact": "",
                "sources": [],
                "query": current_user_query,
                "is_refusal": True,
                "is_greeting": True,
                "elapsed_time": None
            })
            render_followup_suggestions(current_user_query, key_suffix=str(new_msg_idx), sources=[], assistant_reply=clarify_reply, preselected_prompts=pre_followups)
        elif check_social_or_command_reply(current_user_query) or is_greeting(current_user_query):
            social_reply = check_social_or_command_reply(current_user_query)
            if social_reply:
                greeting_reply = social_reply
            else:
                greeting_idx = int(st.session_state.get("greeting_turn_count", 0)) % len(GREETING_REPLIES)
                greeting_reply = GREETING_REPLIES[greeting_idx]
                st.session_state.greeting_turn_count = greeting_idx + 1
            pre_followups = _preselect_followups(current_user_query, sources=[], assistant_reply=greeting_reply)
            status_placeholder.markdown(
                build_assistant_bubble_html(greeting_reply, is_welcome_or_greeting=True),
                unsafe_allow_html=True
            )
            st.session_state.messages.append({
                "role": "assistant",
                "content": greeting_reply,
                "contact": "",
                "sources": [],
                "query": current_user_query,
                "is_refusal": True,
                "is_greeting": True,
                "elapsed_time": None
            })
            render_followup_suggestions(current_user_query, key_suffix=str(new_msg_idx), sources=[], assistant_reply=greeting_reply, preselected_prompts=pre_followups)
        else:
            canonical_query = normalize_query_intent(current_user_query)
            ensure_kb_synced_and_fresh_cache()
            answer_cache = get_answer_cache()
            canonical_cache_key = _strip_accents(canonical_query)
            canonical_cached = answer_cache.get(canonical_cache_key) if canonical_cache_key else None
            if canonical_cached and (time.time() - float(canonical_cached.get("timestamp", 0))) > ANSWER_CACHE_TTL:
                answer_cache.pop(canonical_cache_key, None)
                canonical_cached = None

            if canonical_cached and canonical_cached.get("answer"):
                rewritten_query = canonical_query
            else:
                rewritten_query = rewrite_conversational_query(canonical_query, recent_chat_history)
            dept_reply = check_department_inquiry(rewritten_query) if "check_department_inquiry" in globals() else None

            if dept_reply:
                pre_followups = _preselect_followups(rewritten_query, sources=[], assistant_reply=dept_reply)
                status_placeholder.markdown(
                    build_assistant_bubble_html(dept_reply, is_welcome_or_greeting=True),
                    unsafe_allow_html=True
                )
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": dept_reply,
                    "contact": "",
                    "sources": [],
                    "query": rewritten_query,
                    "is_refusal": False,
                    "is_greeting": False,
                    "is_dept_inquiry": True,
                    "elapsed_time": None
                })
                render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=[], assistant_reply=dept_reply, preselected_prompts=pre_followups)

            # 5. Tra cứu RAG nếu là câu hỏi quy chế (kiểm tra Answer Cache tự làm mới theo data/ trước khi gọi LLM)
            else:
                try:
                    cache_key = _strip_accents(rewritten_query)
                    cached_entry = answer_cache.get(cache_key) if cache_key else None
                    if cached_entry and (time.time() - float(cached_entry.get("timestamp", 0))) > ANSWER_CACHE_TTL:
                        answer_cache.pop(cache_key, None)
                        cached_entry = None

                    if cached_entry and cached_entry.get("answer") and is_refusal_answer(cached_entry.get("answer")):
                        answer_cache.pop(cache_key, None)
                        cached_entry = None

                    if cached_entry and cached_entry.get("answer"):
                        cached_answer = cached_entry["answer"]
                        cached_contact = cached_entry.get("contact") or get_contact_footer(rewritten_query, retrieved_docs=None, is_refusal=False)
                        cached_sources = cached_entry.get("sources") or []
                        cached_elapsed = 0.05
                        pre_followups = _preselect_followups(rewritten_query, sources=cached_sources, assistant_reply=cached_answer)
                        status_placeholder.markdown(
                            build_assistant_bubble_html(cached_answer, contact_html=cached_contact, elapsed_time=cached_elapsed, is_refusal=False),
                            unsafe_allow_html=True
                        )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": cached_answer,
                            "contact": cached_contact,
                            "sources": cached_sources,
                            "query": rewritten_query,
                            "is_refusal": False,
                            "is_greeting": False,
                            "elapsed_time": cached_elapsed
                        })
                        print(f"[ANSWER CACHE HIT] key='{cache_key}' (0.05s)")
                        render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=cached_sources, assistant_reply=cached_answer, preselected_prompts=pre_followups)
                    else:
                        start_time = time.time()
                        stream_gen, sources_to_save, num_docs, retrieved_docs = stream_rag_pipeline(rewritten_query)

                        if not num_docs or not stream_gen:
                            no_doc_msg = REFUSAL_MESSAGE
                            contact_footer = ""
                            pre_followups = _preselect_followups(rewritten_query, sources=[], assistant_reply=no_doc_msg)
                            status_placeholder.markdown(
                                build_assistant_bubble_html(no_doc_msg, contact_html=contact_footer, is_refusal=True),
                                unsafe_allow_html=True
                            )
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": no_doc_msg,
                                "contact": contact_footer,
                                "sources": [],
                                "query": rewritten_query,
                                "is_refusal": True,
                                "is_greeting": False,
                                "elapsed_time": None
                            })
                            render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=[], assistant_reply=no_doc_msg, preselected_prompts=pre_followups)
                        else:
                            badge_html = get_verify_badge_html()
                            streamed_chunks = []
                            last_update = time.time()
                            first_chunk_rendered = False

                            for chunk in stream_gen:
                                chunk_str = str(chunk)
                                if not chunk_str:
                                    continue
                                streamed_chunks.append(chunk_str)
                                if (not first_chunk_rendered) or (time.time() - last_update > 0.065):
                                    current_text = _escape_unsafe_lt("".join(streamed_chunks))
                                    status_placeholder.markdown(f"{badge_html}\n\n{current_text}", unsafe_allow_html=True)
                                    last_update = time.time()
                                    first_chunk_rendered = True

                            full_answer = "".join(streamed_chunks).strip()
                            elapsed_time = round(time.time() - start_time, 2)
                            is_interrupted = "phản hồi bị gián đoạn giữa chừng" in full_answer.lower()

                            if is_interrupted:
                                contact_footer = ""
                                pre_followups = _preselect_followups(rewritten_query, sources=sources_to_save, assistant_reply=full_answer)
                                status_placeholder.markdown(
                                    build_assistant_bubble_html(full_answer, contact_html=contact_footer, is_refusal=True),
                                    unsafe_allow_html=True
                                )
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": full_answer,
                                    "contact": contact_footer,
                                    "sources": [],
                                    "query": rewritten_query,
                                    "is_refusal": True,
                                    "is_greeting": False,
                                    "elapsed_time": None
                                })
                                render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=sources_to_save, assistant_reply=full_answer, preselected_prompts=pre_followups)
                            elif is_refusal_answer(full_answer) or not full_answer:
                                full_answer = full_answer or REFUSAL_MESSAGE
                                contact_footer = ""
                                pre_followups = _preselect_followups(rewritten_query, sources=[], assistant_reply=full_answer)
                                status_placeholder.markdown(
                                    build_assistant_bubble_html(full_answer, contact_html=contact_footer, is_refusal=True),
                                    unsafe_allow_html=True
                                )
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": full_answer,
                                    "contact": contact_footer,
                                    "sources": [],
                                    "query": rewritten_query,
                                    "is_refusal": True,
                                    "is_greeting": False,
                                    "elapsed_time": None
                                })
                                render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=[], assistant_reply=full_answer, preselected_prompts=pre_followups)
                            else:
                                contact_footer = get_contact_footer(rewritten_query, retrieved_docs=retrieved_docs, is_refusal=False)
                                pre_followups = _preselect_followups(rewritten_query, sources=sources_to_save, assistant_reply=full_answer)
                                status_placeholder.markdown(
                                    build_assistant_bubble_html(full_answer, contact_html=contact_footer, elapsed_time=elapsed_time, is_refusal=False),
                                    unsafe_allow_html=True
                                )
                                if cache_key:
                                    cache_record = {
                                        "answer": full_answer,
                                        "contact": contact_footer,
                                        "sources": sources_to_save,
                                        "timestamp": time.time(),
                                    }
                                    answer_cache[cache_key] = cache_record
                                    if rewritten_query == canonical_query and canonical_cache_key and canonical_cache_key != cache_key:
                                        answer_cache[canonical_cache_key] = cache_record
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": full_answer,
                                    "contact": contact_footer,
                                    "sources": sources_to_save,
                                    "query": rewritten_query,
                                    "is_refusal": False,
                                    "is_greeting": False,
                                    "elapsed_time": elapsed_time
                                })
                                render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=sources_to_save, assistant_reply=full_answer, preselected_prompts=pre_followups)

                except Exception as e:
                    status_placeholder.empty()
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
                        contact_footer = ""
                        pre_followups = _preselect_followups(rewritten_query, sources=[], assistant_reply=RATE_LIMIT_MESSAGE)
                        status_placeholder.markdown(
                            build_assistant_bubble_html(RATE_LIMIT_MESSAGE, contact_html=contact_footer, is_refusal=True),
                            unsafe_allow_html=True
                        )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": RATE_LIMIT_MESSAGE,
                            "contact": contact_footer,
                            "sources": [],
                            "query": rewritten_query,
                            "is_refusal": True,
                            "is_greeting": False,
                            "elapsed_time": None
                        })
                        render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx), sources=[], assistant_reply=RATE_LIMIT_MESSAGE, preselected_prompts=pre_followups)
                    else:
                        import traceback
                        traceback.print_exc()
                        status_placeholder.error(f"Lỗi: {e}")

with st.sidebar:
    if LOGO_B64:
        st.markdown(f"""
        <div style="display: flex; justify-content: center; align-items: center; width: 100%; padding-top: 14px; margin-bottom: 8px; margin-top: 6px;">
            <img src="data:image/png;base64,{LOGO_B64}" width="95" height="95" style="width: 95px; height: 95px; max-width: 95px; max-height: 95px; object-fit: contain; display: block; filter: drop-shadow(0 3px 8px rgba(0,0,0,0.4));" alt="Logo VLUTE" />
        </div>
        <div style="text-align: center; color: #ffffff; font-weight: 800; font-size: 0.92rem; letter-spacing: 0.3px; margin-bottom: 4px; line-height: 1.35;">
            TRƯỜNG ĐẠI HỌC<br><span style="white-space: nowrap; color: #ffffff;">CNKT VĨNH LONG</span>
        </div>
        <div style="text-align: center; color: #00a65a; font-weight: 700; font-size: 0.76rem; letter-spacing: 0.6px; text-transform: uppercase; margin-bottom: 10px;">
            QUẢN LÝ ĐÀO TẠO & HỌC VỤ
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div style="display: flex; align-items: center; justify-content: center; gap: 5px; text-align: center; color: #cbd5e1; font-size: 0.75rem; margin-bottom: 10px; padding: 6px 8px; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; line-height: 1.4; word-break: keep-all;">
        {SVG_PIN_ICON} <span>Số 73 Nguyễn Huệ, Phường Long Châu, Tỉnh Vĩnh Long</span>
    </div>
    """, unsafe_allow_html=True)

    st.button(
        "Làm mới cuộc trò chuyện",
        use_container_width=True,
        on_click=reset_chat_history,
    )
    
    # 2 nhóm liên kết hệ thống rõ rệt (chuỗi không thụt lề để triệt tiêu lỗi code thô)
    SIDEBAR_NAV_HTML = (
        '<div class="sidebar-links-card">'
        f'<div class="sidebar-section-title">{SVG_LINK_ICON}<span>HỆ THỐNG HỌC TẬP</span></div>'
        '<div class="sidebar-link-grid">'
        f'<a href="https://vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Cổng thông tin My VLUTE">{SVG_GLOBE_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">My VLUTE</span></a>'
        f'<a href="https://daotao.vlute.edu.vn/sinh-vien" target="_blank" class="sidebar-link-item" title="Đăng ký học phần">{SVG_FILE_EDIT_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">ĐK Học phần</span></a>'
        f'<a href="http://elearning.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Học trực tuyến E-Learning">{SVG_MONITOR_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">E-Learning</span></a>'
        f'<a href="https://thanhtoan.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Cổng thanh toán Trực tuyến">{SVG_CARD_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">Thanh toán</span></a>'
        '</div>'
        f'<div class="sidebar-section-title" style="margin-top: 12px;">{SVG_LANDMARK_ICON}<span>ĐƠN VỊ HỖ TRỢ</span></div>'
        '<div class="sidebar-link-grid">'
        f'<a href="https://tuyensinh.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Tuyển sinh">{SVG_COMPASS_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">Tuyển sinh</span></a>'
        f'<a href="http://pdt.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Đào tạo - Đảm bảo chất lượng (A1.101)">{SVG_CLIPBOARD_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">Đào tạo (A1.101)</span></a>'
        f'<a href="http://cgtdt-dsa.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Công tác sinh viên và Truyền thông (A1.102)">{SVG_USERS_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">CTSV (A1.102)</span></a>'
        f'<a href="https://vlute.edu.vn/phong-ke-hoach-tai-chinh" target="_blank" class="sidebar-link-item" title="Phòng Kế hoạch - Tài chính (Tầng trệt)">{SVG_WALLET_ICON}<span style="overflow:hidden;text-overflow:ellipsis;">KHTC (Tầng trệt)</span></a>'
        '</div>'
        '</div>'
    )
    st.markdown(SIDEBAR_NAV_HTML, unsafe_allow_html=True)

    # Khối thông tin liên hệ phòng ban (đọc động từ departments.json)
    depts_cfg = load_departments_config()
    sidebar_order = [k for k in ("dao_tao", "ctsv", "khtc", "cntt") if k in depts_cfg] + [
        k for k in depts_cfg.keys() if k not in ("dao_tao", "ctsv", "khtc", "cntt")
    ]
    dept_rows_html = []
    for d_key in sidebar_order:
        d_item = depts_cfg.get(d_key, {})
        d_name = html.escape(str(d_item.get("name", d_key)).replace(" (VLUTE)", ""))
        d_loc = html.escape(str(d_item.get("location", "")))
        d_phone = html.escape(str(d_item.get("phone", "")))
        d_email = html.escape(str(d_item.get("email", "")))
        loc_str = f" ({d_loc})" if d_loc else ""
        dept_rows_html.append(
            f'<div style="margin-bottom: 6px; font-size: 0.8rem;">'
            f'<b style="color: #a7f3d0;">• {d_name}{loc_str}:</b><br>'
            f'<span style="display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap;">'
            f'{SVG_SIDEBAR_PHONE_ROW}<code>{d_phone}</code>'
            f'<span style="color: #475569; margin: 0 2px;">|</span>'
            f'{SVG_SIDEBAR_MAIL_ROW}<i>{d_email}</i>'
            f'</span>'
            f'</div>'
        )
    sidebar_contacts_html = (
        '<div class="sidebar-contact-card">'
        f'<div style="font-weight: 700; color: #ffffff; margin-bottom: 6px; font-size: 0.85rem; display: flex; align-items: center; gap: 6px;">'
        f'{SVG_SIDEBAR_PHONE_HEADER}<span>ĐẦU MỐI LIÊN HỆ PHÒNG BAN:</span>'
        '</div>'
        + "".join(dept_rows_html)
        + '</div>'
    )
    st.markdown(sidebar_contacts_html, unsafe_allow_html=True)
    
    st.markdown("""
    <div style="margin-top: 10px; padding: 8px 10px; background: rgba(0, 0, 0, 0.2); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; font-size: 0.72rem; color: #94a3b8; text-align: center; line-height: 1.45;">
        <div style="color: #cbd5e1; font-weight: 700;">© Trường ĐH Công nghệ Kỹ thuật Vĩnh Long</div>
        <div style="font-size: 0.68rem; color: #a7f3d0; margin-top: 1px;">(Tiền thân: Trường ĐH Sư phạm Kỹ thuật Vĩnh Long)</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<div id="chat-scroll-anchor"></div>', unsafe_allow_html=True)
components.html(
    """<script>
    (function() {
        var parentWin = window.parent;
        var doc = parentWin.document;

        function isScrollableY(el) {
            if (!el || el.nodeType !== 1) {
                return false;
            }
            var style = parentWin.getComputedStyle(el);
            var oy = style ? style.overflowY : '';
            return oy === 'auto' || oy === 'scroll';
        }

        function findScrollContainer() {
            var anchor = doc.getElementById('chat-scroll-anchor');
            var firstOverflowMatch = null;
            var el = anchor ? anchor.parentElement : null;
            while (el && el !== doc.documentElement) {
                if (isScrollableY(el)) {
                    if (el.scrollHeight > el.clientHeight) {
                        return el;
                    }
                    if (!firstOverflowMatch) {
                        firstOverflowMatch = el;
                    }
                }
                el = el.parentElement;
            }

            var fallbacks = [
                doc.querySelector('[data-testid="stAppViewContainer"]'),
                doc.querySelector('[data-testid="stMain"]'),
                firstOverflowMatch,
                doc.scrollingElement,
                doc.documentElement,
                doc.body
            ];
            for (var i = 0; i < fallbacks.length; i++) {
                var cand = fallbacks[i];
                if (cand && cand.scrollHeight > cand.clientHeight) {
                    return cand;
                }
            }
            for (var j = 0; j < fallbacks.length; j++) {
                if (fallbacks[j]) {
                    return fallbacks[j];
                }
            }
            return null;
        }

        function syncUserMessageScrollReset() {
            var curUsers = doc.querySelectorAll('.chat-row-user').length;
            if (curUsers === 0) {
                parentWin.__vluteLastUserMsgCount = 0;
                parentWin.__vluteUserScrolledUp = false;
                return 0;
            }
            if (typeof parentWin.__vluteLastUserMsgCount === 'undefined') {
                parentWin.__vluteLastUserMsgCount = curUsers;
            } else if (curUsers > parentWin.__vluteLastUserMsgCount) {
                parentWin.__vluteLastUserMsgCount = curUsers;
                parentWin.__vluteUserScrolledUp = false;
                parentWin.__vlutePauseGlideUntil = 0;
            }
            return curUsers;
        }

        function distFromBottom(el) {
            if (!el) return 0;
            return Math.max(0, el.scrollHeight - el.scrollTop - el.clientHeight);
        }

        function cancelActiveGlide() {
            if (parentWin.__vluteGlideRaf) {
                parentWin.cancelAnimationFrame(parentWin.__vluteGlideRaf);
                parentWin.__vluteGlideRaf = null;
            }
        }

        function bindScrollContainerEvents(sc) {
            if (!sc || sc.__vluteScrollListenersBound) {
                return;
            }
            sc.__vluteScrollListenersBound = true;
            sc.__vlutePrevScrollTop = sc.scrollTop;

            sc.addEventListener('wheel', function(e) {
                if (e.deltaY < 0) {
                    parentWin.__vluteLastUpInputTs = Date.now();
                    parentWin.__vlutePauseGlideUntil = Date.now() + 200;
                    cancelActiveGlide();
                    if (distFromBottom(sc) > 140) {
                        parentWin.__vluteUserScrolledUp = true;
                    }
                }
            }, { passive: true });

            sc.addEventListener('touchstart', function() {
                parentWin.__vluteLastUpInputTs = Date.now();
                parentWin.__vlutePauseGlideUntil = Date.now() + 450;
                if (distFromBottom(sc) > 140) {
                    parentWin.__vluteUserScrolledUp = true;
                    cancelActiveGlide();
                }
            }, { passive: true });

            sc.addEventListener('scroll', function() {
                var dist = distFromBottom(sc);
                var now = Date.now();
                var recentUpInput = (now - (parentWin.__vluteLastUpInputTs || 0)) < 700;
                var movedUp = sc.scrollTop < (sc.__vlutePrevScrollTop || 0) - 6;
                if (dist > 140 && (recentUpInput || (!parentWin.__vluteGlideRaf && movedUp))) {
                    parentWin.__vluteUserScrolledUp = true;
                    cancelActiveGlide();
                } else if (parentWin.__vluteUserScrolledUp && dist < 60) {
                    parentWin.__vluteUserScrolledUp = false;
                }
                sc.__vlutePrevScrollTop = sc.scrollTop;
            }, { passive: true });
        }

        function pinWelcomeTopIfEmpty() {
            try {
                if (parentWin.history && 'scrollRestoration' in parentWin.history) {
                    parentWin.history.scrollRestoration = 'manual';
                }
            } catch (e) {}
            if (syncUserMessageScrollReset() > 0) {
                return false;
            }
            parentWin.__vlutePrevScrollHeight = 0;
            parentWin.__vluteUserScrolledUp = false;
            cancelActiveGlide();
            var candidates = [
                findScrollContainer(),
                doc.querySelector('[data-testid="stAppViewContainer"]'),
                doc.querySelector('[data-testid="stMain"]'),
                doc.scrollingElement,
                doc.documentElement
            ];
            for (var c = 0; c < candidates.length; c++) {
                if (candidates[c] && candidates[c].scrollTop > 0) {
                    candidates[c].scrollTop = 0;
                }
            }
            return true;
        }

        function smoothGlideToBottom() {
            cancelActiveGlide();
            if (parentWin.__vluteUserScrolledUp || Date.now() < (parentWin.__vlutePauseGlideUntil || 0)) {
                return;
            }

            function step() {
                if (pinWelcomeTopIfEmpty()) {
                    return;
                }
                if (parentWin.__vluteUserScrolledUp || Date.now() < (parentWin.__vlutePauseGlideUntil || 0)) {
                    parentWin.__vluteGlideRaf = null;
                    return;
                }

                var scrollContainer = findScrollContainer();
                if (!scrollContainer) {
                    parentWin.__vluteGlideRaf = null;
                    return;
                }
                bindScrollContainerEvents(scrollContainer);

                var el = scrollContainer;
                if (el.scrollHeight < (parentWin.__vlutePrevScrollHeight || 0) - 160 && el.scrollTop > 120) {
                    parentWin.__vluteGlideRaf = null;
                    return;
                }

                parentWin.__vlutePrevScrollHeight = Math.max(parentWin.__vlutePrevScrollHeight || 0, el.scrollHeight);

                if (el.scrollHeight <= el.clientHeight) {
                    parentWin.__vluteGlideRaf = null;
                    return;
                }

                var targetTop = Math.max(0, el.scrollHeight - el.clientHeight);
                var diff = targetTop - el.scrollTop;
                if (Math.abs(diff) < 1.5) {
                    el.scrollTop = targetTop;
                    parentWin.__vluteGlideRaf = null;
                    return;
                }

                var prevTop = el.scrollTop;
                el.scrollTop += diff * 0.34;
                if (Math.abs(el.scrollTop - prevTop) < 0.05) {
                    el.scrollTop += diff > 0 ? 1 : -1;
                    if (Math.abs(el.scrollTop - prevTop) < 0.05 || Math.abs(targetTop - el.scrollTop) < 1.5) {
                        el.scrollTop = targetTop;
                        parentWin.__vluteGlideRaf = null;
                        return;
                    }
                }
                parentWin.__vluteGlideRaf = parentWin.requestAnimationFrame(step);
            }

            parentWin.__vluteGlideRaf = parentWin.requestAnimationFrame(step);
        }

        function scheduleScroll() {
            syncUserMessageScrollReset();
            var sc = findScrollContainer();
            if (sc) {
                bindScrollContainerEvents(sc);
            }
            if (parentWin.__vluteUserScrolledUp || Date.now() < (parentWin.__vlutePauseGlideUntil || 0)) {
                return;
            }
            if (parentWin.__vluteWaitDomRaf) {
                return;
            }
            parentWin.__vluteWaitDomRaf = parentWin.requestAnimationFrame(function() {
                parentWin.__vluteWaitDomRaf = null;
                if (pinWelcomeTopIfEmpty()) {
                    return;
                }
                if (parentWin.__vluteUserScrolledUp || Date.now() < (parentWin.__vlutePauseGlideUntil || 0)) {
                    return;
                }
                var el = findScrollContainer();
                if (!el) {
                    return;
                }
                bindScrollContainerEvents(el);
                if (el.scrollHeight < (parentWin.__vlutePrevScrollHeight || 0) - 160 && el.scrollTop > 120) {
                    return;
                }
                parentWin.__vlutePrevScrollHeight = Math.max(parentWin.__vlutePrevScrollHeight || 0, el.scrollHeight);
                smoothGlideToBottom();
            });
        }

        parentWin.__vluteScheduleScroll = scheduleScroll;

        function scrollToBottomNow() {
            if (pinWelcomeTopIfEmpty() || parentWin.__vluteUserScrolledUp) {
                return;
            }
            var sc = findScrollContainer();
            if (!sc || sc.scrollHeight <= sc.clientHeight) {
                return;
            }
            cancelActiveGlide();
            var targetTop = Math.max(0, sc.scrollHeight - sc.clientHeight);
            sc.scrollTop = targetTop;
            sc.__vlutePrevScrollTop = sc.scrollTop;
            parentWin.__vlutePrevScrollHeight = sc.scrollHeight;
        }

        function attachMainResizeObserver() {
            if (typeof parentWin.ResizeObserver !== 'function') {
                return;
            }
            var mainBlock = doc.querySelector('[data-testid="stMainBlockContainer"]') || doc.querySelector('[data-testid="stAppViewBlockContainer"]');
            if (!mainBlock || mainBlock.__vluteResizeObserved) {
                return;
            }
            mainBlock.__vluteResizeObserved = true;
            mainBlock.__vluteLastWidth = mainBlock.getBoundingClientRect().width;

            var resizeObs = new parentWin.ResizeObserver(function(entries) {
                if (pinWelcomeTopIfEmpty() || parentWin.__vluteUserScrolledUp) {
                    return;
                }
                var widthChanged = false;
                for (var i = 0; i < entries.length; i++) {
                    var w = entries[i].contentRect ? entries[i].contentRect.width : mainBlock.getBoundingClientRect().width;
                    if (Math.abs(w - (mainBlock.__vluteLastWidth || 0)) > 0.5) {
                        mainBlock.__vluteLastWidth = w;
                        widthChanged = true;
                    }
                }
                if (!widthChanged) {
                    return;
                }
                var sc = findScrollContainer();
                if (sc && !parentWin.__vluteUserScrolledUp && distFromBottom(sc) < 260) {
                    scrollToBottomNow();
                    setTimeout(function() {
                        var scLate = findScrollContainer();
                        if (scLate && !parentWin.__vluteUserScrolledUp && distFromBottom(scLate) < 260) {
                            scrollToBottomNow();
                        }
                    }, 380);
                }
            });
            resizeObs.observe(mainBlock);
        }

        function attachScrollObserver() {
            if (!doc.body) {
                return false;
            }
            var initialSc = findScrollContainer();
            if (initialSc) {
                bindScrollContainerEvents(initialSc);
            }
            attachMainResizeObserver();
            if (parentWin.__vluteScrollObserverAttached) {
                return true;
            }
            parentWin.__vluteScrollObserverAttached = true;

            var observer = new MutationObserver(function(mutations) {
                if (pinWelcomeTopIfEmpty()) {
                    return;
                }
                var hasChatMutation = false;
                for (var i = 0; i < mutations.length; i++) {
                    var target = mutations[i].target;
                    var el = target && target.nodeType === 1 ? target : (target ? target.parentElement : null);
                    if (el && !el.closest('[data-testid="stSidebar"]') && !el.closest('[data-testid="stBottom"]')) {
                        if (
                            el.closest('[data-testid="stChatMessage"]') ||
                            el.closest('[data-testid="stMainBlockContainer"]') ||
                            el.closest('[data-testid="stAppViewBlockContainer"]') ||
                            el.closest('.chat-row-user') ||
                            el.id === 'chat-scroll-anchor'
                        ) {
                            hasChatMutation = true;
                            break;
                        }
                    }
                    var added = mutations[i].addedNodes;
                    if (added && added.length) {
                        for (var k = 0; k < added.length; k++) {
                            var node = added[k];
                            if (node && node.nodeType === 1 && !(node.closest && node.closest('[data-testid="stSidebar"]'))) {
                                if (
                                    node.id === 'chat-scroll-anchor' ||
                                    (node.matches && node.matches('[data-testid="stChatMessage"], .chat-row-user')) ||
                                    (node.querySelector && node.querySelector('[data-testid="stChatMessage"], .chat-row-user, #chat-scroll-anchor'))
                                ) {
                                    hasChatMutation = true;
                                    break;
                                }
                            }
                        }
                        if (hasChatMutation) {
                            break;
                        }
                    }
                }
                if (hasChatMutation && typeof parentWin.__vluteScheduleScroll === 'function') {
                    parentWin.__vluteScheduleScroll();
                }
            });

            observer.observe(doc.body, {
                childList: true,
                subtree: true,
                characterData: true
            });
            if (!pinWelcomeTopIfEmpty()) {
                scheduleScroll();
            }
            return true;
        }

        if (pinWelcomeTopIfEmpty()) {
            parentWin.requestAnimationFrame(pinWelcomeTopIfEmpty);
            setTimeout(pinWelcomeTopIfEmpty, 120);
        }

        if (!attachScrollObserver()) {
            var retry = setInterval(function() {
                if (attachScrollObserver()) {
                    clearInterval(retry);
                }
            }, 80);
        } else if (!pinWelcomeTopIfEmpty()) {
            scheduleScroll();
        }
        if (doc.querySelectorAll('.chat-row-user').length === 0) {
            pinWelcomeTopIfEmpty();
        }
    })();
    </script>""",
    height=0,
)