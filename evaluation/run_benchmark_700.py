"""
Benchmark đánh giá toàn diện Tầng 1 (700 câu hỏi = 100 câu/văn bản × 7 văn bản)
cho hệ thống truy xuất Hybrid Search và định tuyến phòng ban của VLUTEBOT.

- Không chỉnh sửa app.py hay rag.py.
- Sinh bộ câu hỏi tại: evaluation/benchmark_700_per_doc.json
- Xuất kết quả chi tiết tại: evaluation/benchmark_700_results.csv
"""

from __future__ import annotations

import ast
import csv
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag import SmartRAGChain, get_bm25_index, get_vector_db, load_departments_config


def load_app_routing_helpers():
    """Trích xuất nguyên bản các hàm định tuyến từ app.py qua AST mà không chạy UI Streamlit."""
    app_path = ROOT_DIR / "app.py"
    src = app_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = {
        "SVG_PHONE_ICON",
        "GREETING_KEYWORDS",
        "is_greeting",
        "_strip_accents",
        "_build_contact_footer_html",
        "get_contact_footer",
        "check_department_inquiry",
        "is_refusal_answer",
    }
    env = {
        "json": json,
        "os": os,
        "re": re,
        "unicodedata": unicodedata,
        "load_departments_config": load_departments_config,
    }
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            name = node.name
            node.decorator_list = []
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    name = target.id
                    break
        if name:
            mod = ast.Module(body=[node], type_ignores=[])
            exec(compile(mod, str(app_path), "exec"), env)
    return env


