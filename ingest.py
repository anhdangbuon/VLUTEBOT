import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import re
import shutil
import glob
import pdfplumber
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
    
    # 2. Xử lý từ bị gắt đôi do xuống dòng có dấu gạch ngang (ví dụ: hoàn -\n trả -> hoàn trả)
    text = re.sub(r"(\w+)\s*-\s*\n\s*(\w+)", r"\1\2", text)
    
    # 3. Chuẩn hóa dấu đầu dòng rời rạc (ví dụ: -\n Sinh viên -> - Sinh viên)
    text = re.sub(r"-\s*\n\s*", "- ", text)
    
    # 4. Thay thế nhiều dấu xuống dòng liên tiếp thành 1 dấu ngắt đoạn
    text = re.sub(r"\n{2,}", "\n", text)
    
    # 5. Loại bỏ khoảng trắng thừa
    words = text.split()
    cleaned = " ".join(words)
    
    return cleaned.strip()

def load_documents():
    docs = []
    pdf_files = glob.glob(os.path.join(DATA_PATH, "*.pdf"))
    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        
        # Bỏ qua các văn bản nghị quyết không liên quan
        if filename in EXCLUDED_FILES:
            print(f"⏩ Bỏ qua văn bản không thuộc quy chế sinh viên: {filename}")
            continue
            
        print(f"📖 Đang trích xuất: {filename}")
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    raw_text = page.extract_text() or ""
                    cleaned = clean_text(raw_text)
                    if len(cleaned) > 25:  # Chỉ giữ lại trang có nội dung chữ có nghĩa
                        docs.append(
                            Document(
                                page_content=cleaned,
                                metadata={
                                    "source": filename,
                                    "page": page_idx + 1
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

    print("⏳ Đang trích xuất văn bản từ thư mục data...")
    documents = load_documents()
    print(f"📄 Đã nạp thành công {len(documents)} trang tài liệu quy chế chính quy.")

    print("✂️ Đang chia đoạn văn bản (Chunking chuẩn hóa: chunk_size=600, overlap=80)...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=80,
        separators=["\n\n", "\n", ". ", "; ", " "]
    )
    chunks = text_splitter.split_documents(documents)
    print(f"🧩 Tổng số chunks tinh gọn được tạo: {len(chunks)}.")

    print("🧠 Đang tạo Vector Database với mô hình bkai-foundation-models/vietnamese-bi-encoder...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    embedding_model = SentenceTransformerEmbeddings(
        model_name="bkai-foundation-models/vietnamese-bi-encoder",
        model_kwargs={"device": device}
    )
    
    Chroma.from_documents(
        documents=chunks,
        embedding=embedding_model,
        persist_directory=DB_PATH
    )
    print("✅ ĐÃ HOÀN TẤT TẠO VECTOR DATABASE MỚI SẠCH HOÀN TOÀN!")

if __name__ == "__main__":
    create_vector_db()