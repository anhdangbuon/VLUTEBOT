import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import re
import math
import json
import time
import socket
import threading
import unicodedata
from pathlib import Path
try:
    import tomllib
except ImportError:
    tomllib = None
import torch
import streamlit as st
from rank_bm25 import BM25Okapi
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from ingest import (
    sync_knowledge_base_from_data_dir,
    SUPPORTED_EXTENSIONS,
    DATA_PATH,
    EXCLUDED_FILES as INGEST_EXCLUDED_FILES,
)

DEPT_FILE = Path(__file__).parent / "departments.json"
DB_PATH = str(Path(__file__).parent / "chroma_db")

# Hằng số phản hồi từ chối duy nhất cho câu hỏi ngoài phạm vi dữ liệu
REFUSAL_MESSAGE = "Nội dung này không được đề cập trong các văn bản quy định trước đây hoặc nằm ngoài phạm vi dữ liệu quy chế của Nhà trường."

# Danh sách tệp nghị quyết bị loại khỏi phạm vi tra cứu theo chính sách hệ thống
EXCLUDED_SOURCE_FILES = {"nghi_quyet_71.pdf", "nghi_quyet_72.pdf", "nghi_quyet_153.pdf"}

# Ngưỡng tương đồng Cosine tối thiểu (Cosine Similarity nằm trong đoạn [0, 1])
SIMILARITY_THRESHOLD = 0.38

# Hằng số cảnh báo khi luồng stream bị gián đoạn giữa chừng
STREAM_INTERRUPTED_NOTICE = "⚠️ *[Phản hồi bị gián đoạn giữa chừng do sự cố kết nối mô hình. Nội dung phía trên có thể chưa đầy đủ, bạn vui lòng gửi lại câu hỏi nhé!]*"