# ---------------------------------------------------------------------------
# 700 câu hỏi đa dạng (100 câu/văn bản), bám sát điều khoản, số liệu, bảng biểu
# và các cách diễn đạt tự nhiên của sinh viên VLUTE.
# ---------------------------------------------------------------------------
QUESTIONS_BY_DOC: dict[str, dict] = {
    "xet_cap_hoc_bong.pdf": {
        "expected_dept": "Phòng Công tác Sinh viên (VLUTE)",
        "questions": [
            # QĐ ban hành, phạm vi, nguyên tắc, hội đồng (1-20)
            ("QĐ ban hành", "direct", "Quyết định số bao nhiêu ban hành Quy định xét thi đua, khen thưởng, học bổng và trợ cấp học tập hiện hành?"),
            ("Hiệu lực", "direct", "Quy định xét khen thưởng và học bổng ban hành ngày 26/02/2025 thay thế cho những quyết định cũ nào?"),
            ("Phạm vi", "direct", "Quy định xét thi đua, khen thưởng, học bổng và trợ cấp học tập áp dụng cho hệ đào tạo nào tại VLUTE?"),
            ("Nghĩa vụ học phí", "paraphrase", "Sinh viên còn nợ học phí có được xét cấp học bổng khuyến khích học tập hoặc khen thưởng không?"),
            ("Nguồn quỹ", "direct", "Quỹ khen thưởng, học bổng và trợ cấp học tập của trường được phân bổ từ những nguồn nào?"),
            ("Phân bổ quỹ", "direct", "Căn cứ vào yếu tố nào để phân bổ quỹ học bổng cho từng khoa, từng khóa học và từng ngành?"),
            ("Mẫu hình SV", "direct", "Năm phẩm chất trong mẫu hình sinh viên VLUTE nêu tại Điều 3 Quy định xét thi đua là gì?"),
            ("Nguyên tắc thưởng", "paraphrase", "Nếu một tập thể hoặc cá nhân đạt nhiều thành tích trong cùng một đợt thì nhận phần thưởng ra sao?"),
            ("Tránh trùng thưởng", "paraphrase", "Có được dùng quỹ thưởng để trao thưởng trùng lặp cho cùng một thành tích không?"),
            ("Loại học bổng", "direct", "Theo Điều 4, nhà trường có tất cả bao nhiêu loại học bổng và trợ cấp học tập cho sinh viên chính quy?"),
            ("Mục đích KKHT", "direct", "Học bổng khuyến khích học tập được xét cấp dựa trên kết quả của khoảng thời gian nào?"),
            ("Mục tiêu SPKT", "direct", "Học bổng Sư phạm kỹ thuật tương đương với mức nào của học bổng khuyến khích học tập?"),
            ("Đối tượng HB vượt khó", "paraphrase", "Học bổng vượt khó dành cho nhóm sinh viên nào và nhằm mục đích gì?"),
            ("Trợ cấp học tập", "direct", "Những nhóm sinh viên nào thuộc diện xét trợ cấp học tập dành cho hộ nghèo, khuyết tật, mồ côi chưa đủ điều kiện học bổng?"),
            ("Thành lập Hội đồng", "direct", "Đơn vị nào tham mưu thành lập Hội đồng xét thi đua, khen thưởng, học bổng trình Hiệu trưởng phê duyệt?"),
            ("Chủ tịch Hội đồng", "direct", "Ai giữ vai trò Chủ tịch và Thường trực Hội đồng xét thi đua, khen thưởng, học bổng?"),
            ("Thư ký Hội đồng", "direct", "Thư ký Hội đồng xét thi đua, khen thưởng, học bổng là nhân sự thuộc đơn vị nào?"),
            ("Trách nhiệm CTSV", "direct", "Phòng Công tác sinh viên đảm nhận những nhiệm vụ gì trong công tác xét thi đua khen thưởng?"),
            ("Trách nhiệm đề xuất", "paraphrase", "Các Khoa, Bộ môn, Đoàn trường muốn đề xuất khen thưởng sinh viên tiêu biểu thì gửi qua đơn vị nào?"),
            ("Trách nhiệm KHTC", "direct", "Phòng Kế hoạch tài chính phối hợp với đơn vị nào để lập dự trù kinh phí xét cấp học bổng trình Hội đồng Trường?"),
            # Danh hiệu khen thưởng & tiêu chuẩn (21-42)
            ("Danh hiệu cá nhân", "direct", "Khen thưởng định kỳ theo học kỳ và năm học gồm những danh hiệu cá nhân nào?"),
            ("Danh hiệu thủ khoa", "direct", "Nhà trường có những danh hiệu khen thưởng thủ khoa đầu khóa nào?"),
            ("Danh hiệu tập thể", "direct", "Khen thưởng định kỳ dành cho tập thể lớp gồm hai danh hiệu nào?"),
            ("SV Xuất sắc", "paraphrase", "Điều kiện về học tập và rèn luyện để đạt danh hiệu Sinh viên Xuất sắc theo học kỳ, năm học là gì?"),
            ("SV Giỏi", "paraphrase", "Sinh viên muốn đạt danh hiệu Sinh viên Giỏi trong năm học cần xếp loại học tập và rèn luyện mức nào?"),
            ("Loại trừ khen thưởng", "paraphrase", "Sinh viên bị nợ học phần hoặc học lực Khá có được xét khen thưởng định kỳ cuối kỳ không?"),
            ("Tập thể lớp Xuất sắc", "direct", "Tiêu chuẩn tỷ lệ sinh viên học lực Giỏi trở lên và sĩ số tối thiểu để đạt danh hiệu Tập thể lớp Xuất sắc là bao nhiêu?"),
            ("Kỷ luật lớp XS", "paraphrase", "Lớp có sinh viên rèn luyện kém hoặc bị kỷ luật cảnh cáo có được công nhận Tập thể lớp Xuất sắc không?"),
            ("Tập thể lớp Tiên tiến", "direct", "Danh hiệu Tập thể lớp Tiên tiến yêu cầu tối thiểu bao nhiêu phần trăm sinh viên học lực Khá trở lên và dưới yếu bao nhiêu?"),
            ("Hoạt động lớp TT", "paraphrase", "Ngoài điểm số và sĩ số tối thiểu 20 người, Tập thể lớp Tiên tiến cần đạt điều kiện phong trào nào?"),
            ("Xuất sắc toàn khóa", "direct", "Để được khen thưởng danh hiệu Sinh viên Xuất sắc toàn khóa, điểm rèn luyện tối thiểu phải đạt bao nhiêu điểm?"),
            ("Chậm tiến độ toàn khóa", "paraphrase", "Sinh viên học chậm tiến độ hoặc từng bị kỷ luật có được xét Sinh viên Xuất sắc toàn khóa không?"),
            ("Thủ khoa đầu khóa", "direct", "Tiêu chuẩn xét Thủ khoa Trường và Thủ khoa Khoa chuyên môn căn cứ vào loại điểm nào?"),
            ("Điểm ưu tiên thủ khoa", "paraphrase", "Khi xét thưởng Thủ khoa đầu khóa, điểm thi THPT Quốc gia có được cộng điểm ưu tiên hoặc nhân hệ số không?"),
            ("Thủ khoa Khoa", "direct", "Danh hiệu Thủ khoa Khoa chuyên môn được xét theo từng ngành riêng lẻ hay xét chung tất cả các ngành trong Khoa?"),
            ("Giải quốc tế", "direct", "Những kỳ thi cấp quốc tế, khu vực nào được xét khen thưởng thành tích khác theo Điều 11?"),
            ("Giải phong trào", "paraphrase", "Sinh viên đóng góp tích cực phong trào Đoàn, Hội cần nộp giấy tờ gì để xét khen thưởng thành tích khác?"),
            ("Thí sinh DTTS đạt giải", "direct", "Sinh viên dân tộc thiểu số hoặc khuyết tật đạt giải các kỳ thi khu vực, quốc gia được đề xuất mức thưởng như thế nào?"),
            ("Mức thưởng HK lớp", "direct", "Định mức tiền thưởng cho Tập thể lớp Xuất sắc và Tập thể lớp Tiên tiến trong học kỳ là bao nhiêu đồng?"),
            ("Mức thưởng HK cá nhân", "direct", "Sinh viên Xuất sắc trong một học kỳ được thưởng bao nhiêu tiền theo Điều 12?"),
            ("Mức thưởng năm học", "direct", "Định mức khen thưởng năm học cho Tập thể lớp Xuất sắc, Tập thể lớp Tiên tiến và Sinh viên Xuất sắc là bao nhiêu?"),
            ("Mức thưởng Thủ khoa", "direct", "Sinh viên đạt danh hiệu Thủ khoa Trường và Thủ khoa Khoa chuyên môn được thưởng số tiền bao nhiêu?"),
            # Mức thưởng toàn khóa, quy trình khen thưởng & Học bổng KKHT/SPKT (43-76)
            ("Thưởng toàn khóa", "direct", "Tiền thưởng cho danh hiệu Sinh viên Xuất sắc toàn khóa là bao nhiêu tiền mỗi sinh viên?"),
            ("Quy trình khen thưởng kỳ", "direct", "Ai là người lập hồ sơ gửi thành viên Hội đồng rà soát trong quy trình xét khen thưởng định kỳ?"),
            ("Quy trình toàn khóa", "direct", "Phòng nào chủ trì phối hợp với Phòng CTSV rà soát và trình Hiệu trưởng quyết định khen thưởng Sinh viên Xuất sắc toàn khóa?"),
            ("Quy trình khen thưởng giải", "paraphrase", "Khi sinh viên đạt giải cuộc thi quốc gia hoặc cấp tỉnh, đơn vị nào lập danh sách ban đầu gửi Phòng CTSV?"),
            ("Hệ đại trà SPKT", "direct", "Học bổng Sư phạm kỹ thuật (SPKT) áp dụng cho đối tượng sinh viên đại học thuộc hệ nào của Trường?"),
            ("Loại trừ NĐ 116", "paraphrase", "Sinh viên đang hưởng chế độ theo Nghị định 116/2020/NĐ-CP có được xét nhận học bổng mức 1 (học bổng SPKT) không?"),
            ("Tỷ lệ quỹ Mức 1", "direct", "Học bổng KKHT Mức 1 (Học bổng SPKT) chiếm tối đa bao nhiêu phần trăm tổng quỹ học bổng mỗi đợt xét?"),
            ("Đơn xét Mức 1", "paraphrase", "Muốn nhận học bổng KKHT Mức 1 (học bổng SPKT) thì sinh viên có bắt buộc phải nộp đơn xét học bổng SPKT không?"),
            ("Số tín chỉ tối thiểu", "direct", "Để đủ điều kiện xét học bổng khuyến khích học tập, sinh viên phải đăng ký tối thiểu bao nhiêu tín chỉ trong học kỳ chính?"),
            ("Tín chỉ học kỳ đầu", "paraphrase", "Yêu cầu đăng ký tối thiểu 17 tín chỉ để xét học bổng có áp dụng cho sinh viên học kỳ đầu khóa không?"),
            ("Tín chỉ loại trừ", "paraphrase", "Các học phần học lại, học cải thiện, giáo dục quốc phòng an ninh và bằng đại học thứ hai có được tính vào 17 tín chỉ xét học bổng không?"),
            ("GPA xét KKHT", "direct", "Điểm trung bình chung học kỳ tối thiểu theo thang điểm 4,0 để xét học bổng KKHT thông thường là bao nhiêu?"),
            ("Điểm liệt môn", "paraphrase", "Nếu có một học phần bị điểm dưới C (như điểm D) thì có được xét cấp học bổng khuyến khích học tập không?"),
            ("GPA Mức 1 SPKT", "direct", "Điểm trung bình chung học kỳ tối thiểu để đạt Học bổng KKHT Mức 1 (Học bổng SPKT) là mấy chấm?"),
            ("Điểm thi lần 1", "paraphrase", "Điểm trung bình chung học kỳ dùng để xét học bổng KKHT tính theo điểm thi lần mấy?"),
            ("Điểm rèn luyện HB", "direct", "Điều kiện xếp loại rèn luyện để xét học bổng KKHT nói chung và học bổng Mức 1 (SPKT) khác nhau thế nào?"),
            ("Kỷ luật HB", "paraphrase", "Sinh viên bị kỷ luật từ mức khiển trách trở lên có được xét cấp học bổng KKHT không?"),
            ("Cam kết 3 tín chỉ SPKT", "paraphrase", "Sau khi đã nhận học bổng SPKT, học kỳ chính tiếp theo sinh viên phải đăng ký tối thiểu mấy tín chỉ học phần SPKT?"),
            ("Vi phạm cam kết SPKT", "paraphrase", "Nếu nhận học bổng SPKT xong mà kỳ sau không đăng ký đủ 3 tín chỉ học phần SPKT thì hậu quả ra sao?"),
            ("Bảng ma trận loại HB", "direct", "Sinh viên có học lực Xuất sắc nhưng rèn luyện loại Khá thì được xếp loại học bổng KKHT gì?"),
            ("Ma trận Giỏi Xuất sắc", "paraphrase", "Nếu kết quả học tập đạt loại Giỏi còn rèn luyện đạt loại Xuất sắc thì xếp loại học bổng KKHT nào?"),
            ("Ma trận Giỏi Tốt", "paraphrase", "Học lực loại Xuất sắc kết hợp rèn luyện loại Tốt được xếp vào loại học bổng khuyến khích học tập nào?"),
            ("Công thức Mức 1", "direct", "Học bổng KKHT Mức 1 (Học bổng SPKT) được tính bằng đơn giá học phí khối ngành nào nhân với bao nhiêu tín chỉ?"),
            ("Công thức Mức 2 3 4", "direct", "Tỷ lệ tính tiền học bổng KKHT Mức 2, Mức 3 và Mức 4 so với Mức 1 lần lượt bằng bao nhiêu?"),
            ("Thứ tự ưu tiên đồng hạng", "direct", "Khi xét học bổng KKHT cho các sinh viên có cùng loại học bổng, thứ tự ưu tiên xét từ trên xuống dưới gồm những tiêu chí nào?"),
            ("Hết quỹ đồng điểm", "paraphrase", "Nếu nhiều sinh viên có cùng điểm học tập và rèn luyện mà quỹ học bổng của khoa không đủ chia hết thì hội đồng xử lý thế nào?"),
            ("Quy trình Bước 1 HB", "direct", "Trong quy trình xét học bổng SPKT, ai thu đơn đề nghị của sinh viên trước khi gửi Phòng Đào tạo?"),
            ("Quy trình Bước 2 HB", "direct", "Phòng Công tác sinh viên lập danh sách dự kiến cấp học bổng KKHT vào thời điểm nào của học kỳ?"),
            ("Quy trình Bước 3 HB", "direct", "Sau khi Hội đồng họp xét học bổng KKHT, phòng ban nào căn cứ quyết định đã duyệt để chi trả tiền cho sinh viên?"),
            ("Xác nhận đơn SPKT", "paraphrase", "Cơ quan nào kiểm tra kết quả học tập đủ điều kiện xin xét học bổng SPKT rồi chuyển danh sách sang Phòng CTSV?"),
            ("Phân bổ theo tỷ lệ SV", "direct", "Bước 2 trong phương pháp phân bổ chỉ tiêu học bổng phân chia quỹ cho các ngành và khóa theo cơ sở nào?"),
            ("Học bổng Mức 4 Khá", "paraphrase", "Sinh viên học lực Khá và rèn luyện Khá có thể được nhận mức học bổng KKHT nào và hệ số nhân bao nhiêu?"),
            ("Rèn luyện Tốt học lực Xuất sắc", "paraphrase", "Để nhận học bổng KKHT Loại Xuất sắc (Mức 2) cần đạt xếp loại học tập và rèn luyện tối thiểu mức nào?"),
            ("Học cải thiện tín chỉ", "paraphrase", "Em đăng ký 18 tín chỉ nhưng trong đó có 3 tín chỉ học cải thiện thì có đủ chuẩn 17 tín chỉ xét học bổng không?"),
            # Trợ cấp học tập, Học bổng DN & Vượt khó (77-100)
            ("4 nhóm trợ cấp HT", "direct", "Theo Điều 21, bốn nhóm đối tượng được xét hưởng trợ cấp học tập gồm những đối tượng nào?"),
            ("Mồ côi trợ cấp", "direct", "Sinh viên mồ côi cả cha lẫn mẹ muốn hưởng trợ cấp học tập cần đáp ứng thêm điều kiện gì về người đỡ đầu và chu cấp?"),
            ("Tàn tật 41%", "direct", "Sinh viên là người tàn tật phải có tỷ lệ suy giảm khả năng lao động tối thiểu bao nhiêu phần trăm để hưởng trợ cấp học tập?"),
            ("Mức tiền trợ cấp 140k", "direct", "Mức trợ cấp học tập 140.000 đồng/tháng được cấp cho đối tượng sinh viên nào?"),
            ("Mức tiền trợ cấp 100k", "direct", "Những đối tượng nào được hưởng mức trợ cấp học tập 100.000 đồng/tháng?"),
            ("Số tháng trợ cấp", "direct", "Trợ cấp học tập tại Điều 22 được cấp bao nhiêu tháng mỗi năm và chia thành mấy đợt mỗi học kỳ?"),
            ("Hồ sơ trợ cấp DTTS", "direct", "Sinh viên dân tộc thiểu số ở vùng cao ĐBKK cần nộp giấy tờ gì để chứng minh thời gian cư trú ít nhất 3 năm?"),
            ("Hồ sơ trợ cấp mồ côi", "direct", "Giấy tờ chứng minh hoàn cảnh cho sinh viên mồ côi cả cha lẫn mẹ xin trợ cấp học tập gồm những gì?"),
            ("Hồ sơ trợ cấp tàn tật", "direct", "Sinh viên khuyết tật suy giảm lao động từ 41% trở lên nộp giấy tờ y tế và xác nhận nào để xin trợ cấp học tập?"),
            ("Hồ sơ trợ cấp hộ nghèo", "direct", "Sinh viên thuộc hộ gia đình nghèo khi làm hồ sơ xin trợ cấp học tập theo Điều 23 cần nộp giấy tờ gì?"),
            ("Giáo viên quản lý trợ cấp", "direct", "Ai triển khai và tổng hợp đơn xin trợ cấp học tập (Phụ lục 1) gửi về thư ký hội đồng tại Phòng CTSV?"),
            ("Cam kết bồi thường trợ cấp", "paraphrase", "Theo mẫu Đơn xin hưởng trợ cấp học tập (Phụ lục 1), nếu sinh viên tự ý nghỉ học thì phải chịu trách nhiệm gì?"),
            ("2 dạng HB doanh nghiệp", "direct", "Học bổng do doanh nghiệp tài trợ được phân thành hai trường hợp xét cấp nào?"),
            ("Điều kiện HB DN ủy quyền", "direct", "Khi doanh nghiệp ủy quyền cho Nhà trường xét cấp học bổng, sinh viên phải đạt điều kiện học tập, rèn luyện và kỷ luật ra sao?"),
            ("Quỹ HB doanh nghiệp", "direct", "Mức học bổng và số suất học bổng do doanh nghiệp tài trợ được xác định căn cứ vào đâu?"),
            ("Thẩm quyền Hội đồng HB DN", "direct", "Thành phần Hội đồng xét cấp học bổng do doanh nghiệp tài trợ gồm những ai?"),
            ("Vai trò Khoa HB DN", "paraphrase", "Đơn vị nào rà soát và lập biên bản họp Khoa đề xuất sinh viên nhận học bổng doanh nghiệp gửi Phòng CTSV?"),
            ("Điều kiện HB vượt khó", "direct", "Sinh viên muốn xin xét cấp học bổng vượt khó theo Điều 32 cần đáp ứng điều kiện và chuẩn bị giấy tờ gì?"),
            ("Nguồn quỹ HB vượt khó", "direct", "Quỹ học bổng vượt khó cho sinh viên được trích từ nguồn nào và ai quyết định mức học bổng?"),
            ("Thẩm quyền Hội đồng vượt khó", "direct", "Hội đồng xét cấp học bổng vượt khó cho sinh viên do đơn vị nào tham mưu thành lập?"),
            ("Quy trình Khoa vượt khó", "paraphrase", "Ai chịu trách nhiệm rà soát, xác minh hoàn cảnh và họp lập biên bản xét học bổng vượt khó trước khi gửi Phòng CTSV?"),
            ("Cấp phát vượt khó", "direct", "Phòng ban nào thực hiện chi trả tiền học bổng doanh nghiệp và học bổng vượt khó sau khi Hiệu trưởng ký quyết định?"),
            ("Phân công tổng hợp KQ", "direct", "Theo Điều 36, phòng ban nào thống kê số lượng sinh viên thuộc diện xét cấp học bổng theo từng ngành, từng khóa?"),
            ("Sửa đổi quy định HB", "paraphrase", "Nếu phát sinh vướng mắc cần bổ sung Quy định xét khen thưởng và học bổng, các đơn vị báo cáo Hiệu trưởng thông qua phòng nào?"),
        ],
    },
    "quy_dinh_mien_giam_hoc_phi.pdf": {
        "expected_dept": "Phòng Công tác Sinh viên (VLUTE) – Đầu mối tiếp nhận hồ sơ (Phối hợp Phòng Kế hoạch - Tài chính)",
        "questions": [
            # QĐ, căn cứ, nguyên tắc, miễn 100% học phí (1-32)
            ("QĐ 904 miễn giảm", "direct", "Quy định chế độ chính sách miễn giảm học phí, hỗ trợ chi phí học tập hiện hành được ban hành theo Quyết định số mấy và ngày nào?"),
            ("Thay thế QĐ 205", "direct", "Quyết định 904/QĐ-ĐHSPKTVL ngày 09/9/2025 thay thế quyết định cũ nào trước đó?"),
            ("Nghị định 238/2025", "direct", "Chính sách miễn giảm học phí của trường hiện nay căn cứ theo Nghị định nào của Chính phủ ban hành tháng 9/2025?"),
            ("QĐ 66 và TTLT 35", "direct", "Chính sách hỗ trợ chi phí học tập cho sinh viên dân tộc thiểu số hộ nghèo được thực hiện theo Quyết định và Thông tư liên tịch nào?"),
            ("Đối tượng áp dụng", "direct", "Quy định về chế độ miễn giảm học phí và hỗ trợ chi phí học tập áp dụng cho trình độ đào tạo nào tại trường?"),
            ("Hai chế độ chính sách", "direct", "Điều 2 nêu hai chế độ chính sách sinh viên được quy định trong văn bản gồm những chế độ nào?"),
            ("Nguyên tắc nộp hồ sơ", "paraphrase", "Bốn nguyên tắc thực hiện chế độ chính sách miễn giảm học phí theo Điều 3 là gì?"),
            ("Nhóm miễn 100% Điều 5", "direct", "Có tổng cộng bao nhiêu nhóm đối tượng sinh viên được miễn 100% học phí theo Điều 5?"),
            ("Người có công cách mạng", "direct", "Những đối tượng thuộc Pháp lệnh Ưu đãi người có công với cách mạng nào được miễn học phí tại trường?"),
            ("Con thương binh bệnh binh", "paraphrase", "Con của thương binh, bệnh binh hoặc con người hoạt động kháng chiến bị nhiễm chất độc hóa học có được miễn học phí không?"),
            ("Anh hùng LLVT", "paraphrase", "Con của Anh hùng Lực lượng vũ trang nhân dân hoặc Anh hùng Lao động thời kỳ kháng chiến có thuộc diện miễn học phí không?"),
            ("Sinh viên khuyết tật", "paraphrase", "Sinh viên bị khuyết tật đang học đại học chính quy tại VLUTE được hưởng chế độ miễn học phí thế nào?"),
            ("Độ tuổi 16-22 trợ cấp XH", "direct", "Người hưởng trợ cấp xã hội hàng tháng theo Nghị định 20/2021/NĐ-CP cần đáp ứng điều kiện độ tuổi và văn bằng nào để được miễn học phí?"),
            ("Sinh viên cử tuyển", "paraphrase", "Sinh viên học theo chế độ cử tuyển tại VLUTE có được miễn học phí toàn khóa không?"),
            ("DTTS hộ nghèo miễn HP", "direct", "Sinh viên dân tộc thiểu số có người thân nào thuộc hộ nghèo hoặc cận nghèo thì được miễn học phí theo khoản 5 Điều 5?"),
            ("Ông bà nuôi dưỡng DTTS", "paraphrase", "Sinh viên dân tộc thiểu số sống với ông bà thuộc diện hộ nghèo có được xét miễn học phí không?"),
            ("Ngành Mác Lênin", "direct", "Sinh viên theo học chuyên ngành nào về lý luận chính trị được hưởng chính sách miễn học phí?"),
            ("DTTS rất ít người NĐ 57", "direct", "Sinh viên thuộc nhóm dân tộc thiểu số rất ít người được miễn học phí theo quy định tại Nghị định nào?"),
            ("Số lượng 16 dân tộc", "direct", "Theo khoản 7 Điều 5, danh sách dân tộc thiểu số rất ít người gồm tất cả bao nhiêu dân tộc?"),
            ("Kể tên DTTS rất ít", "direct", "Những dân tộc nào nằm trong nhóm 16 dân tộc thiểu số rất ít người được miễn học phí (ví dụ Cống, Mảng, Pu Péo, Ơ Đu)?"),
            ("Bố Y La Ha Chứt", "paraphrase", "Sinh viên thuộc dân tộc Bố Y, La Ha, Ngái hoặc Chứt có được miễn học phí theo diện dân tộc rất ít người không?"),
            ("Brâu Rơ Măm Lô Lô", "paraphrase", "Người học thuộc dân tộc Brâu, Rơ Măm, Lô Lô, Lự, Pà Then, La Hủ có được miễn học phí tại trường không?"),
            ("Chương trình đề án Chính phủ", "direct", "Ngoài 7 nhóm cụ thể đầu tiên, nhóm đối tượng thứ 8 được miễn học phí theo Điều 5 là ai?"),
            ("Học văn bằng 2 trợ cấp XH", "paraphrase", "Sinh viên từ 16 đến 22 tuổi hưởng trợ cấp xã hội nhưng đang học văn bằng đại học thứ hai có được miễn học phí không?"),
            ("Bằng Có công với nước", "direct", "Người trong gia đình được tặng Kỷ niệm chương Tổ quốc ghi công hoặc Bằng Có công với nước trước mốc thời gian nào được miễn học phí?"),
            ("Con liệt sĩ miễn HP", "paraphrase", "Sinh viên là con liệt sĩ cần căn cứ quy định nào trong Điều 5 để được miễn hoàn toàn học phí?"),
            ("Sửa đổi thay thế QĐ 904", "direct", "Quy định chế độ miễn giảm học phí mới ban hành ngày 09/9/2025 do ai ký ban hành và ai đề nghị?"),
            ("Phân biệt miễn 100% vs 70%", "paraphrase", "Sự khác biệt về điều kiện đối tượng giữa sinh viên dân tộc thiểu số được miễn 100% học phí và giảm 70% học phí là gì?"),
            ("Miễn HP theo chương trình chuẩn", "paraphrase", "Sinh viên hệ chất lượng cao hoặc chương trình khác được tính mức miễn giảm học phí dựa trên mức học phí nào?"),
            ("Trần học phí NĐ 238", "direct", "Mức ngân sách nhà nước cấp bù tiền miễn giảm học phí bị giới hạn tối đa bởi mức trần nào?"),
            ("Trùng lặp chế độ cao hơn", "paraphrase", "Nếu sinh viên đồng thời thuộc nhiều diện hưởng chính sách miễn giảm học phí khác nhau ở các văn bản thì giải quyết thế nào?"),
            ("Học 2 trường 2 ngành", "paraphrase", "Sinh viên đang học cùng lúc hai ngành trong trường hoặc đã hưởng miễn giảm ở trường khác thì có được miễn thêm không?"),
            # Giảm 70%, Giảm 50%, Hồ sơ & Thủ tục miễn giảm (33-66)
            ("Đối tượng giảm 70%", "direct", "Sinh viên thuộc diện nào được giảm 70% học phí theo Điều 6 của Quy định miễn giảm học phí?"),
            ("Xã khu vực III bãi ngang", "paraphrase", "Sinh viên dân tộc thiểu số thường trú tại xã khu vực III hoặc xã đặc biệt khó khăn vùng bãi ngang, hải đảo được giảm bao nhiêu phần trăm học phí?"),
            ("Điều kiện thường trú 70%", "paraphrase", "Để được giảm 70% học phí, yêu cầu về nơi thường trú của bản thân sinh viên và cha mẹ như thế nào?"),
            ("Giảm 50% tai nạn lao động", "direct", "Trường hợp nào sinh viên có cha hoặc mẹ bị tai nạn lao động, mắc bệnh nghề nghiệp được giảm 50% học phí?"),
            ("Con viên chức VLUTE", "paraphrase", "Sinh viên là con của viên chức và người lao động đang công tác tại VLUTE được giảm bao nhiêu phần trăm học phí?"),
            ("Thời hạn 45 ngày nộp đơn", "direct", "Trong vòng bao nhiêu ngày kể từ ngày khai giảng năm học, sinh viên phải nộp đơn đề nghị miễn giảm học phí?"),
            ("Mẫu đơn Phụ lục I", "direct", "Mẫu Đơn đề nghị miễn, giảm học phí được quy định tại Phụ lục nào kèm theo Quyết định 904?"),
            ("Hình thức bản sao hồ sơ", "paraphrase", "Các giấy tờ chứng minh đối tượng miễn giảm học phí nộp kèm đơn phải đảm bảo yêu cầu công chứng hoặc đối chiếu như thế nào?"),
            ("Hồ sơ người có công", "direct", "Sinh viên diện người có công với cách mạng cần nộp giấy xác nhận của cơ quan nào khi xin miễn học phí?"),
            ("Hồ sơ khuyết tật", "direct", "Giấy xác nhận khuyết tật dùng trong hồ sơ miễn học phí do cơ quan cấp nào cấp?"),
            ("Hồ sơ mồ côi bảo trợ XH", "direct", "Đối tượng 16–22 tuổi học văn bằng thứ nhất nộp quyết định trợ cấp xã hội hoặc giấy xác nhận mồ côi do cơ quan nào cấp?"),
            ("Hồ sơ cử tuyển", "direct", "Sinh viên hệ cử tuyển khi làm hồ sơ miễn học phí phải nộp quyết định của cơ quan nào?"),
            ("Hồ sơ DTTS nghèo", "direct", "Sinh viên dân tộc thiểu số thuộc hộ nghèo hoặc cận nghèo cần chuẩn bị những giấy tờ gì để xin miễn học phí?"),
            ("Hồ sơ vùng ĐBKK công an", "direct", "Đối tượng dân tộc thiểu số rất ít người và vùng đặc biệt khó khăn cần xin giấy xác nhận thường trú từ cơ quan nào?"),
            ("Hồ sơ tai nạn LĐ BHXH", "direct", "Quyết định hưởng trợ cấp hàng tháng do tai nạn lao động hoặc bệnh nghề nghiệp phải do cơ quan nào cấp?"),
            ("Hồ sơ con CBVC VLUTE", "direct", "Sinh viên là con viên chức, người lao động đang công tác tại trường cần nộp những giấy tờ gì để được giảm 50% học phí?"),
            ("Xác nhận BGH con CBVC", "paraphrase", "Đơn xin giảm 50% học phí của con cán bộ, viên chức VLUTE cần có chữ ký xác nhận của cấp nào?"),
            ("Nộp 1 lần đầu cả khóa", "paraphrase", "Sinh viên thuộc diện miễn giảm học phí có phải làm lại toàn bộ hồ sơ nộp vào mỗi học kỳ không?"),
            ("Bổ sung hộ nghèo từng kỳ", "direct", "Đối tượng nào phải nộp bổ sung giấy xác nhận mỗi đầu học kỳ để tiếp tục hưởng miễn giảm học phí?"),
            ("Thông tin trên Phụ lục I", "direct", "Mẫu đơn Phụ lục I đề nghị miễn giảm học phí yêu cầu sinh viên điền những thông tin cá nhân cơ bản nào?"),
            ("Số CCCD Phụ lục I", "paraphrase", "Sinh viên viết đơn đề nghị miễn giảm học phí theo Phụ lục I có cần ghi số Căn cước công dân và nơi sinh không?"),
            ("Thời điểm chi trả miễn giảm", "direct", "Kinh phí cấp bù miễn giảm học phí được tính tối đa bao nhiêu tháng một năm và chi trả mấy lần mỗi năm?"),
            ("Bị kỷ luật ngừng học miễn giảm", "paraphrase", "Trong thời gian bị kỷ luật ngừng học, buộc thôi học, học lưu ban hoặc học lại, sinh viên có được miễn giảm học phí không?"),
            ("Ngoại lệ ốm đau tai nạn", "paraphrase", "Sinh viên phải dừng học hoặc học lại do ốm đau, tai nạn bất khả kháng thì có được tiếp tục hưởng miễn giảm học phí không và giới hạn mấy lần?"),
            ("Truy lĩnh giảm trừ kỳ sau", "paraphrase", "Nếu gia đình hoặc sinh viên nộp hồ sơ miễn giảm học phí đúng hạn nhưng chưa kịp nhận tiền cấp bù thì xử lý ra sao?"),
            ("Thời gian đào tạo chính thức", "direct", "Chế độ miễn giảm học phí chỉ được thực hiện trong thời gian đào tạo chính thức hay tính cả thời gian học kéo dài, học bổ sung?"),
            ("Thay đổi lý do miễn giảm", "paraphrase", "Trong quá trình học nếu phát sinh thay đổi về lý do được miễn hoặc giảm học phí thì việc miễn giảm được điều chỉnh khi nào?"),
            ("Hồ sơ không nộp kịp 45 ngày", "direct", "Thời hạn 45 ngày nộp đơn miễn giảm học phí được tính kể từ mốc thời gian nào của năm học?"),
            ("Bản sao có bản chính đối chiếu", "paraphrase", "Nếu không kịp đi chứng thực bản sao giấy tờ miễn giảm học phí thì sinh viên có thể dùng phương án nào để đối chiếu?"),
            ("Đặc khu xã phường cấp", "direct", "Ngoài UBND xã và phường, cấp hành chính nào được ghi trong quy định mới về xác nhận hộ nghèo, khuyết tật?"),
            ("Phòng thu hồ sơ miễn giảm", "direct", "Phòng ban nào ra thông báo và trực tiếp thu hồ sơ miễn giảm học phí của sinh viên trước mỗi học kỳ?"),
            ("Phòng chi trả miễn giảm", "direct", "Đơn vị nào căn cứ quyết định đã phê duyệt để thực hiện chi trả miễn giảm học phí cho sinh viên?"),
            ("Cập nhật hệ thống đào tạo", "direct", "Phòng Đào tạo và Đảm bảo chất lượng có trách nhiệm gì đối với dữ liệu sinh viên được miễn giảm học phí?"),
            ("Phê duyệt danh sách miễn giảm", "direct", "Ai là người xét duyệt cuối cùng danh sách miễn giảm học phí do Phòng CTSV&TT trình lên?"),
            # Hỗ trợ chi phí học tập (67-100)
            ("Đối tượng hỗ trợ CPHT", "direct", "Chính sách hỗ trợ chi phí học tập theo Điều 10 áp dụng cho đối tượng sinh viên nào?"),
            ("Loại trừ hỗ trợ CPHT", "direct", "Những hệ hoặc diện sinh viên nào bị loại trừ, không được hưởng hỗ trợ chi phí học tập theo khoản 2 Điều 10?"),
            ("Cử tuyển có được hỗ trợ CPHT", "paraphrase", "Sinh viên hệ cử tuyển hoặc liên thông là người dân tộc thiểu số hộ nghèo có được nhận hỗ trợ chi phí học tập 60% lương tối thiểu không?"),
            ("Dự bị đại học hỗ trợ CPHT", "paraphrase", "Sinh viên học đại học sau khi hoàn thành chương trình dự bị đại học hoặc đào tạo theo địa chỉ có được hưởng hỗ trợ chi phí học tập không?"),
            ("Mức 60% lương tối thiểu", "direct", "Mức hỗ trợ chi phí học tập mỗi tháng bằng bao nhiêu phần trăm mức lương tối thiểu chung và hưởng tối đa mấy tháng một năm?"),
            ("Số năm hưởng hỗ trợ CPHT", "direct", "Sinh viên dân tộc thiểu số hộ nghèo được hưởng hỗ trợ chi phí học tập trong tối đa bao nhiêu năm?"),
            ("Thời hạn 30 ngày thông báo", "direct", "Trong vòng bao nhiêu ngày từ khi khai giảng năm học, Phòng CTSV&TT ra thông báo về chính sách hỗ trợ chi phí học tập?"),
            ("Hồ sơ hỗ trợ CPHT", "direct", "Một bộ hồ sơ đề nghị hỗ trợ chi phí học tập theo Điều 12 bao gồm những loại giấy tờ nào?"),
            ("Mẫu đơn Phụ lục II", "direct", "Đơn đề nghị hỗ trợ chi phí học tập của sinh viên sử dụng mẫu tại Phụ lục nào của Quy định?"),
            ("Xác nhận đơn Phụ lục II", "paraphrase", "Mẫu đơn Phụ lục II đề nghị hỗ trợ chi phí học tập có mục xác nhận của phòng ban nào?"),
            ("Số lần nộp hỗ trợ CPHT", "direct", "Sinh viên diện hỗ trợ chi phí học tập phải nộp hồ sơ bao nhiêu lần trong một năm học?"),
            ("Thoát nghèo trong năm", "paraphrase", "Nếu giữa năm học gia đình sinh viên dân tộc thiểu số đã thoát nghèo thì sinh viên có nghĩa vụ nộp giấy tờ gì?"),
            ("Bổ sung hộ nghèo mới", "paraphrase", "Nếu đầu năm chưa phải hộ nghèo nhưng giữa năm học gia đình được bổ sung diện hộ nghèo thì có được nộp hồ sơ hưởng hỗ trợ chi phí học tập không?"),
            ("Hiệu lực giấy hộ nghèo", "direct", "Thời gian sinh viên được hưởng hỗ trợ chi phí học tập khi bổ sung hồ sơ hộ nghèo mới được tính dựa trên yếu tố nào?"),
            ("Không truy lĩnh nộp muộn", "paraphrase", "Nếu sinh viên đủ điều kiện hỗ trợ chi phí học tập nhưng không nộp đơn và hồ sơ đúng lúc thì có được truy lĩnh tiền cho thời gian đã học trước đó không?"),
            ("Hai đợt cấp tiền CPHT", "direct", "Kinh phí hỗ trợ chi phí học tập được chi trả hai lần trong năm học vào những tháng nào và mỗi lần cấp cho mấy tháng?"),
            ("Truy lĩnh khi chưa nhận CPHT", "direct", "Trường hợp đến hạn cấp kinh phí hỗ trợ chi phí học tập mà sinh viên chưa được nhận tiền thì xử lý thế nào?"),
            ("Dừng hỗ trợ khi bỏ học", "paraphrase", "Sinh viên bỏ học hoặc bị kỷ luật buộc thôi học thì bị dừng cấp kinh phí hỗ trợ chi phí học tập từ thời điểm nào?"),
            ("Khấu trừ khi đã nhận trước", "paraphrase", "Nếu sinh viên đã nhận tiền hỗ trợ chi phí học tập rồi mới bị kỷ luật buộc thôi học hoặc bỏ học thì nhà trường xử lý ra sao?"),
            ("Đình chỉ học tập và CPHT", "direct", "Sinh viên bị đình chỉ học tập có thời hạn có được nhận hỗ trợ chi phí học tập trong thời gian đình chỉ không?"),
            ("Khấu trừ số tháng đình chỉ", "paraphrase", "Trường hợp đã nhận tiền hỗ trợ chi phí học tập trước khi bị đình chỉ học tập, sau khi nhập học lại nhà trường khấu trừ thế nào?"),
            ("Ngoại lệ đình chỉ do ốm đau", "paraphrase", "Nếu phải tạm dừng học do tai nạn, ốm đau hoặc lý do khách quan được xác nhận thì có bị cắt tiền hỗ trợ chi phí học tập không?"),
            ("Học kỳ tiếp theo thoát nghèo", "paraphrase", "Khi sinh viên nộp giấy chứng nhận hộ đã thoát nghèo trong năm học, việc dừng chi trả áp dụng bắt đầu từ kỳ nào?"),
            ("Cập nhật hệ thống KHTC CTSV", "direct", "Trong Điều 15, phân công trách nhiệm phối hợp giữa Phòng CTSV&TT, Phòng KHTC và Phòng ĐT&ĐBCL về miễn giảm học phí như thế nào?"),
            ("Hiệu lực thi hành Đ16", "direct", "Ai có thẩm quyền điều chỉnh tạm thời một số nội dung trong Quy định miễn giảm học phí cho phù hợp thực tế?"),
            ("Văn bằng hai có được CPHT", "paraphrase", "Sinh viên đang học văn bằng hai là người dân tộc thiểu số thuộc hộ cận nghèo có được xét hỗ trợ chi phí học tập không?"),
            ("Giấy khai sinh hỗ trợ CPHT", "direct", "Bản sao giấy khai sinh nộp trong hồ sơ hỗ trợ chi phí học tập chấp nhận những dạng sao y nào?"),
            ("Hiệu lực từ ngày ký", "direct", "Quy định miễn giảm học phí ban hành theo Quyết định 904 có hiệu lực từ thời điểm nào?"),
            ("Điền thông tin dân tộc PL II", "direct", "Khi điền Đơn đề nghị hỗ trợ chi phí học tập ở Phụ lục II, sinh viên cần ghi thêm thông tin gì so với Phụ lục I?"),
            ("Lần 1 tháng 10 tháng 11", "paraphrase", "Đợt chi trả hỗ trợ chi phí học tập lần thứ nhất hàng năm chi trả tiền của bao nhiêu tháng và vào khoảng thời gian nào?"),
            ("Lần 2 tháng 3 tháng 4", "paraphrase", "Đợt cấp kinh phí hỗ trợ chi phí học tập lần 2 cho 5 tháng còn lại được thực hiện vào những tháng nào của năm sau?"),
            ("Chênh lệch mức hỗ trợ 10 tháng", "direct", "Một năm học sinh viên được hưởng tối đa bao nhiêu tháng hỗ trợ chi phí học tập và bao nhiêu tháng cấp bù miễn giảm học phí?"),
            ("Nghị quyết 98 và QĐ 1723", "direct", "Ngoài Nghị định 238/2025/NĐ-CP và Quyết định 66/2013/QĐ-TTg, Quyết định 904 còn căn cứ vào Thông tư công tác sinh viên số mấy?"),
            ("Tích hợp miễn giảm và CPHT", "paraphrase", "Sinh viên dân tộc thiểu số thuộc hộ nghèo học chính quy văn bằng thứ nhất vừa thuộc diện miễn học phí vừa có thể hưởng chế độ nào khác trong văn bản này?"),
        ],
    },
    "quy_trinh_hoan_tra_hoc_phi.pdf": {
        "expected_dept": "Tuyến phối hợp xử lý (CTSV – Đào tạo – KHTC)",
        "questions": [
            # Thông tin tài liệu, mục đích, đối tượng, thời gian (1-38)
            ("Mã số quy trình", "direct", "Quy trình hoàn trả học phí thừa cho sinh viên có mã số tài liệu là gì và thuộc lần soát xét thứ mấy?"),
            ("Ngày hiệu lực QT-SV-04", "direct", "Quy trình hoàn trả học phí thừa mã số QT-SV-04 bắt đầu có hiệu lực từ ngày tháng năm nào?"),
            ("Tiêu chuẩn ISO", "direct", "Quy trình hoàn trả học phí thừa QT-SV-04 được xây dựng theo tài liệu viện dẫn tiêu chuẩn ISO nào?"),
            ("Viện dẫn QĐ 100", "direct", "Ngoài ISO 9001:2015, quy trình hoàn trả học phí thừa còn viện dẫn Quyết định đào tạo tín chỉ số mấy và ngày nào?"),
            ("Người soạn phê duyệt", "direct", "Ai là người soạn thảo, xem xét và phê duyệt Quy trình hoàn trả học phí thừa QT-SV-04?"),
            ("Từ viết tắt Khoa CN", "direct", "Trong mục từ viết tắt của Quy trình hoàn trả học phí thừa, ký hiệu Khoa CN, GVQL, KHTC, ĐT viết tắt cho những từ gì?"),
            ("Mục đích quy trình", "direct", "Mục đích ban hành Quy trình hoàn trả học phí thừa QT-SV-04 là gì?"),
            ("Đối tượng áp dụng hệ", "direct", "Quy trình hoàn trả học phí thừa áp dụng cho sinh viên thuộc hệ đào tạo nào?"),
            ("Hai trường hợp đủ điều kiện", "direct", "Sinh viên có học phí thừa phải thuộc một trong hai trường hợp điều kiện nào mới được nộp đơn xin hoàn trả?"),
            ("Điều kiện xét tốt nghiệp", "paraphrase", "Sinh viên đã hoàn thành chương trình đào tạo và đã nộp hồ sơ xét tốt nghiệp mà còn dư học phí thì có được xin hoàn trả học phí thừa không?"),
            ("Điều kiện năm thứ ba", "paraphrase", "Sinh viên chưa tốt nghiệp nhưng đang học năm thứ ba trở đi và đã hoàn thành tối thiểu mấy học kỳ chính thì được xin nhận lại học phí thừa?"),
            ("Sinh viên năm nhất năm hai", "paraphrase", "Sinh viên năm nhất hoặc mới học xong 2 học kỳ chính nhưng đóng dư học phí có đủ điều kiện nộp đơn hoàn trả học phí thừa ngay không?"),
            ("Số học kỳ chính 4 kỳ", "paraphrase", "Muốn làm đơn hoàn trả học phí thừa khi chưa tốt nghiệp thì sinh viên cần hoàn thành ít nhất mấy học kỳ chính?"),
            ("Hai đợt một năm", "direct", "Nhà trường tổ chức tiếp nhận hồ sơ hoàn trả học phí thừa mấy đợt trong năm và vào những tháng nào?"),
            ("Tuần tiếp nhận hoàn trả", "direct", "Sinh viên được nộp đơn đề nghị nhận lại học phí thừa vào tuần thứ mấy của tháng 2 và tháng 9 hàng năm?"),
            ("Tháng 3 nộp đơn được không", "paraphrase", "Nếu lỡ hạn tuần 1 và tuần 2 tháng 2 thì sinh viên xin hoàn trả học phí thừa phải đợi đến đợt tháng mấy trong năm?"),
            ("Thời hạn tháng 9", "paraphrase", "Đợt hoàn trả học phí thừa thứ hai trong năm nhận đơn của sinh viên vào thời điểm cụ thể nào trong tháng 9?"),
            ("Thủ tục đầu tiên 5.2.1", "paraphrase", "Bước đầu tiên sinh viên cần làm khi muốn xin hoàn trả lại tiền học phí đóng thừa là gặp ai và xin mẫu đơn gì?"),
            ("Mẫu đơn BM-KH-10a", "direct", "Sinh viên có nhu cầu nhận lại học phí thừa phải điền thông tin vào mẫu đơn có ký hiệu gì?"),
            ("Nơi xin mẫu BM-KH-10a", "paraphrase", "Sinh viên liên hệ bộ phận hoặc cá nhân nào để xin mẫu đơn đề nghị hoàn trả học phí thừa BM-KH-10a và nộp lại cho ai?"),
            ("Lưu đồ bước 1", "direct", "Trong lưu đồ tiến trình 1 của Quy trình hoàn trả học phí thừa, trách nhiệm chính và trách nhiệm hỗ trợ thuộc về ai?"),
            ("Tên đầy đủ QT-SV-04", "direct", "Quy trình hoàn trả học phí thừa cho sinh viên gồm tổng cộng bao nhiêu bước trong lưu đồ tiến trình?"),
            ("Tổng quan diễn giải 5.2", "direct", "Mục 5.2 diễn giải quy trình hoàn trả học phí thừa gồm bốn giai đoạn cụ thể nào?"),
            ("Nếu đơn không hợp lệ", "paraphrase", "Khi nộp đơn xin hoàn trả học phí thừa mà hồ sơ chưa hợp lệ thì bước tiếp nhận sẽ xử lý như thế nào?"),
            ("Bảo lưu danh sách hoàn trả", "paraphrase", "Trong bước 5.2.2 tiếp nhận và tổng hợp đề nghị hoàn trả học phí thừa, giáo viên phụ trách cần soạn thảo quyết định gì trình lãnh đạo Phòng CTSV?"),
            ("Đóng thừa do học bổng miễn giảm", "paraphrase", "Quy trình QT-SV-04 giải quyết việc gì đối với khoản học phí thừa của sinh viên chính quy?"),
            ("Văn phòng liên quan hoàn trả", "direct", "Có những phòng ban nào tham gia trực tiếp vào quy trình xét duyệt và hoàn trả học phí thừa cho sinh viên?"),
            ("Vai trò GVQL", "paraphrase", "Giáo viên quản lý (GVQL) đóng vai trò gì trong giai đoạn sinh viên nộp đơn xin hoàn lại học phí thừa?"),
            ("Xác nhận lãnh đạo CTSV", "paraphrase", "Ai là người xem xét duyệt danh sách tổng hợp sinh viên đề nghị hoàn trả học phí thừa theo mẫu BM-KH-10c tại Phòng CTSV?"),
            ("Hướng dẫn sửa đơn", "paraphrase", "Trường hợp đơn đề nghị nhận lại học phí thừa của sinh viên bị lãnh đạo Phòng CTSV đánh giá không hợp lệ thì xử lý ra sao?"),
            ("Thời gian CTSV chuyển ĐT", "direct", "Phòng Công tác sinh viên phải chuyển danh sách hoàn trả học phí thừa sang Phòng Đào tạo trong vòng bao nhiêu ngày làm việc?"),
            ("Mốc tính 5 ngày CTSV", "paraphrase", "Thời hạn 5 ngày làm việc để Phòng CTSV gửi danh sách đề nghị hoàn trả học phí thừa sang Phòng Đào tạo được tính kể từ ngày nào?"),
            ("Định dạng file CTSV gửi", "direct", "Khi chuyển danh sách đề nghị hoàn trả học phí thừa sang Phòng Đào tạo, Phòng CTSV gửi theo hình thức hồ sơ nào?"),
            ("Trách nhiệm bước 2 lưu đồ", "direct", "Trong tiến trình số 2 của lưu đồ hoàn trả học phí thừa, đơn vị nào chịu trách nhiệm chính và đơn vị nào hỗ trợ?"),
            ("Nếu CTSV gửi ĐT không hợp lệ", "paraphrase", "Nếu danh sách đề nghị hoàn trả học phí thừa gửi lên xét duyệt chưa hợp lệ thì trả về bộ phận nào xử lý lại?"),
            ("Khoa chuyên môn liên quan", "direct", "Khi Phòng Đào tạo tiếp nhận xong thông tin sinh viên nộp đơn đề nghị hoàn trả học phí thừa thì phải thông báo cho những đối tượng nào?"),
            ("Cơ sở học chế tín chỉ", "direct", "Quy định đào tạo đại học cao đẳng theo học chế tín chỉ viện dẫn trong quy trình hoàn trả học phí thừa là quyết định số bao nhiêu?"),
            ("Phạm vi văn bản trang", "direct", "Tài liệu Quy trình hoàn trả học phí thừa mã số QT-SV-04 gồm tổng cộng bao nhiêu trang nội dung chính?"),
            # Bước xử lý tại Phòng ĐT, Phòng KHTC, Thanh toán, Biểu mẫu & Lưu trữ (39-100)
            ("Xử lý dữ liệu Phòng ĐT", "direct", "Tại bước 5.2.3, Phòng Đào tạo thực hiện những công việc gì sau khi nhận danh sách BM-KH-10c từ Phòng CTSV?"),
            ("Ai xác nhận số tiền thừa", "paraphrase", "Phòng ban nào chịu trách nhiệm xác nhận chính xác số tiền học phí thừa của sinh viên?"),
            ("Thành phần hồ sơ ĐT gửi KHTC", "direct", "Bộ hồ sơ chứng từ hoàn trả tiền học phí thừa do Phòng Đào tạo lập gửi sang Phòng KH-TC gồm những giấy tờ và mẫu biểu nào?"),
            ("Mẫu BM-KH-10b", "direct", "Giấy đề nghị theo mẫu BM-KH-10b nằm trong bộ hồ sơ do phòng nào lập để gửi về Phòng Kế hoạch - Tài chính?"),
            ("Giấy đề nghị C37-HD", "direct", "Giấy đề nghị thanh toán dùng trong hồ sơ hoàn trả học phí thừa có ký hiệu biểu mẫu là gì?"),
            ("Hình thức gửi sang KHTC", "direct", "Phòng Đào tạo gửi hồ sơ chứng từ hoàn trả học phí thừa về Phòng KH-TC gồm bản giấy và tệp tin định dạng gì?"),
            ("Thời gian ĐT xử lý 3 ngày", "direct", "Phòng Đào tạo phải hoàn tất xử lý và thông báo cho Phòng/Khoa và sinh viên trong vòng bao nhiêu ngày làm việc?"),
            ("Mốc tính 3 ngày Phòng ĐT", "paraphrase", "Thời hạn 3 ngày làm việc của Phòng Đào tạo trong bước xử lý hoàn trả học phí thừa tính từ mốc thời gian nào?"),
            ("Thông báo đã tiếp nhận", "paraphrase", "Phòng Đào tạo có trách nhiệm thông báo kết quả đã tiếp nhận thông tin sinh viên nộp đơn hoàn trả học phí thừa cho những ai?"),
            ("Trách nhiệm Phòng KHTC", "direct", "Bước 5.2.4 quy định Phòng Kế hoạch - Tài chính làm những nhiệm vụ gì khi nhận hồ sơ hoàn trả học phí thừa từ Phòng Đào tạo?"),
            ("Ai duyệt hồ sơ thanh toán", "paraphrase", "Sau khi Phòng Kế hoạch - Tài chính kiểm tra đối chiếu chứng từ hoàn trả học phí thừa, phải trình ai phê duyệt?"),
            ("Thời gian KHTC trình duyệt", "direct", "Phòng KH-TC mất tối đa bao nhiêu ngày làm việc để kiểm tra chứng từ, đối chiếu và trình Hiệu trưởng duyệt thanh toán hoàn trả học phí?"),
            ("Mốc tính 3 ngày KHTC", "paraphrase", "Thời hạn 3 ngày làm việc của Phòng KH-TC trình Hiệu trưởng duyệt hồ sơ hoàn trả học phí tính từ lúc nào?"),
            ("Hình thức trả tiền thừa", "paraphrase", "Nhà trường hoàn lại học phí thừa cho sinh viên bằng tiền mặt trực tiếp hay hình thức chuyển khoản?"),
            ("Thời gian chuyển khoản 5 ngày", "direct", "Phòng Kế hoạch - Tài chính thực hiện chuyển khoản hoàn trả học phí thừa cho sinh viên tối đa bao nhiêu ngày làm việc?"),
            ("Mốc tính 5 ngày chuyển khoản", "paraphrase", "Thời hạn tối đa 5 ngày làm việc để chuyển khoản tiền học phí thừa cho sinh viên được tính kể từ khi nào?"),
            ("Tổng thời gian từ tháng 2/9", "paraphrase", "Tính theo các mốc 5 ngày làm việc, 3 ngày làm việc, 3 ngày làm việc và tối đa 5 ngày làm việc, mỗi khâu hoàn trả học phí thừa quy định bao nhiêu ngày?"),
            ("Lưu đồ bước 5 6 7 8", "paraphrase", "Ai phê duyệt chi tiền hoàn trả học phí thừa trong tiến trình số 7 của lưu đồ QT-SV-04?"),
            ("Danh sách BM-KH-10c là gì", "direct", "Biểu mẫu ký hiệu BM-KH-10c trong Quy trình hoàn trả học phí thừa có tên gọi là gì?"),
            ("Tên 4 biểu mẫu hoàn trả", "direct", "Mục 6 liệt kê tất cả 4 biểu mẫu áp dụng trong quy trình hoàn trả học phí thừa gồm những ký hiệu và tên nào?"),
            ("Nơi lưu BM-KH-10a", "direct", "Đơn đề nghị nhận lại học phí thừa (BM-KH-10a) bản chính được lưu tại phòng nào và lưu trong thời gian bao lâu?"),
            ("Nơi lưu bản photo 10a", "direct", "Ngoài bản chính tại Phòng CTSV, bản photo và file của mẫu BM-KH-10a được lưu tại phòng nào trong thời gian 2 năm?"),
            ("Nơi lưu BM-KH-10c", "direct", "Danh sách đề nghị hoàn trả tiền học phí thừa (BM-KH-10c) bản chính lưu ở phòng nào, bản photo lưu ở đâu và thời hạn lưu bao lâu?"),
            ("Nơi lưu BM-KH-10b", "direct", "Giấy đề nghị (BM-KH-10b) bản chính và bản photo được lưu giữ tại hai phòng nào với thời gian lưu trữ bao lâu?"),
            ("Nơi lưu C37-HD", "direct", "Giấy đề nghị thanh toán C37-HD được lưu bản chính tại phòng nào, bản photo tại phòng nào và thời gian lưu trữ bao lâu?"),
            ("Biểu mẫu lưu vĩnh viễn", "paraphrase", "Trong số 4 biểu mẫu hoàn trả học phí thừa, biểu mẫu nào có thời gian lưu trữ vĩnh viễn?"),
            ("Các biểu mẫu lưu 2 năm", "paraphrase", "Những biểu mẫu nào trong Quy trình hoàn trả học phí thừa có thời hạn lưu giữ 2 năm trước khi hủy?"),
            ("Kiểm tra hồ sơ hoàn trả ĐT", "paraphrase", "Nếu Phòng Đào tạo kiểm tra thấy danh sách BM-KH-10c gửi sang không hợp lệ thì bước lưu đồ số 5 xử lý ra sao?"),
            ("Cơ chế phối hợp 3 phòng", "paraphrase", "Tuyến phối hợp xử lý hồ sơ hoàn trả học phí thừa của sinh viên đi qua ba phòng ban chức năng nào theo thứ tự?"),
            ("Sinh viên năm 2 hoàn trả", "paraphrase", "Sinh viên năm hai mới học xong 3 học kỳ chính có thuộc đối tượng hoàn trả học phí thừa trong đợt tháng 2 không?"),
            ("Sinh viên năm 3 hoàn 4 kỳ", "paraphrase", "Sinh viên năm thứ ba đã học đủ 4 học kỳ chính muốn rút tiền học phí đóng dư thì liên hệ ai đầu tiên?"),
            ("Đã tốt nghiệp rút tiền dư", "paraphrase", "Sinh viên vừa hoàn thành chương trình đào tạo và nộp hồ sơ xét tốt nghiệp muốn lấy lại tiền học phí thừa cần chuẩn bị mẫu đơn nào?"),
            ("Sinh viên cần nộp đơn tháng nào", "paraphrase", "Hai đợt tiếp nhận đơn xin hoàn trả học phí thừa cố định hàng năm diễn ra vào tuần nào của tháng mấy?"),
            ("File Excel BM-KH-10c", "paraphrase", "Vì sao cả Phòng CTSV và Phòng Đào tạo đều phải gửi kèm file Excel của mẫu BM-KH-10c khi bàn giao chứng từ?"),
            ("Xác nhận ký tên ĐT trên 10c", "direct", "Mẫu BM-KH-10c gửi sang Phòng KH-TC phải có xác nhận và chữ ký của đơn vị nào?"),
            ("Quyết định bảo lưu CTSV", "direct", "Trong mục 5.2.2, giáo viên phụ trách lập danh sách và soạn thảo quyết định gì trước khi trình lãnh đạo Phòng CTSV duyệt?"),
            ("BGH duyệt hoàn trả", "paraphrase", "Trong lưu đồ quy trình hoàn trả học phí thừa, BGH (Hiệu trưởng) tham gia phê duyệt ở bước nào?"),
            ("Chuyển khoản hoàn trả KHTC", "paraphrase", "Đơn vị nào thực hiện bước cuối cùng là chuyển khoản tiền học phí thừa vào tài khoản cho sinh viên?"),
            ("Đối chiếu số tiền KHTC", "direct", "Trước khi trình Hiệu trưởng duyệt hoàn trả học phí thừa, Phòng KH-TC thực hiện thao tác kiểm tra gì?"),
            ("Khác biệt BM-KH-10a và 10b", "paraphrase", "Biểu mẫu BM-KH-10a và biểu mẫu BM-KH-10b trong quy trình hoàn trả học phí thừa khác nhau ở nội dung và nơi lưu bản chính như thế nào?"),
            ("Khác biệt lưu trữ 10c và C37", "paraphrase", "Thời gian lưu trữ của mẫu BM-KH-10c và mẫu C37-HD khác nhau như thế nào theo Mục 6?"),
            ("Sinh viên nộp đơn trực tiếp KHTC", "paraphrase", "Sinh viên muốn xin lại học phí thừa có mang đơn thẳng xuống Phòng Kế hoạch - Tài chính nộp ngay từ đầu được không?"),
            ("Ai hướng dẫn hoàn chỉnh đơn", "paraphrase", "Khi đơn xin hoàn trả học phí thừa không hợp lệ, ai hướng dẫn sinh viên chỉnh sửa lại hồ sơ?"),
            ("Phòng CTSV tổng hợp 10c", "direct", "Phòng Công tác sinh viên tổng hợp đơn đề nghị hoàn trả học phí thừa của sinh viên theo ký hiệu danh sách nào?"),
            ("Tháng 2 và tháng 9 tuần 1 2", "paraphrase", "Nếu sinh viên nộp đơn xin hoàn trả học phí thừa vào tuần 1 tháng 9 thì chậm nhất khi nào Phòng CTSV chuyển danh sách sang Phòng Đào tạo?"),
            ("Hạn CTSV 5 ngày cuối tháng", "paraphrase", "Ngày bắt đầu đếm 5 ngày làm việc để Phòng CTSV chuyển danh sách BM-KH-10c sang Phòng ĐT là ngày nào của tháng 2 và tháng 9?"),
            ("Lưu trữ bản photo tại ĐT", "direct", "Phòng Đào tạo lưu bản chính của biểu mẫu nào và lưu bản photo của những biểu mẫu nào trong quy trình hoàn trả học phí thừa?"),
            ("Lưu trữ bản chính tại CTSV", "direct", "Phòng Công tác sinh viên lưu bản chính của mẫu đơn nào và bản photo của danh sách nào theo Mục 6?"),
            ("Lưu trữ bản chính tại KHTC", "direct", "Phòng Kế hoạch - Tài chính chịu trách nhiệm lưu bản chính và file của hai chứng từ hoàn trả học phí thừa nào?"),
            ("Phương pháp hủy hết hạn", "direct", "Sau thời hạn lưu trữ 2 năm đối với BM-KH-10a, BM-KH-10b, BM-KH-10c, bảng biểu mẫu quy định thông tin gì về lưu giữ?"),
            ("Quy trình hoàn trả 10a 10c 10b", "paraphrase", "Thứ tự sử dụng ba biểu mẫu BM-KH-10a, BM-KH-10c, BM-KH-10b và C37-HD qua các bước từ khi sinh viên làm đơn đến lúc thanh toán ra sao?"),
            ("Thông báo cho Khoa CN", "paraphrase", "Trong bước 4 của lưu đồ và bước 5.2.3, Phòng Đào tạo có trách nhiệm thông báo thông tin tiếp nhận hồ sơ hoàn trả học phí thừa cho những bên nào?"),
            ("Điều kiện kép hay hoặc", "paraphrase", "Sinh viên muốn hoàn trả học phí thừa phải đáp ứng cả hai điều kiện tốt nghiệp và năm 3 cùng lúc hay chỉ cần thỏa mãn một trong hai trường hợp?"),
            ("Số đợt nhận đơn hoàn trả", "paraphrase", "Một năm học trường giải quyết bao nhiêu đợt hoàn trả học phí thừa theo đúng quy trình QT-SV-04?"),
            ("Cập nhật dữ liệu số tiền thừa", "paraphrase", "Bộ phận nào có trách nhiệm rà soát và xác nhận chính xác số tiền học phí thừa trong tài khoản sinh viên?"),
            ("Giấy đề nghị thanh toán kho bạc", "direct", "Ký hiệu chứng từ thanh toán đi kèm giấy đề nghị BM-KH-10b trong hồ sơ hoàn trả học phí thừa là gì?"),
            ("Tên người phê duyệt QT-SV-04", "direct", "Phó Hiệu trưởng hay Hiệu trưởng nào đã ký phê duyệt Quy trình hoàn trả học phí thừa QT-SV-04 ngày 01/03/2024?"),
            ("Lần soát xét QT-SV-04", "direct", "Trang bìa Quy trình hoàn trả học phí thừa ghi ngày hiệu lực và lần soát xét là bao nhiêu?"),
            ("Không hợp lệ ở Phòng ĐT", "paraphrase", "Khi danh sách hoàn trả học phí thừa tại Phòng Đào tạo phát hiện không hợp lệ thì trong lưu đồ xử lý quay lại bước nào?"),
            ("Nhận tiền sau khi BGH duyệt", "paraphrase", "Từ lúc Ban Giám hiệu ký duyệt hồ sơ thanh toán hoàn trả học phí thừa, sinh viên đợi tối đa mấy ngày làm việc để nhận chuyển khoản?"),
            ("Mục đích thống nhất giấy tờ", "paraphrase", "Quy trình QT-SV-04 ban hành nhằm thống nhất những loại giấy tờ và bước thực hiện nào cho sinh viên chính quy?"),
            ("Phối hợp CTSV ĐT KHTC", "paraphrase", "Vai trò khác nhau của CTSV, Phòng Đào tạo và Phòng KHTC trong việc hoàn trả học phí thừa cho sinh viên là gì?"),
        ],
    },
    "quy_dinh_cong_tac_sinh_vien.pdf": {
        "expected_dept": "Phòng Công tác Sinh viên (VLUTE)",
        "questions": [
            # QĐ, nhiệm vụ, quyền, hành vi cấm, khen thưởng (1-33)
            ("QĐ 1079 CTSV", "direct", "Quy định công tác sinh viên đối với chương trình đào tạo đại học chính quy được ban hành kèm theo Quyết định số mấy và ngày nào?"),
            ("Thay thế QĐ 356", "direct", "Quyết định 1079/QĐ-ĐHSPKTVL ngày 06/10/2025 thay thế quyết định cũ nào ban hành năm 2024?"),
            ("Thông tư 10/2016", "direct", "Quy định công tác sinh viên của trường căn cứ vào Thông tư nào của Bộ Giáo dục và Đào tạo?"),
            ("Phạm vi điều chỉnh Đ1", "direct", "Điều 1 của Quy định công tác sinh viên nêu rõ những nội dung điều chỉnh chính nào?"),
            ("Nguyên tắc CTSV Đ3", "direct", "Công tác sinh viên phải bảo đảm năm tính chất nguyên tắc nào theo khoản 3 Điều 3?"),
            ("12 nhiệm vụ sinh viên", "direct", "Theo Điều 4, sinh viên đại học chính quy có những nhiệm vụ cơ bản nào?"),
            ("Khám sức khỏe đầu khóa", "paraphrase", "Sinh viên có bắt buộc phải thực hiện khám sức khỏe đầu khóa và đóng bảo hiểm y tế đầy đủ, đúng hạn không?"),
            ("Sinh hoạt lớp", "paraphrase", "Tham gia đầy đủ số giờ sinh hoạt lớp quy định trong học kỳ có phải là nhiệm vụ bắt buộc của sinh viên không?"),
            ("Bồi hoàn học bổng NN", "paraphrase", "Nếu được Nhà nước cấp học bổng hoặc chi phí đào tạo mà không chấp hành điều động làm việc có thời hạn thì sinh viên phải xử lý thế nào?"),
            ("Tố giác tiêu cực", "paraphrase", "Khi phát hiện hành vi gian lận thi cử hoặc vi phạm pháp luật trong trường, sinh viên có nhiệm vụ báo cáo với ai?"),
            ("Quyền bình đẳng thông tin", "direct", "Theo khoản 2 Điều 5, sinh viên có quyền được cung cấp những thông tin gì về bản thân và quy chế?"),
            ("Quyền NCKH và trao đổi", "paraphrase", "Sinh viên có quyền tham gia thi Olympic, nghiên cứu khoa học và giao lưu trao đổi sinh viên ở nước ngoài không?"),
            ("Quyền dịch vụ CTXH", "direct", "Các dịch vụ công tác xã hội hiện có của trường mà sinh viên được quyền sử dụng theo Điều 5 gồm những gì?"),
            ("Quyền học cùng lúc 2 CT", "paraphrase", "Sinh viên có quyền xin nghỉ học tạm thời, học theo tiến độ nhanh hoặc học cùng lúc hai chương trình không?"),
            ("Quyền nghỉ hè tết lễ", "direct", "Sinh viên được hưởng quyền lợi gì về học bổng, miễn giảm phí dịch vụ công cộng, bảo tàng, di tích lịch sử?"),
            ("Quyền KTX và văn bằng", "paraphrase", "Sinh viên đủ điều kiện tốt nghiệp được cấp những giấy tờ gì và có được ưu tiên xét vào ký túc xá không?"),
            ("Quyền khiếu nại lên HT", "direct", "Sinh viên có quyền đề đạt nguyện vọng và khiếu nại lên Hiệu trưởng về những vấn đề nào theo khoản 5 Điều 5?"),
            ("5 hành vi cấm Đ6", "direct", "Điều 6 quy định năm nhóm hành vi nào sinh viên tuyệt đối không được làm?"),
            ("Cấm uống rượu say đến lớp", "paraphrase", "Hút thuốc và uống rượu bia trong giờ học hoặc say rượu bia khi đến lớp học bị quy định ra sao tại Điều 6?"),
            ("Khen thưởng thường xuyên", "direct", "Theo khoản 1 Điều 7, những thành tích đột xuất nào giúp cá nhân và tập thể lớp được khen thưởng thường xuyên kịp thời?"),
            ("Dũng cảm cứu người", "paraphrase", "Sinh viên có thành tích dũng cảm cứu người bị nạn, phòng chống tội phạm hoặc chống tham nhũng có được khen thưởng thường xuyên không?"),
            ("3 danh hiệu cá nhân Đ7", "direct", "Khen thưởng định kỳ cuối học kỳ, năm học, khóa học đối với cá nhân gồm những danh hiệu nào?"),
            ("Tiêu chuẩn Khá Giỏi XS", "direct", "Tiêu chuẩn điểm học tập thang 4, điểm thang 10 và xếp loại rèn luyện để đạt danh hiệu sinh viên Khá, Giỏi, Xuất sắc theo Điều 7 là gì?"),
            ("Loại trừ khen thưởng Đ7", "paraphrase", "Nếu có một học phần đạt điểm kết thúc dưới mức trung bình trong năm học đó thì sinh viên có được xét khen thưởng không?"),
            ("2 danh hiệu lớp Đ7", "direct", "Điều 7 quy định hai loại danh hiệu khen thưởng tập thể lớp sinh viên nào?"),
            ("Thủ tục xét khen thưởng Đ8", "direct", "Trình tự xét khen thưởng sinh viên theo Điều 8 đi qua các cấp xác nhận và xét duyệt nào?"),
            # Kỷ luật, chấm dứt hiệu lực, Hội đồng, Nội dung & Tổ chức CTSV (27-68)
            ("4 hình thức kỷ luật", "direct", "Điều 9 quy định bốn hình thức kỷ luật đối với sinh viên vi phạm là những mức nào?"),
            ("Khiển trách khi nào", "paraphrase", "Hình thức kỷ luật Khiển trách áp dụng đối với hành vi vi phạm có tính chất và mức độ như thế nào?"),
            ("Cảnh cáo khi nào", "paraphrase", "Trường hợp nào sinh viên bị áp dụng hình thức kỷ luật Cảnh cáo theo Điều 9?"),
            ("Các mức đình chỉ học", "direct", "Khi áp dụng hình thức đình chỉ học tập có thời hạn, Hiệu trưởng có thể quyết định theo những mức thời gian nào?"),
            ("Án treo và tù giam", "paraphrase", "Sinh viên vi phạm pháp luật bị xử phạt tù nhưng cho hưởng án treo và trường hợp bị tù giam bị xử lý kỷ luật khác nhau thế nào?"),
            ("Buộc thôi học khi nào", "direct", "Những trường hợp nào dẫn đến hình thức kỷ luật cao nhất là Buộc thôi học theo Điều 9?"),
            ("Lưu hồ sơ báo gia đình", "direct", "Từ mức kỷ luật nào trở lên phải lưu vào hồ sơ sinh viên và thông báo về cho gia đình?"),
            ("Báo địa phương kỷ luật", "paraphrase", "Hai hình thức kỷ luật nào bắt buộc nhà trường phải gửi thông báo phối hợp đến cả gia đình và chính quyền địa phương?"),
            ("Không viết tự kiểm điểm", "paraphrase", "Nếu sinh viên vi phạm không chịu viết bản tự kiểm điểm hoặc được mời nhưng vắng mặt không lý do chính đáng thì Hội đồng kỷ luật xử lý thế nào?"),
            ("Hồ sơ kỷ luật 3 thứ", "direct", "Theo khoản 2 Điều 10, hồ sơ xử lý kỷ luật sinh viên gồm những tài liệu bắt buộc nào?"),
            ("Chấm dứt khiển trách 3T", "direct", "Sau thời gian bao lâu kể từ ngày có quyết định kỷ luật Khiển trách thì sinh viên đương nhiên được chấm dứt hiệu lực kỷ luật?"),
            ("Chấm dứt cảnh cáo 6T", "direct", "Thời hạn để quyết định kỷ luật Cảnh cáo đương nhiên chấm dứt hiệu lực nếu không tái phạm là mấy tháng?"),
            ("Thủ tục hết hạn đình chỉ", "paraphrase", "Khi hết thời hạn bị đình chỉ học tập có thời hạn, sinh viên phải xuất trình chứng nhận của cơ quan nào để được xem xét học tiếp?"),
            ("Điều khoản thời hạn QĐ", "direct", "Theo khoản 4 Điều 11, trong quyết định kỷ luật phải ghi rõ mốc thời gian thi hành tính từ lúc nào đến lúc nào?"),
            ("Cơ cấu Hội đồng kỷ luật", "direct", "Điều 12 quy định ai làm Chủ tịch, ai làm Thường trực và ai là các ủy viên Hội đồng khen thưởng và kỷ luật sinh viên?"),
            ("Quyền biểu quyết lớp trưởng", "paraphrase", "Đại diện lớp sinh viên, giáo viên quản lý và cố vấn học tập được mời họp Hội đồng khen thưởng và kỷ luật có quyền biểu quyết không?"),
            ("Quyền khiếu nại kỷ luật", "direct", "Sinh viên thấy hình thức khen thưởng hoặc kỷ luật chưa thỏa đáng có quyền khiếu nại lên những cấp nào theo Điều 13?"),
            ("6 nội dung giáo dục Đ14", "direct", "Điều 14 quy định công tác tổ chức giáo dục, tuyên truyền cho sinh viên gồm sáu mảng nội dung nào?"),
            ("Quản lý hành chính SV", "direct", "Nội dung công tác hành chính trong quản lý sinh viên theo Điều 15 bao gồm những công việc gì?"),
            ("Nội trú ngoại trú ANTT", "direct", "Nhà trường thực hiện công tác quản lý sinh viên nội trú, ngoại trú và phối hợp công an địa phương bảo đảm an ninh trật tự như thế nào?"),
            ("6 dịch vụ hỗ trợ SV", "direct", "Điều 16 quy định sáu nhóm hỗ trợ và dịch vụ sinh viên trong nhà trường gồm những dịch vụ nào?"),
            ("Y tế và BHYT ban đầu", "paraphrase", "Dịch vụ chăm sóc sức khỏe và tư vấn tâm lý sinh viên của trường theo khoản 3 Điều 16 bao gồm những hoạt động gì?"),
            ("Dịch vụ căng tin giữ xe", "direct", "Khoản 6 Điều 16 liệt kê những dịch vụ sinh viên nào do nhà trường tổ chức, quản lý?"),
            ("Hệ thống tổ chức CTSV", "direct", "Hệ thống tổ chức, quản lý công tác sinh viên tại VLUTE theo Điều 17 gồm những thành phần nào?"),
            ("Tuần SHCD và đối thoại", "direct", "Theo khoản 3 Điều 18, Tuần Sinh hoạt công dân - sinh viên được tổ chức vào những thời điểm nào và hoạt động đối thoại diễn ra định kỳ ra sao?"),
            ("Phân biệt GVQL vs CVHT", "paraphrase", "Sự khác nhau giữa thẩm quyền phân công và nhiệm vụ của Giáo viên quản lý sinh viên và Cố vấn học tập theo Điều 19 là gì?"),
            ("Lớp sinh viên và nhiệm kỳ BCS", "direct", "Ban cán sự lớp sinh viên gồm ai, do ai bầu/công nhận và nhiệm kỳ kéo dài bao lâu?"),
            ("Quyền lợi Ban cán sự lớp", "paraphrase", "Ban cán sự lớp sinh viên và Ban cán sự lớp học phần được hưởng quyền lợi ưu tiên gì khi thực hiện nhiệm vụ?"),
            ("Lớp học phần do ai chỉ định", "paraphrase", "Lớp trưởng và lớp phó của lớp học phần được thành lập bằng cách bầu hay do nhà trường chỉ định và nhiệm kỳ theo thời gian nào?"),
            ("Báo cáo Bộ GD&ĐT Đ22", "direct", "Khi có vụ việc phức tạp, nghiêm trọng liên quan đến sinh viên, nhà trường gửi báo cáo cho Bộ Giáo dục và Đào tạo theo chế độ nào?"),
            # Phụ lục Khung xử lý kỷ luật 27 mục (57-100)
            ("Đi muộn từ 5 phút", "direct", "Theo Phụ lục khung xử lý kỷ luật, sinh viên đến muộn giờ học hoặc giờ thực tập từ 05 phút trở lên bị khiển trách, cảnh cáo, đình chỉ, buộc thôi học từ lần vi phạm thứ mấy?"),
            ("Nghỉ học không phép", "direct", "Sinh viên nghỉ học không phép hoặc trễ phép cộng dồn trong khóa học bao nhiêu ngày thì bị khiển trách, cảnh cáo, đình chỉ và buộc thôi học?"),
            ("Nghỉ không phép 5 ngày", "paraphrase", "Nếu em nghỉ học không phép tổng cộng 5 ngày trong khóa học thì tương ứng với mức kỷ luật nào trong Phụ lục?"),
            ("Nghỉ không phép trên 8 ngày", "paraphrase", "Nghỉ học không phép vượt quá 8 ngày tính trong cả khóa học sẽ đối mặt với hình thức kỷ luật gì?"),
            ("Mất trật tự làm việc riêng", "direct", "Hành vi gây mất trật tự, làm việc riêng trong giờ học, thực tập, tự học bị khiển trách từ lần thứ mấy và buộc thôi học ở lần thứ mấy?"),
            ("Vô lễ giảng viên CBVC", "paraphrase", "Sinh viên có thái độ vô lễ với thầy cô giáo và cán bộ viên chức nhà trường bị xử lý ở khung kỷ luật nào?"),
            ("Học thay nhờ học thay", "paraphrase", "Đi học thay cho bạn hoặc nhờ người khác đi học thay bị xử lý kỷ luật ra sao theo mục 4 Phụ lục?"),
            ("Thi hộ nhờ thi thay sao chép", "direct", "Sinh viên thi, kiểm tra thay hoặc nhờ người thi thay, sao chép làm thay tiểu luận, đồ án, khóa luận tốt nghiệp bị xử lý từ lần 1 và lần 2 như thế nào?"),
            ("Tổ chức học thi thay", "direct", "Hành vi tổ chức học, thi, kiểm tra thay hoặc tổ chức làm thay đồ án, khóa luận tốt nghiệp bị kỷ luật mức nào ngay ở lần 1?"),
            ("Mang tài liệu bỏ thi", "paraphrase", "Mang tài liệu vào phòng thi, đưa đề thi ra ngoài nhờ làm thay hoặc bỏ thi không có lý do chính đáng xử lý theo quy định nào?"),
            ("Chậm nộp học phí BHYT", "paraphrase", "Cố tình chậm nộp hoặc không nộp học phí, bảo hiểm y tế không có lý do chính đáng bị xử lý kỷ luật từ mức nào đến mức nào?"),
            ("Làm hư hỏng tài sản KTX", "paraphrase", "Sinh viên làm hư hỏng tài sản trong ký túc xá hoặc tài sản của trường ngoài bị kỷ luật từ khiển trách đến buộc thôi học còn phải làm gì?"),
            ("Uống rượu bia giờ học", "direct", "Uống rượu bia trong giờ học hoặc say rượu bia khi đến lớp bị xử lý kỷ luật ở lần 1, lần 2, lần 3 và lần 4 lần lượt ra sao?"),
            ("Hút thuốc phòng thí nghiệm", "direct", "Sinh viên hút thuốc lá trong giờ học, phòng họp, phòng thí nghiệm và nơi cấm bị xử lý kỷ luật từ lần vi phạm thứ mấy?"),
            ("Đánh bạc dưới mọi hình thức", "direct", "Sinh viên đánh bạc lần 1, lần 2, lần 3 và lần 4 bị xử lý kỷ luật thế nào theo mục 12 Phụ lục?"),
            ("Văn hóa phẩm đồi trụy mê tín", "direct", "Tàng trữ, lưu hành, truy cập sản phẩm văn hóa đồi trụy hoặc tham gia mê tín dị đoan, tôn giáo trái phép xử lý lần 1 đến lần 4 ra sao?"),
            ("Buôn bán vận chuyển ma túy", "paraphrase", "Sinh viên buôn bán, vận chuyển, tàng trữ hoặc lôi kéo người khác sử dụng ma túy bị xử lý kỷ luật gì ngay lần đầu?"),
            ("Sử dụng ma túy mục 15", "paraphrase", "Trường hợp sinh viên bị phát hiện sử dụng ma túy sẽ được xử lý theo quy định cụ thể nào tại mục 15 Phụ lục?"),
            ("Chứa chấp môi giới mại dâm", "direct", "Hành vi chứa chấp, môi giới mại dâm tại mục 16 Phụ lục bị xử lý hình thức kỷ luật nào ngay lần 1?"),
            ("Hoạt động mại dâm mục 17", "direct", "Sinh viên tham gia hoạt động mại dâm lần 1, lần 2, lần 3, lần 4 chịu khung kỷ luật như thế nào?"),
            ("Lấy cắp tài sản mục 18", "direct", "Hành vi lấy cắp tài sản, chứa chấp hoặc tiêu thụ tài sản do trộm cắp mà có bị xử lý từ mức nào đến mức nào?"),
            ("Chứa chấp vũ khí chất nổ", "paraphrase", "Tàng trữ, buôn bán vũ khí, chất nổ và hàng cấm ngoài xử lý nội bộ nhà trường còn phải giao cho ai xử lý?"),
            ("Đưa phần tử xấu vào KTX", "direct", "Hành vi đưa phần tử xấu vào trong trường hoặc ký túc xá gây mất an ninh trật tự bị xử lý theo khung kỷ luật nào?"),
            ("Đánh nhau tổ chức đánh nhau", "direct", "Sinh viên đánh nhau hoặc tổ chức, tham gia tổ chức đánh nhau bị kỷ luật mức nào ở lần 1 và lần 2?"),
            ("Kích động biểu tình truyền đơn", "direct", "Hành vi kích động, lôi kéo người khác biểu tình hoặc viết truyền đơn, áp phích trái pháp luật bị xử lý ra sao ngay lần 1?"),
            ("Tham gia biểu tình tụ tập", "direct", "Sinh viên tham gia biểu tình, tụ tập đông người, khiếu kiện trái pháp luật lần 1, lần 2 và lần 3 bị xử lý kỷ luật gì?"),
            ("Đăng tải xuyên tạc Internet", "direct", "Đăng tải, bình luận, chia sẻ bài viết hoặc hình ảnh bạo lực, đồi trụy, xuyên tạc, vu khống trên Internet bị xử lý thế nào?"),
            ("Quấy rối xâm phạm đời tư", "direct", "Hành vi quấy rối, dâm ô, xâm phạm nhân phẩm và đời tư của người khác tại mục 25 Phụ lục bị xử lý theo khung nào?"),
            ("Vi phạm an toàn giao thông", "paraphrase", "Sinh viên vi phạm các quy định về an toàn giao thông theo mục 26 Phụ lục có thể bị áp dụng những hình thức nhắc nhở hay kỷ luật nào?"),
            ("Tính số lần vi phạm cả khóa", "direct", "Số lần vi phạm trong Phụ lục khung xử lý kỷ luật sinh viên được tính cộng dồn theo học kỳ, năm học hay cả khóa học?"),
            ("Đi muộn lần 4 bị gì", "paraphrase", "Em đi học trễ trên 5 phút đến lần thứ 4 trong khóa học thì bị khiển trách hay cảnh cáo?"),
            ("Uống bia lần 2 trong lớp", "paraphrase", "Lần thứ 2 uống rượu bia trong giờ học hoặc say xỉn đến lớp sẽ bị mức kỷ luật nào?"),
            ("Đánh nhau lần 1 bị đình chỉ", "paraphrase", "Đánh nhau trong trường ngay lần đầu tiên có bị đình chỉ học tập không hay chỉ bị khiển trách?"),
            ("Thi hộ lần 2 bị gì", "paraphrase", "Nếu đã từng bị đình chỉ vì thi hộ ở lần 1 mà vẫn tái phạm thi thay hoặc sao chép khóa luận lần 2 thì sao?"),
            ("Nghỉ không phép 3 ngày", "paraphrase", "Tổng cộng 3 ngày nghỉ học không phép trong cả khóa học rơi vào khung kỷ luật nào?"),
            ("Nghỉ không phép 7 ngày", "paraphrase", "Nghỉ học không phép 7 ngày trong khóa học bị xử lý cảnh cáo hay đình chỉ học tập có thời hạn?"),
            ("Tụ tập khiếu kiện lần 3", "paraphrase", "Tham gia tụ tập đông người, khiếu kiện trái quy định pháp luật đến lần thứ 3 thì nhận án kỷ luật nào?"),
            ("Hồ sơ tự kiểm điểm vắng mặt", "paraphrase", "Nếu sinh viên bị mời họp Hội đồng kỷ luật mà vắng mặt không lý do chính đáng thì Hội đồng xem xét thêm khuyết điểm gì?"),
            ("Nhiệm vụ BCS lớp học phần", "direct", "Ban cán sự lớp học phần có trách nhiệm báo cáo việc chấp hành nội quy, quy chế của sinh viên cho những đơn vị nào?"),
            ("Xóa kỷ luật khiển trách", "paraphrase", "Sinh viên bị khiển trách từ tháng 3, nếu 3 tháng sau không tái phạm thì quyền lợi sinh viên có được khôi phục tự động không?"),
            ("Xác nhận địa phương sau đình chỉ", "paraphrase", "Hết thời hạn 1 năm bị đình chỉ học tập, sinh viên phải xin giấy xác nhận chấp hành tốt nghĩa vụ công dân ở UBND cấp nào?"),
            ("Mục đích Đ12 Hội đồng", "direct", "Ai quy định cụ thể chức năng, nhiệm vụ và tổ chức hoạt động của Hội đồng khen thưởng và kỷ luật sinh viên?"),
            ("Đoàn Hội trong CTSV", "direct", "Vai trò của tổ chức Đoàn TNCS Hồ Chí Minh và Hội Sinh viên Việt Nam trong nhiệm vụ của Hiệu trưởng tại Điều 18 là gì?"),
            ("So sánh kỷ luật Đ7 vs Đ9", "paraphrase", "Sinh viên bị kỷ luật từ mức khiển trách trở lên trong năm học có ảnh hưởng gì đến việc xét danh hiệu thi đua cá nhân cuối năm không?"),
        ],
    },
    "tin_chi_cong_tac_xa_hoi.pdf": {
        "expected_dept": "Phòng Công tác Sinh viên (VLUTE)",
        "questions": [
            # QĐ, chuẩn 12 ngày, miễn giảm, quy định tốt nghiệp (1-24)
            ("QĐ 575 ngày CTXH", "direct", "Quy định chuẩn tham gia hoạt động Công tác xã hội đối với sinh viên đại học chính quy ban hành theo Quyết định số mấy và ngày nào?"),
            ("Đơn vị áp dụng CTXH", "direct", "Quy định chuẩn tích lũy ngày CTXH áp dụng cho hệ đào tạo nào tại Trường Đại học Sư phạm Kỹ thuật Vĩnh Long?"),
            ("Định nghĩa ngày CTXH", "direct", "Theo Điều 2, số ngày CTXH và chuẩn tham gia hoạt động CTXH được định nghĩa như thế nào?"),
            ("Căn cứ Luật GDĐH CTXH", "direct", "Điều 3 Quy định CTXH viện dẫn các căn cứ pháp lý nào từ Nghị quyết Trung ương VIII, Luật Giáo dục Đại học và Thông tư 10/2016?"),
            ("Mục đích hoạt động CTXH", "direct", "Điều 4 nêu hai mục đích chính của việc quy định tham gia hoạt động công tác xã hội đối với sinh viên là gì?"),
            ("SV khuyết tật miễn CTXH", "direct", "Sinh viên khuyết tật không thể tham gia hoạt động cộng đồng có được miễn tích lũy 12 ngày CTXH không và phải tham gia thay thế hoạt động gì?"),
            ("Miễn giảm do sức khỏe", "paraphrase", "Sinh viên gặp vấn đề sức khỏe khó tham gia hoạt động CTXH cần nộp hồ sơ gì để Nhà trường xem xét miễn giảm số ngày CTXH?"),
            ("Chuẩn tối thiểu 12 ngày", "direct", "Sinh viên đại học hệ chính quy cần tích lũy đủ tối thiểu bao nhiêu ngày công tác xã hội trong toàn khóa học?"),
            ("Bằng ĐH thứ hai CTXH", "paraphrase", "Thời gian đào tạo thuộc Chương trình đào tạo lấy bằng Đại học thứ hai có phải tính chuẩn tích lũy ngày CTXH không?"),
            ("Phân bổ khuyến nghị 4-4-3-1", "direct", "Nhà trường khuyến nghị sinh viên phân bổ số ngày CTXH theo từng năm học từ năm nhất đến năm tư như thế nào?"),
            ("Điều kiện 2/3 đăng ký TN", "direct", "Sinh viên phải tích lũy ít nhất bao nhiêu phần trăm (tương đương mấy ngày) chuẩn CTXH mới được xét đăng ký các học phần tốt nghiệp?"),
            ("Đủ chuẩn mới xét tốt nghiệp", "paraphrase", "Nếu chỉ đạt 10 trên 12 ngày công tác xã hội thì sinh viên có đủ điều kiện được xét công nhận tốt nghiệp không?"),
            ("CTXH tại địa phương", "paraphrase", "Sinh viên có được phép tham gia hoạt động CTXH ngoài trường tại địa phương cư trú không và cần giấy tờ gì để công nhận?"),
            ("Từ chối công nhận CTXH", "direct", "Trong trường hợp nào Nhà trường có quyền từ chối không công nhận số ngày CTXH đã tham gia tại địa phương?"),
            ("Đầu mối tổ chức CTXH", "direct", "Tổ chức nào chịu trách nhiệm chỉ đạo, phối hợp tổ chức các hoạt động CTXH và đánh giá kết quả cho sinh viên?"),
            ("Tổng hợp trình xét TN", "direct", "Hai đơn vị nào phối hợp tổng hợp kết quả tích lũy ngày CTXH để tham mưu Hội đồng xét tốt nghiệp?"),
            ("Bảy loại hình CTXH Đ7", "direct", "Điều 7 phân chia các hoạt động công tác xã hội được tính ngày thành những nhóm loại hình nào?"),
            ("Không phù hợp Đ7", "paraphrase", "Đối với những hoạt động không nằm trong danh mục loại hình CTXH thông thường tại Điều 7, trường hợp đặc biệt do ai quyết định?"),
            # Bảng quy đổi ngày CTXH & Trừ ngày (25-71)
            ("Mã 001101 Mùa hè xanh", "direct", "Hoạt động Mùa hè xanh có mã số là gì, yêu cầu làm việc tối thiểu bao nhiêu giờ mỗi ngày và được quy đổi bao nhiêu ngày CTXH?"),
            ("Mã 001201 vs 001202 hiến máu", "direct", "Sự khác biệt về số ngày CTXH quy đổi giữa hỗ trợ tổ chức hiến máu (001201) và trực tiếp hiến máu tình nguyện (001202) là bao nhiêu?"),
            ("Mã 001301 Tiếp sức mùa thi", "direct", "Tham gia Tiếp sức mùa thi mã 001301 yêu cầu tối thiểu mấy giờ một ngày và quy đổi mấy ngày CTXH?"),
            ("Mã 001401 001402 tư vấn TS", "direct", "Sinh viên tham gia Ngày hội tư vấn hướng nghiệp - tuyển sinh hoặc hướng dẫn học sinh THPT tham quan trường được tính bao nhiêu ngày CTXH mỗi ca?"),
            ("Mã 001501 Tiếp sức tân SV", "direct", "Hoạt động Tiếp sức tân sinh viên mã 001501 yêu cầu thời gian làm việc ra sao và quy đổi được bao nhiêu ngày CTXH?"),
            ("Quyên góp tối thiểu 50.000đ", "direct", "Các mã quyên góp cứu trợ thiên tai (001601), nhà tình nghĩa (001602), giúp SV khó khăn (001603) yêu cầu mức tối thiểu bao nhiêu tiền và quy đổi mấy ngày?"),
            ("Mã 001701 001702 công ích 2.5h", "direct", "Tham gia Ngày thứ bảy tình nguyện, Chủ nhật xanh hoặc dọn dẹp xưởng thực hành, thư viện 01 buổi kéo dài mấy giờ và được mấy ngày CTXH?"),
            ("Mã 001801 vs 001802 ngoài trường", "direct", "Hoạt động tình nguyện tại địa bàn dân cư mã 001801 (5 giờ) và dọn vệ sinh địa bàn dân cư mã 001802 (2.5 giờ) quy đổi lần lượt mấy ngày CTXH?"),
            ("Mã 001901-001904 chính sách", "direct", "Thăm Mẹ Việt Nam anh hùng, tôn tạo nghĩa trang liệt sĩ, chăm sóc người già neo đơn và trẻ em trung tâm (001901–001904) quy đổi mỗi buổi mấy ngày CTXH?"),
            ("Mã 002001 cán bộ cấp trường", "direct", "Cán bộ Đoàn, Hội từ cấp trường trở lên (mã 002001) hoàn thành nhiệm vụ ở các mức 50%, 75%, 100% được quy đổi tương ứng mấy ngày CTXH?"),
            ("Mã 002002 cán bộ cấp khoa", "direct", "Cán bộ Đoàn, Hội cấp khoa và Ban chủ nhiệm CLB (mã 002002) đạt 50%, 75%, 100% nhiệm vụ nhận bao nhiêu ngày CTXH?"),
            ("Mã 002003 tham gia CLB đội hình", "direct", "Sinh viên tham gia các đội hình tình nguyện cấp trường, CTXH cấp khoa hoặc CLB (mã 002003) quy đổi theo mức 50%, 75%, 100% được mấy ngày?"),
            ("Mã 002101 002103 002106 cấp trường", "direct", "Tham gia tổ chức hoặc dự thi văn nghệ, thể dục thể thao, chuyên môn cấp trường (mã 002101, 002103, 002106) được quy đổi bao nhiêu ngày CTXH theo từng mức?"),
            ("Mã 002102 cấp khoa", "direct", "Tham gia tổ chức hoặc thi đấu hội thi, hội thao cấp khoa được quy đổi 1, 1.5 hay 2 ngày CTXH tương ứng các mức hoàn thành nào?"),
            ("Mã 002104 biểu diễn văn nghệ", "direct", "Sinh viên tham gia biểu diễn văn nghệ trong một sự kiện của trường (mã 002104) được cộng mấy ngày CTXH?"),
            ("Mã 002107 thành viên CLB Đội", "direct", "Hoàn thành nhiệm vụ thành viên các Câu lạc bộ, Đội đánh giá theo học kỳ (mã 002107) được quy đổi trong khoảng bao nhiêu ngày CTXH?"),
            ("Mã 002108 Mitting bên ngoài", "direct", "Được nhà trường điều động tham dự Mitting tổ chức bên ngoài trường (mã 002108) quy đổi được mấy ngày CTXH mỗi đợt?"),
            ("Mã 002109 cổ vũ văn nghệ TDTT", "direct", "Xem một buổi trình diễn văn hóa nghệ thuật, chiếu phim hoặc xem cổ vũ thi đấu thể thao tại trường (mã 002109) được tính mấy ngày CTXH?"),
            ("Mã 002110 002111 chuyên đề hội thảo", "direct", "Tham dự một buổi sinh hoạt chuyên đề chính trị pháp luật (002110) hoặc một hội thảo tại trường (002111) được quy đổi bao nhiêu ngày CTXH?"),
            ("Mã 002201 nội dung khác", "direct", "Các hoạt động đặc biệt thuộc mã 002201 quy đổi 0.5 ngày CTXH do cơ quan nào của Đoàn - Hội quyết định?"),
            ("Hiến máu trực tiếp được mấy ngày", "paraphrase", "Nếu em trực tiếp đi hiến máu và có giấy xác nhận hiến máu thì được cộng 0.5 ngày hay 1 ngày CTXH?"),
            ("Quyên góp 100k có được 1 ngày", "paraphrase", "Quy định quyên góp giúp đồng bào thiên tai yêu cầu mức tối thiểu bao nhiêu để ghi nhận 0.5 ngày CTXH?"),
            ("Kiêm nhiệm nhiều chức vụ Đoàn Hội", "paraphrase", "Nếu sinh viên kiêm nhiệm nhiều nhiệm vụ cán bộ Đoàn, Hội, Ban chủ nhiệm CLB cùng lúc thì tính ngày CTXH cho cả hai hay tính một mức cao nhất?"),
            ("Xác nhận giấy tờ 001401 002003", "paraphrase", "Tham gia Ngày hội tư vấn tuyển sinh hoặc đội hình tình nguyện cấp trường cần có xác nhận của ai để được công nhận ngày CTXH?"),
            ("Thời gian làm việc 1 ca vs 1 ngày", "paraphrase", "Một buổi làm việc công ích như Chủ nhật xanh quy định kéo dài mấy giờ và một ngày làm việc tình nguyện tối thiểu mấy giờ?"),
            ("Đăng ký nhưng bỏ không lý do", "direct", "Theo khoản 1 Điều 9, sinh viên đã đăng ký hoạt động CTXH mà tự ý không tham gia không lý do chính đáng bị trừ bao nhiêu ngày?"),
            ("Làm xấu uy tín hoạt động CTXH", "paraphrase", "Sinh viên đăng ký tham gia hoạt động CTXH nhưng không hoàn thành nhiệm vụ làm ảnh hưởng xấu uy tín Nhà trường bị kỷ luật và trừ bao nhiêu ngày CTXH?"),
            ("Vắng họp Chi đoàn GVQL", "direct", "Vắng họp Chi đoàn - Chi hội hoặc vắng họp do Giáo viên quản lý - Cố vấn học tập triệu tập không lý do bị trừ mấy ngày CTXH?"),
            ("Nộp trễ Đoàn phí Hội phí", "paraphrase", "Sinh viên nộp Đoàn phí, Hội phí trễ so với quy định bị trừ bao nhiêu ngày CTXH?"),
            # Quy trình 7 bước, kinh phí, đánh giá hàng năm/cuối khóa, trách nhiệm (48-100)
            ("Bước 1 lập kế hoạch CTXH", "direct", "Kế hoạch tổ chức hoạt động CTXH tại Bước 1 được xây dựng công bố vào lúc nào và cần nêu rõ những nội dung nào?"),
            ("Đề xuất CTXH tại trường", "direct", "Đơn vị nào quyết định tổ chức hoạt động CTXH tại trường và vai trò đề xuất của BCH chi đoàn, chi hội là gì?"),
            ("Đề xuất CTXH tại địa phương", "paraphrase", "Khi địa phương hoặc tập thể sinh viên đề xuất tổ chức hoạt động CTXH ngoài trường thì phải gửi văn bản qua đầu mối nào quyết định?"),
            ("Ưu tiên khi vượt quy mô", "paraphrase", "Bước 2 quy định nếu số lượng sinh viên đăng ký tham gia vượt quá quy mô chương trình CTXH thì ưu tiên chọn đối tượng nào?"),
            ("Bước 3 và 4 tại địa phương", "direct", "Khi tổ chức hoạt động CTXH tại địa phương, ai chịu trách nhiệm đánh giá, cho điểm và ký tên vào phiếu đánh giá?"),
            ("Bước 4 tại trường ký đóng dấu", "direct", "Đối với hoạt động CTXH cấp trường trở lên, cấp nào ký tên và đóng dấu vào phiếu đánh giá hoạt động CTXH?"),
            ("Bước 5 nhập kết quả 2 tuần", "direct", "Chậm nhất bao lâu sau khi kết thúc hoạt động CTXH, Ban tổ chức Đoàn - Hội cấp khoa trở lên phải nhập và công bố kết quả?"),
            ("Bước 6 khiếu nại 10 ngày", "direct", "Sinh viên được phép nộp đơn khiếu nại kết quả đánh giá hoạt động CTXH trong vòng bao nhiêu ngày sau khi công bố?"),
            ("Gửi đơn khiếu nại cho ai", "paraphrase", "Đơn khiếu nại sai sót điểm hoặc ngày CTXH gửi trực tiếp cho ai và kết quả điều chỉnh được thông báo qua kênh nào?"),
            ("Bước 7 chuyển bảng điểm 20 ngày", "direct", "Chậm nhất bao nhiêu ngày sau khi kết thúc hoạt động CTXH, các đơn vị phải chuyển bản chính bảng điểm về BTV Đoàn trường hoặc BTK Hội Sinh viên?"),
            ("Lưu danh sách đạt chuẩn TN", "direct", "Phòng ban nào lưu trữ danh sách sinh viên đã đạt chuẩn ngày CTXH để phối hợp xét tốt nghiệp cuối khóa?"),
            ("3 nguồn kinh phí CTXH", "direct", "Theo Điều 11, kinh phí tổ chức hoạt động CTXH tại trường được huy động từ ba nguồn nào?"),
            ("Xử lý kết quả hàng năm T9", "direct", "Đầu tháng 9 hàng năm, BCH Khoa và Chi đoàn - Chi hội thực hiện quy trình thống kê và công bố kết quả CTXH năm học ra sao?"),
            ("Xử lý kết quả cuối khóa T5", "direct", "Đầu tháng 5 hàng năm, nhà trường công bố danh sách cảnh báo cho sinh viên năm tư chưa đủ ngày CTXH để kịp bổ sung vào thời gian nào?"),
            ("Thành phần nhóm kiểm tra", "direct", "Nhóm kiểm tra số liệu CTXH do Đoàn trường - Hội Sinh viên lập ra gồm bốn thành phần nào?"),
            ("Nơi lưu minh chứng báo cáo", "direct", "Bản chính số liệu minh chứng và báo cáo tổng kết ngày CTXH hàng năm và cuối khóa được lưu trữ tại văn phòng nào?"),
            ("Báo cáo sang Phòng Đào tạo", "paraphrase", "BTV Đoàn trường và BTK Hội Sinh viên chuyển danh sách sinh viên đủ ngày CTXH sang Phòng Đào tạo nhằm phục vụ việc gì?"),
            ("Trách nhiệm Bí thư đoàn khoa", "direct", "Trong Điều 13, Bí thư đoàn khoa tại các khoa chuyên môn chịu trách nhiệm gì về hoạt động CTXH?"),
            ("Trách nhiệm của Phòng CTSV", "direct", "Phòng Công tác sinh viên đảm nhận những nhiệm vụ nào trong Điều 13 Quy định hoạt động CTXH?"),
            ("Trách nhiệm Đoàn - Hội trường", "direct", "Theo khoản 2 Điều 13, Đoàn Thanh niên và Hội Sinh viên trường có trách nhiệm giải quyết khiếu nại và xác minh những trường hợp nào?"),
            ("Trách nhiệm của sinh viên CTXH", "direct", "Khoản 5 Điều 13 quy định sinh viên tự chịu trách nhiệm gì về số ngày CTXH trước khi xét tốt nghiệp?"),
            ("Công khai quy định CTXH", "direct", "Quy định chuẩn tham gia hoạt động CTXH được công khai ở đâu để toàn thể sinh viên chính quy nắm bắt?"),
            ("Khen thưởng tập thể CTXH", "direct", "Đơn vị nào đề nghị Ban Giám hiệu khen thưởng các tập thể và cá nhân có thành tích xuất sắc trong phong trào CTXH?"),
            ("Thay đổi bổ sung quy định CTXH", "direct", "Khi phát sinh vướng mắc cần sửa đổi Quy định ngày CTXH, các đơn vị báo cáo Hiệu trưởng bằng văn bản thông qua phòng nào?"),
            ("Năm tư cần tích lũy mấy ngày", "paraphrase", "Theo phân bổ khuyến nghị của trường, nếu 3 năm đầu sinh viên làm theo đúng lịch 4-4-3 thì sang năm thứ tư chỉ cần tích lũy thêm mấy ngày CTXH?"),
            ("2 phần 3 của 12 ngày là mấy ngày", "paraphrase", "Sinh viên đã tích lũy được 7 ngày CTXH (trên chuẩn 12 ngày) thì đã đủ mức 2/3 để đăng ký học phần tốt nghiệp chưa?"),
            ("Hoạt động dọn xưởng 001702", "paraphrase", "Tham gia lao động vệ sinh xưởng thực hành, phòng thí nghiệm hoặc thư viện 1 buổi 2.5 giờ được tính mấy ngày CTXH?"),
            ("Mã 001603 giúp SV khó khăn", "paraphrase", "Sinh viên quyên góp 50.000 đồng giúp đỡ sinh viên hoàn cảnh khó khăn theo mã 001603 được công nhận bao nhiêu ngày CTXH?"),
            ("Làm mất uy tín bị trừ bao nhiêu", "paraphrase", "Sinh viên tham gia hoạt động CTXH gây ảnh hưởng xấu hình ảnh nhà trường có thể bị trừ tối đa bao nhiêu ngày đã tích lũy?"),
            ("Họp lớp hay email báo kết quả", "paraphrase", "Đầu tháng 9 hàng năm, BCH Chi đoàn, Chi hội thông báo kết quả CTXH để sinh viên kiểm tra bổ sung thông qua hình thức nào?"),
            ("Thời gian khắc phục thiếu CTXH", "paraphrase", "Nếu tháng 5 năm cuối sinh viên bị cảnh báo thiếu ngày CTXH thì còn hai khoảng thời gian nào để làm bù trước khi xét tốt nghiệp?"),
            ("Biên bản kiểm tra số liệu", "direct", "Sau khi nhóm kiểm tra đối chiếu số liệu CTXH từ các Khoa thì phải lập văn bản gì gửi BTV Đoàn trường và BTK Hội Sinh viên?"),
            ("Đoàn viên Đảng viên SV kiểm tra", "paraphrase", "Ngoài Bí thư chi đoàn, Chi hội sinh viên và BCH Khoa, thành viên nào bắt buộc có mặt trong nhóm kiểm tra số liệu CTXH?"),
            ("Số giờ tối thiểu Mùa hè xanh", "paraphrase", "Tham gia đội hình chuyên Mùa hè xanh hay Tiếp sức mùa thi mỗi ngày tính chuẩn phải làm ít nhất bao nhiêu giờ?"),
            ("Thứ bảy tình nguyện mấy giờ", "paraphrase", "Một buổi Ngày thứ bảy tình nguyện hoặc Chủ nhật xanh yêu cầu kéo dài trong bao nhiêu giờ để được tính 0.5 ngày CTXH?"),
            ("Tư vấn THPT tham quan VLUTE", "paraphrase", "Sinh viên được huy động hướng dẫn học sinh THPT đến tham quan tại trường (mã 001402) thì 1 ca trực tính mấy ngày CTXH?"),
            ("Cấp trường hoàn thành 75% CLB", "paraphrase", "Sinh viên làm cán bộ Đoàn, Hội cấp trường đạt mức đánh giá 75% nhiệm vụ nhận được mấy ngày CTXH?"),
            ("Hội thao cấp khoa mức 50%", "paraphrase", "Tham gia tổ chức hoặc thi đấu hội thao cấp khoa hoàn thành ở mức 50% nhiệm vụ được tính bao nhiêu ngày CTXH?"),
            ("Cổ vũ thể thao tính CTXH", "paraphrase", "Đi xem và cổ vũ một trận thi đấu thể thao hoặc xem chiếu phim tại trường theo mã 002109 có được cộng ngày CTXH không và được mấy ngày?"),
            ("Tham dự hội thảo mã 002111", "paraphrase", "Sinh viên tham dự 01 hội thảo tại trường theo mã 002111 được quy đổi bao nhiêu ngày CTXH?"),
            ("Thăm Mẹ VN anh hùng 001901", "paraphrase", "Tham gia thăm hỏi, phụng dưỡng Bà mẹ Việt Nam anh hùng hoặc thương binh 1 buổi 2.5 giờ quy đổi bao nhiêu ngày CTXH?"),
            ("Thắp nến tri ân liệt sĩ 001902", "paraphrase", "Hoạt động tôn tạo nghĩa trang liệt sĩ và thắp nến tri ân anh hùng liệt sĩ mã 001902 quy đổi mấy ngày CTXH?"),
            ("Chăm sóc người già trẻ em", "paraphrase", "Đi trung tâm nuôi dưỡng người cao tuổi (001903) hoặc chăm sóc trẻ em tại trung tâm tình nguyện (001904) 2.5 giờ tính bao nhiêu ngày CTXH?"),
            ("Quyên góp xây nhà tình nghĩa", "paraphrase", "Tham gia quyên góp xây nhà tình nghĩa, tình thương theo mã 001602 yêu cầu mức tiền tối thiểu bao nhiêu để tính 0.5 ngày CTXH?"),
            ("Thời gian điều chỉnh khiếu nại", "paraphrase", "Khi giải quyết đơn khiếu nại của sinh viên và có thay đổi kết quả CTXH, đơn vị tổ chức phản hồi cập nhật qua những phương thức nào?"),
            ("Quy trình gửi bản gốc bảng điểm", "paraphrase", "Sau 2 tuần công bố điểm CTXH và 10 ngày khiếu nại, tổng thời hạn tối đa phải nộp bản chính bảng điểm về Đoàn trường là mấy ngày?"),
            ("Nơi xác nhận hoạt động địa phương", "paraphrase", "Nếu sinh viên tham gia tình nguyện tại xã, phường quê nhà thì cần có văn bản gì trước và xác nhận gì sau hoạt động để được tính ngày CTXH?"),
            ("Sinh hoạt chuyên đề pháp luật", "paraphrase", "Tham gia 1 buổi sinh hoạt chuyên đề chính trị hoặc phổ biến pháp luật mã 002110 mang lại bao nhiêu ngày CTXH?"),
            ("Cán bộ CLB mức 100%", "paraphrase", "Thành viên Ban chủ nhiệm câu lạc bộ hoàn thành 100% trách nhiệm học kỳ (mã 002002) được cộng tối đa mấy ngày CTXH?"),
            ("Trừ ngày nộp trễ hội phí", "paraphrase", "Quên đóng Đoàn phí hoặc Hội phí đúng hạn có làm giảm số ngày CTXH tích lũy của sinh viên không và trừ mấy ngày?"),
            ("Ai ra quyết định không nêu trong QĐ", "direct", "Đối với những tình huống phát sinh chưa được quy định trong Quy định chuẩn CTXH, thẩm quyền quyết định thuộc về ai?"),
            ("Phối hợp của giảng viên Đ13", "direct", "Theo khoản 4 Điều 13, giảng viên giảng dạy và các phòng/trung tâm chức năng có trách nhiệm gì giúp sinh viên hoàn thành CTXH?"),
            ("Số lượng tối đa hoạt động 0.5", "paraphrase", "Liệt kê những hoạt động có định mức quy đổi 0.5 ngày CTXH trong Điều 8 như hiến máu hỗ trợ, quyên góp, công ích 2.5 giờ, hội thảo, chuyên đề."),
        ],
    },
    "quy_tac_ung_xu.pdf": {
        "expected_dept": "Phòng Công tác Sinh viên (VLUTE)",
        "questions": [
            # Quyết định, Chương 1-2 quy tắc chung & 5S tài sản công (1-24)
            ("QĐ 367 Quy tắc ứng xử", "direct", "Quy tắc ứng xử của cán bộ quản lý, viên chức, người lao động, học viên và sinh viên tại VLUTE ban hành kèm theo Quyết định số mấy và ngày nào?"),
            ("Thay thế QĐ 351 năm 2022", "direct", "Quyết định 367/QĐ-ĐHSPKTVL ngày 18/9/2023 bãi bỏ quyết định quy tắc ứng xử cũ nào trước đây?"),
            ("Đơn vị trình Quy tắc ứng xử", "direct", "Quy tắc ứng xử năm 2023 được Hiệu trưởng ban hành theo đề nghị của Trưởng phòng nào và dựa trên Đề án văn hóa ứng xử giai đoạn nào?"),
            ("3 mục đích Quy tắc ứng xử", "direct", "Điều 1 quy định ba mục đích của Quy tắc ứng xử trong nhà trường là gì?"),
            ("Phạm vi đơn vị liên kết", "direct", "Phạm vi áp dụng Quy tắc ứng xử tại Điều 2 có bao gồm các đơn vị liên kết đặt văn phòng trong khuôn viên trường không?"),
            ("Hai nhóm đối tượng CBVC và SV", "direct", "Văn bản Quy tắc ứng xử dùng hai thuật ngữ viết tắt CBVC và người học để chỉ những đối tượng cụ thể nào?"),
            ("Bình luận làm tổn hại uy tín", "direct", "Theo khoản 2 Điều 3, cán bộ và người học bị cấm phát ngôn, bình luận hoặc hành động gây ảnh hưởng gì đến nhà trường?"),
            ("Quy định đồ uống có cồn chung", "paraphrase", "Trong khuôn viên trường có trường hợp ngoại lệ nào được phép sử dụng đồ uống có cồn theo khoản 4 Điều 3 không?"),
            ("Ứng xử trên mạng xã hội Đ3", "direct", "Khoản 5 Điều 3 nghiêm cấm hành vi gì khi sử dụng mạng xã hội?"),
            ("Ngôn ngữ giao tiếp ứng xử", "direct", "Theo khoản 8 Điều 3, ngôn ngữ trong giao tiếp và ứng xử hàng ngày tại trường cần đáp ứng chuẩn mực gì và cấm nói những lời nào?"),
            ("Trang phục đồng phục chung Đ3", "direct", "Khoản 9 Điều 3 quy định thế nào về trang phục và việc mặc đồng phục theo quy định nhà trường?"),
            ("Mô hình 5S môi trường", "direct", "Khoản 1 Điều 4 yêu cầu xây dựng môi trường giáo dục xanh, sạch, đẹp và thực hiện mô hình quản lý nào trong nhà trường?"),
            ("An toàn cháy nổ thiên tai", "direct", "Khoản 2 Điều 4 liệt kê những loại hình an toàn nào mà mọi người trong trường phải bảo đảm?"),
            ("Ngắt điện lau bảng khi hết giờ", "direct", "Theo khoản 5 Điều 4, sau khi kết thúc giờ làm việc hoặc giờ học, cần thực hiện những thao tác nào đối với thiết bị điện, bảng viết và cửa phòng?"),
            ("Viết vẽ dán lên tường bàn ghế", "paraphrase", "Khoản 7 Điều 4 nghiêm cấm sinh viên và mọi người làm những hành vi nào lên tường, bàn học, ghế đá?"),
            ("Treo dán áp phích băng rôn", "paraphrase", "Muốn treo áp phích, băng rôn, biểu ngữ hoặc quảng cáo trong trường thì bắt buộc phải có sự cho phép của ai?"),
            ("Bảo vệ tượng đài cây xanh", "direct", "Khoản 6 Điều 4 nhắc nhở ý thức bảo vệ những công trình văn hóa nào trong khuôn viên trường?"),
            ("Nói tục tiếng lóng quát nạt", "paraphrase", "Việc nói tục, nói tiếng lóng hoặc quát nạt gây gổ làm ảnh hưởng hình ảnh tập thể vi phạm điều nào của Quy tắc ứng xử?"),
            ("Không gian lận vu khống bạo lực", "direct", "Khoản 6 và 7 Điều 3 nghiêm cấm những hành vi xâm phạm danh dự, sức khỏe và nhân phẩm người khác nào?"),
            ("Tiết kiệm điện nước Đ4", "direct", "Khoản 4 Điều 4 yêu cầu sử dụng tiết kiệm và an toàn những tài nguyên, trang thiết bị nào?"),
            ("Gây rối mất đoàn kết tập thể", "paraphrase", "Hành vi gây hiềm khích, quấy rối, ép buộc hoặc đe dọa người khác trong trường bị cấm theo quy tắc ứng xử chung nào?"),
            ("Đóng cửa sổ khóa cửa phòng", "paraphrase", "Ai có trách nhiệm thu dọn rác thải tạo ra, đóng cửa sổ phòng học và khóa cửa phòng làm việc khi hết giờ để bảo vệ tài sản hồ sơ?"),
            ("Lối sống lành mạnh Đ3", "direct", "Khoản 3 Điều 3 khuyến khích lối sống như thế nào giữa các thành viên trong nhà trường?"),
            ("Hiệu lực áp dụng từ năm học", "direct", "Quy tắc ứng xử ban hành theo Quyết định 367 có hiệu lực áp dụng từ năm học nào?"),
            # Chương 3: Quy tắc ứng xử của CBVC, Quản lý, Giảng viên, Nhân viên, Nơi công cộng/Gia đình (25-68)
            ("CBVC xử lý sự việc phát sinh", "direct", "Theo điểm b khoản 2 Điều 5, khi có sự việc phát sinh mà CBVC chưa biết cách xử lý thì phải xin ý kiến của ai và tuyệt đối không làm gì?"),
            ("Hỗ trợ đồng nghiệp đúng trình tự", "direct", "Nếu gặp khó khăn cần nhờ sự hỗ trợ của đồng nghiệp hoặc đơn vị khác, CBVC phải thực hiện theo yêu cầu nào tại điểm a khoản 2 Điều 5?"),
            ("Làm gương và giờ làm việc", "direct", "Khoản 3 và khoản 4 Điều 5 yêu cầu CBVC tuân thủ kỷ luật giờ giấc làm việc và thái độ giúp đỡ sinh viên như thế nào?"),
            ("Đồng phục CBVC sự kiện lễ tết", "direct", "Theo khoản 5 Điều 5, cán bộ viên chức nhà trường phải mặc đồng phục trường vào những dịp nào?"),
            ("CBVC vượt thẩm quyền thờ ơ", "direct", "Khoản 1 Điều 6 cấm cán bộ viên chức thực hiện những hành vi thiếu trách nhiệm hoặc vượt quá phạm vi công việc nào?"),
            ("CBVC gây phiền hà sách nhiễu", "direct", "Theo khoản 3 Điều 6, cán bộ viên chức tuyệt đối không được nhận những gì từ người đến giao dịch công tác?"),
            ("Đơn thư nặc danh vượt cấp", "paraphrase", "Khoản 4 Điều 6 cấm CBVC thực hiện hành vi lôi kéo, kích động tố cáo và gửi đơn thư như thế nào?"),
            ("Lợi dụng chức vụ vụ lợi", "direct", "Khoản 5 Điều 6 quy định việc lợi dụng chức vụ hoặc danh nghĩa nhà trường để trục lợi, phát ngôn sai trái bị cấm ra sao?"),
            ("CBVC nghe điện thoại ghi âm", "direct", "Khoản 6 Điều 6 cấm cán bộ viên chức nghe điện thoại trong giờ nào và ghi âm, quay phim, chụp ảnh khi nào?"),
            ("Tiết lộ thông tin mật", "direct", "Cán bộ viên chức có được phép cung cấp thông tin mật của Nhà trường ra ngoài xã hội nếu không được Hiệu trưởng cho phép không?"),
            ("Cán bộ quản lý ứng xử cấp trên", "direct", "Khoản 1 Điều 7 quy định cán bộ quản lý phải ứng xử với lãnh đạo cấp trên theo chuẩn mực ngôn ngữ và thái độ nào?"),
            ("Quản lý đồng cấp Đ7", "direct", "Khoản 2 Điều 7 yêu cầu cán bộ quản lý giao tiếp và bảo vệ danh dự người đồng cấp ra sao?"),
            ("Quản lý ứng xử cấp dưới", "direct", "Cán bộ quản lý khi ứng xử với cấp dưới, giảng viên, nhân viên theo khoản 3 Điều 7 phải tránh những thái độ tiêu cực nào?"),
            ("Dừng phát biểu lạc trọng tâm", "paraphrase", "Cán bộ quản lý có quyền yêu cầu cấp dưới dừng phát biểu trong trường hợp nào theo khoản 4 Điều 7?"),
            ("Quản lý ứng xử người học", "direct", "Khoản 5 Điều 7 yêu cầu cán bộ quản lý dùng ngôn ngữ và thái độ gì khi tiếp xúc với người học?"),
            ("Giảng viên với cán bộ quản lý", "direct", "Khoản 1 Điều 8 quy định giảng viên ứng xử với cán bộ quản lý như thế nào nếu phát hiện hành vi sai phạm?"),
            ("Giảng viên với đồng nghiệp", "direct", "Theo khoản 2 Điều 8, giảng viên cần ứng xử với đồng nghiệp và nhân viên thế nào để giữ đoàn kết?"),
            ("Giảng viên với người học Đ8", "direct", "Khoản 3 Điều 8 quy định giảng viên khen, phê bình, phòng chống bạo lực học đường và tuyệt đối không được làm gì đối với người học?"),
            ("Giảng viên không che giấu vi phạm", "paraphrase", "Giảng viên có được thờ ơ, né tránh hoặc che dấu hành vi vi phạm của người học hay cán bộ quản lý theo Điều 8 không?"),
            ("Nhân viên với quản lý giảng viên", "direct", "Điều 9 quy định ứng xử của nhân viên trong trường đối với ba nhóm đối tượng nào?"),
            ("Nhân viên với người học", "paraphrase", "Nhân viên nhà trường cần giữ ngôn ngữ chuẩn mực, khoan dung và tránh hành vi nào khi làm việc với người học?"),
            ("CBVC với cha mẹ người học", "direct", "Điều 10 quy định cán bộ viên chức phải ứng xử với phụ huynh, cha mẹ người học như thế nào?"),
            ("CBVC với khách đến trường", "direct", "Điều 11 quy định thái độ giao tiếp của cán bộ viên chức khi đón tiếp khách đến liên hệ công tác tại trường là gì?"),
            ("CBVC nơi công cộng Đ12", "direct", "Điều 12 yêu cầu cán bộ viên chức khi ở nơi công cộng phải chấp hành thuần phong mỹ tục và thông báo ngay thông tin gì cho cơ quan chức năng?"),
            ("CBVC nơi cư trú Đ13", "direct", "Điều 13 quy định trách nhiệm của cán bộ viên chức đối với quy chế dân chủ cơ sở và nhân dân nơi cư trú như thế nào?"),
            ("Can thiệp trái PL nơi cư trú", "paraphrase", "Theo khoản 3 Điều 13, CBVC có được can thiệp trái pháp luật vào hoạt động của cơ quan nơi cư trú hoặc bao che hành vi vi phạm không?"),
            ("CBVC với gia đình Đ14", "direct", "Điều 14 quy định trách nhiệm giáo dục người thân trong gia đình và bài trừ hủ tục gì khi tham gia lễ hội?"),
            ("Cưới hỏi ma chay sinh nhật Đ14", "direct", "Khoản 3 Điều 14 cấm CBVC để người thân lợi dụng vị trí công tác và cấm tổ chức những việc hiếu hỷ nào một cách xa hoa, lãng phí?"),
            ("Mê tín dị đoan lễ hội Đ14", "paraphrase", "CBVC thực hiện đời sống văn hóa mới nơi cư trú cần tránh mê tín dị đoan và hành vi gì ở lễ hội theo Điều 14?"),
            ("Không to tiếng trong khuôn viên", "paraphrase", "Việc to tiếng trong khuôn viên nhà trường bị cấm đối với CBVC tại khoản nào của Điều 6?"),
            ("Không thiên vị trù dập Đ8", "paraphrase", "Giảng viên khi đánh giá và phê bình người học cần đảm bảo yếu tố phù hợp gì và tránh định kiến, trù dập ra sao?"),
            ("Nghe chỉ đạo đơn vị khác Đ5", "paraphrase", "CBVC có được tự ý quyết định hoặc nghe theo chỉ đạo của lãnh đạo đơn vị khác khi phát sinh sự việc mà không hỏi trưởng đơn vị trực tiếp không?"),
            ("CBVC tự ý bỏ vị trí công tác", "direct", "Khoản 4 Điều 5 nghiêm cấm CBVC những vi phạm kỷ luật lao động nào trong giờ làm việc?"),
            ("Hồ sơ nặc danh trong trường Đ6", "paraphrase", "Viết đơn thư nặc danh hoặc mạo danh tập thể gửi vượt cấp sai sự thật để nói xấu cá nhân vi phạm điều nào của Quy tắc ứng xử?"),
            # Chương 4 & 5: Người học (Điều 15-17) và Tổ chức thực hiện (Điều 18-21) (59-100)
            ("Đ15 việc người học phải làm", "direct", "Điều 15 liệt kê tám nhóm việc sinh viên và học viên phải làm trong học tập và sinh hoạt gồm những gì?"),
            ("Thói quen phòng tự học Đ15", "direct", "Khoản 6 Điều 15 quy định ý thức tiết kiệm điện và vệ sinh của người học khi sử dụng phòng học trong giờ tự học ra sao?"),
            ("Tắt đèn quạt phòng tự học", "paraphrase", "Khi ngồi tự học hoặc rời khỏi phòng học, sinh viên phải chú ý tắt đèn, quạt và dọn dẹp chỗ ngồi như thế nào?"),
            ("Thẻ SV dép quai hậu Đ15", "direct", "Khoản 8 Điều 15 quy định người học phải mang thẻ gì, đi giày dép loại nào và mặc trang phục gì khi học thực hành?"),
            ("Mang dép lê vào trường Đ15", "paraphrase", "Theo quy tắc ứng xử về trang phục của người học, đi dép không có quai hậu đến lớp có đúng quy định không?"),
            ("Bảo hộ lao động thực hành", "paraphrase", "Trong các giờ học thực hành tại xưởng, sinh viên có bắt buộc mặc đồng phục và đồ bảo hộ lao động đúng quy định không?"),
            ("Đừng bao che sai phạm Đ15", "direct", "Khoản 5 Điều 15 yêu cầu sinh viên giữ đức tính trung thực và không làm gì đối với sai phạm của người khác?"),
            ("Phát biểu và NCKH Đ15", "direct", "Khoản 4 Điều 15 khuyến khích thái độ học tập của sinh viên trên giảng đường và hoạt động nghiên cứu như thế nào?"),
            ("An toàn giao thông người học Đ15", "direct", "Khoản 2 Điều 15 yêu cầu người học chấp hành quy định gì ngoài xã hội và nói không với những tệ nạn nào?"),
            ("Đ16 việc người học không được làm", "direct", "Điều 16 quy định tám hành vi người học không được làm gồm những hành vi nào?"),
            ("Dùng điện thoại trong giờ học", "paraphrase", "Làm việc riêng hoặc sử dụng điện thoại di động trong giờ học và giờ kiểm tra thi bị cấm theo khoản mấy Điều 16?"),
            ("Còn mùi cồn khi học và thi", "direct", "Sinh viên tham gia học tập, kiểm tra, thi cử trong tình trạng vẫn còn mùi cồn có bị coi là vi phạm Điều 16 không?"),
            ("Ghi âm quay lén giảng viên", "direct", "Khoản 4 Điều 16 quy định sinh viên chỉ được ghi âm, ghi hình hoặc chụp ảnh trong giờ học khi có điều kiện gì?"),
            ("Xuyên tạc nói xấu CBVC", "direct", "Hành vi xuyên tạc, nói xấu cán bộ viên chức của Nhà trường bị cấm theo khoản mấy của Điều 16?"),
            ("Dùng Internet nói xấu bạn", "paraphrase", "Sử dụng mạng internet để bình luận, phát tán thông tin nói xấu làm ảnh hưởng danh dự bạn học khác vi phạm quy định nào?"),
            ("Mang ly nước vào lớp học", "paraphrase", "Sinh viên có được phép mang các loại thức uống đựng trong ly như trà sữa, cà phê vào lớp học theo khoản 7 Điều 16 không?"),
            ("Lén ăn vặt trong giờ học", "paraphrase", "Việc lén ăn vặt trong giờ học trên lớp bị nghiêm cấm ở khoản nào của Điều 16 Quy tắc ứng xử?"),
            ("Đánh nhau nơi công cộng Đ16", "direct", "Khoản 2 Điều 16 nghiêm cấm hành vi đánh nhau và gây rối trật tự an ninh ở những phạm vi địa điểm nào?"),
            ("Đ17 người học với CBVC", "direct", "Khoản 1 Điều 17 quy định sinh viên ứng xử với cán bộ viên chức nhà trường phải thể hiện thái độ gì và tránh điều gì?"),
            ("Đ17 người học với nhau", "direct", "Khoản 2 Điều 17 yêu cầu sinh viên giao tiếp với bạn học bằng ngôn ngữ và thái độ như thế nào?"),
            ("Đ17 người học với cha mẹ", "direct", "Khoản 3 Điều 17 nhắc nhở người học giữ phẩm chất ứng xử gì đối với cha mẹ và người thân?"),
            ("Đ17 người học với khách", "direct", "Khi gặp khách đến thăm hoặc liên hệ tại trường, người học phải ứng xử ra sao theo khoản 4 Điều 17?"),
            ("Phòng đầu mối Quy tắc ứng xử", "direct", "Theo khoản 1 Điều 18, phòng ban nào là đơn vị đầu mối tham mưu cho Ban Giám hiệu về tổ chức thực hiện, khen thưởng và kỷ luật quy tắc ứng xử?"),
            ("Phổ biến QĐ đến CBVC", "direct", "Ai chịu trách nhiệm trực tiếp phổ biến và triển khai thực hiện Quy tắc ứng xử đến toàn thể CBVC trong từng đơn vị?"),
            ("Phổ biến QĐ đến người học", "direct", "Những đơn vị, đoàn thể nào chịu trách nhiệm phổ biến và triển khai Quy tắc ứng xử đến sinh viên, học viên?"),
            ("Báo cáo SV chính quy vs VLVH", "direct", "Theo Điều 19, khi CBVC phát hiện người học vi phạm quy tắc ứng xử thì báo cáo cho phòng nào đối với hệ Chính quy và phòng nào đối với hệ Vừa làm vừa học?"),
            ("Vai trò nhắc nhở của SV Đ20", "direct", "Khoản 1 Điều 20 quy định trách nhiệm của người học không chỉ tự thực hiện mà còn làm gì đối với bạn học?"),
            ("Sinh viên phản ánh vi phạm cho ai", "direct", "Theo khoản 2 Điều 20, khi cần phản ánh vụ việc liên quan đến quy tắc ứng xử, người học báo cáo trực tiếp cho những đầu mối nào?"),
            ("Xử lý CBVC vi phạm Đ21", "direct", "Theo khoản 1 Điều 21, Hiệu trưởng có thể áp dụng những biện pháp xử lý nào đối với cán bộ viên chức vi phạm Quy tắc ứng xử?"),
            ("Tạm dừng giảng dạy CBVC", "paraphrase", "CBVC vi phạm quy tắc ứng xử tùy mức độ có thể bị tạm dừng giảng dạy, bố trí việc khác hoặc chấm dứt hợp đồng lao động đúng không?"),
            ("Xử lý người học vi phạm Đ21", "direct", "Khoản 2 Điều 21 quy định thông tin phản ánh hành vi vi phạm quy tắc ứng xử của người học do bộ phận nào giải quyết và xét kỷ luật?"),
            ("Hội đồng xử lý SV vi phạm QĐ 367", "direct", "Tên đầy đủ của Hội đồng xem xét xử lý vi phạm quy tắc ứng xử đối với người học nêu tại điểm b khoản 2 Điều 21 là gì?"),
            ("Mang nước đóng chai vs đựng ly", "paraphrase", "Khoản 7 Điều 16 cấm mang loại đồ uống có bao bì như thế nào vào trong lớp học?"),
            ("Chụp slide bài giảng lớp", "paraphrase", "Sinh viên muốn chụp ảnh hoặc quay video bài giảng trong lớp mà chưa xin phép giảng viên thì có phạm quy định ứng xử không?"),
            ("Quên tắt quạt phòng học", "paraphrase", "Không tắt đèn, quạt thừa không dùng tới hoặc không thu dọn rác chỗ ngồi khi rời phòng tự học trái với quy định ở điều nào?"),
            ("Mất thẻ SV vào lớp", "paraphrase", "Sinh viên đi học có bắt buộc mang thẻ sinh viên theo người không theo Điều 15?"),
            ("Chê bai bạn học trên Facebook", "paraphrase", "Đăng bài bôi nhọ, nói xấu danh dự sinh viên khác trên mạng internet vi phạm khoản nào trong Quy tắc ứng xử người học?"),
            ("Lãnh đạo khoa phổ biến QĐ", "direct", "Ngoài Phòng CTSV và Phòng Đào tạo, ai phổ biến Quy tắc ứng xử cho CBVC các đơn vị trực thuộc theo Điều 18?"),
            ("Văn hóa phẩm đồi trụy Đ16", "paraphrase", "Hành vi lưu hành và sử dụng văn hóa phẩm đồi trụy của người học được quy định cấm tại khoản mấy Điều 16?"),
            ("Khiếu nại vượt cấp sai sự thật", "direct", "Việc kích động nhiều người khiếu nại hoặc gửi đơn vượt cấp sai sự thật áp dụng chế tài cho đối tượng nào trong Quy tắc ứng xử?"),
            ("Điều chỉnh vướng mắc QĐ 367", "direct", "Quy tắc ứng xử năm học 2023-2024 quy định cách giải quyết ra sao nếu có vấn đề phát sinh, vướng mắc trong quá trình thực hiện?"),
            ("Phòng TCHC tham mưu thưởng", "paraphrase", "Cá nhân thực hiện tốt Quy tắc ứng xử được đơn vị đầu mối nào đề xuất Ban Giám hiệu khen thưởng?"),
        ],
    },
    "quy_che_an_toan_thong_tin.pdf": {
        "expected_dept": "Trung tâm Công nghệ Thông tin (VLUTE)",
        "questions": [
            # Quyết định, văn bản căn cứ, định nghĩa, nguyên tắc, cấm, đầu mối nhân lực (1-26)
            ("QĐ 979 ATTT", "direct", "Quy chế bảo đảm an toàn thông tin, an ninh mạng của VLUTE ban hành kèm theo Quyết định số mấy và ngày nào?"),
            ("Thay thế QĐ 269", "direct", "Quyết định 979/QĐ-ĐHSPKTVL ngày 29/9/2025 thay thế quyết định an toàn thông tin cũ nào năm 2024?"),
            ("Luật ATTT ANM GDĐT", "direct", "Quy chế an toàn thông tin năm 2025 căn cứ trên ba bộ Luật chính nào của Quốc hội?"),
            ("Nghị định 85 và 13 ATTT", "direct", "Các Nghị định số 85/2016, 53/2022 và 13/2023 được viện dẫn trong Quy chế an toàn thông tin điều chỉnh những lĩnh vực gì?"),
            ("Thông tư 12 và QĐ 3238", "direct", "Quyết định số 3238/QĐ-BGDĐT ngày 30/10/2024 và Thông tư 12/2022/TT-BTTTT được nhắc tới trong phần căn cứ quy định về nội dung gì?"),
            ("Đối tượng áp dụng ATTT", "direct", "Điều 1 quy định Quy chế an toàn thông tin, an ninh mạng áp dụng cho ba nhóm đối tượng nào?"),
            ("Đơn vị ngoài kết nối HT", "paraphrase", "Các tổ chức hoặc cá nhân cung cấp dịch vụ CNTT bên ngoài khi tham gia kết nối vào hệ thống thông tin của VLUTE có phải tuân thủ Quy chế an toàn thông tin không?"),
            ("3 thuộc tính cơ bản ATTT", "direct", "Theo khoản 1 Điều 2, bảo đảm an toàn thông tin nhằm giữ vững ba thuộc tính cơ bản nào của thông tin?"),
            ("Định nghĩa an ninh mạng", "direct", "Khoản 2 Điều 2 giải thích khái niệm An ninh mạng và Hệ thống thông tin khác nhau như thế nào?"),
            ("Dữ liệu cá nhân cơ bản nhạy cảm", "direct", "Theo khoản 5 Điều 2, dữ liệu cá nhân bao gồm hai phân loại nào và thể hiện dưới những dạng nào trên môi trường điện tử?"),
            ("Khái niệm sự cố ATTT", "direct", "Sự cố an toàn thông tin và Quản trị rủi ro an toàn thông tin được định nghĩa thế nào tại khoản 6 và 7 Điều 2?"),
            ("4 mục tiêu ATTT Đ3", "direct", "Khoản 1 Điều 3 nêu bốn mục tiêu cụ thể của công tác bảo đảm an toàn thông tin và an ninh mạng tại Trường là gì?"),
            ("Nguyên tắc tích hợp từ thiết kế", "direct", "Theo khoản 2 Điều 3, yêu cầu bảo đảm an toàn thông tin phải được tích hợp từ giai đoạn nào của vòng đời hệ thống?"),
            ("Ưu tiên bảo vệ dữ liệu Đ3", "direct", "Điểm d khoản 2 Điều 3 yêu cầu ưu tiên bảo vệ những loại dữ liệu nào theo quy định pháp luật?"),
            ("Điều 7 và 8 Luật ATTT ANM", "direct", "Khoản 1 Điều 4 dẫn chiếu các hành vi bị nghiêm cấm theo điều nào của Luật An toàn thông tin mạng và Luật An ninh mạng?"),
            ("6 hành vi cấm nội bộ Đ4", "direct", "Khoản 2 Điều 4 nghiêm cấm cụ thể những hành vi vi phạm an toàn thông tin nào trong phạm vi Trường?"),
            ("Chia sẻ tài khoản chứng thư số", "paraphrase", "Cho bạn hoặc đồng nghiệp mượn tài khoản, mật khẩu hoặc dùng chung chứng thư số, thiết bị xác thực của mình có bị cấm trong Điều 4 không?"),
            ("Phát tán mã độc spam Đ4", "direct", "Hành vi phát tán mã độc, thư rác, tin nhắn rác qua mạng trường bị cấm tại điểm nào Điều 4?"),
            ("Đầu mối liên hệ và ứng cứu", "direct", "Theo Điều 5, đơn vị nào của Trường làm đầu mối liên hệ cơ quan chức năng và chủ trì điều phối xử lý sự cố an toàn thông tin?"),
            ("Yêu cầu tuyển dụng nhân sự ATTT", "direct", "Khoản 1 Điều 6 quy định người được tuyển dụng vào vị trí liên quan đến an toàn thông tin cần đáp ứng điều kiện và cam kết gì?"),
            ("Trách nhiệm người dùng Đ6", "paraphrase", "Trong quá trình làm việc, người sử dụng thông thường có được tự ý cài đặt, tháo lắp hoặc thay đổi cấu hình thiết bị được giao không?"),
            ("Trách nhiệm cán bộ vận hành Đ6", "direct", "Cán bộ quản lý, vận hành hệ thống theo điểm b khoản 2 Điều 6 phải áp dụng những biện pháp kỹ thuật kiểm soát nào?"),
            ("Đào tạo nhận thức ATTT hàng năm", "direct", "Nhà trường tổ chức hoặc cử cán bộ tham gia bồi dưỡng, tập huấn nâng cao nhận thức về an toàn thông tin theo tần suất bao lâu một lần?"),
            ("Bảo mật dữ liệu người học Đ6", "paraphrase", "Các đơn vị và cá nhân được phép thu thập, tiết lộ hoặc sử dụng dữ liệu cá nhân, dữ liệu người học cho mục đích khác ngoài nhiệm vụ không?"),
            ("Thu hồi quyền khi nghỉ việc Đ6", "direct", "Khi cán bộ hoặc người lao động chấm dứt hoặc thay đổi công việc, khoản 3 Điều 6 yêu cầu thu hồi và vô hiệu hóa những gì?"),
            # Thiết kế, phần mềm thuê khoán, nghiệm thu, mạng, máy chủ, ứng dụng (26-58)
            ("Hồ sơ đề xuất cấp độ Đ7", "direct", "Khoản 1 Điều 7 quy định Hồ sơ đề xuất cấp độ của hệ thống thông tin phải bao gồm bốn nội dung chính nào?"),
            ("Đánh giá lại khi đổi thiết kế", "paraphrase", "Nếu có sự thay đổi thiết kế hệ thống thông tin thì bộ phận chuyên trách phải làm thủ tục gì trước khi triển khai theo khoản 2 Điều 7?"),
            ("Hợp đồng thuê khoán phần mềm", "direct", "Khoản 1 Điều 8 bắt buộc hợp đồng phát triển phần mềm thuê khoán phải quy định rõ bốn điều khoản nào?"),
            ("Cấm cài backdoor mã độc Đ8", "paraphrase", "Khi thuê đơn vị ngoài viết phần mềm cho trường, nhà phát triển phải cam kết điều gì về mã độc, cửa hậu (backdoor) và quyền sở hữu trí tuệ?"),
            ("Bàn giao mã nguồn phần mềm", "direct", "Sau khi hoàn thành phần mềm thuê khoán, nhà phát triển có trách nhiệm bàn giao những tài liệu gì và phối hợp kiểm thử bảo mật ra sao?"),
            ("Lưu trữ mã nguồn an toàn Đ8", "direct", "Bộ phận chuyên trách bảo quản mã nguồn và tài liệu bàn giao bằng các biện pháp kiểm soát, sao lưu nào?"),
            ("Kịch bản kiểm thử ATTT Đ9", "direct", "Điều 9 quy định kế hoạch thử nghiệm trước khi nghiệm thu hệ thống phải bao gồm những kịch bản gì và ai phê duyệt?"),
            ("3 điều kiện nghiệm thu Đ9", "direct", "Hệ thống thông tin mới chỉ được phép nghiệm thu đưa vào vận hành khi đáp ứng đủ ba điều kiện nào tại khoản 4 Điều 9?"),
            ("Phân vùng mạng LAN WAN DMZ", "direct", "Khoản 2 Điều 10 yêu cầu thiết lập các phân vùng mạng và cơ chế bảo mật nào cho hạ tầng mạng trường?"),
            ("Quản lý cấu hình router switch", "direct", "Toàn bộ thiết bị mạng và an ninh như router, switch, firewall phải được quản lý tập trung và theo dõi nhật ký thế nào?"),
            ("Thời điểm nâng cấp cấu hình", "paraphrase", "Việc nâng cấp, thay đổi cấu hình hệ thống mạng ưu tiên thực hiện vào khung thời gian nào và cần có phương án dự phòng gì?"),
            ("Truy cập cấu hình từ bên ngoài", "direct", "Khi truy cập cấu hình hệ thống mạng từ bên ngoài trường, khoản 5 Điều 10 bắt buộc phải sử dụng kênh kết nối và xác thực gì?"),
            ("Giao thức bảo mật cấu hình từ xa", "direct", "Những giao thức mã hóa thông tin nào được quy định khi truy cập cấu hình từ xa hoặc truy cập quản trị hệ thống?"),
            ("Hệ thống SIEM lưu log 12 tháng", "direct", "Khoản 6 Điều 10 quy định triển khai hệ thống giám sát SIEM để làm gì và thời gian lưu giữ nhật ký tối thiểu bao nhiêu tháng?"),
            ("Cấu hình an toàn máy chủ Đ11", "direct", "Theo điểm b khoản 1 Điều 11, hệ điều hành máy chủ khi cài đặt phải tuân thủ chuẩn mực an toàn nào?"),
            ("Sao lưu ảnh HĐH máy chủ", "direct", "Ảnh hệ điều hành và cấu hình máy chủ phải được sao lưu và lưu trữ trên loại hệ thống nào để phòng rủi ro?"),
            ("Gỡ bỏ máy chủ khỏi hệ thống", "paraphrase", "Trước khi thêm mới hoặc gỡ bỏ một máy chủ khỏi hệ thống của trường thì cần xin phê duyệt của ai và xử lý dữ liệu thế nào?"),
            ("Đánh giá ATTT ứng dụng 1 năm", "direct", "Ứng dụng phải được kiểm tra, đánh giá an toàn thông tin định kỳ tối thiểu bao lâu một lần hoặc vào thời điểm nào?"),
            ("Bảo vệ CSDL và mã nguồn ứng dụng", "direct", "Điểm d khoản 2 Điều 11 quy định quản lý cơ sở dữ liệu và mã nguồn ứng dụng theo những nguyên tắc an toàn nào?"),
            ("Tường lửa cổng quản trị máy chủ", "direct", "Việc truy cập quản trị máy chủ và ứng dụng theo điểm a khoản 3 Điều 11 được kiểm soát cổng truy cập ra sao?"),
            ("Đổi mật khẩu quản trị 3 tháng", "direct", "Tài khoản và mật khẩu quản trị mặc định phải thay đổi khi nào và mật khẩu quản trị phải đổi định kỳ tối thiểu mấy tháng một lần?"),
            ("Cấp quyền quản trị máy chủ", "direct", "Ai được phép cấp quyền quản trị máy chủ và ứng dụng theo điểm d khoản 3 Điều 11?"),
            ("Quản trị máy chủ từ xa VPN MFA", "paraphrase", "Quản trị viên muốn truy cập quản trị máy chủ hoặc ứng dụng từ ngoài trường bắt buộc đáp ứng hai điều kiện bảo mật gì?"),
            ("Danh mục phần mềm trên máy chủ", "direct", "Vì sao mỗi máy chủ phải có danh mục và tài liệu cấu hình, phần mềm hệ thống cài đặt theo điểm e khoản 1 Điều 11?"),
            ("Khái niệm IDS IPS firewall", "direct", "Các hệ thống phát hiện và ngăn chặn xâm nhập được viết tắt là gì và phân bổ cùng vùng mạng nào trong Điều 10?"),
            ("Tài liệu bàn giao nhà phát triển", "direct", "Khi nhận bàn giao phần mềm từ bên thuê khoán, mã nguồn phải kèm theo bốn loại tài liệu gì?"),
            ("Lỗ hổng chưa vá khi nghiệm thu", "paraphrase", "Nếu quá trình thử nghiệm hệ thống còn phát hiện lỗ hổng bảo mật chưa khắc phục thì có được phép nghiệm thu đưa vào sử dụng không?"),
            ("Ghi log truy cập quản trị Đ11", "direct", "Toàn bộ thao tác truy cập quản trị máy chủ và ứng dụng phải được xử lý qua nhật ký như thế nào?"),
            ("Mở cổng kết nối mạng quản trị", "paraphrase", "Tường lửa kiểm soát truy cập quản trị máy chủ theo nguyên tắc mở cổng kết nối như thế nào?"),
            ("Sao lưu ảnh hệ điều hành độc lập", "paraphrase", "Bản sao lưu cấu hình máy chủ và ảnh hệ điều hành có được lưu chung ngay trên chính máy chủ đó không?"),
            ("Đánh giá lại sau nâng cấp app", "paraphrase", "Ngoài chu kỳ tối thiểu 1 năm một lần, khi nào ứng dụng buộc phải kiểm tra đánh giá an toàn thông tin đột xuất?"),
            ("Cấm dùng mật khẩu mặc định", "paraphrase", "Tài khoản và mật khẩu mặc định của nhà sản xuất trên máy chủ mới triển khai phải xử lý ngay lập tức thế nào?"),
            ("Yêu cầu 4 yếu tố thuê viết phần mềm", "paraphrase", "Quy chế ATTT quy định trách nhiệm bảo mật dữ liệu trường trong hợp đồng thuê khoán phần mềm ở Điều mấy?"),
            # Sao lưu, Log, Ứng cứu sự cố, Đầu cuối, Rủi ro, Thanh lý, Email, Tổ chức (59-100)
            ("Chu kỳ sao lưu tuần vs tháng", "direct", "Điều 12 quy định dữ liệu nào phải sao lưu định kỳ hàng tuần và dữ liệu nào sao lưu bổ sung hàng tháng hoặc khi có thay đổi lớn?"),
            ("Nơi lưu trữ sao lưu NAS", "direct", "Các bản sao lưu dữ liệu phải được quản lý phiên bản và lưu trữ trên hệ thống lưu trữ độc lập nào?"),
            ("Mã hóa và checksum sao lưu", "direct", "Để bảo đảm an toàn và kiểm tra tính toàn vẹn của dữ liệu sao lưu, khoản 2 Điều 12 bắt buộc áp dụng hai kỹ thuật nào?"),
            ("Lưu sao lưu tại 2 vị trí", "direct", "Bản sao lưu dữ liệu quan trọng phải được cất giữ tối thiểu tại bao nhiêu vị trí và theo mô hình nào để dự phòng thảm họa?"),
            ("Thử nghiệm khôi phục 6 tháng", "direct", "Định kỳ tối thiểu bao lâu một lần phải chạy thử nghiệm khôi phục dữ liệu từ bản sao lưu và báo cáo cho ai?"),
            ("Lưu giữ nhật ký log 12 tháng", "direct", "Điều 13 quy định tất cả hệ thống, máy chủ, ứng dụng, thiết bị mạng phải ghi nhận log và lưu giữ ít nhất bao nhiêu tháng?"),
            ("Quyền truy cập phân tích log", "paraphrase", "Nhân viên bình thường có được tự ý vào đọc và phân tích file nhật ký hệ thống (log) không theo điểm c khoản 1 Điều 13?"),
            ("Cảnh báo sự cố nghiêm trọng", "direct", "Khi hệ thống giám sát phát hiện cảnh báo an toàn thông tin nghiêm trọng, bộ phận chuyên trách phải báo cáo ngay cho ai?"),
            ("Quy trình 3 bước ứng cứu sự cố", "direct", "Khi sự cố an toàn thông tin xảy ra, khoản 3 Điều 13 yêu cầu bộ phận chuyên trách thực hiện ngay ba bước xử lý kỹ thuật nào?"),
            ("Trực ứng cứu 24/7", "direct", "Trong kế hoạch ứng cứu sự cố, bộ phận chuyên trách phải phân công nhân sự trực theo chế độ thời gian nào khi cần thiết?"),
            ("Thông tin liên hệ ứng cứu sự cố", "direct", "Theo điểm c khoản 3 Điều 13, đầu mối ứng cứu sự cố gồm tên đơn vị, tên người liên hệ, số điện thoại và địa chỉ email nào?"),
            ("Số điện thoại Nguyễn Thanh Hoàng", "paraphrase", "Khi gặp sự cố mất an toàn thông tin tại VLUTE, sinh viên hoặc cán bộ liên hệ qua số điện thoại và email cụ thể nào?"),
            ("Quét virus USB ổ cứng ngoài", "direct", "Khoản 1 Điều 14 quy định quy tắc bắt buộc gì khi cắm ổ cứng di động, thẻ nhớ hoặc USB vào máy tính hệ thống?"),
            ("Chép dữ liệu nghiệp vụ ra USB", "paraphrase", "Người dùng có được thoải mái dùng USB hoặc thiết bị lưu trữ ngoài sao chép, di chuyển dữ liệu nghiệp vụ quan trọng không?"),
            ("Cắm laptop cá nhân mạng nội bộ", "paraphrase", "Khoản 2 Điều 14 quy định có được phép cắm trực tiếp máy tính cá nhân hoặc điện thoại cá nhân vào mạng quản trị, mạng nghiệp vụ của trường không?"),
            ("Phân tách mạng thiết bị cá nhân", "direct", "Thiết bị cá nhân của người học và cán bộ chỉ được phép kết nối internet qua vùng mạng nào theo Điều 14?"),
            ("3 yêu cầu máy tính người dùng", "direct", "Khoản 4 Điều 14 quy định ba yêu cầu bảo mật đối với máy tính người dùng trong hệ thống là gì?"),
            ("Cài phần mềm lậu crack", "paraphrase", "Cài đặt phần mềm không có bản quyền hoặc phần mềm không rõ nguồn gốc trên máy tính trong hệ thống trường bị cấm ở điều nào?"),
            ("Rà soát hồ sơ rủi ro 1 năm", "direct", "Điều 15 quy định Hồ sơ quản lý rủi ro an toàn thông tin phải được đơn vị vận hành rà soát định kỳ tối thiểu bao lâu một lần?"),
            ("3 mức độ phân loại rủi ro", "direct", "Quy trình đánh giá rủi ro tại khoản 2 Điều 15 phân loại mức độ rủi ro theo mấy cấp độ và ưu tiên xử lý mức nào trước?"),
            ("Rút kinh nghiệm sau sự cố Đ15", "direct", "Khoản 4 Điều 15 quy định bài học kinh nghiệm từ các sự cố đã xảy ra phải được cập nhật vào đâu?"),
            ("Đưa thiết bị đi sửa bảo hành", "direct", "Thiết bị CNTT chứa dữ liệu bị hỏng trước khi mang ra ngoài sửa chữa hoặc bảo hành phải thực hiện kiểm tra, giám sát thế nào theo Điều 16?"),
            ("Thanh lý hoặc hủy vật lý HDD", "direct", "Khi thanh lý thiết bị hoặc phương tiện lưu trữ mà phần mềm không thể xóa sạch dữ liệu, Điều 16 bắt buộc áp dụng biện pháp hủy vật lý nào?"),
            ("Chuyển giao thiết bị CNTT", "paraphrase", "Máy tính, USB, NAS, CD/DVD khi chuyển giao mục đích sử dụng phải có ai kiểm tra và lập văn bản gì xác nhận đã xóa sạch dữ liệu?"),
            ("Tên miền email CBGV vs SV", "direct", "Điều 17 quy định cán bộ giảng viên được cấp địa chỉ email tên miền gì và sinh viên, học viên được cấp email tên miền nào?"),
            ("Độ dài ký tự mật khẩu email", "direct", "Chính sách mật khẩu mạnh đối với tài khoản email trường yêu cầu độ dài tối thiểu bao nhiêu ký tự và gồm những loại ký tự nào?"),
            ("Đổi mật khẩu email 6 tháng", "direct", "Người dùng phải đổi mật khẩu tài khoản email VLUTE định kỳ tối thiểu bao lâu một lần hoặc trong tình huống khẩn cấp nào?"),
            ("Chia sẻ dùng chung email @vlute", "paraphrase", "Cán bộ hoặc sinh viên có được cho người khác dùng chung tài khoản email nội bộ đã được cấp không?"),
            ("Đăng ký app ngoài bằng email trường", "paraphrase", "Khoản 3 Điều 17 nghiêm cấm việc dùng địa chỉ email @vlute.edu.vn hoặc @st.vlute.edu.vn để làm gì trên mạng?"),
            ("Phòng tránh email lừa đảo phishing", "direct", "Khi gặp email lạ có liên kết, tệp đính kèm nghi ngờ hoặc dấu hiệu lừa đảo phishing, người dùng cần làm gì theo khoản 4 Điều 17?"),
            ("Gửi thông tin nhạy cảm qua email", "paraphrase", "Nếu bắt buộc phải gửi tài khoản, mật khẩu hoặc dữ liệu tài chính qua email thì khoản 4 Điều 17 yêu cầu áp dụng phương pháp gì?"),
            ("Cấm dùng Gmail gửi tài liệu trường", "paraphrase", "Cán bộ, giảng viên có được dùng email cá nhân như Gmail hay Outlook để trao đổi gửi nhận tài liệu công việc của Trường không?"),
            ("So sánh chu kỳ đổi pass 3T vs 6T", "paraphrase", "Chu kỳ đổi mật khẩu quản trị máy chủ/ứng dụng (Điều 11) khác với chu kỳ đổi mật khẩu tài khoản email (Điều 17) là mấy tháng?"),
            ("Trách nhiệm Trường Đ18", "direct", "Điều 18 dẫn chiếu Trường thực hiện trách nhiệm quản lý an toàn thông tin theo Điều 22 của Nghị định nào?"),
            ("Trách nhiệm Phòng QT-TB Đ19", "direct", "Theo Điều 19, Phòng Quản trị - Thiết bị giữ vai trò gì trong giám sát, vận hành và phối hợp khắc phục sự cố ATTT của Trường?"),
            ("Trách nhiệm đơn vị trực thuộc Đ20", "direct", "Các Khoa, Phòng, Trung tâm trực thuộc Trường có trách nhiệm gì theo Điều 20 khi phát hiện nguy cơ hoặc hành vi vi phạm ATTT?"),
            ("Trách nhiệm người sử dụng Đ21", "direct", "Điều 21 yêu cầu người sử dụng hệ thống thông tin trực tiếp tuân thủ hai điều khoản cụ thể nào trong Quy chế này?"),
            ("Đơn vị soạn thảo Quy chế Đ22", "direct", "Theo Điều 22, đơn vị nào chịu trách nhiệm xây dựng Quy chế bảo đảm an toàn thông tin, an ninh mạng trình Lãnh đạo Trường phê duyệt?"),
            ("Chu kỳ rà soát Quy chế 2 năm", "direct", "Điều 23 quy định Nhà trường rà soát, cập nhật và bổ sung Quy chế an toàn thông tin định kỳ bao nhiêu năm một lần?"),
            ("Phòng thu thập góp ý sửa đổi Đ23", "direct", "Đơn vị nào thu thập, tổng hợp ý kiến phản hồi của người dùng và các đơn vị để cập nhật Quy chế an toàn thông tin?"),
            ("Xử lý vi phạm Quy chế Đ24", "direct", "Cá nhân hoặc tổ chức vi phạm Quy chế bảo đảm an toàn thông tin, an ninh mạng bị xử lý theo quy định nào và ai đôn đốc kiểm tra?"),
            ("Không mở link từ người gửi lạ", "paraphrase", "Quy định an toàn trao đổi qua email khuyến cáo thế nào về tệp đính kèm và đường link từ người gửi lạ?"),
        ],
    },
}


