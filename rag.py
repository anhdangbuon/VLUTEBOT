import os
import re
import torch
from langchain_chroma import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

DB_PATH = "chroma_db"

# Hằng số phản hồi từ chối duy nhất cho câu hỏi ngoài phạm vi dữ liệu
REFUSAL_MESSAGE = "• Nội dung này không được đề cập trong các văn bản quy định trước đây hoặc nằm ngoài phạm vi dữ liệu quy chế của Nhà trường."

# Các chủ đề học vụ (Quy chế đào tạo tín chỉ) chưa có văn bản nạp vào hệ thống -> Fast Bail-out ở tầng Python
UNSUPPORTED_TRAINING_KEYWORDS = [
    "cảnh báo học vụ",
    "buộc thôi học do học vụ",
    "rút học phần",
    "hủy học phần",
    "đăng ký tín chỉ tối thiểu",
    "đăng ký tín chỉ tối đa",
]

# Ngưỡng tương đồng Cosine tối thiểu (Cosine Similarity = 1 - Cosine Distance >= 0.42, tương đương Distance <= 0.58)
MIN_COSINE_SIMILARITY = 0.42
MAX_COSINE_DISTANCE = 1.0 - MIN_COSINE_SIMILARITY


def is_fast_bailout_query(query: str) -> bool:
    """Kiểm tra nhanh các chủ đề học vụ chưa nạp văn bản để trả về ngay REFUSAL_MESSAGE mà không cần gọi LLM."""
    q_lower = (query or "").lower().strip()
    return any(kw in q_lower for kw in UNSUPPORTED_TRAINING_KEYWORDS)


# =======================================================
# DANH MỤC LIÊN HỆ PHÒNG BAN & METADATA MỞ RỘNG LINH HOẠT
# (Đảm bảo tương thích 100% với app.py đồng thời hỗ trợ Dynamic RAG)
# =======================================================
DOC_CATALOG = {
    "xet_cap_hoc_bong.pdf": {
        "title": "Quy định xét cấp học bổng, khen thưởng & trợ cấp học tập (QĐ 201/QĐ-ĐHSPKTVL)",
        "short_title": "QĐ Xét cấp Học bổng & Khen thưởng",
        "year": "2025",
        "category": "hoc_bong",
        "dept": "Phòng Công tác Sinh viên (A1.102)",
        "hotline": "(0270) 3862 436 - ctsv@vlute.edu.vn",
        "keywords": ["học bổng", "khen thưởng", "trợ cấp", "khuyến khích học tập", "xuất sắc", "giỏi", "khá", "điểm rèn luyện", "xét học bổng"]
    },
    "quy_dinh_mien_giam_hoc_phi.pdf": {
        "title": "Quy định chế độ chính sách miễn giảm học phí SV (QĐ 904/QĐ-ĐHSPKTVL)",
        "short_title": "QĐ Miễn giảm Học phí Sinh viên",
        "year": "2025",
        "category": "hoc_phi",
        "dept": "Phòng Kế hoạch - Tài chính & Phòng CTSV",
        "hotline": "(0270) 3822 141 - khtc@vlute.edu.vn",
        "keywords": ["miễn giảm", "giảm học phí", "chế độ chính sách", "hộ nghèo", "dân tộc", "con thương binh", "khuyết tật", "hỗ trợ chi phí"]
    },
    "quy_trinh_hoan_tra_hoc_phi.pdf": {
        "title": "Quy trình hoàn trả học phí thừa cho sinh viên (QT-SV-04)",
        "short_title": "Quy trình Hoàn trả Học phí Thừa",
        "year": "2024",
        "category": "hoc_phi",
        "dept": "Phòng Kế hoạch - Tài chính",
        "hotline": "(0270) 3822 141 - khtc@vlute.edu.vn",
        "keywords": ["hoàn trả", "học phí thừa", "rút tiền", "hoàn tiền", "kế toán", "tài chính", "nộp thừa"]
    },
    "quy_dinh_cong_tac_sinh_vien.pdf": {
        "title": "Quy định công tác sinh viên hệ đại học chính quy (QĐ 1079/QĐ-ĐHSPKTVL)",
        "short_title": "Quy chế Công tác Sinh viên",
        "year": "2025",
        "category": "cong_tac_sv",
        "dept": "Phòng Công tác Sinh viên (A1.102)",
        "hotline": "(0270) 3862 436 - ctsv@vlute.edu.vn",
        "keywords": ["công tác sinh viên", "nhiệm vụ sinh viên", "quyền sinh viên", "kỷ luật", "khiển trách", "cảnh cáo", "buộc thôi học", "đánh giá rèn luyện", "ban cán sự"]
    },
    "tin_chi_cong_tac_xa_hoi.pdf": {
        "title": "Quy định chuẩn tham gia hoạt động Công tác xã hội SV (QĐ 55/QĐ-ĐHSPKTVL)",
        "short_title": "Quy định Tín chỉ Công tác xã hội",
        "year": "2025",
        "category": "ctxh",
        "dept": "Đoàn Thanh niên & Phòng CTSV",
        "hotline": "(0270) 3862 436 - ctsv@vlute.edu.vn",
        "keywords": ["công tác xã hội", "ctxh", "tín chỉ công tác xã hội", "tình nguyện", "mùa hè xanh", "tiếp sức mùa thi", "hiến máu", "hoạt động xã hội"]
    },
    "quy_tac_ung_xu.pdf": {
        "title": "Quy tắc ứng xử của cán bộ, giảng viên & người học",
        "short_title": "Quy tắc Ứng xử Học đường",
        "year": "2023",
        "category": "ung_xu",
        "dept": "Trường ĐH Công nghệ Kỹ thuật Vĩnh Long",
        "hotline": "(0270) 3822 141",
        "keywords": ["ứng xử", "giao tiếp", "trang phục", "thái độ", "văn hóa học đường", "tác phong"]
    },
    "quy_che_an_toan_thong_tin.pdf": {
        "title": "Quy chế bảo đảm an toàn thông tin & an ninh mạng VLUTE (QĐ 979/QĐ-ĐHSPKTVL)",
        "short_title": "Quy chế An toàn Thông tin",
        "year": "2025",
        "category": "an_toan_tt",
        "dept": "Trung tâm Tin học & TT",
        "hotline": "(0270) 3822 141",
        "keywords": ["an toàn thông tin", "mật khẩu", "an ninh mạng", "phần mềm", "tài khoản", "dữ liệu"]
    }
}

