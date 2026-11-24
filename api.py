from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag import (
    FRIENDLY_ERROR_MESSAGE,
    MAX_QUERY_LENGTH,
    REFUSAL_MESSAGE,
    STREAM_INTERRUPTED_NOTICE,
    TOO_LONG_QUERY_MESSAGE,
    auto_sync_knowledge_base,
    clip_context_text,
    extract_article_info,
    get_greeting_or_chitchat_reply,
    get_rag_chain,
    is_greeting_or_chitchat,
    is_prompt_injection,
    load_departments_config,
    normalize_chat_slang,
    rewrite_conversational_query,
    sanitize_client_error_message,
    sanitize_no_markdown_tables,
)

BASE_DIR = Path(__file__).resolve().parent
PROMPTS_FILE = BASE_DIR / "prompts.json"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
LOGO_PATH = BASE_DIR / "logo_vlute.png"
AVATAR_PATH = BASE_DIR / "lucas_avatar.png"

ANSWER_CACHE_TTL = 1800
WELCOME_CONTENT = (
    "**Xin chào! Mình là Lucas** – trợ lý hỗ trợ tra cứu Quy chế Đào tạo & Quy định sinh viên VLUTE.\n\n"
    "Bạn có thể chọn nhanh một trong các câu hỏi gợi ý bên dưới hoặc nhập trực tiếp thắc mắc về học bổng, miễn giảm học phí, công tác xã hội, kỷ luật hay học vụ!"
)
RATE_LIMIT_MESSAGE = (
    "⚠️ Hệ thống tra cứu đang nhận lượng truy cập cao trong cùng thời điểm. "
    "Bạn vui lòng đợi khoảng 30–60 giây rồi thử hỏi lại nhé!"
)
CLARIFY_EMPTY_QUERY_MESSAGE = (
    "Bạn vui lòng nhập nội dung câu hỏi cụ thể về quy chế hoặc chọn một gợi ý bên dưới để Lucas hỗ trợ nhé!"
)

GREETING_KEYWORDS = [
    "chào", "hello", "hi", "bạn là ai", "tên gì", "giới thiệu", "alo", "lucas", "xin chào", "hey", "ad"
]
GREETING_REPLIES = [
    "Chào bạn! Mình là Lucas – trợ lý học vụ VLUTE. Hôm nay bạn muốn tra cứu quy định về học bổng, học phí, công tác xã hội hay học vụ? *(Bạn có thể bấm chọn nhanh gợi ý bên dưới hoặc nhập trực tiếp câu hỏi nhé!)*",
    "Xin chào! Rất vui được đồng hành cùng bạn. Bạn đang quan tâm đến chế độ chính sách, điểm rèn luyện hay quy chế đào tạo tại VLUTE? *(Hãy chọn một gợi ý bên dưới hoặc gõ câu hỏi cụ thể nhé!)*",
    "Chào bạn nhé! Lucas luôn sẵn sàng hỗ trợ bạn giải đáp các quy định về khóa luận, tốt nghiệp hay kỷ luật sinh viên VLUTE. *(Bạn có thể tham khảo các câu hỏi gợi ý bên dưới hoặc đặt câu hỏi trực tiếp cho mình!)*",
    "Chào bạn! Mình có thể giúp gì cho bạn hôm nay? Bạn cứ nhập thắc mắc về học vụ, miễn giảm học phí, học bổng hoặc chọn nhanh một chủ đề gợi ý ngay bên dưới nhé!",
]

_FOLLOWUP_Q_STOPWORDS = frozenset({
    "ai", "nao", "nhung", "cac", "cua", "va", "hoac", "duoc", "la", "gi",
    "the", "ra", "sao", "bao", "nhieu", "theo", "hien", "hanh", "nhu", "co",
    "bi", "xin", "cho", "tai", "voi", "trong", "ve", "de", "den", "hay",
    "thi", "ma", "sinh", "vien", "nha", "truong", "quy", "dinh", "xem",
    "xet", "thuoc", "dien", "dieu", "o", "dau",
})

SIDEBAR_LINK_GROUPS = [
    {
        "title": "HỆ THỐNG HỌC TẬP",
        "icon": "link",
        "items": [
            {"label": "My VLUTE", "title": "Cổng thông tin My VLUTE", "url": "https://vlute.edu.vn/", "icon": "globe"},
            {"label": "ĐK Học phần", "title": "Đăng ký học phần", "url": "https://daotao.vlute.edu.vn/sinh-vien", "icon": "file-edit"},
            {"label": "E-Learning", "title": "Học trực tuyến E-Learning", "url": "http://elearning.vlute.edu.vn/", "icon": "monitor"},
            {"label": "Thanh toán", "title": "Cổng thanh toán Trực tuyến", "url": "https://thanhtoan.vlute.edu.vn/", "icon": "credit-card"},
        ],
    },
    {
        "title": "ĐƠN VỊ HỖ TRỢ",
        "icon": "landmark",
        "items": [
            {"label": "Tuyển sinh", "title": "Phòng Tuyển sinh", "url": "https://tuyensinh.vlute.edu.vn/", "icon": "compass"},
            {"label": "Đào tạo (A1.101)", "title": "Phòng Đào tạo - Đảm bảo chất lượng (A1.101)", "url": "http://pdt.vlute.edu.vn/", "icon": "clipboard-list"},
            {"label": "CTSV (A1.102)", "title": "Phòng Công tác sinh viên và Truyền thông (A1.102)", "url": "http://cgtdt-dsa.vlute.edu.vn/", "icon": "users"},
            {"label": "KHTC (Tầng trệt)", "title": "Phòng Kế hoạch - Tài chính (Tầng trệt)", "url": "https://vlute.edu.vn/phong-ke-hoach-tai-chinh", "icon": "wallet"},
        ],
    },
]

