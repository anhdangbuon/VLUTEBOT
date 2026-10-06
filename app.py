import os
import re
import html
import time
import base64
import streamlit as st
from rag import get_rag_chain, DOC_CATALOG, extract_article_info, check_out_of_scope

st.set_page_config(
    page_title="VLUTEBOT - Trợ lý Lucas", 
    page_icon="🎓", 
    layout="centered"
)

# ==========================================
# CẤU HÌNH NHẬN DIỆN THƯƠNG HIỆU VLUTE
# ==========================================
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

lucas_avatar_b64 = get_base64_image("lucas_avatar.png")
avatar_img_html = f'''<div style="width: 66px; height: 66px; border-radius: 50%; overflow: hidden; display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; margin-right: 14px; border: 2.5px solid #2e7d32; box-shadow: 0 4px 10px rgba(0,0,0,0.3); background: #a5d6a7;"><img src="data:image/png;base64,{lucas_avatar_b64}" style="width: 100%; height: 100%; object-fit: cover; transform: scale(1.14); display: block;"></div>''' if lucas_avatar_b64 else '🎓 '

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
/* 0. Nền chung toàn trang */
.stApp {
    background-color: #f4f6f9 !important;
    color: #1e293b !important;
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
    width: 56px !important;
    height: 56px !important;
    min-width: 56px !important;
    min-height: 56px !important;
    margin-top: 2px !important;
    border-radius: 50% !important;
    overflow: hidden !important;
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 0 !important;
}

[data-testid="stChatMessageAvatarCustom"],
div[data-testid="stChatMessage"] img {
    width: 56px !important;
    height: 56px !important;
    border-radius: 50% !important;
    object-fit: cover !important;
    transform: scale(1.14) !important;
    border: 2px solid #2e7d32 !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15) !important;
    background: transparent !important;
}

div[data-testid="stChatMessage"] div:has(> img) {
    overflow: hidden !important;
    border-radius: 50% !important;
}

/* Khung tin nhắn của Lucas: Màu xanh lá VLUTE, MAX-WIDTH: 720px */
div[data-testid="stChatMessageContent"] {
    background-color: #00703c !important;
    border: 2px solid #00502b !important;
    border-radius: 20px !important;
    padding: 13px 20px !important;
    max-width: 720px !important;
    width: fit-content !important;
    color: #ffffff !important;
    box-sizing: border-box !important;
    line-height: 1.65 !important;
    margin-left: 0px !important;
    box-shadow: 0 4px 14px rgba(0, 112, 60, 0.18) !important;
    word-break: normal !important;
    overflow-wrap: break-word !important;
}

div[data-testid="stChatMessageContent"] ul {
    margin: 8px 0 8px 0 !important;
    padding-left: 20px !important;
}

div[data-testid="stChatMessageContent"] li {
    margin-bottom: 6px !important;
    line-height: 1.6 !important;
    color: #ffffff !important;
}

div[data-testid="stChatMessageContent"] li:last-child {
    margin-bottom: 0px !important;
}

div[data-testid="stChatMessageContent"] p,
div[data-testid="stChatMessageContent"] strong,
div[data-testid="stChatMessageContent"] b {
    color: #ffffff !important;
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
    word-break: normal !important;
    overflow-wrap: break-word !important;
    font-size: 1rem !important;
    line-height: 1.6 !important;
    box-shadow: 0 4px 14px rgba(0, 115, 183, 0.18) !important;
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

/* 6. Hoạt ảnh xoay bánh răng khi tìm kiếm */
.thinking-track {
    width: 100% !important;
    min-width: 280px;
    height: 36px;
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
}

.gears-slider {
    position: absolute;
    left: 0;
    display: inline-flex;
    align-items: center;
    width: max-content;
    animation: rollAcrossFull 3.5s ease-in-out infinite alternate;
}

.gear-icon {
    font-size: 22px;
    display: inline-block;
    line-height: 1;
}

.gear-main {
    color: #a7f3d0;
    animation: rotateGearMain 3.5s ease-in-out infinite alternate;
    transform-origin: center;
}

.gear-sub {
    color: #fde68a;
    font-size: 16px;
    margin-left: -5px;
    margin-top: -6px;
    animation: rotateGearSub 3.5s ease-in-out infinite alternate;
    transform-origin: center;
}

.thinking-label {
    font-size: 13px;
    color: #ecfdf5;
    font-style: italic;
    font-weight: 500;
    margin-left: 10px;
    white-space: nowrap;
}

@keyframes rollAcrossFull {
    0% { transform: translateX(0px); }
    100% { transform: translateX(calc(100% - 230px)); }
}

@keyframes rotateGearMain {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(720deg); }
}

