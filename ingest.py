import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import re
import shutil
import glob
from datetime import datetime
import fitz  # PyMuPDF
import torch
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_chroma import Chroma

DATA_PATH = "data"
DB_PATH = "chroma_db"

# Danh sách các văn bản nghị quyết hành chính không liên quan đến sinh viên (cần loại bỏ)
EXCLUDED_FILES = [
    "nghi_quyet_71.pdf",
    "nghi_quyet_72.pdf",
    "nghi_quyet_153.pdf"
]


def extract_doc_title(text: str, filename: str) -> str:
    """
    Bóc tách tiêu đề văn bản từ nội dung 2 trang đầu của file PDF.
    Nếu không tìm thấy, chuẩn hóa tên file (bỏ .pdf, thay '_' bằng khoảng trắng, viết hoa).
    """
    m_block = re.search(
        r"(?:Ban hành|V/v ban hành|Về việc ban hành)\s+((?:Quy định|Quy chế|Quy trình|Quy tắc)(?:\s+[^\n]+){1,3})",
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

    m = re.search(r"(QUY ĐỊNH[^\n]+|QUY CHẾ[^\n]+|QUY TRÌNH[^\n]+|QUYẾT ĐỊNH[^\n]+)", text, re.IGNORECASE)
    if m:
        candidate = re.sub(r"\s+", " ", m.group(1)).strip()
        if candidate.upper() not in ["QUYẾT ĐỊNH", "QUY ĐỊNH", "QUY CHẾ", "QUY TRÌNH"]:
            return candidate

    return os.path.splitext(filename)[0].replace("_", " ").upper()


def extract_doc_year(text: str, filepath: str) -> str:
    """
    Bóc tách năm ban hành từ nội dung 2 trang đầu của file PDF.
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

    m2 = re.search(r"(?:QĐ|QT)[^\n]{0,30}(\d{4})", flat, re.IGNORECASE)
    if m2:
        return str(m2.group(1))

    return str(datetime.fromtimestamp(os.path.getmtime(filepath)).year)


def extract_doc_code(text: str) -> str:
    """
    Bóc tách số hiệu / mã số văn bản từ nội dung 2 trang đầu của file PDF.
    (Ví dụ: 201/QĐ-ĐHSPKTVL, QT-SV-04...)
    """
    flat = re.sub(r"\s+", " ", text)
    m = re.search(
        r"((?:Số|Só|Mã số)?:?\s*(?:[\d\w\-\/]+\s*\/?\s*(?:QĐ|QD|QT|HD|KH)|(?:QĐ|QT|HD|KH)[\d\w\-\/]+)[^\n\s]*)",
        flat,
        re.IGNORECASE
    )
    if m:
        code = m.group(1).strip()
        code = re.sub(r"^(?:Số|Só|Mã số)\s*:?\s*", "", code, flags=re.IGNORECASE).strip()
        return re.sub(r"\s+", "", code)

    m2 = re.search(r"((?:Số|Mã số)?:?\s*[\d\w\-\/]+(?:QĐ|QT|HD|KH)[^\n\s]*)", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()

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


def load_documents():
    docs = []
    pdf_files = sorted(glob.glob(os.path.join(DATA_PATH, "*.pdf")))
    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        
        # Bỏ qua các văn bản nghị quyết không liên quan
        if filename in EXCLUDED_FILES:
            print(f"⏩ Bỏ qua văn bản không thuộc quy chế sinh viên: {filename}")
            continue
            
        print(f"📖 Đang trích xuất & bóc tách Metadata tự động (PyMuPDF): {filename}")
        try:
            pages_data = extract_clean_text_from_pdf(file_path)
            if pages_data:
                p0 = pages_data[0]
                print(f"   ↳ Tiêu đề: {p0['title']} | Số hiệu: {p0['doc_code']} | Năm: {p0['year']}")
            for p in pages_data:
                docs.append(
                    Document(
                        page_content=p["text"],
                        metadata={
                            "source": os.path.basename(file_path),
                            "title": p["title"],
                            "year": str(p["year"]),
                            "doc_code": p["doc_code"],
                            "page": p["page"]
                        }
                    )
                )
        except Exception as e:
            print(f"⚠️ Lỗi đọc file {file_path}: {e}")
    return docs


def create_vector_db():
    if os.path.exists(DB_PATH):
        print("🗑️ Đang xóa cơ sở dữ liệu cũ để làm sạch hoàn toàn...")
        shutil.rmtree(DB_PATH)

    print("⏳ Đang trích xuất văn bản từ thư mục data bằng PyMuPDF (fitz)...")
    documents = load_documents()
    print(f"📄 Đã nạp thành công {len(documents)} trang tài liệu quy chế chính quy.")

    print("✂️ Đang chia đoạn văn bản (Chunking chuẩn hóa: chunk_size=600, overlap=100)...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", "; ", " "]
    )
    chunks = text_splitter.split_documents(documents)

    # Gắn trực tiếp metadata động vào từng chunk trước khi đưa vào ChromaDB
    for chunk in chunks:
        chunk.metadata.update({
            "title": chunk.metadata.get("title", ""),
            "year": str(chunk.metadata.get("year", "")),
            "doc_code": chunk.metadata.get("doc_code", ""),
            "source": os.path.basename(chunk.metadata.get("source", ""))
        })

    print(f"🧩 Tổng số chunks tinh gọn được tạo: {len(chunks)}.")

    print("🧠 Đang tạo Vector Database với mô hình bkai-foundation-models/vietnamese-bi-encoder...")
    embedding_model = SentenceTransformerEmbeddings(
        model_name="bkai-foundation-models/vietnamese-bi-encoder",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )
    
    vector_db = Chroma.from_documents(
        documents=chunks,
        embedding=embedding_model,
        persist_directory=DB_PATH,
        collection_metadata={"hnsw:space": "cosine"}
    )
    print("✅ ĐÃ HOÀN TẤT TẠO VECTOR DATABASE DYNAMIC MỚI SẠCH HOÀN TOÀN!")


if __name__ == "__main__":
    create_vector_db()
