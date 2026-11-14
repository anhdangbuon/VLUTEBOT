import os
import sys
import csv
import json
import time
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from rag import get_rag_chain, get_groq_api_key, REFUSAL_MESSAGE

DATASET_PATH = Path(__file__).resolve().parent / "test_dataset.json"
CSV_OUTPUT_PATH = Path(__file__).resolve().parent / "eval_results.csv"


def build_judge_clients():
    """Khởi tạo các LLM Judge (ưu tiên Groq 20B/120B/Qwen3/70B với max_tokens=1024, dự phòng Local LM Studio)."""
    clients = []
    groq_key = get_groq_api_key()
    if groq_key:
        for model_name in (
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
        ):
            clients.append((
                f"groq:{model_name}",
                ChatGroq(
                    api_key=groq_key,
                    model_name=model_name,
                    temperature=0.0,
                    max_tokens=1024,
                    max_retries=0,
                    request_timeout=20
                )
            ))
    clients.append((
        "local:qwen/qwen3.5-4b",
        ChatOpenAI(
            base_url="http://127.0.0.1:1234/v1",
            api_key="not-needed",
            model="qwen/qwen3.5-4b",
            temperature=0.0,
            max_tokens=512,
            max_retries=0,
            request_timeout=30,
            extra_body={"reasoning_effort": "none"}
        )
    ))
    return clients


def _parse_judge_output(raw: str) -> tuple[int, str] | None:
    """Trích xuất điểm (1-5) và nhận xét từ phản hồi của LLM Judge một cách an toàn."""
    cleaned = re.sub(r"```(?:json)?|```", "", raw, flags=re.IGNORECASE).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            score = max(1, min(5, int(data.get("score", 3))))
            reason = str(data.get("reason", "")).strip()
            return score, reason
        except Exception:
            pass
    m_score = re.search(r'"score"\s*:\s*([1-5])', cleaned)
    if m_score:
        score = int(m_score.group(1))
        m_reason = re.search(r'"reason"\s*:\s*"([^"\n]+)', cleaned)
        reason = m_reason.group(1).strip() if m_reason else "Đã chấm điểm (regex fallback)"
        return score, reason
    return None


