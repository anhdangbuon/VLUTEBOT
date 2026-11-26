import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import re
import json
import time
import shutil
import glob
import unicodedata
from pathlib import Path
from datetime import datetime
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
import torch
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

BASE_DIR = Path(__file__).parent
DATA_PATH = str(BASE_DIR / "data")
DB_PATH = str(BASE_DIR / "chroma_db")
DEPT_FILE = BASE_DIR / "departments.json"
DEPARTMENTS_PATH = str(DEPT_FILE)

# Tự động bật chế độ Offline cho Hugging Face nếu máy đã có sẵn cache mô hình vietnamese-bi-encoder
# (Nếu triển khai sang máy chủ/máy mới chưa có cache, hệ thống vẫn tự động tải model ở lần chạy đầu tiên)
_HF_MODEL_CACHE_DIR = os.path.join(
    os.getenv("HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface")),
    "hub",
    "models--bkai-foundation-models--vietnamese-bi-encoder",
)
if os.path.isdir(_HF_MODEL_CACHE_DIR):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Danh sách các văn bản nghị quyết hành chính không liên quan đến sinh viên (cần loại bỏ)
EXCLUDED_FILES = [
    "nghi_quyet_71.pdf",
    "nghi_quyet_72.pdf",
    "nghi_quyet_153.pdf"
]

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}

_DEPT_CONTENT_CUES = {
    "dao_tao": {
        "strong": (
            "phòng đào tạo", "phong_dao_tao", "daotao@vlute",
            "phòng quản lý đào tạo", "phong_quan_ly_dao_tao",
            "đề cương học phần", "de_cuong_hoc_phan", "đề cương", "de_cuong",
            "bm-dt", "bm_dt", "chương trình đào tạo", "chuong_trinh_dao_tao",
            "mã học phần", "ma_hoc_phan", "số tín chỉ", "so_tin_chi",
            "học phần tiên quyết", "hoc_phan_tien_quyet",
            "chuẩn đầu ra", "chuan_dau_ra", "giảng viên phụ trách", "giang_vien_phu_trach",
            "phương pháp kiểm tra đánh giá", "phuong_phap_kiem_tra_danh_gia",
        ),
        "regular": (
            "học phần", "hoc_phan", "tín chỉ", "tin_chi",
            "giảng viên", "giang_vien", "tốt nghiệp", "tot_nghiep",
            "học vụ", "hoc_vu", "đăng ký môn", "dang_ky_mon",
            "học kỳ hè", "hoc_ky_he", "khóa luận", "khoa_luan",
            "xét tốt nghiệp", "xet_tot_nghiep", "cảnh báo học vụ", "canh_bao_hoc_vu",
            "tiên quyết", "tien_quyet", "học trước", "hoc_truoc",
            "song hành", "song_hanh", "lý thuyết", "ly_thuyet", "thực hành", "thuc_hanh",
        ),
    },
    "ctsv": {
        "strong": (
            "phòng công tác sinh viên", "phong_cong_tac_sinh_vien", "ctsv@vlute",
            "học bổng khuyến khích", "hoc_bong_khuyen_khich",
            "điểm rèn luyện", "diem_ren_luyen", "công tác xã hội", "cong_tac_xa_hoi",
            "kỷ luật sinh viên", "ky_luat_sinh_vien", "quy tắc ứng xử", "quy_tac_ung_xu",
        ),
        "regular": (
            "học bổng", "hoc_bong", "rèn luyện", "ren_luyen",
            "ctxh", "kỷ luật", "ky_luat", "khen thưởng", "khen_thuong",
            "ứng xử", "ung_xu", "ban cán sự", "ban_can_su", "cố vấn học tập", "co_van_hoc_tap",
        ),
    },
    "khtc": {
        "strong": (
            "phòng kế hoạch - tài chính", "phòng kế hoạch tài chính",
            "phong_ke_hoach_tai_chinh", "khtc@vlute",
            "miễn, giảm học phí", "miễn giảm học phí", "mien_giam_hoc_phi",
            "hoàn trả học phí", "hoan_tra_hoc_phi",
        ),
        "regular": (
            "học phí", "hoc_phi", "hoàn trả", "hoan_tra", "miễn giảm", "mien_giam",
            "biên lai", "bien_lai", "hóa đơn", "hoa_don",
            "thu học phí", "thu_hoc_phi", "tài chính", "tai_chinh",
        ),
    },
    "cntt": {
        "strong": (
            "trung tâm công nghệ thông tin", "trung_tam_cong_nghe_thong_tin",
            "ttcntt@vlute", "an toàn thông tin", "an_toan_thong_tin",
            "an ninh mạng", "an_ninh_mang",
        ),
        "regular": (
            "mật khẩu", "mat_khau", "tài khoản", "tai_khoan",
            "hệ thống mạng", "he_thong_mang", "st.vlute.edu.vn", "elearning",
            "phần mềm", "phan_mem", "cntt",
        ),
    },
}