@keyframes rotateGearSub {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(-720deg); }
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
<div class="thinking-track">
    <div class="gears-slider">
        <span class="gear-icon gear-main">⚙️</span>
        <span class="gear-icon gear-sub">⚙️</span>
        <span class="thinking-label">Lucas đang tra cứu quy chế VLUTE...</span>
    </div>
</div>
"""

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

<div class="vlute-alert-box">
    <span>💡 Lucas giải đáp dựa trên văn bản chính thức và luôn đính kèm nguồn điều khoản đối chiếu.</span>
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
    <div style="text-align: center; color: #cbd5e1; font-size: 0.75rem; margin-bottom: 12px; padding: 6px 8px; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; line-height: 1.4; word-break: keep-all;">
        <span>📍</span> <span>Số 73 Nguyễn Huệ, Phường Long Châu, Tỉnh Vĩnh Long</span>
    </div>
    """, unsafe_allow_html=True)
    
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

    # Khối thông tin liên hệ phòng ban
    st.markdown("""
    <div class="sidebar-contact-card">
        <div style="font-weight: 700; color: #ffffff; margin-bottom: 6px; font-size: 0.85rem;">
            📞 ĐẦU MỐI LIÊN HỆ PHÒNG BAN:
        </div>
        <div style="margin-bottom: 6px; font-size: 0.8rem;">
            <b style="color: #a7f3d0;">• Phòng Đào tạo (A1.101):</b><br>
            ☎️ <code>(0270) 3822 141</code> | ✉️ <i>daotao@vlute.edu.vn</i>
        </div>
        <div style="margin-bottom: 6px; font-size: 0.8rem;">
            <b style="color: #a7f3d0;">• Phòng CTSV (A1.102):</b><br>
            ☎️ <code>(0270) 3862 436</code> | ✉️ <i>ctsv@vlute.edu.vn</i>
        </div>
        <div style="margin-bottom: 6px; font-size: 0.8rem;">
            <b style="color: #a7f3d0;">• Phòng Kế hoạch - Tài chính:</b><br>
            ☎️ <code>(0270) 3822 141</code> | ✉️ <i>khtc@vlute.edu.vn</i>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div style="margin-top: 10px; padding: 8px 10px; background: rgba(0, 0, 0, 0.2); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; font-size: 0.72rem; color: #94a3b8; text-align: center; line-height: 1.45;">
        <div style="color: #cbd5e1; font-weight: 700;">© Trường ĐH Công nghệ Kỹ thuật Vĩnh Long</div>
        <div style="font-size: 0.68rem; color: #a7f3d0; margin-top: 1px;">(Tiền thân: Trường ĐH Sư phạm Kỹ thuật Vĩnh Long)</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    if st.button("🗑️ Làm mới cuộc trò chuyện", use_container_width=True):
        st.session_state.messages = []
        st.session_state.quick_prompt = None
        st.rerun()

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

@st.cache_data(ttl=86400, show_spinner=False)
def execute_rag_pipeline(query: str):
    """Thực thi pipeline RAG và cache kết quả vào RAM để tái sử dụng cho các sinh viên hỏi trùng câu hỏi."""
    # Lấy chuỗi RAG singleton
    chain = get_rag_chain()
    
    # 1. Trích xuất tài liệu đối chiếu
    docs = chain.filter_documents(query, k=3)
    if not docs:
        return "", [], None
        
    context_parts = []
    sources = []
    for i, doc in enumerate(docs, 1):
        src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
        doc_meta = DOC_CATALOG.get(src_file, {})
        title = doc_meta.get("title", src_file)
        short_title = doc_meta.get("short_title", src_file)
        dept = doc_meta.get("dept", "VLUTE")
        page = doc.metadata.get("page", 1)
        article = extract_article_info(doc.page_content)
        
        header_line = f"--- [TÀI LIỆU {i}: {title} | Trang {page}" + (f" | {article}" if article else "") + " ---"
        context_parts.append(f"{header_line}\n{doc.page_content}")
        
        sources.append({
            "file": src_file,
            "title": title,
            "short_title": short_title,
            "dept": dept,
            "page": page,
            "article": article,
            "snippet": doc.page_content.strip()
        })

    context_str = "\n\n".join(context_parts)
    formatted_prompt = chain.prompt.format(context=context_str, input=query)

    # 2. Gọi LLM có retry an toàn
    import time
    raw_answer = ""
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            response_obj = chain.llm.invoke(formatted_prompt)
            raw_answer = getattr(response_obj, "content", str(response_obj))
            if raw_answer:
                break
        except Exception as api_err:
            err_str = str(api_err)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                raw_answer = "Hệ thống tra cứu đang nhận lượng truy cập cao trong ngày từ sinh viên khiến hạn ngạch tạm thời bị chạm mốc. Bạn vui lòng đợi khoảng 1 phút rồi bấm hỏi lại nhé!"
                break
            elif any(code in err_str for code in ["503", "UNAVAILABLE"]) and attempt < max_attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise api_err

    return raw_answer, sources, len(docs)

def normalize_query_intent(query: str) -> str:
    """Chuẩn hóa câu hỏi của sinh viên về truy vấn chuẩn để tối đa hóa tỷ lệ trúng Response Cache (RAM)."""
    if not query:
        return ""
    
    q_clean = query.strip()
    q_lower = q_clean.lower()

    # 1. Nhóm học bổng khuyến khích: chứa "học bổng", "kkht", "khen thưởng" (và không có "vượt khó", "nghèo")
    if any(k in q_lower for k in ["học bổng", "kkht", "khen thưởng"]) and not any(k in q_lower for k in ["vượt khó", "nghèo"]):
        return "Tiêu chuẩn và điều kiện xét cấp học bổng khuyến khích học tập là gì?"

    # 2. Nhóm hoàn học phí: chứa "hoàn trả", "hoàn tiền", "học phí thừa", "rút tiền học phí"
    if any(k in q_lower for k in ["hoàn trả", "hoàn tiền", "học phí thừa", "rút tiền học phí"]):
        return "Quy trình làm thủ tục hoàn trả học phí thừa cho sinh viên gồm những bước nào?"

    # 3. Nhóm miễn giảm học phí: chứa "miễn giảm", "giảm học phí", "chính sách học phí"
    if any(k in q_lower for k in ["miễn giảm", "giảm học phí", "chính sách học phí"]):
        return "Đối tượng sinh viên nào được xét miễn giảm học phí theo quy định của trường?"

    # 4. Nhóm tín chỉ CTXH: chứa "công tác xã hội", "ctxh", "tín chỉ ctxh"
    if any(k in q_lower for k in ["công tác xã hội", "ctxh", "tín chỉ ctxh"]):
        return "Sinh viên cần hoàn thành bao nhiêu tín chỉ Công tác xã hội để đủ điều kiện xét tốt nghiệp?"

    # 5. Các câu hỏi khác: làm sạch dấu câu cuối câu và khoảng trắng thừa
    normalized = re.sub(r"[\?\.\,\!\;\:\_]+$", "", q_clean).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized if normalized else q_clean

# ==========================================
# 2. TINH GỌN LỜI CHÀO MỞ ĐẦU
# ==========================================
WELCOME_CONTENT = (
    "👋 **Xin chào! Mình là Lucas** – trợ lý hỗ trợ tra cứu Quy chế Đào tạo & Quy định sinh viên VLUTE.\n\n"
    "Bạn có thể chọn nhanh các câu hỏi bên dưới hoặc tra cứu về:\n\n"
    "🏆 **Học bổng** &nbsp;&nbsp;&nbsp; 💰 **Học phí** &nbsp;&nbsp;&nbsp; 🎓 **Đào tạo** &nbsp;&nbsp;&nbsp; ⚠️ **Học vụ**"
)

if "messages" not in st.session_state or len(st.session_state.messages) == 0:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": WELCOME_CONTENT,
            "sources": []
        }
    ]
elif len(st.session_state.messages) == 1 and st.session_state.messages[0]["role"] == "assistant":
    st.session_state.messages[0]["content"] = WELCOME_CONTENT

if "quick_prompt" not in st.session_state:
    st.session_state.quick_prompt = None

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
    """Hiển thị căn cứ quy chế trích dẫn gọn gàng trong st.expander, sạch ký tự rác."""
    if not sources_list:
        return
    
    grouped = {}
    for item in sources_list:
        file_name = item.get("file", "")
        doc_info = DOC_CATALOG.get(file_name, {})
        title = item.get("title") or doc_info.get("title", file_name)
        dept = item.get("dept") or doc_info.get("dept", "ĐH Công nghệ Kỹ thuật Vĩnh Long")
        
        if file_name not in grouped:
            grouped[file_name] = {
                "title": title,
                "dept": dept,
                "items": []
            }
        
        page = item.get("page", 1)
        article = item.get("article", "")
        snippet = clean_snippet_text(item.get("snippet", ""))
        
        key = f"{page}_{article}"
        if not any(f"{it.get('page')}_{it.get('article')}" == key for it in grouped[file_name]["items"]):
            grouped[file_name]["items"].append({
                "page": page,
                "article": article,
                "snippet": snippet
            })

    total_chunks = sum(len(g["items"]) for g in grouped.values())
    expander_label = f"📚 CĂN CỨ VĂN BẢN TRÍCH DẪN ({total_chunks} đoạn trích đối chiếu)"

    with st.expander(expander_label, expanded=False):
        for idx, (file_name, gdata) in enumerate(grouped.items(), 1):
            st.markdown(f"📄 **{gdata['title']}** — *({gdata['dept']})*")
            for sub in gdata["items"]:
                loc_parts = [f"Trang {sub['page']}"]
                if sub['article']:
                    clean_art = sub['article'].replace("*", "").replace("`", "").strip()
                    loc_parts.append(clean_art)
                loc_label = " - ".join(loc_parts)
                
                snippet_text = sub['snippet']
                if len(snippet_text) > 220:
                    snippet_text = snippet_text[:220] + "..."
                st.markdown(f"- 📍 **{loc_label}**: *\"{html.escape(snippet_text)}\"*")
            if idx < len(grouped):
                st.markdown("<hr style='margin: 8px 0; border-color: rgba(0, 0, 0, 0.1);'>", unsafe_allow_html=True)

# ==========================================
# PHÂN LOẠI CÂU HỎI VÀ ĐẦU MỐI LIÊN HỆ
# ==========================================
GREETING_KEYWORDS = ["chào", "hello", "hi", "bạn là ai", "tên gì", "giới thiệu", "alo", "lucas", "xin chào", "hey", "ad"]

def is_greeting(query: str) -> bool:
    """Nhận diện nhanh các câu chào hỏi xã giao."""
    clean = query.lower().strip()
    words = clean.split()
    duty_keywords = ["học bổng", "học phí", "tín chỉ", "cảnh báo", "điểm", "rút môn", "thôi học", "miễn giảm", "bảo hiểm", "quy chế", "điều"]
    if len(words) <= 4 and any(k in clean for k in GREETING_KEYWORDS):
        if not any(dk in clean for dk in duty_keywords):
            return True
    return False

def get_contact_footer(query: str, answer: str) -> str:
    """Tự động đính kèm thông tin liên hệ phòng ban thích hợp theo nghiệp vụ."""
    safe_query = str(query) if query is not None else ""
    safe_answer = str(answer) if answer is not None else ""
    combined = (safe_query + " " + safe_answer).lower()
    
    # 1. Nhóm Kế hoạch - Tài chính
    if any(k in combined for k in ["hoàn tiền", "hoàn trả học phí", "nộp tiền", "tài khoản ngân hàng", "biên lai", "học phí đóng trễ", "số tài khoản"]):
        return (
            "\n\n---\n"
            "📞 **Phòng Kế hoạch - Tài chính (VLUTE):**\n"
            "- Vị trí: Tòa nhà A (Tầng trệt)\n"
            "- Điện thoại: **(0270) 3822 141** | Email: **khtc@vlute.edu.vn**"
        )
    
    # 2. Nhóm Công tác Sinh viên
    if any(k in combined for k in ["học bổng", "miễn giảm", "chính sách", "bảo hiểm", "bhyt", "trợ cấp", "rèn luyện", "kỷ luật", "khen thưởng", "ký túc xá", "công tác xã hội", "vay vốn"]):
        return (
            "\n\n---\n"
            "📞 **Phòng Công tác Sinh viên (VLUTE):**\n"
            "- Vị trí: Tòa nhà A (Phòng A1.102 - Tầng trệt)\n"
            "- Điện thoại: **(0270) 3862 436** | Email: **ctsv@vlute.edu.vn**"
        )
    
    # 3. Nhóm Đào tạo
    if any(k in combined for k in ["tín chỉ", "học phần", "môn học", "rút môn", "cảnh báo", "thôi học", "điểm", "thang điểm", "thi", "lịch thi", "hoãn thi", "tốt nghiệp", "chứng chỉ", "chuẩn đầu ra"]):
        return (
            "\n\n---\n"
            "📞 **Phòng Đào tạo (VLUTE):**\n"
            "- Vị trí: Tòa nhà A (Phòng A1.101 - Tòa nhà Điều hành)\n"
            "- Điện thoại: **(0270) 3822 141** | Email: **daotao@vlute.edu.vn**"
        )
        
    return ""

# ==========================================
# HIỂN THỊ LỊCH SỬ TIN NHẮN
# ==========================================
for message in st.session_state.messages:
    if message["role"] == "user":
        safe_content = html.escape(message["content"]).replace("\n", "<br>")
        st.markdown(
            f'<div class="chat-row-user"><div class="user-bubble">{safe_content}</div></div>',
            unsafe_allow_html=True
        )
    else:
        with st.chat_message("assistant", avatar="lucas_avatar.png" if os.path.exists("lucas_avatar.png") else "🎓"):
            st.markdown(message["content"])
            if message.get("sources"):
                render_sources(message["sources"])
            if message.get("contact"):
                st.markdown(message["contact"])

# ==========================================
# KHỐI GỢI Ý CÂU HỎI NHANH
# ==========================================
st.markdown('<div class="quick-prompt-title">💡 Gợi ý câu hỏi nhanh từ văn bản quy chế:</div>', unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    if st.button("🏆 Tiêu chuẩn xét học bổng khuyến khích?", use_container_width=True, key="btn_hb"):
        st.session_state.quick_prompt = "Tiêu chuẩn và điều kiện xét cấp học bổng khuyến khích học tập là gì?"
        st.rerun()
    if st.button("💰 Quy trình hoàn trả học phí thừa?", use_container_width=True, key="btn_ht"):
        st.session_state.quick_prompt = "Quy trình làm thủ tục hoàn trả học phí thừa cho sinh viên gồm những bước nào?"
        st.rerun()
with col2:
    if st.button("🎁 Đối tượng được miễn giảm học phí?", use_container_width=True, key="btn_mg"):
        st.session_state.quick_prompt = "Đối tượng sinh viên nào được xét miễn giảm học phí theo quy định của trường?"
        st.rerun()
    if st.button("🤝 Quy định tích lũy tín chỉ CTXH?", use_container_width=True, key="btn_ctxh"):
        st.session_state.quick_prompt = "Sinh viên cần hoàn thành bao nhiêu tín chỉ Công tác xã hội để đủ điều kiện xét tốt nghiệp?"
        st.rerun()

# ==========================================
# 5. KHUNG NHẬP CÂU HỎI (INPUT PLACEHOLDER)
# ==========================================
user_input_from_chat = st.chat_input("Hỏi về quy chế đào tạo, học bổng, học phí, học vụ VLUTE...")

user_query = None
if user_input_from_chat:
    user_query = user_input_from_chat
elif st.session_state.quick_prompt:
    user_query = st.session_state.quick_prompt
    st.session_state.quick_prompt = None

if user_query:
    # 1. Lưu và hiển thị ngay câu hỏi của sinh viên
    st.session_state.messages.append({"role": "user", "content": user_query})
    safe_user_query = html.escape(user_query).replace("\n", "<br>")
    st.markdown(
        f'<div class="chat-row-user"><div class="user-bubble">{safe_user_query}</div></div>',
        unsafe_allow_html=True
    )

    # 2. Xử lý phản hồi từ Lucas
    with st.chat_message("assistant", avatar="lucas_avatar.png" if os.path.exists("lucas_avatar.png") else "🎓"):
        # TRƯỜNG HỢP 1: Chào hỏi xã giao -> Phản hồi tức thì, không lặp lại câu chào dài dòng
        if is_greeting(user_query):
            greeting_reply = (
                "Chào bạn! Mình có thể hỗ trợ bạn tra cứu quy chế nào hôm nay? "
                "*(Bạn có thể chọn các gợi ý nhanh ở trên hoặc gõ câu hỏi cụ thể nhé!)*"
            )
            st.markdown(greeting_reply)
            answer_to_save = greeting_reply
            contact_to_save = ""
            sources_to_save = []

        # TRƯỜNG HỢP 2: Kiểm tra chủ động ngoài phạm vi (Active Anti-Hallucination)
        elif check_out_of_scope(user_query):
            out_info = check_out_of_scope(user_query)
            refusal_reply = (
                f"Về nội dung **{out_info['topic']}**, hiện tại trong các văn bản quy chế đã nạp vào hệ thống chưa có quy định chi tiết.\n\n"
                f"ℹ️ *Gợi ý cho bạn:* {out_info['advice']}\n\n"
                f"💡 Để đảm bảo chuẩn xác, mình không tự suy đoán khi chưa có văn bản ban hành chính thức.\n\n"
                f"📞 Bạn vui lòng liên hệ trực tiếp **{out_info['dept_name']}** ({out_info['dept_contact']}) để được hỗ trợ chính xác nhất nhé!"
            )
            st.markdown(refusal_reply)
            answer_to_save = refusal_reply
            contact_to_save = ""
            sources_to_save = []

        # TRƯỜNG HỢP 3: Câu hỏi quy chế học vụ hợp lệ -> Kích hoạt Smart RAG + Stream an toàn
        else:
            status_placeholder = st.empty()
            status_placeholder.markdown(THINKING_HTML, unsafe_allow_html=True)

            try:
                canonical_query = normalize_query_intent(user_query)
                raw_text, sources_to_save, num_docs = execute_rag_pipeline(canonical_query)

                # Nếu gặp phản hồi hạn ngạch 429, xóa cache để lần hỏi sau thử lại API
                if raw_text and "hạn ngạch" in raw_text:
                    execute_rag_pipeline.clear()

                if not num_docs or not raw_text:
                    status_placeholder.empty()
                    no_doc_msg = (
                        "Hiện tại mình chưa tìm thấy thông tin phù hợp trong các văn bản quy chế để giải đáp câu hỏi này.\n\n"
                        "Để tránh cung cấp thông tin sai lệch, mình không tự suy đoán. "
                        "Bạn có thể thử đặt lại câu hỏi ngắn gọn hơn hoặc hỏi về các chủ đề: *học bổng, hoàn trả học phí, miễn giảm học phí, công tác xã hội, khen thưởng kỷ luật sinh viên* nhé!"
                    )
                    st.markdown(no_doc_msg)
                    answer_to_save = no_doc_msg
                    contact_to_save = ""
                    sources_to_save = []
                else:
                    if "hạn ngạch" not in raw_text:
                        status_placeholder.markdown(f"""
                        <div class="rag-status-badge">
                            <span>✓</span> <span>Đã đối soát thành công <b>{num_docs}</b> đoạn trích quy chế liên quan</span>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        status_placeholder.empty()

                    def word_generator(text):
                        words = text.split(" ")
                        for idx, w in enumerate(words):
                            yield w + (" " if idx < len(words) - 1 else "")
                            time.sleep(0.015)

                    full_answer = st.write_stream(word_generator(raw_text))
                    if not isinstance(full_answer, str):
                        full_answer = str(full_answer)
                    answer_to_save = full_answer

                    # 1. Hiển thị căn cứ quy chế trích dẫn ngay dưới câu trả lời
                    if sources_to_save and "hạn ngạch" not in raw_text:
                        render_sources(sources_to_save)

                    # 2. Hiển thị thông tin liên hệ phòng ban ở cuối cùng
                    contact_footer = get_contact_footer(user_query, full_answer)
                    if contact_footer and "hạn ngạch" not in raw_text:
                        st.markdown(contact_footer)
                        contact_to_save = contact_footer
                    else:
                        contact_to_save = ""

            except Exception as rag_err:
                status_placeholder.empty()
                err_msg = f"⚠️ Đã xảy ra lỗi trong quá trình xử lý câu hỏi: {rag_err}. Vui lòng thử lại sau ít phút."
                st.error(err_msg)
                answer_to_save = err_msg
                contact_to_save = ""
                sources_to_save = []

    # 3. Lưu câu trả lời cùng trích dẫn vào lịch sử
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer_to_save,
        "contact": contact_to_save,
        "sources": sources_to_save
    })
    st.rerun()