def validate_dataset(dataset_by_doc: dict[str, dict]) -> list[dict]:
    """Kiểm tra chặt chẽ đúng 100 câu/văn bản (tổng 700 câu) và không trùng câu hỏi."""
    records = []
    seen_questions = set()
    idx = 1
    for source_file, cfg in dataset_by_doc.items():
        q_list = cfg["questions"]
        assert len(q_list) == 100, f"{source_file} phải có đúng 100 câu, hiện có {len(q_list)}"
        for topic, style, question in q_list:
            q_clean = question.strip()
            assert q_clean not in seen_questions, f"Câu hỏi bị trùng: {q_clean}"
            seen_questions.add(q_clean)
            records.append(
                {
                    "id": idx,
                    "expected_source": source_file,
                    "expected_dept": cfg["expected_dept"],
                    "topic": topic,
                    "style": style,
                    "question": q_clean,
                }
            )
            idx += 1
    assert len(records) == 700, f"Tổng bộ benchmark phải là 700 câu, hiện có {len(records)}"
    return records


def extract_contact_header(html: str) -> str:
    """Lấy tiêu đề phòng ban/tuyến xử lý đầu tiên từ HTML thẻ liên hệ."""
    if not html:
        return ""
    m = re.search(r"<strong[^>]*>(.*?)</strong>", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return text.rstrip(":").strip()
    return re.sub(r"<[^>]+>", " ", html).strip()


def percentile(values: list[float], p: float) -> float:
    """Tính bách phân vị p (0-100) theo nội suy tuyến tính."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def dept_matches(expected: str, actual_header: str, contact_html: str) -> bool:
    """Kiểm tra đầu ra thẻ liên hệ khớp chính xác tuyến/phòng ban kỳ vọng."""
    if not actual_header:
        return False
    exp_norm = expected.strip()
    act_norm = actual_header.strip()
    if exp_norm == act_norm or exp_norm in contact_html:
        # Tránh khớp nhầm "Phòng Công tác Sinh viên (VLUTE)" vào bản ghi miễn giảm có thêm hậu tố
        if exp_norm == "Phòng Công tác Sinh viên (VLUTE)" and "Đầu mối tiếp nhận hồ sơ" in act_norm:
            return False
        if exp_norm == "Phòng Công tác Sinh viên (VLUTE)" and "Tuyến phối hợp xử lý" in act_norm:
            return False
        return True
    return False


def main():
    os.chdir(ROOT_DIR)
    records = validate_dataset(QUESTIONS_BY_DOC)

    json_path = ROOT_DIR / "evaluation" / "benchmark_700_per_doc.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[1/3] Da luu bo 700 cau hoi tai: {json_path}")

    print("[2/3] Dang nap Vector DB, BM25 Index va cac ham dinh tuyen tu app.py...")
    vector_db = get_vector_db()
    _ = get_bm25_index()
    chain = SmartRAGChain(vector_db=vector_db, llm=None, prompt=None)
    app_helpers = load_app_routing_helpers()
    is_greeting = app_helpers["is_greeting"]
    check_department_inquiry = app_helpers["check_department_inquiry"]
    get_contact_footer = app_helpers["get_contact_footer"]

    # Warm-up 1 truy vấn nhỏ để mô hình PyTorch ổn định trước khi đo độ trễ đồng đều
    _ = chain.filter_documents("Điều kiện xét học bổng khuyến khích học tập?", k=6)

    print("[3/3] Dang chay 700 cau hoi qua filter_documents + routing...")
    rows = []
    per_doc_stats = defaultdict(list)

    for rec in records:
        q = rec["question"]
        exp_src = rec["expected_source"]
        exp_dept = rec["expected_dept"]

        t0 = time.perf_counter()
        greeting_flag = bool(is_greeting(q))
        dept_intercept = check_department_inquiry(q)
        docs = chain.filter_documents(q, k=6)
        dbg = dict(getattr(chain, "last_retrieval_debug", {}) or {})

        is_false_refusal = len(docs) == 0
        contact_html = get_contact_footer(q, retrieved_docs=docs, is_refusal=is_false_refusal)
        t1 = time.perf_counter()
        latency_ms = round((t1 - t0) * 1000.0, 2)

        retrieved_sources = []
        for d in docs:
            src_base = os.path.basename(str(d.metadata.get("source", ""))).lower()
            if src_base and src_base not in retrieved_sources:
                retrieved_sources.append(src_base)

        top1_src = (
            os.path.basename(str(docs[0].metadata.get("source", ""))).lower() if docs else ""
        )
        source_hit = exp_src.lower() in retrieved_sources
        top1_hit = top1_src == exp_src.lower()

        contact_header = extract_contact_header(contact_html)
        intercepted = greeting_flag or (dept_intercept is not None)
        dept_ok = (not intercepted) and (not is_false_refusal) and dept_matches(exp_dept, contact_header, contact_html)

        row = {
            "id": rec["id"],
            "expected_source": exp_src,
            "topic": rec["topic"],
            "style": rec["style"],
            "question": q,
            "num_docs": len(docs),
            "source_hit": source_hit,
            "top1_hit": top1_hit,
            "top1_source": top1_src,
            "retrieved_sources": ";".join(retrieved_sources),
            "false_refusal": is_false_refusal,
            "is_greeting": greeting_flag,
            "dept_inquiry_intercept": dept_intercept is not None,
            "expected_dept": exp_dept,
            "actual_contact_header": contact_header,
            "dept_routing_ok": dept_ok,
            "latency_ms": latency_ms,
            "gate_reason": dbg.get("reason", ""),
            "max_dense": dbg.get("max_dense", ""),
            "max_bm25": dbg.get("max_bm25", ""),
            "best_idf_cov": dbg.get("best_idf_cov", ""),
        }
        rows.append(row)
        per_doc_stats[exp_src].append(row)

    csv_path = ROOT_DIR / "evaluation" / "benchmark_700_results.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Da xuat ket qua chi tiet tai: {csv_path}\n")

    print("=" * 112)
    print(
        f"{'Van ban (100 cau/file)':<36} | {'Hit@k':>7} | {'Top-1':>7} | {'Dept OK':>8} | "
        f"{'FalseRef':>8} | {'Avg(ms)':>8} | {'p95(ms)':>8} | {'Max(ms)':>8}"
    )
    print("-" * 112)

    all_lat = []
    misses = []
    dept_mismatches = []
    for doc_name in QUESTIONS_BY_DOC.keys():
        items = per_doc_stats[doc_name]
        n = len(items)
        hit_cnt = sum(1 for r in items if r["source_hit"])
        top1_cnt = sum(1 for r in items if r["top1_hit"])
        dept_cnt = sum(1 for r in items if r["dept_routing_ok"])
        ref_cnt = sum(1 for r in items if r["false_refusal"])
        lats = [r["latency_ms"] for r in items]
        all_lat.extend(lats)

        print(
            f"{doc_name:<36} | {hit_cnt/n*100:6.1f}% | {top1_cnt/n*100:6.1f}% | "
            f"{dept_cnt/n*100:7.1f}% | {ref_cnt:8d} | {sum(lats)/n:8.2f} | "
            f"{percentile(lats, 95):8.2f} | {max(lats):8.2f}"
        )
        for r in items:
            if not r["source_hit"] or r["false_refusal"]:
                misses.append(r)
            elif not r["dept_routing_ok"]:
                dept_mismatches.append(r)

    total_n = len(rows)
    tot_hit = sum(1 for r in rows if r["source_hit"])
    tot_top1 = sum(1 for r in rows if r["top1_hit"])
    tot_dept = sum(1 for r in rows if r["dept_routing_ok"])
    tot_ref = sum(1 for r in rows if r["false_refusal"])
    print("-" * 112)
    print(
        f"{'TONG HOP 700 CAU':<36} | {tot_hit/total_n*100:6.2f}% | {tot_top1/total_n*100:6.2f}% | "
        f"{tot_dept/total_n*100:7.2f}% | {tot_ref:8d} | {sum(all_lat)/total_n:8.2f} | "
        f"{percentile(all_lat, 95):8.2f} | {max(all_lat):8.2f}"
    )
    print("=" * 112)

    print(f"\n[MISSES / FALSE REFUSALS] ({len(misses)} cau):")
    for m in misses:
        print(
            f"  - ID={m['id']} | expected={m['expected_source']} | num_docs={m['num_docs']} | "
            f"false_refusal={m['false_refusal']} | top={m['retrieved_sources']} | "
            f"gate={m['gate_reason']} | Q: {m['question']}"
        )

    print(f"\n[DEPT ROUTING MISMATCHES / INTERCEPTIONS] ({len(dept_mismatches)} cau):")
    for dm in dept_mismatches:
        print(
            f"  - ID={dm['id']} | expected={dm['expected_source']} ({dm['expected_dept']}) | "
            f"actual='{dm['actual_contact_header']}' | top1={dm['top1_source']} | "
            f"greeting={dm['is_greeting']} | dept_intercept={dm['dept_inquiry_intercept']} | Q: {dm['question']}"
        )


if __name__ == "__main__":
    main()
