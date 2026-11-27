import os
_HF_MODEL_CACHE_DIR = os.path.join(
    os.getenv("HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface")),
    "hub",
    "models--bkai-foundation-models--vietnamese-bi-encoder",
)
if os.path.isdir(_HF_MODEL_CACHE_DIR):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import re
import math
import json
import time
import queue
import socket
import threading
import unicodedata
from collections import OrderedDict
from pathlib import Path
try:
    import tomllib
except ImportError:
    tomllib = None
import numpy as np
import torch
import streamlit as st
from rank_bm25 import BM25Okapi
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from ingest import (
    match_department_for_file,
    sync_knowledge_base_from_data_dir,
    SUPPORTED_EXTENSIONS,
    DATA_PATH,
    EXCLUDED_FILES as INGEST_EXCLUDED_FILES,
)

DEPT_FILE = Path(__file__).parent / "departments.json"
DB_PATH = str(Path(__file__).parent / "chroma_db")

# Hằng số phản hồi từ chối duy nhất cho câu hỏi ngoài phạm vi dữ liệu
REFUSAL_MESSAGE = "Nội dung này không được đề cập trong các văn bản quy định trước đây hoặc nằm ngoài phạm vi dữ liệu quy chế của Nhà trường."

MAX_QUERY_LENGTH = 2000
TOO_LONG_QUERY_MESSAGE = (
    "⚠️ Tin nhắn của bạn vượt quá độ dài cho phép (tối đa 2.000 ký tự). "
    "Bạn vui lòng rút gọn câu hỏi, chỉ nhập đúng trọng tâm quy chế hoặc học phần cần tra cứu nhé! "
    "(Nội dung này nằm ngoài phạm vi xử lý do vượt giới hạn độ dài)."
)
FRIENDLY_ERROR_MESSAGE = (
    "⚠️ Hệ thống đang tạm thời bận hoặc gián đoạn kết nối khi tra cứu dữ liệu. "
    "Bạn vui lòng đợi vài giây rồi thử hỏi lại nhé!"
)


def sanitize_client_error_message(err: Exception | str, rate_limit_msg: str | None = None) -> str:
    """
    Làm sạch mọi thông báo lỗi trước khi trả về phía client (No Stacktrace / Path Leakage):
    Tuyệt đối không để lộ đường dẫn ổ đĩa (D:\\VLUTEBOT\\..., C:\\...) hoặc chi tiết exception thô.
    """
    err_str = str(err or "")
    if any(tok in err_str.upper() for tok in ("429", "RESOURCE_EXHAUSTED", "RATE_LIMIT", "TOO MANY REQUESTS")):
        return rate_limit_msg or FRIENDLY_ERROR_MESSAGE
    return FRIENDLY_ERROR_MESSAGE


def build_extractive_offline_fallback(
    query: str,
    docs: list,
    err: Exception | str | None = None,
    rate_limit_msg: str | None = None,
) -> str:
    """
    Chế độ dự phòng ngoại tuyến (Offline Extractive Fallback):
    Khi toàn bộ LLM/mạng gián đoạn nhưng đã truy xuất được đoạn quy chế khớp nội dung,
    trả về thông báo lỗi đã làm sạch kèm tối đa 3 đoạn trích quy chế chuẩn hóa dạng gạch đầu dòng.
    """
    safe_msg = sanitize_client_error_message(err, rate_limit_msg=rate_limit_msg)
    if not docs:
        return safe_msg

    lines = [
        safe_msg,
        "",
        "Dưới đây là nội dung trích xuất trực tiếp từ văn bản quy chế chính thức của Nhà trường:",
    ]
    for doc in docs[:3]:
        meta = getattr(doc, "metadata", {}) or {}
        src_file = os.path.basename(str(meta.get("source", "") or "Tài liệu"))
        title = str(meta.get("title", src_file) or src_file).strip()
        page = meta.get("page", 1)
        raw_content = getattr(doc, "page_content", "") or ""
        article = extract_article_info(raw_content)
        excerpt = sanitize_no_markdown_tables(clip_context_text(raw_content, max_chars=360))
        excerpt = re.sub(r"\s+", " ", excerpt.replace("|", " - ")).strip()
        loc_parts = [title]
        if article:
            loc_parts.append(article)
        loc_parts.append(f"Trang {page}")
        lines.append(f"- **[{ ' — '.join(loc_parts) }]**: {excerpt}")

    return sanitize_no_markdown_tables("\n".join(lines))


_PROMPT_INJECTION_PATTERNS = (
    "bỏ qua mọi quy tắc", "bỏ qua các quy tắc", "bỏ qua mọi hướng dẫn",
    "bỏ qua chỉ dẫn trước", "bỏ qua mọi chỉ dẫn", "bỏ qua hướng dẫn trước",
    "bỏ qua tất cả quy tắc", "quên hết các quy tắc", "quên mọi quy tắc",
    "phớt lờ mọi quy tắc", "vượt qua mọi rào cản",
    "ignore all previous", "ignore previous instructions", "disregard all previous",
    "forget previous instructions", "override system instructions",
    "system prompt", "tiết lộ prompt", "in ra system prompt", "in ra prompt",
    "hiển thị system prompt", "đóng vai chatgpt", "đóng vai hiệu trưởng",
    "giả làm hiệu trưởng", "ký quyết định", "ra quyết định cấp học bổng",
    "jailbreak", "developer mode", "dan mode", "bạn không còn là lucas",
    "in ra api key", "tiết lộ api key", "cho xin api key", "groq_api_key",
    "google_api_key", "gemini_api_key", "biến môi trường", "os.environ",
    "file .env", "tệp .env", "secrets.toml", "mật khẩu hệ thống", "mật khẩu quản trị",
)

_PROMPT_INJECTION_REGEXES = (
    re.compile(
        r"(?i)(?:bỏ\s+qua|quên\s+hết|phớt\s+lờ|ignore|disregard|forget|override)\s+"
        r"(?:mọi|các|tất\s+cả|toàn\s+bộ|all|any|previous|prior)?\s*"
        r"(?:quy\s+tắc|chỉ\s+dẫn|hướng\s+dẫn|luật|rào\s+cản|instructions|rules|guidelines|constraints)"
    ),
    re.compile(
        r"(?i)(?:in\s+ra|tiết\s+lộ|hiển\s+thị|xuất\s+ra|cho\s+xem|cho\s+xin|show|print|dump|leak|reveal)\s+"
        r"(?:toàn\s+bộ\s+|full\s+|original\s+)?(?:system\s*prompt|prompt\s*gốc|cấu\s+hình\s+prompt|"
        r"api\s*key|mật\s*khẩu\s*hệ\s*thống|biến\s*môi\s*trường|environment\s*variables|secrets?\.toml|\.env)"
    ),
    re.compile(
        r"(?i)(?:đóng\s+vai|giả\s+làm|nhập\s+vai|hóa\s+thân\s+thành|act\s+as|pretend\s+to\s+be)\s+"
        r"(?:thầy\s+)?(?:hiệu\s+trưởng|phó\s+hiệu\s+trưởng|quản\s+trị\s+viên\s+hệ\s+thống|chatgpt\s+không\s+giới\s+hạn)"
    ),
)


def is_prompt_injection(query: str) -> bool:
    """Nhận diện các mẫu tấn công Prompt Injection / Jailbreak / khai thác thông tin nhạy cảm."""
    raw = (query or "").strip()
    if not raw:
        return False
    clean = re.sub(r"\s+", " ", raw.lower())
    if any(pat in clean for pat in _PROMPT_INJECTION_PATTERNS):
        return True
    return any(rx.search(clean) for rx in _PROMPT_INJECTION_REGEXES)


_HP_HOC_PHAN_CUES = (
    "môn", "mon", "đăng ký", "dang ky", "tín chỉ", "tin chi",
    "tiên quyết", "tien quyet", "đề cương", "de cuong", "it1216",
    "mã nguồn mở", "ma nguon mo", "giảng viên", "giang vien", "gv",
    "chuẩn đầu ra", "chuan dau ra", "cđr", "cdr", "giáo trình", "giao trinh",
    "lý thuyết", "ly thuyet", "thực hành", "thuc hanh", "mã hp", "ma hp",
    "rút hp", "rut hp", "học lại", "hoc lai", "lớp hp", "lop hp",
)

