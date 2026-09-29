import os
import re
import torch
from langchain_chroma import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import OllamaLLM

DB_PATH = "chroma_db"

# =======================================================
# DANH MỤC VĂN BẢN QUY CHẾ CHÍNH THỨC CỦA TRƯỜNG ĐẠI HỌC CÔNG NGHỆ KỸ THUẬT VĨNH LONG (VLUTE)
# =======================================================
DOC_CATALOG = {
    "xet_cap_hoc_bong.pdf": {
        "title": "Quy định xét cấp học bổng, khen thưởng & trợ cấp học tập (QĐ 201/QĐ-ĐHSPKTVL)",
        "short_title": "QĐ Xét cấp Học bổng & Khen thưởng",
        "category": "hoc_bong",
        "dept": "Phòng Công tác Sinh viên (A1.102)",
        "hotline": "(0270) 3862 436 - ctsv@vlute.edu.vn",
        "keywords": ["học bổng", "khen thưởng", "trợ cấp", "khuyến khích học tập", "xuất sắc", "giỏi", "khá", "điểm rèn luyện", "xét học bổng"]
    },
    "quy_dinh_mien_giam_hoc_phi.pdf": {
        "title": "Quy định chế độ chính sách miễn giảm học phí SV (QĐ 904/QĐ-ĐHSPKTVL)",
        "short_title": "QĐ Miễn giảm Học phí Sinh viên",
        "category": "hoc_phi",
        "dept": "Phòng Kế hoạch - Tài chính & Phòng CTSV",
        "hotline": "(0270) 3822 141 - khtc@vlute.edu.vn",
        "keywords": ["miễn giảm", "giảm học phí", "chế độ chính sách", "hộ nghèo", "dân tộc", "con thương binh", "khuyết tật", "hỗ trợ chi phí"]
    },
    "quy_trinh_hoan_tra_hoc_phi.pdf": {
        "title": "Quy trình hoàn trả học phí thừa cho sinh viên (QT-SV-04)",
        "short_title": "Quy trình Hoàn trả Học phí Thừa",
        "category": "hoc_phi",
        "dept": "Phòng Kế hoạch - Tài chính",
        "hotline": "(0270) 3822 141 - khtc@vlute.edu.vn",
        "keywords": ["hoàn trả", "học phí thừa", "rút tiền", "hoàn tiền", "kế toán", "tài chính", "nộp thừa"]
    },
    "quy_dinh_cong_tac_sinh_vien.pdf": {
        "title": "Quy định công tác sinh viên hệ đại học chính quy (QĐ 1079/QĐ-ĐHSPKTVL)",
        "short_title": "Quy chế Công tác Sinh viên",
        "category": "cong_tac_sv",
        "dept": "Phòng Công tác Sinh viên (A1.102)",
        "hotline": "(0270) 3862 436 - ctsv@vlute.edu.vn",
        "keywords": ["công tác sinh viên", "nhiệm vụ sinh viên", "quyền sinh viên", "kỷ luật", "khiển trách", "cảnh cáo", "buộc thôi học", "đánh giá rèn luyện", "ban cán sự"]
    },
    "tin_chi_cong_tac_xa_hoi.pdf": {
        "title": "Quy định chuẩn tham gia hoạt động Công tác xã hội SV (QĐ 55/QĐ-ĐHSPKTVL)",
        "short_title": "Quy định Tín chỉ Công tác xã hội",
        "category": "ctxh",
        "dept": "Đoàn Thanh niên & Phòng CTSV",
        "hotline": "(0270) 3862 436 - ctsv@vlute.edu.vn",
        "keywords": ["công tác xã hội", "ctxh", "tín chỉ công tác xã hội", "tình nguyện", "mùa hè xanh", "tiếp sức mùa thi", "hiến máu", "hoạt động xã hội"]
    },
    "quy_tac_ung_xu.pdf": {
        "title": "Quy tắc ứng xử của cán bộ, giảng viên & người học",
        "short_title": "Quy tắc Ứng xử Học đường",
        "category": "ung_xu",
        "dept": "Trường ĐH Công nghệ Kỹ thuật Vĩnh Long",
        "hotline": "(0270) 3822 141",
        "keywords": ["ứng xử", "giao tiếp", "trang phục", "thái độ", "văn hóa học đường", "tác phong"]
    },
    "quy_che_an_toan_thong_tin.pdf": {
        "title": "Quy chế bảo đảm an toàn thông tin & an ninh mạng VLUTE (QĐ 979/QĐ-ĐHSPKTVL)",
        "short_title": "Quy chế An toàn Thông tin",
        "category": "an_toan_tt",
        "dept": "Trung tâm Tin học & TT",
        "hotline": "(0270) 3822 141",
        "keywords": ["an toàn thông tin", "mật khẩu", "an ninh mạng", "phần mềm", "tài khoản", "dữ liệu"]
    }
}