@st.cache_data(show_spinner=False)
def load_departments_config() -> dict:
    """Đọc cấu hình phòng ban tập trung từ tệp departments.json."""
    if DEPT_FILE.exists():
        try:
            with open(DEPT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def ensure_doc_department_metadata(doc, departments: dict = None):
    """Đảm bảo Document luôn có đầy đủ metadata phòng ban từ departments.json nếu cần bổ sung."""
    if not hasattr(doc, "metadata") or doc.metadata is None:
        return doc
    if doc.metadata.get("dept_name") and doc.metadata.get("dept_phone") and doc.metadata.get("dept_email"):
        return doc

    depts = departments if departments is not None else load_departments_config()
    src_name = os.path.basename(doc.metadata.get("source", "")).lower().replace("cong_tac_xa_hoi", "ctxh")
    matched_key = "ctsv"
    matched_info = depts.get("ctsv", {
        "name": "Phòng Công tác Sinh viên (VLUTE)",
        "location": "Tòa nhà A (Phòng A1.102 - Tầng trệt)",
        "phone": "(0270) 3862 436",
        "email": "ctsv@vlute.edu.vn"
    })
    for d_key, d_info in depts.items():
        patterns = d_info.get("patterns", [])
        if any(str(pat).lower() in src_name for pat in patterns):
            matched_key = d_key
            matched_info = d_info
            break

    doc.metadata.setdefault("dept_key", matched_key)
    doc.metadata.setdefault("dept_name", matched_info.get("name", "Phòng Công tác Sinh viên (VLUTE)"))
    doc.metadata.setdefault("dept_location", matched_info.get("location", "Tòa nhà A (Phòng A1.102 - Tầng trệt)"))
    doc.metadata.setdefault("dept_phone", matched_info.get("phone", "(0270) 3862 436"))
    doc.metadata.setdefault("dept_email", matched_info.get("email", "ctsv@vlute.edu.vn"))
    return doc


def extract_article_info(content: str):
    """Trích xuất tên Điều và Khoản từ đoạn văn bản."""
    m = re.search(r"Điều\s+(\d+)[\.\:]?\s*([^\n\.\;]{0,60})", content, re.IGNORECASE)
    if m:
        num = m.group(1)
        name = m.group(2).strip().strip(":")
        name = re.sub(r"[\*\_\`\#\:\.\,\;]+$", "", name).strip()
        if name and len(name) > 3 and not name.lower().startswith("khoản"):
            if len(name) > 40:
                name = name[:40].rsplit(" ", 1)[0]
            return f"Điều {num}: {name}"
        return f"Điều {num}"
    
    m_chuong = re.search(r"Chương\s+([IVXLCDM\d]+)[\.\:]?\s*([^\n\.\;]{0,40})", content, re.IGNORECASE)
    if m_chuong:
        c_num = m_chuong.group(1)
        c_name = m_chuong.group(2).strip().strip(":")
        c_name = re.sub(r"[\*\_\`\#\:\.\,\;]+$", "", c_name).strip()
        if c_name and len(c_name) > 3:
            if len(c_name) > 30:
                c_name = c_name[:30].rsplit(" ", 1)[0]
            return f"Chương {c_num}: {c_name}"
        return f"Chương {c_num}"
        
    return None


class SmartRAGChain:
    def __init__(self, vector_db, llm, prompt):
        self.vector_db = vector_db
        self.llm = llm
        self.prompt = prompt
        self.last_retrieval_debug = {}

    @staticmethod
    def _is_excluded_resolution_query(q_lower: str) -> bool:
        """Kiểm tra câu hỏi có nhắc trực tiếp tới các nghị quyết nằm trong danh sách loại trừ không."""
        excluded_patterns = [
            "nghị quyết 153", "nghi quyet 153", "153/nq-cp", "153/nq",
            "nghị quyết 71", "nghi quyet 71", "71/nq-cp", "71/nq",
            "nghị quyết 72", "nghi quyet 72", "72/nq-cp", "72/nq",
            "hội nhập quốc tế",
        ]
        return any(pat in q_lower for pat in excluded_patterns)

    @staticmethod
    def _looks_like_table_or_split_page(text: str, page_chunk_count: int) -> bool:
        """Nhận diện tự động trang bảng biểu/phụ lục thưa hoặc đoạn trích vắt trang (không hardcode PDF)."""
        if page_chunk_count <= 2:
            return True
        if "|" in text or len(text) < 420:
            return True
        return bool(re.search(r"(?i)\b(phụ lục|biểu mẫu|bảng\s+\d|như sau\s*:)", text))

    @staticmethod
    def _collapse_consecutive_repeats(tokens: list[str]) -> list[str]:
        """Khử các cụm từ hoặc câu lặp lại liên tiếp (kể cả khi không có dấu câu ngăn cách)."""
        if len(tokens) < 2:
            return tokens

        def _norm_tok(tok: str) -> str:
            return re.sub(r"^[\(\[\"'«“]+|[\)\]\.,;:!?\"'»”]+$", "", tok.lower())

        normed = [_norm_tok(t) for t in tokens]
        out: list[str] = []
        i = 0
        n = len(tokens)
        while i < n:
            matched_span = 0
            max_span = min(48, (n - i) // 2)
            for span in range(1, max_span + 1):
                base = normed[i : i + span]
                if not any(base):
                    continue
                reps = 1
                pos = i + span
                while pos + span <= n and normed[pos : pos + span] == base:
                    reps += 1
                    pos += span
                min_reps = 2 if span >= 4 else 3
                if reps >= min_reps:
                    kept = list(tokens[i : i + span])
                    last_tok = tokens[pos - 1]
                    if last_tok.endswith(("?", "!", ".")) and not kept[-1].endswith(("?", "!", ".")):
                        kept[-1] = kept[-1].rstrip(",;:") + last_tok[-1]
                    out.extend(kept)
                    i = pos
                    matched_span = span
                    break
            if not matched_span:
                out.append(tokens[i])
                i += 1
        return out

    @staticmethod
    def _prepare_retrieval_query(q_clean: str) -> str:
        """Chuẩn hóa câu truy vấn tìm kiếm tổng quát: khử lặp chuỗi, giới hạn 450 ký tự và mở rộng viết tắt nếu ngắn."""
        s = re.sub(r"\s+", " ", (q_clean or "").strip())
        if not s:
            return ""

        s = re.sub(r"([?!;])(?=\S)", r"\1 ", s)
        raw_clauses = [c.strip() for c in re.split(r"(?<=[.?!;])\s+", s) if c.strip()]
        if len(raw_clauses) > 1:
            dedup_clauses: list[str] = []
            seen_clauses: set[str] = set()
            for clause in raw_clauses:
                norm_clause = re.sub(r"[.!?,;:\s]+$", "", clause.lower()).strip()
                if len(norm_clause) >= 8 or len(norm_clause.split()) >= 3:
                    if norm_clause in seen_clauses:
                        continue
                    seen_clauses.add(norm_clause)
                dedup_clauses.append(clause)
            s = " ".join(dedup_clauses).strip()

        tokens = SmartRAGChain._collapse_consecutive_repeats(s.split())
        s = " ".join(tokens).strip()
        if not s:
            return ""

        words = s.split()
        if len(words) <= 5:
            q_punct = "?" if s.endswith("?") else ""
            stripped = re.sub(r"\b(?:lucas|alo|ad|ơi)\b", " ", s, flags=re.IGNORECASE)
            stripped = re.sub(r"^[\s\,\.\:\!\?\-]+|[\s\,\.\:\!\?\-]+$", "", stripped)
            stripped = re.sub(r"\s+", " ", stripped).strip()
            if stripped:
                s = stripped
                acronym_expansions = (
                    ("ctxh", "công tác xã hội", "công tác xã hội (CTXH)"),
                    ("kkht", "khuyến khích học tập", "học bổng khuyến khích học tập (KKHT)"),
                    ("ctsv", "công tác sinh viên", "công tác sinh viên (CTSV)"),
                    ("attt", "an toàn thông tin", "an toàn thông tin (ATTT)"),
                    ("khtc", "kế hoạch tài chính", "kế hoạch tài chính (KHTC)"),
                )
                s_low = s.lower()
                for abbr, full_check, full_label in acronym_expansions:
                    if full_check not in s_low and re.search(rf"\b{abbr}\b", s_low):
                        s = re.sub(rf"\b{abbr}\b", full_label, s, flags=re.IGNORECASE)
                        s_low = s.lower()
                if len(s.split()) <= 5 and not re.search(r"(?i)\b(quy\s+định|quy\s+chế)\b", s):
                    s = f"quy định về {s}"
                if q_punct and not s.endswith("?"):
                    s = f"{s}{q_punct}"

        if len(s) > 450:
            q_suffix = "?" if s.rstrip().endswith("?") else ""
            max_body = 450 - (1 if q_suffix else 0)
            cut = s[:max_body].rsplit(" ", 1)[0].rstrip(" ,.;:-")
            if not cut:
                cut = s[:max_body].rstrip()
            s = f"{cut}{q_suffix}" if q_suffix and not cut.endswith("?") else cut
        return s

    @staticmethod
    def _split_compound_clauses(query: str) -> list[str]:
        """
        Chỉ tách vế khi câu hỏi thực sự hỏi 2 hành vi hoặc 2 quy định độc lập
        (ví dụ nối bởi '; ', ' đồng thời ', câu hỏi phụ 'nếu/khi/còn...', hoặc 2 động từ hành vi
        riêng biệt như 'không đi hoặc vắng họp', 'thi hộ và mang tài liệu'); KHÔNG tách
        các cụm liệt kê điều kiện cùng một chế độ (như 'tín chỉ và điểm rèn luyện',
        'điểm dưới C hoặc nợ học phí').
        """
        q = re.sub(r"\s+", " ", (query or "").strip())
        if not q or len(q.split()) < 6:
            return []

        q_punct = "?" if q.endswith("?") else ""
        q_body = q.rstrip("?.! ").strip()

        fixed_phrases = (
            "cán bộ, giảng viên và người học",
            "an toàn thông tin và an ninh mạng",
            "học bổng và khen thưởng",
            "khóa luận và tốt nghiệp",
            "khen thưởng và kỷ luật",
            "đồ án và khóa luận",
            "tiểu luận và đồ án",
            "quyền lợi và nghĩa vụ",
            "nhiệm vụ và quyền hạn",
            "quyền và nghĩa vụ",
            "đoàn phí và hội phí",
            "chi đoàn và chi hội",
            "học phí và lệ phí",
            "miễn hoặc giảm",
            "miễn và giảm",
            "miễn, giảm",
        )
        protected = q_body
        restore_map = {}
        for idx, phrase in enumerate(fixed_phrases):
            token = f"__FIXEDPHRASE{idx}__"
            pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
            if pattern.search(protected):
                def _store(match, tok=token):
                    restore_map[tok] = match.group(0)
                    return tok
                protected = pattern.sub(_store, protected, count=1)

        def _restore_and_clean(raw_list: list[str]) -> list[str]:
            cleaned_parts = []
            for raw_p in raw_list:
                restored = raw_p
                for tok, orig in restore_map.items():
                    restored = restored.replace(tok, orig)
                cleaned = re.sub(r"^[\s,\-:;]+|[\s,\-:;]+$", "", restored).strip()
                if not cleaned:
                    return []
                cleaned_parts.append(cleaned)
            return cleaned_parts

        # Ưu tiên 1: Dấu phân tách câu hỏi ghép rõ ràng ('; ' hoặc ' đồng thời ')
        strong_parts = re.split(
            r"\s*(?:[;,]\s*\bđồng\s+thời\b|\bđồng\s+thời\b|;\s*)\s*",
            protected,
            flags=re.IGNORECASE,
        )
        is_strong_split = 2 <= len(strong_parts) <= 3
        parts: list[str] = []

        if is_strong_split:
            cand_parts = _restore_and_clean(strong_parts)
            if cand_parts and all(len(tokenize_vietnamese_for_bm25(p, include_bigrams=False)) >= 3 for p in cand_parts):
                parts = cand_parts
        else:
            # Ưu tiên 2: Liên từ mềm ('hoặc' / 'hay' / 'và') chỉ tách khi thực sự là 2 hành vi hoặc 2 mệnh đề hỏi
            soft_parts = re.split(r"\s*(?:\bhoặc\b|\bhay\b|\bvà\b)\s*", protected, flags=re.IGNORECASE)
            if not (2 <= len(soft_parts) <= 3):
                return []
            cand_parts = _restore_and_clean(soft_parts)
            if not cand_parts or any(len(re.findall(r"[^\W_]+", p)) < 2 for p in cand_parts):
                return []

            behavior_verb_re = re.compile(
                r"(?i)\b(?:"
                r"không\s+đi|đi\s+muộn|đi\s+trễ|vắng|nghỉ|bỏ\s+(?:thi|học|họp|sinh\s+hoạt)|"
                r"thi\s+hộ|thi\s+thay|học\s+hộ|học\s+thay|nhờ\s+(?:thi|học|làm)|"
                r"mang(?:\s+tài\s+liệu)?|đem(?:\s+tài\s+liệu)?|sử\s+dụng(?:\s+tài\s+liệu|\s+điện\s+thoại)?|"
                r"gian\s+lận|làm\s+giả|giả\s+mạo|sao\s+chép|đánh\s+nhau|gây\s+rối|xúc\s+phạm|"
                r"tổ\s+chức|đăng\s+tải|chia\s+sẻ|tiết\s+lộ|khai\s+man|chiếm\s+đoạt|hủy\s+hoại|"
                r"xâm\s+phạm|vi\s+phạm|hiến\s+máu|tham\s+gia(?!\s+xét)|rút\s+môn|bảo\s+lưu|"
                r"nộp\s+muộn|chậm\s+nộp|trốn|chống\s+đối|tuyên\s+truyền"
                r")\b"
            )
            interrogative_re = re.compile(
                r"(?i)\b(?:bao\s+nhiêu|mấy|thế\s+nào|như\s+thế\s+nào|ra\s+sao|mức\s+nào|gồm\s+những\s+gì|ở\s+đâu)\b"
            )
            cond_start_re = re.compile(r"^(?:nếu|khi|trường\s+hợp|còn)\b", flags=re.IGNORECASE)

            all_have_behavior_verb = all(behavior_verb_re.search(p) for p in cand_parts)
            dual_question_clauses = (
                bool(interrogative_re.search(cand_parts[0]))
                and any(bool(cond_start_re.match(p)) or bool(interrogative_re.search(p)) for p in cand_parts[1:])
            )
            if not (all_have_behavior_verb or dual_question_clauses):
                return []
            parts = cand_parts

        if not parts:
            return []

        subj_match = re.match(
            r"^(?:(?:khi|nếu|trường\s+hợp)\s+)?(?:sinh\s+viên|người\s+học)\b",
            parts[0],
            flags=re.IGNORECASE,
        )
        shared_subj = subj_match.group(0).strip() if subj_match else ""

        tail_match = re.search(
            r"\b((?:thì\s+)?(?:sẽ\s+|có\s+)?(?:bị|được|phải)\s+(?:trừ|cộng|xử\s+lý|xử\s+phạt|kỷ\s+luật|miễn|giảm|hoàn|tính|xét|nộp|hưởng|làm|chịu)\b.{0,50}|(?:quy\s+định|xử\s+lý|tính|xét)\s+(?:như\s+thế\s+nào|thế\s+nào|ra\s+sao)|bao\s+nhiêu\b.{0,30}|như\s+thế\s+nào|thế\s+nào|ra\s+sao|gồm\s+những\s+gì)$",
            parts[-1],
            flags=re.IGNORECASE,
        )
        shared_tail = ""
        if tail_match and len(tail_match.group(0)) < len(parts[-1]) * 0.72:
            shared_tail = tail_match.group(0).strip()

        enriched = []
        for i, part in enumerate(parts):
            clause = part
            if i > 0 and shared_subj and not re.match(r"^(?:khi|nếu|trường\s+hợp|sinh\s+viên|người\s+học)\b", clause, flags=re.IGNORECASE):
                clause = f"{shared_subj} {clause}"
            if i < len(parts) - 1 and shared_tail:
                c_low = clause.lower()
                if not any(m in c_low for m in ("bao nhiêu", "thế nào", "ra sao", "gồm những gì", "bị trừ", "bị xử lý", "kỷ luật")):
                    clause = f"{clause} {shared_tail}"
            clause = re.sub(r"\s+", " ", clause).strip()
            if len(tokenize_vietnamese_for_bm25(clause, include_bigrams=False)) < 3:
                return []
            if q_punct and not clause.endswith("?"):
                clause = f"{clause}{q_punct}"
            enriched.append(clause)
        return enriched

    def _retrieve_single_query(self, q_str: str, k: int = 6):
        """
        Truy xuất Hybrid Search đơn cho một vế/câu hỏi:
        Dense Vector (ChromaDB) + Lexical BM25 (rank_bm25) + Reciprocal Rank Fusion (RRF)
        + Mở rộng tự động trang liền kề cho bảng biểu/phụ lục vắt trang + Dual Refusal Gate.
        """
        q_clean = self._prepare_retrieval_query(q_str)
        q_lower = q_clean.lower()
        if not q_lower:
            self.last_retrieval_debug = {"reason": "empty_query", "accepted": False}
            return []

        if self._is_excluded_resolution_query(q_lower):
            self.last_retrieval_debug = {"reason": "excluded_resolution", "accepted": False}
            return []

        # 1. Truy xuất Dense Vector từ ChromaDB
        try:
            dense_results = self.vector_db.similarity_search_with_relevance_scores(
                q_clean, k=max(HYBRID_DENSE_CANDIDATES, k * 4)
            )
        except Exception:
            global _GLOBAL_VECTOR_DB
            _GLOBAL_VECTOR_DB = None
            self.vector_db = get_vector_db()
            dense_results = self.vector_db.similarity_search_with_relevance_scores(
                q_clean, k=max(HYBRID_DENSE_CANDIDATES, k * 4)
            )

        bm25_data = get_bm25_index()
        docs_corpus = bm25_data["docs"]
        unigram_sets = bm25_data["unigram_sets"]
        meta_unigram_sets = bm25_data.get("meta_unigram_sets", [])
        meta_bigram_sets = bm25_data.get("meta_bigram_sets", [])
        raw_idf = bm25_data["raw_idf"]
        page_map = bm25_data["page_map"]
        doc_key_to_idx = bm25_data["doc_key_to_idx"]
        bm25_engine = bm25_data["bm25"]
        departments = load_departments_config()

        dense_rank = {}
        dense_score = {}
        extra_dense_docs = []
        max_dense_score = 0.0
        rank_counter = 0

        for doc, rel_score in dense_results:
            src_name = os.path.basename(str(doc.metadata.get("source", ""))).lower()
            if src_name in EXCLUDED_SOURCE_FILES or src_name.startswith("nghi_quyet_"):
                continue
            score_val = float(rel_score)
            if score_val > max_dense_score:
                max_dense_score = score_val
            try:
                page_num = int(doc.metadata.get("page", 1))
            except Exception:
                page_num = 1
            doc_key = (src_name, page_num, doc.page_content.strip())
            idx = doc_key_to_idx.get(doc_key)
            if idx is not None:
                if idx not in dense_rank:
                    rank_counter += 1
                    dense_rank[idx] = rank_counter
                    dense_score[idx] = score_val
            else:
                ensure_doc_department_metadata(doc, departments)
                doc.metadata["similarity_score"] = score_val
                extra_dense_docs.append(doc)

        # 2. Chấm điểm Lexical BM25 toàn corpus
        q_tokens = tokenize_vietnamese_for_bm25(q_clean, include_bigrams=True)
        bm25_rank = {}
        bm25_score_map = {}
        max_bm25_score = 0.0

        if bm25_engine is not None and q_tokens:
            raw_scores = bm25_engine.get_scores(q_tokens)
            ranked_bm25 = sorted(
                ((i, float(s)) for i, s in enumerate(raw_scores) if float(s) > 0.0),
                key=lambda x: x[1],
                reverse=True,
            )
            if ranked_bm25:
                max_bm25_score = ranked_bm25[0][1]
            for pos, (idx, sc) in enumerate(ranked_bm25[:max(HYBRID_BM25_CANDIDATES, k * 4)], 1):
                bm25_rank[idx] = pos
                bm25_score_map[idx] = sc

        # 3. Dual Refusal Gate tổng quát (Dense + BM25 + Độ phủ IDF từ vựng nội dung)
        q_unigrams = []
        seen_u = set()
        for u in tokenize_vietnamese_for_bm25(q_clean, include_bigrams=False):
            if len(u) >= 2 and u not in seen_u:
                seen_u.add(u)
                q_unigrams.append(u)

        total_q_idf = sum(raw_idf.get(u, 3.2) for u in q_unigrams) or 1.0
        eval_candidates = set(list(dense_rank.keys())[:15]) | set(list(bm25_rank.keys())[:15])
        best_idf_cov = 0.0
        for idx in eval_candidates:
            d_set = unigram_sets[idx]
            matched_idf = sum(raw_idf.get(u, 3.2) for u in q_unigrams if u in d_set)
            cov = matched_idf / total_q_idf
            if cov > best_idf_cov:
                best_idf_cov = cov

        dense_strong = (max_dense_score >= HYBRID_STRONG_DENSE) and (
            best_idf_cov >= HYBRID_IDF_COV_FLOOR or max_bm25_score >= HYBRID_MIN_BM25_WITH_DENSE
        )
        lexical_strong = (
            (max_bm25_score >= HYBRID_STRONG_BM25)
            and (best_idf_cov >= HYBRID_IDF_COV_STRONG)
            and (max_dense_score >= 0.36)
        ) or (
            (max_bm25_score >= 44.0)
            and (best_idf_cov >= 0.48)
            and (max_dense_score >= 0.28)
        )
        both_moderate = (
            (max_dense_score >= HYBRID_SIM_FLOOR)
            and (max_bm25_score >= HYBRID_MIN_BM25_WITH_DENSE)
            and (best_idf_cov >= 0.38)
        ) or (
            (max_dense_score >= 0.43)
            and (max_bm25_score >= 18.0)
            and (best_idf_cov >= 0.37)
        )
        accepted = bool(dense_strong or lexical_strong or both_moderate)

        self.last_retrieval_debug = {
            "max_dense": round(max_dense_score, 4),
            "max_bm25": round(max_bm25_score, 4),
            "best_idf_cov": round(best_idf_cov, 4),
            "accepted": accepted,
            "reason": (
                "dense_strong" if dense_strong else (
                    "lexical_strong" if lexical_strong else (
                        "both_moderate" if both_moderate else "dual_refusal_gate"
                    )
                )
            ),
        }
        if not accepted:
            return []

        # 4. Hợp nhất xếp hạng bằng Reciprocal Rank Fusion (RRF) + đồng thuận tiêu đề & từ hiếm IDF cao
        candidate_indices = set(dense_rank.keys()) | set(bm25_rank.keys())
        q_u_set = set(q_unigrams)
        q_b_set = {t for t in q_tokens if "_" in t}
        rare_q_terms = {u: raw_idf[u] for u in q_unigrams if raw_idf.get(u, 0.0) >= 2.2}
        total_rare_idf = sum(rare_q_terms.values()) or 1.0

        rrf_scores = {}
        for idx in candidate_indices:
            r_d = dense_rank.get(idx)
            r_b = bm25_rank.get(idx)
            score = 0.0
            if r_d is not None:
                score += HYBRID_DENSE_WEIGHT / (HYBRID_RRF_K + r_d)
            if r_b is not None:
                score += HYBRID_BM25_WEIGHT / (HYBRID_RRF_K + r_b)
            if r_d is not None and r_d <= 8 and r_b is not None and r_b <= 8:
                score += 0.0025
            if rare_q_terms:
                d_u_set = unigram_sets[idx]
                matched_rare = sum(w for u, w in rare_q_terms.items() if u in d_u_set)
                score += 0.015 * (matched_rare / total_rare_idf)
            if idx < len(meta_unigram_sets) and q_u_set:
                meta_hits = len(q_u_set & meta_unigram_sets[idx])
                meta_b_hits = len(q_b_set & meta_bigram_sets[idx]) if idx < len(meta_bigram_sets) else 0
                if meta_b_hits >= 2 or meta_hits >= 4:
                    score += 0.025 * min((meta_hits + 2 * meta_b_hits) / max(len(q_u_set) + 2, 1), 1.0)
                elif meta_hits >= 2:
                    score += 0.005 * (meta_hits / max(len(q_u_set), 1))
            rrf_scores[idx] = score

        sorted_indices = sorted(
            candidate_indices,
            key=lambda i: (rrf_scores[i], bm25_score_map.get(i, 0.0), dense_score.get(i, 0.0)),
            reverse=True,
        )

        # Lấy top k tài liệu RRF chính, bảo đảm Top-1 của mỗi kênh luôn nằm trong nhóm neo đầu (<= vị trí 2)
        selected_indices = list(sorted_indices[:k])
        top_bm25_indices = [idx for idx, _r in sorted(bm25_rank.items(), key=lambda x: x[1])[:2]]
        top_dense_indices = [idx for idx, _r in sorted(dense_rank.items(), key=lambda x: x[1])[:2]]

        if top_bm25_indices and top_bm25_indices[0] not in selected_indices[:3]:
            b0 = top_bm25_indices[0]
            if b0 in selected_indices:
                selected_indices.remove(b0)
            else:
                selected_indices.pop()
            selected_indices.insert(min(1, len(selected_indices)), b0)

        for must_idx in top_bm25_indices[1:] + top_dense_indices:
            if must_idx not in selected_indices and len(selected_indices) > 0:
                for rep_pos in range(len(selected_indices) - 1, 2, -1):
                    cand_rep = selected_indices[rep_pos]
                    if cand_rep not in top_bm25_indices and cand_rep not in top_dense_indices:
                        selected_indices[rep_pos] = must_idx
                        break
        selected_set = set(selected_indices)

        # 5. Mở rộng ngữ cảnh liên tục có phân bổ công bằng cho Top-4 neo (tối đa 2-3 đoạn/neo)
        # Giúp không để neo đầu chiếm hết ngân sách và nối trọn vẹn Điều dài + Bảng vắt trang
        adjacent_extras = []
        max_neighbor_adds = 4
        max_total = 7
        for anchor_pos, anchor_idx in enumerate(selected_indices[:4]):
            if len(adjacent_extras) >= max_neighbor_adds:
                break
            anchor_doc = docs_corpus[anchor_idx]
            src_name = os.path.basename(str(anchor_doc.metadata.get("source", ""))).lower()
            try:
                page_num = int(anchor_doc.metadata.get("page", 1))
            except Exception:
                page_num = 1
            same_page_indices = page_map.get((src_name, page_num), [])
            is_table_like = self._looks_like_table_or_split_page(anchor_doc.page_content, len(same_page_indices))
            starts_with_heading = bool(re.match(r"^\s*(?:Điều\s+\d+|Chương\s+)", anchor_doc.page_content, flags=re.IGNORECASE))

            neighbor_candidates = []
            # Khi đoạn neo không bắt đầu bằng tiêu đề Điều/Chương, luôn ưu tiên đưa đoạn liền trước (-1)
            # cùng file nguồn lên đầu danh sách để nối trọn vẹn phần đầu các điều dài vắt qua trang
            has_prev_same_src = False
            if anchor_idx - 1 >= 0:
                prv_src = os.path.basename(str(docs_corpus[anchor_idx - 1].metadata.get("source", ""))).lower()
                if prv_src == src_name:
                    has_prev_same_src = True
                    if not starts_with_heading:
                        neighbor_candidates.append(anchor_idx - 1)

            # Các đoạn cùng trang để giữ đủ Khoản a, b, c của cùng một Điều
            for sibling_idx in same_page_indices:
                if sibling_idx != anchor_idx and sibling_idx not in neighbor_candidates:
                    neighbor_candidates.append(sibling_idx)
            # Nối tiếp trang kế tiếp (+1), bổ sung đoạn liền trước (-1) nếu là bảng/đầu trang khi đã có tiêu đề
            tail_base = same_page_indices[-1] if same_page_indices else anchor_idx
            if tail_base + 1 < len(docs_corpus):
                nxt_src = os.path.basename(str(docs_corpus[tail_base + 1].metadata.get("source", ""))).lower()
                if nxt_src == src_name and (tail_base + 1) not in neighbor_candidates:
                    neighbor_candidates.append(tail_base + 1)
            if has_prev_same_src and (anchor_idx - 1) not in neighbor_candidates:
                if is_table_like or (same_page_indices and anchor_idx == same_page_indices[0]):
                    neighbor_candidates.append(anchor_idx - 1)
            extra_forward_steps = (2, 3) if anchor_pos == 0 else (2,)
            for step in extra_forward_steps:
                cand_idx = tail_base + step
                if cand_idx < len(docs_corpus):
                    nxt_src = os.path.basename(str(docs_corpus[cand_idx].metadata.get("source", ""))).lower()
                    if nxt_src == src_name and cand_idx not in neighbor_candidates:
                        neighbor_candidates.append(cand_idx)

            per_anchor_cap = 3 if anchor_pos == 0 else 2
            added_for_anchor = 0
            for nb_idx in neighbor_candidates:
                if nb_idx not in selected_set and nb_idx not in adjacent_extras:
                    adjacent_extras.append(nb_idx)
                    added_for_anchor += 1
                    if len(adjacent_extras) >= max_neighbor_adds or added_for_anchor >= per_anchor_cap:
                        break

        # Chèn đoạn nối trang liền kề ngay sau 4 kết quả anchor chính để luôn giữ đủ anchor top trong docs[:5]
        insert_pos = min(4, len(selected_indices))
        ordered_indices = selected_indices[:insert_pos] + adjacent_extras + selected_indices[insert_pos:]

        result_docs = []
        for idx in ordered_indices[:max_total]:
            base_doc = docs_corpus[idx]
            meta_copy = dict(base_doc.metadata)
            meta_copy["similarity_score"] = round(dense_score.get(idx, max(HYBRID_SIM_FLOOR, max_dense_score)), 4)
            meta_copy["bm25_score"] = round(bm25_score_map.get(idx, 0.0), 4)
            meta_copy["rrf_score"] = round(rrf_scores.get(idx, 0.0), 6)
            result_docs.append(Document(page_content=base_doc.page_content, metadata=meta_copy))

        if not result_docs and extra_dense_docs:
            return extra_dense_docs[:k]
        return result_docs

    def filter_documents(self, query: str, k: int = 6):
        """
        Truy xuất Hybrid Search tổng quát (hỗ trợ cả câu đơn lẫn câu hỏi ghép nhiều vế):
        Với câu hỏi ghép nhiều hành vi/quy định độc lập, truy xuất cho cả câu đầy đủ lẫn
        từng vế con rồi trộn xen kẽ (round-robin, khử trùng lặp) tối đa 7 đoạn trích.
        """
        prepared_query = self._prepare_retrieval_query(query)
        primary_docs = self._retrieve_single_query(prepared_query, k=k)
        primary_debug = dict(self.last_retrieval_debug)

        sub_clauses = self._split_compound_clauses(prepared_query)
        if not sub_clauses:
            self.last_retrieval_debug = primary_debug
            return primary_docs

        clause_doc_lists = []
        for clause in sub_clauses:
            c_docs = self._retrieve_single_query(clause, k=k)
            if c_docs:
                clause_doc_lists.append(c_docs)

        all_lists = ([primary_docs] if primary_docs else []) + clause_doc_lists
        if not all_lists:
            self.last_retrieval_debug = primary_debug
            return []

        merged_docs = []
        seen_keys = set()
        max_merged = 7
        max_len = max(len(lst) for lst in all_lists)

        for pos in range(max_len):
            for lst in all_lists:
                if pos >= len(lst):
                    continue
                doc = lst[pos]
                src_name = os.path.basename(str(doc.metadata.get("source", ""))).lower()
                try:
                    page_num = int(doc.metadata.get("page", 1))
                except Exception:
                    page_num = 1
                dedup_key = (src_name, page_num, doc.page_content.strip())
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                merged_docs.append(doc)
                if len(merged_docs) >= max_merged:
                    break
            if len(merged_docs) >= max_merged:
                break

        self.last_retrieval_debug = {
            **primary_debug,
            "accepted": bool(merged_docs),
            "compound_clauses": sub_clauses,
            "merged_count": len(merged_docs),
        }
        return merged_docs

    def invoke(self, inputs):
        if isinstance(inputs, str):
            inputs = {"input": inputs}
        query = inputs.get("input", "").strip()
        if inputs.get("chat_history"):
            query = rewrite_conversational_query(query, inputs.get("chat_history"))

        docs = self.filter_documents(query, k=6)

        if not docs:
            return {
                "answer": REFUSAL_MESSAGE,
                "context": [],
                "is_refusal": True,
                "is_out_of_scope": True
            }

        context_parts = []
        for doc in docs[:5]:
            src_file = os.path.basename(doc.metadata.get("source", "Tài liệu"))
            page = doc.metadata.get("page", 1)
            header_line = f"--- [VĂN BẢN: {doc.metadata.get('title', src_file)} | Năm ban hành: {doc.metadata.get('year', 'Chưa rõ')} | Số hiệu: {doc.metadata.get('doc_code', '')} | Trang {page}] ---"
            context_parts.append(f"{header_line}\n{clip_context_text(doc.page_content)}")

        context_str = "\n\n".join(context_parts)
        formatted_prompt = self.prompt.format(context=context_str, input=query)
        raw_answer = self.llm.invoke(formatted_prompt)
        answer = raw_answer if isinstance(raw_answer, str) else getattr(raw_answer, 'content', str(raw_answer))
        is_refusal = (REFUSAL_MESSAGE in str(answer)) or ("không được đề cập" in str(answer).lower())

        return {
            "answer": answer,
            "context": docs,
            "is_refusal": is_refusal
        }

    def as_retriever(self, search_kwargs=None):
        kwargs = search_kwargs or {"k": 6, "fetch_k": 15}
        return self.vector_db.as_retriever(search_type="mmr", search_kwargs=kwargs)


# =======================================================
# BỘ NHỚ ĐỆM SINGLETON (MODULE-LEVEL CACHE) TĂNG TỐC KHỞI ĐỘNG < 1 GIÂY
# =======================================================
_GLOBAL_EMBEDDINGS = None
_GLOBAL_VECTOR_DB = None
_GLOBAL_LLM = None
_GLOBAL_CHAIN = None
_GLOBAL_REWRITER_LLM = None
_GLOBAL_BM25_DATA = None
_LAST_DATA_DIR_SIGNATURE = None
_DEAD_GROQ_MODELS = set()
_COOLDOWN_GROQ_MODELS: dict[str, float] = {}
_GROQ_CLIENTS_CACHE = {}
_TOML_SECRETS_CACHE: dict | None = None
_CURRENT_KEY_INDEX = 0
_CURRENT_GROQ_KEY_INDEX = 0
_GROQ_STATE_LOCK = threading.Lock()

MAX_CONTEXT_SNIPPET_CHARS = 560


def clip_context_text(text: str, max_chars: int = MAX_CONTEXT_SNIPPET_CHARS) -> str:
    """Giới hạn độ dài mỗi đoạn trích đưa vào prompt LLM để tiết kiệm token và tránh chạm trần TPM."""
    clean = str(text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "..."

# Tham số tổng quát cho Hybrid Search (Dense + BM25 + RRF + Dual Refusal Gate)
HYBRID_RRF_K = 20
HYBRID_DENSE_WEIGHT = 1.0
HYBRID_BM25_WEIGHT = 1.35
HYBRID_DENSE_CANDIDATES = 30
HYBRID_BM25_CANDIDATES = 30
HYBRID_SIM_FLOOR = 0.39
HYBRID_STRONG_DENSE = 0.51
HYBRID_STRONG_BM25 = 32.5
HYBRID_MIN_BM25_WITH_DENSE = 29.0
HYBRID_IDF_COV_STRONG = 0.44
HYBRID_IDF_COV_FLOOR = 0.35

# Chuẩn hóa viết tắt hành chính phổ biến tại VLUTE để BM25 nhận diện đồng nhất
_ACADEMIC_ACRONYM_EXPANSIONS = {
    "ctsv": ("công", "tác", "sinh", "viên"),
    "ctxh": ("công", "tác", "xã", "hội"),
    "kkht": ("khuyến", "khích", "học", "tập"),
    "attt": ("an", "toàn", "thông", "tin"),
    "khtc": ("kế", "hoạch", "tài", "chính"),
    "cvht": ("cố", "vấn", "học", "tập"),
    "cbvc": ("cán", "bộ", "viên", "chức"),
}

_ACADEMIC_SYNONYM_BIGRAMS = {
    "thi_hộ": ("thi", "thay", "kiểm", "tra", "thi_thay", "tra_thay"),
    "học_hộ": ("học", "thay", "học_thay"),
    "nhờ_người": ("nhờ", "thay", "thi_thay"),
    "rớt_môn": ("học", "lại", "điểm", "c", "học_lại", "điểm_c"),
    "nợ_môn": ("học", "lại", "điểm", "c", "học_lại", "điểm_c"),
}

_BM25_STOPWORDS = frozenset({
    "là", "của", "và", "các", "những", "trong", "cho", "về", "với", "được", "bị",
    "khi", "nào", "gì", "sao", "thế", "tại", "theo", "từ", "đến", "hoặc", "hay",
    "có", "không", "thì", "mà", "này", "đó", "kia", "nếu", "để", "như", "rằng",
    "cái", "việc", "sự", "một", "sẽ", "đã", "đang", "do", "bởi", "qua", "vào",
    "ra", "lên", "xuống", "lại", "nữa", "cũng", "đều", "phải", "cần", "nên",
    "bao", "nhiêu", "làm", "gồm", "vậy", "nhé", "nhỉ", "ạ", "ơi", "vì",
    "trên", "dưới", "sau", "trước", "giữa", "bằng", "nơi", "nhất", "hơn", "kém",
    "từng", "mỗi", "mọi", "tất", "cả", "còn", "hỏi", "xin", "cho_biết", "biết",
    "thế_nào", "như_thế", "như_nào", "ra_sao", "có_thể", "hay_không", "lucas", "ad",
})


def tokenize_vietnamese_for_bm25(text: str, include_bigrams: bool = True) -> list[str]:
    """Chuẩn hóa và tách từ tiếng Việt (unigram + bigram + mã văn bản) cho BM25."""
    if not text:
        return []
    normalized = unicodedata.normalize("NFC", str(text)).lower()
    normalized = re.sub(r"(\d),(\d)", r"\1.\2", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Giữ lại các mã hiệu có gạch nối hoặc gạch chéo (vd: bm-kh-10a, qt-sv-04, 201/qd-dhspktvl)
    compound_codes = re.findall(r"[0-9a-zđ]+(?:[-/][0-9a-zđ]+)+", normalized)

    # Tách từ tiếng Việt và số thập phân (giữ 3.2, 0.5 nhưng bỏ dấu câu cuối câu)
    raw_tokens = re.findall(r"\d+\.\d+|[^\W_]+", normalized, flags=re.UNICODE)
    content_unigrams = []
    for tok in raw_tokens:
        if tok in _BM25_STOPWORDS:
            continue
        content_unigrams.append(tok)
        if tok in _ACADEMIC_ACRONYM_EXPANSIONS:
            content_unigrams.extend(_ACADEMIC_ACRONYM_EXPANSIONS[tok])
        if tok.isdigit() and len(tok) == 2 and tok.startswith("0"):
            content_unigrams.append(tok.lstrip("0") or "0")

    tokens = list(content_unigrams)
    tokens.extend(compound_codes)

    if include_bigrams and len(content_unigrams) >= 2:
        for i in range(len(content_unigrams) - 1):
            bg = f"{content_unigrams[i]}_{content_unigrams[i + 1]}"
            tokens.append(bg)
            if bg in _ACADEMIC_SYNONYM_BIGRAMS:
                tokens.extend(_ACADEMIC_SYNONYM_BIGRAMS[bg])

    return tokens


def _expand_bm25_corpus(raw_docs: list[str], raw_metas: list[dict], departments: dict):
    """Xây dựng chỉ mục BM25Okapi, bản đồ trang (page_map) và trọng số IDF thô."""
    docs = []
    tokenized_docs = []
    unigram_sets = []
    meta_unigram_sets = []
    meta_bigram_sets = []
    doc_key_to_idx = {}
    page_map = {}
    df_counts = {}

    for text, meta in zip(raw_docs, raw_metas):
        if not text or not text.strip():
            continue
        meta_copy = dict(meta or {})
        src_name = os.path.basename(str(meta_copy.get("source", ""))).lower()
        if src_name in EXCLUDED_SOURCE_FILES or src_name.startswith("nghi_quyet_"):
            continue

        doc = Document(page_content=text, metadata=meta_copy)
        ensure_doc_department_metadata(doc, departments)
        try:
            page_num = int(doc.metadata.get("page", 1))
        except Exception:
            page_num = 1

        idx = len(docs)
        docs.append(doc)

        tokens = tokenize_vietnamese_for_bm25(text, include_bigrams=True)
        tokenized_docs.append(tokens)

        u_set = set(tokenize_vietnamese_for_bm25(text, include_bigrams=False))
        unigram_sets.append(u_set)
        for u in u_set:
            df_counts[u] = df_counts.get(u, 0) + 1

        src_base = os.path.splitext(src_name)[0].replace("_", " ")
        meta_str = f"{doc.metadata.get('title', '')} {doc.metadata.get('doc_code', '')} {src_base}"
        meta_all = set(tokenize_vietnamese_for_bm25(meta_str, include_bigrams=True))
        meta_unigram_sets.append({t for t in meta_all if "_" not in t})
        meta_bigram_sets.append({t for t in meta_all if "_" in t})

        doc_key = (src_name, page_num, text.strip())
        doc_key_to_idx.setdefault(doc_key, idx)
        page_map.setdefault((src_name, page_num), []).append(idx)

    total_docs = max(len(docs), 1)
    raw_idf = {}
    for term, df in df_counts.items():
        val = math.log((total_docs - df + 0.5) / (df + 0.5))
        raw_idf[term] = max(0.30, val)

    bm25 = BM25Okapi(tokenized_docs) if tokenized_docs else None
    return {
        "docs": docs,
        "tokenized_docs": tokenized_docs,
        "unigram_sets": unigram_sets,
        "meta_unigram_sets": meta_unigram_sets,
        "meta_bigram_sets": meta_bigram_sets,
        "bm25": bm25,
        "raw_idf": raw_idf,
        "page_map": page_map,
        "doc_key_to_idx": doc_key_to_idx,
        "total_docs": total_docs,
    }


@st.cache_resource(show_spinner=False)
def get_bm25_index():
    """Khởi tạo và cache chỉ mục BM25 toàn văn từ ChromaDB để phục vụ Hybrid Search."""
    global _GLOBAL_BM25_DATA
    if _GLOBAL_BM25_DATA is not None:
        return _GLOBAL_BM25_DATA

    vector_db = get_vector_db()
    data = vector_db.get(include=["documents", "metadatas"])
    raw_docs = data.get("documents", []) or []
    raw_metas = data.get("metadatas", []) or []
    departments = load_departments_config()
    _GLOBAL_BM25_DATA = _expand_bm25_corpus(raw_docs, raw_metas, departments)
    return _GLOBAL_BM25_DATA


def get_data_dir_signature(data_dir: str = DATA_PATH) -> tuple:
    """Tính nhanh chữ ký (tên, mtime, kích thước) của các tệp hợp lệ trong thư mục data/ (< 5ms)."""
    if not os.path.isdir(data_dir):
        return ()
    excluded_set = set(EXCLUDED_SOURCE_FILES) | {str(f).lower() for f in INGEST_EXCLUDED_FILES}
    sig_items = []
    try:
        with os.scandir(data_dir) as it:
            for entry in it:
                fname = entry.name
                if fname.startswith(("~$", ".")) or not entry.is_file():
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                fname_lower = fname.lower()
                if fname_lower in excluded_set or fname_lower.startswith("nghi_quyet_"):
                    continue
                st_res = entry.stat()
                sig_items.append((fname, round(st_res.st_mtime, 2), st_res.st_size))
    except Exception:
        return ()
    sig_items.sort()
    return tuple(sig_items)


def auto_sync_knowledge_base(force: bool = False) -> dict:
    """
    Kiểm tra chữ ký thư mục data/ với chi phí < 5ms; chỉ đồng bộ ChromaDB & làm mới BM25 RRF
    khi phát hiện có file mới, file sửa đổi hoặc file bị xóa.
    """
    global _LAST_DATA_DIR_SIGNATURE, _GLOBAL_BM25_DATA
    current_sig = get_data_dir_signature(DATA_PATH)
    if not force and _LAST_DATA_DIR_SIGNATURE == current_sig:
        return {"changed": False, "added": [], "updated": [], "deleted": []}

    vector_db = get_vector_db()
    sync_res = sync_knowledge_base_from_data_dir(vector_db=vector_db)
    _LAST_DATA_DIR_SIGNATURE = current_sig

    if sync_res.get("changed"):
        _GLOBAL_BM25_DATA = None
        try:
            get_bm25_index.clear()
        except Exception:
            pass
        get_bm25_index()
        print(f"[AUTO-SYNC] Đồng bộ hoàn tất và đã làm mới Hybrid BM25 Index: {sync_res}")

    return sync_res


def _parse_keys_value(raw_val):
    """Chuẩn hóa giá trị key (list hoặc chuỗi phân tách bởi dấu phẩy/xuống dòng) thành danh sách các API key sạch."""
    if not raw_val:
        return []
    if isinstance(raw_val, (list, tuple, set)):
        items = []
        for item in raw_val:
            items.extend(str(item).replace("\n", ",").split(","))
    else:
        items = str(raw_val).replace("\n", ",").split(",")

    cleaned = []
    for k in items:
        key_str = k.strip().strip('"').strip("'")
        if key_str and key_str not in cleaned:
            cleaned.append(key_str)
    return cleaned


def _load_secrets_toml_fallback() -> dict:
    """Đọc trực tiếp tệp .streamlit/secrets.toml bằng tomllib khi chạy ngoài runtime Streamlit (FastAPI/CLI)."""
    global _TOML_SECRETS_CACHE
    if _TOML_SECRETS_CACHE is not None:
        return _TOML_SECRETS_CACHE

    if tomllib is None:
        _TOML_SECRETS_CACHE = {}
        return _TOML_SECRETS_CACHE

    candidate_paths = (
        Path(__file__).parent / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
    )
    for sec_path in candidate_paths:
        if sec_path.is_file():
            try:
                with open(sec_path, "rb") as f:
                    data = tomllib.load(f)
                if isinstance(data, dict):
                    _TOML_SECRETS_CACHE = data
                    return _TOML_SECRETS_CACHE
            except Exception:
                pass
    _TOML_SECRETS_CACHE = {}
    return _TOML_SECRETS_CACHE


def _collect_secret_or_env_keys(sec_names: tuple[str, ...]) -> list[str]:
    """Đọc key từ st.secrets (nếu trong Streamlit runtime), dự phòng .streamlit/secrets.toml (tomllib) và biến môi trường."""
    raw_keys = []
    in_st_runtime = False
    try:
        rt = getattr(st, "runtime", None)
        if rt is not None and callable(getattr(rt, "exists", None)):
            in_st_runtime = bool(rt.exists())
    except Exception:
        in_st_runtime = False

    if in_st_runtime and hasattr(st, "secrets"):
        try:
            for sec_name in sec_names:
                if sec_name in st.secrets:
                    val = st.secrets[sec_name]
                    if isinstance(val, str):
                        raw_keys.append(val)
                    elif isinstance(val, (list, tuple, set)):
                        raw_keys.extend(list(val))
                    else:
                        raw_keys.extend(_parse_keys_value(val))
        except Exception:
            pass

    if not raw_keys:
        toml_data = _load_secrets_toml_fallback()
        for sec_name in sec_names:
            if sec_name in toml_data:
                raw_keys.extend(_parse_keys_value(toml_data[sec_name]))

    for env_name in sec_names:
        env_val = os.getenv(env_name)
        if env_val:
            raw_keys.extend(_parse_keys_value(env_val))

    return _parse_keys_value(raw_keys)


def get_all_google_api_keys():
    """
    Đọc danh sách khóa API từ st.secrets, .streamlit/secrets.toml (tomllib) hoặc biến môi trường:
    - Nếu là string (GEMINI_API_KEY): tự động bọc thành list.
    - Nếu là list (GEMINI_API_KEYS): giữ nguyên list.
    - Kiểm tra hợp lệ: Bắt buộc key phải bắt đầu bằng 'AIzaSy' (bỏ qua ngay lập tức các chuỗi
      bắt đầu bằng 'AQ...' hoặc chuỗi rác để tránh treo timeout 40s).
    """
    cleaned = _collect_secret_or_env_keys(("GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEYS", "GOOGLE_API_KEY"))
    # Lọc nghiêm ngặt: Chỉ giữ lại các key Google hợp lệ bắt đầu bằng 'AIzaSy'
    valid_keys = [k for k in cleaned if k.startswith("AIzaSy")]
    return valid_keys


def get_google_api_key():
    """Lấy 1 API key theo cơ chế Round-Robin toàn cục (_CURRENT_KEY_INDEX)."""
    global _CURRENT_KEY_INDEX
    keys = get_all_google_api_keys()
    if not keys:
        return None
    with _GROQ_STATE_LOCK:
        idx = _CURRENT_KEY_INDEX % len(keys)
        _CURRENT_KEY_INDEX = (_CURRENT_KEY_INDEX + 1) % len(keys)
    return keys[idx]


def get_all_groq_api_keys() -> list[str]:
    """Đọc danh sách Groq API key từ GROQ_API_KEYS / GROQ_API_KEY trong st.secrets, secrets.toml hoặc biến môi trường."""
    return _collect_secret_or_env_keys(("GROQ_API_KEYS", "GROQ_API_KEY"))


def get_groq_api_key():
    """
    Lấy Groq API key theo cơ chế Round-Robin khi cấu hình nhiều key (GROQ_API_KEYS);
    tương thích 100% khi chỉ cấu hình 1 key GROQ_API_KEY.
    """
    global _CURRENT_GROQ_KEY_INDEX
    keys = get_all_groq_api_keys()
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    with _GROQ_STATE_LOCK:
        idx = _CURRENT_GROQ_KEY_INDEX % len(keys)
        _CURRENT_GROQ_KEY_INDEX = (_CURRENT_GROQ_KEY_INDEX + 1) % len(keys)
    return keys[idx]


@st.cache_resource(show_spinner=False)
def get_embedding_model():
    """Luôn sử dụng mô hình SentenceTransformer để khớp 100% với dữ liệu ChromaDB đã lưu."""
    global _GLOBAL_EMBEDDINGS
    if _GLOBAL_EMBEDDINGS is not None:
        return _GLOBAL_EMBEDDINGS

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    device = "cpu"
    try:
        torch.set_num_threads(2)
    except Exception:
        pass

    _GLOBAL_EMBEDDINGS = HuggingFaceEmbeddings(
        model_name="bkai-foundation-models/vietnamese-bi-encoder",
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True}
    )
    return _GLOBAL_EMBEDDINGS


@st.cache_resource(show_spinner=False)
def get_vector_db():
    """Khởi tạo kết nối ChromaDB với persist_directory có sẵn, chuyển đổi Cosine Distance sang Relevance Score [0, 1]."""
    global _GLOBAL_VECTOR_DB
    if _GLOBAL_VECTOR_DB is not None:
        return _GLOBAL_VECTOR_DB
    
    embedding_model = get_embedding_model()
    _GLOBAL_VECTOR_DB = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embedding_model,
        collection_metadata={"hnsw:space": "cosine"},
        relevance_score_fn=lambda distance: max(0.0, min(1.0, 1.0 - float(distance)))
    )
    return _GLOBAL_VECTOR_DB


class RotatingResilientLLM:
    """
    Lớp bọc LLM với Groq LPU làm Engine xử lý chính (Tier 1):
    - TẦNG 1 (Mặc định): Groq API (xoay vòng tự động + giữ ấm client cache) - sinh chữ tốc độ cao.
    - TẦNG 2 (Dự phòng 1): Local LLM (LM Studio - http://127.0.0.1:1234/v1, model qwen/qwen3.5-4b).
    - TẦNG 2 (Dự phòng 2): Gemini (chỉ gọi nếu có key 'AIzaSy...' hợp lệ).
    - TẦNG 3: Báo lỗi quá tải an toàn (429 RESOURCE_EXHAUSTED).
    """
    def __init__(self, local_llm, groq_llm=None, max_output_tokens: int = 2048, temperature: float = 0.0, preferred_model: str | None = None):
        self.local_llm = local_llm
        self.groq_llm = groq_llm
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.preferred_model = preferred_model
        self._cloud_clients = {}
        self._models_lock = threading.Lock()
        self._groq_models = [
            "openai/gpt-oss-120b",
            "qwen/qwen3-32b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ]
        self._dead_groq_models = _DEAD_GROQ_MODELS
        self._cooldown_groq_models = _COOLDOWN_GROQ_MODELS

    def _get_cloud_client(self, api_key: str):
        with self._models_lock:
            if api_key not in self._cloud_clients:
                self._cloud_clients[api_key] = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    google_api_key=api_key,
                    max_retries=0,        # Tắt hoàn toàn cơ chế tự động thử lại của LangChain
                    request_timeout=4,    # Ngắt kết nối nhanh trong 4 giây nếu mạng bị nghẽn
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                    streaming=True
                )
            return self._cloud_clients[api_key]

    def _get_groq_client(self, model_name: str = "openai/gpt-oss-120b", temperature: float | None = None, max_tokens: int | None = None):
        groq_api_key = get_groq_api_key()
        if not groq_api_key:
            return None
        temp = self.temperature if temperature is None else temperature
        mtok = self.max_output_tokens if max_tokens is None else max_tokens
        timeout_sec = 4.5 if int(mtok) <= 200 else 6.5
        is_gpt_oss = "gpt-oss" in model_name
        effective_mtok = max(int(mtok), 600 if int(mtok) <= 200 else 2500) if is_gpt_oss else int(mtok)
        extra_kwargs = {"reasoning_effort": "low"} if is_gpt_oss else {}
        cache_key = (groq_api_key, model_name, float(temp), effective_mtok, is_gpt_oss, timeout_sec)
        with _GROQ_STATE_LOCK:
            client = _GROQ_CLIENTS_CACHE.get(cache_key)
            if client is None:
                client = ChatGroq(
                    api_key=groq_api_key,
                    model_name=model_name,
                    temperature=temp,
                    max_tokens=effective_mtok,
                    max_retries=0,
                    request_timeout=timeout_sec,
                    **extra_kwargs,
                )
                _GROQ_CLIENTS_CACHE[cache_key] = client
            return client

    def _promote_groq_model(self, groq_model: str):
        with self._models_lock:
            if groq_model in self._groq_models and groq_model != self._groq_models[0]:
                self._groq_models.remove(groq_model)
                self._groq_models.insert(0, groq_model)

    def _handle_groq_error(self, groq_model: str, err: Exception):
        """Phân loại lỗi Groq, gắn cooldown 45s cho model chạm trần 429 và xoay vòng tức thì (0ms)."""
        err_msg = str(err).lower()
        if any(tok in err_msg for tok in ("not_found", "does not exist", "404", "decommissioned", "model_not_found")):
            with _GROQ_STATE_LOCK:
                _DEAD_GROQ_MODELS.add(groq_model)
            return
        if any(tok in err_msg for tok in ("429", "rate_limit", "rate limit", "too many requests")):
            with _GROQ_STATE_LOCK:
                _COOLDOWN_GROQ_MODELS[groq_model] = time.time() + 45.0
            with self._models_lock:
                if groq_model in self._groq_models:
                    self._groq_models.remove(groq_model)
                    self._groq_models.append(groq_model)

    def _get_candidate_groq_models(self, prioritize_fast: bool = False) -> list[str]:
        """Lọc bỏ các model đã chết (404) hoặc đang trong thời gian cooldown 45s do 429 TPM."""
        now = time.time()
        with _GROQ_STATE_LOCK:
            for m_expired in [m for m, until in _COOLDOWN_GROQ_MODELS.items() if until <= now]:
                _COOLDOWN_GROQ_MODELS.pop(m_expired, None)
            dead_snapshot = set(_DEAD_GROQ_MODELS)
            cooldown_snapshot = dict(_COOLDOWN_GROQ_MODELS)

        with self._models_lock:
            models_snapshot = list(self._groq_models)

        candidates = [
            m for m in models_snapshot
            if m not in dead_snapshot and cooldown_snapshot.get(m, 0.0) <= now
        ]
        if prioritize_fast:
            for fast_model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.1-8b-instant"):
                if fast_model in candidates:
                    candidates.remove(fast_model)
                    candidates.insert(0, fast_model)
            if self.preferred_model and self.preferred_model not in dead_snapshot and cooldown_snapshot.get(self.preferred_model, 0.0) <= now:
                if self.preferred_model in candidates:
                    candidates.remove(self.preferred_model)
                candidates.insert(0, self.preferred_model)
        return candidates

    @staticmethod
    def _is_local_lm_available(host: str = "127.0.0.1", port: int = 1234, timeout: float = 0.15) -> bool:
        """Kiểm tra nhanh cổng LM Studio trước khi gọi để bỏ qua ngay (< 1ms) nếu đã tắt."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def invoke(self, prompt, *args, **kwargs):
        global _CURRENT_KEY_INDEX
        groq_err = None
        local_err = None
        gemini_err = None

        # TẦNG 1 (Engine chính): Ưu tiên gọi trực tiếp Groq LPU ngay từ đầu
        print("[LLM ENGINE] Đang tạo phản hồi qua Groq LPU...")
        candidate_models = self._get_candidate_groq_models(
            prioritize_fast=bool(self.max_output_tokens <= 200 or self.preferred_model)
        )

        for groq_model in candidate_models:
            try:
                groq_client = self._get_groq_client(model_name=groq_model)
                if groq_client is None:
                    continue
                groq_resp = groq_client.invoke(prompt, *args, **kwargs)
                groq_content = getattr(groq_resp, "content", str(groq_resp))
                if groq_content and str(groq_content).strip():
                    if self.max_output_tokens > 200:
                        self._promote_groq_model(groq_model)
                    return groq_resp
            except Exception as g_err:
                groq_err = g_err
                self._handle_groq_error(groq_model, g_err)
                continue

        # TẦNG 2 (Dự phòng 1): Chuyển tiếp sang Local LM Studio (Qwen 4B)
        if not self._is_local_lm_available():
            local_err = ConnectionRefusedError("Local LM Studio (127.0.0.1:1234) is unreachable")
            print("[FAILOVER] Cổng Local LM Studio (127.0.0.1:1234) đóng -> Bỏ qua ngay sang dự phòng Cloud...")
        else:
            try:
                print("[FAILOVER] Groq không khả dụng -> Chuyển sang Local LM Studio (qwen/qwen3.5-4b)...")
                local_resp = self.local_llm.invoke(prompt, *args, **kwargs)
                local_content = getattr(local_resp, "content", str(local_resp))
                if local_content and str(local_content).strip():
                    return local_resp
            except Exception as l_err:
                local_err = l_err

        # TẦNG 2 (Dự phòng 2): Gọi Gemini nếu có key 'AIzaSy' hợp lệ
        valid_gemini_keys = get_all_google_api_keys()
        if valid_gemini_keys:
            print("[FAILOVER] Local LM Studio không khả dụng -> Chuyển sang dự phòng Gemini...")
            num_keys = len(valid_gemini_keys)
            with _GROQ_STATE_LOCK:
                start_idx = _CURRENT_KEY_INDEX % num_keys
                _CURRENT_KEY_INDEX = (start_idx + 1) % num_keys

            for offset in range(num_keys):
                current_idx = (start_idx + offset) % num_keys
                api_key = valid_gemini_keys[current_idx]
                try:
                    client = self._get_cloud_client(api_key)
                    response = client.invoke(prompt, *args, **kwargs)
                    content = getattr(response, "content", str(response))
                    if content and str(content).strip():
                        if offset > 0:
                            with _GROQ_STATE_LOCK:
                                _CURRENT_KEY_INDEX = (current_idx + 1) % num_keys
                        return response
                except Exception as cloud_err:
                    gemini_err = cloud_err
                    continue

        # TẦNG 3: Tất cả đều lỗi -> ném lỗi 429 RESOURCE_EXHAUSTED để app.py hiển thị RATE_LIMIT_MESSAGE
        err_detail = f"Groq: {groq_err} | Local: {local_err} | Gemini: {gemini_err}"
        raise RuntimeError(f"429 RESOURCE_EXHAUSTED: {err_detail}") from (groq_err or local_err or gemini_err)

    def stream(self, prompt, *args, **kwargs):
        global _CURRENT_KEY_INDEX
        groq_err = None
        local_err = None
        gemini_err = None

        # TẦNG 1 (Engine chính): Ưu tiên gọi trực tiếp Groq LPU ngay từ đầu
        print("[LLM ENGINE] Đang tạo phản hồi qua Groq LPU...")
        candidate_models = self._get_candidate_groq_models(prioritize_fast=False)
        for groq_model in candidate_models:
            yielded_groq = False
            try:
                groq_client = self._get_groq_client(model_name=groq_model)
                if groq_client is None:
                    continue
                for chunk in groq_client.stream(prompt, *args, **kwargs):
                    chunk_text = getattr(chunk, "content", str(chunk))
                    if chunk_text:
                        yielded_groq = True
                        yield chunk
                if yielded_groq:
                    self._promote_groq_model(groq_model)
                    return
                continue
            except Exception as g_err:
                groq_err = g_err
                if yielded_groq:
                    yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                    return
                self._handle_groq_error(groq_model, g_err)
                continue

        # TẦNG 2 (Dự phòng 1): Chuyển tiếp sang Local LM Studio (Qwen 4B)
        yielded_local = False
        if not self._is_local_lm_available():
            local_err = ConnectionRefusedError("Local LM Studio (127.0.0.1:1234) is unreachable")
            print("[FAILOVER] Cổng Local LM Studio (127.0.0.1:1234) đóng -> Bỏ qua ngay sang dự phòng Cloud...")
        else:
            try:
                print("[FAILOVER] Groq không khả dụng -> Chuyển sang Local LM Studio (qwen/qwen3.5-4b)...")
                for chunk in self.local_llm.stream(prompt, *args, **kwargs):
                    chunk_text = getattr(chunk, "content", str(chunk))
                    if chunk_text:
                        yielded_local = True
                        yield chunk
                if yielded_local:
                    return
                resp = self.local_llm.invoke(prompt, *args, **kwargs)
                if getattr(resp, "content", ""):
                    yield resp
                    return
            except Exception as l_err:
                local_err = l_err
                if yielded_local:
                    yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                    return

        # TẦNG 2 (Dự phòng 2): Gọi Gemini nếu có key 'AIzaSy' hợp lệ
        valid_gemini_keys = get_all_google_api_keys()
        if valid_gemini_keys:
            print("[FAILOVER] Local LM Studio không khả dụng -> Chuyển sang dự phòng Gemini...")
            num_keys = len(valid_gemini_keys)
            with _GROQ_STATE_LOCK:
                start_idx = _CURRENT_KEY_INDEX % num_keys
                _CURRENT_KEY_INDEX = (start_idx + 1) % num_keys

            for offset in range(num_keys):
                current_idx = (start_idx + offset) % num_keys
                api_key = valid_gemini_keys[current_idx]
                yielded_from_this_key = False
                try:
                    client = self._get_cloud_client(api_key)
                    for chunk in client.stream(prompt, *args, **kwargs):
                        chunk_text = getattr(chunk, "content", str(chunk))
                        if chunk_text:
                            yielded_from_this_key = True
                            if offset > 0:
                                with _GROQ_STATE_LOCK:
                                    _CURRENT_KEY_INDEX = (current_idx + 1) % num_keys
                            yield chunk
                    if yielded_from_this_key:
                        return
                except Exception as cloud_err:
                    gemini_err = cloud_err
                    if not yielded_from_this_key:
                        continue
                    yield f"\n\n{STREAM_INTERRUPTED_NOTICE}"
                    return

        # TẦNG 3: Tất cả đều lỗi -> ném lỗi 429 RESOURCE_EXHAUSTED để app.py hiển thị RATE_LIMIT_MESSAGE
        err_detail = f"Groq: {groq_err} | Local: {local_err} | Gemini: {gemini_err}"
        raise RuntimeError(f"429 RESOURCE_EXHAUSTED: {err_detail}") from (groq_err or local_err or gemini_err)


def get_llm(temperature: float = 0.0, max_output_tokens: int = 2048, preferred_model: str | None = None):
    groq_api_key = get_groq_api_key()
    groq_llm = None
    if groq_api_key:
        groq_llm = ChatGroq(
            api_key=groq_api_key,
            model_name=preferred_model or "openai/gpt-oss-120b",
            temperature=temperature,
            max_tokens=max_output_tokens,
            max_retries=0,
            request_timeout=4.5 if int(max_output_tokens) <= 200 else 6.5
        )

    local_llm = ChatOpenAI(
        base_url="http://127.0.0.1:1234/v1",
        api_key="not-needed",
        model="qwen/qwen3.5-4b",
        temperature=0.0,
        max_tokens=min(800, max_output_tokens),
        max_retries=0,
        request_timeout=8,
        streaming=(max_output_tokens > 200),
        extra_body={"reasoning_effort": "none"}
    )
    return RotatingResilientLLM(
        local_llm=local_llm,
        groq_llm=groq_llm,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        preferred_model=preferred_model
    )


@st.cache_resource(show_spinner=False)
def get_rewriter_llm():
    """Khởi tạo và cache LLM tốc độ cao dành riêng cho bước viết lại câu hỏi nối tiếp."""
    global _GLOBAL_REWRITER_LLM
    if _GLOBAL_REWRITER_LLM is not None:
        return _GLOBAL_REWRITER_LLM
    _GLOBAL_REWRITER_LLM = get_llm(temperature=0.0, max_output_tokens=100, preferred_model="llama-3.1-8b-instant")
    return _GLOBAL_REWRITER_LLM


def rewrite_conversational_query(query: str, chat_history: list | None = None) -> str:
    """
    Viết lại câu hỏi nối tiếp có chứa đại từ/từ nối ngữ cảnh thành câu hỏi độc lập đầy đủ nghĩa.
    Nếu lịch sử trống hoặc câu hỏi đã rõ chủ ngữ/đối tượng, giữ nguyên câu hỏi gốc để không tăng độ trễ.
    """
    if not query or not str(query).strip():
        return ""

    raw_query = re.sub(r"\s+", " ", str(query).strip())
    if not chat_history:
        return raw_query

    valid_history = []
    for msg in chat_history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = str(msg.get("content", "") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if msg.get("is_greeting"):
            if role == "assistant" and valid_history and valid_history[-1][0] == "user":
                valid_history.pop()
            continue
        if role == "assistant":
            c_low = content.lower()
            is_excluded_assistant = bool(
                msg.get("is_refusal")
                or REFUSAL_MESSAGE in content
                or "không được đề cập trong các văn bản quy định" in c_low
                or "ngoài phạm vi dữ liệu quy chế" in c_low
                or "lượng truy cập cao" in c_low
                or "đợi khoảng 30–60 giây" in c_low
                or "phản hồi bị gián đoạn giữa chừng" in c_low
            )
            if is_excluded_assistant:
                if valid_history and valid_history[-1][0] == "user":
                    valid_history.pop()
                continue
        valid_history.append((role, content))

    if valid_history and valid_history[-1][0] == "user" and valid_history[-1][1].strip() == raw_query:
        valid_history = valid_history[:-1]

    if not valid_history:
        return raw_query

    recent_history = valid_history[-6:]
    q_lower = raw_query.lower()

    has_pronoun_no = bool(re.search(r"\bnó\b", q_lower))
    explicit_phrases = [
        "cái đó", "cái này", "mức này", "mức đó", "loại này", "loại đó",
        "khoản này", "quy định này", "trường hợp này", "đối tượng này",
        "phòng này", "phòng đó", "đơn vị này", "đơn vị đó", "ở đó", "bên đó",
        "vậy thì", "vậy còn", "vậy mức", "thế còn", "còn hồ sơ", "còn thủ tục",
        "còn thời gian", "còn điều kiện", "còn mức", "thì sao"
    ]
    has_explicit_marker = (
        has_pronoun_no
        or any(phrase in q_lower for phrase in explicit_phrases)
        or q_lower.startswith(("vậy ", "còn ", "thế "))
    )

    contextual_question_markers = [
        "bao lâu", "như thế nào", "ra sao", "nộp ở đâu", "nộp cho ai",
        "gồm những gì", "bao nhiêu tiền", "mức tiền", "công thức tính",
        "đúng không", "phải không", "tức là", "nghĩa là", "vậy là",
        "như vậy", "được không", "mấy buổi", "bao nhiêu buổi"
    ]
    has_contextual_marker = any(marker in q_lower for marker in contextual_question_markers)

    standalone_subjects = [
        "học bổng", "kkht", "spkt", "miễn giảm học phí", "miễn, giảm học phí",
        "hỗ trợ chi phí học tập", "hoàn trả học phí", "học phí thừa", "qt-sv-04",
        "công tác xã hội", "ctxh", "công tác sinh viên", "kỷ luật", "ban cán sự",
        "quy tắc ứng xử", "an toàn thông tin", "mật khẩu", "nghị quyết",
        "thi hộ", "thi thay", "học thay", "phòng thi", "khiển trách",
        "cảnh cáo", "đình chỉ", "buộc thôi học", "điểm rèn luyện",
        "khóa luận", "tốt nghiệp", "danh hiệu", "xuất sắc", "sinh viên giỏi",
        "khen thưởng", "quy định", "quy chế", "quy trình", "thông báo", "hướng dẫn"
    ]
    has_article_or_section_ref = bool(
        re.search(r"\b(?:điều|khoản|mục|chương|phụ\s+lục|biểu\s+mẫu|mẫu)\s+[ivxlcdm\d]+", q_lower)
    )
    has_standalone_subject = (
        any(subj in q_lower for subj in standalone_subjects)
        or has_article_or_section_ref
    )

    needs_rewrite = has_explicit_marker or (
        (has_contextual_marker or len(q_lower.split()) <= 15) and not has_standalone_subject
    )
    if not needs_rewrite:
        return raw_query

    history_lines = []
    for role, content in recent_history:
        speaker = "Sinh viên" if role == "user" else "Trợ lý"
        snippet = content if role == "user" else content[:350]
        history_lines.append(f"{speaker}: {snippet}")
    history_block = "\n".join(history_lines)

    rewrite_prompt = (
        "Nhiệm vụ: Viết lại câu hỏi mới nhất của sinh viên thành MỘT câu hỏi tra cứu quy chế đại học "
        "độc lập, đầy đủ chủ ngữ/đối tượng (giữ nguyên tên học bổng, mức học bổng, chế độ, quy trình hoặc phòng ban "
        "từ ngữ cảnh hội thoại trước đó nếu câu hỏi dùng đại từ như 'nó', 'cái đó', 'mức này', 'vậy'... ).\n"
        "Quy tắc:\n"
        "- Chỉ trả về duy nhất câu hỏi đã viết lại bằng tiếng Việt, không giải thích, không ngoặc kép.\n"
        "- Giữ nguyên đầy đủ các con số, giả định phép tính của sinh viên trong câu hỏi hiện tại và gắn thêm chủ ngữ/định mức từ lượt hội thoại trước.\n"
        "- Không tự bịa thông tin mới không có trong lịch sử.\n\n"
        f"Lịch sử hội thoại gần nhất:\n{history_block}\n\n"
        f"Câu hỏi hiện tại: {raw_query}\n"
        "Câu hỏi độc lập:"
    )

    try:
        t_rw = time.time()
        rewriter_llm = get_rewriter_llm()
        resp = rewriter_llm.invoke(rewrite_prompt)
        rewritten = getattr(resp, "content", str(resp)).strip()
        rewritten = re.sub(r"^(Câu hỏi độc lập|Câu hỏi viết lại)\s*:\s*", "", rewritten, flags=re.IGNORECASE)
        rewritten = rewritten.strip().strip('"').strip("'").splitlines()[0].strip()
        if rewritten and len(rewritten) >= 5:
            rw_elapsed = round(time.time() - t_rw, 3)
            print(f"[QUERY REWRITE] ({rw_elapsed}s) '{raw_query}' -> '{rewritten}'")
            return rewritten
    except Exception as err:
        print(f"[QUERY REWRITE WARNING] Không thể viết lại câu hỏi: {err}")

    return raw_query


@st.cache_resource(show_spinner=False)
def get_rag_chain():
    """Khởi tạo hoặc trả về chain RAG đã được lưu trong bộ nhớ đệm (singleton + @st.cache_resource)."""
    global _GLOBAL_CHAIN
    if _GLOBAL_CHAIN is not None:
        return _GLOBAL_CHAIN

    vector_db = get_vector_db()
    llm = get_llm()
    get_rewriter_llm()

    system_prompt = (
        "Bạn là trợ lý giải đáp thắc mắc về quy chế và học vụ cho sinh viên VLUTE.\n"
        "NGUYÊN TẮC TRẢ LỜI:\n"
        "1. CHỈ sử dụng thông tin có trong tài liệu quy chế dưới đây để trả lời. Tuyệt đối không tự suy diễn hoặc dùng kiến thức ngoài tài liệu.\n"
        "2. Trả lời đúng trọng tâm và phân biệt rõ bản chất câu hỏi:\n"
        "   - Tách bạch từng hành vi/điều kiện đối với câu hỏi ghép nhiều vế (áp dụng tổng quát cho mọi văn bản quy chế hiện tại và tương lai): Khi sinh viên hỏi câu ghép nhắc đến nhiều hành vi, đối tượng hoặc trường hợp cùng lúc (ví dụ: vừa hỏi hành vi thi hộ vừa hỏi hành vi mang tài liệu vào phòng thi, hoặc hỏi gộp nhiều diện đối tượng/mức quy định), BẮT BUỘC phân tích và trình bày tách riêng từng ý/gạch đầu dòng theo đúng điều khoản hoặc dòng bảng quy định của từng hành vi/đối tượng đó. Tuyệt đối không gộp chung hoặc áp nhầm khung xử lý/định mức của mục này sang mục khác; nếu một ý thuộc quy định có trong tài liệu còn ý kia thuộc văn bản khác hoặc chưa được đề cập trong đoạn trích hiện tại thì phải tách bạch và nêu rõ cho từng ý.\n"
        "   - Phân biệt rạch ròi giữa 'Miễn giảm học phí' (chế độ giảm trừ tiền học) và 'Trợ cấp xã hội / Hỗ trợ chi phí học tập' (các khoản chi trả tiền mặt/sinh hoạt phí).\n"
        "   - Nếu người dùng hỏi về 'trợ cấp xã hội' hoặc 'hỗ trợ chi phí học tập' mà tài liệu chỉ quy định về 'miễn giảm học phí' (hoặc chỉ nhắc đến giấy tờ 'Quyết định trợ cấp xã hội' như một thành phần hồ sơ minh chứng), hãy làm rõ điểm này: nêu rõ đối tượng được miễn giảm học phí theo quy định, đồng thời chỉ rõ văn bản hiện tại chưa quy định riêng về khoản tiền trợ cấp xã hội độc lập.\n"
        "   - Đối soát toán học & định lượng tổng quát (áp dụng cho mọi văn bản hiện tại và tương lai như ngày CTXH, số tín chỉ, điểm trung bình, tỷ lệ miễn giảm, mức học bổng, thời hạn xử lý...): Bất cứ khi nào sinh viên đưa ra một phép tính, con số quy đổi hoặc giả định cụ thể, PHẢI kiểm tra phép nhân/chia/so sánh đó đối chiếu với định mức trong văn bản và nêu rõ kết quả đúng/sai bằng phép tính cụ thể (ví dụ: 12 buổi × 0,5 ngày = 6 ngày, chưa đủ 12 ngày; nếu tính theo mức 0,5 ngày/buổi thì cần 12 : 0,5 = 24 buổi mới đủ 12 ngày) trước khi giải thích các trường hợp ngoại lệ hoặc các mức quy đổi khác nhau trong quy định.\n"
        "   - Khi sinh viên hỏi 'có nợ môn hoặc nợ học phí thì được xét học bổng không?': Căn cứ Điều 17 (yêu cầu tối thiểu 17 tín chỉ, không có học phần nào dưới điểm C) và Điều 1 (hoàn thành nghĩa vụ học phí) để trả lời rõ ràng: Sinh viên nợ môn (dưới điểm C) hoặc chưa hoàn thành học phí sẽ KHÔNG đủ điều kiện xét cấp học bổng khuyến khích học tập. Tuyệt đối không trả về thông báo từ chối ngoài phạm vi dữ liệu đối với câu hỏi này.\n"
        "   - Khi sinh viên hỏi về điều kiện xét học bổng khuyến khích học tập (tín chỉ, điểm TBC, hoặc điểm rèn luyện theo Điều 17): Luôn nêu đầy đủ cả 3 tiêu chuẩn cốt lõi tại Điều 17 gồm: (1) Đăng ký tối thiểu 17 tín chỉ, (2) Điểm TBC học kỳ đạt từ 2,5 trở lên theo thang 4,0 (riêng Học bổng KKHT Mức 1 / SPKT yêu cầu từ 3,2 trở lên) và không có học phần dưới điểm C, (3) Xếp loại rèn luyện đạt từ loại Khá trở lên (riêng Mức 1 / SPKT yêu cầu từ loại Tốt trở lên).\n"
        "   - Khi sinh viên hỏi về mức tiền hoặc cách tính Học bổng KKHT Mức 1 (Học bổng SPKT) tại Điều 18: Nêu rõ công thức 'Học bổng KKHT Mức 1 (Học bổng SPKT) = Đơn giá học phí × 17 TC', trong đó 'Đơn giá học phí = Đơn giá học phí theo khối ngành VII (hệ đại trà)'.\n"
        "   - Cấm tự đặt ví dụ giả định cho mọi văn bản quy chế: Chỉ nêu đúng công thức, tỷ lệ và con số được quy định nguyên văn trong tài liệu; tuyệt đối KHÔNG tự đặt ví dụ tính thử bằng số tiền, điểm số hay định mức giả định (như tự lấy đơn giá tín chỉ giả định để nhân thử) khi sinh viên không đưa ra con số cụ thể để tính, giúp câu trả lời cô đọng và chuẩn xác cho mọi quy chế hiện tại lẫn về sau.\n"
        "   - Khi đọc Bảng quy đổi ngày CTXH (Điều 8 Quyết định 55, Trang 9–10) bị tách cột qua 2 trang liên tiếp: đối chiếu theo mã số tương ứng gồm Mùa hè xanh (001101 - tham gia các đội hình chuyên), Tiếp sức mùa thi (001301), Tiếp sức tân sinh viên (001501) đều quy đổi 1 ngày CTXH / ngày tham gia (tối thiểu 5 giờ làm việc hoặc 1 ca trực theo phân công); Trực tiếp hiến máu tình nguyện (001202) quy đổi 1 ngày CTXH (theo Giấy xác nhận hiến máu); Hỗ trợ tổ chức hoạt động hiến máu tình nguyện (001201) quy đổi 0,5 ngày CTXH (theo Bảng phân công nhiệm vụ hỗ trợ).\n"
        "   - Khi đọc Phụ lục Khung xử lý kỷ luật sinh viên (Quyết định 1079, Trang 25–34, 4 cột mức kỷ luật theo thứ tự: Khiển trách | Cảnh cáo | Đình chỉ có thời hạn | Buộc thôi học): mục 4 (Học thay hoặc nhờ người khác học thay) xử lý từ Khiển trách đến Buộc thôi học tùy mức độ; mục 5 (Thi, kiểm tra thay hoặc nhờ thi, kiểm tra thay; làm thay, nhờ làm hoặc sao chép tiểu luận, đồ án, khóa luận tốt nghiệp) xử lý Đình chỉ học tập có thời hạn (vi phạm lần 1) và Buộc thôi học (vi phạm lần 2); mục 6 (Tổ chức học, thi, kiểm tra thay) xử lý Buộc thôi học ngay từ lần 1 (nếu nghiêm trọng giao cơ quan chức năng xử lý theo pháp luật).\n"
        "   - Khi sinh viên hỏi về quyền lợi điểm rèn luyện của Ban cán sự lớp / Cán bộ lớp / Đoàn – Hội, phải đối chiếu quy định trong tài liệu để nêu rõ số điểm rèn luyện được cộng cụ thể theo từng chức danh và mức độ hoàn thành nhiệm vụ (nếu văn bản có quy định) thay vì chỉ trả lời chung chung.\n"
        "3. Phong cách trả lời:\n"
        "   - Tuyệt đối KHÔNG dùng các cụm từ máy móc làm lộ kỹ thuật prompt như 'Dựa trên ngữ cảnh được cung cấp', 'Theo ngữ cảnh được cung cấp', 'Theo ngữ cảnh', 'Trong đoạn trích', 'Tài liệu cung cấp', 'Dựa vào đoạn văn bản trên', 'Trong văn bản được trích dẫn', 'Theo văn bản được trích dẫn', 'tài liệu được trích dẫn'; thay vào đó diễn đạt tự nhiên như cán bộ tư vấn học vụ (ví dụ: 'Theo quy định hiện hành của Nhà trường...', 'Theo quy định tại VLUTE...', hoặc đi thẳng vào nội dung trả lời).\n"
        "   - Đi thẳng vào câu hỏi, diễn đạt tự nhiên, rõ ràng, súc tích.\n"
        "   - KHÔNG cần trích dẫn rườm rà số hiệu quyết định hay điều khoản trừ khi câu hỏi yêu cầu cụ thể.\n"
        "   - Trình bày dạng gạch đầu dòng ngắn gọn để sinh viên nắm bắt thông tin nhanh nhất.\n"
        "   - Tuyệt đối KHÔNG dùng ký hiệu toán học LaTeX như '\\[ ... \\]', '\\( ... \\)', '$$ ... $$', '\\text', '\\frac', '\\div', '\\times'. Luôn viết phép tính bằng chữ và số thuần túy rõ ràng (ví dụ: 15 - 3 = 12 ngày còn thiếu; 12 : 0,5 = 24 buổi).\n"
        f"4. CHỈ trả về hằng số REFUSAL_MESSAGE duy nhất (không giải thích thêm) khi câu hỏi hoàn toàn nằm ngoài phạm vi các văn bản quy chế tham khảo (ví dụ: hỏi giá phòng ký túc xá, điểm chuẩn tuyển sinh, tuyến xe buýt, học phí 1 tín chỉ...). Nếu tài liệu quy chế đã có quy định liên quan đến chủ đề câu hỏi, tuyệt đối KHÔNG trả về REFUSAL_MESSAGE:\n{REFUSAL_MESSAGE}\n\n"
        "Nội dung quy chế tham khảo:\n{context}\n\n"
        "Câu hỏi: {input}\n\n"
        "Trả lời:"
    )

    prompt = ChatPromptTemplate.from_template(system_prompt)
    _GLOBAL_CHAIN = SmartRAGChain(vector_db, llm, prompt)
    return _GLOBAL_CHAIN
