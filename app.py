import os
import re
import json
import html
import time
import base64
import traceback
import unicodedata
import streamlit as st
import streamlit.components.v1 as components
from rag import get_rag_chain, DOC_CATALOG, extract_article_info, REFUSAL_MESSAGE, load_departments_config, rewrite_conversational_query

st.set_page_config(
    page_title="VLUTEBOT - Trợ lý Lucas", 
    page_icon="🎓", 
    layout="centered"
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
avatar_img_html = f'<img src="data:image/png;base64,{lucas_avatar_b64}" style="width: 56px; height: 56px; border-radius: 50%; vertical-align: middle; margin-right: 12px; object-fit: cover; box-shadow: 0 3px 8px rgba(0,0,0,0.25); display: inline-block;">' if lucas_avatar_b64 else '🎓 '

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
/* Vô hiệu hóa hiệu ứng làm mờ khi Streamlit đang tính toán hoặc re-run */
[data-stale="true"] {
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

/* Ẩn widget trạng thái, menu/header mặc định thừa và nút deploy để giao diện gọn như web app độc lập */
div[data-testid="stElementContainer"]:has(iframe[height="0"]),
iframe[height="0"] {
    height: 0px !important;
    min-height: 0px !important;
    margin: 0px !important;
    padding: 0px !important;
    overflow: hidden !important;
    border: none !important;
}

#MainMenu,
footer,
[data-testid="stDecoration"],
.stAppDeployButton,
div[data-testid="stStatusWidget"] {
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

/* Cuộn mượt toàn cục */
html, body, [data-testid="stAppViewContainer"], section[data-testid="stMain"], .main {
    scroll-behavior: smooth !important;
}

/* 0. Nền chung toàn trang & vùng nội dung chính */
.stApp {
    background-color: #f4f6f9 !important;
    color: #1e293b !important;
}

.main .block-container,
div[data-testid="stAppViewBlockContainer"] {
    max-width: 820px !important;
    padding-bottom: 120px !important;
}

/* 1. Header tinh gọn chiều cao 110-120px */
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
    transition: all 0.2s ease;
}

.vlute-nav-badge:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.12);
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
    transition: all 0.2s ease !important;
    font-size: 0 !important;
    color: transparent !important;
}

button[data-testid="stExpandSidebarButton"]:hover,
[data-testid="stExpandSidebarButton"]:hover,
[data-testid="collapsedControl"]:hover {
    background-color: #f0f7f3 !important;
    border-color: #008d4c !important;
    transform: scale(1.05) !important;
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
    font-size: 0.8rem !important;
    font-weight: 700 !important;
    color: #b8c7ce !important;
    letter-spacing: 0.6px !important;
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
    transition: all 0.2s ease !important;
    font-size: 0 !important;
    color: transparent !important;
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
    transition: all 0.2s ease;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.sidebar-link-item:hover {
    background: #00a65a !important;
    border-color: #00a65a !important;
    color: #ffffff !important;
    transform: translateY(-1px);
}

section[data-testid="stSidebar"] .stButton > button {
    border-radius: 8px !important;
    border: none !important;
    background-color: #00a65a !important;
    color: white !important;
    font-weight: 700 !important;
    transition: all 0.2s ease !important;
}

section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #008d4c !important;
    color: white !important;
}

