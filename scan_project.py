import os
import ast
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
IGNORE_DIRS = {".venv", "__pycache__", ".git", "chroma_db"}
MAIN_SOURCE_FILES = ["rag.py", "app.py", "ingest.py"]
OUTPUT_FILE = os.path.join(ROOT_DIR, "project_overview.txt")


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB ({size_bytes / 1024:.1f} KB)"
    return f"{size_bytes / 1024:.2f} KB ({size_bytes} bytes)"


def build_directory_tree(root_path: str) -> list[str]:
    lines = [f"📁 {os.path.basename(root_path)}/ ({root_path})"]

    def _walk(current_path: str, prefix: str = ""):
        try:
            entries = sorted(
                os.listdir(current_path),
                key=lambda x: (not os.path.isdir(os.path.join(current_path, x)), x.lower()),
            )
        except PermissionError:
            return

        filtered_entries = [e for e in entries if e not in IGNORE_DIRS]
        for idx, entry in enumerate(filtered_entries):
            full_path = os.path.join(current_path, entry)
            is_last = idx == len(filtered_entries) - 1
            connector = "└── " if is_last else "├── "
            if os.path.isdir(full_path):
                lines.append(f"{prefix}{connector}📂 {entry}/")
                extension = "    " if is_last else "│   "
                _walk(full_path, prefix + extension)
            else:
                size_str = format_size(os.path.getsize(full_path))
                lines.append(f"{prefix}{connector}📄 {entry} [{size_str}]")

    _walk(root_path)
    return lines


def scan_data_directory(root_path: str) -> list[str]:
    data_dir = os.path.join(root_path, "data")
    lines = []
    if not os.path.exists(data_dir):
        lines.append("⚠️ Thư mục data/ không tồn tại.")
        return lines

    files = sorted(
        [f for f in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, f))]
    )
    total_size = 0
    lines.append(f"Tổng số file trong data/: {len(files)}")
    lines.append("-" * 80)
    lines.append(f"{'STT':<5} | {'Tên file chính xác':<38} | {'Định dạng':<10} | {'Dung lượng'}")
    lines.append("-" * 80)

    for idx, fname in enumerate(files, 1):
        fpath = os.path.join(data_dir, fname)
        fsize = os.path.getsize(fpath)
        total_size += fsize
        ext = os.path.splitext(fname)[1].lower() or "N/A"
        lines.append(f"{idx:<5} | {fname:<38} | {ext:<10} | {format_size(fsize)}")

    lines.append("-" * 80)
    lines.append(f"Tổng dung lượng thư mục data/: {format_size(total_size)}")
    return lines


def inspect_source_files(root_path: str) -> list[str]:
    lines = []
    for fname in MAIN_SOURCE_FILES:
        fpath = os.path.join(root_path, fname)
        lines.append("=" * 80)
        if not os.path.exists(fpath):
            lines.append(f"📄 File: {fname} -> KHÔNG TÌM THẤY")
            continue

        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            file_lines = content.splitlines()

        total_lines = len(file_lines)
        non_empty_lines = sum(1 for l in file_lines if l.strip())
        fsize = os.path.getsize(fpath)

        lines.append(f"📄 File: {fname}")
        lines.append(f"   - Dung lượng     : {format_size(fsize)}")
        lines.append(f"   - Tổng số dòng   : {total_lines} dòng (Dòng có nội dung: {non_empty_lines} dòng)")

        try:
            tree = ast.parse(content, filename=fname)
            classes = []
            functions = []

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [
                        n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    classes.append((node.name, node.lineno, methods))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append((node.name, node.lineno))

            lines.append(f"   - Các Class chính ({len(classes)}):")
            if classes:
                for cname, lineno, methods in classes:
                    method_str = ", ".join(f"{m}()" for m in methods) if methods else "Không có method"
                    lines.append(f"       + class {cname} (Dòng {lineno}) -> Methods: {method_str}")
            else:
                lines.append("       + (Không có class)")

            lines.append(f"   - Các Hàm (Functions) cấp module ({len(functions)}):")
            if functions:
                for fn_name, lineno in functions:
                    lines.append(f"       + def {fn_name}() (Dòng {lineno})")
            else:
                lines.append("       + (Không có hàm cấp module)")

        except Exception as e:
            lines.append(f"   - ⚠️ Lỗi phân tích AST: {e}")

    lines.append("=" * 80)
    return lines


def main():
    report = []
    report.append("=" * 80)
    report.append("BÁO CÁO TỔNG QUAN CẤU TRÚC DỰ ÁN VLUTEBOT")
    report.append(f"Thời gian xuất báo cáo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)
    report.append("")

    report.append("1. CÂY THƯ MỤC DỰ ÁN (Đã bỏ qua: .venv, __pycache__, .git, chroma_db)")
    report.append("-" * 80)
    report.extend(build_directory_tree(ROOT_DIR))
    report.append("")

    report.append("2. CHI TIẾT THƯ MỤC DỮ LIỆU (data/)")
    report.append("-" * 80)
    report.extend(scan_data_directory(ROOT_DIR))
    report.append("")

    report.append("3. PHÂN TÍCH CÁC FILE MÃ NGUỒN CHÍNH (rag.py, app.py, ingest.py)")
    report.extend(inspect_source_files(ROOT_DIR))
    report.append("")

    full_text = "\n".join(report)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(full_text)

    print(full_text)
    print(f"\n✅ Đã xuất báo cáo thành công ra file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