def extract_article_info(content: str):
    """Trích xuất tên Điều và Khoản từ đoạn văn bản."""
    m = re.search(r"Điều\s+(\d+)[\.\:]?\s*([^\n\.\;]{0,60})", content, re.IGNORECASE)
    if m:
        num = m.group(1)
        name = m.group(2).strip().strip(":")
        name = re.sub(r"[\*\_\`\#\:\.\,\;]+$", "", name).strip()
        if name and len(name) > 3 and not name.lower().startswith("khoản"):
            if len(name) > 40:
                name = name[:40].rsplit(" ", 1)[0]
            return f"Điều {num}: {name}"
        return f"Điều {num}"
    
    m_chuong = re.search(r"Chương\s+([IVXLCDM\d]+)[\.\:]?\s*([^\n\.\;]{0,40})", content, re.IGNORECASE)
    if m_chuong:
        c_num = m_chuong.group(1)
        c_name = m_chuong.group(2).strip().strip(":")
        c_name = re.sub(r"[\*\_\`\#\:\.\,\;]+$", "", c_name).strip()
        if c_name and len(c_name) > 3:
            if len(c_name) > 30:
                c_name = c_name[:30].rsplit(" ", 1)[0]
            return f"Chương {c_num}: {c_name}"
        return f"Chương {c_num}"
        
    return None