# ==========================================
# 6. TỰ ĐỘNG LÀM ẤM BỘ NHỚ ĐỆM (CACHE PRE-WARMING)
# ==========================================
def _prewarm_cache_background():
    """Khởi chạy ngầm nạp sẵn câu trả lời cho 4 câu hỏi gợi ý phổ biến vào RAM (@st.cache_data)."""
    suggested_queries = [
        "Tiêu chuẩn và điều kiện xét cấp học bổng khuyến khích học tập là gì?",
        "Quy trình làm thủ tục hoàn trả học phí thừa cho sinh viên gồm những bước nào?",
        "Đối tượng sinh viên nào được xét miễn giảm học phí theo quy định của trường?",
        "Sinh viên cần hoàn thành bao nhiêu tín chỉ Công tác xã hội để đủ điều kiện xét tốt nghiệp?"
    ]
    for q in suggested_queries:
        try:
            execute_rag_pipeline(q)
        except Exception:
            pass

try:
    import threading
    if "_cache_prewarmed" not in st.session_state:
        st.session_state["_cache_prewarmed"] = True
        try:
            from streamlit.runtime.scriptrunner import add_script_run_ctx
        except Exception:
            add_script_run_ctx = None

        _prewarm_thread = threading.Thread(target=_prewarm_cache_background, daemon=True)
        if add_script_run_ctx:
            try:
                add_script_run_ctx(_prewarm_thread)
            except Exception:
                pass
        _prewarm_thread.start()
except Exception:
    pass