# =======================================================
# DANH MỤC CÁC CHỦ ĐỀ CHƯA CÓ TRONG KHO VĂN BẢN HIỆN CÓ
# (Chống Hallucination chủ động theo tư vấn của ChatGPT)
# =======================================================
OUT_OF_SCOPE_TOPICS = [
    {
        "pattern": r"(rút\s+(học\s+phần|môn)|hủy\s+(học\s+phần|môn)|hủy\s+đăng\s+ký)",
        "topic": "thời gian và thủ tục rút hoặc hủy môn học / học phần",
        "advice": (
            "Quy định rút học phần thuộc **Quy chế Đào tạo theo học chế tín chỉ** của trường "
            "(thường sinh viên thực hiện nộp đơn hoặc thao tác trực tuyến trên Cổng Quản lý Đào tạo "
            "trong các tuần đầu của học kỳ theo thông báo của Nhà trường)."
        ),
        "dept_name": "Phòng Đào tạo (A1.101)",
        "dept_contact": "☎️ (0270) 3822 141 | ✉️ daotao@vlute.edu.vn"
    },
    {
        "pattern": r"(tín\s+chỉ\s+(tối\s+thiểu|tối\s+đa)|số\s+tín\s+chỉ.*(học\s+kỳ|đăng\s+ký)|đăng\s+ký\s+tối\s+đa\s+bao\s+nhiêu|đăng\s+ký\s+tối\s+thiểu\s+bao\s+nhiêu)",
        "topic": "số tín chỉ học tập tối thiểu và tối đa được phép đăng ký trong một học kỳ",
        "advice": (
            "Số tín chỉ học phần đăng ký tối thiểu/tối đa trong học kỳ thuộc **Quy chế Đào tạo trình độ đại học** "
            "(thông thường dao động từ 10 - 14 tín chỉ tối thiểu và 20 - 24 tín chỉ tối đa tùy theo xếp loại học lực của sinh viên)."
        ),
        "dept_name": "Phòng Đào tạo (A1.101)",
        "dept_contact": "☎️ (0270) 3822 141 | ✉️ daotao@vlute.edu.vn"
    },
    {
        "pattern": r"(cảnh\s+báo\s+học\s+vụ|buộc\s+thôi\s+học\s+do\s+kết\s+quả|điểm\s+f.*thôi\s+học|học\s+vụ.*bị\s+đuổi)",
        "topic": "tiêu chí cảnh báo kết quả học tập và buộc thôi học do học vụ",
        "advice": (
            "Cảnh báo học vụ được xét dựa trên điểm trung bình chung học kỳ (GPA) và số tín chỉ tích lũy "
            "theo Quy chế Đào tạo tín chỉ hiện hành của trường."
        ),
        "dept_name": "Phòng Đào tạo (A1.101)",
        "dept_contact": "☎️ (0270) 3822 141 | ✉️ daotao@vlute.edu.vn"
    }
]