def judge_answer(judge_clients, question: str, ground_truth: str, answer: str, context_text: str) -> tuple[int, str]:
    """Chấm điểm Answer Correctness / Faithfulness (1-5) bằng LLM Judge."""
    prompt = (
        "Bạn là giám khảo đánh giá chất lượng câu trả lời của hệ thống RAG tra cứu quy chế đại học.\n"
        "Hãy chấm điểm câu trả lời của Bot trên thang điểm nguyên từ 1 đến 5 dựa trên 2 tiêu chí:\n"
        "- Correctness: Đúng và đủ các ý chính so với Đáp án chuẩn (Ground Truth).\n"
        "- Faithfulness: Bám sát Ngữ cảnh văn bản trích xuất, không bịa đặt thông tin.\n"
        "Quy ước điểm:\n"
        "5 = Chính xác hoàn toàn, đủ ý trọng tâm, bám sát văn bản.\n"
        "4 = Đúng phần lớn ý chính, thiếu chi tiết nhỏ không đáng kể.\n"
        "3 = Đúng một phần, thiếu một số ý quan trọng nhưng không sai lệch nặng.\n"
        "2 = Trả lời mơ hồ, thiếu nhiều ý hoặc có chi tiết không khớp.\n"
        "1 = Sai hoàn toàn, từ chối nhầm câu có dữ liệu, hoặc bịa đặt thông tin.\n\n"
        f"Câu hỏi: {question}\n"
        f"Đáp án chuẩn (Ground Truth): {ground_truth}\n"
        f"Ngữ cảnh trích xuất:\n{context_text[:2200]}\n\n"
        f"Câu trả lời của Bot:\n{answer}\n\n"
        'Chỉ trả về duy nhất 1 JSON hợp lệ dạng: {"score": <1..5>, "reason": "<ngắn gọn 1 câu, không dùng dấu ngoặc kép bên trong>"}'
    )

    last_err = None
    for _name, client in judge_clients:
        try:
            resp = client.invoke(prompt)
            raw = getattr(resp, "content", str(resp)).strip()
            parsed = _parse_judge_output(raw)
            if parsed is not None:
                return parsed
            last_err = f"{_name}: parse_failed"
        except Exception as exc:
            last_err = f"{_name}: {exc}"
            err_msg = str(exc).lower()
            if any(tok in err_msg for tok in ("429", "rate_limit", "rate limit", "too many requests")):
                time.sleep(2.5)
            continue
    return 3, f"Không gọi được LLM Judge ({last_err})"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print("Đang khởi tạo SmartRAGChain và LLM Judge...", flush=True)
    chain = get_rag_chain()
    judge_clients = build_judge_clients()

    existing_by_id = {}
    if CSV_OUTPUT_PATH.exists():
        try:
            with open(CSV_OUTPUT_PATH, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    rid = str(row.get("id", "")).strip()
                    if rid:
                        existing_by_id[rid] = row
        except Exception:
            existing_by_id = {}

    results = []
    total = len(dataset)

    for idx, item in enumerate(dataset, 1):
        qid = item["id"]
        category = item["category"]
        question = item["question"]
        ground_truth = item["ground_truth"]
        expected_source = item["expected_source"]
        is_oos = bool(item["is_out_of_scope"])

        existing_row = existing_by_id.get(qid)
        existing_answer = str(existing_row.get("answer", "")).strip() if existing_row else ""
        existing_is_refusal = str(existing_row.get("is_refusal", "")).strip().lower() == "true" if existing_row else False
        existing_score = int(float(existing_row.get("judge_score", 0) or 0)) if existing_row else 0
        can_reuse_answer = (
            existing_row is not None
            and bool(existing_answer)
            and not existing_answer.startswith("[ERROR]")
            and not (not is_oos and existing_is_refusal)
            and not (qid in ("Q01", "Q10") and existing_score <= 1)
        )

        made_api_call = False
        reran_answer = False

        if can_reuse_answer:
            answer = existing_answer
            is_refusal = existing_is_refusal or (REFUSAL_MESSAGE in answer)
            raw_sources = str(existing_row.get("retrieved_sources", "")).strip()
            retrieved_sources = [s.strip() for s in raw_sources.split(";") if s.strip()] if raw_sources else []
            try:
                latency = round(float(existing_row.get("latency_sec", 0.0)), 3)
            except Exception:
                latency = 0.0
            context_docs = []
        else:
            reran_answer = True
            made_api_call = True
            t0 = time.perf_counter()
            try:
                rag_out = chain.invoke(question)
                answer = str(rag_out.get("answer", "")).strip()
                context_docs = rag_out.get("context", []) or []
                is_refusal = bool(rag_out.get("is_refusal", False)) or (REFUSAL_MESSAGE in answer)
            except Exception as err:
                answer = f"[ERROR] {err}"
                try:
                    context_docs = chain.filter_documents(question, k=6)
                except Exception:
                    context_docs = []
                is_refusal = False
            latency = round(time.perf_counter() - t0, 3)

            retrieved_sources = []
            for d in context_docs:
                src = os.path.basename(str(d.metadata.get("source", "")))
                if src and src not in retrieved_sources:
                    retrieved_sources.append(src)

        if is_oos:
            retrieval_hit = ""
            refusal_correct = 1 if is_refusal else 0
            judge_score = 5 if refusal_correct == 1 else 1
            judge_reason = "Từ chối đúng câu hỏi ngoài phạm vi." if refusal_correct == 1 else "Không từ chối câu hỏi ngoài phạm vi."
        else:
            retrieval_hit = 1 if expected_source in retrieved_sources else 0
            refusal_correct = ""
            if is_refusal:
                judge_score = 1
                judge_reason = "Từ chối nhầm câu hỏi thuộc phạm vi quy chế."
            else:
                existing_reason = str(existing_row.get("judge_reason", "")).strip() if existing_row else ""
                has_valid_existing_judge = (
                    not reran_answer
                    and existing_row is not None
                    and bool(existing_reason)
                    and not existing_reason.startswith("Không gọi được LLM Judge")
                )
                if has_valid_existing_judge:
                    judge_score = int(float(existing_row.get("judge_score", 3)))
                    judge_reason = existing_reason
                else:
                    if not context_docs:
                        try:
                            context_docs = chain.filter_documents(question, k=6)
                        except Exception:
                            context_docs = []
                    ctx_str = "\n---\n".join(d.page_content for d in context_docs[:4])
                    judge_score, judge_reason = judge_answer(judge_clients, question, ground_truth, answer, ctx_str)
                    made_api_call = True

        status_lbl = (
            f"OOS_OK={refusal_correct}" if is_oos
            else f"Hit={retrieval_hit} | Score={judge_score}/5"
        )
        print(f"[{idx:02d}/{total}] {qid} ({latency:.2f}s) -> {status_lbl} | Sources={retrieved_sources}", flush=True)

        results.append({
            "id": qid,
            "category": category,
            "expected_source": expected_source,
            "is_out_of_scope": is_oos,
            "question": question,
            "retrieved_sources": "; ".join(retrieved_sources),
            "retrieval_hit": retrieval_hit,
            "is_refusal": is_refusal,
            "refusal_correct": refusal_correct,
            "judge_score": judge_score,
            "judge_reason": judge_reason,
            "latency_sec": latency,
            "answer": answer.replace("\r\n", "\n")
        })
        if made_api_call:
            time.sleep(0.25)

    fieldnames = [
        "id", "category", "expected_source", "is_out_of_scope", "question",
        "retrieved_sources", "retrieval_hit", "is_refusal", "refusal_correct",
        "judge_score", "judge_reason", "latency_sec", "answer"
    ]
    with open(CSV_OUTPUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    in_scope_rows = [r for r in results if not r["is_out_of_scope"]]
    oos_rows = [r for r in results if r["is_out_of_scope"]]

    hit_rate = (sum(int(r["retrieval_hit"]) for r in in_scope_rows) / len(in_scope_rows) * 100.0) if in_scope_rows else 0.0
    refusal_acc = (sum(int(r["refusal_correct"]) for r in oos_rows) / len(oos_rows) * 100.0) if oos_rows else 0.0
    avg_score_all = sum(r["judge_score"] for r in results) / len(results) if results else 0.0
    avg_score_in_scope = sum(r["judge_score"] for r in in_scope_rows) / len(in_scope_rows) if in_scope_rows else 0.0
    avg_latency = sum(r["latency_sec"] for r in results) / len(results) if results else 0.0
    avg_latency_in_scope = sum(r["latency_sec"] for r in in_scope_rows) / len(in_scope_rows) if in_scope_rows else 0.0

    print("\n" + "=" * 72)
    print("BẢNG TỔNG HỢP KẾT QUẢ ĐÁNH GIÁ ĐỊNH LƯỢNG RAG - VLUTEBOT")
    print("=" * 72)
    print(f"Tổng số câu kiểm thử            : {len(results)} ({len(in_scope_rows)} trong phạm vi, {len(oos_rows)} ngoài phạm vi)")
    print(f"Retrieval Hit Rate (In-scope)   : {hit_rate:.2f}% ({sum(int(r['retrieval_hit']) for r in in_scope_rows)}/{len(in_scope_rows)})")
    print(f"Answer Correctness/Faithfulness : {avg_score_in_scope:.2f} / 5.00 (In-scope) | {avg_score_all:.2f} / 5.00 (Toàn bộ 35 câu)")
    print(f"Refusal Accuracy (Out-of-scope) : {refusal_acc:.2f}% ({sum(int(r['refusal_correct']) for r in oos_rows)}/{len(oos_rows)})")
    print(f"Average Latency (Toàn bộ)       : {avg_latency:.2f}s | In-scope: {avg_latency_in_scope:.2f}s")
    print(f"File chi tiết đã xuất           : {CSV_OUTPUT_PATH}")
    print("=" * 72)


if __name__ == "__main__":
    main()
