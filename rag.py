import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import re
import json
import time
from pathlib import Path
import torch
import streamlit as st
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

DEPT_FILE = Path(__file__).parent / "departments.json"
DB_PATH = str(Path(__file__).parent / "chroma_db")

# Hằng số phản hồi từ chối duy nhất cho câu hỏi ngoài phạm vi dữ liệu
REFUSAL_MESSAGE = "• Nội dung này không được đề cập trong các văn bản quy định trước đây hoặc nằm ngoài phạm vi dữ liệu quy chế của Nhà trường."

# Ngưỡng tương đồng Cosine tối thiểu (Cosine Similarity nằm trong đoạn [0, 1])
SIMILARITY_THRESHOLD = 0.38

# Hằng số cảnh báo khi luồng stream bị gián đoạn giữa chừng
STREAM_INTERRUPTED_NOTICE = "⚠️ *[Phản hồi bị gián đoạn giữa chừng do sự cố kết nối mô hình. Nội dung phía trên có thể chưa đầy đủ, bạn vui lòng gửi lại câu hỏi nhé!]*"


def load_departments_config() -> dict:
    """Đọc cấu hình phòng ban tập trung từ tệp departments.json."""
    if DEPT_FILE.exists():
        try:
            with open(DEPT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def ensure_doc_department_metadata(doc, departments: dict = None):
    """Đảm bảo Document luôn có đầy đủ metadata phòng ban từ departments.json nếu cần bổ sung."""
    if not hasattr(doc, "metadata") or doc.metadata is None:
        return doc
    if doc.metadata.get("dept_name") and doc.metadata.get("dept_phone") and doc.metadata.get("dept_email"):
        return doc

    depts = departments if departments is not None else load_departments_config()
    src_name = os.path.basename(doc.metadata.get("source", "")).lower().replace("cong_tac_xa_hoi", "ctxh")
    matched_key = "ctsv"
    matched_info = depts.get("ctsv", {
        "name": "Phòng Công tác Sinh viên (VLUTE)",
        "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
        "phone": "(0270) 3862 436",
        "email": "ctsv@vlute.edu.vn"
    })
    for d_key, d_info in depts.items():
        patterns = d_info.get("patterns", [])
        if any(str(pat).lower() in src_name for pat in patterns):
            matched_key = d_key
            matched_info = d_info
            break

    doc.metadata.setdefault("dept_key", matched_key)
    doc.metadata.setdefault("dept_name", matched_info.get("name", "Phòng Công tác Sinh viên (VLUTE)"))
    doc.metadata.setdefault("dept_location", matched_info.get("location", "Tòa nhà A (Phòng A1.102 - Tầng trệt)"))
    doc.metadata.setdefault("dept_phone", matched_info.get("phone", "(0270) 3862 436"))
    doc.metadata.setdefault("dept_email", matched_info.get("email", "ctsv@vlute.edu.vn"))
    return doc


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

    def filter_documents(self, query: str, k: int = 6):
        """
        Truy xuất động (Dynamic RAG) trên ChromaDB với k=6 (lấy tập ứng viên 15 đoạn trích),
        lọc theo độ tương đồng Cosine thực tế (SIMILARITY_THRESHOLD = 0.38) kết hợp định tuyến
        tệp PDF nguồn (filter={"source": ...}) cho 5 nhóm quy chế trong prompts.json.
        """
        if not query or not str(query).strip():
            return []

        q_lower = query.lower()

        # Chặn triệt để các câu hỏi nhắc trực tiếp đến các nghị quyết nằm trong EXCLUDED_FILES hoặc ngoài phạm vi rõ rệt
        excluded_query_patterns = [
            "nghị quyết 153", "nghi quyet 153", "153/nq-cp", "153/nq",
            "nghị quyết 71", "nghi quyet 71", "71/nq-cp", "71/nq",
            "nghị quyết 72", "nghi quyet 72", "72/nq-cp", "72/nq",
            "hội nhập quốc tế",
            "vé tháng xe buýt", "điểm chuẩn trúng tuyển", "ký túc xá giá phòng"
        ]
        if any(pat in q_lower for pat in excluded_query_patterns):
            return []

        # 1. Nhận diện 5 nhóm câu hỏi quy chế trọng tâm (đồng bộ 100% với prompts.json)
        is_hoan_phi = any(
            kw in q_lower
            for kw in ["hoàn trả", "hoàn phí", "học phí thừa", "rút tiền", "nộp thừa", "hoàn tiền", "trả lại học phí", "trả học phí"]
        )
        is_ho_tro_chi_phi = any(
            kw in q_lower
            for kw in ["hỗ trợ chi phí", "chi phí học tập", "dân tộc thiểu số", "dân tộc", "trợ cấp xã hội"]
        )
        is_mien_giam = (
            not is_ho_tro_chi_phi
            and any(
                kw in q_lower
                for kw in ["miễn giảm", "miễn, giảm", "hồ sơ miễn giảm", "đối tượng miễn giảm", "giảm học phí", "miễn học phí"]
            )
        )
        is_ctxh = any(
            kw in q_lower
            for kw in [
                "công tác xã hội", "ctxh", "tín chỉ công tác xã hội", "ngày công tác xã hội",
                "ngày ctxh", "hiến máu", "mùa hè xanh", "khóa luận", "học phần tốt nghiệp"
            ]
        )
        is_ky_luat_bcs = any(
            kw in q_lower
            for kw in [
                "kỷ luật", "khiển trách", "cảnh cáo", "đình chỉ", "buộc thôi học",
                "thi cử", "phòng thi", "thi hộ", "gian lận", "chấm dứt hiệu lực",
                "ban cán sự", "lớp trưởng",
                "quyền của sinh viên", "không được làm", "khiếu nại",
                "hội đồng khen thưởng", "cố vấn học tập", "giáo viên quản lý", "sinh hoạt công dân"
            ]
        )
        is_ung_xu = any(
            kw in q_lower
            for kw in [
                "quy tắc ứng xử", "ứng xử", "trang phục", "đồng phục",
                "thẻ sinh viên", "quai hậu", "ăn vặt", "tài sản công", "cảnh quan"
            ]
        )
        is_attt_mat_khau = any(
            kw in q_lower
            for kw in [
                "mật khẩu", "an toàn thông tin", "an ninh mạng", "độ phức tạp",
                "email", "@st.vlute.edu.vn", "sao lưu", "thiết bị lưu trữ",
                "usb", "vpn", "phishing", "sự cố an toàn", "quản trị - thiết bị"
            ]
        )
        is_hoc_bong_vuot_kho = any(
            kw in q_lower
            for kw in ["vượt khó", "hoàn cảnh khó khăn", "gia đình khó khăn"]
        )
        is_muc_hoc_bong = (
            not is_hoc_bong_vuot_kho
            and ("học bổng" in q_lower or "kkht" in q_lower or "spkt" in q_lower or "sư phạm kỹ thuật" in q_lower)
            and not any(kw in q_lower for kw in ["nợ môn", "rớt môn", "nợ học phí", "dưới c"])
            and any(
                kw in q_lower
                for kw in [
                    "mức", "mức 1", "mức 2", "mức 3", "phân loại", "các mức",
                    "mức nào", "loại nào", "loại học bổng", "xuất sắc", "giỏi", "khá",
                    "spkt", "sư phạm kỹ thuật"
                ]
            )
        )
        is_hoc_bong_dieu17 = (
            not is_hoc_bong_vuot_kho
            and not is_muc_hoc_bong
            and not is_hoan_phi
            and not is_mien_giam
            and not is_ho_tro_chi_phi
            and any(
                kw in q_lower
                for kw in [
                    "học bổng", "kkht", "điều kiện", "tiêu chuẩn", "điểm rèn luyện",
                    "nợ môn", "rớt môn", "bao nhiêu tín chỉ", "nợ học phí", "dưới c"
                ]
            )
            and any(kw in q_lower for kw in ["học bổng", "kkht", "nợ môn", "rớt môn", "nợ học phí", "dưới c"])
        )

        # Cấu hình định tuyến tệp nguồn (source), từ khóa truy xuất dự phòng và từ khóa ưu tiên
        target_source = None
        fallback_subquery = None
        priority_kws = []
        required_core_kws = []

        if is_hoc_bong_vuot_kho:
            target_source = "xet_cap_hoc_bong.pdf"
            fallback_subquery = "Chương VI Điều 31 Điều 32 học bổng vượt khó hoàn cảnh khó khăn"
            priority_kws = ["điều 31", "điều 32", "vượt khó", "chương vi"]
            required_core_kws = ["điều 31", "điều 32", "chương vi"]
        elif is_muc_hoc_bong:
            target_source = "xet_cap_hoc_bong.pdf"
            if "sư phạm kỹ thuật" in q_lower or "spkt" in q_lower or "mức 1" in q_lower:
                fallback_subquery = "Điều 17 đăng ký tối thiểu 17 tín chỉ điểm TBC 3,2 trở lên rèn luyện Tốt Điều 18 Học bổng KKHT Mức 1 Đơn giá học phí 17 TC khối ngành VII hệ đại trà"
                priority_kws = ["điều 17", "17 tín chỉ", "3,2", "rèn luyện từ tốt", "17 tc", "khối ngành vii", "đơn giá học phí", "mức 1", "điều 18"]
                required_core_kws = ["17 tín chỉ", "3,2", "17 tc", "khối ngành vii"]
            else:
                fallback_subquery = "Điều 18 Mức 1 Mức 2 Mức 3 học bổng loại Xuất sắc loại Giỏi loại Khá"
                priority_kws = ["điều 18", "mức 3", "mức 2", "mức 1", "loại giỏi"]
                required_core_kws = ["điều 18"]
        elif is_hoc_bong_dieu17:
            target_source = "xet_cap_hoc_bong.pdf"
            fallback_subquery = "Điều 17 đăng ký tối thiểu 17 tín chỉ Điểm TBC học kỳ chính trước thời điểm xét đạt từ 2,5 trở lên từ 3,2 trở lên xếp loại rèn luyện từ Khá trở lên"
            priority_kws = ["điều 17", "17 tín chỉ", "2,5 trở lên", "3,2 trở lên", "rèn luyện từ khá", "dưới điểm c", "nhiệm vụ học phí"]
            required_core_kws = ["17 tín chỉ", "2,5 trở lên", "rèn luyện từ khá"]
        elif is_mien_giam:
            target_source = "quy_dinh_mien_giam_hoc_phi.pdf"
            if any(w in q_lower for w in ["hồ sơ", "giấy tờ", "thủ tục", "thời hạn"]):
                fallback_subquery = "Điều 8 quy định về hồ sơ đơn đề nghị miễn giảm học phí"
                priority_kws = ["điều 8", "đơn đề nghị", "điều 5", "điều 6", "điều 7"]
                required_core_kws = ["điều 8", "đơn đề nghị"]
            else:
                fallback_subquery = "Điều 5 Điều 6 Điều 7 đối tượng được miễn học phí giảm học phí"
                priority_kws = ["điều 5", "điều 6", "điều 7", "điều 8"]
                required_core_kws = ["điều 5", "điều 6", "điều 7"]
        elif is_ho_tro_chi_phi:
            target_source = "quy_dinh_mien_giam_hoc_phi.pdf"
            fallback_subquery = "Điều 11 Mức hỗ trợ số tháng hưởng hỗ trợ bằng 60% mức lương tối thiểu chung không quá 10 tháng"
            priority_kws = ["60% mức lương", "điều 11", "điều 10", "điều 12"]
            required_core_kws = ["điều 10", "điều 11", "60% mức lương"]
        elif is_hoan_phi:
            target_source = "quy_trinh_hoan_tra_hoc_phi.pdf"
            fallback_subquery = "tháng 2 tháng 9 năm thứ ba 5.2.1 5.2.2 5.2.3 5.2.4 Phòng CTSV Phòng ĐT Phòng KH-TC hoàn trả học phí thừa"
            priority_kws = ["5.2.1", "5.2.2", "5.2.3", "5.2.4", "tháng 2", "năm thứ ba", "bm-kh-10a"]
            required_core_kws = ["5.2.2", "5.2.3"]
        elif is_ctxh:
            target_source = "tin_chi_cong_tac_xa_hoi.pdf"
            fallback_subquery = "Điều 6 12 ngày 2/3 số ngày Điều 8 Hiến máu Mùa hè xanh"
            priority_kws = ["điều 6", "12 ngày", "2/3 số ngày", "điều 8", "hiến máu"]
            required_core_kws = ["điều 6", "12 ngày", "điều 8", "hiến máu"]
        elif is_ky_luat_bcs:
            target_source = "quy_dinh_cong_tac_sinh_vien.pdf"
            fallback_subquery = f"{query} quyền của sinh viên kỷ luật đình chỉ chấm dứt hiệu lực Ban cán sự"
            priority_kws = ["quyền của sinh viên", "kỷ luật", "đình chỉ", "chấm dứt hiệu lực", "ban cán sự", "không được làm"]
            required_core_kws = priority_kws
        elif is_ung_xu:
            target_source = "quy_tac_ung_xu.pdf"
            fallback_subquery = f"{query} quy tắc ứng xử trang phục thẻ sinh viên tài sản công ăn vặt"
            priority_kws = ["ứng xử", "trang phục", "thẻ sinh viên", "tài sản", "ăn vặt", "cảnh quan"]
            required_core_kws = priority_kws
        elif is_attt_mat_khau:
            target_source = "quy_che_an_toan_thong_tin.pdf"
            fallback_subquery = f"{query} Điều 4 Điều 14 Điều 17 email @st.vlute.edu.vn tối thiểu 8 ký tự 06 tháng usb"
            priority_kws = ["điều 4", "điều 14", "điều 17", "06 tháng", "@st.vlute.edu.vn", "quét virus", "quản trị"]
            required_core_kws = ["điều 4", "điều 14", "điều 17", "@st.vlute.edu.vn", "06 tháng", "quét virus"]

        # Tinh gọn search_query (không nhồi chuỗi dài làm loãng vector Cosine)
        search_query = f"{query} {fallback_subquery}" if fallback_subquery else query

        search_k = max(15, k)
        try:
            docs_with_scores = self.vector_db.similarity_search_with_relevance_scores(search_query, k=search_k)
        except Exception:
            global _GLOBAL_VECTOR_DB
            _GLOBAL_VECTOR_DB = None
            self.vector_db = get_vector_db()
            docs_with_scores = self.vector_db.similarity_search_with_relevance_scores(search_query, k=search_k)

        departments = load_departments_config()
        for doc, _score in docs_with_scores:
            ensure_doc_department_metadata(doc, departments)

        # Nếu là câu hỏi ngoài 5 nhóm quy chế trên và điểm tương đồng cao nhất < 0.38 -> Từ chối ngay
        if not docs_with_scores:
            if not target_source:
                return []
        else:
            top_score = float(docs_with_scores[0][1])
            if top_score < SIMILARITY_THRESHOLD and not target_source:
                return []

        candidate_docs = []
        for doc, rel_score in docs_with_scores:
            if float(rel_score) < SIMILARITY_THRESHOLD:
                continue
            doc.metadata["similarity_score"] = float(rel_score)
            candidate_docs.append(doc)

        filtered = []
        for doc in candidate_docs:
            source = os.path.basename(doc.metadata.get("source", "")).lower()
            title = str(doc.metadata.get("title", "")).lower()

            if source in ["nghi_quyet_71.pdf", "nghi_quyet_72.pdf", "nghi_quyet_153.pdf"] or source.startswith("nghi_quyet_"):
                continue

            if is_hoan_phi and ("cong_tac_sinh_vien" in source or "công tác sinh viên" in title):
                continue

            filtered.append(doc)

        # 2. Truy xuất dự phòng theo tệp nguồn (filter={"source": target_source}) nếu kết quả chưa có đoạn cốt lõi
        if target_source and fallback_subquery:
            check_kws = required_core_kws or priority_kws
            same_source_filtered = [
                d for d in filtered
                if os.path.basename(d.metadata.get("source", "")).lower() == target_source
            ]
            if is_hoan_phi or is_ho_tro_chi_phi or is_hoc_bong_dieu17 or (is_muc_hoc_bong and ("mức 1" in q_lower or "spkt" in q_lower or "sư phạm kỹ thuật" in q_lower)):
                has_core_chunk = all(
                    any(pk in d.page_content.lower() for d in same_source_filtered)
                    for pk in check_kws
                )
            else:
                has_core_chunk = any(
                    any(pk in d.page_content.lower() for pk in check_kws)
                    for d in same_source_filtered
                )
            if not has_core_chunk:
                try:
                    fallback_k = 8 if (is_ho_tro_chi_phi or is_hoc_bong_dieu17 or is_muc_hoc_bong) else (5 if is_hoan_phi else 4)
                    source_docs = self.vector_db.similarity_search(
                        fallback_subquery,
                        k=fallback_k,
                        filter={"source": target_source}
                    )
                    existing_contents = {d.page_content for d in filtered}
                    prepend_docs = []
                    for s_doc in source_docs:
                        ensure_doc_department_metadata(s_doc, departments)
                        s_doc.metadata.setdefault("similarity_score", SIMILARITY_THRESHOLD)
                        if s_doc.page_content not in existing_contents:
                            prepend_docs.append(s_doc)
                            existing_contents.add(s_doc.page_content)
                    filtered = prepend_docs + filtered
                except Exception:
                    pass

            # Nếu hỏi về nợ học phí xét học bổng, bổ sung thêm đoạn Điều 1 (Trang 4) từ xet_cap_hoc_bong.pdf
            if is_hoc_bong_dieu17 and "học phí" in q_lower:
                has_dieu1 = any("nhiệm vụ học phí" in d.page_content.lower() for d in filtered)
                if not has_dieu1:
                    try:
                        dieu1_docs = self.vector_db.similarity_search(
                            "Điều 1 phải hoàn thành nhiệm vụ học phí",
                            k=2,
                            filter={"source": "xet_cap_hoc_bong.pdf"}
                        )
                        existing_contents = {d.page_content for d in filtered}
                        for d1 in dieu1_docs:
                            ensure_doc_department_metadata(d1, departments)
                            d1.metadata.setdefault("similarity_score", SIMILARITY_THRESHOLD)
                            if d1.page_content not in existing_contents:
                                filtered.insert(1 if filtered else 0, d1)
                                existing_contents.add(d1.page_content)
                    except Exception:
                        pass

        # 3. Sắp xếp ưu tiên các đoạn trích chứa điều khoản cốt lõi lên đầu
        if target_source and priority_kws:
            core_docs = [
                d for d in filtered
                if os.path.basename(d.metadata.get("source", "")).lower() == target_source
                and any(pk in d.page_content.lower() for pk in priority_kws)
            ]
            core_docs.sort(
                key=lambda d: sum(1 for pk in priority_kws if pk in d.page_content.lower()),
                reverse=True
            )
            same_source_docs = [
                d for d in filtered
                if d not in core_docs
                and os.path.basename(d.metadata.get("source", "")).lower() == target_source
            ]
            other_docs = [d for d in filtered if d not in core_docs and d not in same_source_docs]
            filtered = core_docs + same_source_docs + other_docs

        return filtered[:k]

    def invoke(self, inputs):
        if isinstance(inputs, str):
            inputs = {"input": inputs}
        query = inputs.get("input", "").strip()
        if inputs.get("chat_history"):
            query = rewrite_conversational_query(query, inputs.get("chat_history"))

        docs = self.filter_documents(query, k=6)

        if not docs:
            return {
                "answer": REFUSAL_MESSAGE,
                "context": [],
                "is_refusal": True,
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
        is_refusal = (REFUSAL_MESSAGE in str(answer)) or ("không được đề cập" in str(answer).lower())

        return {
            "answer": answer,
            "context": docs,
            "is_refusal": is_refusal
        }

    def as_retriever(self, search_kwargs=None):
        kwargs = search_kwargs or {"k": 6, "fetch_k": 15}
        return self.vector_db.as_retriever(search_type="mmr", search_kwargs=kwargs)


# =======================================================
# BỘ NHỚ ĐỆM SINGLETON (MODULE-LEVEL CACHE) TĂNG TỐC KHỞI ĐỘNG < 1 GIÂY
# =======================================================
_GLOBAL_EMBEDDINGS = None
_GLOBAL_VECTOR_DB = None
_GLOBAL_LLM = None
_GLOBAL_CHAIN = None
_CURRENT_KEY_INDEX = 0


def _parse_keys_value(raw_val):
    """Chuẩn hóa giá trị key (list hoặc chuỗi phân tách bởi dấu phẩy/xuống dòng) thành danh sách các API key sạch."""
    if not raw_val:
        return []
    if isinstance(raw_val, (list, tuple, set)):
        items = []
        for item in raw_val:
            items.extend(str(item).replace("\n", ",").split(","))
    else:
        items = str(raw_val).replace("\n", ",").split(",")

    cleaned = []
    for k in items:
        key_str = k.strip().strip('"').strip("'")
        if key_str and key_str not in cleaned:
            cleaned.append(key_str)
    return cleaned


def get_all_google_api_keys():
    """
    Đọc danh sách khóa API từ st.secrets hoặc biến môi trường (hỗ trợ cả dạng string và list):
    - Nếu là string (GEMINI_API_KEY): tự động bọc thành list.
    - Nếu là list (GEMINI_API_KEYS): giữ nguyên list.
    - Kiểm tra hợp lệ: Bắt buộc key phải bắt đầu bằng 'AIzaSy' (bỏ qua ngay lập tức các chuỗi
      bắt đầu bằng 'AQ...' hoặc chuỗi rác để tránh treo timeout 40s).
    """
    raw_keys = []
    try:
        if hasattr(st, "secrets"):
            for sec_name in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEYS", "GOOGLE_API_KEY"):
                if sec_name in st.secrets:
                    val = st.secrets[sec_name]
                    if isinstance(val, str):
                        raw_keys.append(val)
                    elif isinstance(val, (list, tuple, set)):
                        raw_keys.extend(list(val))
                    else:
                        raw_keys.extend(_parse_keys_value(val))
    except Exception:
        pass

    for env_name in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEYS", "GOOGLE_API_KEY"):
        env_val = os.getenv(env_name)
        if env_val:
            raw_keys.extend(_parse_keys_value(env_val))

    cleaned = _parse_keys_value(raw_keys)
    # Lọc nghiêm ngặt: Chỉ giữ lại các key Google hợp lệ bắt đầu bằng 'AIzaSy'
    valid_keys = [k for k in cleaned if k.startswith("AIzaSy")]
    return valid_keys


def get_google_api_key():
    """Lấy 1 API key theo cơ chế Round-Robin toàn cục (_CURRENT_KEY_INDEX)."""
    global _CURRENT_KEY_INDEX
    keys = get_all_google_api_keys()
    if not keys:
        return None
    idx = _CURRENT_KEY_INDEX % len(keys)
    _CURRENT_KEY_INDEX = (_CURRENT_KEY_INDEX + 1) % len(keys)
    return keys[idx]


def get_groq_api_key():
    """Đọc GROQ_API_KEY từ st.secrets hoặc biến môi trường os.getenv('GROQ_API_KEY')."""
    try:
        if hasattr(st, "secrets"):
            if "GROQ_API_KEY" in st.secrets:
                keys = _parse_keys_value(st.secrets["GROQ_API_KEY"])
                if keys:
                    return keys[0]
            if "GROQ_API_KEYS" in st.secrets:
                keys = _parse_keys_value(st.secrets["GROQ_API_KEYS"])
                if keys:
                    return keys[0]
    except Exception:
        pass

    for env_name in ("GROQ_API_KEY", "GROQ_API_KEYS"):
        env_val = os.getenv(env_name)
        if env_val:
            keys = _parse_keys_value(env_val)
            if keys:
                return keys[0]
    return None


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

    _GLOBAL_EMBEDDINGS = HuggingFaceEmbeddings(
        model_name="bkai-foundation-models/vietnamese-bi-encoder",
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True}
    )
    return _GLOBAL_EMBEDDINGS


def get_vector_db():
    """Khởi tạo kết nối ChromaDB với persist_directory có sẵn, chuyển đổi Cosine Distance sang Relevance Score [0, 1]."""
    global _GLOBAL_VECTOR_DB
    if _GLOBAL_VECTOR_DB is not None:
        return _GLOBAL_VECTOR_DB
    
    embedding_model = get_embedding_model()
    _GLOBAL_VECTOR_DB = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embedding_model,
        collection_metadata={"hnsw:space": "cosine"},
        relevance_score_fn=lambda distance: max(0.0, min(1.0, 1.0 - float(distance)))
    )
    return _GLOBAL_VECTOR_DB


