import os
import re
import torch
from langchain_chroma import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import OllamaLLM

DB_PATH = "chroma_db"

# =======================================================
# DANH MỤC VĂN BẢN QUY CHẾ CHÍNH THỨC CỦA TRƯỜNG ĐH SPKT VĨNH LONG
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
        "title": "Quy tắc ứng xử của cán bộ, giảng viên & người học VLUTE",
        "short_title": "Quy tắc Ứng xử Học đường",
        "category": "ung_xu",
        "dept": "Trường ĐH Sư phạm Kỹ thuật Vĩnh Long",
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
        if name and len(name) > 3 and not name.lower().startswith("khoản"):
            return f"Điều {num}: {name}"
        return f"Điều {num}"
    
    # Kiểm tra xem có phải Chương không
    m_chuong = re.search(r"Chương\s+([IVXLCDM\d]+)[\.\:]?\s*([^\n\.\;]{0,50})", content, re.IGNORECASE)
    if m_chuong:
        return f"Chương {m_chuong.group(1)}"
        
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
        3. Ưu tiên đúng tài liệu chuyên môn.
        """
        q_lower = query.lower()
        
        # 1. Xác định nhóm tài liệu mục tiêu
        target_files = []
        for filename, meta in DOC_CATALOG.items():
            if any(kw in q_lower for kw in meta["keywords"]):
                target_files.append(filename)
                
        # 2. Truy xuất tài liệu từ Chroma
        # Lấy số lượng ứng viên lớn hơn (k*2) để lọc sau đó
        candidate_docs = self.vector_db.similarity_search(query, k=k * 3)
        
        # 3. Lọc bỏ các tài liệu nghị quyết nhà nước / cán bộ viên chức nếu câu hỏi là về sinh viên
        filtered = []
        for doc in candidate_docs:
            source = os.path.basename(doc.metadata.get("source", ""))
            
            # Nếu câu hỏi không hỏi đích danh về Nghị quyết, bỏ qua 3 file nghị quyết
            if source in ["nghi_quyet_71.pdf", "nghi_quyet_72.pdf", "nghi_quyet_153.pdf"]:
                if not any(nq in q_lower for nq in ["nghị quyết", "nghi quyet", "bộ chính trị", "chính phủ"]):
                    continue
                    
            filtered.append(doc)
            
        # 4. Nếu có target_files rõ ràng, ưu tiên các chunk thuộc target_files lên đầu
        if target_files:
            priority_docs = [d for d in filtered if os.path.basename(d.metadata.get("source", "")) in target_files]
            other_docs = [d for d in filtered if os.path.basename(d.metadata.get("source", "")) not in target_files]
            final_docs = priority_docs + other_docs
        else:
            final_docs = filtered

        # Cắt lấy đúng k chunks tinh túy nhất
        return final_docs[:k]

    def invoke(self, inputs):
        query = inputs.get("input", "").strip()
        
        # BƯỚC 1: Kiểm tra chống Hallucination chủ động cho các câu hỏi ngoài phạm vi
        out_of_scope = check_out_of_scope(query)
        if out_of_scope:
            refusal_text = (
                f"👋 **Chào bạn sinh viên VLUTE,**\n\n"
                f"Hiện tại trong các tài liệu quy chế được nạp vào hệ thống, "
                f"**chưa có văn bản quy định chi tiết về: {out_of_scope['topic']}**.\n\n"
                f"ℹ️ *Giải thích:* {out_of_scope['advice']}\n\n"
                f"⚠️ **Nguyên tắc RAG chống suy đoán (Anti-Hallucination):** Lucas tuyệt đối không suy đoán hoặc mượn số liệu từ văn bản khác để đảm bảo tính chuẩn xác cho bạn.\n\n"
                f"💡 **Các nội dung bạn có thể tra cứu có dữ liệu đầy đủ tại trường:**\n"
                f"• 🏆 **Học bổng:** Tiêu chuẩn xét học bổng khuyến khích học tập (QĐ 201)\n"
                f"• 💰 **Học phí:** Quy trình hoàn trả học phí thừa (QT-SV-04) & Miễn giảm học phí (QĐ 904)\n"
                f"• 🤝 **Công tác xã hội:** Quy định tích lũy tín chỉ Công tác xã hội (QĐ 55)\n"
                f"• 📋 **Khen thưởng & Kỷ luật:** Quy chế công tác sinh viên (QĐ 1079)\n\n"
                f"📞 Để được hỗ trợ cụ thể về vấn đề này, bạn vui lòng liên hệ trực tiếp **{out_of_scope['dept_name']}**: {out_of_scope['dept_contact']}."
            )
            return {
                "answer": refusal_text,
                "context": [],
                "is_out_of_scope": True,
                "target_dept": out_of_scope['dept_name']
            }

        # BƯỚC 2: Truy xuất tài liệu phù hợp (Query Routing & Filtering)
        docs = self.filter_documents(query, k=3)
        
        # BƯỚC 3: Nếu không tìm thấy đoạn trích nào hoặc ngữ cảnh rỗng
        if not docs:
            fallback_text = (
                "⚠️ **Lucas chưa tìm thấy thông tin đủ phù hợp trong kho tài liệu quy chế hiện có để giải đáp câu hỏi này.**\n\n"
                "Lucas không muốn tự suy đoán để tránh cung cấp thông tin sai lệch cho sinh viên. "
                "Bạn có thể thử đặt lại câu hỏi ngắn gọn hơn hoặc hỏi về các chủ đề: *học bổng, học phí, công tác xã hội, khen thưởng kỷ luật sinh viên*."
            )
            return {
                "answer": fallback_text,
                "context": [],
                "is_out_of_scope": True
            }

        # BƯỚC 4: Chuẩn bị context và đưa vào LLM với quy tắc chống hallucination nghiêm ngặt
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
        answer = self.llm.invoke(formatted_prompt)

        return {
            "answer": answer,
            "context": docs
        }

def get_rag_chain():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    embedding_model = SentenceTransformerEmbeddings(
        model_name="bkai-foundation-models/vietnamese-bi-encoder",
        model_kwargs={"device": device}
    )
    
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model)

    llm = OllamaLLM(
        model="llama3.2",
        num_gpu=99,
        temperature=0.05,  # Giảm temperature xuống cực thấp để triệt tiêu hoàn toàn tính ngẫu nhiên
        repeat_penalty=1.2,
        stop=["<|eot_id|>", "<|end_of_text|>", "\n\n\n"]
    )

    # Prompt tuân thủ 6 quy tắc chống hallucination theo đề xuất của ChatGPT
    system_prompt = (
        "Bạn là Lucas, trợ lý AI tư vấn Quy chế Đào tạo và Quy định Sinh viên của Trường Đại học Sư phạm Kỹ thuật Vĩnh Long (VLUTE).\n\n"
        "QUY TẮC BẮT BUỘC KHI TRẢ LỜI (ANTI-HALLUCINATION):\n"
        "1. CHỈ sử dụng thông tin có căn cứ xác thực trong phần 'NGỮ CẢNH QUY CHẾ' bên dưới.\n"
        "2. TUYỆT ĐỐI KHÔNG tự suy đoán, không bịa đặt số liệu (tỷ lệ %, số tiền, số tín chỉ, mốc thời gian).\n"
        "3. TUYỆT ĐỐI KHÔNG lấy số liệu từ các văn bản không liên quan (như quy định dành cho giáo viên, viên chức) để áp đặt vào câu trả lời cho sinh viên.\n"
        "4. Nếu trong ngữ cảnh KHÔNG có câu trả lời rõ ràng hoặc thông tin không liên quan trực tiếp, hãy trả lời trung thực: "
        "'Văn bản quy chế hiện có chưa đề cập chi tiết đến nội dung này.'\n"
        "5. Nếu câu hỏi có nhiều ý mà ngữ cảnh chỉ có một phần, chỉ trả lời phần có dữ liệu và nói rõ phần còn lại chưa có văn bản quy định.\n"
        "6. Trình bày dạng gạch đầu dòng rõ ràng, mạch lạc, ngắn gọn; có nêu rõ tên Điều/Khoản nếu có trong ngữ cảnh.\n\n"
        "NGỮ CẢNH QUY CHẾ:\n{context}\n\n"
        "CÂU HỎI CỦA SINH VIÊN: {input}\n\n"
        "CÂU TRẢ LỜI BẰNG TIẾNG VIỆT (CHUẨN XÁC, CÓ TRÍCH DẪN):"
    )

    prompt = ChatPromptTemplate.from_template(system_prompt)
    return SmartRAGChain(vector_db, llm, prompt)