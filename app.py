import streamlit as st
from rag import get_rag_chain

st.set_page_config(
    page_title="VLUTEBOT - Trợ lý Lucas", 
    page_icon="🎓", 
    layout="centered"
)

# ==========================================
# CẤU HÌNH NHẬN DIỆN THƯƠNG HIỆU VLUTE
# ==========================================
BOT_AVATAR = "🎓"

# ==========================================
# CSS GIAO DIỆN THEO PHONG CÁCH WEB TRƯỜNG VLUTE
# ==========================================
st.markdown("""
<style>
/* 1. Header phong cách cổng thông tin VLUTE */
.vlute-header {
    background: linear-gradient(135deg, #072a6b 0%, #0d47a1 100%);
    border-radius: 12px;
    padding: 18px 24px;
    margin-bottom: 24px;
    color: white;
    box-shadow: 0 4px 15px rgba(7, 42, 107, 0.25);
    border-left: 6px solid #d32f2f;
}

.vlute-title {
    font-size: 1.45rem;
    font-weight: 700;
    margin: 0;
    color: #ffffff;
    display: flex;
    align-items: center;
    gap: 10px;
    letter-spacing: 0.3px;
}

.vlute-subtitle {
    font-size: 0.88rem;
    color: #e3f2fd;
    margin-top: 6px;
    margin-bottom: 0px;
    font-weight: 400;
}

/* 2. Cấu trúc hàng tin nhắn Chatbot */
div[data-testid="stChatMessage"] {
    display: flex !important;
    align-items: flex-start !important;
    margin-bottom: 1.3rem !important;
    gap: 16px !important; /* <--- CHỈNH KHOẢNG CÁCH RÕ RÀNG Ở ĐÂY (thử 12px, 16px, 20px) */
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
    width: 36px !important;
    height: 36px !important;
    margin-top: 0px !important;
    margin-right: 0px !important;
    margin-left: 0px !important;
    border-radius: 50% !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.2) !important;
}

div[data-testid="stChatMessageAvatar"] img,
div[data-testid="stChatMessageAvatar"] div {
    border-radius: 50% !important;
    overflow: hidden !important;
}

/* Khung tin nhắn của Lucas */
div[data-testid="stChatMessageContent"] {
    background: #0d1e3a !important;
    border: 1px solid #1a3a6c !important;
    border-radius: 4px 18px 18px 18px !important;
    padding: 13px 18px !important;
    max-width: 82% !important;
    width: fit-content !important;
    color: #f0f4f8 !important;
    box-sizing: border-box !important;
    line-height: 1.55 !important;
    margin-left: 0px !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15) !important;
}

/* 3. Khung tin nhắn Sinh viên (User) - Đồng bộ thẳng hàng dọc với Bot */
.chat-row-user {
    display: flex;
    justify-content: flex-end;
    width: 100%;
    margin-bottom: 1.3rem;
    box-sizing: border-box;
    /* 36px (avatar) + 16px (gap ở trên) = 52px */
    padding-left: 52px; 
}

.user-bubble {
    background-color: #242b35;
    border: 1px solid #364151;
    color: #ffffff;
    border-radius: 18px 18px 4px 18px;
    padding: 11px 18px;
    max-width: 82%;
    width: fit-content;
    word-break: break-word;
    font-size: 0.98rem;
    line-height: 1.55;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

/* 4. Animation Bánh răng kỹ thuật VLUTE */
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
    color: #2196f3;
    animation: rotateGearMain 3.5s ease-in-out infinite alternate;
    transform-origin: center;
}

.gear-sub {
    color: #ff9800;
    font-size: 18px;
    margin-left: -5px;
    margin-top: -7px;
    animation: rotateGearSub 3.5s ease-in-out infinite alternate;
    transform-origin: center;
}

.thinking-label {
    font-size: 13px;
    color: #90caf9;
    font-style: italic;
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

.stButton > button {
    border-radius: 8px !important;
    border: none !important;
    background-color: #0d47a1 !important;
    color: white !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    background-color: #1565c0 !important;
    color: white !important;
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
# BANNER TIÊU ĐỀ VLUTE
# ==========================================
st.markdown("""
<div class="vlute-header">
    <div class="vlute-title">
        <span>🎓 VLUTEBOT - Trợ Lý Sinh Viên Lucas</span>
    </div>
    <div class="vlute-subtitle">
        Trường Đại học Sư phạm Kỹ thuật Vĩnh Long | Tư vấn Quy chế & Hỗ trợ học vụ
    </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Bảng điều khiển")
    st.markdown("**Trường ĐH SPKT Vĩnh Long**")
    st.caption("Địa chỉ: 73 Nguyễn Huệ, Phường 2, TP. Vĩnh Long, Vĩnh Long")
    
    if st.button("🗑️ Làm mới cuộc trò chuyện", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

@st.cache_resource
def load_chain():
    return get_rag_chain()

try:
    qa_chain = load_chain()
except Exception as e:
    st.error(f"Lỗi khởi tạo hệ thống: {e}")
    st.stop()

if "messages" not in st.session_state or len(st.session_state.messages) == 0:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 **Chào bạn sinh viên VLUTE! Mình là Lucas**, trợ lý ảo thuộc hệ thống **VLUTEBOT** - "
                "chuyên hỗ trợ giải đáp Quy chế Đào tạo và Quy định Sinh viên của **Trường Đại học Sư phạm Kỹ thuật Vĩnh Long**.\n\n"
                "Bạn cần Lucas hỗ trợ thông tin gì hôm nay? "
                "(Ví dụ: *học bổng khuyến khích học tập, hoàn trả học phí, đăng ký môn học, cảnh báo học vụ...*)"
            )
        }
    ]