class SmartRAGChain:
    def __init__(self, vector_db, llm, prompt):
        self.vector_db = vector_db
        self.llm = llm
        self.prompt = prompt

    def filter_documents(self, query: str, k: int = 5):
        """
        Truy xuất động (Dynamic RAG) trên ChromaDB với k=5 (fetch_k=15),
        kết hợp Fast Bail-out và ngưỡng tương đồng Cosine (Fast Exit) để tối ưu tốc độ < 0.2s.
        """
        if not query or is_fast_bailout_query(query):
            return []

        q_lower = query.lower()
        is_hoan_phi = any(
            kw in q_lower
            for kw in ["hoàn trả", "hoàn phí", "học phí thừa", "rút tiền", "nộp thừa", "hoàn tiền", "trả lại học phí", "trả học phí"]
        )
        is_ctxh = any(
            kw in q_lower
            for kw in ["công tác xã hội", "ctxh", "tín chỉ công tác xã hội", "ngày công tác xã hội", "ngày ctxh"]
        )
        is_hoc_bong_dieu17 = (
            ("học bổng" in q_lower or "kkht" in q_lower)
            and any(
                kw in q_lower
                for kw in ["điều kiện", "tiêu chuẩn", "điểm rèn luyện", "rèn luyện", "nợ môn", "rớt môn", "bao nhiêu tín chỉ", "học phí"]
            )
        )

        search_query = query
        if is_hoc_bong_dieu17:
            search_query = (
                f"{query} Điều 17 Điều kiện xét cấp học bổng KKHT đăng ký tối thiểu 17 tín chỉ "
                "không có học phần nào dưới điểm C kết quả xếp loại rèn luyện từ Khá trở lên Tốt trở lên "
                "Điều 1 phải hoàn thành nhiệm vụ học phí"
            )

        fetch_k = 15
        results_with_score = self.vector_db.similarity_search_with_score(query, k=fetch_k)
        if not results_with_score:
            return []

        # Kiểm tra điểm của đoạn trích đứng đầu (ChromaDB với hnsw:space="cosine" trả về Cosine Distance = 1 - Cosine Similarity)
        top_score = float(results_with_score[0][1])
        cosine_similarity = 1.0 - top_score
        if cosine_similarity < MIN_COSINE_SIMILARITY or top_score > MAX_COSINE_DISTANCE:
            return []

        candidate_docs = [doc for doc, _score in results_with_score]
        if is_hoc_bong_dieu17:
            extra_docs = self.vector_db.similarity_search(search_query, k=fetch_k)
            seen_contents = {d.page_content for d in candidate_docs}
            for ed in extra_docs:
                if ed.page_content not in seen_contents:
                    candidate_docs.append(ed)
                    seen_contents.add(ed.page_content)

        filtered = []
        for doc in candidate_docs:
            source = os.path.basename(doc.metadata.get("source", "")).lower()
            title = str(doc.metadata.get("title", "")).lower()

            # Lọc bỏ 3 file nghị quyết nếu câu hỏi không chứa từ "nghị quyết"
            if source in ["nghi_quyet_71.pdf", "nghi_quyet_72.pdf", "nghi_quyet_153.pdf"] or source.startswith("nghi_quyet_"):
                if "nghị quyết" not in q_lower and "nghi quyet" not in q_lower:
                    continue

            # Nếu hỏi hoàn trả học phí, loại bỏ chunk của quy định công tác sinh viên để tránh mâu thuẫn ngữ cảnh
            if is_hoan_phi and ("cong_tac_sinh_vien" in source or "công tác sinh viên" in title):
                continue

            filtered.append(doc)

        if is_hoan_phi:
            priority_docs = []
            other_docs = []
            for d in filtered:
                src = os.path.basename(d.metadata.get("source", "")).lower()
                ttl = str(d.metadata.get("title", "")).lower()
                if "hoan_tra_hoc_phi" in src or "hoàn trả học phí" in ttl:
                    priority_docs.append(d)
                else:
                    other_docs.append(d)
            filtered = priority_docs + other_docs
        elif is_hoc_bong_dieu17:
            # Ưu tiên đưa các chunk thuộc Điều 17 (Trang 19) và Điều 1 (Trang 4 - hoàn thành nhiệm vụ học phí)
            # của file xet_cap_hoc_bong.pdf lên đầu danh sách ngữ cảnh gửi cho LLM (thay vì đoạn định nghĩa ở Điều 4)
            dieu17_and_1_docs = []
            other_hb_docs = []
            other_docs = []
            for d in filtered:
                src = os.path.basename(d.metadata.get("source", "")).lower()
                page = d.metadata.get("page", 0)
                content_lower = d.page_content.lower()
                if "xet_cap_hoc_bong" in src:
                    if (
                        page == 19
                        or "điều 17" in content_lower
                        or "17 tín chỉ" in content_lower
                        or "dưới điểm c" in content_lower
                        or "xếp loại rèn luyện từ khá" in content_lower
                        or "nhiệm vụ học phí" in content_lower
                        or "điều 1." in content_lower
                    ):
                        dieu17_and_1_docs.append(d)
                    elif "điều 4." not in content_lower and page != 6:
                        other_hb_docs.append(d)
                    else:
                        other_docs.append(d)
                else:
                    other_docs.append(d)
            filtered = dieu17_and_1_docs + other_hb_docs + other_docs
        elif is_ctxh:
            # Đảm bảo lấy trọn vẹn văn bản CTXH (đặc biệt Điều 6 Khoản 1 & Khoản 4 quy định 12 ngày CTXH và 2/3 số ngày)
            dieu6_docs = []
            ctxh_docs = []
            other_docs = []
            for d in filtered:
                src = os.path.basename(d.metadata.get("source", "")).lower()
                content_lower = d.page_content.lower()
                if "tin_chi_cong_tac_xa_hoi" in src:
                    if "điều 6" in content_lower or "12 ngày" in content_lower or "2/3 số ngày" in content_lower:
                        dieu6_docs.append(d)
                    else:
                        ctxh_docs.append(d)
                else:
                    other_docs.append(d)
            filtered = dieu6_docs + ctxh_docs + other_docs

        return filtered[:k]

    def invoke(self, inputs):
        if isinstance(inputs, str):
            inputs = {"input": inputs}
        query = inputs.get("input", "").strip()

        # Fast Bail-out cho các chủ đề học vụ chưa có văn bản nạp vào
        if is_fast_bailout_query(query):
            return {
                "answer": REFUSAL_MESSAGE,
                "context": [],
                "is_out_of_scope": True
            }

        docs = self.filter_documents(query, k=5)

        if not docs:
            return {
                "answer": REFUSAL_MESSAGE,
                "context": [],
                "is_out_of_scope": True
            }

        context_parts = []
        for doc in docs:
            src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
            page = doc.metadata.get("page", 1)
            header_line = f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
            context_parts.append(f"{header_line}\n{doc.page_content}")

        context_str = "\n\n".join(context_parts)
        formatted_prompt = self.prompt.format(context=context_str, input=query)
        raw_answer = self.llm.invoke(formatted_prompt)
        answer = raw_answer if isinstance(raw_answer, str) else getattr(raw_answer, 'content', str(raw_answer))

        return {
            "answer": answer,
            "context": docs
        }

    def as_retriever(self, search_kwargs=None):
        kwargs = search_kwargs or {"k": 5}
        return self.vector_db.as_retriever(search_kwargs=kwargs)