def load_departments(json_path: str = DEPARTMENTS_PATH) -> dict:
    """Đọc tệp cấu hình phòng ban departments.json."""
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _strip_accents(text: str) -> str:
    """Chuẩn hóa tiếng Việt không dấu dạng slug chữ thường để so khớp từ khóa ổn định."""
    if not text:
        return ""
    s = str(text).lower().replace("đ", "d")
    s = "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def match_department_for_file(filename: str, departments: dict, content_preview: str = ""):
    """
    Chấm điểm toàn diện trên cả tên file, tiêu đề và nội dung chính của tài liệu (content_preview)
    để tự động định tuyến phòng ban phụ trách cho bất kỳ tài liệu .pdf, .docx, .txt mới nào:
    - Nhóm từ khóa học thuật (đề cương, học phần, tín chỉ, giảng viên, chuẩn đầu ra, chương trình đào tạo...)
      được chấm trọng số cao cho Phòng Đào tạo (dao_tao) để không bị từ khóa tên môn học (như phần mềm, CNTT, mạng)
      kéo nhầm sang Trung tâm CNTT (cntt).
    """
    if not departments:
        departments = load_departments(DEPARTMENTS_PATH)

    fname_norm = unicodedata.normalize("NFC", str(filename or "")).lower().replace("cong_tac_xa_hoi", "ctxh")
    fname_slug = _strip_accents(fname_norm)
    preview_raw = unicodedata.normalize("NFC", (content_preview or "")[:2500]).lower()
    preview_slug = _strip_accents(preview_raw) if preview_raw.strip() else ""

    # Tín hiệu học thuật đặc trưng của Đề cương học phần / Chương trình đào tạo
    is_explicit_ctsv = "công tác sinh viên" in fname_norm or "cong_tac_sinh_vien" in fname_slug
    academic_strong_hits = 0 if is_explicit_ctsv else sum(
        1 for cue in (
            "đề cương", "de_cuong", "bm-dt", "bm_dt", "mã học phần", "ma_hoc_phan",
            "số tín chỉ", "so_tin_chi", "chuẩn đầu ra", "chuan_dau_ra",
            "học phần tiên quyết", "hoc_phan_tien_quyet", "chương trình đào tạo", "chuong_trinh_dao_tao",
            "giảng viên phụ trách", "giang_vien_phu_trach",
        )
        if (cue in fname_norm or cue in fname_slug or (preview_raw and (cue in preview_raw or cue in preview_slug)))
    )

    best_key = None
    best_score = 0
    generic_it_patterns = {"cntt", "phan_mem", "mang"}

    for dept_key, dept_info in departments.items():
        score = 0
        cues = _DEPT_CONTENT_CUES.get(dept_key, {})

        # 1. Chấm điểm trên tên file / tiêu đề
        for cue in cues.get("strong", ()):
            if cue in fname_norm or cue in fname_slug:
                score += 6
        for cue in cues.get("regular", ()):
            if cue in fname_norm or cue in fname_slug:
                score += 2

        for pat in dept_info.get("patterns", []):
            pat_str = str(pat).lower().strip()
            if not pat_str:
                continue
            if pat_str in fname_norm or pat_str in fname_slug:
                # Từ khóa IT chung (phan_mem, cntt, mang) trong tên môn học chỉ cộng nhẹ nếu có tín hiệu học thuật
                if dept_key == "cntt" and pat_str in generic_it_patterns and academic_strong_hits > 0:
                    score += 1
                else:
                    score += 5

        # 2. Chấm điểm trên nội dung văn bản (content_preview)
        if preview_raw:
            for cue in cues.get("strong", ()):
                if cue in preview_raw or cue in preview_slug:
                    score += 4
            for cue in cues.get("regular", ()):
                if cue in preview_raw or cue in preview_slug:
                    score += 2
            for pat in dept_info.get("patterns", []):
                pat_str = str(pat).lower().strip()
                if not pat_str:
                    continue
                if pat_str == "mang":
                    if "an_ninh_mang" in preview_slug or "he_thong_mang" in preview_slug:
                        score += 2
                elif pat_str in preview_slug or pat_str.replace("_", " ") in preview_raw:
                    if dept_key == "cntt" and pat_str in generic_it_patterns and academic_strong_hits > 0:
                        score += 0
                    else:
                        score += 1

        if dept_key == "dao_tao" and academic_strong_hits >= 2:
            score += academic_strong_hits * 4
        if dept_key == "ctsv" and is_explicit_ctsv:
            score += 12

        if score > best_score:
            best_score = score
            best_key = dept_key

    if best_key and best_score > 0:
        return best_key, departments[best_key]

    default_key = "ctsv"
    default_info = departments.get(default_key, {
        "name": "Phòng Công tác Sinh viên (VLUTE)",
        "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
        "phone": "(0270) 3862 436",
        "email": "ctsv@vlute.edu.vn"
    })
    return default_key, default_info


def _extract_syllabus_info(text: str, filename: str) -> tuple[str, str, str]:
    """
    Nhận diện biểu mẫu đào tạo / đề cương học phần (BM-DT hoặc ĐỀ CƯƠNG HỌC PHẦN).
    Trả về (course_name, course_code, chunk_prefix). Nếu không phải đề cương, trả về ("", "", "").
    """
    norm_text = unicodedata.normalize("NFC", text or "")
    norm_fname = unicodedata.normalize("NFC", filename or "")
    fname_lower = norm_fname.lower()
    fname_slug = _strip_accents(norm_fname)
    head_lower = norm_text[:2500].lower()
    head_slug = _strip_accents(norm_text[:2500]).replace("_", " ")

    is_syllabus = (
        "bm-dt" in fname_lower
        or "bm_dt" in fname_slug
        or "de_cuong" in fname_slug
        or "đề cương học phần" in head_lower
        or "de cuong hoc phan" in head_slug
    )
    if not is_syllabus:
        return "", "", ""

    course_name = ""
    # 1. Tìm theo mục "Tiếng Việt: <Tên học phần>"
    m_vi = re.search(r"Tiếng\s+Việt\s*:\s*([^\n|]+)", norm_text[:2500], re.IGNORECASE)
    if m_vi:
        candidate = re.sub(r"\s+", " ", m_vi.group(1)).strip(" .-:")
        if len(candidate) >= 3:
            course_name = candidate

    # 2. Tìm theo mục "1. TÊN HỌC PHẦN: <Tên học phần>"
    if not course_name:
        m_ten = re.search(r"TÊN\s+HỌC\s+PHẦN\s*:\s*([^\n|]+)", norm_text[:2500], re.IGNORECASE)
        if m_ten:
            candidate = re.sub(r"\s+", " ", m_ten.group(1)).strip(" .-:")
            if len(candidate) >= 3 and not re.match(r"^tiếng\s+việt\b", candidate, re.IGNORECASE):
                course_name = candidate

    # 3. Tìm dòng ngay dưới tiêu đề "ĐỀ CƯƠNG HỌC PHẦN"
    if not course_name:
        m_after = re.search(r"ĐỀ\s+CƯƠNG\s+HỌC\s+PHẦN\s*\n+\s*([^\n|]+)", norm_text[:2500], re.IGNORECASE)
        if m_after:
            candidate = re.sub(r"\s+", " ", m_after.group(1)).strip(" .-:")
            if len(candidate) >= 3 and not re.search(r"mã\s+học\s+phần", candidate, re.IGNORECASE):
                course_name = candidate

    # 4. Tìm Mã học phần
    course_code = ""
    m_code = re.search(
        r"(?:MÃ\s+HỌC\s+PHẦN|MÃ\s+HP)\s*:\s*([A-Z0-9_-]{3,20})",
        norm_text[:2500],
        re.IGNORECASE,
    )
    if m_code:
        course_code = m_code.group(1).strip().upper()
    if not course_code:
        m_fcode = re.search(r"\b([A-Z]{2,4}\d{3,6})\b", norm_fname)
        if m_fcode:
            course_code = m_fcode.group(1).upper()

    if not course_name:
        base_clean = os.path.splitext(norm_fname)[0]
        base_clean = re.sub(r"^BM[-_]?DT[-_]?\d+[-_]?", "", base_clean, flags=re.IGNORECASE)
        if course_code:
            base_clean = re.sub(rf"^{re.escape(course_code)}[-_]?", "", base_clean, flags=re.IGNORECASE)
        base_clean = re.sub(r"\(\d{4}\)", "", base_clean).replace("_", " ").strip()
        course_name = base_clean.upper() or "HỌC PHẦN ĐÀO TẠO"

    if course_code:
        prefix = f"[Đề cương học phần: {course_name} - Mã HP: {course_code}]"
    else:
        prefix = f"[Đề cương học phần: {course_name}]"
    return course_name, course_code, prefix


