from pypdf import PdfReader

pdf_path = "data/quy_tac_ung_xu.pdf"
reader = PdfReader(pdf_path)

print("Số trang:", len(reader.pages))

for i, page in enumerate(reader.pages):
    text = page.extract_text()
    print(f"\n===== TRANG {i + 1} =====")
    if text:
        print(text[:1000])  # In ra 1000 ký tự đầu tiên
    else:
        print("Không đọc được chữ ở trang này.")