_chain_lock = threading.Lock()
_cache_lock = threading.Lock()
_greeting_lock = threading.Lock()
_rate_limit_lock = threading.Lock()
_rag_chain: Any = None
_ANSWER_CACHE: dict[str, dict[str, Any]] = {}
_greeting_counter = 0

RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0
CLIENT_RATE_LIMIT_MESSAGE = (
    "⚠️ Bạn đang gửi yêu cầu quá nhanh (vượt giới hạn 20 yêu cầu/phút). "
    "Bạn vui lòng chờ vài giây rồi thử hỏi lại nhé!"
)
_client_request_timestamps: dict[str, list[float]] = {}


def _check_client_rate_limit(request: Request | None) -> bool:
    """Giới hạn tối đa 20 yêu cầu/phút trên mỗi IP/Session client."""
    if request is None:
        return False
    client_key = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Client-Session", "").strip()
        or (request.client.host if request.client else "127.0.0.1")
    )
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        recent_ts = [ts for ts in _client_request_timestamps.get(client_key, []) if ts > cutoff]
        if len(recent_ts) >= RATE_LIMIT_MAX_REQUESTS:
            _client_request_timestamps[client_key] = recent_ts
            return True
        recent_ts.append(now)
        _client_request_timestamps[client_key] = recent_ts
        return False


def get_cached_rag_chain():
    """Khởi tạo và giữ singleton RAG chain dùng chung toàn server FastAPI."""
    global _rag_chain
    if _rag_chain is not None:
        return _rag_chain
    with _chain_lock:
        if _rag_chain is None:
            _rag_chain = get_rag_chain()
    return _rag_chain


def ensure_kb_synced_and_fresh_cache() -> dict:
    """Kiểm tra thay đổi ở thư mục data/ và xóa ANSWER_CACHE nếu cơ sở tri thức cập nhật."""
    sync_res = auto_sync_knowledge_base()
    if isinstance(sync_res, dict) and sync_res.get("changed"):
        with _cache_lock:
            _ANSWER_CACHE.clear()
    return sync_res if isinstance(sync_res, dict) else {"changed": False}