def extract_doc_title(text: str, filename: str) -> str:
    """
    Bóc tách tiêu đề văn bản tổng quát từ phần đầu nội dung file (.pdf, .docx, .txt).
    Hỗ trợ mọi loại quy chế, quy định, thông báo, đề cương học phần, chương trình đào tạo...
    Nếu không tìm thấy trong nội dung, chuẩn hóa tên file (bỏ phần mở rộng, thay '_' bằng khoảng trắng, viết hoa).
    """
    text = unicodedata.normalize("NFC", text or "")
    course_name, course_code, _ = _extract_syllabus_info(text, filename)
    if course_name:
        if course_code:
            return f"Đề cương học phần: {course_name} - Mã HP: {course_code}"
        return f"Đề cương học phần: {course_name}"

    m_block = re.search(
        r"(?:Ban hành|V/v ban hành|Về việc ban hành|V/v)\s+((?:Quy định|Quy chế|Quy trình|Quy tắc|Thông báo|Hướng dẫn|Kế hoạch|Chương trình|Đề án)(?:\s+[^\n]+){1,3})",
        text,
        re.IGNORECASE
    )
    if m_block:
        title_str = re.sub(r"\s+", " ", m_block.group(1)).strip()
        title_str = re.split(r"\s+(?:HIỆU TRƯỞNG|Căn cứ|Điều\s+1\b|Chương\s+I\b|1\.\s+)", title_str, flags=re.IGNORECASE)[0].strip()
        if len(title_str) > 10:
            return title_str

    m_qt = re.search(r"(QUY TRÌNH\s+HOÀN TRẢ[^\n]*(?:\n[^\n]+)?)", text, re.IGNORECASE)
    if m_qt:
        return re.sub(r"\s+", " ", m_qt.group(1)).strip()

    bare_headers = {
        "QUYẾT ĐỊNH", "QUY ĐỊNH", "QUY CHẾ", "QUY TRÌNH", "QUY TẮC",
        "THÔNG BÁO", "HƯỚNG DẪN", "KẾ HOẠCH", "ĐỀ CƯƠNG HỌC PHẦN",
        "ĐỀ CƯƠNG", "CHƯƠNG TRÌNH ĐÀO TẠO", "CHƯƠNG TRÌNH", "BIỂU MẪU",
    }
    m = re.search(
        r"((?:QUY ĐỊNH|QUY CHẾ|QUY TRÌNH|QUY TẮC|QUYẾT ĐỊNH|THÔNG BÁO|HƯỚNG DẪN|KẾ HOẠCH|ĐỀ CƯƠNG HỌC PHẦN|ĐỀ CƯƠNG|CHƯƠNG TRÌNH ĐÀO TẠO)[^\n]*)",
        text,
        re.IGNORECASE
    )
    if m:
        candidate = re.sub(r"\s+", " ", m.group(1)).strip()
        if candidate.upper() not in bare_headers:
            return candidate
        # Nếu dòng tiêu đề chỉ có từ khóa loại văn bản (vd: "THÔNG BÁO" hoặc "ĐỀ CƯƠNG HỌC PHẦN"), ghép với dòng kế tiếp
        after_text = text[m.end():].lstrip()
        next_line = after_text.splitlines()[0].strip() if after_text else ""
        next_line = re.sub(r"\s+", " ", next_line)
        if len(next_line) >= 4 and not re.search(r"^(?:Số|Căn cứ|HIỆU TRƯỞNG)\b", next_line, re.IGNORECASE):
            return f"{candidate}: {next_line}"

    return os.path.splitext(filename)[0].replace("_", " ").upper()


def extract_doc_year(text: str, filepath: str) -> str:
    """
    Bóc tách năm ban hành từ phần đầu nội dung tài liệu.
    Nếu không thấy, lấy năm chỉnh sửa file từ hệ thống (os.path.getmtime).
    """
    text = unicodedata.normalize("NFC", text or "")
    flat = re.sub(r"\s+", " ", text)
    m = re.search(
        r"(?:ngày\s*\d+\s*tháng\s*\d+\s*năm\s*|ban\s+hành\s+năm\s*|hiệu\s+lực\D{0,10}|năm\s+)(\d{4})",
        flat,
        re.IGNORECASE
    )
    if m:
        return str(m.group(1))

    m2 = re.search(r"(?:QĐ|QT|TB|BM-DT)[^\n]{0,30}(\d{4})", flat, re.IGNORECASE)
    if m2:
        return str(m2.group(1))

    m_fname = re.search(r"\((\d{4})\)", os.path.basename(filepath))
    if m_fname:
        return str(m_fname.group(1))

    return str(datetime.fromtimestamp(os.path.getmtime(filepath)).year)


