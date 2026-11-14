"""Automated 70-question Hybrid Search & OOS Refusal stress test for VLUTEBOT."""
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Avoid initializing unnecessary cloud LLMs during retrieval evaluation;
# SmartRAGChain.filter_documents only uses vector_db and cached BM25 index.
from rag import SmartRAGChain, get_vector_db, get_bm25_index


def evaluate_retrieval_dataset(chain: SmartRAGChain, dataset_path: Path, is_stress70: bool = True):
    with open(dataset_path, encoding="utf-8") as f:
        items = json.load(f)

    rows = []
    passed = 0
    in_scope_total = 0
    in_scope_pass = 0
    oos_total = 0
    oos_pass = 0
    total_ms = 0.0

    for item in items:
        qid = item.get("id", "")
        question = item["question"]
        is_oos = bool(item.get("is_out_of_scope", False))
        expected_source = item.get("expected_source", "")
        if not expected_source and not is_oos:
            expected_source = ""
        expected_kws = [kw.lower() for kw in item.get("expected_keywords", [])]

        t0 = time.perf_counter()
        docs = chain.filter_documents(question, k=6)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        total_ms += elapsed_ms
        dbg = dict(getattr(chain, "last_retrieval_debug", {}) or {})

        sources = [os.path.basename(str(d.metadata.get("source", ""))).lower() for d in docs]
        pages = [d.metadata.get("page", "") for d in docs]
        joined_text = " ".join("\n".join(d.page_content.lower() for d in docs).split())

        if is_oos:
            oos_total += 1
            ok = len(docs) == 0
            source_ok = ok
            kw_ok = ok
            missing_kws = [] if ok else ["NOT_REFUSED"]
            if ok:
                oos_pass += 1
        else:
            in_scope_total += 1
            source_ok = (expected_source.lower() in sources) if expected_source else (len(docs) > 0)
            missing_kws = [kw for kw in expected_kws if kw not in joined_text]
            kw_ok = len(missing_kws) == 0
            ok = bool(docs) and source_ok and kw_ok
            if ok:
                in_scope_pass += 1

        if ok:
            passed += 1

        rows.append({
            "id": qid,
            "category": item.get("category", ""),
            "difficulty": item.get("difficulty", ""),
            "is_out_of_scope": is_oos,
            "expected_source": expected_source,
            "retrieved_sources": "|".join(f"{s}:P{p}" for s, p in zip(sources, pages)),
            "num_docs": len(docs),
            "source_ok": source_ok,
            "kw_ok": kw_ok,
            "missing_kws": "|".join(missing_kws),
            "passed": ok,
            "max_dense": dbg.get("max_dense", ""),
            "max_bm25": dbg.get("max_bm25", ""),
            "best_idf_cov": dbg.get("best_idf_cov", ""),
            "gate_reason": dbg.get("reason", ""),
            "latency_ms": round(elapsed_ms, 1),
            "question": question,
        })

    total = len(items)
    acc = (passed / total * 100.0) if total else 0.0
    in_acc = (in_scope_pass / in_scope_total * 100.0) if in_scope_total else 0.0
    oos_acc = (oos_pass / oos_total * 100.0) if oos_total else 0.0
    avg_ms = (total_ms / total) if total else 0.0

    print(f"\n=== EVALUATION SUMMARY: {dataset_path.name} ({total} questions) ===")
    print(f"Overall Accuracy : {passed}/{total} ({acc:.2f}%)")
    print(f"In-Scope Accuracy: {in_scope_pass}/{in_scope_total} ({in_acc:.2f}%)")
    print(f"OOS Refusal Acc  : {oos_pass}/{oos_total} ({oos_acc:.2f}%)")
    print(f"Avg Retrieval Lat: {avg_ms:.1f} ms")

    failures = [r for r in rows if not r["passed"]]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r in failures:
            print(
                f"  - [{r['id']}] ({r['category']}/{r['difficulty']}) "
                f"src_ok={r['source_ok']} kw_ok={r['kw_ok']} miss={r['missing_kws']} "
                f"dbg=(d={r['max_dense']}, b={r['max_bm25']}, cov={r['best_idf_cov']}, {r['gate_reason']}) "
                f"got=[{r['retrieved_sources']}] | Q: {r['question']}"
            )
    else:
        print("Zero failures!")

    if is_stress70:
        out_csv = ROOT_DIR / "evaluation" / "stress_test_70_results.csv"
        fieldnames = list(rows[0].keys())
        with open(out_csv, "w", encoding="utf-8-sig", newline="") as cf:
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved CSV report to: {out_csv}")

    return passed, total, acc


def main():
    t_init = time.perf_counter()
    vector_db = get_vector_db()
    bm25_data = get_bm25_index()
    chain = SmartRAGChain(vector_db=vector_db, llm=None, prompt=None)
    print(f"Initialized Hybrid Index ({bm25_data['total_docs']} chunks) in {time.perf_counter() - t_init:.2f}s")

    eval_dir = ROOT_DIR / "evaluation"
    evaluate_retrieval_dataset(chain, eval_dir / "stress_test_70.json", is_stress70=True)
    if (eval_dir / "test_dataset.json").exists():
        evaluate_retrieval_dataset(chain, eval_dir / "test_dataset.json", is_stress70=False)


if __name__ == "__main__":
    main()