/* 5. KHUNG TIN NHẮN VÀ BONG BÓNG CHAT (MAX-WIDTH: 720PX) */
@keyframes fadeInBubble {
    from {
        opacity: 0;
        transform: translateY(6px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

div[data-testid="stChatMessage"] {
    display: flex !important;
    align-items: flex-start !important;
    margin-bottom: 1.2rem !important;
    gap: 14px !important;
    width: 100% !important;
    background: transparent !important;
    padding: 0 !important;
    animation: fadeInBubble 0.25s ease-out both;
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
    border-radius: 50% !important;
    object-fit: cover !important;
    transform: none !important;
    border: none !important;
    background: transparent !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15) !important;
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
    width: fit-content !important;
    color: #1e293b !important;
    box-sizing: border-box !important;
    line-height: 1.65 !important;
    margin-left: 0px !important;
    box-shadow: 0 4px 14px rgba(0, 112, 60, 0.12) !important;
    word-break: normal !important;
    overflow-wrap: break-word !important;
    transition: all 0.2s ease !important;
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
    animation: fadeInBubble 0.22s ease-out both;
}

.user-bubble {
    background-color: #0073b7 !important;
    border: 2px solid #005587 !important;
    color: #ffffff !important;
    border-radius: 20px !important;
    padding: 12px 20px !important;
    max-width: 720px !important;
    width: fit-content;
    word-break: normal !important;
    overflow-wrap: break-word !important;
    font-size: 1rem !important;
    line-height: 1.6 !important;
    box-shadow: 0 4px 14px rgba(0, 115, 183, 0.18) !important;
    transition: all 0.2s ease !important;
}

/* Thẻ chân trang liên hệ phòng ban có micro-interaction mượt */
.contact-footer-card {
    margin-top: 12px;
    padding: 12px 16px;
    background: #f8fafc;
    border-radius: 8px;
    border-left: 3.5px solid #ff9800;
    color: #334155 !important;
    transition: all 0.2s ease !important;
}

.contact-footer-card:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 90, 48, 0.12);
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

/* 7. Nút bấm câu hỏi gợi ý nhanh */
.quick-prompt-title {
    font-size: 0.88rem;
    font-weight: 700;
    color: #00703c;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
}

div[data-testid="stHorizontalBlock"] button {
    background-color: #ffffff !important;
    color: #00703c !important;
    border: 1.5px solid #00703c !important;
    border-radius: 18px !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
    padding: 6px 12px !important;
    text-align: left !important;
    box-shadow: 0 2px 4px rgba(0, 112, 60, 0.08) !important;
    transition: all 0.2s ease !important;
    white-space: normal !important;
    height: auto !important;
}

div[data-testid="stHorizontalBlock"] button:hover {
    background-color: #00703c !important;
    color: #ffffff !important;
    box-shadow: 0 4px 8px rgba(0, 112, 60, 0.22) !important;
    transform: translateY(-1px);
}

/* Đảm bảo nút gợi ý bên trong tin nhắn bot có chữ rõ nét, không bị đè màu trắng */
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button p,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button span {
    color: #00703c !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button:hover,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button:hover p,
div[data-testid="stChatMessageContent"] div[data-testid="stHorizontalBlock"] button:hover span {
    color: #ffffff !important;
}

/* Khung chat input */
div[data-testid="stChatInput"] {
    border-radius: 12px !important;
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
    }
    .vlute-portal-title {
        font-size: 0.95rem !important;
        line-height: 1.25 !important;
    }
    .vlute-portal-subtitle {
        font-size: 0.75rem !important;
    }

    /* 3. Tối ưu bong bóng chat hiển thị rộng rãi, vừa vặn khung hình */
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

def trigger_smooth_scroll(follow_stream: bool = False):
    """Tự động cuộn mượt xuống cuối khung trò chuyện mà không làm chớp giao diện."""
    observer_js = """
        const mainContainer = doc.querySelector('[data-testid="stAppViewContainer"]') || doc.querySelector('section.main') || doc.documentElement;
        if (mainContainer) {
            let timer = null;
            const obs = new MutationObserver(() => {
                doScroll();
                clearTimeout(timer);
                timer = setTimeout(() => obs.disconnect(), 1800);
            });
            obs.observe(mainContainer, { childList: true, subtree: true, characterData: true });
            setTimeout(() => obs.disconnect(), 18000);
        }
    """ if follow_stream else ""
    components.html(
        f"""
        <script>
        (function() {{
            const doc = window.parent.document;
            function doScroll() {{
                const targets = [
                    doc.querySelector('[data-testid="stAppViewContainer"]'),
                    doc.querySelector('section.main'),
                    doc.documentElement,
                    doc.body
                ].filter(Boolean);
                targets.forEach(el => {{
                    try {{
                        el.scrollTo({{ top: el.scrollHeight, behavior: 'smooth' }});
                    }} catch (e) {{
                        el.scrollTop = el.scrollHeight;
                    }}
                }});
                try {{
                    window.parent.scrollTo({{ top: doc.body.scrollHeight, behavior: 'smooth' }});
                }} catch (e) {{}}
            }}
            setTimeout(doScroll, 60);
            {observer_js}
        }})();
        </script>
        """,
        height=0,
    )

# ==========================================
# 1. HEADER TINH GỌN (110-120PX)
# ==========================================
logo_html_img = f'<img src="data:image/png;base64,{LOGO_B64}" class="vlute-logo-img" alt="Logo VLUTE" />' if LOGO_B64 else '<span style="font-size:32px;">🎓</span>'

st.markdown(f"""
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
        <span>🟢 Tra cứu học vụ</span>
    </div>
    <div class="vlute-nav-badge official">
        <span>📚 Văn bản chính thức</span>
    </div>
    <div class="vlute-nav-badge verified">
        <span>🛡️ Trả lời có căn cứ</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# 4. SIDEBAR ĐẦY ĐỦ (2 NHÓM RÕ RÀNG)
# ==========================================
with st.sidebar:
    if LOGO_B64:
        st.markdown(f"""
        <div style="display: flex; justify-content: center; align-items: center; width: 100%; margin-bottom: 8px; margin-top: 2px;">
            <img src="data:image/png;base64,{LOGO_B64}" style="width: 95px; height: 95px; object-fit: contain; filter: drop-shadow(0 3px 8px rgba(0,0,0,0.4));" alt="Logo VLUTE" />
        </div>
        <div style="text-align: center; color: #ffffff; font-weight: 800; font-size: 0.92rem; letter-spacing: 0.3px; margin-bottom: 4px; line-height: 1.35;">
            TRƯỜNG ĐẠI HỌC<br><span style="white-space: nowrap; color: #ffffff;">CNKT VĨNH LONG</span>
        </div>
        <div style="text-align: center; color: #00a65a; font-weight: 700; font-size: 0.76rem; letter-spacing: 0.6px; text-transform: uppercase; margin-bottom: 10px;">
            QUẢN LÝ ĐÀO TẠO & HỌC VỤ
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("""
    <div style="text-align: center; color: #cbd5e1; font-size: 0.75rem; margin-bottom: 10px; padding: 6px 8px; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; line-height: 1.4; word-break: keep-all;">
        <span>📍</span> <span>Số 73 Nguyễn Huệ, Phường Long Châu, Tỉnh Vĩnh Long</span>
    </div>
    """, unsafe_allow_html=True)

    if st.button("🗑️ Làm mới cuộc trò chuyện", use_container_width=True):
        st.session_state.messages = []
        st.session_state.pending_user_query = None
        st.rerun()
    
    # 2 nhóm liên kết hệ thống rõ rệt (chuỗi không thụt lề để triệt tiêu lỗi code thô)
    SIDEBAR_NAV_HTML = """<div class="sidebar-links-card">
<div class="sidebar-section-title">🔗 HỆ THỐNG HỌC TẬP</div>
<div class="sidebar-link-grid">
<a href="https://vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Cổng thông tin My VLUTE">🌐 My VLUTE</a>
<a href="https://daotao.vlute.edu.vn/sinh-vien" target="_blank" class="sidebar-link-item" title="Đăng ký học phần">📝 ĐK Học phần</a>
<a href="http://elearning.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Học trực tuyến E-Learning">💻 E-Learning</a>
<a href="https://thanhtoan.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Cổng thanh toán Trực tuyến">💳 Thanh toán</a>
</div>
<div class="sidebar-section-title" style="margin-top: 12px;">🏫 ĐƠN VỊ HỖ TRỢ</div>
<div class="sidebar-link-grid">
<a href="https://tuyensinh.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Tuyển sinh">🎯 Tuyển sinh</a>
<a href="http://pdt.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Đào tạo (A1.101)">📋 Đào tạo (A1.101)</a>
<a href="http://cgtdt-dsa.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Công tác SV (A1.102)">👥 CTSV (A1.102)</a>
<a href="https://vlute.edu.vn" target="_blank" class="sidebar-link-item" title="Phòng Kế hoạch - Tài chính">💰 KHTC (Tầng trệt)</a>
</div>
</div>"""
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
            f'☎️ <code>{d_phone}</code> | ✉️ <i>{d_email}</i>'
            f'</div>'
        )
    sidebar_contacts_html = (
        '<div class="sidebar-contact-card">'
        '<div style="font-weight: 700; color: #ffffff; margin-bottom: 6px; font-size: 0.85rem;">'
        '📞 ĐẦU MỐI LIÊN HỆ PHÒNG BAN:'
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

# ==========================================
# KHỞI TẠO VÀ CACHE RAG CHAIN
# ==========================================
@st.cache_resource(show_spinner=False)
def load_chain():
    """Nạp chuỗi RAG Lucas một lần duy nhất vào bộ nhớ cache toàn cục (Singleton)."""
    return get_rag_chain()

try:
    if "qa_chain" not in st.session_state:
        st.session_state.qa_chain = load_chain()
    qa_chain = st.session_state.qa_chain
except Exception as e:
    st.error(f"Lỗi khởi tạo hệ thống: {e}")
    st.stop()

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


def build_assistant_bubble_html(content: str, contact_html: str = "", elapsed_time=None, is_refusal: bool = False, is_welcome_or_greeting: bool = False) -> str:
    """Gộp Huy hiệu + Nội dung + Khối liên hệ vào chung 1 chuỗi Markdown/HTML duy nhất để cố định 1 DOM Slot."""
    body = (content or "").strip()
    if is_welcome_or_greeting:
        return body
    if is_refusal:
        if not body:
            body = REFUSAL_MESSAGE
        # Đảm bảo ép hiển thị rõ ràng chuỗi từ chối kèm định dạng gạch đầu dòng
        refusal_text = body if body.startswith("•") else f"• {body}"
        return f"{refusal_text}\n\n{contact_html}" if contact_html else refusal_text

    badge = get_verify_badge_html(elapsed_time)
    return f"{badge}\n\n{body}\n\n{contact_html}" if contact_html else f"{badge}\n\n{body}"

CTSV_CONTACT_HTML = """<div class="contact-footer-card">
  <b style="color: #005a30 !important;">📞 Phòng Công tác Sinh viên (VLUTE):</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;">Vị trí: Tòa nhà A (Phòng A1.102 - Tầng trệt)</li>
    <li style="color: #334155 !important;">Điện thoại: (0270) 3862 436 | Email: ctsv@vlute.edu.vn</li>
  </ul>
</div>"""

KHTC_CONTACT_HTML = """<div class="contact-footer-card">
  <b style="color: #005a30 !important;">📞 Phòng Kế hoạch - Tài chính (VLUTE):</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;">Vị trí: Tòa nhà A (Tầng trệt)</li>
    <li style="color: #334155 !important;">Điện thoại: (0270) 3822 141 | Email: khtc@vlute.edu.vn</li>
  </ul>
</div>"""

RATE_LIMIT_MESSAGE = "⚠️ Hệ thống tra cứu đang nhận lượng truy cập cao trong cùng thời điểm. Bạn vui lòng đợi khoảng 30–60 giây rồi thử hỏi lại nhé!"


def execute_rag_pipeline(query: str, chat_history: list | None = None):
    """Thực thi trực tiếp (live) pipeline RAG sử dụng chain đã cache."""
    effective_query = rewrite_conversational_query(query, chat_history) if chat_history else query
    chain = load_chain()
    docs = chain.filter_documents(effective_query, k=6)
    if not docs:
        return REFUSAL_MESSAGE, [], 0

    context_parts = []
    sources = []
    for doc in docs:
        src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
        title = doc.metadata.get("title", src_file)
        page = doc.metadata.get("page", 1)
        article = extract_article_info(doc.page_content)

        header_line = f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
        context_parts.append(f"{header_line}\n{doc.page_content}")

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
            "snippet": doc.page_content.strip()
        })

    context_str = "\n\n".join(context_parts)
    formatted_prompt = chain.prompt.format(context=context_str, input=effective_query)

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

    context_parts = []
    sources = []
    for doc in docs:
        src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
        title = doc.metadata.get("title", src_file)
        page = doc.metadata.get("page", 1)
        article = extract_article_info(doc.page_content)

        header_line = f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
        context_parts.append(f"{header_line}\n{doc.page_content}")

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
            "snippet": doc.page_content.strip()
        })

    context_str = "\n\n".join(context_parts)
    formatted_prompt = chain.prompt.format(context=context_str, input=effective_query)

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
    """Làm sạch khoảng trắng thừa của câu hỏi, giữ nguyên nội dung câu hỏi để chạy trực tiếp qua RAG."""
    if not query:
        return ""
    return re.sub(r"\s+", " ", query.strip())