class RotatingResilientLLM:
    """
    Lớp bọc LLM với Groq LPU làm Engine xử lý chính (Tier 1):
    - TẦNG 1 (Mặc định): Groq API (llama-3.3-70b-versatile) - sinh chữ tốc độ cao ngay lập tức.
    - TẦNG 2 (Dự phòng 1): Local LLM (LM Studio - http://127.0.0.1:1234/v1, model qwen/qwen3.5-4b).
    - TẦNG 2 (Dự phòng 2): Gemini (chỉ gọi nếu có key 'AIzaSy...' hợp lệ).
    - TẦNG 3: Báo lỗi quá tải an toàn (429 RESOURCE_EXHAUSTED).
    """
    def __init__(self, local_llm, groq_llm=None, max_output_tokens: int = 1200, temperature: float = 0.2):
        self.local_llm = local_llm
        self.groq_llm = groq_llm
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self._cloud_clients = {}
        self._groq_models = [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
        ]
        self._dead_groq_models = set()

    def _get_cloud_client(self, api_key: str):
        if api_key not in self._cloud_clients:
            self._cloud_clients[api_key] = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=api_key,
                max_retries=0,        # Tắt hoàn toàn cơ chế tự động thử lại của LangChain
                request_timeout=4,    # Ngắt kết nối nhanh trong 4 giây nếu mạng bị nghẽn
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                streaming=True
            )
        return self._cloud_clients[api_key]

    def _get_groq_client(self, model_name: str = "llama-3.3-70b-versatile", temperature: float | None = None, max_tokens: int | None = None):
        groq_api_key = get_groq_api_key()
        if not groq_api_key:
            return None
        temp = self.temperature if temperature is None else temperature
        mtok = self.max_output_tokens if max_tokens is None else max_tokens
        return ChatGroq(
            api_key=groq_api_key,
            model_name=model_name,
            temperature=temp,
            max_tokens=mtok,
            max_retries=0,
            request_timeout=25
        )

    def invoke(self, prompt, *args, **kwargs):
        global _CURRENT_KEY_INDEX
        groq_err = None
        local_err = None
        gemini_err = None

        # TẦNG 1 (Engine chính): Ưu tiên gọi trực tiếp Groq LPU ngay từ đầu
        print("[LLM ENGINE] Đang tạo phản hồi qua Groq LPU...")
        candidate_models = [m for m in self._groq_models if m not in self._dead_groq_models]
        if self.max_output_tokens <= 200 and "qwen/qwen3.8-27b" in candidate_models:
            candidate_models.remove("qwen/qwen3.8-27b")
            candidate_models.insert(0, "qwen/qwen3.8-27b")

        for groq_model in candidate_models:
            groq_client = self._get_groq_client(model_name=groq_model)
            if groq_client is not None:
                try:
                    groq_resp = groq_client.invoke(prompt, *args, **kwargs)
                    groq_content = getattr(groq_resp, "content", str(groq_resp))
                    if groq_content and str(groq_content).strip():
                        if self.max_output_tokens > 200 and groq_model in self._groq_models and groq_model != self._groq_models[0]:
                            self._groq_models.remove(groq_model)
                            self._groq_models.insert(0, groq_model)
                        return groq_resp
                except Exception as g_err:
                    groq_err = g_err
                    err_msg = str(g_err).lower()
                    if any(tok in err_msg for tok in ("not_found", "does not exist", "404", "decommissioned", "model_not_found")):
                        self._dead_groq_models.add(groq_model)
                        continue
                    if any(tok in err_msg for tok in ("429", "rate_limit", "rate limit", "too many requests")):
                        if groq_model in self._groq_models:
                            self._groq_models.remove(groq_model)
                            self._groq_models.append(groq_model)
                        time.sleep(0.5)
                    continue

        # TẦNG 2 (Dự phòng 1): Chuyển tiếp sang Local LM Studio (Qwen 4B)
        try:
            print("[FAILOVER] Groq không khả dụng -> Chuyển sang Local LM Studio (qwen/qwen3.5-4b)...")
            local_resp = self.local_llm.invoke(prompt, *args, **kwargs)
            local_content = getattr(local_resp, "content", str(local_resp))
            if local_content and str(local_content).strip():
                return local_resp
        except Exception as l_err:
            local_err = l_err

        # TẦNG 2 (Dự phòng 2): Gọi Gemini nếu có key 'AIzaSy' hợp lệ
        valid_gemini_keys = get_all_google_api_keys()
        if valid_gemini_keys:
            print("[FAILOVER] Local LM Studio không khả dụng -> Chuyển sang dự phòng Gemini...")
            num_keys = len(valid_gemini_keys)
            start_idx = _CURRENT_KEY_INDEX % num_keys
            _CURRENT_KEY_INDEX = (start_idx + 1) % num_keys

            for offset in range(num_keys):
                current_idx = (start_idx + offset) % num_keys
                api_key = valid_gemini_keys[current_idx]
                try:
                    client = self._get_cloud_client(api_key)
                    response = client.invoke(prompt, *args, **kwargs)
                    content = getattr(response, "content", str(response))
                    if content and str(content).strip():
                        if offset > 0:
                            _CURRENT_KEY_INDEX = (current_idx + 1) % num_keys
                        return response
                except Exception as cloud_err:
                    gemini_err = cloud_err
                    continue

        # TẦNG 3: Tất cả đều lỗi -> ném lỗi 429 RESOURCE_EXHAUSTED để app.py hiển thị RATE_LIMIT_MESSAGE
        err_detail = f"Groq: {groq_err} | Local: {local_err} | Gemini: {gemini_err}"
        raise RuntimeError(f"429 RESOURCE_EXHAUSTED: {err_detail}") from (groq_err or local_err or gemini_err)

    def stream(self, prompt, *args, **kwargs):
        global _CURRENT_KEY_INDEX
        groq_err = None
        local_err = None
        gemini_err = None

        # TẦNG 1 (Engine chính): Ưu tiên gọi trực tiếp Groq LPU ngay từ đầu
        print("[LLM ENGINE] Đang tạo phản hồi qua Groq LPU...")
        candidate_models = [m for m in self._groq_models if m not in self._dead_groq_models]
        for groq_model in candidate_models:
            groq_client = self._get_groq_client(model_name=groq_model)
            if groq_client is not None:
                yielded_groq = False
                try:
                    for chunk in groq_client.stream(prompt, *args, **kwargs):
                        chunk_text = getattr(chunk, "content", str(chunk))
                        if chunk_text:
                            yielded_groq = True
                            yield chunk
                    if yielded_groq:
                        if groq_model in self._groq_models and groq_model != self._groq_models[0]:
                            self._groq_models.remove(groq_model)
                            self._groq_models.insert(0, groq_model)
                        return
                    continue
                except Exception as g_err:
                    groq_err = g_err
                    if yielded_groq:
                        yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                        return
                    err_msg = str(g_err).lower()
                    if any(tok in err_msg for tok in ("not_found", "does not exist", "404", "decommissioned", "model_not_found")):
                        self._dead_groq_models.add(groq_model)
                        continue
                    if any(tok in err_msg for tok in ("429", "rate_limit", "rate limit", "too many requests")):
                        if groq_model in self._groq_models:
                            self._groq_models.remove(groq_model)
                            self._groq_models.append(groq_model)
                        time.sleep(0.5)
                    continue

        # TẦNG 2 (Dự phòng 1): Chuyển tiếp sang Local LM Studio (Qwen 4B)
        yielded_local = False
        try:
            print("[FAILOVER] Groq không khả dụng -> Chuyển sang Local LM Studio (qwen/qwen3.5-4b)...")
            for chunk in self.local_llm.stream(prompt, *args, **kwargs):
                chunk_text = getattr(chunk, "content", str(chunk))
                if chunk_text:
                    yielded_local = True
                    yield chunk
            if yielded_local:
                return
            resp = self.local_llm.invoke(prompt, *args, **kwargs)
            if getattr(resp, "content", ""):
                yield resp
                return
        except Exception as l_err:
            local_err = l_err
            if yielded_local:
                yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                return

        # TẦNG 2 (Dự phòng 2): Gọi Gemini nếu có key 'AIzaSy' hợp lệ
        valid_gemini_keys = get_all_google_api_keys()
        if valid_gemini_keys:
            print("[FAILOVER] Local LM Studio không khả dụng -> Chuyển sang dự phòng Gemini...")
            num_keys = len(valid_gemini_keys)
            start_idx = _CURRENT_KEY_INDEX % num_keys
            _CURRENT_KEY_INDEX = (start_idx + 1) % num_keys

            for offset in range(num_keys):
                current_idx = (start_idx + offset) % num_keys
                api_key = valid_gemini_keys[current_idx]
                yielded_from_this_key = False
                try:
                    client = self._get_cloud_client(api_key)
                    for chunk in client.stream(prompt, *args, **kwargs):
                        chunk_text = getattr(chunk, "content", str(chunk))
                        if chunk_text:
                            yielded_from_this_key = True
                            if offset > 0:
                                _CURRENT_KEY_INDEX = (current_idx + 1) % num_keys
                            yield chunk
                    if yielded_from_this_key:
                        return
                except Exception as cloud_err:
                    gemini_err = cloud_err
                    if not yielded_from_this_key:
                        continue
                    yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                    return

        # TẦNG 3: Tất cả đều lỗi -> ném lỗi 429 RESOURCE_EXHAUSTED để app.py hiển thị RATE_LIMIT_MESSAGE
        err_detail = f"Groq: {groq_err} | Local: {local_err} | Gemini: {gemini_err}"
        raise RuntimeError(f"429 RESOURCE_EXHAUSTED: {err_detail}") from (groq_err or local_err or gemini_err)


