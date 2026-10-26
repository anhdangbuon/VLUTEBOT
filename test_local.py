from rag import get_vector_db

db = get_vector_db()
docs = db.similarity_search("quy trình hoàn trả học phí thừa các bước", k=5)

print(f"--- TÌM THẤY {len(docs)} ĐOẠN TRÍCH ---")
for i, d in enumerate(docs, 1):
    src = d.metadata.get("source", "Không rõ")
    print(f"{i}. Nguồn: {src}")
    print(f"   Trích đoạn: {d.page_content[:150]}...\n")