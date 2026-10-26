import os
from rag import get_vector_db, get_rag_chain

test_queries = [
    "Quy trình làm thủ tục hoàn trả học phí thừa gồm những bước nào?",
    "Tiêu chuẩn để được xét học bổng khuyến khích học tập là gì?",
    "Sinh viên cần hoàn thành bao nhiêu tín chỉ công tác xã hội để đủ điều kiện xét tốt nghiệp?"
]

db = get_vector_db()

print("="*80)
print("KIỂM TRA CHẤT LƯỢNG TRUY XUẤT (RETRIEVAL CHECK)")
print("="*80)

for q in test_queries:
    print(f"\n🔍 CÂU HỎI: {q}")
    docs = db.similarity_search(q, k=3)
    for i, d in enumerate(docs, 1):
        src = os.path.basename(d.metadata.get("source", "Không rõ"))
        page = d.metadata.get("page", "?")
        title = d.metadata.get("title", "Không có title")
        content_preview = d.page_content.replace("\n", " ")[:150]
        print(f"  [{i}] File: {src} (Trang {page}) | Title: {title}")
        print(f"      Trích đoạn: {content_preview}...")

print("\n" + "="*80)
print("HOÀN TẤT KIỂM TRA")
print("="*80)
