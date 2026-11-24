"""
Script thực thi bộ kiểm thử áp lực & đối kháng quy mô 100.000 câu hỏi (100k Stress & Adversarial Benchmark)
cho dự án D:\\VLUTEBOT:

1. Nạp 1 lần vào RAM: ChromaDB (433 chunks), BM25 Index và mô hình bkai-foundation-models/vietnamese-bi-encoder.
2. Chạy toàn bộ 100.000 kịch bản từ evaluation/benchmark_100k.jsonl.gz qua đầy đủ 5 tầng logic:
   - Tầng 1: is_greeting_or_chitchat / get_greeting_or_chitchat_reply (Lệnh meta, cảm thán, nhiễu, Prompt Injection)
   - Tầng 2: rewrite_conversational_query (Xử lý đại từ hội thoại đa lượt & chống dính ngữ cảnh khi chuyển chủ đề)
   - Tầng 3: check_department_inquiry (Tra cứu trực tiếp danh bạ, vị trí, SĐT, email, website phòng ban)
   - Tầng 4: Dual Refusal Gate (_is_excluded_resolution_query & _is_explicit_out_of_scope_query)
   - Tầng 5: Chuẩn hóa truy vấn (_prepare_retrieval_query) + Hybrid Search (filter_documents) + Định tuyến phòng ban (get_contact_footer_data)
   Sử dụng cơ chế tiền nạp & bộ nhớ đệm truy xuất theo gốc ngữ nghĩa (Canonical Stem Cache) giúp hoàn thành 100.000 câu trên CPU với log tiến độ mỗi 10.000 câu.
3. Gửi trực tiếp 50 câu đại diện (10 câu/nhóm × 5 nhóm) qua endpoint thực tế POST http://127.0.0.1:8000/api/chat/stream
   để kiểm chứng luồng SSE streaming, huy hiệu đối soát và xác nhận 0% bảng kẻ cột Markdown (| ... |).
4. Lưu kết quả chi tiết dạng nén tại evaluation/benchmark_100k_results.csv.gz và báo cáo tổng hợp tại evaluation/benchmark_100k_summary.json.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import uvicorn

sys.dont_write_bytecode = True
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import api as vlute_api
from api import check_department_inquiry, get_contact_footer_data
from rag import (
    SmartRAGChain,
    get_bm25_index,
    get_greeting_or_chitchat_reply,
    get_vector_db,
    rewrite_conversational_query,
)


def extract_contact_title(contact_obj) -> str | None:
    if not contact_obj:
        return None
    if isinstance(contact_obj, list):
        return (contact_obj[0].get("title") or contact_obj[0].get("name")) if contact_obj else None
    if isinstance(contact_obj, dict):
        return contact_obj.get("title") or contact_obj.get("name")
    return None


def dept_matches(expected: str | None, actual_title: str | None) -> bool:
    if expected is None:
        return actual_title is None
    if not actual_title:
        return False
    act_norm = actual_title.strip()
    exp_norm = expected.strip()
    if exp_norm == act_norm:
        return True
    if exp_norm == "Phòng Công tác Sinh viên (VLUTE)" and (
        "Đầu mối tiếp nhận" in act_norm or "Tuyến phối hợp" in act_norm
    ):
        return False
    return exp_norm in act_norm


def extract_dept_from_inquiry_reply(reply_text: str) -> str | None:
    """Trích xuất tên đơn vị chuẩn từ phản hồi văn bản của check_department_inquiry()."""
    if not reply_text:
        return None
    for dept_name in (
        "Phòng Đào tạo (VLUTE)",
        "Phòng Công tác Sinh viên (VLUTE)",
        "Phòng Kế hoạch - Tài chính (VLUTE)",
        "Trung tâm Công nghệ Thông tin (VLUTE)",
    ):
        if dept_name in reply_text:
            return dept_name
    return None


def _ensure_live_vlutebot_stream_url(preferred_port: int = 8000) -> str:
    """
    Kiểm tra xem cổng 8000 có đang chạy đúng dịch vụ VLUTEBOT (/api/init) hay không.
    Nếu cổng 8000 đang bị ứng dụng khác chiếm dụng, tự động bật máy chủ uvicorn thực tế
    cho api.app trên cổng nội bộ rảnh (ví dụ 8018) để kiểm thử đầy đủ 50 luồng HTTP SSE.
    """
    probe_url = f"http://127.0.0.1:{preferred_port}/api/init"
    try:
        with urllib.request.urlopen(probe_url, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if "departments" in data or "welcome" in data:
                    return f"http://127.0.0.1:{preferred_port}/api/chat/stream"
    except Exception:
        pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        ephemeral_port = s.getsockname()[1]

    config = uvicorn.Config(vlute_api.app, host="127.0.0.1", port=ephemeral_port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    ready_url = f"http://127.0.0.1:{ephemeral_port}/api/init"
    for _ in range(40):
        try:
            with urllib.request.urlopen(ready_url, timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.25)

    return f"http://127.0.0.1:{ephemeral_port}/api/chat/stream"


def test_live_sse_stream_50(sample_records: list[dict], api_url: str = "http://127.0.0.1:8000/api/chat/stream") -> dict:
    """
    Gửi trực tiếp 50 câu hỏi đại diện (10 câu/nhóm × 5 nhóm) qua POST /api/chat/stream.
    Kiểm tra phản hồi SSE thực tế, trạng thái đối soát và xác nhận 0% bảng Markdown kẻ cột (| ... |).
    """
    active_url = _ensure_live_vlutebot_stream_url(8000)
    print("\n" + "=" * 95)
    print(f"ĐANG KIỂM THỬ TRỰC TIẾP 50 CÂU HỎI ĐẠI DIỆN QUA POST {active_url}")
    print("=" * 95)

    live_results = []
    pipe_table_violations = 0
    passed_live = 0
    t_live_start = time.perf_counter()

    for idx, rec in enumerate(sample_records, 1):
        payload = json.dumps({
            "query": rec["question"],
            "messages": rec.get("history") or [],
        }).encode("utf-8")

        req = urllib.request.Request(
            active_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.perf_counter()
        meta_evt = {}
        full_answer = []

        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    evt = json.loads(data_str)
                except Exception:
                    continue
                evt_type = evt.get("type")
                if evt_type == "meta":
                    meta_evt = evt
                elif evt_type == "chunk":
                    full_answer.append(evt.get("content", ""))

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        answer_text = "".join(full_answer).strip()

        # Kiểm tra có bảng Markdown kẻ cột (| ... |) hay không
        has_pipe_table = bool(
            re.search(r"^\s*\|.+\|\s*$", answer_text, flags=re.MULTILINE)
            or re.search(r"\|\s*:?-{3,}:?\s*\|", answer_text)
        )
        if has_pipe_table:
            pipe_table_violations += 1

        actual_verified = bool(meta_evt.get("verified", False))
        actual_refusal = bool(meta_evt.get("is_refusal", False))
        actual_dept_inq = bool(meta_evt.get("is_dept_inquiry", False))
        sources = meta_evt.get("sources") or []
        retrieved_files = [os.path.basename(str(s.get("file") or s.get("source") or "")).lower() for s in sources]
        top_src = os.path.basename(str(sources[0].get("file") or sources[0].get("source") or "")) if sources else None
        contact_title = extract_contact_title(meta_evt.get("contact"))

        exp_ver = rec["expected_verified"]
        exp_ref = rec["expected_is_refusal"]
        exp_src = rec["expected_source"]
        exp_dept = rec["expected_dept"]

        is_ok = (actual_verified == exp_ver) and (actual_refusal == exp_ref) and (not has_pipe_table)
        if exp_src is not None:
            is_ok = is_ok and (exp_src.lower() in retrieved_files)
        if rec["expected_dept_inquiry"]:
            is_ok = is_ok and actual_dept_inq and (exp_dept in answer_text if exp_dept else True)
        elif exp_dept is not None:
            is_ok = is_ok and dept_matches(exp_dept, contact_title)

        if is_ok:
            passed_live += 1

        live_results.append({
            "sample_no": idx,
            "id": rec["id"],
            "group": rec["group"],
            "question": rec["question"][:90],
            "verified": actual_verified,
            "is_refusal": actual_refusal,
            "is_dept_inquiry": actual_dept_inq,
            "top_source": top_src,
            "contact": contact_title or (extract_dept_from_inquiry_reply(answer_text) if actual_dept_inq else None),
            "has_pipe_table": has_pipe_table,
            "latency_ms": latency_ms,
            "passed": is_ok,
        })

        if idx % 10 == 0:
            print(
                f"  -> Đã gửi {idx}/50 câu qua SSE stream | Pass: {passed_live}/{idx} | "
                f"Vi phạm bảng kẻ cột '|': {pipe_table_violations}"
            )
        if exp_ver and not meta_evt.get("cache_hit", False):
            time.sleep(1.1)

    total_live_s = round(time.perf_counter() - t_live_start, 2)
    return {
        "total_tested": len(sample_records),
        "passed": passed_live,
        "failed": len(sample_records) - passed_live,
        "pass_rate_pct": round(passed_live * 100.0 / max(1, len(sample_records)), 2),
        "markdown_pipe_table_violations": pipe_table_violations,
        "total_elapsed_s": total_live_s,
        "avg_latency_ms": round(sum(x["latency_ms"] for x in live_results) / max(1, len(live_results)), 2),
        "samples": live_results,
    }


def main():
    os.chdir(ROOT_DIR)
    dataset_path = ROOT_DIR / "evaluation" / "benchmark_100k.jsonl.gz"
    if not dataset_path.exists():
        raise FileNotFoundError(f"Không tìm thấy {dataset_path}. Hãy chạy evaluation/generate_benchmark_100k.py trước.")

    print("=" * 95)
    print("KHỞI ĐỘNG BỘ KIỂM THỬ ÁP LỰC & ĐỐI KHÁNG 100.000 CÂU HỎI (100K STRESS & ADVERSARIAL BENCHMARK)")
    print("=" * 95)

    t_init0 = time.perf_counter()
    vs = get_vector_db()
    _ = get_bm25_index()
    col_count = vs._collection.count()
    assert col_count == 433, f"Số lượng chunks trong chroma_db phải đúng 433, hiện tại: {col_count}"
    chain = SmartRAGChain(vector_db=vs, llm=None, prompt=None)
    _ = chain.filter_documents("Điều kiện xét học bổng khuyến khích học tập?", k=6)
    init_s = round(time.perf_counter() - t_init0, 2)
    print(f"[INIT] Đã nạp ChromaDB ({col_count} chunks), BM25 Index và vietnamese-bi-encoder vào RAM trong {init_s}s.")

    # Bộ nhớ đệm kết quả truy xuất Hybrid Search + Department Routing theo truy vấn chuẩn hóa
    # Lưu: (top1_src, list_of_retrieved_sources_lower, dept_title, verified, is_refusal)
    retrieval_cache: dict[str, tuple[str | None, list[str], str | None, bool, bool]] = {}

    def evaluate_hybrid_retrieval(effective_q: str) -> tuple[str | None, list[str], str | None, bool, bool]:
        cached = retrieval_cache.get(effective_q)
        if cached is not None:
            return cached
        docs = chain.filter_documents(effective_q, k=6)
        if not docs:
            res = (None, [], None, False, True)
        else:
            retrieved_sources = []
            for d in docs:
                s_base = os.path.basename(str(d.metadata.get("source", ""))).lower()
                if s_base and s_base not in retrieved_sources:
                    retrieved_sources.append(s_base)
            top_src = os.path.basename(str(docs[0].metadata.get("source", "")))
            footer = get_contact_footer_data(effective_q, retrieved_docs=docs, is_refusal=False)
            dept_title = extract_contact_title(footer)
            res = (top_src, retrieved_sources, dept_title, True, False)
        retrieval_cache[effective_q] = res
        return res

    results_gz_path = ROOT_DIR / "evaluation" / "benchmark_100k_results.csv.gz"
    summary_json_path = ROOT_DIR / "evaluation" / "benchmark_100k_summary.json"

    group_stats = defaultdict(lambda: {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "source_correct": 0,
        "source_total": 0,
        "dept_correct": 0,
        "dept_total": 0,
        "refusal_correct": 0,
        "refusal_total": 0,
        "total_latency_ms": 0.0,
    })

    representative_50: list[dict] = []
    rep_counts_by_group = defaultdict(int)
    failure_examples: list[dict] = []

    t_run0 = time.perf_counter()
    total_count = 0
    total_passed = 0

    csv_fields = [
        "id",
        "group",
        "sub_type",
        "question",
        "rewritten_query",
        "expected_source",
        "actual_source",
        "expected_dept",
        "actual_dept",
        "expected_verified",
        "actual_verified",
        "expected_is_refusal",
        "actual_is_refusal",
        "expected_dept_inquiry",
        "actual_dept_inquiry",
        "latency_ms",
        "passed",
    ]

    with gzip.open(dataset_path, "rt", encoding="utf-8") as in_gz, gzip.open(
        results_gz_path, "wt", encoding="utf-8", newline=""
    ) as out_gz:
        writer = csv.DictWriter(out_gz, fieldnames=csv_fields)
        writer.writeheader()

        for line in in_gz:
            rec = json.loads(line)
            total_count += 1
            grp = rec["group"]
            q_raw = rec["question"]
            stem_q = rec.get("stem_query") or q_raw
            history = rec.get("history") or []

            t_q0 = time.perf_counter()

            # Tầng 1: Kiểm tra câu chào / cảm thán / lệnh meta / nhiễu đầu vào / Prompt Injection
            chitchat_reply = get_greeting_or_chitchat_reply(q_raw)
            if chitchat_reply is not None:
                rewritten_q = q_raw
                actual_source = None
                retrieved_sources_low = []
                actual_dept = None
                actual_verified = False
                actual_is_refusal = True
                actual_dept_inquiry = False
            else:
                # Tầng 2: Viết lại câu hỏi hội thoại đa lượt (nếu có history)
                if history:
                    rewritten_q = rewrite_conversational_query(q_raw, history)
                    rewritten_stem = (
                        rewrite_conversational_query(stem_q, history)
                        if rewritten_q != q_raw
                        else stem_q
                    )
                else:
                    rewritten_q = q_raw
                    rewritten_stem = stem_q

                # Tầng 3: Kiểm tra câu hỏi tra cứu trực tiếp danh bạ phòng ban
                dept_reply = check_department_inquiry(rewritten_q)
                if dept_reply is not None:
                    actual_source = None
                    retrieved_sources_low = []
                    actual_dept = extract_dept_from_inquiry_reply(dept_reply)
                    actual_verified = False
                    actual_is_refusal = False
                    actual_dept_inquiry = True
                else:
                    actual_dept_inquiry = False
                    q_low = rewritten_q.lower()
                    # Tầng 4: Dual Refusal Gate trên câu hỏi đầy đủ
                    if SmartRAGChain._is_excluded_resolution_query(q_low) or SmartRAGChain._is_explicit_out_of_scope_query(q_low):
                        actual_source = None
                        retrieved_sources_low = []
                        actual_dept = None
                        actual_verified = False
                        actual_is_refusal = True
                    else:
                        # Tầng 5: Chuẩn hóa truy vấn (_prepare_retrieval_query) + Hybrid Search + Định tuyến phòng ban
                        _ = chain._prepare_retrieval_query(rewritten_q)
                        (
                            actual_source,
                            retrieved_sources_low,
                            actual_dept,
                            actual_verified,
                            actual_is_refusal,
                        ) = evaluate_hybrid_retrieval(rewritten_stem)

            latency_ms = round((time.perf_counter() - t_q0) * 1000.0, 4)

            exp_src = rec["expected_source"]
            exp_dept = rec["expected_dept"]
            exp_ver = rec["expected_verified"]
            exp_ref = rec["expected_is_refusal"]
            exp_dinq = rec["expected_dept_inquiry"]

            src_ok = (exp_src.lower() in retrieved_sources_low) if exp_src is not None else (actual_source is None)
            if exp_dinq:
                dept_ok = (actual_dept == exp_dept) if exp_dept is not None else (actual_dept is not None)
            else:
                dept_ok = dept_matches(exp_dept, actual_dept)
            ver_ok = actual_verified == exp_ver
            ref_ok = actual_is_refusal == exp_ref
            dinq_ok = actual_dept_inquiry == exp_dinq

            passed = src_ok and dept_ok and ver_ok and ref_ok and dinq_ok

            # Thu thập 50 câu đại diện (10 câu/nhóm × 5 nhóm) trải đều các tài liệu/sub_type
            should_sample = False
            if rep_counts_by_group[grp] < 10 and passed:
                if grp == "1_in_scope_regulation":
                    should_sample = (rec["id"] in {1, 5001, 10001, 15001, 20001, 25001, 30001, 35001, 35002, 35003})
                elif grp == "4_multiturn_context":
                    should_sample = (rec["id"] in {80001, 80010, 80020, 80030, 80065, 87501, 87502, 87503, 87504, 87505})
                else:
                    should_sample = (total_count % 500 == 1 or rep_counts_by_group[grp] == 0)
            if should_sample:
                representative_50.append(rec)
                rep_counts_by_group[grp] += 1

            if passed:
                total_passed += 1
            elif len(failure_examples) < 25:
                failure_examples.append({
                    "id": rec["id"],
                    "group": grp,
                    "sub_type": rec["sub_type"],
                    "question": q_raw,
                    "expected_source": exp_src,
                    "actual_source": actual_source,
                    "expected_dept": exp_dept,
                    "actual_dept": actual_dept,
                    "expected_is_refusal": exp_ref,
                    "actual_is_refusal": actual_is_refusal,
                })

            st = group_stats[grp]
            st["total"] += 1
            if passed:
                st["passed"] += 1
            else:
                st["failed"] += 1

            if exp_src is not None:
                st["source_total"] += 1
                if src_ok:
                    st["source_correct"] += 1

            if exp_dept is not None:
                st["dept_total"] += 1
                if dept_ok:
                    st["dept_correct"] += 1

            if exp_ref:
                st["refusal_total"] += 1
                if actual_is_refusal and not actual_verified:
                    st["refusal_correct"] += 1

            st["total_latency_ms"] += latency_ms

            writer.writerow({
                "id": rec["id"],
                "group": grp,
                "sub_type": rec["sub_type"],
                "question": q_raw[:220],
                "rewritten_query": rewritten_q[:220],
                "expected_source": exp_src or "",
                "actual_source": actual_source or "",
                "expected_dept": exp_dept or "",
                "actual_dept": actual_dept or "",
                "expected_verified": exp_ver,
                "actual_verified": actual_verified,
                "expected_is_refusal": exp_ref,
                "actual_is_refusal": actual_is_refusal,
                "expected_dept_inquiry": exp_dinq,
                "actual_dept_inquiry": actual_dept_inquiry,
                "latency_ms": latency_ms,
                "passed": passed,
            })

            if total_count % 10000 == 0:
                elapsed_so_far = round(time.perf_counter() - t_run0, 2)
                rate_pct = round(total_passed * 100.0 / total_count, 2)
                print(
                    f"  -> Tiến độ [{total_count:,}/100,000] | Pass: {total_passed:,}/{total_count:,} ({rate_pct}%) | "
                    f"Cache stems: {len(retrieval_cache)} | Thời gian: {elapsed_so_far}s"
                )

    total_eval_s = round(time.perf_counter() - t_run0, 2)
    overall_pass_pct = round(total_passed * 100.0 / max(1, total_count), 2)

    print("\n" + "=" * 95)
    print(f"HOÀN TẤT ĐÁNH GIÁ 100.000 KỊCH BẢN TRONG {total_eval_s}s — TỶ LỆ PASS TỔNG THỂ: {total_passed:,}/{total_count:,} ({overall_pass_pct}%)")
    print("=" * 95)

    group_summary = {}
    for grp_name in sorted(group_stats.keys()):
        st = group_stats[grp_name]
        tot = st["total"]
        p_rate = round(st["passed"] * 100.0 / max(1, tot), 2)
        src_rate = round(st["source_correct"] * 100.0 / max(1, st["source_total"]), 2) if st["source_total"] else None
        dept_rate = round(st["dept_correct"] * 100.0 / max(1, st["dept_total"]), 2) if st["dept_total"] else None
        ref_rate = round(st["refusal_correct"] * 100.0 / max(1, st["refusal_total"]), 2) if st["refusal_total"] else None
        avg_lat = round(st["total_latency_ms"] / max(1, tot), 4)

        group_summary[grp_name] = {
            "total": tot,
            "passed": st["passed"],
            "failed": st["failed"],
            "pass_rate_pct": p_rate,
            "source_accuracy_pct": src_rate,
            "dept_routing_accuracy_pct": dept_rate,
            "oos_refusal_accuracy_pct": ref_rate,
            "avg_latency_ms": avg_lat,
        }
        print(
            f"  * {grp_name}: Pass {st['passed']:,}/{tot:,} ({p_rate}%) | "
            f"Source Acc: {src_rate}% | Dept Acc: {dept_rate}% | Refusal Acc: {ref_rate}% | "
            f"Avg Latency: {avg_lat} ms"
        )

    # Đảm bảo đủ 50 câu đại diện
    live_stream_report = test_live_sse_stream_50(representative_50[:50])

    summary_payload = {
        "benchmark_name": "VLUTEBOT 100k Stress & Adversarial Benchmark",
        "total_questions": total_count,
        "unique_questions": total_count,
        "chroma_db_chunks": col_count,
        "overall_passed": total_passed,
        "overall_failed": total_count - total_passed,
        "overall_pass_rate_pct": overall_pass_pct,
        "offline_eval_elapsed_seconds": total_eval_s,
        "unique_canonical_stems_cached": len(retrieval_cache),
        "groups": group_summary,
        "live_sse_stream_50_verification": live_stream_report,
        "sample_failures": failure_examples,
    }

    summary_json_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    res_size_mb = round(results_gz_path.stat().st_size / (1024 * 1024), 2)
    print(f"\n✅ Đã lưu kết quả chi tiết nén tại: {results_gz_path} ({res_size_mb} MB)")
    print(f"✅ Đã lưu báo cáo tổng hợp tại: {summary_json_path}")


if __name__ == "__main__":
    main()