# ==========================================
# 2. TINH GỌN LỜI CHÀO MỞ ĐẦU
# ==========================================
WELCOME_CONTENT = (
    "👋 **Xin chào! Mình là Lucas** – trợ lý hỗ trợ tra cứu Quy chế Đào tạo & Quy định sinh viên VLUTE.\n\n"
    "Bạn có thể chọn nhanh các câu hỏi bên dưới hoặc tra cứu về: Học bổng, học phí, đào tạo, học vụ..."
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


# Callback gán câu hỏi trực tiếp vào session_state trước khi rerun
if "pending_user_query" not in st.session_state:
    st.session_state.pending_user_query = None


def submit_user_query(query_text: str):
    st.session_state.pending_user_query = query_text

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

def is_greeting(query: str) -> bool:
    """Nhận diện nhanh các câu chào hỏi xã giao bằng ranh giới từ (\\b) để tránh khớp nhầm."""
    clean = query.lower().strip()
    words = clean.split()
    duty_keywords = ["học bổng", "học phí", "tín chỉ", "cảnh báo", "điểm", "rút môn", "thôi học", "miễn giảm", "bảo hiểm", "quy chế", "điều"]
    if len(words) <= 4 and any(re.search(rf"\b{re.escape(k)}\b", clean) for k in GREETING_KEYWORDS):
        if not any(dk in clean for dk in duty_keywords):
            return True
    return False

def is_refusal_answer(text: str) -> bool:
    """Kiểm tra xem phản hồi của mô hình có phải là câu từ chối ngoài phạm vi dữ liệu hoặc thông báo quá tải hay không."""
    t = (text or "").lower().strip()
    if not t:
        return True
    if "lượng truy cập cao" in t or "đợi khoảng 30–60 giây" in t:
        return True
    if "không được đề cập trong các văn bản quy định" in t or "nằm ngoài phạm vi dữ liệu quy chế" in t:
        return True
    if len(t) < 220 and any(kw in t for kw in ["không được đề cập", "ngoài phạm vi dữ liệu"]):
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
  <b style="color: #005a30 !important;">📞 {dept_name}:</b>
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
  <b style="color: #005a30 !important;">📞 Tuyến phối hợp xử lý (CTSV – Đào tạo – KHTC):</b>
  <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #334155 !important;">
    <li style="color: #334155 !important;"><b>1. {ctsv_dept['name']} (Tiếp nhận & tổng hợp đơn):</b> {ctsv_dept['location']} | ĐT: {ctsv_dept['phone']} | Email: {ctsv_dept['email']}</li>
    <li style="color: #334155 !important;"><b>2. {pdt_dept['name']} (Xác nhận học phí thừa):</b> {pdt_dept['location']} | ĐT: {pdt_dept['phone']} | Email: {pdt_dept['email']}</li>
    <li style="color: #334155 !important;"><b>3. {khtc_dept['name']} (Thanh toán hoàn trả):</b> {khtc_dept['location']} | ĐT: {khtc_dept['phone']} | Email: {khtc_dept['email']}</li>
  </ul>
</div>"""

    # 1. Ưu tiên cao nhất: Học bổng, khen thưởng, rèn luyện, kỷ luật, CTXH -> LUÔN về Phòng CTSV
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

    # 2. Miễn giảm học phí / Hỗ trợ chi phí học tập / Trợ cấp xã hội -> Đầu mối chính Phòng CTSV (A1.102) phối hợp Phòng KHTC
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

    # 3. Hoàn trả học phí thừa (QT-SV-04) -> Tuyến phối hợp CTSV – Đào tạo – KHTC
    hoan_tra_keywords = [
        "hoàn trả học phí", "học phí thừa", "hoàn phí", "hoàn tiền học phí",
        "rút tiền học phí", "nộp thừa", "hoàn trả"
    ]
    if any(kw in q_raw for kw in hoan_tra_keywords):
        return _build_hoan_tra_footer()

    # 3b. Chỉ định tuyến độc lập về Phòng KHTC khi hỏi về nộp học phí, hóa đơn, biên lai
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

    # 4. Nếu có retrieved_docs (và không phải từ chối): lấy metadata phòng ban từ tài liệu
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
    ]
    if any(rw in q for rw in regulation_keywords):
        return None
    ask_contact_keywords = ["địa chỉ", "ở đâu", "liên hệ", "số điện thoại", "sđt", "hotline", "email", "phòng nào", "gặp ai", "đơn vị nào"]
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

        has_pdt = any(k in q for k in ["đào tạo", "pdt", "học vụ"])
        has_ctsv = any(k in q for k in ["công tác sinh viên", "ctsv"])
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


def render_followup_suggestions(query_or_content: str, key_suffix: str = ""):
    """Hiển thị tối đa 2 nút gợi ý liên quan theo chủ đề, dùng callback on_click để phản hồi tức thì."""
    text_check = (query_or_content or "").lower()
    config = load_prompts_config()
    categories = config.get("categories", {})

    candidate_prompts = []
    # 1. So khớp từ khóa để tìm danh mục phù hợp nhất
    for _cat_key, cat_data in categories.items():
        kws = cat_data.get("keywords", [])
        if any(kw in text_check for kw in kws):
            candidate_prompts = [(p["label"], p["query"]) for p in cat_data.get("prompts", [])]
            break

    # Nếu không khớp nhóm nào, lấy mặc định từ initial_prompts
    if not candidate_prompts:
        candidate_prompts = [(p["label"], p["query"]) for p in config.get("initial_prompts", [])]

    # 2. Lọc bỏ câu hỏi trùng lặp với câu vừa hỏi
    filtered = [
        (lbl, q) for lbl, q in candidate_prompts
        if q.lower().strip("?") not in text_check and text_check not in q.lower()
    ]
    prompts_to_show = (filtered if len(filtered) >= 2 else candidate_prompts)[:2]

    if not prompts_to_show:
        return

    st.markdown("<p style='font-size: 0.88rem; color: #00703c !important; margin-top: 10px; margin-bottom: 6px;'>💡 <b style='color: #00703c !important;'>Gợi ý câu hỏi liên quan bạn có thể quan tâm:</b></p>", unsafe_allow_html=True)
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

# ==========================================
# HIỂN THỊ LỊCH SỬ TIN NHẮN
# ==========================================
last_assistant_idx = max(
    (i for i, m in enumerate(st.session_state.messages) if m.get("role") == "assistant"),
    default=-1
)

for idx, message in enumerate(st.session_state.messages):
    if message["role"] == "user":
        safe_content = html.escape(message["content"]).replace("\n", "<br>")
        st.markdown(
            f'<div class="chat-row-user"><div class="user-bubble">{safe_content}</div></div>',
            unsafe_allow_html=True
        )
    else:
        with st.chat_message("assistant", avatar="lucas_avatar.png" if os.path.exists("lucas_avatar.png") else "🎓"):
            msg_content = str(message.get("content", "") or "").strip()
            is_welcome_or_greeting = (idx == 0) or bool(message.get("is_greeting", False))
            is_dept_inquiry = bool(message.get("is_dept_inquiry", False))
            msg_is_refusal = bool(message.get("is_refusal", is_refusal_answer(msg_content))) or is_refusal_answer(msg_content)

            if is_welcome_or_greeting or is_dept_inquiry:
                st.markdown(build_assistant_bubble_html(msg_content, is_welcome_or_greeting=True), unsafe_allow_html=True)
                if is_dept_inquiry and idx > 0 and idx == last_assistant_idx and not user_query:
                    q_text = message.get("query") or (st.session_state.messages[idx - 1].get("content") if idx > 0 else "")
                    render_followup_suggestions(q_text or msg_content, key_suffix=str(idx))
            elif not msg_is_refusal:
                q_text = message.get("query") or (st.session_state.messages[idx - 1].get("content") if idx > 0 else "")
                contact_html = message.get("contact") or get_contact_footer(q_text or "", retrieved_docs=message.get("sources"), is_refusal=False)
                st.markdown(
                    build_assistant_bubble_html(msg_content, contact_html=contact_html, elapsed_time=message.get("elapsed_time"), is_refusal=False),
                    unsafe_allow_html=True
                )
                if idx > 0 and idx == last_assistant_idx and not user_query:
                    render_followup_suggestions(q_text or msg_content, key_suffix=str(idx))
            else:
                q_text = message.get("query") or (st.session_state.messages[idx - 1].get("content") if idx > 0 else "")
                contact_html = message.get("contact") or get_contact_footer(q_text or "", retrieved_docs=None, is_refusal=True)
                st.markdown(
                    build_assistant_bubble_html(msg_content or REFUSAL_MESSAGE, contact_html=contact_html, is_refusal=True),
                    unsafe_allow_html=True
                )
                if idx > 0 and idx == last_assistant_idx and not user_query:
                    render_followup_suggestions(q_text or msg_content, key_suffix=str(idx))

# ==========================================
# KHỐI GỢI Ý CÂU HỎI NHANH (KHI CHƯA BẮT ĐẦU HỎI)
# ==========================================
if len(st.session_state.messages) <= 1 and not user_query:
    st.markdown('<div class="quick-prompt-title">💡 Gợi ý câu hỏi nhanh từ văn bản quy chế:</div>', unsafe_allow_html=True)
    prompts_cfg = load_prompts_config()
    init_items = prompts_cfg.get("initial_prompts", [])[:4]

    col1, col2 = st.columns(2)
    for i, item in enumerate(init_items):
        target_col = col1 if i % 2 == 0 else col2
        with target_col:
            st.button(
                item["label"],
                key=f"init_prompt_{i}",
                use_container_width=True,
                on_click=submit_user_query,
                args=(item["query"],)
            )

if user_query:
    current_user_query = user_query.strip()

    # Lấy 2-3 lượt hội thoại gần nhất (tối đa 6 tin nhắn) trước khi nối câu hỏi hiện tại
    recent_chat_history = [
        {"role": m.get("role"), "content": m.get("content", "")}
        for m in st.session_state.messages[1:]
        if m.get("role") in ("user", "assistant") and not m.get("is_greeting", False)
    ][-6:]

    # Chống lặp tin nhắn nếu bấm nhiều lần
    if not (st.session_state.messages and st.session_state.messages[-1].get("role") == "user" and st.session_state.messages[-1].get("content") == current_user_query):
        st.session_state.messages.append({"role": "user", "content": current_user_query})

    # 1. Render ngay lập tức bong bóng câu hỏi người dùng lên màn hình (giữ nguyên văn bản gốc)
    safe_user_query = html.escape(current_user_query).replace("\n", "<br>")
    st.markdown(
        f'<div class="chat-row-user"><div class="user-bubble">{safe_user_query}</div></div>',
        unsafe_allow_html=True
    )

    new_msg_idx = len(st.session_state.messages)

    # 2. Mở ngay khung chat của Lucas và hiển thị hoạt ảnh Typing Indicator
    with st.chat_message("assistant", avatar="lucas_avatar.png" if os.path.exists("lucas_avatar.png") else "🎓"):
        status_placeholder = st.empty()
        status_placeholder.markdown(THINKING_HTML, unsafe_allow_html=True)
        trigger_smooth_scroll(follow_stream=True)

        # Force Flush nhả GIL để WebSocket đẩy bong bóng người dùng và typing indicator lên màn hình ngay lập tức
        time.sleep(0.05)

        if is_greeting(current_user_query):
            greeting_reply = (
                "Chào bạn! Mình có thể hỗ trợ bạn tra cứu quy chế nào hôm nay? "
                "*(Bạn có thể chọn các gợi ý nhanh ở trên hoặc gõ câu hỏi cụ thể nhé!)*"
            )
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
        else:
            canonical_query = normalize_query_intent(current_user_query)
            rewritten_query = rewrite_conversational_query(canonical_query, recent_chat_history)
            dept_reply = check_department_inquiry(rewritten_query) if "check_department_inquiry" in globals() else None

            if dept_reply:
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
                render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx))

            # 5. Tra cứu RAG nếu là câu hỏi quy chế
            else:
                try:
                    start_time = time.time()
                    stream_gen, sources_to_save, num_docs, retrieved_docs = stream_rag_pipeline(rewritten_query)

                    if not num_docs or not stream_gen:
                        no_doc_msg = REFUSAL_MESSAGE
                        contact_footer = get_contact_footer(rewritten_query, retrieved_docs=None, is_refusal=True)
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
                        render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx))
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
                            if (not first_chunk_rendered) or (time.time() - last_update > 0.035):
                                current_text = "".join(streamed_chunks)
                                status_placeholder.markdown(f"{badge_html}\n\n{current_text}", unsafe_allow_html=True)
                                last_update = time.time()
                                first_chunk_rendered = True

                        full_answer = "".join(streamed_chunks).strip()
                        elapsed_time = round(time.time() - start_time, 2)
                        is_interrupted = "Phản hồi bị gián đoạn giữa chừng do sự cố kết nối mô hình" in full_answer

                        if is_interrupted:
                            contact_footer = get_contact_footer(rewritten_query, retrieved_docs=retrieved_docs, is_refusal=True)
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
                            render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx))
                        elif is_refusal_answer(full_answer) or not full_answer:
                            full_answer = full_answer or REFUSAL_MESSAGE
                            contact_footer = get_contact_footer(rewritten_query, retrieved_docs=None, is_refusal=True)
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
                            render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx))
                        else:
                            contact_footer = get_contact_footer(rewritten_query, retrieved_docs=retrieved_docs, is_refusal=False)
                            status_placeholder.markdown(
                                build_assistant_bubble_html(full_answer, contact_html=contact_footer, elapsed_time=elapsed_time, is_refusal=False),
                                unsafe_allow_html=True
                            )
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
                            render_followup_suggestions(rewritten_query, key_suffix=str(new_msg_idx))

                except Exception as e:
                    status_placeholder.empty()
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
                        contact_footer = get_contact_footer(rewritten_query, retrieved_docs=None, is_refusal=True)
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
                    else:
                        import traceback
                        traceback.print_exc()
                        status_placeholder.error(f"Lỗi: {e}")

    trigger_smooth_scroll(follow_stream=False)