def _strip_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và chuẩn hóa ký tự thành slug gạch dưới."""
    if not text:
        return ""
    s = text.lower().replace("đ", "d")
    s = "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def load_prompts_config() -> dict:
    """Đọc cấu hình câu hỏi gợi ý từ tệp prompts.json."""
    if PROMPTS_FILE.exists():
        try:
            with PROMPTS_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"initial_prompts": [], "categories": {}}


def get_random_welcome_prompts(previous_queries: list[str] | None = None) -> list[dict[str, str]]:
    """Chọn 4 câu hỏi gợi ý ngẫu nhiên từ 4 nhóm trong prompts.json, loại trừ bộ đang hiển thị."""
    import random

    config = load_prompts_config()
    categories = config.get("categories", {})
    prev_set = {str(q).strip() for q in (previous_queries or []) if str(q).strip()}
    selected: list[dict[str, str]] = []
    remaining_pool: list[dict[str, str]] = []

    for _cat_key, cat_data in categories.items():
        prompts = [
            {"label": str(p["label"]), "query": str(p["query"])}
            for p in cat_data.get("prompts", [])
            if isinstance(p, dict) and p.get("label") and p.get("query")
        ]
        if prompts:
            candidates = [p for p in prompts if p["query"].strip() not in prev_set]
            pool = candidates if candidates else prompts
            chosen = random.choice(pool)
            selected.append(chosen)
            for p in prompts:
                if p != chosen and p["query"].strip() not in prev_set:
                    remaining_pool.append(p)

    if len(selected) > 4:
        selected = random.sample(selected, 4)
    elif len(selected) < 4:
        fallback_pool = remaining_pool or [
            {"label": str(p["label"]), "query": str(p["query"])}
            for p in config.get("initial_prompts", [])
            if isinstance(p, dict) and p.get("label") and p.get("query") and str(p["query"]).strip() not in prev_set
        ]
        need = 4 - len(selected)
        if fallback_pool:
            selected.extend(random.sample(fallback_pool, min(need, len(fallback_pool))))

    return selected[:4]


def is_greeting(query: str) -> bool:
    """Nhận diện lời chào xã giao ngắn bằng ranh giới từ để không nhầm câu hỏi quy chế."""
    clean = (query or "").lower().strip()
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
    """Phát hiện câu trả lời thuộc diện từ chối ngoài phạm vi, báo quá tải hoặc bị gián đoạn."""
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


def normalize_query_intent(query: str) -> str:
    """Chuẩn hóa tiếng chat Zalo/viết tắt sinh viên, làm sạch khoảng trắng, lọc từ gọi bot và mở rộng viết tắt ở câu ngắn."""
    if not query:
        return ""
    cleaned = re.sub(r"\s+", " ", normalize_chat_slang(query.strip()))
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


def check_department_inquiry(query: str) -> str | None:
    """Xử lý nhánh hỏi trực tiếp thông tin liên hệ/địa chỉ phòng ban giống hệt app.py."""
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
        "đường link", "link cổng", "link trang", "trang web", "website", "cổng thông tin phòng",
        "liên hệ phòng nào", "liên hệ đơn vị nào", "liên hệ bộ phận nào",
        "hỏi phòng nào", "tới phòng nào", "đến phòng nào", "qua phòng nào",
        "phòng nào hỗ trợ", "đơn vị nào hỗ trợ", "bộ phận nào hỗ trợ",
    ]
    if not any(kw in q for kw in ask_contact_keywords):
        return None

    departments = load_departments_config()
    pdt = departments.get("daotao") or departments.get("dao_tao") or {
        "name": "Phòng Đào tạo (VLUTE)",
        "location": "Tòa nhà A (Tầng 1)",
        "phone": "(0270) 3822 140",
        "email": "daotao@vlute.edu.vn",
    }
    ctsv = departments.get("ctsv", {
        "name": "Phòng Công tác Sinh viên (VLUTE)",
        "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
        "phone": "(0270) 3862 436",
        "email": "ctsv@vlute.edu.vn",
    })
    khtc = departments.get("khtc", {
        "name": "Phòng Kế hoạch - Tài chính (VLUTE)",
        "location": "Tòa nhà A (Tầng trệt)",
        "phone": "(0270) 3822 141",
        "email": "khtc@vlute.edu.vn",
    })
    cntt = departments.get("cntt", {
        "name": "Trung tâm Công nghệ Thông tin (VLUTE)",
        "location": "Tòa nhà B",
        "phone": "(0270) 3862 250",
        "email": "ttcntt@vlute.edu.vn",
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
    if has_cntt:
        return (
            f"Thông tin liên hệ của **{cntt['name']}** như sau:\n\n"
            f"• **Vị trí phòng làm việc:** {cntt['location']}\n"
            f"• **Số điện thoại:** {cntt['phone']}\n"
            f"• **Email tiếp nhận:** {cntt['email']}\n\n"
            "Bạn có thể liên hệ để được hỗ trợ cấp lại mật khẩu cổng thông tin, tài khoản E-Learning, email sinh viên và sự cố kết nối mạng."
        )
    if has_pdt:
        return (
            f"Thông tin liên hệ của **{pdt['name']}** như sau:\n\n"
            f"• **Vị trí phòng làm việc:** {pdt['location']}\n"
            f"• **Số điện thoại:** {pdt['phone']}\n"
            f"• **Email tiếp nhận:** {pdt['email']}\n\n"
            "Bạn có thể liên hệ trực tiếp trong giờ hành chính để được hướng dẫn giải quyết các thủ tục đào tạo, đăng ký môn học và học vụ."
        )
    if has_ctsv:
        return (
            f"Thông tin liên hệ của **{ctsv['name']}** như sau:\n\n"
            f"• **Vị trí phòng làm việc:** {ctsv['location']}\n"
            f"• **Số điện thoại:** {ctsv['phone']}\n"
            f"• **Email tiếp nhận:** {ctsv['email']}\n\n"
            "Bạn có thể liên hệ trực tiếp để được hỗ trợ về học bổng, chính sách miễn giảm học phí, rèn luyện và các thủ tục sinh viên."
        )
    if has_khtc:
        return (
            f"Thông tin liên hệ của **{khtc['name']}** như sau:\n\n"
            f"• **Vị trí phòng làm việc:** {khtc['location']}\n"
            f"• **Số điện thoại:** {khtc['phone']}\n"
            f"• **Email tiếp nhận:** {khtc['email']}\n\n"
            "Bạn có thể liên hệ để giải quyết các vấn đề nộp học phí, hoàn trả học phí thừa hoặc thủ tục hóa đơn, biên lai."
        )
    return None


def get_contact_footer_data(query: str, retrieved_docs=None, is_refusal: bool = False) -> dict[str, Any]:
    """Định tuyến phòng ban đầu mối và trả về JSON có cấu trúc cho frontend."""
    departments = load_departments_config()
    q_raw = str(query or "").lower()
    q_slug = _strip_accents(q_raw)

    ctsv_dept = departments.get("ctsv", {
        "name": "Phòng Công tác Sinh viên (VLUTE)",
        "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
        "phone": "(0270) 3862 436",
        "email": "ctsv@vlute.edu.vn",
    })
    pdt_dept = departments.get("dao_tao") or departments.get("daotao") or {
        "name": "Phòng Đào tạo (VLUTE)",
        "location": "Tòa nhà A (Tầng 1)",
        "phone": "(0270) 3822 140",
        "email": "daotao@vlute.edu.vn",
    }
    khtc_dept = departments.get("khtc", {
        "name": "Phòng Kế hoạch - Tài chính (VLUTE)",
        "location": "Tòa nhà A (Tầng trệt)",
        "phone": "(0270) 3822 141",
        "email": "khtc@vlute.edu.vn",
    })

    def _single(name: str, location: str, phone: str, email: str) -> dict[str, Any]:
        return {
            "type": "single",
            "title": name,
            "location": location,
            "phone": phone,
            "email": email,
        }

    def _hoan_tra_pipeline() -> dict[str, Any]:
        return {
            "type": "pipeline",
            "title": "Tuyến phối hợp xử lý (CTSV – Đào tạo – KHTC)",
            "steps": [
                {
                    "order": 1,
                    "role": "Tiếp nhận & tổng hợp đơn",
                    "name": ctsv_dept["name"],
                    "location": ctsv_dept["location"],
                    "phone": ctsv_dept["phone"],
                    "email": ctsv_dept["email"],
                },
                {
                    "order": 2,
                    "role": "Xác nhận học phí thừa",
                    "name": pdt_dept["name"],
                    "location": pdt_dept["location"],
                    "phone": pdt_dept["phone"],
                    "email": pdt_dept["email"],
                },
                {
                    "order": 3,
                    "role": "Thanh toán hoàn trả",
                    "name": khtc_dept["name"],
                    "location": khtc_dept["location"],
                    "phone": khtc_dept["phone"],
                    "email": khtc_dept["email"],
                },
            ],
        }

    # 1. Ưu tiên metadata của nguồn tài liệu truy xuất hàng đầu
    if retrieved_docs and not is_refusal and isinstance(retrieved_docs, (list, tuple)) and len(retrieved_docs) > 0:
        first_item = retrieved_docs[0]
        meta = getattr(first_item, "metadata", None)
        if meta is None and isinstance(first_item, dict):
            meta = first_item
        if isinstance(meta, dict) and meta.get("dept_name"):
            src_file = os.path.basename(str(meta.get("source", "") or meta.get("file", ""))).lower()
            if "hoan_tra_hoc_phi" in src_file:
                return _hoan_tra_pipeline()
            if "mien_giam_hoc_phi" in src_file:
                return _single(
                    "Phòng Công tác Sinh viên (VLUTE) – Đầu mối tiếp nhận hồ sơ (Phối hợp Phòng Kế hoạch - Tài chính)",
                    ctsv_dept["location"],
                    ctsv_dept["phone"],
                    ctsv_dept["email"],
                )
            return _single(
                str(meta.get("dept_name", ctsv_dept["name"])),
                str(meta.get("dept_location", ctsv_dept["location"])),
                str(meta.get("dept_phone", ctsv_dept["phone"])),
                str(meta.get("dept_email", ctsv_dept["email"])),
            )

    # 2. Nhóm học bổng, rèn luyện, kỷ luật, CTXH -> CTSV
    ctsv_priority_keywords = [
        "học bổng", "kkht", "khen thưởng", "rèn luyện", "điểm rèn luyện",
        "kỷ luật", "công tác xã hội", "ctxh", "nội quy", "ứng xử",
    ]
    if any(kw in q_raw for kw in ctsv_priority_keywords):
        return _single(ctsv_dept["name"], ctsv_dept["location"], ctsv_dept["phone"], ctsv_dept["email"])

    # 3. Nhóm miễn giảm học phí / hỗ trợ chi phí học tập -> CTSV phối hợp KHTC
    mien_giam_keywords = [
        "miễn giảm học phí", "miễn giảm", "giảm học phí", "miễn học phí",
        "hỗ trợ chi phí học tập", "hỗ trợ chi phí", "trợ cấp xã hội",
    ]
    if any(kw in q_raw for kw in mien_giam_keywords):
        return _single(
            "Phòng Công tác Sinh viên (VLUTE) – Đầu mối tiếp nhận hồ sơ (Phối hợp Phòng Kế hoạch - Tài chính)",
            ctsv_dept["location"],
            ctsv_dept["phone"],
            ctsv_dept["email"],
        )

    # 4. Hoàn trả học phí thừa -> Tuyến phối hợp 3 bước
    hoan_tra_keywords = [
        "hoàn trả học phí", "học phí thừa", "hoàn phí", "hoàn tiền học phí",
        "rút tiền học phí", "nộp thừa", "hoàn trả",
    ]
    if any(kw in q_raw for kw in hoan_tra_keywords):
        return _hoan_tra_pipeline()

    # 4b. Nộp học phí, hóa đơn, biên lai -> KHTC
    khtc_exclusive_keywords = ["rút tiền", "nộp học phí", "đóng học phí", "thu học phí", "hóa đơn", "biên lai"]
    if any(kw in q_raw for kw in khtc_exclusive_keywords):
        return _single(khtc_dept["name"], khtc_dept["location"], khtc_dept["phone"], khtc_dept["email"])

    # 5. Quét các phòng ban còn lại trong departments.json
    for dept_key, dept_info in departments.items():
        if dept_key == "khtc":
            continue
        for pat in dept_info.get("patterns", []):
            pat_str = str(pat).lower().strip()
            if not pat_str:
                continue
            if pat_str == "mang":
                if "mạng" in q_raw or "an_ninh_mang" in q_slug or "mang_internet" in q_slug or "mang_wifi" in q_slug:
                    return _single(dept_info["name"], dept_info["location"], dept_info["phone"], dept_info["email"])
            elif pat_str in q_slug or pat_str.replace("_", " ") in q_raw:
                return _single(dept_info["name"], dept_info["location"], dept_info["phone"], dept_info["email"])

    return _single(ctsv_dept["name"], ctsv_dept["location"], ctsv_dept["phone"], ctsv_dept["email"])


def _content_tokens(text: str) -> set[str]:
    return {t for t in _strip_accents(text).split("_") if t and t not in _FOLLOWUP_Q_STOPWORDS}


def _build_chronological_asked_turns(
    messages: list[dict[str, Any]] | None,
    query_or_content: str = "",
    asked_queries: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Tổng hợp các lượt hỏi theo thứ tự thời gian từ cũ đến mới cho LRU Recycling."""
    turns: list[list[str]] = []
    msg_list = messages or []
    for idx, msg in enumerate(msg_list):
        if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content"):
            texts = [str(msg.get("content", ""))]
            if idx + 1 < len(msg_list) and isinstance(msg_list[idx + 1], dict):
                nxt = msg_list[idx + 1]
                if nxt.get("role") == "assistant" and nxt.get("query"):
                    texts.append(str(nxt.get("query", "")))
            turns.append(texts)

    seen_all_norms = {_strip_accents(t) for grp in turns for t in grp if _strip_accents(t)}
    for extra in (asked_queries or []):
        en = _strip_accents(str(extra or ""))
        if en and en not in seen_all_norms:
            turns.append([str(extra)])
            seen_all_norms.add(en)

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