def check_out_of_scope(query: str):
    """Kiểm tra xem câu hỏi có thuộc các chủ đề đào tạo tín chỉ chưa có trong kho dữ liệu hay không."""
    q_lower = query.lower()
    for item in OUT_OF_SCOPE_TOPICS:
        if re.search(item["pattern"], q_lower):
            return item
    return None

def extract_article_info(content: str):
    """Trích xuất tên Điều và Khoản từ đoạn văn bản để hiển thị trên Thẻ Nguồn (Source Card)."""
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
    
    # Kiểm tra xem có phải Chương không
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

    def filter_documents(self, query: str, k: int = 3):
        """
        Truy xuất thông minh:
        1. Phân loại chủ đề câu hỏi (Query Routing).
        2. Loại trừ triệt để các văn bản nghị quyết hành chính không liên quan.
        3. Phân biệt rõ Học bổng khuyến khích học tập (Điều 17, 18) và Học bổng vượt khó (Điều 32).
        4. Ưu tiên đúng tài liệu chuyên môn.
        """
        q_lower = query.lower()
        
        # Nhận diện nếu câu hỏi hỏi về Học bổng khuyến khích học tập (KKHT)
        is_kkht = any(kw in q_lower for kw in ["khuyến khích", "kkht", "tiêu chuẩn học bổng", "điều kiện xét học bổng", "xét học bổng", "học bổng học tập", "mức học bổng", "học bổng"]) and not any(kw in q_lower for kw in ["vượt khó", "nghèo", "khó khăn", "tài trợ", "doanh nghiệp"])

        # Mở rộng từ khóa truy vấn khi hỏi về học bổng KKHT
        search_query = query
        if is_kkht:
            search_query += " học bổng KKHT Điều 17 Điều 18 điều kiện xét cấp học bổng điểm TBC rèn luyện 17 tín chỉ Mức 1 Mức 2 Mức 3 Mức 4 Xuất sắc Giỏi Khá"

        # 1. Xác định nhóm tài liệu mục tiêu
        target_files = []
        for filename, meta in DOC_CATALOG.items():
            if any(kw in q_lower for kw in meta["keywords"]):
                target_files.append(filename)
                
        # 2. Truy xuất tài liệu từ Chroma (giới hạn index search k=3 đến 5 tối ưu tốc độ)
        fetch_k = max(3, k + 2)
        candidate_docs = self.vector_db.similarity_search(search_query, k=fetch_k)
        
        # 3. Lọc bỏ các tài liệu nghị quyết và lọc học bổng vượt khó nếu là câu hỏi KKHT
        filtered = []
        for doc in candidate_docs:
            source = os.path.basename(doc.metadata.get("source", ""))
            content = doc.page_content.lower()
            
            # Bỏ 3 file nghị quyết nhà nước
            if source in ["nghi_quyet_71.pdf", "nghi_quyet_72.pdf", "nghi_quyet_153.pdf"]:
                if not any(nq in q_lower for nq in ["nghị quyết", "nghi quyet", "bộ chính trị", "chính phủ"]):
                    continue
            
            # Nếu hỏi học bổng KKHT thì LOẠI BỎ triệt để các chunk về Học bổng vượt khó (Điều 30-33)
            if is_kkht and any(vk in content for vk in ["học bổng vượt khó", "điều 30.", "điều 31.", "điều 32.", "điều 33.", "sinh viên có hoàn cảnh đặc biệt", "sinh viên có hoàn cảnh khó khăn"]):
                continue
                    
            filtered.append(doc)
            
        # 4. Ưu tiên các chunk chuyên biệt
        if is_kkht:
            # Ưu tiên chunk có điều kiện cốt lõi (17 tín chỉ, Điểm TBC, rèn luyện) lên vị trí số 1
            priority_docs = []
            secondary_docs = []
            other_docs = []
            for d in filtered:
                c = d.page_content.lower()
                if "17 tín chỉ" in c or "điểm tbc" in c or "điều 17." in c:
                    priority_docs.append(d)
                elif any(cond in c for cond in ["điều 17", "điều 18", "điều 19", "mức 1", "mức 2", "loại học bổng"]):
                    secondary_docs.append(d)
                else:
                    other_docs.append(d)
            final_docs = priority_docs + secondary_docs + other_docs
        elif target_files:
            priority_docs = [d for d in filtered if os.path.basename(d.metadata.get("source", "")) in target_files]
            other_docs = [d for d in filtered if os.path.basename(d.metadata.get("source", "")) not in target_files]
            final_docs = priority_docs + other_docs
        else:
            final_docs = filtered

        # Cắt lấy đúng k chunks tinh túy nhất
        return final_docs[:k]

    def invoke(self, inputs):
        if isinstance(inputs, str):
            inputs = {"input": inputs}
        query = inputs.get("input", "").strip()
        
        # BƯỚC 1: Kiểm tra ngoài phạm vi để tránh suy đoán sai
        out_of_scope = check_out_of_scope(query)
        if out_of_scope:
            refusal_text = (
                f"Chào bạn nhé! Về nội dung **{out_of_scope['topic']}**, hiện tại trong các văn bản quy chế đã nạp vào hệ thống chưa có quy định chi tiết.\n\n"
                f"ℹ️ *Gợi ý cho bạn:* {out_of_scope['advice']}\n\n"
                f"💡 Để đảm bảo quyền lợi và sự chuẩn xác cho bạn, mình không tự suy đoán khi chưa có văn bản ban hành chính thức.\n\n"
                f"📞 Bạn vui lòng liên hệ trực tiếp **{out_of_scope['dept_name']}** ({out_of_scope['dept_contact']}) để được thầy cô hướng dẫn thủ tục chính xác nhất nhé!"
            )
            return {
                "answer": refusal_text,
                "context": [],
                "is_out_of_scope": True,
                "target_dept": out_of_scope['dept_name']
            }

        # BƯỚC 2: Truy xuất tài liệu phù hợp (Query Routing & Filtering)
        docs = self.filter_documents(query, k=3)
        
        # BƯỚC 3: Nếu không tìm thấy đoạn trích nào phù hợp
        if not docs:
            fallback_text = (
                "Chào bạn, mình chưa tìm thấy thông tin phù hợp trong các văn bản quy chế hiện có để giải đáp câu hỏi này.\n\n"
                "Để tránh cung cấp thông tin sai lệch cho bạn, mình không tự suy đoán. "
                "Bạn có thể thử đặt lại câu hỏi ngắn gọn hơn hoặc hỏi về các chủ đề: *học bổng, hoàn trả học phí, miễn giảm học phí, công tác xã hội, khen thưởng kỷ luật sinh viên* nhé!"
            )
            return {
                "answer": fallback_text,
                "context": [],
                "is_out_of_scope": True
            }

        # BƯỚC 4: Chuẩn bị context và đưa vào LLM với văn phong tự nhiên, chuẩn xác
        context_parts = []
        for i, doc in enumerate(docs, 1):
            src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
            doc_info = DOC_CATALOG.get(src_file, {})
            title = doc_info.get("title", src_file)
            page = doc.metadata.get("page", 1)
            article = extract_article_info(doc.page_content)
            header_line = f"--- [TÀI LIỆU {i}: {title} | Trang {page}" + (f" | {article}" if article else "") + " ---"
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
        """Hỗ trợ giao diện retriever chuẩn với tham số giới hạn k=3 mặc định."""
        kwargs = search_kwargs or {"k": 3}
        return self.vector_db.as_retriever(search_kwargs=kwargs)