_HP_HOC_PHI_CUES = (
    "đóng", "dong", "nộp", "nop", "miễn", "mien", "giảm", "giam",
    "hoàn trả", "hoan tra", "hoàn", "hoan", "thừa", "thua",
    "tiền", "tien", "thu", "mức", "muc", "biên lai", "bien lai",
    "hóa đơn", "hoa don", "khtc", "tài chính", "tai chinh", "nợ hp",
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_HAS_ALPHA_VN_RE = re.compile(r"[a-zA-ZÀ-ỹ]")

_CHAT_SLANG_MULTI_RULES = (
    (re.compile(r"(?i)(?<!\w)bao\s+nhiu(?!\w)"), "bao nhiêu"),
    (re.compile(r"(?i)(?<!\w)như\s+nào(?!\w)"), "như thế nào"),
    (re.compile(r"(?i)(?<!\w)nhu\s+nao(?!\w)"), "như thế nào"),
)
_CHAT_SLANG_HP_RE = re.compile(r"(?i)(?<!\w)hp(?!\w)")
_CHAT_SLANG_SINGLE_RULES = (
    (re.compile(r"(?i)(?<!\w)(?:ko|kh|khong)(?!\w)"), "không"),
    (re.compile(r"(?i)(?<=\s)k(?=\s|[?.!,;:]|$)"), "không"),
    (re.compile(r"(?i)(?<!\w)(?:dc|đc|duoc)(?!\w)"), "được"),
    (re.compile(r"(?i)(?<!\w)roi(?!\w)"), "rồi"),
    (re.compile(r"(?i)(?<=\s)r(?=\s|[?.!,;:]|$)"), "rồi"),
    (re.compile(r"(?i)(?<!\w)(?:j|gi)(?!\w)"), "gì"),
    (re.compile(r"(?i)(?<!\w)(?:bn|bnhiu)(?!\w)"), "bao nhiêu"),
    (re.compile(r"(?i)(?<!\w)ntn(?!\w)"), "như thế nào"),
    (re.compile(r"(?i)(?:^(?=\s*[zv]\s)|(?<=[.?!,;]\s))([zv])(?=\s)"), "vậy"),
    (re.compile(r"(?i)(?<=\s)([zv])(?=\s*[?.!]*\s*$)"), "vậy"),
    (re.compile(r"(?i)(?<!\w)vs(?!\w)"), "với"),
    (re.compile(r"(?i)(?<!\w)sv(?!\w)"), "sinh viên"),
    (re.compile(r"(?i)(?<!\w)gv(?!\w)"), "giảng viên"),
    (re.compile(r"(?i)(?<!\w)hb(?!\w)"), "học bổng"),
    (re.compile(r"(?i)(?<!\w)(?:đrl|drl)(?!\w)"), "điểm rèn luyện"),
    (re.compile(r"(?i)(?<!\w)mghp(?!\w)"), "miễn giảm học phí"),
)


def normalize_chat_slang(query: str) -> str:
    """
    Chuẩn hóa tiếng chat Zalo/Messenger & từ viết tắt sinh viên bằng khớp ranh giới từ (?<!\\w)...(?!\\w).
    - Chạy ở đầu pipeline (trước bộ lọc xã giao, viết lại câu hỏi và tìm kiếm) nhưng giữ nguyên câu gốc trên UI.
    - Tự động phân giải ngữ cảnh cho 'hp' -> 'học phí' hoặc 'học phần'.
    - Giữ nguyên tuyệt đối các mã chuẩn (IT1216, BM-DT-04, KKHT, CTXH, CTSV, KHTC, ATTT, VLUTE, QT-SV-04, CĐR).
    """
    if not query:
        return ""
    s = str(query)
    if len(s) > MAX_QUERY_LENGTH or is_prompt_injection(s):
        return s
    s = _CONTROL_CHARS_RE.sub(" ", s)
    if not _HAS_ALPHA_VN_RE.search(s):
        return s

    # 1. Cụm nhiều từ trước
    for rx, repl in _CHAT_SLANG_MULTI_RULES:
        s = rx.sub(repl, s)

    # 2. Phân giải thông minh từ viết tắt 'hp' theo ngữ cảnh cửa sổ cục bộ & toàn câu
    if _CHAT_SLANG_HP_RE.search(s):
        s_low_full = s.lower()
        def _resolve_hp(match: re.Match) -> str:
            start, end = match.span()
            prefix_slice = s[max(0, start - 10):start].lower()
            if "mã " in prefix_slice and s[end:end + 2].startswith(":"):
                return match.group(0)
            window = s_low_full[max(0, start - 40):min(len(s_low_full), end + 40)]
            win_phan = sum(1 for c in _HP_HOC_PHAN_CUES if c in window)
            win_phi = sum(1 for c in _HP_HOC_PHI_CUES if c in window)
            if win_phan > win_phi:
                return "học phần"
            if win_phi > win_phan:
                return "học phí"
            full_phan = sum(1 for c in _HP_HOC_PHAN_CUES if c in s_low_full)
            full_phi = sum(1 for c in _HP_HOC_PHI_CUES if c in s_low_full)
            return "học phần" if full_phan > full_phi else "học phí"

        s = _CHAT_SLANG_HP_RE.sub(_resolve_hp, s)

    # 3. Từ đơn tiếng chat Zalo/Messenger & từ viết tắt sinh viên
    for rx, repl in _CHAT_SLANG_SINGLE_RULES:
        s = rx.sub(repl, s)

    return s

# Danh sách tệp nghị quyết bị loại khỏi phạm vi tra cứu theo chính sách hệ thống
EXCLUDED_SOURCE_FILES = {"nghi_quyet_71.pdf", "nghi_quyet_72.pdf", "nghi_quyet_153.pdf"}

# Ngưỡng tương đồng Cosine tối thiểu (Cosine Similarity nằm trong đoạn [0, 1])
SIMILARITY_THRESHOLD = 0.38

# Hằng số cảnh báo khi luồng stream bị gián đoạn giữa chừng
STREAM_INTERRUPTED_NOTICE = "⚠️ *[Phản hồi bị gián đoạn giữa chừng do sự cố kết nối mô hình. Nội dung phía trên có thể chưa đầy đủ, bạn vui lòng gửi lại câu hỏi nhé!]*"


@st.cache_data(show_spinner=False)
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
    src_name = os.path.basename(str(doc.metadata.get("source", "") or ""))
    preview_text = f"{doc.metadata.get('title', '')}\n{getattr(doc, 'page_content', '') or ''}"[:2000]
    matched_key, matched_info = match_department_for_file(src_name, depts, content_preview=preview_text)

    doc.metadata.setdefault("dept_key", matched_key)
    doc.metadata.setdefault("dept_name", matched_info.get("name", "Phòng Công tác Sinh viên (VLUTE)"))
    doc.metadata.setdefault("dept_location", matched_info.get("location", "Tòa nhà A (Phòng A1.102 - Tầng trệt)"))
    doc.metadata.setdefault("dept_phone", matched_info.get("phone", "(0270) 3862 436"))
    doc.metadata.setdefault("dept_email", matched_info.get("email", "ctsv@vlute.edu.vn"))
    return doc


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
        self.last_retrieval_debug = {}

    @staticmethod
    def _is_excluded_resolution_query(q_lower: str) -> bool:
        """Kiểm tra câu hỏi có nhắc trực tiếp tới các nghị quyết nằm trong danh sách loại trừ không."""
        excluded_patterns = [
            "nghị quyết 153", "nghi quyet 153", "153/nq-cp", "153/nq",
            "nghị quyết 71", "nghi quyet 71", "71/nq-cp", "71/nq",
            "nghị quyết 72", "nghi quyet 72", "72/nq-cp", "72/nq",
            "hội nhập quốc tế",
        ]
        return any(pat in q_lower for pat in excluded_patterns)

    @staticmethod
    def _has_core_in_scope_regulation_anchor(q_lower: str) -> bool:
        """
        Kiểm tra câu hỏi có chứa chủ đề quy chế/học phần cốt lõi nằm trong 8 tài liệu chính thức hay không.
        Giúp nhận diện câu hỏi ghép 'nửa trong – nửa ngoài' (Hybrid Trap) để không từ chối oan toàn bộ câu.
        """
        core_anchors = (
            "học bổng khuyến khích", "học bổng kkht", "học bổng spkt", "xét cấp học bổng",
            "xét học bổng", "trợ cấp học tập", "miễn giảm học phí", "miễn, giảm học phí",
            "miễn 100% học phí", "giảm 70% học phí", "giảm 50% học phí", "hỗ trợ chi phí học tập",
            "hoàn trả học phí", "học phí thừa", "qt-sv-04", "công tác xã hội", "ngày ctxh",
            "tín chỉ ctxh", "hiến máu tình nguyện", "mùa hè xanh", "điểm rèn luyện",
            "ban cán sự lớp", "kỷ luật sinh viên", "thi hộ", "học hộ", "quy tắc ứng xử",
            "an toàn thông tin", "an ninh mạng", "it1216", "phần mềm mã nguồn mở", "đề cương học phần",
        )
        return any(anchor in q_lower for anchor in core_anchors)

    @staticmethod
    def _is_explicit_out_of_scope_query(q_lower: str) -> bool:
        """
        Nhận diện các câu hỏi kiểu ChatGPT / Gemini đa năng hoặc chủ đề đời sống/tuyển sinh/sau đại học
        nằm ngoài phạm vi 8 văn bản quy chế đại học chính quy & đề cương học phần của Nhà trường.
        Nếu là câu hỏi ghép 'nửa trong – nửa ngoài' (có chứa chủ đề quy chế cốt lõi), cho phép đi qua
        để LLM trả lời vế đúng quy chế và bác bỏ vế bịa đặt.
        """
        if SmartRAGChain._has_core_in_scope_regulation_anchor(q_lower):
            return False
        oos_patterns = (
            "viết code", "đoạn code", "code python", "code c++", "code java", "code javascript",
            "code c#", "code php", "code html", "code sql", "lập trình python", "lập trình c++",
            "lập trình java", "lập trình web", "giải phương trình", "hệ phương trình",
            "tính tích phân", "tính đạo hàm", "ma trận nghịch đảo", "thuật toán sắp xếp",
            "cây nhị phân", "dịch đoạn văn", "dịch sang tiếng", "dịch câu này", "viết bài văn",
            "viết đoạn văn", "làm bài thơ", "sáng tác thơ", "tóm tắt truyện", "tóm tắt tác phẩm",
            "truyện kiều", "chí phèo", "tắt đèn", "vợ nhặt", "lão hạc", "cách làm món",
            "cách nấu", "công thức nấu", "thịt kho tàu", "phở bò", "bún bò", "canh chua",
            "thời tiết", "dự báo thời tiết", "nhiệt độ hôm nay", "trời có mưa không",
            "cấu hình pc", "build pc", "pc gaming", "mua laptop", "tư vấn laptop", "tư vấn điện thoại",
            "giá vàng", "tỷ giá ngoại tệ", "tỷ giá usd", "chứng khoán", "bitcoin", "tiền ảo",
            "giá xăng", "bóng đá", "ngoại hạng anh", "world cup", "champions league",
            "xổ số", "vietlott", "cung hoàng đạo", "tử vi", "bói toán", "xem bói", "phong thủy",
            "căn tin", "cantin", "căng tin", "ký túc xá trường", "phòng ký túc xá",
            "nội quy ký túc xá", "quy chế nội trú", "đăng ký ở ký túc xá", "cổng ký túc xá",
            "ktx trường", "ktx của trường", "tiền điện nước ở ktx", "tiền phòng trọ", "thuê trọ",
            "nhà trọ sinh viên", "vé gửi xe", "giữ xe tháng", "gửi xe tháng", "bãi giữ xe",
            "nhà xe sinh viên", "tuyến xe buýt", "xe buýt số", "xe bus số",
            "điểm chuẩn", "điểm sàn xét tuyển", "chỉ tiêu tuyển sinh", "xét học bạ", "mã trường tuyển sinh",
            "lịch nghỉ tết", "tết nguyên đán", "nghỉ lễ 30/4", "nghỉ lễ 2/9", "lịch nghỉ hè",
            "thư viện mở cửa", "giờ mở cửa thư viện", "đơn giá 1 tín chỉ là bao nhiêu tiền",
            "1 tín chỉ bao nhiêu tiền", "một tín chỉ bao nhiêu tiền", "học phí 1 tín chỉ",
            "học phí một tín chỉ", "quy chế sau đại học", "đào tạo sau đại học", "đào tạo thạc sĩ",
            "đào tạo tiến sĩ", "trình độ thạc sĩ", "trình độ tiến sĩ", "luận văn thạc sĩ",
            "luận án tiến sĩ", "tuyển sinh cao học", "học viên cao học",
            "nghi_quyet_71", "nghi_quyet_72", "nghi_quyet_153",
        )
        return any(pat in q_lower for pat in oos_patterns)

    @staticmethod
    def _looks_like_table_or_split_page(text: str, page_chunk_count: int) -> bool:
        """Nhận diện tự động trang bảng biểu/phụ lục thưa hoặc đoạn trích vắt trang (không hardcode PDF)."""
        if page_chunk_count <= 2:
            return True
        if "|" in text or len(text) < 420:
            return True
        return bool(re.search(r"(?i)\b(phụ lục|biểu mẫu|bảng\s+\d|như sau\s*:)", text))

    @staticmethod
    def _collapse_consecutive_repeats(tokens: list[str]) -> list[str]:
        """Khử các cụm từ hoặc câu lặp lại liên tiếp (kể cả khi không có dấu câu ngăn cách)."""
        if len(tokens) < 2:
            return tokens

        def _norm_tok(tok: str) -> str:
            return re.sub(r"^[\(\[\"'«“]+|[\)\]\.,;:!?\"'»”]+$", "", tok.lower())

        normed = [_norm_tok(t) for t in tokens]
        out: list[str] = []
        i = 0
        n = len(tokens)
        while i < n:
            matched_span = 0
            max_span = min(48, (n - i) // 2)
            for span in range(1, max_span + 1):
                base = normed[i : i + span]
                if not any(base):
                    continue
                reps = 1
                pos = i + span
                while pos + span <= n and normed[pos : pos + span] == base:
                    reps += 1
                    pos += span
                min_reps = 2 if span >= 4 else 3
                if reps >= min_reps:
                    kept = list(tokens[i : i + span])
                    last_tok = tokens[pos - 1]
                    if last_tok.endswith(("?", "!", ".")) and not kept[-1].endswith(("?", "!", ".")):
                        kept[-1] = kept[-1].rstrip(",;:") + last_tok[-1]
                    out.extend(kept)
                    i = pos
                    matched_span = span
                    break
            if not matched_span:
                out.append(tokens[i])
                i += 1
        return out

    @staticmethod
    def _prepare_retrieval_query(q_clean: str) -> str:
        """Chuẩn hóa câu truy vấn tìm kiếm tổng quát: dịch tiếng chat Zalo/viết tắt, khử lặp chuỗi, giới hạn 450 ký tự và mở rộng viết tắt nếu ngắn."""
        s = re.sub(r"\s+", " ", normalize_chat_slang((q_clean or "").strip()))
        if not s:
            return ""

        s = re.sub(r"([?!;])(?=\S)", r"\1 ", s)
        raw_clauses = [c.strip() for c in re.split(r"(?<=[.?!;])\s+", s) if c.strip()]
        if len(raw_clauses) > 1:
            dedup_clauses: list[str] = []
            seen_clauses: set[str] = set()
            for clause in raw_clauses:
                norm_clause = re.sub(r"[.!?,;:\s]+$", "", clause.lower()).strip()
                if len(norm_clause) >= 8 or len(norm_clause.split()) >= 3:
                    if norm_clause in seen_clauses:
                        continue
                    seen_clauses.add(norm_clause)
                dedup_clauses.append(clause)
            s = " ".join(dedup_clauses).strip()

        tokens = SmartRAGChain._collapse_consecutive_repeats(s.split())
        s = " ".join(tokens).strip()
        if not s:
            return ""

        q_end = "?" if s.endswith("?") else ""
        s_core = re.sub(
            r"^(?:lucas\s+ơi(?:\s+cho\s+hỏi)?|ad\s+ơi(?:\s+cho\s+hỏi)?|bạn\s+ơi(?:\s+cho\s+hỏi)?|"
            r"bot\s+ơi|cho\s+(?:mình|em|tôi)?\s*hỏi(?:\s+về)?|xin\s+hỏi|giải\s+đáp\s+giúp|"
            r"theo\s+quy\s+định\s+trường)\b[\s,\.\:\-]*",
            "",
            s,
            flags=re.IGNORECASE,
        ).strip()
        s_core_body = s_core.rstrip("?.! ").strip()
        s_core_body = re.sub(
            r"\s+(?:dành\s+cho\s+sinh\s+viên\s+chính\s+quy|cho\s+em\s+biết|cho\s+mình\s+biết|"
            r"giúp\s+mình|theo\s+văn\s+bản|năm\s+học\s+này|của\s+vlute|"
            r"mới\s+nhất|hiện\s+nay|chi\s+tiết|cụ\s+thể|với\s+ạ|vậy\s+ạ|ạ|nhé)$",
            "",
            s_core_body,
            flags=re.IGNORECASE,
        ).strip()
        if len(s_core_body) >= 4 and len(s_core_body.split()) >= 3:
            s = f"{s_core_body}{q_end}"

        q_end = "?" if s.endswith("?") else ""
        s_core = re.sub(
            r"^(?i:(?:lucas\s+ơi(?:\s+cho\s+hỏi)?|ad\s+ơi(?:\s+cho\s+hỏi)?|bạn\s+ơi(?:\s+cho\s+hỏi)?|"
            r"bot\s+ơi(?:\s+cho\s+hỏi)?|cho\s+(?:mình|em|tôi)?\s*hỏi(?:\s+về)?|xin\s+hỏi|giải\s+đáp\s+giúp|"
            r"theo\s+quy\s+định\s+trường|dạ|ủa|ơ))\s+",
            "",
            s,
        ).strip()
        s_core_body = s_core.rstrip("?.! ").strip()
        for _ in range(2):
            stripped_tail = re.sub(
                r"\s+(?i:(?:dành\s+cho\s+sinh\s+viên\s+chính\s+quy|cho\s+em\s+biết|cho\s+mình\s+biết|"
                r"giúp\s+mình|theo\s+văn\s+bản|năm\s+học\s+này|của\s+vlute|"
                r"mới\s+nhất|hiện\s+nay|chi\s+tiết|cụ\s+thể|với\s+ạ|vậy\s+ạ|ạ|nhé))$",
                "",
                s_core_body,
            ).strip()
            if stripped_tail == s_core_body:
                break
            s_core_body = stripped_tail
        if len(s_core_body) >= 4:
            s = f"{s_core_body}{q_end}"

        # Khôi phục dấu tiếng Việt cho các cụm từ khóa quy chế gõ không dấu hoặc viết tắt phổ biến
        unaccented_phrase_map = (
            ("dieu kien", "điều kiện"),
            ("hoc bong khuyen khich hoc tap", "học bổng khuyến khích học tập"),
            ("khuyen khich hoc tap", "khuyến khích học tập"),
            ("hoc bong", "học bổng"),
            ("mien giam hoc phi", "miễn giảm học phí"),
            ("ho tro chi phi hoc tap", "hỗ trợ chi phí học tập"),
            ("hoan tra hoc phi thua", "hoàn trả học phí thừa"),
            ("hoan tra hoc phi", "hoàn trả học phí"),
            ("hoc phi thua", "học phí thừa"),
            ("cong tac xa hoi", "công tác xã hội"),
            ("cong tac sinh vien", "công tác sinh viên"),
            ("diem ren luyen", "điểm rèn luyện"),
            ("ren luyen", "rèn luyện"),
            ("ban can su lop", "ban cán sự lớp"),
            ("xu ly ky luat", "xử lý kỷ luật"),
            ("ky luat", "kỷ luật"),
            ("thi ho", "thi hộ"),
            ("hoc ho", "học hộ"),
            ("quy tac ung xu", "quy tắc ứng xử"),
            ("an toan thong tin", "an toàn thông tin"),
            ("an ninh mang", "an ninh mạng"),
            ("mat khau", "mật khẩu"),
            ("de cuong hoc phan", "đề cương học phần"),
            ("phan mem ma nguon mo", "phần mềm mã nguồn mở"),
            ("ma nguon mo", "mã nguồn mở"),
            ("so tin chi", "số tín chỉ"),
            ("tin chi", "tín chỉ"),
            ("ly thuyet", "lý thuyết"),
            ("thuc hanh", "thực hành"),
            ("giang vien phu trach", "giảng viên phụ trách"),
            ("giang vien", "giảng viên"),
            ("hoc phan tien quyet", "học phần tiên quyết"),
            ("tien quyet", "tiên quyết"),
            ("chuan dau ra", "chuẩn đầu ra"),
            ("phuong phap kiem tra danh gia", "phương pháp kiểm tra đánh giá"),
            ("he so", "hệ số"),
            ("chuyen can", "chuyên cần"),
            ("qua trinh", "quá trình"),
            ("cuoi ky", "cuối kỳ"),
            ("giao trinh", "giáo trình"),
            ("dan toc thieu so", "dân tộc thiểu số"),
            ("ho ngheo", "hộ nghèo"),
            ("can ngheo", "cận nghèo"),
            ("khuyet tat", "khuyết tật"),
            ("mo coi", "mồ côi"),
            ("hien mau", "hiến máu"),
            ("mua he xanh", "mùa hè xanh"),
            ("khoa luan tot nghiep", "khóa luận tốt nghiệp"),
            ("tot nghiep", "tốt nghiệp"),
        )
        s_low_check = s.lower()
        for unacc, acc in unaccented_phrase_map:
            if unacc in s_low_check:
                s = re.sub(rf"\b{re.escape(unacc)}\b", acc, s, flags=re.IGNORECASE)
                s_low_check = s.lower()

        words = s.split()
        if len(words) <= 5:
            q_punct = "?" if s.endswith("?") else ""
            stripped = re.sub(r"\b(?:lucas|alo|ad|ơi)\b", " ", s, flags=re.IGNORECASE)
            stripped = re.sub(r"^[\s\,\.\:\!\?\-]+|[\s\,\.\:\!\?\-]+$", "", stripped)
            stripped = re.sub(r"\s+", " ", stripped).strip()
            if stripped:
                s = stripped
                acronym_expansions = (
                    ("ctxh", "công tác xã hội", "công tác xã hội (CTXH)"),
                    ("kkht", "khuyến khích học tập", "học bổng khuyến khích học tập (KKHT)"),
                    ("ctsv", "công tác sinh viên", "công tác sinh viên (CTSV)"),
                    ("attt", "an toàn thông tin", "an toàn thông tin (ATTT)"),
                    ("khtc", "kế hoạch tài chính", "kế hoạch tài chính (KHTC)"),
                )
                s_low = s.lower()
                for abbr, full_check, full_label in acronym_expansions:
                    if full_check not in s_low and re.search(rf"\b{abbr}\b", s_low):
                        s = re.sub(rf"\b{abbr}\b", full_label, s, flags=re.IGNORECASE)
                        s_low = s.lower()
                if len(s.split()) <= 5 and not re.search(r"(?i)\b(quy\s+định|quy\s+chế)\b", s):
                    s = f"quy định về {s}"
                if q_punct and not s.endswith("?"):
                    s = f"{s}{q_punct}"

        if len(s) > 450:
            q_suffix = "?" if s.rstrip().endswith("?") else ""
            max_body = 450 - (1 if q_suffix else 0)
            cut = s[:max_body].rsplit(" ", 1)[0].rstrip(" ,.;:-")
            if not cut:
                cut = s[:max_body].rstrip()
            s = f"{cut}{q_suffix}" if q_suffix and not cut.endswith("?") else cut
        return s

    @staticmethod
    def _split_compound_clauses(query: str) -> list[str]:
        """
        Chỉ tách vế khi câu hỏi thực sự hỏi 2 hành vi hoặc 2 quy định độc lập
        (ví dụ nối bởi '; ', ' đồng thời ', câu hỏi phụ 'nếu/khi/còn...', hoặc 2 động từ hành vi
        riêng biệt như 'không đi hoặc vắng họp', 'thi hộ và mang tài liệu'); KHÔNG tách
        các cụm liệt kê điều kiện cùng một chế độ (như 'tín chỉ và điểm rèn luyện',
        'điểm dưới C hoặc nợ học phí').
        """
        q = re.sub(r"\s+", " ", (query or "").strip())
        if not q or len(q.split()) < 6:
            return []

        q_punct = "?" if q.endswith("?") else ""
        q_body = q.rstrip("?.! ").strip()

        fixed_phrases = (
            "cán bộ, giảng viên và người học",
            "an toàn thông tin và an ninh mạng",
            "học bổng và khen thưởng",
            "khóa luận và tốt nghiệp",
            "khen thưởng và kỷ luật",
            "đồ án và khóa luận",
            "tiểu luận và đồ án",
            "quyền lợi và nghĩa vụ",
            "nhiệm vụ và quyền hạn",
            "quyền và nghĩa vụ",
            "đoàn phí và hội phí",
            "chi đoàn và chi hội",
            "học phí và lệ phí",
            "miễn hoặc giảm",
            "miễn và giảm",
            "miễn, giảm",
        )
        protected = q_body
        restore_map = {}
        for idx, phrase in enumerate(fixed_phrases):
            token = f"__FIXEDPHRASE{idx}__"
            pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
            if pattern.search(protected):
                def _store(match, tok=token):
                    restore_map[tok] = match.group(0)
                    return tok
                protected = pattern.sub(_store, protected, count=1)

        def _restore_and_clean(raw_list: list[str]) -> list[str]:
            cleaned_parts = []
            for raw_p in raw_list:
                restored = raw_p
                for tok, orig in restore_map.items():
                    restored = restored.replace(tok, orig)
                cleaned = re.sub(r"^[\s,\-:;]+|[\s,\-:;]+$", "", restored).strip()
                if not cleaned:
                    return []
                cleaned_parts.append(cleaned)
            return cleaned_parts

        # Ưu tiên 1: Dấu phân tách câu hỏi ghép rõ ràng ('; ' hoặc ' đồng thời ')
        strong_parts = re.split(
            r"\s*(?:[;,]\s*\bđồng\s+thời\b|\bđồng\s+thời\b|;\s*)\s*",
            protected,
            flags=re.IGNORECASE,
        )
        is_strong_split = 2 <= len(strong_parts) <= 3
        parts: list[str] = []

        if is_strong_split:
            cand_parts = _restore_and_clean(strong_parts)
            if cand_parts and all(len(tokenize_vietnamese_for_bm25(p, include_bigrams=False)) >= 3 for p in cand_parts):
                parts = cand_parts
        else:
            # Ưu tiên 2: Liên từ mềm ('hoặc' / 'hay' / 'và') chỉ tách khi thực sự là 2 hành vi hoặc 2 mệnh đề hỏi
            soft_parts = re.split(r"\s*(?:\bhoặc\b|\bhay\b|\bvà\b)\s*", protected, flags=re.IGNORECASE)
            if not (2 <= len(soft_parts) <= 3):
                return []
            cand_parts = _restore_and_clean(soft_parts)
            if not cand_parts or any(len(re.findall(r"[^\W_]+", p)) < 2 for p in cand_parts):
                return []

            behavior_verb_re = re.compile(
                r"(?i)\b(?:"
                r"không\s+đi|đi\s+muộn|đi\s+trễ|vắng|nghỉ|bỏ\s+(?:thi|học|họp|sinh\s+hoạt)|"
                r"thi\s+hộ|thi\s+thay|học\s+hộ|học\s+thay|nhờ\s+(?:thi|học|làm)|"
                r"mang(?:\s+tài\s+liệu)?|đem(?:\s+tài\s+liệu)?|sử\s+dụng(?:\s+tài\s+liệu|\s+điện\s+thoại)?|"
                r"gian\s+lận|làm\s+giả|giả\s+mạo|sao\s+chép|đánh\s+nhau|gây\s+rối|xúc\s+phạm|"
                r"tổ\s+chức|đăng\s+tải|chia\s+sẻ|tiết\s+lộ|khai\s+man|chiếm\s+đoạt|hủy\s+hoại|"
                r"xâm\s+phạm|vi\s+phạm|hiến\s+máu|tham\s+gia(?!\s+xét)|rút\s+môn|bảo\s+lưu|"
                r"nộp\s+muộn|chậm\s+nộp|trốn|chống\s+đối|tuyên\s+truyền"
                r")\b"
            )
            interrogative_re = re.compile(
                r"(?i)\b(?:bao\s+nhiêu|mấy|thế\s+nào|như\s+thế\s+nào|ra\s+sao|mức\s+nào|gồm\s+những\s+gì|ở\s+đâu)\b"
            )
            cond_start_re = re.compile(r"^(?:nếu|khi|trường\s+hợp|còn)\b", flags=re.IGNORECASE)

            all_have_behavior_verb = all(behavior_verb_re.search(p) for p in cand_parts)
            dual_question_clauses = (
                bool(interrogative_re.search(cand_parts[0]))
                and any(bool(cond_start_re.match(p)) or bool(interrogative_re.search(p)) for p in cand_parts[1:])
            )
            if not (all_have_behavior_verb or dual_question_clauses):
                return []
            parts = cand_parts

        if not parts:
            return []

        subj_match = re.match(
            r"^(?:(?:khi|nếu|trường\s+hợp)\s+)?(?:sinh\s+viên|người\s+học)\b",
            parts[0],
            flags=re.IGNORECASE,
        )
        shared_subj = subj_match.group(0).strip() if subj_match else ""

        tail_match = re.search(
            r"\b((?:thì\s+)?(?:sẽ\s+|có\s+)?(?:bị|được|phải)\s+(?:trừ|cộng|xử\s+lý|xử\s+phạt|kỷ\s+luật|miễn|giảm|hoàn|tính|xét|nộp|hưởng|làm|chịu)\b.{0,50}|(?:quy\s+định|xử\s+lý|tính|xét)\s+(?:như\s+thế\s+nào|thế\s+nào|ra\s+sao)|bao\s+nhiêu\b.{0,30}|như\s+thế\s+nào|thế\s+nào|ra\s+sao|gồm\s+những\s+gì)$",
            parts[-1],
            flags=re.IGNORECASE,
        )
        shared_tail = ""
        if tail_match and len(tail_match.group(0)) < len(parts[-1]) * 0.72:
            shared_tail = tail_match.group(0).strip()

        enriched = []
        for i, part in enumerate(parts):
            clause = part
            if i > 0 and shared_subj and not re.match(r"^(?:khi|nếu|trường\s+hợp|sinh\s+viên|người\s+học)\b", clause, flags=re.IGNORECASE):
                clause = f"{shared_subj} {clause}"
            if i < len(parts) - 1 and shared_tail:
                c_low = clause.lower()
                if not any(m in c_low for m in ("bao nhiêu", "thế nào", "ra sao", "gồm những gì", "bị trừ", "bị xử lý", "kỷ luật")):
                    clause = f"{clause} {shared_tail}"
            clause = re.sub(r"\s+", " ", clause).strip()
            if len(tokenize_vietnamese_for_bm25(clause, include_bigrams=False)) < 3:
                return []
            if q_punct and not clause.endswith("?"):
                clause = f"{clause}{q_punct}"
            enriched.append(clause)
        return enriched

    def _retrieve_single_query(self, q_str: str, k: int = 6):
        """
        Truy xuất Hybrid Search đơn cho một vế/câu hỏi:
        Dense Vector (ChromaDB) + Lexical BM25 (rank_bm25) + Reciprocal Rank Fusion (RRF)
        + Mở rộng tự động trang liền kề cho bảng biểu/phụ lục vắt trang + Dual Refusal Gate.
        """
        q_clean = self._prepare_retrieval_query(q_str)
        q_lower = q_clean.lower()
        if not q_lower:
            self.last_retrieval_debug = {"reason": "empty_query", "accepted": False}
            return []

        if is_greeting_or_chitchat(q_str):
            self.last_retrieval_debug = {"reason": "greeting_or_chitchat", "accepted": False}
            return []

        if self._is_excluded_resolution_query(q_lower) or self._is_explicit_out_of_scope_query(q_lower):
            self.last_retrieval_debug = {"reason": "excluded_or_explicit_oos", "accepted": False}
            return []

        # 1. Truy xuất Dense Vector từ ChromaDB
        try:
            dense_results = self.vector_db.similarity_search_with_relevance_scores(
                q_clean, k=max(HYBRID_DENSE_CANDIDATES, k * 4)
            )
        except Exception:
            global _GLOBAL_VECTOR_DB
            _GLOBAL_VECTOR_DB = None
            self.vector_db = get_vector_db()
            dense_results = self.vector_db.similarity_search_with_relevance_scores(
                q_clean, k=max(HYBRID_DENSE_CANDIDATES, k * 4)
            )

        bm25_data = get_bm25_index()
        docs_corpus = bm25_data["docs"]
        unigram_sets = bm25_data["unigram_sets"]
        meta_unigram_sets = bm25_data.get("meta_unigram_sets", [])
        meta_bigram_sets = bm25_data.get("meta_bigram_sets", [])
        raw_idf = bm25_data["raw_idf"]
        page_map = bm25_data["page_map"]
        doc_key_to_idx = bm25_data["doc_key_to_idx"]
        bm25_engine = bm25_data["bm25"]
        departments = load_departments_config()

        dense_rank = {}
        dense_score = {}
        extra_dense_docs = []
        max_dense_score = 0.0
        rank_counter = 0

        for doc, rel_score in dense_results:
            src_name = os.path.basename(str(doc.metadata.get("source", ""))).lower()
            if src_name in EXCLUDED_SOURCE_FILES or src_name.startswith("nghi_quyet_"):
                continue
            score_val = float(rel_score)
            if score_val > max_dense_score:
                max_dense_score = score_val
            try:
                page_num = int(doc.metadata.get("page", 1))
            except Exception:
                page_num = 1
            doc_key = (src_name, page_num, doc.page_content.strip())
            idx = doc_key_to_idx.get(doc_key)
            if idx is not None:
                if idx not in dense_rank:
                    rank_counter += 1
                    dense_rank[idx] = rank_counter
                    dense_score[idx] = score_val
            else:
                ensure_doc_department_metadata(doc, departments)
                doc.metadata["similarity_score"] = score_val
                extra_dense_docs.append(doc)

        # 2. Chấm điểm Lexical BM25 toàn corpus
        q_tokens = tokenize_vietnamese_for_bm25(q_clean, include_bigrams=True)
        bm25_rank = {}
        bm25_score_map = {}
        max_bm25_score = 0.0

        if bm25_engine is not None and q_tokens:
            raw_scores = bm25_engine.get_scores(q_tokens)
            ranked_bm25 = sorted(
                ((i, float(s)) for i, s in enumerate(raw_scores) if float(s) > 0.0),
                key=lambda x: x[1],
                reverse=True,
            )
            if ranked_bm25:
                max_bm25_score = ranked_bm25[0][1]
            for pos, (idx, sc) in enumerate(ranked_bm25[:max(HYBRID_BM25_CANDIDATES, k * 4)], 1):
                bm25_rank[idx] = pos
                bm25_score_map[idx] = sc

        # 3. Dual Refusal Gate tổng quát (Dense + BM25 + Độ phủ IDF từ vựng & Tiêu đề tài liệu động)
        q_unigrams = []
        seen_u = set()
        for u in tokenize_vietnamese_for_bm25(q_clean, include_bigrams=False):
            if len(u) >= 2 and u not in seen_u:
                seen_u.add(u)
                q_unigrams.append(u)

        q_b_set_gate = {t for t in q_tokens if "_" in t}
        total_q_idf = sum(raw_idf.get(u, 2.2) for u in q_unigrams) or 1.0
        eval_candidates = set(list(dense_rank.keys())[:15]) | set(list(bm25_rank.keys())[:15])
        best_idf_cov = 0.0
        has_doc_title_anchor = False

        for idx in eval_candidates:
            d_set = unigram_sets[idx]
            if idx < len(meta_unigram_sets):
                d_set = d_set | meta_unigram_sets[idx]
                meta_u_hits = len(seen_u & meta_unigram_sets[idx])
                meta_b_hits = len(q_b_set_gate & meta_bigram_sets[idx]) if idx < len(meta_bigram_sets) else 0
                if meta_b_hits >= 2 or meta_u_hits >= 3:
                    has_doc_title_anchor = True
            matched_idf = sum(raw_idf.get(u, 2.2) for u in q_unigrams if u in d_set)
            cov = matched_idf / total_q_idf
            if cov > best_idf_cov:
                best_idf_cov = cov

        dense_strong = (max_dense_score >= HYBRID_STRONG_DENSE) and (
            best_idf_cov >= HYBRID_IDF_COV_FLOOR or max_bm25_score >= HYBRID_MIN_BM25_WITH_DENSE
        )
        lexical_strong = (
            (max_bm25_score >= HYBRID_STRONG_BM25)
            and (best_idf_cov >= HYBRID_IDF_COV_STRONG)
            and (max_dense_score >= 0.36)
        ) or (
            (max_bm25_score >= 44.0)
            and (best_idf_cov >= 0.48)
            and (max_dense_score >= 0.28)
        )
        both_moderate = (
            (max_dense_score >= HYBRID_SIM_FLOOR)
            and (max_bm25_score >= HYBRID_MIN_BM25_WITH_DENSE)
            and (best_idf_cov >= 0.38)
        ) or (
            (max_dense_score >= 0.43)
            and (max_bm25_score >= 18.0)
            and (best_idf_cov >= 0.37)
        ) or (
            has_doc_title_anchor
            and (max_bm25_score >= 16.0)
            and (max_dense_score >= 0.33)
            and (best_idf_cov >= 0.32)
        )
        accepted = bool(dense_strong or lexical_strong or both_moderate)

        self.last_retrieval_debug = {
            "max_dense": round(max_dense_score, 4),
            "max_bm25": round(max_bm25_score, 4),
            "best_idf_cov": round(best_idf_cov, 4),
            "accepted": accepted,
            "reason": (
                "dense_strong" if dense_strong else (
                    "lexical_strong" if lexical_strong else (
                        "both_moderate" if both_moderate else "dual_refusal_gate"
                    )
                )
            ),
        }
        if not accepted:
            return []

        # 4. Hợp nhất xếp hạng bằng Reciprocal Rank Fusion (RRF) + đồng thuận tiêu đề & từ hiếm IDF cao
        candidate_indices = set(dense_rank.keys()) | set(bm25_rank.keys())
        q_u_set = set(q_unigrams)
        q_b_set = {t for t in q_tokens if "_" in t}
        rare_q_terms = {u: raw_idf[u] for u in q_unigrams if raw_idf.get(u, 0.0) >= 2.2}
        total_rare_idf = sum(rare_q_terms.values()) or 1.0

        rrf_scores = {}
        for idx in candidate_indices:
            r_d = dense_rank.get(idx)
            r_b = bm25_rank.get(idx)
            score = 0.0
            if r_d is not None:
                score += HYBRID_DENSE_WEIGHT / (HYBRID_RRF_K + r_d)
            if r_b is not None:
                score += HYBRID_BM25_WEIGHT / (HYBRID_RRF_K + r_b)
            if r_d is not None and r_d <= 8 and r_b is not None and r_b <= 8:
                score += 0.0025
            if rare_q_terms:
                d_u_set = unigram_sets[idx]
                matched_rare = sum(w for u, w in rare_q_terms.items() if u in d_u_set)
                score += 0.015 * (matched_rare / total_rare_idf)
            if idx < len(meta_unigram_sets) and q_u_set:
                meta_hits = len(q_u_set & meta_unigram_sets[idx])
                meta_b_hits = len(q_b_set & meta_bigram_sets[idx]) if idx < len(meta_bigram_sets) else 0
                if meta_b_hits >= 2 or meta_hits >= 4:
                    score += 0.025 * min((meta_hits + 2 * meta_b_hits) / max(len(q_u_set) + 2, 1), 1.0)
                elif meta_hits >= 2:
                    score += 0.005 * (meta_hits / max(len(q_u_set), 1))
            rrf_scores[idx] = score

        sorted_indices = sorted(
            candidate_indices,
            key=lambda i: (rrf_scores[i], bm25_score_map.get(i, 0.0), dense_score.get(i, 0.0)),
            reverse=True,
        )

        # Lấy top k tài liệu RRF chính, bảo đảm Top-1 của mỗi kênh luôn nằm trong nhóm neo đầu (<= vị trí 2)
        selected_indices = list(sorted_indices[:k])
        top_bm25_indices = [idx for idx, _r in sorted(bm25_rank.items(), key=lambda x: x[1])[:2]]
        top_dense_indices = [idx for idx, _r in sorted(dense_rank.items(), key=lambda x: x[1])[:2]]

        if top_bm25_indices and top_bm25_indices[0] not in selected_indices[:3]:
            b0 = top_bm25_indices[0]
            if b0 in selected_indices:
                selected_indices.remove(b0)
            else:
                selected_indices.pop()
            selected_indices.insert(min(1, len(selected_indices)), b0)

        for must_idx in top_bm25_indices[1:] + top_dense_indices:
            if must_idx not in selected_indices and len(selected_indices) > 0:
                for rep_pos in range(len(selected_indices) - 1, 2, -1):
                    cand_rep = selected_indices[rep_pos]
                    if cand_rep not in top_bm25_indices and cand_rep not in top_dense_indices:
                        selected_indices[rep_pos] = must_idx
                        break
        selected_set = set(selected_indices)

        # 5. Mở rộng ngữ cảnh liên tục có phân bổ công bằng cho Top-4 neo (tối đa 2-3 đoạn/neo)
        # Giúp không để neo đầu chiếm hết ngân sách và nối trọn vẹn Điều dài + Bảng vắt trang
        adjacent_extras = []
        max_neighbor_adds = 4
        max_total = 7
        for anchor_pos, anchor_idx in enumerate(selected_indices[:4]):
            if len(adjacent_extras) >= max_neighbor_adds:
                break
            anchor_doc = docs_corpus[anchor_idx]
            src_name = os.path.basename(str(anchor_doc.metadata.get("source", ""))).lower()
            try:
                page_num = int(anchor_doc.metadata.get("page", 1))
            except Exception:
                page_num = 1
            same_page_indices = page_map.get((src_name, page_num), [])
            is_table_like = self._looks_like_table_or_split_page(anchor_doc.page_content, len(same_page_indices))
            starts_with_heading = bool(re.match(r"^\s*(?:Điều\s+\d+|Chương\s+)", anchor_doc.page_content, flags=re.IGNORECASE))

            neighbor_candidates = []
            # Khi đoạn neo không bắt đầu bằng tiêu đề Điều/Chương, luôn ưu tiên đưa đoạn liền trước (-1)
            # cùng file nguồn lên đầu danh sách để nối trọn vẹn phần đầu các điều dài vắt qua trang
            has_prev_same_src = False
            if anchor_idx - 1 >= 0:
                prv_src = os.path.basename(str(docs_corpus[anchor_idx - 1].metadata.get("source", ""))).lower()
                if prv_src == src_name:
                    has_prev_same_src = True
                    if not starts_with_heading:
                        neighbor_candidates.append(anchor_idx - 1)

            # Các đoạn cùng trang để giữ đủ Khoản a, b, c của cùng một Điều
            for sibling_idx in same_page_indices:
                if sibling_idx != anchor_idx and sibling_idx not in neighbor_candidates:
                    neighbor_candidates.append(sibling_idx)
            # Nối tiếp trang kế tiếp (+1), bổ sung đoạn liền trước (-1) nếu là bảng/đầu trang khi đã có tiêu đề
            tail_base = same_page_indices[-1] if same_page_indices else anchor_idx
            if tail_base + 1 < len(docs_corpus):
                nxt_src = os.path.basename(str(docs_corpus[tail_base + 1].metadata.get("source", ""))).lower()
                if nxt_src == src_name and (tail_base + 1) not in neighbor_candidates:
                    neighbor_candidates.append(tail_base + 1)
            if has_prev_same_src and (anchor_idx - 1) not in neighbor_candidates:
                if is_table_like or (same_page_indices and anchor_idx == same_page_indices[0]):
                    neighbor_candidates.append(anchor_idx - 1)
            extra_forward_steps = (2, 3) if anchor_pos == 0 else (2,)
            for step in extra_forward_steps:
                cand_idx = tail_base + step
                if cand_idx < len(docs_corpus):
                    nxt_src = os.path.basename(str(docs_corpus[cand_idx].metadata.get("source", ""))).lower()
                    if nxt_src == src_name and cand_idx not in neighbor_candidates:
                        neighbor_candidates.append(cand_idx)

            per_anchor_cap = 3 if anchor_pos == 0 else 2
            added_for_anchor = 0
            for nb_idx in neighbor_candidates:
                if nb_idx not in selected_set and nb_idx not in adjacent_extras:
                    adjacent_extras.append(nb_idx)
                    added_for_anchor += 1
                    if len(adjacent_extras) >= max_neighbor_adds or added_for_anchor >= per_anchor_cap:
                        break

        # Chèn đoạn nối trang liền kề ngay sau 3 kết quả anchor chính để luôn giữ đủ cả đoạn trước và đoạn sau của anchor đầu trong docs[:5]
        insert_pos = min(3, len(selected_indices))
        ordered_indices = selected_indices[:insert_pos] + adjacent_extras + selected_indices[insert_pos:]

        result_docs = []
        for idx in ordered_indices[:max_total]:
            base_doc = docs_corpus[idx]
            meta_copy = dict(base_doc.metadata)
            meta_copy["similarity_score"] = round(dense_score.get(idx, max(HYBRID_SIM_FLOOR, max_dense_score)), 4)
            meta_copy["bm25_score"] = round(bm25_score_map.get(idx, 0.0), 4)
            meta_copy["rrf_score"] = round(rrf_scores.get(idx, 0.0), 6)
            result_docs.append(Document(page_content=base_doc.page_content, metadata=meta_copy))

        if not result_docs and extra_dense_docs:
            return extra_dense_docs[:k]
        return result_docs

    def filter_documents(self, query: str, k: int = 6):
        """
        Truy xuất Hybrid Search tổng quát (hỗ trợ cả câu đơn lẫn câu hỏi ghép nhiều vế):
        Với câu hỏi ghép nhiều hành vi/quy định độc lập, truy xuất cho cả câu đầy đủ lẫn
        từng vế con rồi trộn xen kẽ (round-robin, khử trùng lặp) tối đa 7 đoạn trích.
        """
        raw_q = str(query or "")
        if len(raw_q) > MAX_QUERY_LENGTH or is_prompt_injection(raw_q):
            self.last_retrieval_debug = {"reason": "security_or_length_block", "accepted": False}
            return []
        norm_query = normalize_chat_slang(raw_q)
        if is_greeting_or_chitchat(norm_query):
            self.last_retrieval_debug = {"reason": "greeting_or_chitchat", "accepted": False}
            return []
        q_low_raw = norm_query.lower()
        if self._is_excluded_resolution_query(q_low_raw) or self._is_explicit_out_of_scope_query(q_low_raw):
            self.last_retrieval_debug = {"reason": "excluded_or_explicit_oos", "accepted": False}
            return []

        prepared_query = self._prepare_retrieval_query(norm_query)
        primary_docs = self._retrieve_single_query(prepared_query, k=k)
        primary_debug = dict(self.last_retrieval_debug)

        sub_clauses = self._split_compound_clauses(prepared_query)
        if not sub_clauses:
            self.last_retrieval_debug = primary_debug
            return primary_docs

        clause_doc_lists = []
        for clause in sub_clauses:
            c_docs = self._retrieve_single_query(clause, k=k)
            if c_docs:
                clause_doc_lists.append(c_docs)

        all_lists = ([primary_docs] if primary_docs else []) + clause_doc_lists
        if not all_lists:
            self.last_retrieval_debug = primary_debug
            return []

        merged_docs = []
        seen_keys = set()
        max_merged = 7
        max_len = max(len(lst) for lst in all_lists)

        for pos in range(max_len):
            for lst in all_lists:
                if pos >= len(lst):
                    continue
                doc = lst[pos]
                src_name = os.path.basename(str(doc.metadata.get("source", ""))).lower()
                try:
                    page_num = int(doc.metadata.get("page", 1))
                except Exception:
                    page_num = 1
                dedup_key = (src_name, page_num, doc.page_content.strip())
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                merged_docs.append(doc)
                if len(merged_docs) >= max_merged:
                    break
            if len(merged_docs) >= max_merged:
                break

        self.last_retrieval_debug = {
            **primary_debug,
            "accepted": bool(merged_docs),
            "compound_clauses": sub_clauses,
            "merged_count": len(merged_docs),
        }
        return merged_docs

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
        for doc in docs[:5]:
            src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
            page = doc.metadata.get("page", 1)
            header_line = f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
            context_parts.append(f"{header_line}\n{clip_context_text(doc.page_content)}")

        context_str = "\n\n".join(context_parts)
        formatted_prompt = self.prompt.format(context=context_str, input=query)
        try:
            raw_answer = self.llm.invoke(formatted_prompt)
        except Exception as llm_err:
            fallback_ans = build_extractive_offline_fallback(query, docs, err=llm_err)
            return {
                "answer": fallback_ans,
                "context": docs,
                "is_refusal": False,
                "api_error": True,
                "offline_fallback": True,
            }
        answer = raw_answer if isinstance(raw_answer, str) else getattr(raw_answer, 'content', str(raw_answer))
        answer = sanitize_no_markdown_tables(answer)
        is_refusal = is_llm_refusal_answer(answer)

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
_GLOBAL_REWRITER_LLM = None
_GLOBAL_BM25_DATA = None
_LAST_DATA_DIR_SIGNATURE = None
_DEAD_GROQ_MODELS = set()
_COOLDOWN_GROQ_MODELS: dict[str, float] = {}
_GROQ_CLIENTS_CACHE = {}
_TOML_SECRETS_CACHE: dict | None = None
_CURRENT_KEY_INDEX = 0
_CURRENT_GROQ_KEY_INDEX = 0
_GROQ_STATE_LOCK = threading.Lock()

MAX_CONTEXT_SNIPPET_CHARS = 680


_THINK_CLOSED_RE = re.compile(r"<think(?:ing)?\b[^>]*>.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
_THINK_UNCLOSED_TAIL_RE = re.compile(r"<think(?:ing)?\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)
_THINK_ORPHAN_CLOSE_RE = re.compile(r"</think(?:ing)?>", re.IGNORECASE)


def strip_think_tags(text: str) -> str:
    """Loại bỏ triệt để mọi thẻ suy luận <think>...</think> hoặc <thinking>...</thinking> (kể cả chưa đóng)."""
    if not text:
        return ""
    s = str(text)
    s = _THINK_CLOSED_RE.sub("", s)
    s = _THINK_UNCLOSED_TAIL_RE.sub("", s)
    s = _THINK_ORPHAN_CLOSE_RE.sub("", s)
    return re.sub(r"^\s*\n+", "", s).lstrip(" \t") if s.startswith(("\n", " ", "\t")) and "<think" in str(text).lower() else s.strip()


class ThinkTagStreamFilter:
    """
    Bộ lọc trạng thái (Stateful O(1) Memory Stream Filter) cắt bỏ hoàn toàn khối <think>...</think>
    và <thinking>...</thinking> theo thời gian thực ngay cả khi thẻ bị xẻ nhỏ qua nhiều chunk SSE.
    Giữ nguyên các ký tự toán học bình thường như '< 2,5' hoặc '< 80%' mà không làm trễ luồng chữ.
    """

    _OPEN_TAG_RE = re.compile(r"<think(?:ing)?(?:\s[^>]*)?>", re.IGNORECASE)
    _CLOSE_TAG_RE = re.compile(r"</think(?:ing)?>", re.IGNORECASE)
    _PARTIAL_OPEN_RE = re.compile(
        r"<(?:t(?:h(?:i(?:n(?:k(?:i(?:n(?:g)?)?)?)?)?)?)?)?(?:\s[^>]*)?$",
        re.IGNORECASE,
    )
    _PARTIAL_OPEN_ATTR_RE = re.compile(r"<think(?:ing)?\b[^>]*$", re.IGNORECASE)
    _PARTIAL_CLOSE_RE = re.compile(
        r"<(?:/(?:t(?:h(?:i(?:n(?:k(?:i(?:n(?:g)?)?)?)?)?)?)?)?)?$",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._buf: str = ""
        self._in_think: bool = False
        self._emitted_any_visible: bool = False
        self._trim_leading_ws: bool = False

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buf += str(chunk)
        out_parts: list[str] = []

        while self._buf:
            if self._in_think:
                m_close = self._CLOSE_TAG_RE.search(self._buf)
                if m_close:
                    self._buf = self._buf[m_close.end():]
                    self._trim_leading_ws = not self._emitted_any_visible
                    self._in_think = False
                    continue

                m_part_close = self._PARTIAL_CLOSE_RE.search(self._buf)
                self._buf = m_part_close.group(0) if m_part_close else ""
                break

            if self._trim_leading_ws:
                self._buf = self._buf.lstrip("\r\n ")
                if not self._buf:
                    break
                self._trim_leading_ws = False

            m_open = self._OPEN_TAG_RE.search(self._buf)
            if m_open:
                before = self._buf[:m_open.start()]
                if before:
                    out_parts.append(before)
                    self._emitted_any_visible = True
                self._buf = self._buf[m_open.end():]
                self._in_think = True
                continue

            hold_idx = len(self._buf)
            m_attr = self._PARTIAL_OPEN_ATTR_RE.search(self._buf)
            if m_attr:
                hold_idx = min(hold_idx, m_attr.start())
            else:
                m_part = self._PARTIAL_OPEN_RE.search(self._buf)
                if m_part:
                    hold_idx = min(hold_idx, m_part.start())

            emit_text = self._buf[:hold_idx]
            if emit_text:
                out_parts.append(emit_text)
                self._emitted_any_visible = True
            self._buf = self._buf[hold_idx:]
            break

        return "".join(out_parts)

    def flush(self) -> str:
        if self._in_think:
            self._buf = ""
            self._in_think = False
            return ""
        rem = self._buf
        self._buf = ""
        if rem:
            self._emitted_any_visible = True
        return rem


def is_llm_refusal_answer(text: str) -> bool:
    """
    Nhận diện thống nhất mọi phản hồi từ chối ngoài phạm vi / gián đoạn / lỗi hệ thống từ LLM
    (sau khi loại bỏ thẻ <think>) để đồng bộ chuẩn xác verified=False & contact=None.
    Bảo vệ câu trả lời ghép 'nửa trong – nửa ngoài' (Hybrid) có trích xuất quy định hợp lệ.
    """
    cleaned = strip_think_tags(text or "").strip()
    t = cleaned.lower()
    if not t:
        return True
    if REFUSAL_MESSAGE.lower() in t:
        return True
    if "phản hồi bị gián đoạn giữa chừng" in t:
        return True
    if "lượng truy cập cao" in t or "đợi khoảng 30–60 giây" in t:
        return True
    if "tạm thời bận hoặc gián đoạn kết nối" in t or "vượt quá độ dài cho phép" in t:
        return True

    refusal_cues = (
        "không được đề cập",
        "nằm ngoài phạm vi dữ liệu",
        "ngoài phạm vi dữ liệu quy chế",
        "tài liệu không quy định",
        "tài liệu tham khảo không quy định",
        "văn bản hiện tại không quy định",
        "văn bản quy chế không đề cập",
        "tài liệu được cung cấp không đề cập",
        "chưa quy định về",
        "chưa được quy định trong",
        "không có quy định về",
        "không tìm thấy quy định",
        "không có thông tin trong tài liệu",
    )
    if any(cue in t for cue in refusal_cues):
        has_hybrid_affirmative_bullets = False
        if len(t) >= 220:
            bullets = [ln.strip() for ln in cleaned.splitlines() if ln.strip().startswith(("-", "*", "•"))]
            affirmative_cues = ("tín chỉ", "học bổng", "miễn", "giảm", "học phí", "ngày ctxh", "điều ", "thang ")
            for b in bullets:
                b_low = b.lower()
                if not any(cue in b_low for cue in refusal_cues) and any(ac in b_low for ac in affirmative_cues):
                    has_hybrid_affirmative_bullets = True
                    break
        if not has_hybrid_affirmative_bullets:
            return True

    has_legal_citation = bool(
        re.search(r"\b(?:điều|khoản|mục|chương|quyết\s+định|phụ\s+lục)\s+[ivxlcdm\d]+", t)
    )
    if len(t) < 220 and not has_legal_citation and any(kw in t for kw in ("không được đề cập", "ngoài phạm vi dữ liệu")):
        return True
    return False


def sanitize_no_markdown_tables(text: str) -> str:
    """
    Hậu xử lý đảm bảo tuyệt đối không còn thẻ <think>, bảng kẻ bằng dấu gạch đứng (| ... |) hoặc thẻ <br>:
    Tự động chuyển mọi bảng Markdown (nhiều dòng hoặc bị gộp 1 dòng) thành các gạch đầu dòng phân cấp rõ ràng.
    """
    if not text:
        return ""
    s = strip_think_tags(str(text))
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "; ", s, flags=re.IGNORECASE)

    # Nếu bảng Markdown bị gộp trên cùng 1 dòng (ví dụ: "| Cột 1 | Cột 2 | |---|---| | A | B |")
    if "|---" in s or "| ---" in s or " :---" in s:
        s = re.sub(r"\|\s*\|\s*(?=[-:]+\s*\|)", "|\n|", s)
        s = re.sub(r"(\|[\s\-:]+\|)\s*\|", r"\1\n|", s)
        s = re.sub(r"\|\s*\|\s*(?=\*\*|[A-Za-zÀ-ỹ0-9])", "|\n|", s)

    lines = s.splitlines()
    out_lines: list[str] = []
    i = 0
    n = len(lines)

    def _split_pipe_row(row_line: str) -> list[str]:
        inner = row_line.strip()
        if inner.startswith("|"):
            inner = inner[1:]
        if inner.endswith("|"):
            inner = inner[:-1]
        return [re.sub(r"\s+", " ", c).strip() for c in inner.split("|")]

    def _is_sep_row(cells: list[str]) -> bool:
        return bool(cells) and all(not c or bool(re.match(r"^[:\-]+$", c)) for c in cells)

    while i < n:
        line_str = lines[i].strip()
        if line_str.count("|") >= 2 and (line_str.startswith("|") or (i + 1 < n and re.search(r"\|[\s\-:]+\|", lines[i + 1]))):
            table_rows: list[list[str]] = []
            while i < n and lines[i].strip().count("|") >= 2:
                cells = _split_pipe_row(lines[i])
                if cells and any(cells):
                    table_rows.append(cells)
                i += 1

            has_sep = any(_is_sep_row(r) for r in table_rows)
            data_rows = [r for r in table_rows if not _is_sep_row(r)]
            if has_sep and len(data_rows) >= 2:
                headers = [re.sub(r"^\*\*|\*\*$", "", h).strip() for h in data_rows[0]]
                last_first_col = ""
                for r in data_rows[1:]:
                    if not any(r):
                        continue
                    c0 = r[0].strip() if len(r) > 0 else ""
                    if c0 in ("", "-", "–", "—") and last_first_col:
                        c0 = last_first_col
                    elif c0:
                        last_first_col = c0
                    c0_clean = re.sub(r"^\*\*|\*\*$", "", c0).strip()
                    sub_parts = []
                    for col_idx in range(1, len(r)):
                        val = r[col_idx].strip()
                        if not val or val in ("-", "–", "—"):
                            continue
                        hdr = headers[col_idx] if col_idx < len(headers) and headers[col_idx] else f"Cột {col_idx + 1}"
                        sub_parts.append(f"{hdr}: {val}")
                    if c0_clean and sub_parts:
                        out_lines.append(f"- **{c0_clean}**:")
                        for sp in sub_parts:
                            out_lines.append(f"  - {sp}")
                    elif c0_clean:
                        out_lines.append(f"- **{c0_clean}**")
                    elif sub_parts:
                        out_lines.append("- " + "; ".join(sub_parts))
                continue
            else:
                for r in data_rows:
                    non_empty = [c for c in r if c and c not in ("-", "–", "—")]
                    if non_empty:
                        out_lines.append("- " + " — ".join(non_empty))
                continue

        out_lines.append(lines[i])
        i += 1

    return "\n".join(out_lines).strip()


def clip_context_text(text: str, max_chars: int = MAX_CONTEXT_SNIPPET_CHARS) -> str:
    """Giới hạn độ dài mỗi đoạn trích đưa vào prompt LLM để tiết kiệm token và tránh chạm trần TPM."""
    clean = str(text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "..."

# Tham số tổng quát cho Hybrid Search (Dense + BM25 + RRF + Dual Refusal Gate)
HYBRID_RRF_K = 20
HYBRID_DENSE_WEIGHT = 1.0
HYBRID_BM25_WEIGHT = 1.35
HYBRID_DENSE_CANDIDATES = 30
HYBRID_BM25_CANDIDATES = 30
HYBRID_SIM_FLOOR = 0.39
HYBRID_STRONG_DENSE = 0.51
HYBRID_STRONG_BM25 = 32.5
HYBRID_MIN_BM25_WITH_DENSE = 29.0
HYBRID_IDF_COV_STRONG = 0.44
HYBRID_IDF_COV_FLOOR = 0.35

# Chuẩn hóa viết tắt hành chính phổ biến tại VLUTE để BM25 nhận diện đồng nhất
_ACADEMIC_ACRONYM_EXPANSIONS = {
    "ctsv": ("công", "tác", "sinh", "viên"),
    "ctxh": ("công", "tác", "xã", "hội"),
    "kkht": ("khuyến", "khích", "học", "tập"),
    "attt": ("an", "toàn", "thông", "tin"),
    "khtc": ("kế", "hoạch", "tài", "chính"),
    "cvht": ("cố", "vấn", "học", "tập"),
    "cbvc": ("cán", "bộ", "viên", "chức"),
    "cđr": ("chuẩn", "đầu", "ra"),
    "cdr": ("chuẩn", "đầu", "ra"),
    "ctđt": ("chương", "trình", "đào", "tạo"),
    "đrl": ("điểm", "rèn", "luyện"),
    "drl": ("điểm", "rèn", "luyện"),
}

_ACADEMIC_SYNONYM_BIGRAMS = {
    "thi_hộ": ("thi", "thay", "kiểm", "tra", "thi_thay", "tra_thay"),
    "học_hộ": ("học", "thay", "học_thay"),
    "nhờ_người": ("nhờ", "thay", "thi_thay"),
    "rớt_môn": ("học", "lại", "điểm", "c", "học_lại", "điểm_c"),
    "nợ_môn": ("học", "lại", "điểm", "c", "học_lại", "điểm_c"),
    "môn_học": ("học", "phần", "học_phần"),
    "thầy_cô": ("giảng", "viên", "giảng_viên"),
    "ai_dạy": ("giảng", "viên", "phụ", "trách", "giảng_viên", "phụ_trách"),
    "tính_điểm": ("kiểm", "tra", "đánh", "giá", "hệ", "số", "đánh_giá", "hệ_số"),
    "chấm_điểm": ("kiểm", "tra", "đánh", "giá", "hệ", "số", "đánh_giá", "hệ_số"),
    "trang_phục": ("quy", "tắc", "ứng", "xử", "quy_tắc", "ứng_xử"),
    "mạng_xã": ("quy", "tắc", "ứng", "xử", "quy_tắc", "ứng_xử"),
    "hút_thuốc": ("quy", "tắc", "ứng", "xử", "khuôn", "viên", "ứng_xử"),
    "rượu_bia": ("quy", "tắc", "ứng", "xử", "khuôn", "viên", "ứng_xử"),
}

_BM25_STOPWORDS = frozenset({
    "là", "của", "và", "các", "những", "trong", "cho", "về", "với", "được", "bị",
    "khi", "nào", "gì", "sao", "thế", "tại", "theo", "từ", "đến", "hoặc", "hay",
    "có", "không", "thì", "mà", "này", "đó", "kia", "nếu", "để", "như", "rằng",
    "cái", "việc", "sự", "một", "sẽ", "đã", "đang", "do", "bởi", "qua", "vào",
    "ra", "lên", "xuống", "lại", "nữa", "cũng", "đều", "phải", "cần", "nên",
    "bao", "nhiêu", "làm", "gồm", "vậy", "nhé", "nhỉ", "ạ", "ơi", "vì",
    "trên", "dưới", "sau", "trước", "giữa", "bằng", "nơi", "nhất", "hơn", "kém",
    "từng", "mỗi", "mọi", "tất", "cả", "còn", "hỏi", "xin", "cho_biết", "biết",
    "thế_nào", "như_thế", "như_nào", "ra_sao", "có_thể", "hay_không", "lucas", "ad",
})


def tokenize_vietnamese_for_bm25(text: str, include_bigrams: bool = True) -> list[str]:
    """Chuẩn hóa và tách từ tiếng Việt (unigram + bigram + mã văn bản) cho BM25."""
    if not text:
        return []
    normalized = unicodedata.normalize("NFC", str(text)).lower()
    normalized = re.sub(r"(\d),(\d)", r"\1.\2", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Giữ lại các mã hiệu có gạch nối hoặc gạch chéo (vd: bm-kh-10a, qt-sv-04, 201/qd-dhspktvl)
    compound_codes = re.findall(r"[0-9a-zđ]+(?:[-/][0-9a-zđ]+)+", normalized)

    # Tách từ tiếng Việt và số thập phân (giữ 3.2, 0.5 nhưng bỏ dấu câu cuối câu)
    raw_tokens = re.findall(r"\d+\.\d+|[^\W_]+", normalized, flags=re.UNICODE)
    content_unigrams = []
    for tok in raw_tokens:
        if tok in _BM25_STOPWORDS:
            continue
        content_unigrams.append(tok)
        if tok in _ACADEMIC_ACRONYM_EXPANSIONS:
            content_unigrams.extend(_ACADEMIC_ACRONYM_EXPANSIONS[tok])
        if tok.isdigit() and len(tok) == 2 and tok.startswith("0"):
            content_unigrams.append(tok.lstrip("0") or "0")

    tokens = list(content_unigrams)
    tokens.extend(compound_codes)

    if include_bigrams and len(content_unigrams) >= 2:
        for i in range(len(content_unigrams) - 1):
            bg = f"{content_unigrams[i]}_{content_unigrams[i + 1]}"
            tokens.append(bg)
            if bg in _ACADEMIC_SYNONYM_BIGRAMS:
                tokens.extend(_ACADEMIC_SYNONYM_BIGRAMS[bg])

    return tokens


def _expand_bm25_corpus(raw_docs: list[str], raw_metas: list[dict], departments: dict):
    """Xây dựng chỉ mục BM25Okapi, bản đồ trang (page_map) và trọng số IDF thô."""
    docs = []
    tokenized_docs = []
    unigram_sets = []
    meta_unigram_sets = []
    meta_bigram_sets = []
    doc_key_to_idx = {}
    page_map = {}
    df_counts = {}

    for text, meta in zip(raw_docs, raw_metas):
        if not text or not text.strip():
            continue
        meta_copy = dict(meta or {})
        src_name = os.path.basename(str(meta_copy.get("source", ""))).lower()
        if src_name in EXCLUDED_SOURCE_FILES or src_name.startswith("nghi_quyet_"):
            continue

        doc = Document(page_content=text, metadata=meta_copy)
        ensure_doc_department_metadata(doc, departments)
        try:
            page_num = int(doc.metadata.get("page", 1))
        except Exception:
            page_num = 1

        idx = len(docs)
        docs.append(doc)

        tokens = tokenize_vietnamese_for_bm25(text, include_bigrams=True)
        tokenized_docs.append(tokens)

        u_set = set(tokenize_vietnamese_for_bm25(text, include_bigrams=False))
        unigram_sets.append(u_set)
        # Khi tính df_counts cho IDF, bỏ dòng tiền tố [Tài liệu: ...] lặp trên mọi chunk của cùng 1 file
        # để các từ khóa tiêu đề tài liệu/môn học giữ nguyên trọng số IDF cao.
        body_without_prefix = re.sub(r"^\[(?:Tài liệu|Đề cương học phần):[^\n]+\]\n?", "", text.strip())
        df_u_set = set(tokenize_vietnamese_for_bm25(body_without_prefix or text, include_bigrams=False))
        for u in df_u_set:
            df_counts[u] = df_counts.get(u, 0) + 1

        src_base = os.path.splitext(src_name)[0].replace("_", " ")
        meta_str = f"{doc.metadata.get('title', '')} {doc.metadata.get('doc_code', '')} {src_base}"
        meta_all = set(tokenize_vietnamese_for_bm25(meta_str, include_bigrams=True))
        meta_unigram_sets.append({t for t in meta_all if "_" not in t})
        meta_bigram_sets.append({t for t in meta_all if "_" in t})

        doc_key = (src_name, page_num, text.strip())
        doc_key_to_idx.setdefault(doc_key, idx)
        page_map.setdefault((src_name, page_num), []).append(idx)

    total_docs = max(len(docs), 1)
    raw_idf = {}
    for term, df in df_counts.items():
        val = math.log((total_docs - df + 0.5) / (df + 0.5))
        raw_idf[term] = max(0.30, val)

    bm25 = BM25Okapi(tokenized_docs) if tokenized_docs else None
    return {
        "docs": docs,
        "tokenized_docs": tokenized_docs,
        "unigram_sets": unigram_sets,
        "meta_unigram_sets": meta_unigram_sets,
        "meta_bigram_sets": meta_bigram_sets,
        "bm25": bm25,
        "raw_idf": raw_idf,
        "page_map": page_map,
        "doc_key_to_idx": doc_key_to_idx,
        "total_docs": total_docs,
    }


@st.cache_resource(show_spinner=False)
def get_bm25_index():
    """Khởi tạo và cache chỉ mục BM25 toàn văn từ ChromaDB để phục vụ Hybrid Search."""
    global _GLOBAL_BM25_DATA
    if _GLOBAL_BM25_DATA is not None:
        return _GLOBAL_BM25_DATA

    vector_db = get_vector_db()
    data = vector_db.get(include=["documents", "metadatas"])
    raw_docs = data.get("documents", []) or []
    raw_metas = data.get("metadatas", []) or []
    departments = load_departments_config()
    _GLOBAL_BM25_DATA = _expand_bm25_corpus(raw_docs, raw_metas, departments)
    return _GLOBAL_BM25_DATA


def get_data_dir_signature(data_dir: str = DATA_PATH) -> tuple:
    """Tính nhanh chữ ký (tên, mtime, kích thước) của các tệp hợp lệ trong thư mục data/ (< 5ms)."""
    if not os.path.isdir(data_dir):
        return ()
    excluded_set = set(EXCLUDED_SOURCE_FILES) | {str(f).lower() for f in INGEST_EXCLUDED_FILES}
    sig_items = []
    try:
        with os.scandir(data_dir) as it:
            for entry in it:
                fname = entry.name
                if fname.startswith(("~$", ".")) or not entry.is_file():
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                fname_lower = fname.lower()
                if fname_lower in excluded_set or fname_lower.startswith("nghi_quyet_"):
                    continue
                st_res = entry.stat()
                sig_items.append((fname, round(st_res.st_mtime, 2), st_res.st_size))
    except Exception:
        return ()
    sig_items.sort()
    return tuple(sig_items)


def auto_sync_knowledge_base(force: bool = False) -> dict:
    """
    Kiểm tra chữ ký thư mục data/ với chi phí < 5ms; chỉ đồng bộ ChromaDB & làm mới BM25 RRF
    khi phát hiện có file mới, file sửa đổi hoặc file bị xóa.
    """
    global _LAST_DATA_DIR_SIGNATURE, _GLOBAL_BM25_DATA
    current_sig = get_data_dir_signature(DATA_PATH)
    if not force and _LAST_DATA_DIR_SIGNATURE == current_sig:
        return {"changed": False, "added": [], "updated": [], "deleted": []}

    vector_db = get_vector_db()
    sync_res = sync_knowledge_base_from_data_dir(vector_db=vector_db)
    _LAST_DATA_DIR_SIGNATURE = current_sig

    if sync_res.get("changed"):
        _GLOBAL_BM25_DATA = None
        if "_GLOBAL_SEMANTIC_CACHE" in globals() and _GLOBAL_SEMANTIC_CACHE is not None:
            try:
                _GLOBAL_SEMANTIC_CACHE.clear()
            except Exception:
                pass
        try:
            get_bm25_index.clear()
        except Exception:
            pass
        get_bm25_index()
        print(f"[AUTO-SYNC] Đồng bộ hoàn tất và đã làm mới Hybrid BM25 Index: {sync_res}")

    return sync_res


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


def _load_secrets_toml_fallback() -> dict:
    """Đọc trực tiếp tệp .streamlit/secrets.toml bằng tomllib khi chạy ngoài runtime Streamlit (FastAPI/CLI)."""
    global _TOML_SECRETS_CACHE
    if _TOML_SECRETS_CACHE is not None:
        return _TOML_SECRETS_CACHE

    if tomllib is None:
        _TOML_SECRETS_CACHE = {}
        return _TOML_SECRETS_CACHE

    candidate_paths = (
        Path(__file__).parent / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
    )
    for sec_path in candidate_paths:
        if sec_path.is_file():
            try:
                with open(sec_path, "rb") as f:
                    data = tomllib.load(f)
                if isinstance(data, dict):
                    _TOML_SECRETS_CACHE = data
                    return _TOML_SECRETS_CACHE
            except Exception:
                pass
    _TOML_SECRETS_CACHE = {}
    return _TOML_SECRETS_CACHE


def _collect_secret_or_env_keys(sec_names: tuple[str, ...]) -> list[str]:
    """Đọc key từ st.secrets (nếu trong Streamlit runtime), dự phòng .streamlit/secrets.toml (tomllib) và biến môi trường."""
    raw_keys = []
    in_st_runtime = False
    try:
        rt = getattr(st, "runtime", None)
        if rt is not None and callable(getattr(rt, "exists", None)):
            in_st_runtime = bool(rt.exists())
    except Exception:
        in_st_runtime = False

    if in_st_runtime and hasattr(st, "secrets"):
        try:
            for sec_name in sec_names:
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

    if not raw_keys:
        toml_data = _load_secrets_toml_fallback()
        for sec_name in sec_names:
            if sec_name in toml_data:
                raw_keys.extend(_parse_keys_value(toml_data[sec_name]))

    for env_name in sec_names:
        env_val = os.getenv(env_name)
        if env_val:
            raw_keys.extend(_parse_keys_value(env_val))

    return _parse_keys_value(raw_keys)


def get_all_google_api_keys():
    """
    Đọc danh sách khóa API từ st.secrets, .streamlit/secrets.toml (tomllib) hoặc biến môi trường:
    - Nếu là string (GEMINI_API_KEY): tự động bọc thành list.
    - Nếu là list (GEMINI_API_KEYS): giữ nguyên list.
    - Kiểm tra hợp lệ: Bắt buộc key phải bắt đầu bằng 'AIzaSy' (bỏ qua ngay lập tức các chuỗi
      bắt đầu bằng 'AQ...' hoặc chuỗi rác để tránh treo timeout 40s).
    """
    cleaned = _collect_secret_or_env_keys(("GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEYS", "GOOGLE_API_KEY"))
    # Lọc nghiêm ngặt: Chỉ giữ lại các key Google hợp lệ bắt đầu bằng 'AIzaSy'
    valid_keys = [k for k in cleaned if k.startswith("AIzaSy")]
    return valid_keys


def get_google_api_key():
    """Lấy 1 API key theo cơ chế Round-Robin toàn cục (_CURRENT_KEY_INDEX)."""
    global _CURRENT_KEY_INDEX
    keys = get_all_google_api_keys()
    if not keys:
        return None
    with _GROQ_STATE_LOCK:
        idx = _CURRENT_KEY_INDEX % len(keys)
        _CURRENT_KEY_INDEX = (_CURRENT_KEY_INDEX + 1) % len(keys)
    return keys[idx]


def get_all_groq_api_keys() -> list[str]:
    """Đọc danh sách Groq API key từ GROQ_API_KEYS / GROQ_API_KEY trong st.secrets, secrets.toml hoặc biến môi trường."""
    return _collect_secret_or_env_keys(("GROQ_API_KEYS", "GROQ_API_KEY"))


def get_groq_api_key():
    """
    Lấy Groq API key theo cơ chế Round-Robin khi cấu hình nhiều key (GROQ_API_KEYS);
    tương thích 100% khi chỉ cấu hình 1 key GROQ_API_KEY.
    """
    global _CURRENT_GROQ_KEY_INDEX
    keys = get_all_groq_api_keys()
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    with _GROQ_STATE_LOCK:
        idx = _CURRENT_GROQ_KEY_INDEX % len(keys)
        _CURRENT_GROQ_KEY_INDEX = (_CURRENT_GROQ_KEY_INDEX + 1) % len(keys)
    return keys[idx]


@st.cache_resource(show_spinner=False)
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


@st.cache_resource(show_spinner=False)
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


# ==============================================================================
# SEMANTIC CACHE (REUSE RAM SINGLETON EMBEDDINGS + 3 STRICT GUARDS)
# ==============================================================================
_QUERY_VEC_LOCK = threading.Lock()
_QUERY_VEC_CACHE: "OrderedDict[str, np.ndarray]" = OrderedDict()
_QUERY_VEC_CACHE_MAX = 1024

_SEMANTIC_CACHE_NUMERIC_CODE_RE = re.compile(
    r'\b[a-zA-Z]{2,6}\d{2,6}\b|\d+(?:[.,/-]\d+)*%?'
)
_SEMANTIC_ABBREV_PATTERNS = (
    (re.compile(r'(?<!\w)kkht(?!\w)', re.IGNORECASE), 'khuyến khích học tập'),
    (re.compile(r'(?<!\w)đrl(?!\w)', re.IGNORECASE), 'điểm rèn luyện'),
    (re.compile(r'(?<!\w)ctxh(?!\w)', re.IGNORECASE), 'công tác xã hội'),
    (re.compile(r'(?<!\w)ctsv(?!\w)', re.IGNORECASE), 'công tác sinh viên'),
    (re.compile(r'(?<!\w)attt(?!\w)', re.IGNORECASE), 'an toàn thông tin'),
    (re.compile(r'(?<!\w)khtc(?!\w)', re.IGNORECASE), 'kế hoạch tài chính'),
    (re.compile(r'(?<!\w)cđr(?!\w)', re.IGNORECASE), 'chuẩn đầu ra'),
    (re.compile(r'(?<!\w)bcs(?!\w)', re.IGNORECASE), 'ban cán sự'),
    (re.compile(r'(?<!\w)đoàn\s+phí(?!\w)', re.IGNORECASE), 'đoàn phí'),
    (re.compile(r'(?<!\w)vlute(?!\w)', re.IGNORECASE), 'trường'),
)
_SEMANTIC_FILLER_PHRASES = (
    'làm sao để đủ',
    'làm sao để được',
    'làm sao để',
    'làm thế nào để',
    'như thế nào để',
    'cần những gì để',
    'bao gồm những gì',
    'gồm những gì',
    'là những gì',
    'gồm các',
    'của trường',
    'ở trường',
    'tại trường',
    'cho em hỏi',
    'cho mình hỏi',
    'cho tôi hỏi',
    'cho hỏi',
    'hỏi về',
    'vui lòng cho biết',
    'em muốn hỏi',
    'mình muốn hỏi',
    'cho mình biết',
    'giúp mình',
    'theo quy định',
    'vậy bạn',
    'vậy ạ',
    'mới nhất',
    'hiện nay',
    'chi tiết',
    'cụ thể',
    'xét cấp',
    'bạn ơi',
    'lucas ơi',
    'xin hỏi',
    'ad ơi',
    'bot ơi',
    'là gì',
    'thì sao',
    'như thế nào',
    'xét',
    'cấp',
    'nhận',
    'để',
    'cần',
    'có',
    'được',
    'nhé',
    'ạ',
)
_SEMANTIC_POLARITY_TERMS = (
    'không',
    'chưa',
    'dưới',
    'trên',
    'hơn',
    'tối thiểu',
    'tối đa',
    'cấm',
    'bị',
)
_SEMANTIC_POLARITY_PATTERNS = tuple(
    (term, re.compile(rf'(?<!\w){re.escape(term)}(?!\w)', re.IGNORECASE))
    for term in _SEMANTIC_POLARITY_TERMS
)


def _resolve_existing_embedding_model(chain=None):
    """Tái sử dụng instance vietnamese-bi-encoder đã nạp trong RAM, tuyệt đối không tạo bản sao mới."""
    if chain is not None:
        vdb = getattr(chain, "vector_db", None)
        emb = getattr(vdb, "_embedding_function", None) if vdb is not None else None
        if emb is not None:
            return emb
    if _GLOBAL_EMBEDDINGS is not None:
        return _GLOBAL_EMBEDDINGS
    if _GLOBAL_VECTOR_DB is not None:
        emb = getattr(_GLOBAL_VECTOR_DB, "_embedding_function", None)
        if emb is not None:
            return emb
    return get_embedding_model()


def canonicalize_for_semantic_cache(query: str) -> str:
    """
    Chuẩn hóa câu truy vấn về lõi ngữ nghĩa (giữ nguyên số, mã môn/quyết định và từ phủ định/ngưỡng)
    để nhận diện chuẩn xác paraphrase trên vietnamese-bi-encoder.
    """
    q = normalize_chat_slang(query or "")
    q = unicodedata.normalize("NFC", q).lower().strip()
    for pat, repl in _SEMANTIC_ABBREV_PATTERNS:
        q = pat.sub(repl, q)
    q = re.sub(r'[?!.,;:()\[\]"\'""'']+', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    for phrase in _SEMANTIC_FILLER_PHRASES:
        q = re.sub(rf'(?<!\w){re.escape(phrase)}(?!\w)', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q or unicodedata.normalize("NFC", (query or "")).lower().strip()


def extract_numeric_and_code_tokens(query: str) -> tuple:
    """Trích xuất tập token số học, phần trăm, số quyết định và mã môn/lớp theo thứ tự chuẩn hóa."""
    norm = unicodedata.normalize("NFC", (query or "")).lower()
    tokens = []
    for tok in _SEMANTIC_CACHE_NUMERIC_CODE_RE.findall(norm):
        clean_tok = tok.replace(",", ".").strip()
        if clean_tok:
            tokens.append(clean_tok)
    return tuple(sorted(tokens))


def extract_polarity_signature(query: str) -> tuple:
    """Trích xuất chữ ký phủ định và ngưỡng biên (không, chưa, dưới, trên, hơn, tối thiểu, tối đa, cấm, bị)."""
    norm = unicodedata.normalize("NFC", normalize_chat_slang(query or "")).lower()
    found = []
    for term, pat in _SEMANTIC_POLARITY_PATTERNS:
        matches = pat.findall(norm)
        if matches:
            found.append((term, len(matches)))
    return tuple(found)


def _l2_normalize_vec(vec_raw) -> np.ndarray:
    vec = np.asarray(vec_raw, dtype=np.float32).reshape(-1)
    norm_val = float(np.linalg.norm(vec))
    if norm_val > 1e-12 and abs(norm_val - 1.0) > 1e-4:
        vec = vec / norm_val
    return vec


def encode_queries_l2_batch(texts: list, chain=None) -> list:
    """
    Mã hóa theo lô các chuỗi truy vấn thành vector L2-normalized dùng chung model trong RAM.
    """
    keys = [unicodedata.normalize("NFC", (t or "")).strip() for t in texts]
    results = [None] * len(keys)
    missing_indices = []
    missing_keys = []

    with _QUERY_VEC_LOCK:
        for idx, key in enumerate(keys):
            if not key:
                results[idx] = np.zeros(1, dtype=np.float32)
                continue
            cached_vec = _QUERY_VEC_CACHE.get(key)
            if cached_vec is not None:
                _QUERY_VEC_CACHE.move_to_end(key)
                results[idx] = cached_vec
            else:
                missing_indices.append(idx)
                missing_keys.append(key)

    if not missing_keys:
        return results

    emb_model = _resolve_existing_embedding_model(chain=chain)
    st_client = getattr(emb_model, "_client", None) or getattr(emb_model, "client", None)
    if st_client is not None:
        with torch.inference_mode():
            vecs_raw = st_client.encode(
                missing_keys,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
                batch_size=len(missing_keys),
            )
        encoded = [_l2_normalize_vec(v) for v in vecs_raw]
    else:
        encoded = [_l2_normalize_vec(emb_model.embed_query(k)) for k in missing_keys]

    with _QUERY_VEC_LOCK:
        for idx, key, vec in zip(missing_indices, missing_keys, encoded):
            results[idx] = vec
            _QUERY_VEC_CACHE[key] = vec
            _QUERY_VEC_CACHE.move_to_end(key)
        while len(_QUERY_VEC_CACHE) > _QUERY_VEC_CACHE_MAX:
            _QUERY_VEC_CACHE.popitem(last=False)
    return results


def encode_query_l2_vector(text: str, chain=None) -> np.ndarray:
    """
    Mã hóa câu truy vấn thành vector L2-normalized dùng chung model trong RAM.
    """
    return encode_queries_l2_batch([text], chain=chain)[0]


class SemanticAnswerCache:
    """
    Semantic Cache LRU (tối đa 500 mục, TTL 1800s, thread-safe) dùng Cosine >= 0.95
    kết hợp Numeric/Code Guard và Polarity Guard.
    """

    def __init__(
        self,
        max_size: int = 500,
        ttl_seconds: float = 1800.0,
        similarity_threshold: float = 0.95,
    ):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, dict]" = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _evict_expired_unlocked(self, now: float) -> None:
        expired_keys = [
            k for k, v in self._entries.items()
            if (now - v["created_at"]) >= self.ttl_seconds
        ]
        for k in expired_keys:
            self._entries.pop(k, None)

    @staticmethod
    def _build_query_features(effective_query: str, chain=None) -> dict:
        norm_q = unicodedata.normalize("NFC", normalize_chat_slang(effective_query or "")).strip()
        canonical_q = canonicalize_for_semantic_cache(norm_q)
        if canonical_q == norm_q.lower():
            raw_vec = encode_query_l2_vector(norm_q, chain=chain)
            canon_vec = raw_vec
        else:
            raw_vec, canon_vec = encode_queries_l2_batch([norm_q, canonical_q], chain=chain)
        return {
            "norm_q": norm_q,
            "canonical_q": canonical_q,
            "raw_vec": raw_vec,
            "canon_vec": canon_vec,
            "numeric_tokens": extract_numeric_and_code_tokens(norm_q),
            "polarity": extract_polarity_signature(norm_q),
        }

    def lookup(self, effective_query: str, chain=None):
        """
        Tìm câu trả lời khớp ngữ nghĩa đạt đồng thời cả 3 màng lọc an toàn:
        1) Cosine Similarity >= 0.95 (so cả vector chuẩn hóa lõi ngữ nghĩa và vector câu gốc)
        2) Khớp tuyệt đối tập token số & mã học phần/quyết định
        3) Khớp tuyệt đối chữ ký phủ định / ngưỡng biên
        """
        norm_q_fast = unicodedata.normalize("NFC", normalize_chat_slang(effective_query or "")).strip()
        if not norm_q_fast:
            return None
        fast_num = extract_numeric_and_code_tokens(norm_q_fast)
        fast_pol = extract_polarity_signature(norm_q_fast)

        now = time.time()
        with self._lock:
            self._evict_expired_unlocked(now)
            if not self._entries:
                return None
            if not any(
                e["numeric_tokens"] == fast_num and e["polarity"] == fast_pol
                for e in self._entries.values()
            ):
                return None

        features = self._build_query_features(effective_query, chain=chain)
        now = time.time()

        with self._lock:
            self._evict_expired_unlocked(now)
            if not self._entries:
                return None

            best_key = None
            best_score = -1.0
            best_payload = None

            q_num = features["numeric_tokens"]
            q_pol = features["polarity"]
            q_raw_vec = features["raw_vec"]
            q_canon_vec = features["canon_vec"]

            for key, entry in list(self._entries.items()):
                # Màng lọc 2: Numeric & Identifier Guard
                if entry["numeric_tokens"] != q_num:
                    continue
                # Màng lọc 3: Negation & Polarity Guard
                if entry["polarity"] != q_pol:
                    continue

                # Màng lọc 1: Cosine Similarity via dot product of L2 vectors
                e_raw = entry["raw_vec"]
                e_canon = entry["canon_vec"]
                sim_raw = float(np.dot(q_raw_vec, e_raw)) if q_raw_vec.shape == e_raw.shape else 0.0
                sim_canon = float(np.dot(q_canon_vec, e_canon)) if q_canon_vec.shape == e_canon.shape else 0.0
                sim_score = max(sim_raw, sim_canon)

                if sim_score >= self.similarity_threshold and sim_score > best_score:
                    best_score = sim_score
                    best_key = key
                    best_payload = entry["payload"]

            if best_key is not None and best_payload is not None:
                self._entries.move_to_end(best_key)
                result = dict(best_payload)
                result["semantic_similarity"] = round(best_score, 4)
                return result

        return None

    def store(self, effective_query: str, payload: dict, chain=None) -> bool:
        """
        Chỉ lưu kết quả đã đối soát thành công (verified=True, is_refusal=False, không lỗi API).
        """
        if not isinstance(payload, dict):
            return False
        if not payload.get("verified", False) or payload.get("is_refusal", False):
            return False
        if payload.get("api_error", False):
            return False

        answer_text = (payload.get("answer") or "").strip()
        if not answer_text or answer_text == REFUSAL_MESSAGE or answer_text == FRIENDLY_ERROR_MESSAGE:
            return False

        features = self._build_query_features(effective_query, chain=chain)
        cache_key = features["norm_q"].lower()
        if not cache_key:
            return False

        now = time.time()
        stored_payload = {
            "answer": payload.get("answer", ""),
            "sources": list(payload.get("sources", []) or []),
            "contact": payload.get("contact"),
            "followups": list(payload.get("followups", []) or []),
            "verified": True,
            "is_refusal": False,
        }

        with self._lock:
            self._evict_expired_unlocked(now)
            self._entries[cache_key] = {
                "created_at": now,
                "canonical_q": features["canonical_q"],
                "raw_vec": features["raw_vec"],
                "canon_vec": features["canon_vec"],
                "numeric_tokens": features["numeric_tokens"],
                "polarity": features["polarity"],
                "payload": stored_payload,
            }
            self._entries.move_to_end(cache_key)
            while len(self._entries) > self.max_size:
                self._entries.popitem(last=False)
        return True


_GLOBAL_SEMANTIC_CACHE_LOCK = threading.Lock()
_GLOBAL_SEMANTIC_CACHE = None


def get_semantic_cache() -> SemanticAnswerCache:
    """Trả về singleton SemanticAnswerCache dùng chung cho API và Streamlit."""
    global _GLOBAL_SEMANTIC_CACHE
    if _GLOBAL_SEMANTIC_CACHE is not None:
        return _GLOBAL_SEMANTIC_CACHE
    with _GLOBAL_SEMANTIC_CACHE_LOCK:
        if _GLOBAL_SEMANTIC_CACHE is None:
            _GLOBAL_SEMANTIC_CACHE = SemanticAnswerCache(
                max_size=500,
                ttl_seconds=1800.0,
                similarity_threshold=0.95,
            )
    return _GLOBAL_SEMANTIC_CACHE


class RotatingResilientLLM:
    """
    Lớp bọc LLM với Groq LPU làm Engine xử lý chính (Tier 1):
    - TẦNG 1 (Mặc định): Groq API (xoay vòng tự động + giữ ấm client cache) - sinh chữ tốc độ cao.
    - TẦNG 2 (Dự phòng 1): Local LLM (LM Studio - http://127.0.0.1:1234/v1, model qwen/qwen3.5-4b).
    - TẦNG 2 (Dự phòng 2): Gemini (chỉ gọi nếu có key 'AIzaSy...' hợp lệ).
    - TẦNG 3: Báo lỗi quá tải an toàn (429 RESOURCE_EXHAUSTED).
    """
    def __init__(
        self,
        local_llm,
        groq_llm=None,
        max_output_tokens: int = 2048,
        temperature: float = 0.0,
        preferred_model: str | None = None,
        groq_timeout_sec: float | None = None,
        local_timeout_sec: float = 5.0,
        gemini_timeout_sec: float = 5.0,
        total_thinking_budget_sec: float = 15.0,
    ):
        self.local_llm = local_llm
        self.groq_llm = groq_llm
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.preferred_model = preferred_model
        self.groq_timeout_sec = groq_timeout_sec
        self.local_timeout_sec = float(local_timeout_sec)
        self.gemini_timeout_sec = float(gemini_timeout_sec)
        self.total_thinking_budget_sec = float(total_thinking_budget_sec)
        self._cloud_clients = {}
        self._models_lock = threading.Lock()
        self._groq_models = [
            "openai/gpt-oss-120b",
            "qwen/qwen3-32b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ]
        self._dead_groq_models = _DEAD_GROQ_MODELS
        self._cooldown_groq_models = _COOLDOWN_GROQ_MODELS

    def _effective_groq_timeout(self) -> float:
        if self.groq_timeout_sec is not None:
            return float(self.groq_timeout_sec)
        return 4.0 if int(self.max_output_tokens) <= 200 else 6.5

    @staticmethod
    def _call_with_timeout(fn, timeout_sec: float):
        """Thực thi lời gọi đồng bộ với giới hạn thời gian cứng để chặn treo vô hạn."""
        result_q: queue.Queue = queue.Queue(maxsize=1)

        def _runner():
            try:
                result_q.put(("ok", fn()))
            except BaseException as exc:
                result_q.put(("err", exc))

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        try:
            kind, val = result_q.get(timeout=max(0.01, float(timeout_sec)))
        except queue.Empty:
            raise TimeoutError(f"LLM invoke timed out after {timeout_sec}s")
        if kind == "err":
            raise val
        return val

    @staticmethod
    def _iter_with_timeout(stream_factory, first_chunk_timeout: float, idle_chunk_timeout: float):
        """Bao bọc stream generator với timeout riêng cho token đầu tiên và thời gian nhàn rỗi giữa các chunk."""
        chunk_q: queue.Queue = queue.Queue()
        stop_evt = threading.Event()

        def _producer():
            try:
                for item in stream_factory():
                    if stop_evt.is_set():
                        return
                    chunk_q.put(("chunk", item))
                chunk_q.put(("done", None))
            except BaseException as exc:
                chunk_q.put(("err", exc))

        t = threading.Thread(target=_producer, daemon=True)
        t.start()
        seen_first = False
        try:
            while True:
                wait_s = first_chunk_timeout if not seen_first else idle_chunk_timeout
                try:
                    kind, val = chunk_q.get(timeout=max(0.01, float(wait_s)))
                except queue.Empty:
                    raise TimeoutError(f"LLM stream timed out waiting after {wait_s}s")
                if kind == "done":
                    return
                if kind == "err":
                    raise val
                seen_first = True
                yield val
        finally:
            stop_evt.set()

    def _get_cloud_client(self, api_key: str):
        with self._models_lock:
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

    def _get_groq_client(self, model_name: str = "openai/gpt-oss-120b", temperature: float | None = None, max_tokens: int | None = None):
        groq_api_key = get_groq_api_key()
        if not groq_api_key:
            return None
        temp = self.temperature if temperature is None else temperature
        mtok = self.max_output_tokens if max_tokens is None else max_tokens
        timeout_sec = self._effective_groq_timeout()
        is_gpt_oss = "gpt-oss" in model_name
        effective_mtok = max(int(mtok), 600 if int(mtok) <= 200 else 2500) if is_gpt_oss else int(mtok)
        extra_kwargs = {"reasoning_effort": "low"} if is_gpt_oss else {}
        cache_key = (groq_api_key, model_name, float(temp), effective_mtok, is_gpt_oss, timeout_sec)
        with _GROQ_STATE_LOCK:
            client = _GROQ_CLIENTS_CACHE.get(cache_key)
            if client is None:
                client = ChatGroq(
                    api_key=groq_api_key,
                    model_name=model_name,
                    temperature=temp,
                    max_tokens=effective_mtok,
                    max_retries=0,
                    request_timeout=timeout_sec,
                    **extra_kwargs,
                )
                _GROQ_CLIENTS_CACHE[cache_key] = client
            return client

    def _promote_groq_model(self, groq_model: str):
        with self._models_lock:
            if groq_model in self._groq_models and groq_model != self._groq_models[0]:
                self._groq_models.remove(groq_model)
                self._groq_models.insert(0, groq_model)

    def _handle_groq_error(self, groq_model: str, err: Exception):
        """Phân loại lỗi Groq, gắn cooldown 45s cho model chạm trần 429 và xoay vòng tức thì (0ms)."""
        err_msg = str(err).lower()
        if any(tok in err_msg for tok in ("not_found", "does not exist", "404", "decommissioned", "model_not_found")):
            with _GROQ_STATE_LOCK:
                _DEAD_GROQ_MODELS.add(groq_model)
            return
        if any(tok in err_msg for tok in ("429", "rate_limit", "rate limit", "too many requests", "timeout", "timed out")):
            with _GROQ_STATE_LOCK:
                _COOLDOWN_GROQ_MODELS[groq_model] = time.time() + 4.0
            with self._models_lock:
                if groq_model in self._groq_models:
                    self._groq_models.remove(groq_model)
                    self._groq_models.append(groq_model)

    def _get_candidate_groq_models(self, prioritize_fast: bool = False) -> list[str]:
        """Lọc bỏ các model đã chết (404) hoặc đang trong thời gian cooldown ngắn do 429 TPM."""
        now = time.time()
        with _GROQ_STATE_LOCK:
            for m_expired in [m for m, until in _COOLDOWN_GROQ_MODELS.items() if until <= now]:
                _COOLDOWN_GROQ_MODELS.pop(m_expired, None)
            dead_snapshot = set(_DEAD_GROQ_MODELS)
            cooldown_snapshot = dict(_COOLDOWN_GROQ_MODELS)

        with self._models_lock:
            models_snapshot = list(self._groq_models)

        candidates = [
            m for m in models_snapshot
            if m not in dead_snapshot and cooldown_snapshot.get(m, 0.0) <= now
        ]
        if not candidates:
            time.sleep(1.0)
            candidates = sorted(
                [m for m in models_snapshot if m not in dead_snapshot],
                key=lambda m: cooldown_snapshot.get(m, 0.0),
            )
        if prioritize_fast:
            for fast_model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.1-8b-instant"):
                if fast_model in candidates:
                    candidates.remove(fast_model)
                    candidates.insert(0, fast_model)
            if self.preferred_model and self.preferred_model not in dead_snapshot and cooldown_snapshot.get(self.preferred_model, 0.0) <= now:
                if self.preferred_model in candidates:
                    candidates.remove(self.preferred_model)
                candidates.insert(0, self.preferred_model)
        return candidates

    @staticmethod
    def _is_local_lm_available(host: str = "127.0.0.1", port: int = 1234, timeout: float = 0.15) -> bool:
        """Kiểm tra nhanh cổng LM Studio trước khi gọi để bỏ qua ngay (< 1ms) nếu đã tắt."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def invoke(self, prompt, *args, **kwargs):
        global _CURRENT_KEY_INDEX
        groq_err = None
        local_err = None
        gemini_err = None
        budget_start = time.monotonic()

        # TẦNG 1 (Engine chính): Ưu tiên gọi trực tiếp Groq LPU ngay từ đầu
        print("[LLM ENGINE] Đang tạo phản hồi qua Groq LPU...")
        candidate_models = self._get_candidate_groq_models(
            prioritize_fast=bool(self.max_output_tokens <= 200 or self.preferred_model)
        )
        groq_timeout = self._effective_groq_timeout()

        for groq_model in candidate_models:
            if (time.monotonic() - budget_start) >= self.total_thinking_budget_sec:
                groq_err = TimeoutError(f"Groq tier budget exceeded ({self.total_thinking_budget_sec}s)")
                break
            try:
                groq_client = self._get_groq_client(model_name=groq_model)
                if groq_client is None:
                    continue
                groq_resp = self._call_with_timeout(
                    lambda: groq_client.invoke(prompt, *args, **kwargs),
                    timeout_sec=groq_timeout,
                )
                groq_content = getattr(groq_resp, "content", str(groq_resp))
                if groq_content and str(groq_content).strip():
                    if self.max_output_tokens > 200:
                        self._promote_groq_model(groq_model)
                    return groq_resp
            except Exception as g_err:
                groq_err = g_err
                self._handle_groq_error(groq_model, g_err)
                continue

        # TẦNG 2 (Dự phòng 1): Chuyển tiếp sang Local LM Studio (Qwen 4B)
        if not self._is_local_lm_available():
            local_err = ConnectionRefusedError("Local LM Studio (127.0.0.1:1234) is unreachable")
            print("[FAILOVER] Cổng Local LM Studio (127.0.0.1:1234) đóng -> Bỏ qua ngay sang dự phòng Cloud...")
        else:
            try:
                print("[FAILOVER] Groq không khả dụng -> Chuyển sang Local LM Studio (qwen/qwen3.5-4b)...")
                local_resp = self._call_with_timeout(
                    lambda: self.local_llm.invoke(prompt, *args, **kwargs),
                    timeout_sec=self.local_timeout_sec,
                )
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
            with _GROQ_STATE_LOCK:
                start_idx = _CURRENT_KEY_INDEX % num_keys
                _CURRENT_KEY_INDEX = (start_idx + 1) % num_keys

            for offset in range(num_keys):
                current_idx = (start_idx + offset) % num_keys
                api_key = valid_gemini_keys[current_idx]
                try:
                    client = self._get_cloud_client(api_key)
                    response = self._call_with_timeout(
                        lambda: client.invoke(prompt, *args, **kwargs),
                        timeout_sec=self.gemini_timeout_sec,
                    )
                    content = getattr(response, "content", str(response))
                    if content and str(content).strip():
                        if offset > 0:
                            with _GROQ_STATE_LOCK:
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
        budget_start = time.monotonic()

        # TẦNG 1 (Engine chính): Ưu tiên gọi trực tiếp Groq LPU ngay từ đầu
        print("[LLM ENGINE] Đang tạo phản hồi qua Groq LPU...")
        candidate_models = self._get_candidate_groq_models(prioritize_fast=False)
        groq_timeout = self._effective_groq_timeout()
        for groq_model in candidate_models:
            if (time.monotonic() - budget_start) >= self.total_thinking_budget_sec:
                groq_err = TimeoutError(f"Groq stream budget exceeded ({self.total_thinking_budget_sec}s)")
                break
            yielded_groq = False
            try:
                groq_client = self._get_groq_client(model_name=groq_model)
                if groq_client is None:
                    continue
                for chunk in self._iter_with_timeout(
                    lambda: groq_client.stream(prompt, *args, **kwargs),
                    first_chunk_timeout=groq_timeout,
                    idle_chunk_timeout=max(groq_timeout, 8.0),
                ):
                    chunk_text = getattr(chunk, "content", str(chunk))
                    if chunk_text:
                        yielded_groq = True
                        yield chunk
                if yielded_groq:
                    self._promote_groq_model(groq_model)
                    return
                continue
            except Exception as g_err:
                groq_err = g_err
                if yielded_groq:
                    yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                    return
                self._handle_groq_error(groq_model, g_err)
                continue

        # TẦNG 2 (Dự phòng 1): Chuyển tiếp sang Local LM Studio (Qwen 4B)
        yielded_local = False
        if not self._is_local_lm_available():
            local_err = ConnectionRefusedError("Local LM Studio (127.0.0.1:1234) is unreachable")
            print("[FAILOVER] Cổng Local LM Studio (127.0.0.1:1234) đóng -> Bỏ qua ngay sang dự phòng Cloud...")
        else:
            try:
                print("[FAILOVER] Groq không khả dụng -> Chuyển sang Local LM Studio (qwen/qwen3.5-4b)...")
                for chunk in self._iter_with_timeout(
                    lambda: self.local_llm.stream(prompt, *args, **kwargs),
                    first_chunk_timeout=self.local_timeout_sec,
                    idle_chunk_timeout=max(self.local_timeout_sec, 8.0),
                ):
                    chunk_text = getattr(chunk, "content", str(chunk))
                    if chunk_text:
                        yielded_local = True
                        yield chunk
                if yielded_local:
                    return
                resp = self._call_with_timeout(
                    lambda: self.local_llm.invoke(prompt, *args, **kwargs),
                    timeout_sec=self.local_timeout_sec,
                )
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
            with _GROQ_STATE_LOCK:
                start_idx = _CURRENT_KEY_INDEX % num_keys
                _CURRENT_KEY_INDEX = (start_idx + 1) % num_keys

            for offset in range(num_keys):
                current_idx = (start_idx + offset) % num_keys
                api_key = valid_gemini_keys[current_idx]
                yielded_from_this_key = False
                try:
                    client = self._get_cloud_client(api_key)
                    for chunk in self._iter_with_timeout(
                        lambda: client.stream(prompt, *args, **kwargs),
                        first_chunk_timeout=self.gemini_timeout_sec,
                        idle_chunk_timeout=max(self.gemini_timeout_sec, 8.0),
                    ):
                        chunk_text = getattr(chunk, "content", str(chunk))
                        if chunk_text:
                            yielded_from_this_key = True
                            if offset > 0:
                                with _GROQ_STATE_LOCK:
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


def get_llm(temperature: float = 0.0, max_output_tokens: int = 2048, preferred_model: str | None = None):
    groq_api_key = get_groq_api_key()
    groq_llm = None
    if groq_api_key:
        groq_llm = ChatGroq(
            api_key=groq_api_key,
            model_name=preferred_model or "openai/gpt-oss-120b",
            temperature=temperature,
            max_tokens=max_output_tokens,
            max_retries=0,
            request_timeout=4.5 if int(max_output_tokens) <= 200 else 6.5
        )

    local_llm = ChatOpenAI(
        base_url="http://127.0.0.1:1234/v1",
        api_key="not-needed",
        model="qwen/qwen3.5-4b",
        temperature=0.0,
        max_tokens=min(800, max_output_tokens),
        max_retries=0,
        request_timeout=8,
        streaming=(max_output_tokens > 200),
        extra_body={"reasoning_effort": "none"}
    )
    return RotatingResilientLLM(
        local_llm=local_llm,
        groq_llm=groq_llm,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        preferred_model=preferred_model
    )


@st.cache_resource(show_spinner=False)
def get_rewriter_llm():
    """Khởi tạo và cache LLM tốc độ cao dành riêng cho bước viết lại câu hỏi nối tiếp."""
    global _GLOBAL_REWRITER_LLM
    if _GLOBAL_REWRITER_LLM is not None:
        return _GLOBAL_REWRITER_LLM
    _GLOBAL_REWRITER_LLM = get_llm(temperature=0.0, max_output_tokens=100, preferred_model="llama-3.1-8b-instant")
    return _GLOBAL_REWRITER_LLM


_REGULATION_SUBJECT_KEYWORDS = (
    "học bổng", "kkht", "spkt", "học phí", "miễn giảm", "miễn, giảm", "hỗ trợ chi phí",
    "trợ cấp", "hoàn trả", "qt-sv-04", "tín chỉ", "cảnh báo", "rèn luyện", "điểm trung bình",
    "điểm c", "rút môn", "thôi học", "bảo lưu", "bảo hiểm", "quy chế", "quy định", "quy trình",
    "quy tắc", "điều ", "khoản ", "chương ", "phụ lục", "ctxh", "công tác xã hội",
    "công tác sinh viên", "ctsv", "kỷ luật", "khiển trách", "cảnh cáo", "đình chỉ",
    "thi hộ", "thi thay", "học thay", "học hộ", "gian lận", "phòng thi", "tốt nghiệp",
    "khóa luận", "đồ án", "tiểu luận", "hồ sơ", "thủ tục", "đơn đề nghị", "biên lai",
    "hóa đơn", "mật khẩu", "tài khoản", "email", "an toàn thông tin", "attt", "an ninh mạng",
    "trang phục", "ứng xử", "ban cán sự", "lớp trưởng", "cố vấn học tập", "cvht",
    "khiếu nại", "vượt khó", "đề cương", "học phần", "môn học", "giảng viên", "tiên quyết",
    "học trước", "song hành", "chuẩn đầu ra", "cđr", "giáo trình", "hệ số", "chuyên cần",
    "quá trình", "cuối kỳ", "lý thuyết", "thực hành", "it1216", "mã nguồn mở", "linux",
    "ubuntu", "elearning", "e-learning", "phòng đào tạo", "kế hoạch tài chính", "khtc",
    "công nghệ thông tin", "cntt", "hiến máu", "mùa hè xanh", "tiếp sức", "thủ khoa",
    "xuất sắc", "tiên tiến", "dân tộc thiểu số", "hộ nghèo", "cận nghèo", "khuyết tật",
    "mồ côi", "cử tuyển", "thương binh", "liệt sĩ", "hút thuốc", "rượu bia", "mạng xã hội",
    "thẻ sinh viên", "khen thưởng", "hội đồng", "phúc khảo", "học kỳ",
)

_ANAPHORIC_FOLLOWUP_CUES = (
    "của nó", "cái đó", "cái này", "mức này", "mức đó", "loại này", "loại đó",
    "khoản này", "quy định này", "quy trình này", "trường hợp này", "đối tượng này",
    "học phần này", "học phần đó", "môn này", "môn đó", "chế độ này", "chính sách này",
    "hành vi này", "vi phạm này", "phòng này", "đơn vị này", "nộp ở đâu", "nộp cho ai",
    "bao lâu", "mấy ngày", "bao nhiêu ngày", "mấy tháng", "bao nhiêu tháng",
    "bao nhiêu tiền", "mức phạt", "xử lý thế nào", "tính thế nào", "tính sao",
)


def _is_prompt_injection_or_long_noise(raw: str, clean: str) -> bool:
    """Nhận diện bẫy Prompt Injection hoặc văn bản rác copy dài > 1.200 ký tự không phải câu hỏi quy chế."""
    if is_prompt_injection(raw) or is_prompt_injection(clean):
        return True
    if len(raw) > 1200:
        return True
    return False


def get_greeting_or_chitchat_reply(query: str) -> str | None:
    """
    Nhận diện câu chào hỏi, cảm ơn, xác nhận, ra lệnh meta cho bot, bẫy Prompt Injection
    hoặc câu vô nghĩa/xã giao ngắn không có nội dung tra cứu quy chế.
    """
    raw_orig = (query or "").strip()
    if not raw_orig:
        return "Bạn vui lòng nhập nội dung câu hỏi cụ thể về quy chế hoặc chọn một gợi ý bên dưới để Lucas hỗ trợ nhé!"

    if len(raw_orig) > MAX_QUERY_LENGTH:
        return TOO_LONG_QUERY_MESSAGE

    if is_prompt_injection(raw_orig):
        return REFUSAL_MESSAGE

    raw_orig = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", raw_orig).strip()
    if not raw_orig:
        return (
            "Mình chưa nhận diện được nội dung câu hỏi. Bạn hãy chọn nhanh 1 trong các câu hỏi gợi ý bên dưới "
            "hoặc nhập chủ đề quy chế, học vụ, học bổng, học phí cần tra cứu nhé!"
        )

    raw = normalize_chat_slang(raw_orig).strip()
    if not re.search(r"[a-zA-ZÀ-ỹ]", raw):
        return (
            "Mình chưa nhận diện được nội dung câu hỏi. Bạn hãy chọn nhanh 1 trong các câu hỏi gợi ý bên dưới "
            "hoặc nhập chủ đề quy chế, học vụ, học bổng, học phí cần tra cứu nhé!"
        )

    clean = re.sub(r"^[\s\.,!?;:\-\(\)\[\]\"']+|[\s\.,!?;:\-\(\)\[\]\"']+$", "", raw.lower()).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean or len(clean) <= 1:
        return "Bạn vui lòng nhập nội dung câu hỏi cụ thể về quy chế hoặc chọn một gợi ý bên dưới để Lucas hỗ trợ nhé!"

    if _is_prompt_injection_or_long_noise(raw_orig, clean):
        return REFUSAL_MESSAGE

    if any(kw in clean for kw in _REGULATION_SUBJECT_KEYWORDS):
        if not re.match(r"^(?:test|kiểm tra thử)\b", clean):
            return None
    if any(cue in clean for cue in _ANAPHORIC_FOLLOWUP_CUES):
        return None
    if SmartRAGChain._is_excluded_resolution_query(clean) or SmartRAGChain._is_explicit_out_of_scope_query(clean):
        return None

    words = clean.split()

    alpha_tokens = re.findall(r"[a-zà-ỹđ]+", clean)
    if alpha_tokens:
        if len(alpha_tokens) >= 2 and len(set(alpha_tokens)) == 1:
            return (
                "Mình luôn sẵn sàng hỗ trợ! Bạn hãy chọn 1 trong các câu hỏi gợi ý bên dưới "
                "hoặc nhập trực tiếp chủ đề quy chế, học vụ cần tra cứu nhé!"
            )
        vn_vowels = set("aeiouyàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")
        for tok in alpha_tokens:
            if len(tok) >= 5 and not any(ch in vn_vowels for ch in tok):
                return (
                    "Mình chưa hiểu rõ ý bạn. Bạn hãy chọn 1 trong các câu hỏi gợi ý bên dưới "
                    "hoặc nhập rõ chủ đề quy chế, học vụ cần tra cứu nhé!"
                )
            if re.search(r"(?:asdf|qwer|zxcv|hjkl|tyui|bnm|fghj|dfgh|cvbn)", tok):
                return (
                    "Mình chưa hiểu rõ ý bạn. Bạn hãy chọn 1 trong các câu hỏi gợi ý bên dưới "
                    "hoặc nhập rõ chủ đề quy chế, học vụ cần tra cứu nhé!"
                )

    if len(words) > 9:
        return None

    thanks_or_ack_exact = {
        "ok", "okay", "oke", "oki", "okie", "okela", "dạ", "vâng", "dạ vâng",
        "ừ", "ờ", "ừm", "rồi", "rõ rồi", "đã rõ", "hiểu rồi", "biết rồi", "đã hiểu",
        "nắm được rồi", "ok bạn", "ok lucas", "ok ad", "oke bạn", "oke lucas",
        "ok cảm ơn", "oke cảm ơn", "dạ cảm ơn", "vâng cảm ơn", "cảm ơn bạn", "cảm ơn lucas",
        "cảm ơn ad", "cảm ơn nhiều", "cảm ơn nhé", "cảm ơn nha", "cám ơn", "cám ơn bạn",
        "cám ơn lucas", "tốt quá", "hay quá", "tuyệt vời", "giỏi quá", "xịn quá",
        "đỉnh quá", "chuẩn", "chuẩn luôn", "đúng rồi", "cảm ơn", "thank", "thanks",
        "tks", "thank you", "thanks lucas", "thanks bạn", "good", "nice", "great",
    }
    thanks_prefixes = (
        "cảm ơn", "cám ơn", "thank", "tks", "ok cảm ơn", "oke cảm ơn", "dạ cảm ơn", "vâng cảm ơn",
        "rõ rồi", "hiểu rồi", "đã hiểu", "hay quá", "tuyệt vời",
    )
    if clean in thanks_or_ack_exact or any(clean.startswith(p) for p in thanks_prefixes):
        return (
            "Rất vui được hỗ trợ bạn! Nếu cần tra cứu thêm quy chế học vụ, học bổng, học phí hay đề cương học phần, "
            "bạn có thể chọn nhanh 1 trong các gợi ý bên dưới hoặc nhập trực tiếp chủ đề cần tìm hiểu nhé!"
        )

    command_or_chitchat_exact = {
        "đặt câu hỏi đi", "đặt câu hỏi", "hỏi đi", "hỏi lại đi", "hỏi tiếp đi", "hỏi gì đi",
        "hỏi mình đi", "hỏi em đi", "hỏi tôi đi", "nói đi", "nói gì đi", "nói tiếp đi",
        "nói chuyện đi", "trả lời đi", "gợi ý đi", "cho gợi ý đi", "cho câu hỏi đi",
        "tiếp đi", "tiếp tục đi", "bắt đầu đi", "làm đi", "xem nào", "đâu rồi", "sao nữa",
        "sao im thế", "alo đâu rồi", "test", "testing", "test thử", "test bot", "alo test",
        "kiểm tra thử", "bạn ăn cơm chưa", "ăn cơm chưa", "ăn sáng chưa", "ăn trưa chưa",
        "ăn tối chưa", "ngủ chưa", "bạn ngủ chưa", "buồn ngủ quá", "mệt quá", "chán quá",
        "đói quá", "đói bụng quá", "buồn quá", "vui quá", "bạn khỏe không", "khỏe không",
        "dạo này thế nào", "bạn mấy tuổi", "bạn bao nhiêu tuổi", "bạn có người yêu chưa",
        "kể chuyện cười đi", "kể chuyện đi", "hát đi", "hát một bài đi", "làm thơ đi",
        "haha", "hihi", "hehe", "huhu", "kaka", "lol", "ahaha", "blabla", "bla bla",
        "abc", "xyz", "abc xyz", "alo 123", "123", "1234", "12345", "123456",
    }
    command_or_chitchat_prefixes = (
        "đặt câu hỏi", "hỏi đi", "hỏi lại", "hỏi tiếp", "hỏi gì", "hỏi câu khác",
        "đổi câu hỏi", "nói đi", "nói gì", "nói tiếp", "nói chuyện", "trả lời đi",
        "gợi ý đi", "cho câu hỏi", "cho gợi ý", "bạn ăn cơm", "ăn cơm chưa",
        "ăn sáng chưa", "ăn trưa chưa", "ăn tối chưa", "buồn ngủ", "mệt quá",
        "chán quá", "đói bụng", "đói quá", "buồn quá", "vui quá", "bạn khỏe không",
        "bạn mấy tuổi", "bạn bao nhiêu tuổi", "bạn có người yêu", "kể chuyện",
        "hát một bài", "hát đi", "tạm biệt", "chúc ngủ ngon", "chúc bạn", "bye",
        "goodbye", "hẹn gặp lại", "dừng lại đi", "tắt đi", "im đi", "xóa lịch sử",
        "làm mới đi", "reset đi", "bạn đang làm gì", "có ai ở đó", "ai tạo ra bạn",
        "ai lập trình ra bạn", "bạn biết làm gì", "bạn có thông minh", "test ",
        "kiểm tra thử", "alo ", "ê bot", "này lucas", "này bot", "hôm nay trời đẹp",
        "chào lucas", "chào bạn", "chào ad", "xin chào",
    )
    if clean in command_or_chitchat_exact or any(clean.startswith(p) for p in command_or_chitchat_prefixes):
        return (
            "Mình luôn sẵn sàng! Bạn hãy chọn nhanh 1 trong các câu hỏi gợi ý bên dưới "
            "hoặc nhập trực tiếp chủ đề quy chế, học vụ, học bổng, học phí cần tra cứu để Lucas giải đáp ngay nhé!"
        )

    greeting_keywords = (
        "chào", "xin chào", "hello", "hi", "hey", "alo", "bạn là ai", "tên gì",
        "bạn tên gì", "giới thiệu", "lucas", "ad", "admin", "bot ơi",
    )
    if len(words) <= 7 and any(re.search(rf"\b{re.escape(k)}\b", clean) for k in greeting_keywords):
        return (
            "Chào bạn! Mình là Lucas – trợ lý học vụ VLUTE. Hôm nay bạn muốn tra cứu quy định về học bổng, "
            "học phí, công tác xã hội hay học vụ? *(Bạn có thể bấm chọn nhanh gợi ý bên dưới hoặc nhập trực tiếp câu hỏi nhé!)*"
        )

    return None


def is_greeting_or_chitchat(query: str) -> bool:
    """Trả về True nếu câu truy vấn là lời chào, cảm ơn, xác nhận, câu lệnh meta hoặc câu vô nghĩa/xã giao."""
    return get_greeting_or_chitchat_reply(query) is not None


def _extract_topic_anchor_from_history(recent_history: list[tuple[str, str]]) -> str:
    """Trích xuất chủ đề quy chế / tên học phần chính xác từ lượt hỏi gần nhất trong lịch sử hội thoại."""
    topic_patterns = (
        (r"(?:học phần|môn)\s+phần mềm mã nguồn mở(?:\s*\(it1216\))?|it1216|phần mềm mã nguồn mở", "học phần Phần mềm mã nguồn mở (IT1216)"),
        (r"học bổng\s+(?:kkht\s+)?mức\s+1|học bổng\s+sư phạm kỹ thuật|học bổng\s+spkt", "Học bổng KKHT Mức 1 (Học bổng SPKT)"),
        (r"học bổng\s+vượt khó", "Học bổng vượt khó"),
        (r"học bổng\s+doanh nghiệp", "Học bổng do doanh nghiệp tài trợ"),
        (r"trợ cấp\s+học tập", "Trợ cấp học tập"),
        (r"học bổng\s+khuyến khích\s+học tập|học bổng\s+kkht|xét\s+cấp\s+học bổng", "Học bổng khuyến khích học tập (KKHT)"),
        (r"sinh viên\s+xuất sắc\s+toàn khóa", "danh hiệu Sinh viên Xuất sắc toàn khóa"),
        (r"tập thể\s+lớp\s+xuất sắc|tập thể\s+lớp\s+tiên tiến", "danh hiệu Tập thể lớp Xuất sắc / Tiên tiến"),
        (r"thủ khoa", "danh hiệu khen thưởng Thủ khoa đầu khóa"),
        (r"hỗ trợ\s+chi phí\s+học tập", "chế độ hỗ trợ chi phí học tập đối với sinh viên dân tộc thiểu số thuộc hộ nghèo, cận nghèo"),
        (r"miễn[,\s]+giảm\s+học phí|miễn\s+(?:100%\s+)?học phí|giảm\s+70%\s+học phí|giảm\s+50%\s+học phí", "chế độ miễn, giảm học phí"),
        (r"hoàn trả\s+học phí|học phí\s+thừa|qt-sv-04", "quy trình hoàn trả học phí thừa cho sinh viên (QT-SV-04)"),
        (r"công tác\s+xã hội|ctxh|ngày\s+ctxh|hiến máu|mùa hè xanh", "quy định hoạt động Công tác xã hội (CTXH)"),
        (r"ban cán sự\s+lớp|lớp trưởng|lớp phó", "Ban cán sự lớp theo Quy định công tác sinh viên"),
        (r"thi hộ|thi thay|học hộ|học thay|kỷ luật\s+sinh viên|khung\s+xử lý\s+kỷ luật", "khung xử lý kỷ luật sinh viên theo Quy định công tác sinh viên"),
        (r"điểm\s+rèn luyện|công tác\s+sinh viên", "Quy định công tác sinh viên đối với chương trình đào tạo đại học chính quy"),
        (r"quy tắc\s+ứng xử|trang phục|mạng xã hội|hút thuốc", "Quy tắc ứng xử của sinh viên trong Nhà trường"),
        (r"an toàn\s+thông tin|an ninh\s+mạng|mật khẩu|email\s+@|st\.vlute\.edu\.vn", "Quy chế bảo đảm an toàn thông tin, an ninh mạng"),
    )
    # Duyệt ngược từ lượt gần nhất về trước; ưu tiên lấy chủ ngữ từ câu hỏi gần nhất của người dùng
    for role, content in reversed(recent_history):
        if role != "user":
            continue
        c_low = normalize_chat_slang(content).lower()
        best_label = ""
        best_pos = -1
        for pat, label in topic_patterns:
            for m in re.finditer(pat, c_low):
                if m.start() >= best_pos:
                    best_pos = m.start()
                    best_label = label
        if best_label:
            return best_label
    for role, content in reversed(recent_history):
        c_low = normalize_chat_slang(content).lower()
        for pat, label in topic_patterns:
            if re.search(pat, c_low):
                return label
    return ""


def _extract_assistant_drilldown_anchor(q_lower: str, recent_history: list[tuple[str, str]]) -> tuple[str, str]:
    """
    Phân tích 2 chiều (User + Assistant liền trước) để bóc tách đúng khái niệm/mốc điểm/giấy tờ/học phần
    mà trợ lý vừa nhắc tới trong câu trả lời gần nhất khi người dùng hỏi đào sâu.
    Trả về (drilldown_anchor, user_parent_topic).
    """
    user_topic = _extract_topic_anchor_from_history(recent_history)
    last_assistant = ""
    for role, content in reversed(recent_history):
        if role == "assistant" and str(content or "").strip():
            last_assistant = strip_think_tags(str(content))
            break
    if not last_assistant:
        return "", user_topic

    asst_low = last_assistant.lower()
    asst_head_low = asst_low[:220]
    bold_terms = [
        re.sub(r"\s+", " ", b).strip(" .,:;-")
        for b in re.findall(r"\*\*([^\*\n]{2,90})\*\*", last_assistant)
        if len(b.strip()) >= 3
    ]

    # 1. Đào sâu về mức điểm / xếp loại điểm rèn luyện (vd: 'vậy loại Tốt là bao nhiêu điểm?')
    if re.search(
        r"(?:loại\s+(?:xuất\s+sắc|tốt|khá|trung\s+bình|yếu|kém)|bao\s+nhiêu\s+điểm|mấy\s+điểm|xếp\s+loại|mức\s+này|mức\s+đó)",
        q_lower,
    ) and ("rèn luyện" in asst_low or "điểm rèn luyện" in asst_low):
        grade_bold = next(
            (b for b in bold_terms if any(g in b.lower() for g in ("rèn luyện", "loại tốt", "loại khá", "xuất sắc"))),
            "",
        )
        if grade_bold and "rèn luyện" in grade_bold.lower():
            return grade_bold, user_topic or "điểm rèn luyện"
        return "điểm rèn luyện (theo Quy định công tác sinh viên)", user_topic

    # 2. Đào sâu về giấy tờ / biểu mẫu / đơn từ / cơ quan cấp (vd: 'giấy đó xin ở đâu?', 'đơn này nộp cho ai?')
    if re.search(
        r"(?:giấy\s+đó|giấy\s+này|giấy\s+tờ\s+(?:đó|này)|đơn\s+(?:đó|này)|biểu\s+mẫu\s+(?:đó|này)|"
        r"mẫu\s+(?:đó|này)|minh\s+chứng\s+(?:đó|này)|xin\s+ở\s+đâu|lấy\s+ở\s+đâu|cấp\s+ở\s+đâu|ai\s+cấp|cơ\s+quan\s+nào)",
        q_lower,
    ):
        paper_rx = re.compile(
            r"(?:giấy\s+(?:xác\s+nhận|chứng\s+nhận|khai\s+sinh)|đơn\s+đề\s+nghị|"
            r"biểu\s+mẫu\s+[A-Z0-9-]+|quyết\s+định\s+trợ\s+cấp|sổ\s+hộ\s+(?:nghèo|cận\s+nghèo)|"
            r"bảng\s+phân\s+công|thẻ\s+sinh\s+viên|minh\s+chứng)[^,;\.\n\(\*]{0,55}",
            re.IGNORECASE,
        )
        for b in bold_terms:
            m_b = paper_rx.search(b)
            if m_b:
                paper_phrase = m_b.group(0).strip(" .,:;-")
                if user_topic and user_topic.lower() not in paper_phrase.lower():
                    return f"{paper_phrase} ({user_topic})", user_topic
                return paper_phrase, user_topic
        m_asst = paper_rx.search(last_assistant)
        if m_asst:
            paper_phrase = re.sub(r"\s+", " ", m_asst.group(0)).strip(" .,:;-")
            if user_topic and user_topic.lower() not in paper_phrase.lower():
                return f"{paper_phrase} ({user_topic})", user_topic
            return paper_phrase, user_topic

    # 3. Đào sâu về chuẩn ngày CTXH / quy đổi buổi-ngày (vd: 'chuẩn đó cần mấy ngày?', 'hoạt động đó tính mấy ngày?')
    if re.search(
        r"(?:chuẩn\s+(?:đó|này)|mấy\s+ngày|bao\s+nhiêu\s+ngày|mấy\s+buổi|bao\s+nhiêu\s+buổi|hoạt\s+động\s+(?:đó|này))",
        q_lower,
    ) and any(k in asst_low for k in ("ctxh", "công tác xã hội", "hiến máu", "mùa hè xanh", "tiếp sức")):
        ctxh_bold = next(
            (b for b in bold_terms if any(k in b.lower() for k in ("ctxh", "công tác xã hội", "hiến máu", "mùa hè xanh", "tiếp sức"))),
            "",
        )
        if ctxh_bold:
            if "ctxh" not in ctxh_bold.lower() and "công tác xã hội" not in ctxh_bold.lower():
                return f"{ctxh_bold} trong Công tác xã hội (CTXH)", "quy định hoạt động Công tác xã hội (CTXH)"
            return ctxh_bold, "quy định hoạt động Công tác xã hội (CTXH)"
        return "chuẩn ngày Công tác xã hội (CTXH)", "quy định hoạt động Công tác xã hội (CTXH)"

    # 4. Đào sâu về đề cương / học phần tiên quyết / hệ số / CĐR (vd: 'tiên quyết đó là môn nào?', 'hệ số đó tính sao?')
    if re.search(
        r"(?:học\s+phần\s+tiên\s+quyết|môn\s+tiên\s+quyết|tiên\s+quyết\s+(?:đó|này)|"
        r"hệ\s+số\s+(?:đó|này)|chuẩn\s+đầu\s+ra\s+(?:đó|này)|cđr\s+(?:đó|này)|giáo\s+trình\s+(?:đó|này)|"
        r"học\s+phần\s+(?:đó|này)|môn\s+(?:đó|này))",
        q_lower,
    ) and any(k in asst_low for k in ("it1216", "phần mềm mã nguồn mở", "tiên quyết", "chuẩn đầu ra", "hệ số")):
        course_anchor = "học phần Phần mềm mã nguồn mở (IT1216)" if ("it1216" in asst_low or "mã nguồn mở" in asst_low) else user_topic
        course_bold = next(
            (b for b in bold_terms if any(k in b.lower() for k in ("tiên quyết", "it1216", "chuẩn đầu ra", "hệ số", "mã nguồn mở"))),
            "",
        )
        if course_bold and course_anchor and course_anchor.lower() not in course_bold.lower():
            return f"{course_bold} của {course_anchor}", course_anchor
        return course_bold or course_anchor, user_topic

    # 5. Đào sâu tổng quát qua cụm từ in đậm **...** ở phần đầu hoặc thân phản hồi Assistant khớp từ khóa câu hỏi
    q_words = {w for w in re.findall(r"[a-zà-ỹđ0-9]+", q_lower) if len(w) >= 3 and w not in _BM25_STOPWORDS}
    for b in bold_terms:
        b_low = b.lower()
        b_words = set(re.findall(r"[a-zà-ỹđ0-9]+", b_low))
        overlap = q_words & b_words
        if overlap:
            if user_topic and user_topic.lower() not in b_low and len(b.split()) <= 6:
                return f"{b} ({user_topic})", user_topic
            return b, user_topic

    if bold_terms and any(p in asst_head_low for p in bold_terms[0].lower().split()[:2]):
        lead_bold = bold_terms[0]
        if user_topic and user_topic.lower() not in lead_bold.lower() and len(lead_bold.split()) <= 5:
            return f"{lead_bold} ({user_topic})", user_topic
        return lead_bold, user_topic

    return "", user_topic


def rewrite_conversational_query(query: str, chat_history: list | None = None) -> str:
    """
    Viết lại câu hỏi nối tiếp có chứa đại từ/từ nối ngữ cảnh thành câu hỏi độc lập đầy đủ nghĩa.
    Nếu lịch sử trống hoặc câu hỏi đã rõ chủ ngữ/đối tượng, giữ nguyên câu hỏi đã chuẩn hóa từ viết tắt.
    """
    if not query or not str(query).strip():
        return ""

    raw_orig = str(query).strip()
    if len(raw_orig) > MAX_QUERY_LENGTH or is_prompt_injection(raw_orig):
        return raw_orig

    raw_query = re.sub(r"\s+", " ", normalize_chat_slang(raw_orig).strip())
    if not chat_history:
        return raw_query

    q_lower_init = raw_query.lower()
    if (
        is_greeting_or_chitchat(raw_query)
        or SmartRAGChain._is_excluded_resolution_query(q_lower_init)
        or SmartRAGChain._is_explicit_out_of_scope_query(q_lower_init)
    ):
        return raw_query

    valid_history = []
    for msg in chat_history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = str(msg.get("content", "") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if msg.get("is_greeting"):
            if role == "assistant" and valid_history and valid_history[-1][0] == "user":
                valid_history.pop()
            continue
        if role == "assistant":
            c_low = content.lower()
            is_excluded_assistant = bool(
                msg.get("is_refusal")
                or REFUSAL_MESSAGE in content
                or "không được đề cập trong các văn bản quy định" in c_low
                or "ngoài phạm vi dữ liệu quy chế" in c_low
                or "lượng truy cập cao" in c_low
                or "đợi khoảng 30–60 giây" in c_low
                or "phản hồi bị gián đoạn giữa chừng" in c_low
            )
            if is_excluded_assistant:
                if valid_history and valid_history[-1][0] == "user":
                    valid_history.pop()
                continue
        valid_history.append((role, content))

    if valid_history and valid_history[-1][0] == "user" and valid_history[-1][1].strip() == raw_query:
        valid_history = valid_history[:-1]

    if not valid_history:
        return raw_query

    recent_history = valid_history[-6:]
    q_lower = raw_query.lower()

    # Tuyệt đối không viết lại nếu câu hiện tại là lời chào/cảm thán/ra lệnh meta/Prompt Injection hoặc câu hỏi OOS rõ ràng
    if (
        is_greeting_or_chitchat(raw_query)
        or SmartRAGChain._is_excluded_resolution_query(q_lower)
        or SmartRAGChain._is_explicit_out_of_scope_query(q_lower)
    ):
        return raw_query

    has_pronoun_no = bool(re.search(r"\bnó\b", q_lower))
    anaphoric_pronoun_phrases = [
        "cái đó", "cái này", "mức này", "mức đó", "loại này", "loại đó",
        "khoản này", "quy định này", "quy trình này", "trường hợp này", "đối tượng này",
        "phòng này", "phòng đó", "đơn vị này", "đơn vị đó", "ở đó", "bên đó",
        "học phần này", "học phần đó", "môn này", "môn đó", "ngành này", "ngành đó",
        "bảng này", "mục này", "chế độ này", "chính sách này", "hành vi này",
        "học bổng này", "học bổng đó", "quy tắc này", "quy chế này", "hoạt động này", "danh hiệu này",
        "giấy đó", "giấy này", "giấy tờ đó", "giấy tờ này", "đơn đó", "đơn này",
        "biểu mẫu đó", "biểu mẫu này", "mẫu đó", "mẫu này", "minh chứng đó", "minh chứng này",
        "hồ sơ đó", "hồ sơ này", "điều kiện này", "điều kiện đó", "tiêu chuẩn này", "tiêu chuẩn đó",
        "yêu cầu này", "yêu cầu đó", "chuẩn đó", "chuẩn này", "mốc đó", "mốc này",
        "hệ số đó", "hệ số này", "tỷ lệ đó", "tỷ lệ này", "điểm đó", "điểm này",
        "hoạt động đó", "môn tiên quyết đó", "học phần tiên quyết đó",
    ]
    has_anaphoric_pronoun = has_pronoun_no or any(phrase in q_lower for phrase in anaphoric_pronoun_phrases)
    discourse_connector_phrases = [
        "vậy thì", "vậy còn", "vậy mức", "thế còn", "còn hồ sơ", "còn thủ tục",
        "còn thời gian", "còn điều kiện", "còn mức", "thì sao", "còn chuẩn", "vậy giấy", "vậy loại",
    ]
    has_discourse_connector = (
        any(phrase in q_lower for phrase in discourse_connector_phrases)
        or q_lower.startswith(("vậy ", "còn ", "thế "))
    )
    has_explicit_marker = has_anaphoric_pronoun or has_discourse_connector

    # Bỏ qua ngay các câu cảm thán, cảm ơn, xác nhận hoặc câu lệnh ngắn không có nội dung tra cứu
    short_non_query_phrases = (
        "đặt câu hỏi đi", "hỏi đi", "nói đi", "trả lời đi", "tiếp đi", "tiếp tục đi",
        "gợi ý đi", "cho câu hỏi đi", "bắt đầu đi", "làm đi", "cảm ơn", "cám ơn",
        "thanks", "thank you", "tks", "ok", "okay", "oke", "oki", "hiểu rồi", "biết rồi",
        "đã hiểu", "vâng", "dạ", "ừ", "ờ", "rồi", "tốt quá", "hay quá", "tuyệt vời",
    )
    q_stripped_punct = re.sub(r"^[\s\.,!?;:\-]+|[\s\.,!?;:\-]+$", "", q_lower).strip()
    if len(q_stripped_punct.split()) <= 6 and not has_explicit_marker and "?" not in q_lower:
        if q_stripped_punct in short_non_query_phrases or any(
            q_stripped_punct.startswith(p) for p in ("cảm ơn", "cám ơn", "thank", "đặt câu hỏi", "hỏi đi", "nói đi", "trả lời đi")
        ):
            return raw_query

    contextual_question_markers = [
        "bao lâu", "như thế nào", "ra sao", "nộp ở đâu", "nộp cho ai", "xin ở đâu", "lấy ở đâu",
        "gồm những gì", "bao nhiêu tiền", "bao nhiêu điểm", "mấy điểm", "mức tiền", "công thức tính",
        "đúng không", "phải không", "tức là", "nghĩa là", "vậy là",
        "như vậy", "được không", "mấy buổi", "bao nhiêu buổi", "mấy ngày", "bao nhiêu ngày",
    ]
    has_contextual_marker = any(marker in q_lower for marker in contextual_question_markers)

    interrogative_words = (
        "gì", "nào", "bao nhiêu", "bao lâu", "mấy", "thế nào", "như thế nào",
        "ra sao", "sao", "ở đâu", "đâu", "ai", "được không", "phải không",
        "đúng không", "hay không", "có được", "có bị", "có phải", "khi nào",
    )
    has_interrogative = (
        "?" in q_lower
        or any(
            (w in q_lower if " " in w else bool(re.search(rf"\b{re.escape(w)}\b", q_lower)))
            for w in interrogative_words
        )
    )

    standalone_subjects = [
        "học bổng", "kkht", "spkt", "miễn giảm học phí", "miễn, giảm học phí",
        "hỗ trợ chi phí học tập", "hoàn trả học phí", "học phí thừa", "qt-sv-04",
        "công tác xã hội", "ctxh", "công tác sinh viên", "kỷ luật", "ban cán sự",
        "quy tắc ứng xử", "an toàn thông tin", "mật khẩu", "nghị quyết",
        "thi hộ", "thi thay", "học thay", "phòng thi", "khiển trách",
        "cảnh cáo", "đình chỉ", "buộc thôi học", "điểm rèn luyện",
        "khóa luận", "tốt nghiệp", "danh hiệu", "xuất sắc", "sinh viên giỏi",
        "khen thưởng", "quy định", "quy chế", "quy trình", "thông báo", "hướng dẫn",
        "đề cương", "it1216", "mã nguồn mở", "trang phục", "ứng xử trên mạng",
        "cấp lại mật khẩu", "email sinh viên",
    ]
    has_article_or_section_ref = bool(
        re.search(r"\b(?:điều|khoản|mục|chương|phụ\s+lục|biểu\s+mẫu|mẫu)\s+[ivxlcdm\d]+", q_lower)
    )
    has_standalone_subject = (
        any(subj in q_lower for subj in standalone_subjects)
        or has_article_or_section_ref
    )

    needs_rewrite = has_anaphoric_pronoun or (
        (has_discourse_connector or has_contextual_marker or has_interrogative)
        and len(q_lower.split()) <= 28
        and not has_standalone_subject
    )
    if not needs_rewrite:
        return raw_query

    # Ưu tiên giải quyết đại từ/ngữ cảnh nối tiếp 2 chiều (Assistant liền trước + Chủ đề User) (< 0.5ms)
    asst_anchor, user_topic_anchor = _extract_assistant_drilldown_anchor(q_lower, recent_history)
    topic_anchor = asst_anchor or user_topic_anchor
    if topic_anchor and topic_anchor.lower() not in q_lower:
        rewritten_det = raw_query.strip()
        pronoun_sub_re = re.compile(
            r"\b(?:của\s+nó|nó|cái\s+đó|cái\s+này|mức\s+này|mức\s+đó|loại\s+này|loại\s+đó|"
            r"khoản\s+này|quy\s+định\s+này|quy\s+trình\s+này|trường\s+hợp\s+này|đối\s+tượng\s+này|"
            r"học\s+phần\s+này|học\s+phần\s+đó|môn\s+này|môn\s+đó|chế\s+độ\s+này|chính\s+sách\s+này|"
            r"học\s+bổng\s+này|học\s+bổng\s+đó|quy\s+tắc\s+này|quy\s+chế\s+này|hoạt\s+động\s+này|danh\s+hiệu\s+này|"
            r"giấy\s+tờ\s+đó|giấy\s+tờ\s+này|giấy\s+đó|giấy\s+này|đơn\s+đó|đơn\s+này|"
            r"biểu\s+mẫu\s+đó|biểu\s+mẫu\s+này|mẫu\s+đó|mẫu\s+này|minh\s+chứng\s+đó|minh\s+chứng\s+này|"
            r"hồ\s+sơ\s+đó|hồ\s+sơ\s+này|điều\s+kiện\s+này|điều\s+kiện\s+đó|tiêu\s+chuẩn\s+này|tiêu\s+chuẩn\s+đó|"
            r"yêu\s+cầu\s+này|yêu\s+cầu\s+đó|chuẩn\s+đó|chuẩn\s+này|mốc\s+đó|mốc\s+này|"
            r"hệ\s+số\s+đó|hệ\s+số\s+này|tỷ\s+lệ\s+đó|tỷ\s+lệ\s+này|điểm\s+đó|điểm\s+này|"
            r"hoạt\s+động\s+đó|môn\s+tiên\s+quyết\s+đó|học\s+phần\s+tiên\s+quyết\s+đó)\b",
            flags=re.IGNORECASE,
        )
        if pronoun_sub_re.search(rewritten_det):
            def _repl(m):
                matched_low = m.group(0).lower()
                if matched_low.startswith("của "):
                    return f"của {topic_anchor}"
                return topic_anchor
            rewritten_det = pronoun_sub_re.sub(_repl, rewritten_det, count=1)
            rewritten_det = re.sub(r"^(?:vậy\s+thì|vậy\s+còn|thế\s+còn|vậy|còn|thế)\s+", "", rewritten_det, flags=re.IGNORECASE).strip()
        else:
            q_punct = "?" if rewritten_det.endswith("?") else ""
            body_no_punct = rewritten_det.rstrip("?.! ").strip()
            body_no_lead = re.sub(r"^(?:vậy\s+thì|vậy\s+còn|thế\s+còn|vậy|còn|thế)\s+", "", body_no_punct, flags=re.IGNORECASE).strip()
            rewritten_det = f"{body_no_lead} đối với {topic_anchor}{q_punct}"
        rewritten_det = re.sub(r"\s+", " ", rewritten_det).strip()
        print(f"[QUERY REWRITE] (0.001s) '{raw_query}' -> '{rewritten_det}'")
        return rewritten_det

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
        "- Giữ nguyên đầy đủ các con số, giả định phép tính của sinh viên trong câu hỏi hiện tại và gắn thêm chủ ngữ/định mức từ lượt hội thoại trước.\n"
        "- Không tự bịa thông tin mới không có trong lịch sử.\n\n"
        f"Lịch sử hội thoại gần nhất:\n{history_block}\n\n"
        f"Câu hỏi hiện tại: {raw_query}\n"
        "Câu hỏi độc lập:"
    )

    try:
        t_rw = time.time()
        rewriter_llm = get_rewriter_llm()
        resp = rewriter_llm.invoke(rewrite_prompt)
        rewritten = strip_think_tags(getattr(resp, "content", str(resp))).strip()
        rewritten = re.sub(r"^(Câu hỏi độc lập|Câu hỏi viết lại)\s*:\s*", "", rewritten, flags=re.IGNORECASE)
        rewritten = rewritten.strip().strip('"').strip("'").splitlines()[0].strip()
        if rewritten and len(rewritten) >= 5:
            rw_elapsed = round(time.time() - t_rw, 3)
            print(f"[QUERY REWRITE] ({rw_elapsed}s) '{raw_query}' -> '{rewritten}'")
            return rewritten
    except Exception as err:
        print(f"[QUERY REWRITE WARNING] Không thể viết lại câu hỏi: {err}")

    return raw_query


@st.cache_resource(show_spinner=False)
def get_rag_chain():
    """Khởi tạo hoặc trả về chain RAG đã được lưu trong bộ nhớ đệm (singleton + @st.cache_resource)."""
    global _GLOBAL_CHAIN
    if _GLOBAL_CHAIN is not None:
        return _GLOBAL_CHAIN

    vector_db = get_vector_db()
    llm = get_llm()
    get_rewriter_llm()

    system_prompt = (
        "Bạn là trợ lý giải đáp thắc mắc về quy chế và học vụ cho sinh viên VLUTE.\n"
        "NGUYÊN TẮC TRẢ LỜI:\n"
        "1. CHỈ sử dụng thông tin có trong tài liệu quy chế dưới đây để trả lời. Tuyệt đối không tự suy diễn hoặc dùng kiến thức ngoài tài liệu.\n"
        "2. Trả lời đúng trọng tâm và phân biệt rõ bản chất câu hỏi:\n"
        "   - Tách bạch từng hành vi/điều kiện đối với câu hỏi ghép nhiều vế (áp dụng tổng quát cho mọi văn bản quy chế hiện tại và tương lai): Khi sinh viên hỏi câu ghép nhắc đến nhiều hành vi, đối tượng hoặc trường hợp cùng lúc (ví dụ: vừa hỏi hành vi thi hộ vừa hỏi hành vi mang tài liệu vào phòng thi, hoặc hỏi gộp nhiều diện đối tượng/mức quy định), BẮT BUỘC phân tích và trình bày tách riêng từng ý/gạch đầu dòng theo đúng điều khoản hoặc dòng bảng quy định của từng hành vi/đối tượng đó. Tuyệt đối không gộp chung hoặc áp nhầm khung xử lý/định mức của mục này sang mục khác; nếu một ý thuộc quy định có trong tài liệu còn ý kia thuộc văn bản khác hoặc chưa được đề cập trong đoạn trích hiện tại thì phải tách bạch và nêu rõ cho từng ý.\n"
        "   - Phân biệt rạch ròi giữa 'Miễn giảm học phí' (chế độ giảm trừ tiền học) và 'Trợ cấp xã hội / Hỗ trợ chi phí học tập' (các khoản chi trả tiền mặt/sinh hoạt phí).\n"
        "   - Nếu người dùng hỏi về 'trợ cấp xã hội' hoặc 'hỗ trợ chi phí học tập' mà tài liệu chỉ quy định về 'miễn giảm học phí' (hoặc chỉ nhắc đến giấy tờ 'Quyết định trợ cấp xã hội' như một thành phần hồ sơ minh chứng), hãy làm rõ điểm này: nêu rõ đối tượng được miễn giảm học phí theo quy định, đồng thời chỉ rõ văn bản hiện tại chưa quy định riêng về khoản tiền trợ cấp xã hội độc lập.\n"
        "   - Đối soát toán học & định lượng tổng quát (áp dụng cho mọi văn bản hiện tại và tương lai như ngày CTXH, số tín chỉ, điểm trung bình, tỷ lệ miễn giảm, mức học bổng, thời hạn xử lý...): Bất cứ khi nào sinh viên đưa ra một phép tính, con số quy đổi hoặc giả định cụ thể, PHẢI kiểm tra phép nhân/chia/so sánh đó đối chiếu với định mức trong văn bản và nêu rõ kết quả đúng/sai bằng phép tính cụ thể (ví dụ: 12 buổi × 0,5 ngày = 6 ngày, chưa đủ 12 ngày; nếu tính theo mức 0,5 ngày/buổi thì cần 12 : 0,5 = 24 buổi mới đủ 12 ngày) trước khi giải thích các trường hợp ngoại lệ hoặc các mức quy đổi khác nhau trong quy định.\n"
        "   - Khi sinh viên hỏi 'có nợ môn hoặc nợ học phí thì được xét học bổng không?': Căn cứ Điều 17 (yêu cầu tối thiểu 17 tín chỉ, không có học phần nào dưới điểm C) và Điều 1 (hoàn thành nghĩa vụ học phí) để trả lời rõ ràng: Sinh viên nợ môn (dưới điểm C) hoặc chưa hoàn thành học phí sẽ KHÔNG đủ điều kiện xét cấp học bổng khuyến khích học tập. Tuyệt đối không trả về thông báo từ chối ngoài phạm vi dữ liệu đối với câu hỏi này.\n"
        "   - Khi sinh viên hỏi về điều kiện xét học bổng khuyến khích học tập (tín chỉ, điểm TBC, hoặc điểm rèn luyện theo Điều 17): Luôn nêu đầy đủ cả 3 tiêu chuẩn cốt lõi tại Điều 17 gồm: (1) Đăng ký tối thiểu 17 tín chỉ, (2) Điểm TBC học kỳ đạt từ 2,5 trở lên theo thang 4,0 (riêng Học bổng KKHT Mức 1 / SPKT yêu cầu từ 3,2 trở lên) và không có học phần dưới điểm C, (3) Xếp loại rèn luyện đạt từ loại Khá trở lên (riêng Mức 1 / SPKT yêu cầu từ loại Tốt trở lên).\n"
        "   - Khi sinh viên hỏi về mức tiền hoặc cách tính Học bổng KKHT Mức 1 (Học bổng SPKT) tại Điều 18: Nêu rõ công thức 'Học bổng KKHT Mức 1 (Học bổng SPKT) = Đơn giá học phí × 17 TC', trong đó 'Đơn giá học phí = Đơn giá học phí theo khối ngành VII (hệ đại trà)'.\n"
        "   - Cấm tự đặt ví dụ giả định cho mọi văn bản quy chế: Chỉ nêu đúng công thức, tỷ lệ và con số được quy định nguyên văn trong tài liệu; tuyệt đối KHÔNG tự đặt ví dụ tính thử bằng số tiền, điểm số hay định mức giả định (như tự lấy đơn giá tín chỉ giả định để nhân thử) khi sinh viên không đưa ra con số cụ thể để tính, giúp câu trả lời cô đọng và chuẩn xác cho mọi quy chế hiện tại lẫn về sau.\n"
        "   - Khi đọc Bảng quy đổi ngày CTXH (Điều 8 Quyết định 55, Trang 9–10) bị tách cột qua 2 trang liên tiếp: đối chiếu theo mã số tương ứng gồm Mùa hè xanh (001101 - tham gia các đội hình chuyên), Tiếp sức mùa thi (001301), Tiếp sức tân sinh viên (001501) đều quy đổi 1 ngày CTXH / ngày tham gia (tối thiểu 5 giờ làm việc hoặc 1 ca trực theo phân công); Trực tiếp hiến máu tình nguyện (001202) quy đổi 1 ngày CTXH (theo Giấy xác nhận hiến máu); Hỗ trợ tổ chức hoạt động hiến máu tình nguyện (001201) quy đổi 0,5 ngày CTXH (theo Bảng phân công nhiệm vụ hỗ trợ).\n"
        "   - Khi đọc Phụ lục Khung xử lý kỷ luật sinh viên (Quyết định 1079, Trang 25–34, 4 cột mức kỷ luật theo thứ tự: Khiển trách | Cảnh cáo | Đình chỉ có thời hạn | Buộc thôi học): mục 4 (Học thay hoặc nhờ người khác học thay) xử lý từ Khiển trách đến Buộc thôi học tùy mức độ; mục 5 (Thi, kiểm tra thay hoặc nhờ thi, kiểm tra thay; làm thay, nhờ làm hoặc sao chép tiểu luận, đồ án, khóa luận tốt nghiệp) xử lý Đình chỉ học tập có thời hạn (vi phạm lần 1) và Buộc thôi học (vi phạm lần 2); mục 6 (Tổ chức học, thi, kiểm tra thay) xử lý Buộc thôi học ngay từ lần 1 (nếu nghiêm trọng giao cơ quan chức năng xử lý theo pháp luật).\n"
        "   - Khi sinh viên hỏi về quyền lợi điểm rèn luyện của Ban cán sự lớp / Cán bộ lớp / Đoàn – Hội, phải đối chiếu quy định trong tài liệu để nêu rõ số điểm rèn luyện được cộng cụ thể theo từng chức danh và mức độ hoàn thành nhiệm vụ (nếu văn bản có quy định) thay vì chỉ trả lời chung chung.\n"
        "   - Độ chính xác tuyệt đối với điều kiện biên (Boundary Conditions): Khi đối chiếu điểm rèn luyện, điểm trung bình, tỷ lệ dự lớp/vắng mặt, số tín chỉ hoặc mức hỗ trợ, BẮT BUỘC phân biệt chính xác các dấu và cụm từ so sánh toán học: 'từ X trở lên' / 'tối thiểu X' / 'ít nhất X' nghĩa là >= X (đạt đúng bằng X là ĐỦ điều kiện); 'trên X' / 'lớn hơn X' nghĩa là > X; 'dưới X' / 'nhỏ hơn X' nghĩa là < X; 'không quá X' / 'tối đa X' nghĩa là <= X. Ví dụ cụ thể: (1) Quy chế học bổng KKHT yêu cầu kết quả rèn luyện đạt từ loại Khá trở lên (khung điểm rèn luyện loại Khá là từ 65 đến dưới 80 điểm), nên sinh viên đạt đúng 65 điểm rèn luyện là ĐẠT loại Khá (>= 65) và ĐỦ điều kiện về điểm rèn luyện để xét học bổng KKHT loại Khá; (2) Đề cương học phần IT1216 quy định sinh viên phải tham dự tối thiểu 80% số tiết học trên lớp, nên sinh viên vắng mặt đúng 20% số tiết (tức đã tham dự đúng 80% số tiết trên lớp, >= 80%) vẫn ĐỦ điều kiện chuyên cần dự lớp (chỉ khi vắng trên 20%, tức dự lớp dưới 80%, mới không đạt).\n"
        "   - Xử lý câu hỏi ghép 'nửa trong – nửa ngoài' (Hybrid In-Scope + Out-of-Scope / Fabricated Trap): Khi câu hỏi của sinh viên ghép một vế có thật trong tài liệu quy chế/đề cương với một vế ngoài phạm vi hoặc thông tin bịa đặt (ví dụ: hỏi điều kiện học bổng KKHT hoặc miễn giảm học phí kèm chế độ 'tặng laptop / thưởng tiền Tết / miễn thi cuối kỳ / tặng vé gửi xe tháng'), BẮT BUỘC tách câu trả lời thành 2 phần gạch đầu dòng rõ ràng: (1) Trả lời đầy đủ, chính xác phần nội dung có trong tài liệu quy chế/đề cương; và (2) Khẳng định dứt khoát rằng vế còn lại KHÔNG có trong quy định hiện hành của Nhà trường, tuyệt đối không suy diễn hoặc hùa theo vế bịa đặt.\n"
        "3. Phong cách trả lời:\n"
        "   - Tuyệt đối KHÔNG dùng các cụm từ máy móc làm lộ kỹ thuật prompt như 'Dựa trên ngữ cảnh được cung cấp', 'Theo ngữ cảnh được cung cấp', 'Theo ngữ cảnh', 'Trong đoạn trích', 'Tài liệu cung cấp', 'Dựa vào đoạn văn bản trên', 'Trong văn bản được trích dẫn', 'Theo văn bản được trích dẫn', 'tài liệu được trích dẫn'; thay vào đó diễn đạt tự nhiên như cán bộ tư vấn học vụ (ví dụ: 'Theo quy định hiện hành của Nhà trường...', 'Theo quy định tại VLUTE...', hoặc đi thẳng vào nội dung trả lời).\n"
        "   - Đi thẳng vào câu hỏi, diễn đạt tự nhiên, rõ ràng, súc tích.\n"
        "   - KHÔNG cần trích dẫn rườm rà số hiệu quyết định hay điều khoản trừ khi câu hỏi yêu cầu cụ thể.\n"
        "   - Trình bày dạng gạch đầu dòng ngắn gọn để sinh viên nắm bắt thông tin nhanh nhất.\n"
        "   - Tuyệt đối KHÔNG kẻ bảng Markdown bằng dấu gạch đứng (| ... |) và KHÔNG dùng thẻ HTML như <br>; luôn chuyển dữ liệu bảng thành các gạch đầu dòng phân cấp rõ ràng.\n"
        "   - Tuyệt đối KHÔNG dùng ký hiệu toán học LaTeX như '\\[ ... \\]', '\\( ... \\)', '$$ ... $$', '\\text', '\\frac', '\\div', '\\times'. Luôn viết phép tính bằng chữ và số thuần túy rõ ràng (ví dụ: 15 - 3 = 12 ngày còn thiếu; 12 : 0,5 = 24 buổi).\n"
        f"4. CHỈ trả về hằng số REFUSAL_MESSAGE duy nhất (không giải thích thêm) khi câu hỏi hoàn toàn nằm ngoài phạm vi các văn bản quy chế tham khảo (ví dụ: hỏi giá phòng ký túc xá, điểm chuẩn tuyển sinh, tuyến xe buýt, học phí 1 tín chỉ...). Nếu tài liệu quy chế đã có quy định liên quan đến chủ đề câu hỏi, tuyệt đối KHÔNG trả về REFUSAL_MESSAGE:\n{REFUSAL_MESSAGE}\n\n"
        "Nội dung quy chế tham khảo:\n{context}\n\n"
        "Câu hỏi: {input}\n\n"
        "Trả lời:"
    )

    prompt = ChatPromptTemplate.from_template(system_prompt)
    _GLOBAL_CHAIN = SmartRAGChain(vector_db, llm, prompt)
    return _GLOBAL_CHAIN
