import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import re
import shutil
import glob
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
    Trích xuất văn bản từ file PDF bằng PyMuPDF (fitz):
    - Đọc dạng khối văn bản tự nhiên theo trang.
    - Loại bỏ triệt để các watermark, footer, con dấu quét mờ in hoa rác (HUO TRU, DAI SU, UPH VIN...).
    - Giữ lại nội dung tiếng Việt chuẩn xác kèm số trang thực tế.
    """
    doc = fitz.open(pdf_path)
    full_text = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        # Trích xuất dạng khối văn bản để giữ đúng thứ tự đọc tự nhiên
        text = page.get_text("text")
        
        # Tiền xử lý làm sạch rác:
        # - Loại bỏ các dòng watermark/footer in hoa vô nghĩa dạng: HUO TRU DAI SU...
        cleaned_lines = []
        for line in text.split("\n"):
            line_str = line.strip()
            # Bỏ qua các dòng rác chữ in hoa cụt lủn không dấu do watermark quét nhầm
            if re.search(r'(HUO TRU|DAI SU|UPH VIN)', line_str, re.IGNORECASE):
                continue
            cleaned_lines.append(line_str)
            
        page_clean_text = "\n".join(cleaned_lines)
        page_clean_text = clean_text(page_clean_text)
        
        if len(page_clean_text) > 25:
            full_text.append({
                "page": page_num + 1,
                "text": page_clean_text
            })
            
    doc.close()
    return full_text

def load_documents():
    docs = []
    pdf_files = glob.glob(os.path.join(DATA_PATH, "*.pdf"))
    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        
        # Bỏ qua các văn bản nghị quyết không liên quan
        if filename in EXCLUDED_FILES:
            print(f"⏩ Bỏ qua văn bản không thuộc quy chế sinh viên: {filename}")
            continue
            
        print(f"📖 Đang trích xuất (PyMuPDF): {filename}")
        try:
            pages_data = extract_clean_text_from_pdf(file_path)
            for p in pages_data:
                docs.append(
                    Document(
                        page_content=p["text"],
                        metadata={
                            "source": filename,
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