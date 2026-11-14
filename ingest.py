import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import re
import json
import shutil
import glob
import unicodedata
from pathlib import Path
from datetime import datetime
import fitz  # PyMuPDF
from docx import Document as DocxDocument
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
        ),
        "regular": (
            "học phần", "hoc_phan", "tín chỉ", "tin_chi",
            "tốt nghiệp", "tot_nghiep", "học vụ", "hoc_vu",
            "chương trình đào tạo", "chuong_trinh_dao_tao",
            "đăng ký môn", "dang_ky_mon", "học kỳ hè", "hoc_ky_he",
            "khóa luận", "khoa_luan", "xét tốt nghiệp", "xet_tot_nghiep",
            "cảnh báo học vụ", "canh_bao_hoc_vu",
        ),
    },
    "ctsv": {
        "strong": (
            "phòng công tác sinh viên", "phong_cong_tac_sinh_vien", "ctsv@vlute",
        ),
        "regular": (
            "học bổng", "hoc_bong", "rèn luyện", "ren_luyen",
            "công tác xã hội", "cong_tac_xa_hoi", "ctxh",
            "kỷ luật", "ky_luat", "khen thưởng", "khen_thuong",
            "ứng xử", "ung_xu", "ban cán sự", "ban_can_su",
        ),
    },
    "khtc": {
        "strong": (
            "phòng kế hoạch - tài chính", "phòng kế hoạch tài chính",
            "phong_ke_hoach_tai_chinh", "khtc@vlute",
        ),
        "regular": (
            "học phí", "hoc_phi", "hoàn trả", "hoan_tra",
            "biên lai", "bien_lai", "hóa đơn", "hoa_don",
            "thu học phí", "thu_hoc_phi", "tài chính", "tai_chinh",
        ),
    },
    "cntt": {
        "strong": (
            "trung tâm công nghệ thông tin", "trung_tam_cong_nghe_thong_tin",
            "ttcntt@vlute",
        ),
        "regular": (
            "an toàn thông tin", "an_toan_thong_tin", "mật khẩu", "mat_khau",
            "an ninh mạng", "an_ninh_mang", "phần mềm", "phan_mem",
            "cntt", "st.vlute.edu.vn", "elearning",
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
    Xác định phòng ban phụ trách từ tên file và tối đa 1.500 ký tự đầu nội dung văn bản:
    1. So khớp patterns của departments.json trên tên file.
    2. Nếu tên file mang tính chung (vd: thong_bao_2026.docx), chấm điểm từ khóa phòng ban trên content_preview[:1500].
    3. Mặc định trả về 'ctsv' nếu không có tín hiệu khớp rõ ràng.
    """
    fname_lower = filename.lower().replace("cong_tac_xa_hoi", "ctxh")
    for dept_key, dept_info in departments.items():
        patterns = dept_info.get("patterns", [])
        if any(str(pat).lower() in fname_lower for pat in patterns):
            return dept_key, dept_info

    preview_raw = (content_preview or "")[:1500].lower()
    if preview_raw.strip():
        preview_slug = _strip_accents(preview_raw)
        best_key = None
        best_score = 0
        for dept_key, dept_info in departments.items():
            score = 0
            cues = _DEPT_CONTENT_CUES.get(dept_key, {})
            for cue in cues.get("strong", ()):
                if cue in preview_raw or cue in preview_slug:
                    score += 3
            for cue in cues.get("regular", ()):
                if cue in preview_raw or cue in preview_slug:
                    score += 1
            for pat in dept_info.get("patterns", []):
                pat_str = str(pat).lower().strip()
                if not pat_str:
                    continue
                if pat_str == "mang":
                    if "an_ninh_mang" in preview_slug or "he_thong_mang" in preview_slug or "mạng" in preview_raw:
                        score += 1
                elif pat_str in preview_slug or pat_str.replace("_", " ") in preview_raw:
                    score += 1
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


def extract_doc_title(text: str, filename: str) -> str:
    """
    Bóc tách tiêu đề văn bản từ phần đầu nội dung file (.pdf, .docx, .txt).
    Nếu không tìm thấy, chuẩn hóa tên file (bỏ phần mở rộng, thay '_' bằng khoảng trắng, viết hoa).
    """
    m_block = re.search(
        r"(?:Ban hành|V/v ban hành|Về việc ban hành|V/v)\s+((?:Quy định|Quy chế|Quy trình|Quy tắc|Thông báo|Hướng dẫn|Kế hoạch)(?:\s+[^\n]+){1,3})",
        text,
        re.IGNORECASE
    )
    if m_block:
        title_str = re.sub(r"\s+", " ", m_block.group(1)).strip()
        title_str = re.split(r"\s+(?:HIỆU TRƯỞNG|Căn cứ)\b", title_str, flags=re.IGNORECASE)[0].strip()
        if len(title_str) > 10:
            return title_str

    m_qt = re.search(r"(QUY TRÌNH\s+HOÀN TRẢ[^\n]*(?:\n[^\n]+)?)", text, re.IGNORECASE)
    if m_qt:
        return re.sub(r"\s+", " ", m_qt.group(1)).strip()

    m = re.search(
        r"(QUY ĐỊNH[^\n]+|QUY CHẾ[^\n]+|QUY TRÌNH[^\n]+|QUYẾT ĐỊNH[^\n]+|THÔNG BÁO[^\n]+|HƯỚNG DẪN[^\n]+|KẾ HOẠCH[^\n]+)",
        text,
        re.IGNORECASE
    )
    if m:
        candidate = re.sub(r"\s+", " ", m.group(1)).strip()
        if candidate.upper() not in ["QUYẾT ĐỊNH", "QUY ĐỊNH", "QUY CHẾ", "QUY TRÌNH", "THÔNG BÁO", "HƯỚNG DẪN", "KẾ HOẠCH"]:
            return candidate

    return os.path.splitext(filename)[0].replace("_", " ").upper()


def extract_doc_year(text: str, filepath: str) -> str:
    """
    Bóc tách năm ban hành từ phần đầu nội dung tài liệu.
    Nếu không thấy, lấy năm chỉnh sửa file từ hệ thống (os.path.getmtime).
    """
    flat = re.sub(r"\s+", " ", text)
    m = re.search(
        r"(?:ngày\s*\d+\s*tháng\s*\d+\s*năm\s*|ban\s+hành\s+năm\s*|hiệu\s+lực\D{0,10}|năm\s+)(\d{4})",
        flat,
        re.IGNORECASE
    )
    if m:
        return str(m.group(1))

    m2 = re.search(r"(?:QĐ|QT|TB)[^\n]{0,30}(\d{4})", flat, re.IGNORECASE)
    if m2:
        return str(m2.group(1))

    return str(datetime.fromtimestamp(os.path.getmtime(filepath)).year)


def extract_doc_code(text: str) -> str:
    """
    Bóc tách số hiệu / mã số văn bản từ phần đầu nội dung tài liệu.
    (Ví dụ: 201/QĐ-ĐHSPKTVL, QT-SV-04, 888/TB-ĐHSPKTVL...)
    """
    flat = re.sub(r"\s+", " ", text)
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
    Làm sạch sâu văn bản PDF:
    - Loại bỏ tiêu đề bảng lặp, ký tự rác, dấu nối từ vô lý
    - Chuẩn hóa khoảng trắng và dấu câu tiếng Việt
    """
    if not text:
        return ""
    
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


def extract_clean_text_from_pdf(pdf_path: str):
    """
    Trích xuất văn bản và metadata từ file PDF bằng PyMuPDF (fitz):
    - Đọc 2 trang đầu để bóc tách tự động: title, year, doc_code.
    - Loại bỏ triệt để các watermark, footer, con dấu quét mờ in hoa rác (HUO TRU, DAI SU, UPH VIN...).
    - Giữ lại nội dung tiếng Việt chuẩn xác kèm số trang thực tế.
    """
    doc = fitz.open(pdf_path)
    filename = os.path.basename(pdf_path)

    # Bóc tách metadata tự động từ 2 trang đầu của file PDF
    first_two_pages_text = "\n".join(
        doc[i].get_text("text") for i in range(min(2, len(doc)))
    )
    doc_title = extract_doc_title(first_two_pages_text, filename)
    doc_year = extract_doc_year(first_two_pages_text, pdf_path)
    doc_code = extract_doc_code(first_two_pages_text)

    full_text = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        
        cleaned_lines = []
        for line in text.split("\n"):
            line_str = line.strip()
            if re.search(r'(HUO TRU|DAI SU|UPH VIN)', line_str, re.IGNORECASE):
                continue
            cleaned_lines.append(line_str)
            
        page_clean_text = "\n".join(cleaned_lines)
        page_clean_text = clean_text(page_clean_text)
        
        if len(page_clean_text) > 25:
            full_text.append({
                "page": page_num + 1,
                "text": page_clean_text,
                "title": doc_title,
                "year": str(doc_year),
                "doc_code": doc_code
            })
            
    doc.close()
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
        if current_len + len(line_s) + 1 > page_chars and current_lines:
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


def extract_clean_text_from_docx(docx_path: str) -> list[dict]:
    """Trích xuất văn bản sạch (cả đoạn văn và bảng biểu) kèm metadata từ file Word (.docx)."""
    filename = os.path.basename(docx_path)
    word_doc = DocxDocument(docx_path)
    blocks = []

    for para in word_doc.paragraphs:
        text = para.text.strip()
        if text:
            blocks.append(text)

    for table in word_doc.tables:
        for row in table.rows:
            row_cells = []
            prev_val = None
            for cell in row.cells:
                cell_text = re.sub(r"\s+", " ", cell.text).strip()
                if cell_text and cell_text != prev_val:
                    row_cells.append(cell_text)
                    prev_val = cell_text
            if row_cells:
                blocks.append(" | ".join(row_cells))

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
    """Trích xuất và chia đoạn (chunk_size=600, overlap=100) kèm đủ metadata cho 1 file."""
    page_docs = build_page_documents_for_file(file_path, departments)
    if not page_docs:
        return []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", "; ", " "]
    )
    return text_splitter.split_documents(page_docs)


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
    for file_path in _iter_valid_data_files(DATA_PATH):
        try:
            chunks.extend(build_chunks_for_file(file_path, departments))
        except Exception as e:
            print(f"⚠️ Lỗi xử lý file {file_path}: {e}")

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

    added, updated, deleted = [], [], []

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
            vector_db.delete(where={"source": src})
            new_chunks = build_chunks_for_file(full_path, departments)
            if new_chunks:
                vector_db.add_documents(new_chunks)
            updated.append(src)
            print(f"[AUTO-SYNC] Đã cập nhật lại trong ChromaDB ({len(new_chunks)} chunks): {src}")

    # 3. Nạp file mới được thêm vào data/
    for src, (full_path, _disk_mtime) in disk_files.items():
        if src not in ids_by_src:
            new_chunks = build_chunks_for_file(full_path, departments)
            if new_chunks:
                vector_db.add_documents(new_chunks)
                added.append(src)
                print(f"[AUTO-SYNC] Đã nạp tài liệu mới vào ChromaDB ({len(new_chunks)} chunks): {src}")

    return {
        "changed": bool(added or updated or deleted),
        "added": added,
        "updated": updated,
        "deleted": deleted,
    }


if __name__ == "__main__":
    create_vector_db()