def extract_doc_code(text: str) -> str:
    """
    Bóc tách số hiệu / mã số văn bản từ phần đầu nội dung tài liệu.
    (Ví dụ: 201/QĐ-ĐHSPKTVL, QT-SV-04, 888/TB-ĐHSPKTVL, Mã HP: IT1216...)
    """
    text = unicodedata.normalize("NFC", text or "")
    flat = re.sub(r"\s+", " ", text)

    m_hp = re.search(r"(?:MÃ\s+HỌC\s+PHẦN|MÃ\s+HP)\s*:\s*([A-Z0-9_-]{3,20})", flat, re.IGNORECASE)
    if m_hp:
        return m_hp.group(1).strip().upper()

    m = re.search(
        r"((?:Số|Só|Mã số)?:?\s*(?:[\d\w\-\/]+\s*\/?\s*(?:QĐ|QD|QT|HD|KH|TB)|(?:QĐ|QT|HD|KH|TB)[\d\w\-\/]+)[^\n\s]*)",
        flat,
        re.IGNORECASE
    )
    if m:
        code = m.group(1).strip()
        code = re.sub(r"^(?:Số|Só|Mã số)\s*:?\s*", "", code, flags=re.IGNORECASE).strip()
        return re.sub(r"\s+", "", code).strip(",.;:")

    m2 = re.search(r"((?:Số|Mã số)?:?\s*[\d\w\-\/]+(?:QĐ|QT|HD|KH|TB)[^\n\s]*)", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip().strip(",.;:")

    return "N/A"


def clean_text(text: str) -> str:
    """
    Làm sạch sâu văn bản PDF/Word:
    - Chuẩn hóa Unicode NFC (tránh lỗi dấu tổ hợp NFD trong file Word)
    - Loại bỏ tiêu đề bảng lặp, ký tự rác, dấu nối từ vô lý
    - Chuẩn hóa khoảng trắng và dấu câu tiếng Việt
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFC", text)

    # 1. Loại bỏ các chuỗi rác bảng biểu thường gặp ở đầu trang PDF hành chính
    text = re.sub(r"Lần\s+soát\s+xét\s+Trang\s+Nội\s+dung\s+thay\s+đổi\s+Phê\s+duyệt", "", text, flags=re.IGNORECASE)
    text = re.sub(r"VA\s+PGS\.TS\.\s+Lê\s+Hồng\s+Hùng\s+Ngày", "", text, flags=re.IGNORECASE)

    # 2. Xử lý từ bị ngắt đôi do xuống dòng có dấu gạch ngang (ví dụ: hoàn -\n trả -> hoàn trả)
    text = re.sub(r"(\w+)\s*-\s*\n\s*(\w+)", r"\1\2", text)

    # 3. Chuẩn hóa dấu đầu dòng rời rạc (ví dụ: -\n Sinh viên -> - Sinh viên)
    text = re.sub(r"-\s*\n\s*", "- ", text)

    # 4. Chuẩn hóa khoảng trắng ngang
    text = re.sub(r"[ \t]+", " ", text)

    # 5. Loại bỏ nhiều dòng trống liên tiếp
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


_VIETNAMESE_OCR_READER = None
_OCR_INIT_FAILED = False
MAX_OCR_PAGES_PER_FILE = 25


def _is_file_ready_for_reading(filepath: str, wait_sec: float = 0.3) -> bool:
    """
    Kiểm tra tệp đã hoàn tất sao chép/ghi xuống đĩa và không bị khóa bởi tiến trình khác:
    - Kích thước tệp > 0 và không thay đổi sau wait_sec (0.3s).
    - Mở thử ở chế độ đọc nhị phân ('rb') thành công.
    """
    try:
        if not os.path.isfile(filepath):
            return False
        size_1 = os.path.getsize(filepath)
        if size_1 <= 0:
            return False
        time.sleep(wait_sec)
        if not os.path.isfile(filepath):
            return False
        size_2 = os.path.getsize(filepath)
        if size_1 != size_2 or size_2 <= 0:
            print(
                f"[WARN] Tệp '{os.path.basename(filepath)}' đang được sao chép dở "
                f"({size_1} -> {size_2} bytes), tạm bỏ qua ở lượt này và tự nạp ở lượt kế tiếp."
            )
            return False
        with open(filepath, "rb") as f:
            _ = f.read(16)
        return True
    except (PermissionError, OSError) as lock_err:
        print(
            f"[WARN] Tệp '{os.path.basename(filepath)}' đang bị khóa hoặc đang ghi dở ({lock_err}), "
            "tạm bỏ qua ở lượt này và tự nạp ở lượt kế tiếp."
        )
        return False


def _warn_duplicate_doc_titles(title_to_files: dict[str, list[str]]) -> None:
    """In cảnh báo nếu phát hiện từ 2 tệp khác nhau trở lên trong data/ có cùng tiêu đề chính thức (doc_title)."""
    for norm_title, entries in title_to_files.items():
        if not norm_title:
            continue
        unique_files = []
        display_title = norm_title
        for fname, raw_title in entries:
            if raw_title:
                display_title = raw_title
            if fname not in unique_files:
                unique_files.append(fname)
        if len(unique_files) >= 2:
            print(
                f"[WARN] Phát hiện {len(unique_files)} tệp có tiêu đề tương tự ('{display_title}'): "
                f"{', '.join(unique_files)}. Quản trị viên vui lòng kiểm tra và gỡ bỏ bản cũ nếu cần."
            )


def _get_vietnamese_ocr_reader():
    """
    Khởi tạo lazy singleton EasyOCR Reader hỗ trợ tiếng Việt và tiếng Anh (['vi', 'en'], gpu=False).
    Bọc trong try...except ImportError/Exception để nếu môi trường thiếu thư viện vẫn bỏ qua an toàn.
    """
    global _VIETNAMESE_OCR_READER, _OCR_INIT_FAILED
    if _VIETNAMESE_OCR_READER is not None:
        return _VIETNAMESE_OCR_READER
    if _OCR_INIT_FAILED:
        return None
    try:
        import easyocr
        _VIETNAMESE_OCR_READER = easyocr.Reader(["vi", "en"], gpu=False, verbose=False)
        return _VIETNAMESE_OCR_READER
    except ImportError as imp_err:
        _OCR_INIT_FAILED = True
        print(f"⚠️ [OCR] Thư viện easyocr chưa được cài đặt, bỏ qua nhận diện ảnh scan: {imp_err}")
        return None
    except Exception as ocr_err:
        _OCR_INIT_FAILED = True
        print(f"⚠️ [OCR] Không thể khởi tạo EasyOCR Reader, bỏ qua nhận diện ảnh scan: {ocr_err}")
        return None


def _ocr_pdf_page(page) -> str:
    """
    Kết xuất trang PDF sang ảnh độ phân giải dpi=200 bằng PyMuPDF (fitz),
    nhận diện chữ tiếng Việt bằng EasyOCR (detail=0, paragraph=True) và làm sạch qua clean_text().
    """
    reader = _get_vietnamese_ocr_reader()
    if reader is None:
        return ""
    try:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        ocr_segments = reader.readtext(img_bytes, detail=0, paragraph=True)
        if not ocr_segments:
            return ""
        cleaned_lines = []
        for seg in ocr_segments:
            line_str = str(seg or "").strip()
            if not line_str:
                continue
            if re.search(r"(HUO TRU|DAI SU|UPH VIN)", line_str, re.IGNORECASE):
                continue
            cleaned_lines.append(line_str)
        return clean_text("\n\n".join(cleaned_lines))
    except Exception as err:
        print(f"⚠️ [OCR] Lỗi khi nhận diện trang PDF: {err}")
        return ""


def extract_clean_text_from_pdf(pdf_path: str):
    """
    Trích xuất văn bản và metadata từ file PDF bằng PyMuPDF (fitz) kết hợp Fallback OCR (EasyOCR):
    - Đọc 2 trang đầu để bóc tách tự động: title, year, doc_code.
    - Với mỗi trang, vẫn trích xuất văn bản bình thường trước (page.get_text("text")).
    - Chỉ khi len(page_clean_text) <= 25 (trang trắng hoặc trang ảnh scan), tự động gọi _ocr_pdf_page(page)
      để lấy nội dung tiếng Việt (in log [OCR] Đang nhận diện trang X của <filename>...).
    - Nếu first_two_pages_text ban đầu rỗng/ngắn (<= 25 ký tự) do trang 1–2 là bản scan,
      tự động cập nhật lại doc_title, doc_year, doc_code từ văn bản đã OCR của 2 trang đầu.
    """
    doc = fitz.open(pdf_path)
    filename = os.path.basename(pdf_path)

    # Bóc tách metadata tự động từ 2 trang đầu của file PDF
    first_two_pages_text = clean_text(
        "\n".join(doc[i].get_text("text") for i in range(min(2, len(doc))))
    )
    needs_meta_from_ocr = len(first_two_pages_text) <= 25
    doc_title = extract_doc_title(first_two_pages_text, filename)
    doc_year = extract_doc_year(first_two_pages_text, pdf_path)
    doc_code = extract_doc_code(first_two_pages_text)

    full_text = []
    ocr_first_two_pages = []
    ocr_pages_count = 0
    ocr_limit_warned = False
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")

        cleaned_lines = []
        for line in text.split("\n"):
            line_str = line.strip()
            if re.search(r"(HUO TRU|DAI SU|UPH VIN)", line_str, re.IGNORECASE):
                continue
            cleaned_lines.append(line_str)

        page_clean_text = "\n".join(cleaned_lines)
        page_clean_text = clean_text(page_clean_text)

        if len(page_clean_text) <= 25:
            if ocr_pages_count < MAX_OCR_PAGES_PER_FILE:
                ocr_pages_count += 1
                print(f"[OCR] Đang nhận diện trang {page_num + 1} của {filename} ({ocr_pages_count}/{MAX_OCR_PAGES_PER_FILE})...")
                page_clean_text = _ocr_pdf_page(page)
            elif not ocr_limit_warned:
                print(
                    f"[WARN] Tệp '{filename}' vượt ngưỡng tối đa MAX_OCR_PAGES_PER_FILE={MAX_OCR_PAGES_PER_FILE} trang OCR/tệp trên CPU. "
                    "Tạm dừng OCR các trang còn lại để chống tràn RAM (OOM)."
                )
                ocr_limit_warned = True

        if page_num < 2 and len(page_clean_text) > 25:
            ocr_first_two_pages.append(page_clean_text)

        if len(page_clean_text) > 25:
            full_text.append({
                "page": page_num + 1,
                "text": page_clean_text,
                "title": doc_title,
                "year": str(doc_year),
                "doc_code": doc_code
            })

    doc.close()

    if needs_meta_from_ocr and ocr_first_two_pages and full_text:
        combined_first_two = "\n".join(ocr_first_two_pages)
        doc_title = extract_doc_title(combined_first_two, filename)
        doc_year = extract_doc_year(combined_first_two, pdf_path)
        doc_code = extract_doc_code(combined_first_two)
        for item in full_text:
            item["title"] = doc_title
            item["year"] = str(doc_year)
            item["doc_code"] = doc_code

    return full_text


def _build_logical_pages(cleaned_text: str, filename: str, filepath: str, page_chars: int = 2000) -> list[dict]:
    """Tách văn bản .docx/.txt đã làm sạch thành các trang logic kèm metadata tự động."""
    if not cleaned_text or len(cleaned_text.strip()) <= 25:
        return []

    head_text = cleaned_text[:3000]
    doc_title = extract_doc_title(head_text, filename)
    doc_year = extract_doc_year(head_text, filepath)
    doc_code = extract_doc_code(head_text)

    pages = []
    current_lines = []
    current_len = 0
    for line in cleaned_text.splitlines():
        line_s = line.strip()
        if not line_s:
            if current_lines and current_lines[-1] != "":
                current_lines.append("")
            continue
        is_major_heading = bool(re.match(r"^(?:\d{1,2}\.\s+[A-ZÀ-Ỹ]|[IVX]{1,4}\.\s+[A-ZÀ-Ỹ])", line_s))
        prev_non_empty = next((x for x in reversed(current_lines) if x), "")
        prev_was_heading = bool(
            re.match(r"^(?:\d{1,2}(?:\.\d{1,2})?\.\s+[A-ZÀ-Ỹ]|[IVX]{1,4}\.\s+[A-ZÀ-Ỹ])", prev_non_empty)
            and len(prev_non_empty) <= 120
        )
        should_break = (
            current_lines
            and not prev_was_heading
            and (
                (current_len + len(line_s) + 1 > page_chars)
                or (is_major_heading and current_len >= int(page_chars * 0.65))
            )
        )
        if should_break:
            chunk_text = "\n".join(current_lines).strip()
            if len(chunk_text) > 25:
                pages.append(chunk_text)
            current_lines = [line_s]
            current_len = len(line_s)
        else:
            current_lines.append(line_s)
            current_len += len(line_s) + 1

    if current_lines:
        chunk_text = "\n".join(current_lines).strip()
        if len(chunk_text) > 25:
            pages.append(chunk_text)

    return [
        {
            "page": idx + 1,
            "text": page_text,
            "title": doc_title,
            "year": str(doc_year),
            "doc_code": doc_code,
        }
        for idx, page_text in enumerate(pages)
    ]


def _format_docx_table(table: Table, section_heading: str = "") -> str:
    """
    Chuẩn hóa bảng biểu Word (.docx) thành văn bản có cấu trúc:
    - Giải quyết cả ô gộp ngang (cùng cell._tc trên 1 hàng) và ô gộp dọc (cùng cell._tc giữa các hàng hoặc vMerge).
    - Ghép mỗi ô dữ liệu với tiêu đề cột tương ứng ở hàng đầu tiên (hoặc 2 hàng đầu nếu tiêu đề gộp cột).
    - Giữ ngữ cảnh dòng nhóm (ví dụ: A1. Chuyên cần, A2. Quá trình, A3. Cuối kỳ) và tổng hợp nhanh cột Hệ số / Số tín chỉ.
    """
    rows = list(table.rows)
    if not rows:
        return ""

    num_cols = max((len(r.cells) for r in rows), default=0)
    if num_cols == 0:
        return ""

    # Bước 1: Trích xuất lưới ô (tc_id, text) và khôi phục giá trị của các ô gộp dọc (vertical merge)
    grid: list[list[tuple[int, str]]] = []
    top_cell_by_col: dict[int, tuple[int, str]] = {}

    for row in rows:
        row_cells = list(row.cells)
        row_data: list[tuple[int, str]] = []
        for c_idx in range(num_cols):
            if c_idx >= len(row_cells):
                row_data.append((-1 - c_idx, ""))
                continue
            cell = row_cells[c_idx]
            tc = cell._tc
            tc_id = id(tc)
            txt = unicodedata.normalize("NFC", re.sub(r"\s+", " ", cell.text or "").strip())

            tcPr = tc.tcPr
            vMerge = tcPr.vMerge if tcPr is not None else None
            is_vmerge_cont = vMerge is not None and getattr(vMerge, "val", None) in (None, "continue")

            if not txt and is_vmerge_cont and c_idx in top_cell_by_col:
                tc_id, txt = top_cell_by_col[c_idx]
            elif txt:
                top_cell_by_col[c_idx] = (tc_id, txt)

            row_data.append((tc_id, txt))
        grid.append(row_data)

    # Bước 2: Nhận diện hàng tiêu đề cột (Header Row)
    row0 = grid[0]
    distinct_r0 = []
    seen_tc_r0 = set()
    for tc_id, txt in row0:
        if txt and tc_id not in seen_tc_r0:
            distinct_r0.append(txt)
            seen_tc_r0.add(tc_id)

    max_r0_len = max((len(t) for t in distinct_r0), default=0)
    is_header_table = len(grid) >= 2 and len(distinct_r0) >= 2 and max_r0_len <= 65

    if not is_header_table:
        # Bảng bố cục (ví dụ: quốc hiệu tiêu ngữ hoặc chữ ký cuối trang)
        plain_lines = []
        for row_data in grid:
            vals = []
            prev_tc = None
            for tc_id, txt in row_data:
                if tc_id == prev_tc:
                    continue
                prev_tc = tc_id
                if txt:
                    vals.append(txt)
            if vals:
                plain_lines.append(" | ".join(vals))
        return "\n".join(plain_lines)

    # Kiểm tra tiêu đề 2 tầng (Row 0 có ô gộp ngang và Row 1 có ô gộp dọc với Row 0)
    data_start_row = 1
    headers: list[str] = []
    has_r0_hmerge = any(row0[c][0] == row0[c - 1][0] for c in range(1, num_cols))
    if len(grid) >= 3 and has_r0_hmerge:
        row1 = grid[1]
        has_r1_vmerge_with_r0 = any(row1[c][0] == row0[c][0] and row0[c][1] for c in range(num_cols))
        row1_max_len = max((len(t) for _, t in row1 if t), default=0)
        if has_r1_vmerge_with_r0 and row1_max_len <= 55:
            data_start_row = 2
            for c in range(num_cols):
                h0 = re.sub(r"\s*\(\*+\)\s*$", "", row0[c][1]).strip()
                h1 = re.sub(r"\s*\(\*+\)\s*$", "", row1[c][1]).strip()
                if row1[c][0] == row0[c][0] or not h1 or h1 == h0:
                    headers.append(h0 or f"Cột {c + 1}")
                elif not h0:
                    headers.append(h1)
                else:
                    headers.append(f"{h0} ({h1})")

    if not headers:
        for c in range(num_cols):
            h0 = re.sub(r"\s*\(\*+\)\s*$", "", row0[c][1]).strip()
            headers.append(h0 or f"Cột {c + 1}")

    # Xác định xem bảng có cột Hệ số hoặc Số tín chỉ không
    coef_col_idx = next((i for i, h in enumerate(headers) if "hệ số" in h.lower()), -1)
    credit_col_idx = next((i for i, h in enumerate(headers) if "số tín chỉ" in h.lower()), -1)

    formatted_rows: list[str] = []
    current_group = ""
    coef_groups: list[tuple[int, str, str, list[str]]] = []  # (tc_id, group_name, coef_val, items)
    credit_items: list[str] = []

    for r_idx in range(data_start_row, len(grid)):
        row_data = grid[r_idx]
        # Khử trùng lặp ô gộp ngang theo tc_id (giữ chỉ số cột đầu tiên của ô gộp)
        unique_cols: list[tuple[int, int, str]] = []  # (c_idx, tc_id, txt)
        prev_tc = None
        for c_idx, (tc_id, txt) in enumerate(row_data):
            if prev_tc is not None and tc_id == prev_tc:
                continue
            prev_tc = tc_id
            if txt:
                unique_cols.append((c_idx, tc_id, txt))

        if not unique_cols:
            continue

        # Hàng tiêu đề nhóm (chỉ có cột 0 có chữ, các cột còn lại trống, ví dụ: "A1. Chuyên cần")
        if len(unique_cols) == 1 and unique_cols[0][0] == 0:
            current_group = unique_cols[0][2]
            formatted_rows.append(f"[{headers[0]} - Nhóm: {current_group}]")
            continue

        row_pairs: list[str] = []
        row_first_label = ""
        row_second_label = ""

        for c_idx, tc_id, txt in unique_cols:
            col_header = headers[c_idx] if c_idx < len(headers) else f"Cột {c_idx + 1}"
            display_val = txt
            if c_idx == 0:
                row_first_label = txt
                if current_group and not txt.lower().startswith(current_group.lower()):
                    display_val = f"{current_group} - {txt}"
            elif c_idx == 1:
                row_second_label = txt

            if c_idx == coef_col_idx and r_idx > data_start_row:
                prev_row_tc = grid[r_idx - 1][c_idx][0]
                if tc_id == prev_row_tc and current_group:
                    display_val = f"{txt} (hệ số chung của {current_group})"

            row_pairs.append(f"{col_header}: {display_val}")

        formatted_rows.append(" | ".join(row_pairs))

        # Thu thập tóm tắt Hệ số (gom theo tc_id của ô Hệ số để phản ánh đúng các ô gộp dọc)
        if coef_col_idx >= 0 and coef_col_idx < len(row_data):
            c_tc, c_val = row_data[coef_col_idx]
            if c_val:
                short_first = row_first_label if len(row_first_label) <= 45 else (row_first_label[:42].rstrip(" ,;:") + "...")
                item_desc = short_first
                if row_second_label:
                    item_desc = f"{short_first} ({row_second_label})" if short_first else row_second_label
                if coef_groups and coef_groups[-1][0] == c_tc:
                    coef_groups[-1][3].append(item_desc)
                else:
                    coef_groups.append((c_tc, current_group, c_val, [item_desc]))

        # Thu thập tóm tắt Số tín chỉ
        if credit_col_idx >= 0 and credit_col_idx < len(row_data):
            _, cr_val = row_data[credit_col_idx]
            label_col = row_second_label if (row_first_label.isdigit() and row_second_label) else (row_first_label or row_second_label)
            if label_col and cr_val:
                credit_items.append(f"{label_col}: {cr_val} tín chỉ")

    output_lines: list[str] = []
    if section_heading:
        output_lines.append(f"[Bảng thuộc mục: {section_heading}]")

    if coef_groups:
        coef_list_str = ", ".join(g[2] for g in coef_groups)
        output_lines.append(
            f"Tóm tắt phương pháp đánh giá & {len(coef_groups)} cột hệ số thành phần ({coef_list_str}):"
        )
        for _, grp_name, c_val, items in coef_groups:
            joined_items = "; ".join(i for i in items if i)
            if grp_name and not joined_items.lower().startswith(grp_name.lower()):
                output_lines.append(f"- {grp_name}: {joined_items} => Hệ số: {c_val}")
            else:
                output_lines.append(f"- {joined_items} => Hệ số: {c_val}")

    if credit_items:
        output_lines.append("Tóm tắt phân bổ số tín chỉ: " + " | ".join(credit_items) + ".")

    output_lines.extend(formatted_rows)
    return "\n".join(output_lines)


def extract_clean_text_from_docx(docx_path: str) -> list[dict]:
    """
    Trích xuất văn bản sạch (cả đoạn văn và bảng biểu) kèm metadata từ file Word (.docx):
    - Duyệt tuần tự các phần tử con trực tiếp của word_doc.element.body (CT_P và CT_Tbl)
      theo đúng thứ tự từ trên xuống dưới trong tài liệu gốc.
    - Mỗi bảng biểu luôn nằm ngay bên dưới tiêu đề mục của nó và được gắn nhãn cột đầy đủ.
    """
    filename = os.path.basename(docx_path)
    word_doc = DocxDocument(docx_path)
    blocks: list[str] = []
    current_section_heading = ""

    for child in word_doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, word_doc)
            text = unicodedata.normalize("NFC", para.text or "").strip()
            if not text:
                continue
            blocks.append(text)
            if re.match(r"^(?:\d{1,2}(?:\.\d{1,2})?\.\s+\S|[IVX]{1,4}\.\s+\S)", text) and len(text) <= 140:
                current_section_heading = text
        elif isinstance(child, CT_Tbl):
            table = Table(child, word_doc)
            table_text = _format_docx_table(table, section_heading=current_section_heading)
            if table_text:
                blocks.append(table_text)

    cleaned_text = clean_text("\n\n".join(blocks))
    return _build_logical_pages(cleaned_text, filename, docx_path)


def extract_clean_text_from_txt(txt_path: str) -> list[dict]:
    """Trích xuất văn bản sạch kèm metadata từ file văn bản thuần (.txt)."""
    filename = os.path.basename(txt_path)
    raw_text = ""
    for enc in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
        try:
            with open(txt_path, "r", encoding=enc) as f:
                raw_text = f.read()
            break
        except UnicodeDecodeError:
            continue

    cleaned_text = clean_text(raw_text)
    return _build_logical_pages(cleaned_text, filename, txt_path)


def extract_clean_text_from_file(file_path: str) -> list[dict]:
    """Điều phối trích xuất nội dung đa định dạng (.pdf, .docx, .txt)."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_clean_text_from_pdf(file_path)
    if ext == ".docx":
        return extract_clean_text_from_docx(file_path)
    if ext == ".txt":
        return extract_clean_text_from_txt(file_path)
    return []


def _iter_valid_data_files(data_dir: str = DATA_PATH) -> list[str]:
    """Liệt kê các tệp hợp lệ (.pdf, .docx, .txt) trong data/, bỏ qua tệp tạm và EXCLUDED_FILES."""
    if not os.path.isdir(data_dir):
        return []
    valid_paths = []
    for fname in sorted(os.listdir(data_dir)):
        if fname.startswith(("~$", ".")):
            continue
        full_path = os.path.join(data_dir, fname)
        if not os.path.isfile(full_path):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        if fname in EXCLUDED_FILES or fname.lower().startswith("nghi_quyet_"):
            continue
        valid_paths.append(full_path)
    return valid_paths


def build_page_documents_for_file(file_path: str, departments: dict) -> list[Document]:
    """Đọc 1 file quy chế và đóng gói thành danh sách page Document kèm metadata phòng ban + file_mtime."""
    filename = os.path.basename(file_path)
    pages_data = extract_clean_text_from_file(file_path)
    if not pages_data:
        return []

    content_preview = "\n".join(p["text"] for p in pages_data[:2])[:1500]
    dept_key, dept_info = match_department_for_file(filename, departments, content_preview=content_preview)
    file_mtime = round(os.path.getmtime(file_path), 2)

    p0 = pages_data[0]
    print(f"📖 Đang trích xuất & bóc tách Metadata tự động: {filename}")
    print(f"   ↳ Tiêu đề: {p0['title']} | Số hiệu: {p0['doc_code']} | Năm: {p0['year']} | Phòng ban: {dept_info['name']} ({dept_key})")

    page_docs = []
    for p in pages_data:
        doc = Document(
            page_content=p["text"],
            metadata={
                "source": filename,
                "title": p["title"],
                "year": str(p["year"]),
                "doc_code": p["doc_code"],
                "page": p["page"],
                "file_mtime": file_mtime,
                "dept_key": dept_key,
                "dept_name": dept_info["name"],
                "dept_location": dept_info["location"],
                "dept_phone": dept_info["phone"],
                "dept_email": dept_info["email"],
            }
        )
        page_docs.append(doc)
    return page_docs


def build_chunks_for_file(file_path: str, departments: dict) -> list[Document]:
    """
    Trích xuất và chia đoạn (chunk_size=600, overlap=100) kèm đủ metadata cho mọi file.
    Tự động gắn nhãn ngữ cảnh tài liệu [Tài liệu: <doc_title>] vào đầu mỗi chunk
    (Universal Context Prefix) để mọi bảng biểu ở giữa hoặc cuối tài liệu đều giữ trọn
    ngữ cảnh tên văn bản/môn học khi tìm kiếm và không bị bộ lọc OOS chặn nhầm.
    """
    page_docs = build_page_documents_for_file(file_path, departments)
    if not page_docs:
        return []

    doc_title = str(page_docs[0].metadata.get("title", "") or "").strip()
    doc_code = str(page_docs[0].metadata.get("doc_code", "") or "").strip()
    if doc_code and doc_code != "N/A" and doc_code.lower() not in doc_title.lower():
        universal_prefix = f"[Tài liệu: {doc_title} - Mã: {doc_code}]"
    elif doc_title:
        universal_prefix = f"[Tài liệu: {doc_title}]"
    else:
        universal_prefix = ""

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", "; ", " "]
    )
    chunks = text_splitter.split_documents(page_docs)
    if universal_prefix:
        for chunk in chunks:
            content = (chunk.page_content or "").strip()
            if not content.startswith("[Tài liệu:"):
                chunk.page_content = f"{universal_prefix}\n{content}"
    return chunks