# =======================================================
# BỘ NHỚ ĐỆM SINGLETON (MODULE-LEVEL CACHE) TĂNG TỐC KHỞI ĐỘNG < 1 GIÂY
# =======================================================
_GLOBAL_EMBEDDINGS = None
_GLOBAL_VECTOR_DB = None
_GLOBAL_LLM = None
_GLOBAL_CHAIN = None


def get_all_google_api_keys():
    """Đọc danh sách khóa API từ biến môi trường hoặc Streamlit Secrets."""
    keys_str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            if "GEMINI_API_KEY" in st.secrets:
                keys_str = st.secrets["GEMINI_API_KEY"]
            elif "GOOGLE_API_KEY" in st.secrets:
                keys_str = st.secrets["GOOGLE_API_KEY"]
    except Exception:
        pass
    return [k.strip() for k in str(keys_str).split(",") if k.strip()]


def get_google_api_key():
    keys = get_all_google_api_keys()
    return keys[0] if keys else None


def get_embedding_model():
    """Luôn sử dụng mô hình SentenceTransformer để khớp 100% với dữ liệu ChromaDB đã lưu."""
    global _GLOBAL_EMBEDDINGS
    if _GLOBAL_EMBEDDINGS is not None:
        return _GLOBAL_EMBEDDINGS

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    device = "cpu"
    try:
        torch.set_num_threads(2)
    except Exception:
        pass

    _GLOBAL_EMBEDDINGS = SentenceTransformerEmbeddings(
        model_name="bkai-foundation-models/vietnamese-bi-encoder",
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True}
    )
    return _GLOBAL_EMBEDDINGS


def get_vector_db():
    """Khởi tạo kết nối ChromaDB với persist_directory có sẵn, không quét lại file."""
    global _GLOBAL_VECTOR_DB
    if _GLOBAL_VECTOR_DB is not None:
        return _GLOBAL_VECTOR_DB
    
    embedding_model = get_embedding_model()
    _GLOBAL_VECTOR_DB = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embedding_model,
        collection_metadata={"hnsw:space": "cosine"}
    )
    return _GLOBAL_VECTOR_DB