# ==========================================
# HIỂN THỊ LỊCH SỬ TIN NHẮN
# ==========================================
for message in st.session_state.messages:
    if message["role"] == "user":
        st.markdown(
            f'<div class="chat-row-user"><div class="user-bubble">{message["content"]}</div></div>',
            unsafe_allow_html=True
        )
    else:
        with st.chat_message("assistant", avatar=BOT_AVATAR):
            st.markdown(message["content"])

# ==========================================
# KHUNG NHẬP CÂU HỎI & PHẢN HỒI
# ==========================================
if user_query := st.chat_input("Nhập câu hỏi về quy chế, học bổng, học vụ VLUTE..."):
    st.session_state.messages.append({"role": "user", "content": user_query})
    st.markdown(
        f'<div class="chat-row-user"><div class="user-bubble">{user_query}</div></div>',
        unsafe_allow_html=True
    )

    with st.chat_message("assistant", avatar=BOT_AVATAR):
        status_placeholder = st.empty()
        status_placeholder.markdown(THINKING_HTML, unsafe_allow_html=True)

        docs = qa_chain.retriever.invoke(user_query)
        context_str = "\n\n".join([doc.page_content for doc in docs])
        formatted_prompt = qa_chain.prompt.format(context=context_str, input=user_query)

        def generate_response():
            has_started = False
            for chunk in qa_chain.llm.stream(formatted_prompt):
                if not has_started:
                    status_placeholder.empty()
                    has_started = True
                yield chunk

        answer = st.write_stream(generate_response())

        if docs:
            with st.expander("📌 Căn cứ quy chế và văn bản trích dẫn"):
                seen_sources = set()
                for doc in docs:
                    source_file = doc.metadata.get("source", "Tài liệu quy chế VLUTE")
                    page_num = doc.metadata.get("page", 1)
                    source_key = f"{source_file}_trang_{page_num}"
                    
                    if source_key not in seen_sources:
                        seen_sources.add(source_key)
                        st.markdown(f"- 📄 **Văn bản:** `{source_file}` *(Trang {page_num})*")
                        short_snippet = doc.page_content.strip()
                        if len(short_snippet) > 180:
                            short_snippet = short_snippet[:180] + "..."
                        st.caption(f"_{short_snippet}_")

    st.session_state.messages.append({"role": "assistant", "content": answer})