def get_llm(temperature: float = 0.2, max_output_tokens: int = 1200):
    groq_api_key = get_groq_api_key()
    groq_llm = None
    if groq_api_key:
        groq_llm = ChatGroq(
            api_key=groq_api_key,
            model_name="llama-3.3-70b-versatile",
            temperature=temperature,
            max_tokens=max_output_tokens,
            max_retries=0,
            request_timeout=25
        )

    local_llm = ChatOpenAI(
        base_url="http://127.0.0.1:1234/v1",
        api_key="not-needed",
        model="qwen/qwen3.5-4b",
        temperature=0.0,
        max_tokens=min(800, max_output_tokens),
        max_retries=0,
        request_timeout=45,
        streaming=(max_output_tokens > 200),
        extra_body={"reasoning_effort": "none"}
    )
    return RotatingResilientLLM(
        local_llm=local_llm,
        groq_llm=groq_llm,
        max_output_tokens=max_output_tokens,
        temperature=temperature
    )


def rewrite_conversational_query(query: str, chat_history: list | None = None) -> str:
    """
    Viết lại câu hỏi nối tiếp có chứa đại từ/từ nối ngữ cảnh thành câu hỏi độc lập đầy đủ nghĩa.
    Nếu lịch sử trống hoặc câu hỏi đã rõ chủ ngữ/đối tượng, giữ nguyên câu hỏi gốc để không tăng độ trễ.
    """
    if not query or not str(query).strip():
        return ""

    raw_query = re.sub(r"\s+", " ", str(query).strip())
    if not chat_history:
        return raw_query

    valid_history = []
    for msg in chat_history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = str(msg.get("content", "") or "").strip()
        if role not in ("user", "assistant") or not content or msg.get("is_greeting"):
            continue
        valid_history.append((role, content))

    if valid_history and valid_history[-1][0] == "user" and valid_history[-1][1].strip() == raw_query:
        valid_history = valid_history[:-1]

    if not valid_history:
        return raw_query

    recent_history = valid_history[-6:]
    q_lower = raw_query.lower()

    has_pronoun_no = bool(re.search(r"\bnó\b", q_lower))
    explicit_phrases = [
        "cái đó", "cái này", "mức này", "mức đó", "loại này", "loại đó",
        "khoản này", "quy định này", "trường hợp này", "đối tượng này",
        "phòng này", "phòng đó", "đơn vị này", "đơn vị đó", "ở đó", "bên đó",
        "vậy thì", "vậy còn", "vậy mức", "thế còn", "còn hồ sơ", "còn thủ tục",
        "còn thời gian", "còn điều kiện", "còn mức", "thì sao"
    ]
    has_explicit_marker = (
        has_pronoun_no
        or any(phrase in q_lower for phrase in explicit_phrases)
        or q_lower.startswith(("vậy ", "còn ", "thế "))
    )

    contextual_question_markers = [
        "bao lâu", "như thế nào", "ra sao", "nộp ở đâu", "nộp cho ai",
        "gồm những gì", "bao nhiêu tiền", "mức tiền", "công thức tính"
    ]
    has_contextual_marker = any(marker in q_lower for marker in contextual_question_markers)

    standalone_subjects = [
        "học bổng", "kkht", "spkt", "miễn giảm học phí", "miễn, giảm học phí",
        "hỗ trợ chi phí học tập", "hoàn trả học phí", "học phí thừa", "qt-sv-04",
        "công tác xã hội", "ctxh", "công tác sinh viên", "kỷ luật", "ban cán sự",
        "quy tắc ứng xử", "an toàn thông tin", "mật khẩu", "nghị quyết"
    ]
    has_standalone_subject = any(subj in q_lower for subj in standalone_subjects)

    needs_rewrite = has_explicit_marker or (
        (has_contextual_marker or len(q_lower.split()) <= 7) and not has_standalone_subject
    )
    if not needs_rewrite:
        return raw_query

    history_lines = []
    for role, content in recent_history:
        speaker = "Sinh viên" if role == "user" else "Trợ lý"
        snippet = content if role == "user" else content[:350]
        history_lines.append(f"{speaker}: {snippet}")
    history_block = "\n".join(history_lines)

    rewrite_prompt = (
        "Nhiệm vụ: Viết lại câu hỏi mới nhất của sinh viên thành MỘT câu hỏi tra cứu quy chế đại học "
        "độc lập, đầy đủ chủ ngữ/đối tượng (giữ nguyên tên học bổng, mức học bổng, chế độ, quy trình hoặc phòng ban "
        "từ ngữ cảnh hội thoại trước đó nếu câu hỏi dùng đại từ như 'nó', 'cái đó', 'mức này', 'vậy'... ).\n"
        "Quy tắc:\n"
        "- Chỉ trả về duy nhất câu hỏi đã viết lại bằng tiếng Việt, không giải thích, không ngoặc kép.\n"
        "- Không tự bịa thông tin mới không có trong lịch sử.\n\n"
        f"Lịch sử hội thoại gần nhất:\n{history_block}\n\n"
        f"Câu hỏi hiện tại: {raw_query}\n"
        "Câu hỏi độc lập:"
    )

    try:
        rewriter_llm = get_llm(temperature=0.0, max_output_tokens=120)
        resp = rewriter_llm.invoke(rewrite_prompt)
        rewritten = getattr(resp, "content", str(resp)).strip()
        rewritten = re.sub(r"^(Câu hỏi độc lập|Câu hỏi viết lại)\s*:\s*", "", rewritten, flags=re.IGNORECASE)
        rewritten = rewritten.strip().strip('"').strip("'").splitlines()[0].strip()
        if rewritten and len(rewritten) >= 5:
            print(f"[QUERY REWRITE] '{raw_query}' -> '{rewritten}'")
            return rewritten
    except Exception as err:
        print(f"[QUERY REWRITE WARNING] Không thể viết lại câu hỏi: {err}")

    return raw_query