def get_llm():
    """
    Khởi tạo mô hình LLM qua LM Studio (Qwen 3.5 4B).
    Tự động fallback sang Cloud (Gemini) nếu có API key và mạng khi cần.
    """
    global _GLOBAL_LLM
    if _GLOBAL_LLM is not None:
        return _GLOBAL_LLM

    # 1. Cấu hình Local LLM ưu tiên từ LM Studio
    local_llm = ChatOpenAI(
        base_url="http://127.0.0.1:1234/v1",
        api_key="not-needed",
        model="qwen/qwen3.5-4b",
        temperature=0.1,
        max_tokens=400,
        streaming=True
    )

    # 2. Phương án dự phòng (Fallback) sang Cloud Gemini nếu máy trạm chưa mở LM Studio
    api_keys = get_all_google_api_keys()
    if api_keys:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            cloud_llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=api_keys[0],
                temperature=0.1,
                max_output_tokens=400
            )
            _GLOBAL_LLM = local_llm.with_fallbacks([cloud_llm])
            return _GLOBAL_LLM
        except Exception as e:
            print(f"[Warning] Khởi tạo fallback Cloud thất bại: {e}")

    _GLOBAL_LLM = local_llm
    return _GLOBAL_LLM


def get_rag_chain():
    """Khởi tạo hoặc trả về chain RAG đã được lưu trong bộ nhớ đệm (singleton cache)."""
    global _GLOBAL_CHAIN
    if _GLOBAL_CHAIN is not None:
        return _GLOBAL_CHAIN

    vector_db = get_vector_db()
    llm = get_llm()

    system_prompt = (
        "Bạn là Lucas, trợ lý tư vấn Quy chế Đào tạo và Quy định Sinh viên của Trường Đại học Công nghệ Kỹ thuật Vĩnh Long (VLUTE).\n\n"
        "NGUYÊN TẮC BẮT BUỘC:\n"
        "1. PHẠM VI DỮ LIỆU ĐÓNG: CHỈ sử dụng thông tin CÓ THỰC trong phần 'TÀI LIỆU QUY CHẾ THAM KHẢO' bên dưới. "
        "TUYỆT ĐỐI không tự suy diễn, không tự thêm lời khuyên, không thêm số điện thoại hay thông tin ngoài luồng. Tuyệt đối không tự lấy quy định khác không liên quan đưa vào thay thế.\n"
        "2. QUY TẮC TỪ CHỐI DUY NHẤT:\n"
        "   Khi tài liệu tham khảo không đủ dữ kiện để trả lời câu hỏi, hoặc câu hỏi không liên quan đến quy chế đào tạo/sinh viên, CHỈ in ra đúng 1 câu:\n"
        "   • Nội dung này không được đề cập trong các văn bản quy định trước đây hoặc nằm ngoài phạm vi dữ liệu quy chế của Nhà trường.\n"
        "3. QUY TẮC VỀ NĂM BAN HÀNH:\n"
        "   CHỈ nhắc đến năm ban hành khi người dùng CÓ NÊU CỤ THỂ một năm trong câu hỏi. Nếu người dùng không hỏi năm, TUYỆT ĐỐI KHÔNG tự chèn thêm câu phân trần về năm vào đầu câu trả lời.\n"
        "4. PHẢI TRẢ LỜI TRỰC DIỆN VÀO CÂU HỎI:\n"
        "   - Nếu người dùng hỏi 'điều kiện điểm rèn luyện': BẮT BUỘC phải trả lời cụ thể mức xếp loại rèn luyện yêu cầu (từ loại Khá trở lên, riêng mức 1/SPKT từ loại Tốt trở lên theo Điều 17). Không chép lại định nghĩa chung chung.\n"
        "   - Nếu người dùng hỏi 'nợ môn hoặc nợ học phí có được xét không': BẮT BUỘC trả lời rõ:\n"
        "     + Nợ môn: KHÔNG ĐƯỢC XÉT, vì quy chế yêu cầu không có học phần nào dưới điểm C và tích lũy tối thiểu 17 tín chỉ (Điều 17).\n"
        "     + Nợ học phí: KHÔNG ĐƯỢC XÉT, sinh viên phải hoàn thành nhiệm vụ học phí mới được xét cấp học bổng (Điều 1).\n"
        "   - TUYỆT ĐỐI KHÔNG trả lời vòng vo bằng các câu giới thiệu chung khi tài liệu có điều khoản chi tiết.\n"
        "5. ĐỊNH DẠNG: Trả lời trực tiếp bằng gạch đầu dòng ngắn gọn, không chào hỏi, không kết bài thừa thãi.\n\n"
        "TÀI LIỆU QUY CHẾ THAM KHẢO:\n{context}\n\n"
        "CÂU HỎI CỦA BẠN: {input}\n\n"
        "CÂU TRẢ LỜI CỦA LUCAS:"
    )

    prompt = ChatPromptTemplate.from_template(system_prompt)
    _GLOBAL_CHAIN = SmartRAGChain(vector_db, llm, prompt)
    return _GLOBAL_CHAIN