def load_documents():
    docs = []
    departments = load_departments(DEPARTMENTS_PATH)
    for file_path in _iter_valid_data_files(DATA_PATH):
        try:
            docs.extend(build_page_documents_for_file(file_path, departments))
        except Exception as e:
            print(f"⚠️ Lỗi đọc file {file_path}: {e}")
    return docs


def create_vector_db():
    temp_db_path = str(BASE_DIR / "chroma_db_temp")
    backup_db_path = str(BASE_DIR / "chroma_db_old")

    if os.path.exists(temp_db_path):
        shutil.rmtree(temp_db_path, ignore_errors=True)

    print("⏳ Đang trích xuất văn bản đa định dạng (.pdf, .docx, .txt) từ thư mục data/...")
    departments = load_departments(DEPARTMENTS_PATH)
    chunks = []
    title_to_files: dict[str, list[tuple[str, str]]] = {}
    for file_path in _iter_valid_data_files(DATA_PATH):
        try:
            if not _is_file_ready_for_reading(file_path, wait_sec=0.3):
                continue
            file_chunks = build_chunks_for_file(file_path, departments)
            if file_chunks:
                raw_t = str(file_chunks[0].metadata.get("title", "") or "").strip()
                norm_t = re.sub(r"\s+", " ", raw_t.lower())
                title_to_files.setdefault(norm_t, []).append((os.path.basename(file_path), raw_t))
                chunks.extend(file_chunks)
        except Exception as e:
            print(f"⚠️ Lỗi xử lý file {file_path}: {e}")

    _warn_duplicate_doc_titles(title_to_files)

    print(f"🧩 Tổng số chunks tinh gọn được tạo: {len(chunks)}.")

    print("🧠 Đang tạo Vector Database tạm thời tại chroma_db_temp với mô hình bkai-foundation-models/vietnamese-bi-encoder...")
    try:
        embedding_model = HuggingFaceEmbeddings(
            model_name="bkai-foundation-models/vietnamese-bi-encoder",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )

        vector_db = Chroma.from_documents(
            documents=chunks,
            embedding=embedding_model,
            persist_directory=temp_db_path,
            collection_metadata={"hnsw:space": "cosine"}
        )
        del vector_db
    except Exception as build_err:
        print(f"❌ Lỗi khi khởi tạo Vector Database mới, giữ nguyên cơ sở dữ liệu cũ: {build_err}")
        if os.path.exists(temp_db_path):
            shutil.rmtree(temp_db_path, ignore_errors=True)
        raise build_err

    # Hoán đổi an toàn chroma_db_temp thay thế cho chroma_db sau khi tạo thành công 100%
    if os.path.exists(backup_db_path):
        shutil.rmtree(backup_db_path, ignore_errors=True)

    try:
        if os.path.exists(DB_PATH):
            os.replace(DB_PATH, backup_db_path)
        os.replace(temp_db_path, DB_PATH)
        if os.path.exists(backup_db_path):
            shutil.rmtree(backup_db_path, ignore_errors=True)
    except PermissionError:
        print("ℹ️ Thư mục chroma_db đang mở bởi tiến trình khác, tiến hành đồng bộ tệp từ chroma_db_temp...")
        shutil.copytree(temp_db_path, DB_PATH, dirs_exist_ok=True)
        shutil.rmtree(temp_db_path, ignore_errors=True)

    print("✅ ĐÃ HOÀN TẤT TẠO VÀ HOÁN ĐỔI AN TOÀN VECTOR DATABASE DYNAMIC MỚI!")