# =======================================================
# BỘ NHỚ ĐỆM SINGLETON (MODULE-LEVEL CACHE) TĂNG TỐC KHỞI ĐỘNG < 1 GIÂY
# =======================================================
_GLOBAL_EMBEDDINGS = None
_GLOBAL_VECTOR_DB = None
_GLOBAL_LLM = None
_GLOBAL_CHAIN = None

def get_google_api_key():
    """Đọc khóa API từ biến môi trường hoặc Streamlit Secrets."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    try:
        import streamlit as st
        if not api_key and hasattr(st, "secrets"):
            if "GEMINI_API_KEY" in st.secrets:
                api_key = st.secrets["GEMINI_API_KEY"]
            elif "GOOGLE_API_KEY" in st.secrets:
                api_key = st.secrets["GOOGLE_API_KEY"]
    except Exception:
        pass
    return api_key

def get_embedding_model():
    """Nạp mô hình Embedding tối ưu: Hỗ trợ Google Cloud nếu có API Key hoặc mô hình local nạp offline siêu tốc."""
    global _GLOBAL_EMBEDDINGS
    if _GLOBAL_EMBEDDINGS is not None:
        return _GLOBAL_EMBEDDINGS

    # 1. Hỗ trợ Google Generative AI Embeddings nếu có API Key (tính toán cloud nhẹ máy)
    google_api_key = get_google_api_key()
    if google_api_key:
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            _GLOBAL_EMBEDDINGS = GoogleGenerativeAIEmbeddings(
                model="models/embedding-001",
                google_api_key=google_api_key
            )
            return _GLOBAL_EMBEDDINGS
        except Exception:
            pass

    # 2. Tối ưu nạp offline nhanh cho Vietnamese Bi-Encoder cục bộ
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        torch.set_num_threads(min(8, os.cpu_count() or 4))
    except Exception:
        pass

    try:
        _GLOBAL_EMBEDDINGS = SentenceTransformerEmbeddings(
            model_name="bkai-foundation-models/vietnamese-bi-encoder",
            model_kwargs={"device": device, "local_files_only": True},
            encode_kwargs={"normalize_embeddings": True}
        )
    except Exception:
        _GLOBAL_EMBEDDINGS = SentenceTransformerEmbeddings(
            model_name="bkai-foundation-models/vietnamese-bi-encoder",
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True}
        )
    return _GLOBAL_EMBEDDINGS

def get_vector_db():
    """Khởi tạo kết nối ChromaDB với persist_directory có sẵn, tuyệt đối không quét lại file PDF/Word."""
    global _GLOBAL_VECTOR_DB
    if _GLOBAL_VECTOR_DB is not None:
        return _GLOBAL_VECTOR_DB
    
    embedding_model = get_embedding_model()
    _GLOBAL_VECTOR_DB = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embedding_model
    )
    return _GLOBAL_VECTOR_DB

def get_llm():
    """Khởi tạo mô hình LLM: Sử dụng ChatGoogleGenerativeAI(gemini-1.5-flash) nếu có api_key, fallback về OllamaLLM(llama3.2)."""
    global _GLOBAL_LLM
    if _GLOBAL_LLM is not None:
        return _GLOBAL_LLM

    # 1. Kiểm tra API Key từ môi trường hoặc Streamlit Secrets
    api_key = get_google_api_key()
    if api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            _GLOBAL_LLM = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=api_key,
                temperature=0.1
            )
            return _GLOBAL_LLM
        except Exception as e:
            print(f"[Warning] Không thể khởi tạo ChatGoogleGenerativeAI: {e}. Fallback về Ollama.")

    # 2. Fallback về OllamaLLM(model='llama3.2') như cũ khi chạy cục bộ
    _GLOBAL_LLM = OllamaLLM(
        model="llama3.2",
        num_gpu=99,
        temperature=0.05,
        repeat_penalty=1.2,
        stop=["<|eot_id|>", "<|end_of_text|>", "\n\n\n"]
    )
    return _GLOBAL_LLM

def get_rag_chain():
    """Khởi tạo hoặc trả về chain RAG đã được lưu trong bộ nhớ đệm (singleton cache)."""
    global _GLOBAL_CHAIN
    if _GLOBAL_CHAIN is not None:
        return _GLOBAL_CHAIN

    vector_db = get_vector_db()
    llm = get_llm()

    # Prompt chuẩn hóa: tự nhiên, xưng 'mình' gọi 'bạn', ngắn gọn 3-6 dòng, không mở đầu máy móc
    system_prompt = (
        "Bạn là Lucas, trợ lý tư vấn Quy chế Đào tạo và Quy định Sinh viên của Trường Đại học Công nghệ Kỹ thuật Vĩnh Long (VLUTE - tiền thân là Trường Đại học Sư phạm Kỹ thuật Vĩnh Long).\n\n"
        "VĂN PHONG VÀ CÁCH XƯNG HÔ (TỰ NHIÊN NHƯ CON NGƯỜI):\n"
        "- Xưng hô: Xưng 'mình' hoặc 'Lucas', gọi người hỏi là 'bạn'. Giọng văn nhiệt tình, gần gũi, thân thiện như một người bạn hoặc cán bộ hỗ trợ học vụ.\n"
        "- TUYỆT ĐỐI KHÔNG mở đầu bằng các câu máy móc như: 'Dựa vào ngữ cảnh quy chế...', 'Theo tài liệu được cung cấp...', 'Tôi là hệ thống AI...', 'Để trả lời câu hỏi của bạn...'.\n"
        "- Đi thẳng vào nội dung trả lời một cách gãy gọn, rõ ràng (khoảng 3 - 6 dòng cốt lõi, dùng gạch đầu dòng dễ nhìn).\n\n"
        "QUY TẮC PHÂN BIỆT RÕ CÁC LOẠI HỌC BỔNG (RẤT QUAN TRỌNG):\n"
        "- Phân biệt rõ Học bổng khuyến khích học tập (dựa trên kết quả học tập và rèn luyện: Điểm TBC học kỳ từ 2.5 trở lên, Điểm rèn luyện từ Khá trở lên, đăng ký tối thiểu 17 tín chỉ; chia làm các loại Xuất sắc, Giỏi, Khá theo Điều 17, Điều 18 QĐ 201) với Học bổng tài trợ / vượt khó (Điều 32 dành riêng cho sinh viên hộ nghèo, khó khăn có ý chí vươn lên).\n"
        "- Khi sinh viên hỏi về 'Học bổng khuyến khích học tập' hoặc 'tiêu chuẩn xét học bổng': TUYỆT ĐỐI KHÔNG nhầm sang Học bổng vượt khó (Điều 32). Phải nêu đúng các điều kiện của Học bổng khuyến khích học tập (Điều 17) và các mức cấp (Điều 18).\n\n"
        "QUY TẮC CHÍNH XÁC VĂN BẢN (CHỐNG SUY DIỄN / KHÔNG BỊA ĐẶT):\n"
        "1. CHỈ sử dụng thông tin CÓ THỰC trong phần tài liệu bên dưới để trả lời đúng trọng tâm câu hỏi. Không lan man sang các điều khoản không liên quan.\n"
        "2. TUYỆT ĐỐI KHÔNG tự suy đoán hoặc bịa số liệu (số tiền, tỷ lệ %, số tín chỉ, mốc thời gian).\n"
        "3. Tuyệt đối KHÔNG tự sáng tác hay bịa tên Điều/Khoản. Chỉ nêu tên Điều/Khoản khi trong tài liệu có ghi rõ.\n"
        "4. Nếu trong tài liệu không có câu trả lời rõ ràng, hãy trả lời ngắn gọn: 'Hiện tại trong các văn bản quy chế quy định, mình chưa tìm thấy thông tin chi tiết về nội dung này bạn nhé.'\n\n"
        "TÀI LIỆU QUY CHẾ THAM KHẢO:\n{context}\n\n"
        "CÂU HỎI CỦA BẠN: {input}\n\n"
        "CÂU TRẢ LỜI CỦA LUCAS (TỰ NHIÊN, NGẮN GỌN, CHUẨN XÁC):"
    )

    prompt = ChatPromptTemplate.from_template(system_prompt)
    _GLOBAL_CHAIN = SmartRAGChain(vector_db, llm, prompt)
    return _GLOBAL_CHAIN