def get_rag_chain():
    """Khởi tạo hoặc trả về chain RAG đã được lưu trong bộ nhớ đệm (singleton cache)."""
    global _GLOBAL_CHAIN
    if _GLOBAL_CHAIN is not None:
        return _GLOBAL_CHAIN

    vector_db = get_vector_db()
    llm = get_llm()

    system_prompt = (
        "Bạn là trợ lý giải đáp thắc mắc về quy chế và học vụ cho sinh viên VLUTE.\n"
        "NGUYÊN TẮC TRẢ LỜI:\n"
        "1. CHỈ sử dụng thông tin có trong phần 'Ngữ cảnh' được cung cấp để trả lời. Tuyệt đối không tự suy diễn hoặc dùng kiến thức ngoài tài liệu.\n"
        "2. Trả lời đúng trọng tâm và phân biệt rõ bản chất câu hỏi:\n"
        "   - Phân biệt rạch ròi giữa 'Miễn giảm học phí' (chế độ giảm trừ tiền học) và 'Trợ cấp xã hội / Hỗ trợ chi phí học tập' (các khoản chi trả tiền mặt/sinh hoạt phí).\n"
        "   - Nếu người dùng hỏi về 'trợ cấp xã hội' hoặc 'hỗ trợ chi phí học tập' mà tài liệu cung cấp chỉ quy định về 'miễn giảm học phí' (hoặc chỉ nhắc đến giấy tờ 'Quyết định trợ cấp xã hội' như một thành phần hồ sơ minh chứng), hãy làm rõ điểm này: nêu rõ đối tượng được miễn giảm học phí theo quy định, đồng thời chỉ rõ văn bản hiện tại chưa quy định riêng về khoản tiền trợ cấp xã hội độc lập.\n"
        "   - Khi sinh viên hỏi 'có nợ môn hoặc nợ học phí thì được xét học bổng không?': Căn cứ Điều 17 (yêu cầu tối thiểu 17 tín chỉ, không có học phần nào dưới điểm C) và Điều 1 (hoàn thành nghĩa vụ học phí) để trả lời rõ ràng: Sinh viên nợ môn (dưới điểm C) hoặc chưa hoàn thành học phí sẽ KHÔNG đủ điều kiện xét cấp học bổng khuyến khích học tập. Tuyệt đối không trả về thông báo từ chối ngoài phạm vi dữ liệu đối với câu hỏi này.\n"
        "   - Khi sinh viên hỏi về điều kiện xét học bổng khuyến khích học tập (tín chỉ, điểm TBC, hoặc điểm rèn luyện theo Điều 17): Luôn nêu đầy đủ cả 3 tiêu chuẩn cốt lõi tại Điều 17 gồm: (1) Đăng ký tối thiểu 17 tín chỉ, (2) Điểm TBC học kỳ đạt từ 2,5 trở lên theo thang 4,0 (riêng Học bổng KKHT Mức 1 / SPKT yêu cầu từ 3,2 trở lên) và không có học phần dưới điểm C, (3) Xếp loại rèn luyện đạt từ loại Khá trở lên (riêng Mức 1 / SPKT yêu cầu từ loại Tốt trở lên).\n"
        "   - Khi sinh viên hỏi về mức tiền hoặc cách tính Học bổng KKHT Mức 1 (Học bổng SPKT) tại Điều 18: Nêu rõ công thức 'Học bổng KKHT Mức 1 (Học bổng SPKT) = Đơn giá học phí × 17 TC', trong đó 'Đơn giá học phí = Đơn giá học phí theo khối ngành VII (hệ đại trà)'.\n"
        "3. Phong cách trả lời:\n"
        "   - Đi thẳng vào câu hỏi, diễn đạt tự nhiên, rõ ràng, súc tích.\n"
        "   - KHÔNG cần trích dẫn rườm rà số hiệu quyết định hay điều khoản trừ khi câu hỏi yêu cầu cụ thể.\n"
        "   - Trình bày dạng gạch đầu dòng ngắn gọn để sinh viên nắm bắt thông tin nhanh nhất.\n"
        f"4. Nếu thông tin hoàn toàn không có trong tài liệu được cung cấp, trả về đúng hằng số REFUSAL_MESSAGE duy nhất, không giải thích thêm:\n{REFUSAL_MESSAGE}\n\n"
        "Ngữ cảnh:\n{context}\n\n"
        "Câu hỏi: {input}\n\n"
        "Trả lời:"
    )

    prompt = ChatPromptTemplate.from_template(system_prompt)
    _GLOBAL_CHAIN = SmartRAGChain(vector_db, llm, prompt)
    return _GLOBAL_CHAIN