def sync_knowledge_base_from_data_dir(vector_db=None) -> dict:
    """
    Đồng bộ tăng cường kho tri thức từ thư mục data/ (.pdf, .docx, .txt) vào chroma_db:
    - File mới thêm: Chỉ trích xuất + chunk + add_documents(), không ảnh hưởng dữ liệu cũ.
    - File chỉnh sửa: Xóa chunk cũ theo source và nạp lại file mới.
    - File bị xóa / thuộc EXCLUDED_FILES: Tự động xóa toàn bộ chunk của source khỏi chroma_db.
    - File baseline chưa có file_mtime: Ghi bổ sung file_mtime tại chỗ để tránh nhúng lại toàn bộ.
    """
    if vector_db is None:
        embedding_model = HuggingFaceEmbeddings(
            model_name="bkai-foundation-models/vietnamese-bi-encoder",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )
        vector_db = Chroma(
            persist_directory=DB_PATH,
            embedding_function=embedding_model,
            collection_metadata={"hnsw:space": "cosine"},
        )

    departments = load_departments(DEPARTMENTS_PATH)
    disk_files = {}
    for full_path in _iter_valid_data_files(DATA_PATH):
        fname = os.path.basename(full_path)
        disk_files[fname] = (full_path, round(os.path.getmtime(full_path), 2))

    existing = vector_db.get(include=["metadatas"])
    existing_ids = existing.get("ids") or []
    existing_metas = existing.get("metadatas") or []

    ids_by_src = {}
    metas_by_src = {}
    mtime_by_src = {}
    for cid, meta in zip(existing_ids, existing_metas):
        meta_dict = dict(meta or {})
        src = os.path.basename(str(meta_dict.get("source", "") or ""))
        if not src:
            continue
        ids_by_src.setdefault(src, []).append(cid)
        metas_by_src.setdefault(src, []).append(meta_dict)
        if src not in mtime_by_src and meta_dict.get("file_mtime") is not None:
            try:
                mtime_by_src[src] = float(meta_dict.get("file_mtime"))
            except (TypeError, ValueError):
                pass

    added, updated, deleted, skipped = [], [], [], []
    title_to_files: dict[str, list[tuple[str, str]]] = {}
    for src, meta_list in metas_by_src.items():
        if src in disk_files and meta_list:
            raw_t = str(meta_list[0].get("title", "") or "").strip()
            norm_t = re.sub(r"\s+", " ", raw_t.lower())
            if norm_t:
                title_to_files.setdefault(norm_t, []).append((src, raw_t))

    # 1. Xóa chunk của file không còn trong data/ hoặc nằm trong danh sách loại trừ
    for src in list(ids_by_src.keys()):
        if src not in disk_files or src in EXCLUDED_FILES or src.lower().startswith("nghi_quyet_"):
            vector_db.delete(where={"source": src})
            deleted.append(src)
            print(f"[AUTO-SYNC] Đã xóa khỏi ChromaDB: {src}")

    # 2. Kiểm tra file đã có trong DB: bổ sung file_mtime nếu thiếu, hoặc nạp lại nếu bị sửa
    for src, (full_path, disk_mtime) in disk_files.items():
        if src not in ids_by_src or src in deleted:
            continue
        stored_mtime = mtime_by_src.get(src)
        if stored_mtime is None:
            src_ids = ids_by_src[src]
            if src_ids:
                updated_metas = [{**m, "file_mtime": disk_mtime} for m in metas_by_src[src]]
                vector_db._collection.update(ids=src_ids, metadatas=updated_metas)
        elif abs(disk_mtime - stored_mtime) > 1.0:
            if not _is_file_ready_for_reading(full_path, wait_sec=0.3):
                skipped.append(src)
                continue
            vector_db.delete(where={"source": src})
            new_chunks = build_chunks_for_file(full_path, departments)
            if new_chunks:
                vector_db.add_documents(new_chunks)
                raw_t = str(new_chunks[0].metadata.get("title", "") or "").strip()
                norm_t = re.sub(r"\s+", " ", raw_t.lower())
                if norm_t:
                    title_to_files.setdefault(norm_t, []).append((src, raw_t))
            updated.append(src)
            print(f"[AUTO-SYNC] Đã cập nhật lại trong ChromaDB ({len(new_chunks)} chunks): {src}")

    # 3. Nạp file mới được thêm vào data/
    for src, (full_path, _disk_mtime) in disk_files.items():
        if src not in ids_by_src:
            if not _is_file_ready_for_reading(full_path, wait_sec=0.3):
                skipped.append(src)
                continue
            new_chunks = build_chunks_for_file(full_path, departments)
            if new_chunks:
                vector_db.add_documents(new_chunks)
                added.append(src)
                raw_t = str(new_chunks[0].metadata.get("title", "") or "").strip()
                norm_t = re.sub(r"\s+", " ", raw_t.lower())
                if norm_t:
                    title_to_files.setdefault(norm_t, []).append((src, raw_t))
                print(f"[AUTO-SYNC] Đã nạp tài liệu mới vào ChromaDB ({len(new_chunks)} chunks): {src}")

    _warn_duplicate_doc_titles(title_to_files)

    return {
        "changed": bool(added or updated or deleted),
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
    }


if __name__ == "__main__":
    create_vector_db()
