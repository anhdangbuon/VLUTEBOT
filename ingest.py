import os
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

def clean_text(text: str) -> str:
    """Loại bỏ dấu ngắt dòng vô lý giữa các từ và chuẩn hóa khoảng trắng."""
    if not text:
        return ""
    words = text.split()
    return " ".join(words)

def load_documents():
    docs = []
    pdf_files = glob.glob(os.path.join(DATA_PATH, "*.pdf"))
    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    raw_text = page.extract_text() or ""
                    cleaned = clean_text(raw_text)
                    if len(cleaned) > 20:  # Giữ lại các trang có nội dung thực tế
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
        print("🗑️ Đang xóa cơ sở dữ liệu cũ...")
        shutil.rmtree(DB_PATH)

    print("⏳ Đang trích xuất văn bản từ thư mục data...")
    documents = load_documents()
    print(f"📄 Đã nạp thành công {len(documents)} trang tài liệu.")

    print("✂️ Đang chia đoạn văn bản (Chunking tinh chỉnh 500 ký tự)...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=[". ", "; ", "\n", " "]
    )
    chunks = text_splitter.split_documents(documents)
    print(f"🧩 Tổng số chunks được tạo: {len(chunks)}.")

    print("🧠 Đang tạo Vector Database...")
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
    print("✅ ĐÃ HOÀN TẤT TẠO VECTOR DATABASE MỚI!")

if __name__ == "__main__":
    create_vector_db()