def _last_asked_turn_index(cand_q: str, cand_lbl: str, compiled_turns: list[dict[str, Any]]) -> int:
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


def select_followup_prompts(
    query_or_content: str,
    config: dict,
    messages: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    assistant_reply: str = "",
    asked_queries: list[str] | set[str] | None = None,
    limit: int = 2,
) -> list[dict[str, str]]:
    """Chọn 2 nút gợi ý liên quan theo cơ chế 3-tier LRU Recycling giống app.py."""
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

    categories = config.get("categories", {})
    best_cat_key = None
    best_score = 0
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

    all_candidates = []
    catalog_norms = set()
    for cat_prio, pool in ((0, primary_raw), (1, secondary_raw)):
        for order_idx, (lbl, q) in enumerate(pool):
            qn = _strip_accents(q)
            if qn and qn not in catalog_norms:
                catalog_norms.add(qn)
                last_idx = _last_asked_turn_index(q, lbl, compiled_turns)
                all_candidates.append((last_idx, cat_prio, order_idx, str(lbl), str(q), qn))

    prompts_to_show: list[dict[str, str]] = []
    selected_norms: set[str] = set()

    def _add(lbl: str, q: str, qn: str):
        prompts_to_show.append({"label": lbl, "query": q})
        selected_norms.add(qn)

    for target_prio in (0, 1):
        for last_idx, cat_prio, _order_idx, lbl, q, qn in all_candidates:
            if cat_prio == target_prio and last_idx == -1 and qn not in selected_norms:
                _add(lbl, q, qn)
                if len(prompts_to_show) >= limit:
                    return prompts_to_show

    total_turns = len(compiled_turns)
    recent_cutoff = max(0, total_turns - 4)
    remaining = [item for item in all_candidates if item[5] not in selected_norms]

    lru_eligible = sorted(
        (item for item in remaining if 0 <= item[0] < recent_cutoff),
        key=lambda x: (x[0], x[1], x[2]),
    )
    for _last_idx, _cat_prio, _order_idx, lbl, q, qn in lru_eligible:
        _add(lbl, q, qn)
        if len(prompts_to_show) >= limit:
            return prompts_to_show

    fallback_sorted = sorted(
        remaining,
        key=lambda x: (1 if x[0] >= max(0, total_turns - 1) else 0, x[0], x[1], x[2]),
    )
    for _last_idx, _cat_prio, _order_idx, lbl, q, qn in fallback_sorted:
        _add(lbl, q, qn)
        if len(prompts_to_show) >= limit:
            break

    return prompts_to_show


