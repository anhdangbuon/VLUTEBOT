import fitz  # PyMuPDF

pdf_path = "data/quy_trinh_hoan_tra_hoc_phi.pdf"
try:
    doc = fitz.open(pdf_path)
    print(f"Tổng số trang: {len(doc)}")
    
    total_text = ""
    for page_num in range(len(doc)):
        text = doc[page_num].get_text().strip()
        print(f"\n--- TRANG {page_num + 1} (Số ký tự: {len(text)}) ---")
        print(text[:200] if text else "[TRANG TRỐNG / SCAN DẠNG ẢNH]")
        total_text += text
        
    if not total_text.strip():
        print("\n❌ KẾT LUẬN: File PDF này là BẢN SCAN DẠNG ẢNH, PyMuPDF không đọc được chữ!")
    else:
        print("\n✅ KẾT LUẬN: File PDF có chữ bình thường, sẵn sàng nạp RAG!")
except Exception as e:
    print(f"Lỗi đọc file: {e}")