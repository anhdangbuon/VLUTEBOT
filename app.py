import os
import html
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
BOT_AVATAR = "🎓"

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
# 1. Khung xanh bự: Logo nằm bên TRÁI, chữ CANH GIỮA HOÀN HẢO
# 2. 3 framework / thẻ điều hướng CANH GIỮA ĐẸP MẮT
# 3. Nút kéo ra kéo vô chuyển thành biểu tượng 3 GẠCH (☰) như Ảnh 3
# 4. Sidebar framework mang màu DARK CHARCOAL (#222d32) chuẩn Ảnh 3 với LOGO CANH GIỮA
# 5. Khung chat Lucas (xanh lá VLUTE) & Sinh viên (xanh dương), bo tròn 24px cả 4 góc
# ==========================================
st.markdown("""
<style>
/* 0. Nền chung toàn trang */
.stApp {
    background-color: #f4f6f9 !important;
    color: #1e293b !important;
}

/* 1. Header phong cách Cổng thông tin điện tử VLUTE */
.vlute-portal-header {
    background: linear-gradient(135deg, #005a30 0%, #00733c 100%);
    border-radius: 14px;
    padding: 18px 24px;
    margin-bottom: 14px;
    color: white;
    box-shadow: 0 4px 16px rgba(0, 104, 55, 0.28);
    border-bottom: 4px solid #00a65a;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

/* Logo nằm bên TRÁI */
.header-logo-left {
    width: 82px;
    display: flex;
    justify-content: flex-start;
    align-items: center;
    flex-shrink: 0;
}

.vlute-logo-img {
    width: 78px;
    height: 78px;
    object-fit: contain;
    filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.35));
    transition: transform 0.3s ease;
}

.vlute-logo-img:hover {
    transform: scale(1.05);
}

/* Chữ nằm chính GIỮA HOÀN HẢO */
.header-center-text {
    flex: 1;
    min-width: 0;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 10px;
}

.vlute-brand-top {
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #a7f3d0;
    margin-bottom: 4px;
    text-align: center;
    word-break: keep-all;
    white-space: normal;
}

.vlute-portal-title {
    font-size: 1.35rem;
    font-weight: 800;
    margin: 0;
    color: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    letter-spacing: 0.3px;
    text-align: center;
    word-break: keep-all;
    white-space: normal;
}

.vlute-portal-subtitle {
    font-size: 0.92rem;
    color: #ecfdf5;
    margin-top: 4px;
    margin-bottom: 0px;
    font-weight: 600;
    text-align: center;
    word-break: keep-all;
    white-space: normal;
}

/* Khoảng trống bên phải để cân bằng đối xứng, giữ chữ nằm chính giữa 100% */
.header-right-spacer {
    width: 82px;
    flex-shrink: 0;
}

/* 2. Thanh 3 framework điều hướng nhanh CANH GIỮA MÀN HÌNH */
.vlute-nav-ribbon {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    justify-content: center; /* Nằm ngay chính giữa theo yêu cầu */
    align-items: center;
    width: 100%;
}

.vlute-nav-badge {
    background-color: #008d4c;
    color: white;
    font-size: 0.84rem;
    font-weight: 600;
    padding: 7px 16px;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    box-shadow: 0 2px 6px rgba(0, 141, 76, 0.2);
    transition: all 0.2s ease;
}

.vlute-nav-badge:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
}

.vlute-nav-badge.student {
    background-color: #0073b7;
    box-shadow: 0 2px 6px rgba(0, 115, 183, 0.2);
}

.vlute-nav-badge.general {
    background-color: #e67e22;
    box-shadow: 0 2px 6px rgba(230, 126, 34, 0.2);
}

/* Hộp thông báo nhắc nhở màu vàng kem CANH GIỮA */
.vlute-alert-box {
    background-color: #fffbe6;
    border: 1px solid #ffe58f;
    border-radius: 8px;
    padding: 11px 18px;
    color: #873800;
    font-size: 0.88rem;
    margin-bottom: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 10px;
    box-shadow: 0 2px 6px rgba(250, 173, 20, 0.08);
}

/* 3. NÚT KÉO RA KÉO VÔ CHUYỂN THÀNH ICON 3 GẠCH (☰) NHƯ ẢNH 3 & TRIỆT TIÊU TOÀN BỘ MŨI TÊN (>>) */
/* 3.1. Ẩn triệt để tất cả biểu tượng mũi tên đôi chevron (>> / <<) trên mọi phiên bản Streamlit */
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

/* 3.2. Khi sidebar đang THU VÀO (Collapsed) - Nút mở nằm ở góc trên bên trái màn hình */
button[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: #ffffff !important;
    border: 1px solid #d2d6de !important;
    border-radius: 6px !important;
    width: 38px !important;
    height: 38px !important;
    min-width: 38px !important;
    min-height: 38px !important;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08) !important;
    cursor: pointer !important;
    margin: 6px 0 0 8px !important;
    padding: 0 !important;
    transition: all 0.25s ease !important;
    font-size: 0 !important;
    color: transparent !important;
}

button[data-testid="stExpandSidebarButton"]:hover,
[data-testid="stExpandSidebarButton"]:hover,
[data-testid="collapsedControl"]:hover {
    background-color: #f0f7f3 !important;
    border-color: #008d4c !important;
    transform: scale(1.05) !important;
    box-shadow: 0 4px 12px rgba(0, 141, 76, 0.25) !important;
}

/* Hiện 3 gạch (☰) màu đen xám chuẩn cổng đào tạo Ảnh 3 */
button[data-testid="stExpandSidebarButton"]::before,
[data-testid="stExpandSidebarButton"]::before,
[data-testid="collapsedControl"]::before {
    content: "☰" !important;
    font-size: 22px !important;
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
    transition: color 0.2s ease !important;
}

button[data-testid="stExpandSidebarButton"]:hover::before,
[data-testid="stExpandSidebarButton"]:hover::before,
[data-testid="collapsedControl"]:hover::before {
    color: #008d4c !important;
}

/* 3.3. Khi sidebar đang MỞ - Khung đen bự bao bọc cả chữ BẢNG ĐIỀU KHIỂN HỌC VỤ và nút 3 gạch (☰) */
[data-testid="stSidebarHeader"] {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    padding: 10px 18px !important; /* Mở rộng padding để bao bọc cả 3 sọc nằm gọn gàng bên trong */
    background: #141a1d !important; /* Khung đen tối sang trọng */
    border: 1px solid #2b3b42 !important; /* Viền khung rõ ràng */
    border-radius: 8px !important; /* Bo góc mềm mại cho khung đen */
    min-height: 50px !important; /* Khung bự thoải mái */
    width: 100% !important;
    box-sizing: border-box !important;
    margin-bottom: 12px !important;
    margin-top: 4px !important;
    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.3) !important;
}

[data-testid="stSidebarHeader"]::before {
    content: "BẢNG ĐIỀU KHIỂN HỌC VỤ" !important; /* Đã xóa bánh răng theo yêu cầu */
    font-size: 0.82rem !important;
    font-weight: 700 !important;
    color: #b8c7ce !important;
    letter-spacing: 0.8px !important;
    text-transform: uppercase !important;
    white-space: nowrap !important;
    display: inline-flex !important;
    align-items: center !important;
    margin-right: auto !important;
}

[data-testid="stLogoSpacer"] {
    display: none !important;
}

[data-testid="stSidebarCollapseButton"] {
    display: inline-flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    align-items: center !important;
    justify-content: center !important;
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
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    min-height: 32px !important;
    cursor: pointer !important;
    padding: 0 !important;
    transition: all 0.25s ease !important;
    font-size: 0 !important;
    color: transparent !important;
}

[data-testid="stSidebarCollapseButton"] button:hover,
button[data-testid="stSidebarCollapseButton"]:hover,
[data-testid="stSidebarHeader"] button:hover {
    background-color: rgba(0, 166, 90, 0.25) !important;
    border-color: #00a65a !important;
    transform: scale(1.05) !important;
}

/* Hiện 3 gạch (☰) màu sáng rõ nét bên trong framework sidebar */
[data-testid="stSidebarCollapseButton"] button::before,
button[data-testid="stSidebarCollapseButton"]::before,
[data-testid="stSidebarHeader"] button::before {
    content: "☰" !important;
    font-size: 20px !important;
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
    transition: color 0.2s ease !important;
}

[data-testid="stSidebarCollapseButton"] button:hover::before,
button[data-testid="stSidebarCollapseButton"]:hover::before,
[data-testid="stSidebarHeader"] button:hover::before {
    color: #00a65a !important;
}

/* 4. SIDEBAR FRAMEWORK MANG MÀU DARK CHARCOAL (#222d32) CHUẨN ẢNH 3 & HOẠT ẢNH TRƯỢT KÉO MƯỢT MÀ */
section[data-testid="stSidebar"] {
    background-color: #222d32 !important; /* Màu dark charcoal chuẩn web Quản lý đào tạo VLUTE (Ảnh 3) */
    border-right: 1px solid #1a2226 !important;
    color: #b8c7ce !important;
    transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), 
                width 0.4s cubic-bezier(0.16, 1, 0.3, 1), 
                min-width 0.4s cubic-bezier(0.16, 1, 0.3, 1),
                box-shadow 0.4s ease !important;
    box-shadow: 4px 0 28px rgba(0, 0, 0, 0.35) !important;
}

/* Hoạt ảnh trượt kéo ra toàn bộ nội dung trong framework */
@keyframes frameworkSlideOut {
    0% {
        opacity: 0;
        transform: translateX(-24px);
    }
    100% {
        opacity: 1;
        transform: translateX(0);
    }
}

[data-testid="stSidebarUserContent"] {
    animation: frameworkSlideOut 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards !important;
}

section[data-testid="stSidebar"] * {
    color: #b8c7ce !important;
}

section[data-testid="stSidebar"] h1, 
section[data-testid="stSidebar"] h2, 
section[data-testid="stSidebar"] h3, 
section[data-testid="stSidebar"] strong {
    color: #ffffff !important;
}

section[data-testid="stSidebar"] hr {
    border-color: #374850 !important;
    margin: 12px 0 !important;
}

/* Khối liên hệ trong sidebar theo phong cách thẻ card tối có hiệu ứng trượt nở khi hover */
.sidebar-contact-card {
    background-color: #1e282c;
    border: 1px solid #374850;
    border-radius: 8px;
    padding: 14px;
    margin-top: 10px;
    color: #b8c7ce;
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.sidebar-contact-card:hover {
    transform: translateY(-2px) scale(1.015) !important;
    border-color: #00a65a !important;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4) !important;
}

.sidebar-contact-card code {
    background-color: #141b1e !important;
    color: #a7f3d0 !important;
    border: 1px solid #2b3b42 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-size: 0.85rem !important;
}

/* Khối liên kết Dịch vụ tiện ích & Truy cập nhanh */
.sidebar-links-card {
    background-color: #1e282c;
    border: 1px solid #374850;
    border-radius: 8px;
    padding: 12px 14px;
    margin-top: 10px;
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.sidebar-links-card:hover {
    border-color: #00a65a !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35) !important;
}

.sidebar-section-title {
    font-size: 0.8rem;
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
    gap: 6px;
    background: #141b1e;
    border: 1px solid #2b3b42;
    border-radius: 6px;
    padding: 7px 8px;
    font-size: 0.76rem;
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
    box-shadow: 0 2px 8px rgba(0, 166, 90, 0.35);
}

/* Nút bấm ở sidebar có hiệu ứng nhấc nổi khi hover */
section[data-testid="stSidebar"] .stButton > button {
    border-radius: 8px !important;
    border: none !important;
    background-color: #00a65a !important; /* Xanh lá tươi cổng đào tạo */
    color: white !important;
    font-weight: 700 !important;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
    box-shadow: 0 2px 6px rgba(0, 166, 90, 0.3) !important;
}

section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #008d4c !important;
    color: white !important;
    box-shadow: 0 4px 10px rgba(0, 166, 90, 0.45) !important;
}

/* 5. Cấu trúc hàng tin nhắn Chatbot (Assistant) */
div[data-testid="stChatMessage"] {
    display: flex !important;
    align-items: flex-start !important;
    margin-bottom: 1.3rem !important;
    gap: 16px !important;
    width: 100% !important;
    background: transparent !important;
    padding: 0 !important;
}

div[data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) {
    flex-direction: row !important;
    justify-content: flex-start !important;
}

/* Avatar Trợ lý Lucas - Hình tròn hoàn hảo, màu xanh lá VLUTE */
div[data-testid="stChatMessageAvatar"] {
    flex-shrink: 0 !important;
    width: 40px !important;
    height: 40px !important;
    min-width: 40px !important;
    min-height: 40px !important;
    margin-top: 2px !important;
    margin-right: 0px !important;
    margin-left: 0px !important;
    border-radius: 50% !important;
    background-color: #00703c !important;
    border: 2px solid #004d28 !important;
    box-shadow: 0 3px 8px rgba(0, 112, 60, 0.3) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    overflow: hidden !important;
}

div[data-testid="stChatMessageAvatar"] div,
div[data-testid="stChatMessageAvatar"] span,
div[data-testid="stChatMessageAvatar"] svg,
div[data-testid="stChatMessageAvatar"] img {
    border-radius: 50% !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}

div[data-testid="stChatMessageAvatar"] span {
    font-size: 20px !important;
    line-height: 1 !important;
}

/* Khung tin nhắn của Lucas - Framework màu XANH LÁ VLUTE, bo tròn 24px cả 4 góc */
div[data-testid="stChatMessageContent"] {
    background-color: #00703c !important;
    border: 2px solid #00502b !important;
    border-radius: 24px !important;
    padding: 14px 22px !important;
    max-width: 84% !important;
    width: fit-content !important;
    color: #ffffff !important;
    box-sizing: border-box !important;
    line-height: 1.65 !important;
    margin-left: 0px !important;
    box-shadow: 0 4px 14px rgba(0, 112, 60, 0.2) !important;
    word-break: normal !important;
    overflow-wrap: break-word !important;
}

div[data-testid="stChatMessageContent"] ul {
    margin: 8px 0 8px 0 !important;
    padding-left: 22px !important;
}

div[data-testid="stChatMessageContent"] li {
    margin-bottom: 7px !important;
    line-height: 1.6 !important;
    word-break: normal !important;
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

/* 6. Khung tin nhắn Sinh viên (User) - Màu XANH DƯƠNG SINH VIÊN (Ảnh 3), bo tròn 24px */
.chat-row-user {
    display: flex;
    justify-content: flex-end;
    width: 100%;
    margin-bottom: 1.3rem;
    box-sizing: border-box;
    padding-left: 56px; 
}

.user-bubble {
    background-color: #0073b7 !important;
    border: 2px solid #005587 !important;
    color: #ffffff !important;
    border-radius: 24px !important;
    padding: 12px 22px !important;
    max-width: 84%;
    width: fit-content;
    word-break: normal !important;
    overflow-wrap: break-word !important;
    font-size: 1rem !important;
    line-height: 1.6 !important;
    box-shadow: 0 4px 14px rgba(0, 115, 183, 0.2) !important;
}

/* Khoảng cách đoạn văn bên trong khung chat */
div[data-testid="stChatMessageContent"] p, .user-bubble p {
    margin-bottom: 0.5rem !important;
}
div[data-testid="stChatMessageContent"] p:last-child, .user-bubble p:last-child {
    margin-bottom: 0px !important;
}

/* Tùy biến hộp căn cứ trích dẫn expander trên nền sáng */
div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] {
    background: #f0fdf4 !important;
    border: 1.5px solid #86efac !important;
    border-radius: 14px !important;
    margin-top: 12px !important;
    color: #14532d !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] summary {
    color: #166534 !important;
    font-weight: 600 !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] * {
    color: #166534 !important;
}

div[data-testid="stChatMessageContent"] div[data-testid="stExpander"] code {
    background-color: #dcfce7 !important;
    color: #15803d !important;
    font-weight: 600 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
}

/* 7. Animation Bánh răng kỹ thuật VLUTE */
.thinking-track {
    width: 100% !important;
    min-width: 320px;
    height: 38px;
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
    font-size: 24px;
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
    font-size: 18px;
    margin-left: -5px;
    margin-top: -7px;
    animation: rotateGearSub 3.5s ease-in-out infinite alternate;
    transform-origin: center;
}

.thinking-label {
    font-size: 13.5px;
    color: #ecfdf5;
    font-style: italic;
    font-weight: 500;
    margin-left: 10px;
    white-space: nowrap;
}

@keyframes rollAcrossFull {
    0% {
        transform: translateX(0px);
    }
    100% {
        transform: translateX(calc(100% - 240px));
    }
}

@keyframes rotateGearMain {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(720deg); }
}

@keyframes rotateGearSub {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(-720deg); }
}

/* 8. Nút bấm câu hỏi gợi ý nhanh (Quick Suggestions) */
.quick-prompt-title {
    font-size: 0.9rem;
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
    border-radius: 20px !important;
    font-size: 0.86rem !important;
    font-weight: 600 !important;
    padding: 7px 14px !important;
    text-align: left !important;
    box-shadow: 0 2px 5px rgba(0, 112, 60, 0.08) !important;
    transition: all 0.2s ease !important;
    white-space: normal !important;
    height: auto !important;
}

div[data-testid="stHorizontalBlock"] button:hover {
    background-color: #00703c !important;
    color: #ffffff !important;
    box-shadow: 0 4px 10px rgba(0, 112, 60, 0.25) !important;
    transform: translateY(-1px);
}

/* Khung chat input */
div[data-testid="stChatInput"] {
    border-radius: 12px !important;
}

div[data-testid="stChatInput"] textarea:focus {
    border-color: #00703c !important;
}

/* Tương thích di động */
@media (max-width: 640px) {
    .header-right-spacer { display: none; }
    .vlute-logo-img { width: 56px; height: 56px; }
    .vlute-portal-title { font-size: 1.05rem !important; }
    .chat-row-user { padding-left: 16px !important; }
    div[data-testid="stChatMessageContent"], .user-bubble { max-width: 92% !important; }
}
/* Ẩn hoàn toàn wrapper của iframe chạy script nền */
iframe[height="0"], div:has(> iframe[height="0"]) {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* 9. Thẻ căn cứ văn bản quy chế chính thức (RAG Source Cards) */
.rag-sources-wrap {
    margin-top: 14px;
    padding-top: 10px;
    border-top: 1px dashed rgba(255, 255, 255, 0.3);
}

.rag-sources-header {
    font-size: 0.86rem;
    font-weight: 700;
    color: #a7f3d0;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.rag-source-card {
    background: #ffffff !important;
    border-radius: 10px;
    padding: 10px 14px;
    margin-bottom: 8px;
    border-left: 4px solid #00a65a;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    color: #1e293b !important;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.rag-source-card:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}

.rag-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 4px;
}

.rag-card-title {
    font-weight: 700;
    font-size: 0.88rem;
    color: #005a30 !important;
    line-height: 1.35;
    flex: 1;
}

.rag-card-badge {
    background: #ecfdf5 !important;
    color: #00703c !important;
    border: 1px solid #a7f3d0;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.74rem;
    font-weight: 700;
    white-space: nowrap;
    flex-shrink: 0;
}

.rag-card-meta {
    font-size: 0.78rem;
    color: #475569 !important;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 6px;
    align-items: center;
}

.rag-card-meta b {
    color: #1e293b !important;
}

.rag-card-excerpt {
    font-size: 0.8rem;
    color: #334155 !important;
    background: #f8fafc;
    border-radius: 6px;
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
    line-height: 1.45;
}

/* Badge trạng thái RAG */
.rag-status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #ecfdf5;
    border: 1px solid #6ee7b7;
    color: #047857;
    font-size: 0.82rem;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 20px;
    margin-bottom: 10px;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# HOẠT ẢNH RÊ CHUỘT VÀO FRAMEWORK TỰ ĐỘNG KÉO RA HẾT
# ==========================================
st.components.v1.html("""
<script>
(function() {
    function setupHoverExpand() {
        try {
            const pDoc = window.parent.document;
            if (!pDoc) return;
            
            // Nút 3 gạch bên ngoài: Rê chuột vào là tự động kéo mở toàn bộ framework ra hết
            const expandBtn = pDoc.querySelector('button[data-testid="stExpandSidebarButton"]');
            if (expandBtn && !expandBtn.dataset.hoverBound) {
                expandBtn.dataset.hoverBound = "true";
                expandBtn.addEventListener('mouseenter', function() {
                    expandBtn.click();
                });
            }
        } catch(e) {}
    }
    setupHoverExpand();
    setInterval(setupHoverExpand, 400);
})();
</script>
""", height=0, width=0)

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
# BANNER TIÊU ĐỀ: LOGO BÊN TRÁI + CHỮ CANH GIỮA HOÀN HẢO
# ==========================================
logo_html_img = f'<img src="data:image/png;base64,{LOGO_B64}" class="vlute-logo-img" alt="Logo VLUTE" />' if LOGO_B64 else '<span style="font-size:38px;">🎓</span>'

st.markdown(f"""
<div class="vlute-portal-header">
    <div class="header-logo-left">
        {logo_html_img}
    </div>
    <div class="header-center-text">
        <div class="vlute-brand-top">
            VINH LONG UNIVERSITY OF TECHNOLOGY AND ENGINEERING (VLUTE)
        </div>
        <div class="vlute-portal-title">
            <span>🎓 LUCAS – TRỢ LÝ QUY CHẾ & HỌC VỤ</span>
        </div>
        <div class="vlute-portal-subtitle">
            <span style="white-space: nowrap;">Trường Đại học Công nghệ Kỹ thuật Vĩnh Long</span>
        </div>
        <div style="font-size: 0.8rem; color: #a7f3d0; margin-top: 2px; font-style: italic;">
            (Tiền thân: Trường Đại học Sư phạm Kỹ thuật Vĩnh Long)
        </div>
        <div style="font-size: 0.84rem; color: #ecfdf5; margin-top: 3px; font-weight: 400; word-break: keep-all;">
            <span style="white-space: nowrap;">Hệ thống tra cứu Quy chế Đào tạo</span> & <span style="white-space: nowrap;">Học vụ Sinh viên</span>
        </div>
    </div>
    <div class="header-right-spacer"></div>
</div>

<div class="vlute-nav-ribbon">
    <div class="vlute-nav-badge">
        <span>🟢 Tra cứu học vụ</span>
    </div>
    <div class="vlute-nav-badge general">
        <span>🟠 Quy chế chính thức</span>
    </div>
    <div class="vlute-nav-badge student">
        <span>🔵 Hỗ trợ 24/7</span>
    </div>
</div>

<div class="vlute-alert-box">
    <span>💡</span>
    <div style="line-height: 1.5; word-break: keep-all;">
        <strong>Góc hỗ trợ học vụ:</strong> Thông tin tra cứu trực tiếp từ các văn bản quy chế của <span style="white-space: nowrap;"><b>Trường ĐH Công nghệ Kỹ thuật Vĩnh Long</b></span> <i>(tiền thân Trường ĐH SPKT Vĩnh Long)</i>.
    </div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# SIDEBAR: THEO PHONG CÁCH QUẢN LÝ ĐÀO TẠO VLUTE (ẢNH 3)
# ==========================================
with st.sidebar:
    # Logo VLUTE nằm CHÍNH GIỮA ở đầu sidebar (Ảnh 2)
    if LOGO_B64:
        st.markdown(f"""
        <div style="display: flex; justify-content: center; align-items: center; width: 100%; margin-bottom: 10px; margin-top: 2px;">
            <img src="data:image/png;base64,{LOGO_B64}" style="width: 105px; height: 105px; object-fit: contain; filter: drop-shadow(0 4px 10px rgba(0,0,0,0.5));" alt="Logo VLUTE" />
        </div>
        <div style="text-align: center; color: #ffffff; font-weight: 800; font-size: 0.95rem; letter-spacing: 0.3px; margin-bottom: 4px; line-height: 1.35;">
            TRƯỜNG ĐẠI HỌC<br><span style="white-space: nowrap; color: #ffffff;">CNKT VĨNH LONG</span>
        </div>
        <div style="text-align: center; color: #00a65a; font-weight: 700; font-size: 0.78rem; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 10px;">
            QUẢN LÝ ĐÀO TẠO & HỌC VỤ
        </div>
        """, unsafe_allow_html=True)
    
    # Địa chỉ cập nhật theo thông tin chính thức mới nhất
    st.markdown("""
    <div style="text-align: center; color: #cbd5e1; font-size: 0.76rem; margin-bottom: 14px; padding: 7px 10px; background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; line-height: 1.45; word-break: keep-all;">
        <span>📍</span> <span>Số 73 Nguyễn Huệ, Phường Long Châu, Tỉnh Vĩnh Long</span>
    </div>
    """, unsafe_allow_html=True)
    
    # Khối thông tin liên hệ phòng ban phong cách dark slate
    st.markdown("""
    <div class="sidebar-contact-card">
        <div style="font-weight: 700; color: #ffffff; margin-bottom: 8px; font-size: 0.9rem;">
            📞 ĐẦU MỐI LIÊN HỆ PHÒNG BAN:
        </div>
        <div style="margin-bottom: 8px;">
            <b style="color: #a7f3d0;">• Phòng Đào tạo (A1.101):</b><br>
            ☎️ <code>(0270) 3822 141</code><br>
            ✉️ <i>daotao@vlute.edu.vn</i>
        </div>
        <div style="margin-bottom: 8px;">
            <b style="color: #a7f3d0;">• Phòng Công tác SV (A1.102):</b><br>
            ☎️ <code>(0270) 3862 436</code><br>
            ✉️ <i>ctsv@vlute.edu.vn</i>
        </div>
        <div style="margin-bottom: 8px;">
            <b style="color: #a7f3d0;">• Phòng Kế hoạch - Tài chính:</b><br>
            ☎️ <code>(0270) 3822 141</code><br>
            ✉️ <i>khtc@vlute.edu.vn</i>
        </div>
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #374850; font-size: 0.78rem;">
            🌐 <b>Website:</b> <a href="https://vlute.edu.vn" target="_blank" style="color: #a7f3d0; text-decoration: none;">vlute.edu.vn</a><br>
            ✉️ <b>Email chung:</b> <i>spktvl@vlute.edu.vn</i>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Khối Dịch vụ tiện ích & Truy cập nhanh viết không thụt lề để triệt tiêu lỗi hiển thị code thô
    SIDEBAR_NAV_HTML = """<div class="sidebar-links-card">
<div class="sidebar-section-title">⚡ DỊCH VỤ TIỆN ÍCH</div>
<div class="sidebar-link-grid">
<a href="https://vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Cổng thông tin My VLUTE">🌐 My VLUTE</a>
<a href="https://tuyensinh.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Thông tin tuyển sinh">🎯 Tuyển sinh</a>
<a href="http://cgtdt-dsa.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Công tác sinh viên">👥 Phòng CTSV</a>
<a href="http://pdt.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Phòng Đào tạo">📋 Phòng ĐT</a>
</div>
<div class="sidebar-section-title" style="margin-top: 12px;">🚀 TRUY CẬP NHANH</div>
<div class="sidebar-link-grid">
<a href="https://daotao.vlute.edu.vn/sinh-vien" target="_blank" class="sidebar-link-item" title="Đăng ký học phần">📝 ĐK Học phần</a>
<a href="https://htql.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Hệ thống quản lý">🖥️ Hệ thống QL</a>
<a href="http://elearning.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Học trực tuyến E-Learning">💻 E-Learning</a>
<a href="https://thanhtoan.vlute.edu.vn/" target="_blank" class="sidebar-link-item" title="Cổng thanh toán Trực tuyến">💳 Thanh toán</a>
</div>
</div>
<div style="margin-top: 12px; padding: 10px 12px; background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; font-size: 0.74rem; color: #94a3b8; text-align: center; line-height: 1.5;">
<div style="color: #cbd5e1; font-weight: 700;">© Trường ĐH Công nghệ Kỹ thuật Vĩnh Long</div>
<div style="font-size: 0.68rem; color: #a7f3d0; margin-top: 2px;">(Tiền thân: Trường ĐH Sư phạm Kỹ thuật Vĩnh Long)</div>
<div style="font-size: 0.68rem; color: #64748b; margin-top: 2px;">Vinh Long University of Technology and Engineering (VLUTE)</div>
<div style="margin-top: 5px; color: #94a3b8; font-size: 0.72rem;">☎️ 0270 3822 141 &nbsp;|&nbsp; 📠 Fax: 02703 821 003</div>
</div>"""
    st.markdown(SIDEBAR_NAV_HTML, unsafe_allow_html=True)
    
    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    if st.button("🗑️ Làm mới cuộc trò chuyện", use_container_width=True):
        st.session_state.messages = []
        st.session_state.quick_prompt = None
        st.rerun()

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

# Khởi tạo tin nhắn chào ban đầu
WELCOME_CONTENT = (
    "👋 **Xin chào! Mình là Lucas** – Trợ lý ảo hỗ trợ tra cứu Quy chế Đào tạo & Quy định Sinh viên của **Trường Đại học Công nghệ Kỹ thuật Vĩnh Long** (VLUTE - *tiền thân là Trường ĐH Sư phạm Kỹ thuật Vĩnh Long*).\n\n"
    "📚 Mình giải đáp dựa trên các văn bản quy định chính thức của Nhà trường và luôn kèm theo căn cứ điều khoản để bạn dễ dàng đối chiếu.\n\n"
    "💡 **Bạn có thể hỏi mình về:**\n\n"
    "- 🏆 **Học bổng:** Tiêu chuẩn xét học bổng khuyến khích *(QĐ 201)*\n"
    "- 💰 **Học phí:** Quy trình hoàn trả học phí thừa *(QT-SV-04)* & Miễn giảm học phí *(QĐ 904)*\n"
    "- 🤝 **Công tác xã hội:** Tích lũy tín chỉ CTXH xét tốt nghiệp *(QĐ 55)*\n"
    "- 📋 **Quy chế sinh viên:** Quyền lợi, nghĩa vụ, khen thưởng & kỷ luật *(QĐ 1079)*"
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

# Biến lưu trữ câu hỏi từ nút bấm gợi ý
if "quick_prompt" not in st.session_state:
    st.session_state.quick_prompt = None

def clean_snippet_text(text: str) -> str:
    """Làm sạch đoạn trích quy chế, loại bỏ các ký tự rác, dấu sao, lỗi chính tả từ quét PDF."""
    if not text:
        return ""
    # 1. Bỏ các ký tự đặc biệt, dấu chấm, phẩy, sao, ngoặc kép vô nghĩa ở đầu
    cleaned = re.sub(r"^[\s\.\,\;\"\'\:\-\_\|\*\#\`\(\)]+", "", text)
    # 2. Bỏ các cụm chữ hoa quét PDF lỗi bảng như 'BI UNG HOC PHAN THU NH LON, 8 x'
    cleaned = re.sub(r"^[A-Z0-9\s]{4,35}[\,\.\:\;]\s*", "", cleaned)
    # 3. Chuẩn hóa khoảng trắng
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def render_sources(sources_list):
    """Hiển thị căn cứ quy chế trích dẫn thu gọn trong st.expander sạch đẹp, không lỗi markdown."""
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
    expander_label = f"📌 Xem căn cứ văn bản & trích dẫn quy chế ({total_chunks} đoạn trích)"

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
                if len(snippet_text) > 200:
                    snippet_text = snippet_text[:200] + "..."
                st.markdown(f"- 📍 **{loc_label}**: *\"{html.escape(snippet_text)}\"*")
            if idx < len(grouped):
                st.markdown("<hr style='margin: 8px 0; border-color: rgba(0, 112, 60, 0.2);'>", unsafe_allow_html=True)

# ==========================================
# PHÂN LOẠI CÂU HỎI VÀ TẠO FOOTER LIÊN HỆ PHÒNG BAN
# ==========================================
GREETING_KEYWORDS = ["chào", "hello", "hi", "bạn là ai", "tên gì", "giới thiệu", "alo", "lucas", "xin chào", "hey", "ad"]

def is_greeting(query: str) -> bool:
    """Nhận diện nhanh các câu chào hỏi xã giao để phản hồi tức thì mà không cần chạy RAG."""
    clean = query.lower().strip()
    words = clean.split()
    duty_keywords = ["học bổng", "học phí", "tín chỉ", "cảnh báo", "điểm", "rút môn", "thôi học", "miễn giảm", "bảo hiểm"]
    if len(words) <= 4 and any(k in clean for k in GREETING_KEYWORDS):
        if not any(dk in clean for dk in duty_keywords):
            return True
    return False

def get_contact_footer(query: str, answer: str) -> str:
    """Tự động đính kèm thông tin liên hệ phòng ban thích hợp theo nghiệp vụ."""
    combined = (query + " " + answer).lower()
    
    # 1. Nhóm Kế hoạch - Tài chính (thuần về đóng tiền, tài khoản, hoàn tiền)
    if any(k in combined for k in ["hoàn tiền", "hoàn trả học phí", "nộp tiền", "tài khoản ngân hàng", "biên lai", "học phí đóng trễ", "số tài khoản"]):
        return (
            "\n\n---\n"
            "📞 **Phòng Kế hoạch - Tài chính (VLUTE):**\n"
            "- Vị trí: Tòa nhà A (Tầng trệt)\n"
            "- Điện thoại: **(0270) 3822 141** *(bấm số nội bộ kế toán)* | Email: **khtc@vlute.edu.vn**"
        )
    
    # 2. Nhóm Công tác Sinh viên (học bổng, chính sách, rèn luyện, y tế, ký túc xá)
    if any(k in combined for k in ["học bổng", "miễn giảm", "chính sách", "bảo hiểm", "bhyt", "trợ cấp", "rèn luyện", "kỷ luật", "khen thưởng", "ký túc xá", "công tác xã hội", "vay vốn"]):
        return (
            "\n\n---\n"
            "📞 **Phòng Công tác Sinh viên (VLUTE):**\n"
            "- Vị trí: Tòa nhà A (Phòng A1.102 - Tầng trệt)\n"
            "- Điện thoại: **(0270) 3862 436** | Email: **ctsv@vlute.edu.vn**"
        )
    
    # 3. Nhóm Đào tạo (học phần, tín chỉ, lịch thi, cảnh báo, điểm số, chuẩn đầu ra)
    if any(k in combined for k in ["tín chỉ", "học phần", "môn học", "rút môn", "cảnh báo", "thôi học", "điểm", "thang điểm", "thi", "lịch thi", "hoãn thi", "tốt nghiệp", "chứng chỉ", "chuẩn đầu ra"]):
        return (
            "\n\n---\n"
            "📞 **Phòng Đào tạo (VLUTE):**\n"
            "- Vị trí: Tòa nhà A (Phòng A1.101 - Tòa nhà Điều hành)\n"
            "- Điện thoại: **(0270) 3822 141** | Email: **daotao@vlute.edu.vn**"
        )
        
    return ""

# ==========================================
# HIỂN THỊ LỊCH SỬ TIN NHẮN (BẢO TOÀN TRÍCH DẪN KHI RERUN)
# ==========================================
for message in st.session_state.messages:
    if message["role"] == "user":
        safe_content = html.escape(message["content"]).replace("\n", "<br>")
        st.markdown(
            f'<div class="chat-row-user"><div class="user-bubble">{safe_content}</div></div>',
            unsafe_allow_html=True
        )
    else:
        with st.chat_message("assistant", avatar=BOT_AVATAR):
            st.markdown(message["content"])
            if message.get("sources"):
                render_sources(message["sources"])
            if message.get("contact"):
                st.markdown(message["contact"])

# ==========================================
# KHỐI GỢI Ý CÂU HỎI NHANH (QUICK PROMPTS)
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
# KHUNG NHẬP CÂU HỎI & PHẢN HỒI (HỖ TRỢ CẢ GÕ VÀ BẤM NÚT)
# ==========================================
user_input_from_chat = st.chat_input("🔍 Hỏi Lucas về quy chế, học bổng, học phí, học vụ VLUTE...")

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
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        # TRƯỜNG HỢP 1: Chào hỏi xã giao -> Phản hồi siêu tốc không cần tra cứu vector
        if is_greeting(user_query):
            greeting_reply = (
                "👋 **Xin chào bạn! Mình là Lucas** - Trợ lý ảo tư vấn Quy chế Đào tạo & Quy định Sinh viên "
                "của **Trường Đại học Công nghệ Kỹ thuật Vĩnh Long** (VLUTE - *tiền thân: Trường ĐH Sư phạm Kỹ thuật Vĩnh Long*).\n\n"
                "Bạn cần mình hỗ trợ giải đáp quy định nào hôm nay? "
                "*(Bạn có thể bấm vào các gợi ý câu hỏi nhanh ở trên hoặc gõ câu hỏi cụ thể nhé!)*"
            )
            st.markdown(greeting_reply)
            answer_to_save = greeting_reply
            contact_to_save = ""
            sources_to_save = []

        # TRƯỜNG HỢP 2: Kiểm tra chủ động ngoài phạm vi (Active Anti-Hallucination)
        elif check_out_of_scope(user_query):
            out_info = check_out_of_scope(user_query)
            refusal_reply = (
                f"Chào bạn nhé! Về nội dung **{out_info['topic']}**, hiện tại trong các văn bản quy chế đã nạp vào hệ thống chưa có quy định chi tiết.\n\n"
                f"ℹ️ *Gợi ý cho bạn:* {out_info['advice']}\n\n"
                f"💡 Để đảm bảo quyền lợi và sự chuẩn xác cho bạn, mình không tự suy đoán khi chưa có văn bản ban hành chính thức.\n\n"
                f"📞 Bạn vui lòng liên hệ trực tiếp **{out_info['dept_name']}** ({out_info['dept_contact']}) để được thầy cô hướng dẫn thủ tục chính xác nhất nhé!"
            )
            st.markdown(refusal_reply)
            answer_to_save = refusal_reply
            contact_to_save = ""
            sources_to_save = []

        # TRƯỜNG HỢP 3: Câu hỏi quy chế học vụ hợp lệ -> Kích hoạt Smart RAG + Stream phản hồi
        else:
            status_placeholder = st.empty()
            status_placeholder.markdown(THINKING_HTML, unsafe_allow_html=True)

            # Lọc tài liệu theo Query Routing & Filtering
            docs = qa_chain.filter_documents(user_query, k=3)

            if not docs:
                status_placeholder.empty()
                no_doc_msg = (
                    "Chào bạn, mình chưa tìm thấy thông tin phù hợp trong các văn bản quy chế hiện có để giải đáp câu hỏi này.\n\n"
                    "Để tránh cung cấp thông tin sai lệch cho bạn, mình không tự suy đoán. "
                    "Bạn có thể thử đặt lại câu hỏi ngắn gọn hơn hoặc hỏi về các chủ đề: *học bổng, hoàn trả học phí, miễn giảm học phí, công tác xã hội, khen thưởng kỷ luật sinh viên* nhé!"
                )
                st.markdown(no_doc_msg)
                answer_to_save = no_doc_msg
                contact_to_save = ""
                sources_to_save = []
            else:
                # Chuẩn bị context và prompt
                context_parts = []
                sources_to_save = []
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
                    
                    sources_to_save.append({
                        "file": src_file,
                        "title": title,
                        "short_title": short_title,
                        "dept": dept,
                        "page": page,
                        "article": article,
                        "snippet": doc.page_content.strip()
                    })

                context_str = "\n\n".join(context_parts)
                formatted_prompt = qa_chain.prompt.format(context=context_str, input=user_query)

                def generate_response():
                    has_started = False
                    for chunk in qa_chain.llm.stream(formatted_prompt):
                        if not has_started:
                            status_placeholder.markdown(f"""
                            <div class="rag-status-badge">
                                <span>✓</span> <span>Đã đối soát thành công <b>{len(docs)}</b> đoạn trích quy chế liên quan</span>
                            </div>
                            """, unsafe_allow_html=True)
                            has_started = True
                        chunk_text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                        yield chunk_text

                raw_answer = st.write_stream(generate_response())
                answer_to_save = raw_answer

                # 1. Hiển thị căn cứ quy chế trích dẫn ngay dưới câu trả lời
                if sources_to_save:
                    render_sources(sources_to_save)

                # 2. Hiển thị thông tin liên hệ phòng ban ở cuối cùng
                contact_footer = get_contact_footer(user_query, raw_answer)
                if contact_footer:
                    st.markdown(contact_footer)
                    contact_to_save = contact_footer
                else:
                    contact_to_save = ""

    # 3. Lưu câu trả lời cùng trích dẫn vào lịch sử
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer_to_save,
        "contact": contact_to_save,
        "sources": sources_to_save
    })
    st.rerun()