def _build_filtered_history(messages: list[dict[str, Any]], current_query: str) -> list[dict[str, str]]:
    """Lọc bỏ tin nhắn chào mừng, từ chối OOS và báo quá tải để tránh nhiễu câu nối tiếp."""
    work_msgs = list(messages or [])
    if work_msgs and work_msgs[0].get("role") == "assistant":
        if work_msgs[0].get("is_welcome") or str(work_msgs[0].get("content", "")).strip() == WELCOME_CONTENT.strip():
            work_msgs = work_msgs[1:]

    # Tránh đưa chính câu hỏi hiện tại vào lịch sử rewrite nếu frontend gửi kèm cuối mảng
    if work_msgs and work_msgs[-1].get("role") == "user":
        if str(work_msgs[-1].get("content", "")).strip() == current_query:
            work_msgs = work_msgs[:-1]

    filtered_history: list[dict[str, str]] = []
    for m in work_msgs:
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

    return filtered_history[-6:]


def _build_rag_prompt_and_sources(effective_query: str, docs: list, chain) -> tuple[str, list[dict[str, Any]]]:
    """Tạo chuỗi ngữ cảnh tối đa 5 đoạn trích (<= 560 ký tự/đoạn) và danh sách nguồn JSON."""
    context_parts = []
    sources: list[dict[str, Any]] = []
    for doc in docs[:5]:
        src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
        title = doc.metadata.get("title", src_file)
        page = doc.metadata.get("page", 1)
        raw_content = doc.page_content.strip()
        article = extract_article_info(doc.page_content)

        header_line = (
            f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | "
            f"Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | "
            f"Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
        )
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
            "snippet": raw_content,
        })

    context_str = "\n\n".join(context_parts)
    formatted_prompt = chain.prompt.format(context=context_str, input=effective_query)
    return formatted_prompt, sources


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prewarm RAG chain và đồng bộ tri thức nền khi server FastAPI khởi động."""
    def _prewarm():
        try:
            get_cached_rag_chain()
            ensure_kb_synced_and_fresh_cache()
        except Exception as exc:
            print(f"[FastAPI Prewarm Warning] {exc}")

    await asyncio.to_thread(_prewarm)
    yield


app = FastAPI(title="VLUTEBOT API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ShufflePromptsRequest(BaseModel):
    previous_queries: list[str] = Field(default_factory=list)


class ChatStreamRequest(BaseModel):
    query: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    asked_queries: list[str] = Field(default_factory=list)
    greeting_turn_count: int | None = None


@app.get("/api/health")
def health_check():
    return {"status": "ok", "rag_ready": _rag_chain is not None}


@app.get("/api/init")
def init_portal():
    """Trả dữ liệu khởi tạo đồng bộ 100% với app.py cho giao diện React."""
    depts_cfg = load_departments_config()
    sidebar_order = [k for k in ("dao_tao", "ctsv", "khtc", "cntt") if k in depts_cfg] + [
        k for k in depts_cfg.keys() if k not in ("dao_tao", "ctsv", "khtc", "cntt")
    ]
    departments_list = []
    for d_key in sidebar_order:
        d_item = depts_cfg.get(d_key, {})
        full_name = str(d_item.get("name", d_key))
        departments_list.append({
            "key": d_key,
            "name": full_name,
            "short_name": full_name.replace(" (VLUTE)", ""),
            "location": str(d_item.get("location", "")),
            "phone": str(d_item.get("phone", "")),
            "email": str(d_item.get("email", "")),
        })

    return {
        "welcome_content": WELCOME_CONTENT,
        "input_placeholder": "Hỏi về quy chế đào tạo, học bổng, học phí, học vụ VLUTE...",
        "prompts": get_random_welcome_prompts(),
        "branding": {
            "title": "LUCAS – TRỢ LÝ QUY CHẾ & HỌC VỤ VLUTE",
            "subtitle": "Hệ thống tra cứu từ văn bản chính thức của Nhà trường",
            "university_line_1": "TRƯỜNG ĐẠI HỌC",
            "university_line_2": "CNKT VĨNH LONG",
            "university_unit": "QUẢN LÝ ĐÀO TẠO & HỌC VỤ",
            "address": "Số 73 Nguyễn Huệ, Phường Long Châu, Tỉnh Vĩnh Long",
            "copyright_title": "© Trường ĐH Công nghệ Kỹ thuật Vĩnh Long",
            "copyright_sub": "(Tiền thân: Trường ĐH Sư phạm Kỹ thuật Vĩnh Long)",
            "logo_url": "/assets/logo_vlute.png",
            "avatar_url": "/assets/lucas_avatar.png",
            "badges": [
                {"id": "search", "label": "Tra cứu học vụ", "variant": "primary"},
                {"id": "official", "label": "Văn bản chính thức", "variant": "official"},
                {"id": "verified", "label": "Trả lời có căn cứ", "variant": "verified"},
            ],
        },
        "sidebar_links": SIDEBAR_LINK_GROUPS,
        "departments": departments_list,
    }


@app.post("/api/prompts/shuffle")
def shuffle_prompts(body: ShufflePromptsRequest):
    """Đổi 4 câu hỏi gợi ý khác hoàn toàn bộ đang hiển thị."""
    return {"prompts": get_random_welcome_prompts(previous_queries=body.previous_queries)}


@app.post("/api/chat")
def chat_sync(body: ChatStreamRequest, request: Request):
    """Endpoint đồng bộ /api/chat tích hợp đầy đủ các chốt chặn bảo mật, độ dài và chống spam giống /api/chat/stream."""
    current_user_query = (body.query or "").strip()
    if _check_client_rate_limit(request):
        return {
            "answer": CLIENT_RATE_LIMIT_MESSAGE,
            "verified": False,
            "is_refusal": True,
            "contact": None,
            "sources": [],
        }
    if len(current_user_query) > MAX_QUERY_LENGTH:
        return {
            "answer": TOO_LONG_QUERY_MESSAGE,
            "verified": False,
            "is_refusal": True,
            "contact": None,
            "sources": [],
        }
    if is_prompt_injection(current_user_query):
        return {
            "answer": REFUSAL_MESSAGE,
            "verified": False,
            "is_refusal": True,
            "contact": None,
            "sources": [],
        }
    try:
        norm_q = normalize_query_intent(current_user_query)
        recent_chat_history = _build_filtered_history(body.messages, current_user_query)
        rewritten_q = rewrite_conversational_query(norm_q, recent_chat_history)
        dept_reply = check_department_inquiry(rewritten_q)
        if dept_reply:
            return {
                "answer": dept_reply,
                "verified": False,
                "is_refusal": False,
                "is_dept_inquiry": True,
                "contact": None,
                "sources": [],
            }
        chain = get_cached_rag_chain()
        res = chain.invoke({"input": rewritten_q})
        ans = sanitize_no_markdown_tables(str(res.get("answer") or REFUSAL_MESSAGE))
        is_ref = bool(res.get("is_refusal")) or is_refusal_answer(ans)
        docs = res.get("context") or []
        contact = None if is_ref else get_contact_footer_data(rewritten_q, retrieved_docs=docs, is_refusal=False)
        return {
            "answer": ans,
            "verified": not is_ref and bool(docs),
            "is_refusal": is_ref,
            "contact": contact,
            "sources": [os.path.basename(str(d.metadata.get("source", ""))) for d in docs],
        }
    except Exception as err:
        return {
            "answer": sanitize_client_error_message(err, rate_limit_msg=RATE_LIMIT_MESSAGE),
            "verified": False,
            "is_refusal": True,
            "contact": None,
            "sources": [],
        }


@app.post("/api/chat/stream")
def chat_stream(body: ChatStreamRequest, request: Request):
    """Stream phản hồi qua SSE (chunk, meta, done) dùng chung 100% lõi RAG & logic app.py."""
    current_user_query = (body.query or "").strip()
    prompts_cfg = load_prompts_config()
    rate_limited = _check_client_rate_limit(request)

    def _event_generator():
        global _greeting_counter

        # 0a. Chốt chặn Rate Limiter (tối đa 20 yêu cầu/phút/IP)
        if rate_limited:
            turns_msgs = list(body.messages or []) + [{"role": "user", "content": current_user_query[:200]}]
            followups = select_followup_prompts(
                "", prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=CLIENT_RATE_LIMIT_MESSAGE, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": CLIENT_RATE_LIMIT_MESSAGE})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": None,
                "followups": followups,
                "sources": [],
                "rewritten_query": current_user_query[:200],
                "is_refusal": True,
                "is_greeting": False,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})
            return

        # 0b. Chốt chặn tin nhắn quá dài (> 2.000 ký tự) trong < 5 ms trước khi gọi Embedding/LLM
        if len(current_user_query) > MAX_QUERY_LENGTH:
            turns_msgs = list(body.messages or []) + [{"role": "user", "content": current_user_query[:200]}]
            followups = select_followup_prompts(
                "", prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=TOO_LONG_QUERY_MESSAGE, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": TOO_LONG_QUERY_MESSAGE})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": None,
                "followups": followups,
                "sources": [],
                "rewritten_query": current_user_query[:200],
                "is_refusal": True,
                "is_greeting": False,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})
            return

        # 0c. Chốt chặn Prompt Injection / Jailbreak bằng REFUSAL_MESSAGE (is_refusal=True, contact=None)
        if is_prompt_injection(current_user_query):
            turns_msgs = list(body.messages or []) + [{"role": "user", "content": current_user_query}]
            followups = select_followup_prompts(
                "", prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=REFUSAL_MESSAGE, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": REFUSAL_MESSAGE})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": None,
                "followups": followups,
                "sources": [],
                "rewritten_query": current_user_query,
                "is_refusal": True,
                "is_greeting": False,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})
            return

        if not current_user_query or not re.search(r"[0-9a-zA-ZÀ-ỹ]", current_user_query):
            reply = CLARIFY_EMPTY_QUERY_MESSAGE
            turns_msgs = list(body.messages or []) + [{"role": "user", "content": current_user_query or body.query}]
            followups = select_followup_prompts(
                current_user_query, prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=reply, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": reply})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": None,
                "followups": followups,
                "sources": [],
                "rewritten_query": current_user_query,
                "is_refusal": True,
                "is_greeting": True,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})
            return

        social_reply = check_social_or_command_reply(current_user_query)
        if social_reply or is_greeting(current_user_query):
            if social_reply:
                greeting_reply = social_reply
            else:
                if body.greeting_turn_count is not None:
                    idx = int(body.greeting_turn_count) % len(GREETING_REPLIES)
                else:
                    with _greeting_lock:
                        idx = _greeting_counter % len(GREETING_REPLIES)
                        _greeting_counter += 1
                greeting_reply = GREETING_REPLIES[idx]
            turns_msgs = list(body.messages or []) + [{"role": "user", "content": current_user_query}]
            followups = select_followup_prompts(
                current_user_query, prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=greeting_reply, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": greeting_reply})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": None,
                "followups": followups,
                "sources": [],
                "rewritten_query": current_user_query,
                "is_refusal": True,
                "is_greeting": True,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})
            return

        recent_chat_history = _build_filtered_history(body.messages, current_user_query)
        canonical_query = normalize_query_intent(current_user_query)
        ensure_kb_synced_and_fresh_cache()

        canonical_cache_key = _strip_accents(canonical_query)
        with _cache_lock:
            canonical_cached = _ANSWER_CACHE.get(canonical_cache_key) if canonical_cache_key else None
            if canonical_cached and (time.time() - float(canonical_cached.get("timestamp", 0))) > ANSWER_CACHE_TTL:
                _ANSWER_CACHE.pop(canonical_cache_key, None)
                canonical_cached = None

        if canonical_cached and canonical_cached.get("answer"):
            rewritten_query = canonical_query
        else:
            rewritten_query = rewrite_conversational_query(canonical_query, recent_chat_history)

        turns_msgs = list(body.messages or []) + [{"role": "user", "content": current_user_query}]

        # Nhánh 2: Hỏi thông tin phòng ban trực tiếp
        dept_reply = check_department_inquiry(rewritten_query)
        if dept_reply:
            followups = select_followup_prompts(
                rewritten_query, prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=dept_reply, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": dept_reply})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": None,
                "followups": followups,
                "sources": [],
                "rewritten_query": rewritten_query,
                "is_refusal": False,
                "is_greeting": False,
                "is_dept_inquiry": True,
            })
            yield _sse_event({"type": "done"})
            return

        # Nhánh 3: Kiểm tra ANSWER_CACHE (TTL 1800s) -> RAG Hybrid
        cache_key = _strip_accents(rewritten_query)
        with _cache_lock:
            cached_entry = _ANSWER_CACHE.get(cache_key) if cache_key else None
            if cached_entry and (time.time() - float(cached_entry.get("timestamp", 0))) > ANSWER_CACHE_TTL:
                _ANSWER_CACHE.pop(cache_key, None)
                cached_entry = None
            if cached_entry and cached_entry.get("answer") and is_refusal_answer(cached_entry.get("answer")):
                _ANSWER_CACHE.pop(cache_key, None)
                cached_entry = None

        if cached_entry and cached_entry.get("answer"):
            cached_answer = cached_entry["answer"]
            cached_sources = cached_entry.get("sources") or []
            cached_contact = cached_entry.get("contact") or get_contact_footer_data(
                rewritten_query, retrieved_docs=cached_sources or None, is_refusal=False
            )
            followups = select_followup_prompts(
                rewritten_query,
                prompts_cfg,
                messages=turns_msgs,
                sources=cached_sources,
                assistant_reply=cached_answer,
                asked_queries=body.asked_queries,
            )
            yield _sse_event({"type": "chunk", "content": cached_answer})
            yield _sse_event({
                "type": "meta",
                "verified": True,
                "elapsed_time": 0.05,
                "cache_hit": True,
                "contact": cached_contact,
                "followups": followups,
                "sources": cached_sources,
                "rewritten_query": rewritten_query,
                "is_refusal": False,
                "is_greeting": False,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})
            return

        # Thực thi Live Hybrid RAG + Streaming
        start_time = time.time()
        try:
            chain = get_cached_rag_chain()
            docs = chain.filter_documents(rewritten_query, k=6)
            if not docs:
                contact = None
                followups = select_followup_prompts(
                    rewritten_query,
                    prompts_cfg,
                    messages=turns_msgs,
                    sources=[],
                    assistant_reply=REFUSAL_MESSAGE,
                    asked_queries=body.asked_queries,
                )
                yield _sse_event({"type": "chunk", "content": REFUSAL_MESSAGE})
                yield _sse_event({
                    "type": "meta",
                    "verified": False,
                    "elapsed_time": None,
                    "cache_hit": False,
                    "contact": contact,
                    "followups": followups,
                    "sources": [],
                    "rewritten_query": rewritten_query,
                    "is_refusal": True,
                    "is_greeting": False,
                    "is_dept_inquiry": False,
                })
                yield _sse_event({"type": "done"})
                return

            formatted_prompt, sources_to_save = _build_rag_prompt_and_sources(rewritten_query, docs, chain)
            streamed_chunks: list[str] = []
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
                        streamed_chunks.append(chunk_text)
                        yield _sse_event({"type": "chunk", "content": chunk_text})

                if not yielded_any:
                    resp_obj = chain.llm.invoke(formatted_prompt)
                    fallback_text = getattr(resp_obj, "content", str(resp_obj))
                    if fallback_text and str(fallback_text).strip():
                        text_str = str(fallback_text)
                        streamed_chunks.append(text_str)
                        yield _sse_event({"type": "chunk", "content": text_str})
            except Exception as stream_err:
                if not yielded_any:
                    raise stream_err
                err_str = str(stream_err)
                notice = f"\n\n{RATE_LIMIT_MESSAGE}" if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper()) else f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                streamed_chunks.append(notice)
                yield _sse_event({"type": "chunk", "content": notice})

            full_answer = sanitize_no_markdown_tables("".join(streamed_chunks).strip())
            elapsed_time = round(time.time() - start_time, 2)
            is_interrupted = "phản hồi bị gián đoạn giữa chừng" in full_answer.lower()

            if is_interrupted:
                contact = None
                followups = select_followup_prompts(
                    rewritten_query, prompts_cfg, messages=turns_msgs, sources=sources_to_save, assistant_reply=full_answer, asked_queries=body.asked_queries
                )
                yield _sse_event({
                    "type": "meta",
                    "verified": False,
                    "elapsed_time": None,
                    "cache_hit": False,
                    "contact": contact,
                    "followups": followups,
                    "sources": [],
                    "rewritten_query": rewritten_query,
                    "is_refusal": True,
                    "is_greeting": False,
                    "is_dept_inquiry": False,
                })
            elif is_refusal_answer(full_answer) or not full_answer:
                final_text = full_answer or REFUSAL_MESSAGE
                if not full_answer:
                    yield _sse_event({"type": "chunk", "content": final_text})
                contact = None
                followups = select_followup_prompts(
                    rewritten_query, prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=final_text, asked_queries=body.asked_queries
                )
                yield _sse_event({
                    "type": "meta",
                    "verified": False,
                    "elapsed_time": None,
                    "cache_hit": False,
                    "contact": contact,
                    "followups": followups,
                    "sources": [],
                    "rewritten_query": rewritten_query,
                    "is_refusal": True,
                    "is_greeting": False,
                    "is_dept_inquiry": False,
                })
            else:
                contact = get_contact_footer_data(rewritten_query, retrieved_docs=docs, is_refusal=False)
                followups = select_followup_prompts(
                    rewritten_query,
                    prompts_cfg,
                    messages=turns_msgs,
                    sources=sources_to_save,
                    assistant_reply=full_answer,
                    asked_queries=body.asked_queries,
                )
                if cache_key:
                    record = {
                        "answer": full_answer,
                        "contact": contact,
                        "sources": sources_to_save,
                        "timestamp": time.time(),
                    }
                    with _cache_lock:
                        _ANSWER_CACHE[cache_key] = record
                        if rewritten_query == canonical_query and canonical_cache_key and canonical_cache_key != cache_key:
                            _ANSWER_CACHE[canonical_cache_key] = record
                yield _sse_event({
                    "type": "meta",
                    "verified": True,
                    "elapsed_time": elapsed_time,
                    "cache_hit": False,
                    "contact": contact,
                    "followups": followups,
                    "sources": sources_to_save,
                    "rewritten_query": rewritten_query,
                    "is_refusal": False,
                    "is_greeting": False,
                    "is_dept_inquiry": False,
                })
            yield _sse_event({"type": "done"})

        except Exception as err:
            print(f"[API STREAM ERROR] {type(err).__name__}")
            reply = sanitize_client_error_message(err, rate_limit_msg=RATE_LIMIT_MESSAGE)
            contact = None
            followups = select_followup_prompts(
                rewritten_query, prompts_cfg, messages=turns_msgs, sources=[], assistant_reply=reply, asked_queries=body.asked_queries
            )
            yield _sse_event({"type": "chunk", "content": reply})
            yield _sse_event({
                "type": "meta",
                "verified": False,
                "elapsed_time": None,
                "cache_hit": False,
                "contact": contact,
                "followups": followups,
                "sources": [],
                "rewritten_query": rewritten_query,
                "is_refusal": True,
                "is_greeting": False,
                "is_dept_inquiry": False,
            })
            yield _sse_event({"type": "done"})

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/assets/logo_vlute.png")
def serve_logo():
    if LOGO_PATH.exists():
        return FileResponse(LOGO_PATH, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return JSONResponse({"detail": "logo_vlute.png not found"}, status_code=404)


@app.get("/assets/lucas_avatar.png")
def serve_avatar():
    if AVATAR_PATH.exists():
        return FileResponse(AVATAR_PATH, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return JSONResponse({"detail": "lucas_avatar.png not found"}, status_code=404)


if FRONTEND_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True), name="frontend")
