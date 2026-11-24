"""
Bộ kiểm thử đối kháng & toàn diện 1.000 câu hỏi (Adversarial & Multi-Turn Benchmark 1000)
cho hệ thống VLUTEBOT (7 file PDF quy chế + 1 file Đề cương học phần .docx IT1216):

1. Nhóm 1 (250 câu): Ngớ ngẩn / Vô nghĩa / Ra lệnh meta / Xã giao
   -> Kỳ vọng: 100% bị chặn/xử lý như xã giao hoặc từ chối OOS (verified=False, contact=None).
2. Nhóm 2 (250 câu): Hỏi như ChatGPT / Gemini (Ngoài phạm vi quy chế - OOS)
   -> Kỳ vọng: 100% bị Dual Refusal Gate từ chối chuẩn bằng REFUSAL_MESSAGE (is_refusal=True, contact=None).
3. Nhóm 3 (150 kịch bản): Hội thoại nối tiếp đa lượt (Multi-turn Context)
   - 3a (75 cặp hợp lệ): Lượt 1 hỏi quy chế/môn IT1216, Lượt 2 hỏi nối tiếp ('vậy...', 'còn...', 'nó...')
     -> Kỳ vọng: Viết lại đúng chủ ngữ và tìm trúng tài liệu nguồn + định tuyến đúng phòng ban.
   - 3b (75 cặp bẫy): Lượt 1 hỏi quy chế, Lượt 2 gõ 'đặt câu hỏi đi', 'viết code đi', 'ok cảm ơn'...
     -> Kỳ vọng: 100% không dính ngữ cảnh cũ (rewritten_query == raw_query, verified=False, contact=None).
4. Nhóm 4 (350 câu): Hỏi đáp đúng phạm vi quy chế & Đề cương IT1216 (In-scope)
   -> Phân bổ đều trên cả 8 tài liệu (43-44 câu/tài liệu), gồm câu hỏi chuẩn, viết tắt, số liệu bảng biểu,
      và câu hỏi tình huống đời thường (tăng cường nhóm Quy tắc ứng xử).
5. Kiểm thử trực tiếp 20 câu đại diện qua POST http://127.0.0.1:8000/api/chat/stream.

- Lưu bộ đề tại: evaluation/benchmark_1000_adversarial.json
- Lưu kết quả chi tiết tại: evaluation/benchmark_1000_results.csv
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api import check_department_inquiry, get_contact_footer_data
from evaluation.run_benchmark_700 import QUESTIONS_BY_DOC
from rag import (
    REFUSAL_MESSAGE,
    SmartRAGChain,
    get_bm25_index,
    get_greeting_or_chitchat_reply,
    get_vector_db,
    is_greeting_or_chitchat,
    rewrite_conversational_query,
)


def build_group1_nonsense_meta_chitchat() -> list[dict]:
    """Sinh đúng 250 câu Ngớ ngẩn / Vô nghĩa / Ra lệnh meta / Xã giao không trùng lặp."""
    raw_items = [
        # Ra lệnh meta / thúc giục bot (65 câu)
        "đặt câu hỏi đi", "đặt câu hỏi cho mình đi", "bạn đặt câu hỏi đi", "hãy đặt câu hỏi đi",
        "hỏi đi", "hỏi lại đi", "hỏi tiếp đi", "hỏi gì đi", "hỏi mình đi", "hỏi em đi",
        "hỏi tôi đi", "hỏi câu khác đi", "đổi câu hỏi đi", "cho câu hỏi đi", "cho mình câu hỏi đi",
        "nói đi", "nói gì đi", "nói tiếp đi", "nói chuyện đi", "nói chuyện với mình đi",
        "trả lời đi", "trả lời nhanh đi", "trả lời tiếp đi", "gợi ý đi", "cho gợi ý đi",
        "gợi ý câu hỏi đi", "cho xin gợi ý đi", "tiếp đi", "tiếp tục đi", "bắt đầu đi",
        "làm đi", "thực hiện đi", "chạy thử đi", "xem nào", "đâu rồi", "bạn đâu rồi",
        "lucas đâu rồi", "sao nữa", "sao im thế", "alo đâu rồi", "có ai ở đó không",
        "bạn đang làm gì đấy", "bạn biết làm gì", "bạn có thông minh không", "ai tạo ra bạn",
        "ai lập trình ra bạn", "dừng lại đi", "tắt đi", "im đi", "xóa lịch sử đi",
        "làm mới đi", "reset đi", "test", "testing", "test thử", "test bot",
        "alo test", "kiểm tra thử", "test 123", "test hệ thống", "kể chuyện cười đi",
        "kể chuyện đi", "hát đi", "hát một bài đi", "làm thơ đi",
        # Cảm ơn / Xác nhận / Khen ngợi ngắn (65 câu)
        "ok", "okay", "oke", "oki", "okie", "okela", "ok bạn", "ok lucas",
        "ok ad", "oke bạn", "oke lucas", "ok cảm ơn", "oke cảm ơn", "ok cảm ơn bạn",
        "ok cảm ơn lucas", "dạ", "vâng", "dạ vâng", "dạ cảm ơn", "vâng cảm ơn",
        "dạ em cảm ơn", "vâng mình hiểu rồi", "ừ", "ờ", "ừm", "rồi",
        "rõ rồi", "đã rõ", "hiểu rồi", "biết rồi", "đã hiểu", "nắm được rồi",
        "mình hiểu rồi", "em hiểu rồi", "ok đã rõ", "cảm ơn", "cám ơn", "cảm ơn bạn",
        "cảm ơn lucas", "cảm ơn ad", "cảm ơn nhiều", "cảm ơn nhé", "cảm ơn nha",
        "cảm ơn rất nhiều", "cám ơn bạn", "cám ơn lucas", "cám ơn nhiều nhé", "thank",
        "thanks", "tks", "thank you", "thanks lucas", "thanks bạn", "thank you so much",
        "tốt quá", "hay quá", "tuyệt vời", "giỏi quá", "xịn quá", "đỉnh quá",
        "chuẩn", "chuẩn luôn", "đúng rồi", "good", "great",
        # Xã giao / Tán gẫu cá nhân / Cảm thán đời thường (60 câu)
        "chào", "xin chào", "hello", "hi", "hey", "alo", "chào bạn",
        "chào lucas", "xin chào lucas", "hello lucas", "hi lucas", "alo lucas", "alo bạn ơi",
        "ê bot", "này lucas", "này bot", "bạn là ai", "bạn tên gì", "tên gì",
        "giới thiệu bản thân đi", "bạn ăn cơm chưa", "ăn cơm chưa", "ăn sáng chưa", "ăn trưa chưa",
        "ăn tối chưa", "lucas ăn cơm chưa", "ngủ chưa", "bạn ngủ chưa", "thức khuya thế",
        "buồn ngủ quá", "buồn ngủ ghê", "mệt quá", "hôm nay mệt quá", "chán quá", "chán ghê",
        "đói quá", "đói bụng quá", "buồn quá", "hôm nay buồn quá", "vui quá", "hôm nay vui quá",
        "bạn khỏe không", "khỏe không", "lucas khỏe không", "dạo này thế nào", "bạn mấy tuổi",
        "bạn bao nhiêu tuổi", "bạn có người yêu chưa", "lucas có người yêu chưa", "hôm nay trời đẹp quá",
        "chúc bạn một ngày tốt lành", "chúc ngủ ngon", "chúc lucas ngủ ngon", "tạm biệt", "tạm biệt nhé",
        "bye", "bye bye", "goodbye", "hẹn gặp lại", "hẹn gặp lại nhé",
        # Vô nghĩa / Gõ phím ngẫu nhiên / Số / Ký tự / Lặp từ (60 câu)
        "asdfghjkl", "qwertyuiop", "zxcvbnm", "asdf", "qwerty", "zxcv", "hjkl",
        "dfghjk", "cvbnm", "qazwsx", "edcrfv", "tgbyhn", "ujmik", "plmokn",
        "123", "1234", "12345", "123456", "123456789", "000000", "999999",
        "2025", "2026", "111222", "777888", "???", "?????", "!!!",
        "!!!!!", "...", ".....", "?!?", "??!!", "@@@", "###",
        "$$$", "%%%", "&&&", "***", "---", "___", "===",
        "haha", "hihi", "hehe", "huhu", "kaka", "lol", "ahaha",
        "blabla", "bla bla", "abc", "xyz", "abc xyz", "alo alo alo",
        "test test test", "ok ok ok", "hi hi hi", "la la la", "a a a a",
    ]
    assert len(raw_items) == 250, f"Group 1 must have 250 items, got {len(raw_items)}"
    assert len(set(raw_items)) == 250, "Group 1 has duplicate items"
    return [
        {
            "group": "1_nonsense_meta_chitchat",
            "sub_type": "meta_chitchat_nonsense",
            "question": q,
            "history": [],
            "expected_source": None,
            "expected_dept": None,
            "expected_verified": False,
            "expected_is_refusal": True,
        }
        for q in raw_items
    ]


def build_group2_chatgpt_oos() -> list[dict]:
    """Sinh đúng 250 câu hỏi kiểu ChatGPT / Gemini / Ngoài phạm vi quy chế (OOS)."""
    oos_questions = [
        # 1. Lập trình & CNTT đại cương kiểu ChatGPT (40 câu)
        "Viết code Python giải phương trình bậc 2 có nghiệm phức",
        "Viết đoạn code C++ sắp xếp mảng bằng thuật toán QuickSort",
        "Viết code Java quản lý danh sách nhân viên bằng ArrayList",
        "Viết code JavaScript kiểm tra số nguyên tố trong mảng",
        "Lập trình Python đọc file CSV và vẽ biểu đồ bằng Matplotlib",
        "Viết code HTML và CSS tạo trang đăng nhập responsive",
        "Viết câu lệnh code SQL truy vấn top 5 khách hàng mua nhiều nhất",
        "Lập trình C++ cài đặt cấu trúc dữ liệu cây nhị phân tìm kiếm",
        "Viết code Python cào dữ liệu web bằng thư viện BeautifulSoup",
        "Viết đoạn code C# kết nối cơ sở dữ liệu SQL Server",
        "Viết code PHP xử lý form đăng ký thành viên và mã hóa bcrypt",
        "Viết code Python huấn luyện mô hình phân loại ảnh với PyTorch",
        "Cách sửa lỗi NullPointerException khi lập trình Java",
        "Viết code Python tìm đường đi ngắn nhất bằng thuật toán Dijkstra",
        "Lập trình web bằng ReactJS và TailwindCSS bắt đầu như thế nào",
        "Viết code C++ giải bài toán cái túi Knapsack bằng quy hoạch động",
        "Viết code Python chuyển đổi giọng nói thành văn bản",
        "Viết đoạn code JavaScript gọi REST API bằng fetch và async await",
        "Lập trình Python tạo bot Telegram tự động trả lời tin nhắn",
        "Viết code C++ nhân hai ma trận kích thước N x N",
        "Viết code Python kiểm tra chuỗi đối xứng palindrome",
        "Thuật toán sắp xếp MergeSort có độ phức tạp thời gian là bao nhiêu",
        "Viết code Java cài đặt hàng đợi Queue bằng danh sách liên kết",
        "Viết code Python giải hệ phương trình tuyến tính bằng NumPy",
        "Lập trình C++ tìm ước chung lớn nhất và bội chung nhỏ nhất",
        "Viết code JavaScript tạo đồng hồ đếm ngược trên trình duyệt",
        "Viết code Python nén và giải nén file zip tự động",
        "Lập trình Python kết nối SQLite và thêm bản ghi mới",
        "Viết đoạn code HTML tạo bảng danh sách sản phẩm có nút mua hàng",
        "Viết code C++ đếm số từ trong một chuỗi ký tự nhập từ bàn phím",
        "Viết code Python tạo mã QR code từ đường link website",
        "Lập trình Java đọc và ghi file văn bản bằng BufferedReader",
        "Viết code Python giải bài toán tháp Hà Nội bằng đệ quy",
        "Viết code JavaScript lọc các phần tử trùng lặp trong mảng",
        "Thuật toán sắp xếp nổi bọt Bubble Sort hoạt động như thế nào",
        "Viết code C++ kiểm tra số hoàn hảo và số Armstrong",
        "Lập trình Python gửi email tự động qua giao thức SMTP",
        "Viết code SQL tạo bảng đơn hàng có khóa ngoại tham chiếu khách hàng",
        "Viết code Python tính dãy số Fibonacci không dùng đệ quy",
        "Cây nhị phân cân bằng AVL khác gì với cây đỏ đen Red-Black Tree",
        # 2. Toán, Lý, Hóa, Sinh, Văn, Sử, Địa, Dịch thuật (45 câu)
        "Giải phương trình bậc hai 2x^2 - 5x + 2 = 0 chi tiết từng bước",
        "Tính tích phân xác định của hàm số x*sin(x) từ 0 đến pi",
        "Tính đạo hàm bậc nhất của hàm số y = ln(x^2 + 1)",
        "Tìm ma trận nghịch đảo của ma trận vuông cấp 3 trong đại số tuyến tính",
        "Giải hệ phương trình tuyến tính 3 ẩn bằng phương pháp Gauss",
        "Dịch đoạn văn sau sang tiếng Anh chuẩn học thuật IELTS",
        "Dịch câu này sang tiếng Nhật và tiếng Hàn giúp mình",
        "Dịch sang tiếng Anh câu: Chúc bạn một ngày làm việc hiệu quả",
        "Dịch đoạn văn giới thiệu du lịch Vĩnh Long sang tiếng Pháp",
        "Dịch sang tiếng Trung Quốc các câu giao tiếp thương mại cơ bản",
        "Tóm tắt Truyện Kiều của đại thi hào Nguyễn Du trong 200 chữ",
        "Phân tích nhân vật Chí Phèo trong truyện ngắn cùng tên của Nam Cao",
        "Tóm tắt tác phẩm Tắt đèn của nhà văn Ngô Tất Tố",
        "Phân tích giá trị nhân đạo trong truyện ngắn Vợ nhặt của Kim Lân",
        "Tóm tắt truyện ngắn Lão Hạc và phân tích tâm trạng ông giáo",
        "Viết bài văn nghị luận xã hội về lòng biết ơn của giới trẻ hiện nay",
        "Viết đoạn văn tiếng Anh khoảng 150 từ về sở thích đọc sách",
        "Làm bài thơ lục bát 8 câu về mùa thu và tuổi học trò",
        "Sáng tác thơ thất ngôn bát cú Đường luật về cảnh đẹp quê hương",
        "Viết bài văn tả cảnh biển vào buổi sáng bình minh",
        "Định luật II Newton trong vật lý cổ điển được phát biểu như thế nào",
        "Giải thích hiệu ứng quang điện và thuyết lượng tử ánh sáng của Einstein",
        "Cân bằng phương trình hóa học giữa Fe3O4 và dung dịch HNO3 loãng",
        "Quá trình quang hợp ở thực vật diễn ra qua những pha nào",
        "Cấu trúc xoắn kép của phân tử ADN gồm những loại nuclêôtit nào",
        "Chiến thắng Điện Biên Phủ năm 1954 diễn ra trong bao nhiêu ngày đêm",
        "Nguyên nhân bùng nổ và kết quả của cuộc Chiến tranh thế giới thứ hai",
        "Đồng bằng sông Cửu Long có diện tích tự nhiên là bao nhiêu km vuông",
        "Sông Mê Kông chảy qua lãnh thổ của những quốc gia nào ở châu Á",
        "Thủ đô của các nước Đông Nam Á ASEAN gồm những thành phố nào",
        "Tính tích phân bất định của hàm số e^x * cos(x) dx",
        "Tính đạo hàm của hàm số lượng giác y = tan(2x + 1)",
        "Giải phương trình lượng giác sin(2x) + cos(x) = 0",
        "Dịch sang tiếng Anh bức thư xin việc vị trí kỹ sư phần mềm",
        "Tóm tắt truyện Tấm Cám trong kho tàng cổ tích Việt Nam",
        "Viết bài văn phân tích bài thơ Tây Tiến của nhà thơ Quang Dũng",
        "Làm bài thơ 4 chữ tặng thầy cô nhân ngày 20 tháng 11",
        "Giải hệ phương trình bậc nhất hai ẩn 3x + 2y = 7 và x - y = 1",
        "Dịch đoạn văn mô tả quy trình sản xuất nông nghiệp sang tiếng Anh",
        "Tóm tắt tác phẩm Số Đỏ của nhà văn Vũ Trọng Phụng",
        "Viết đoạn văn nghị luận về tác hại của việc nghiện mạng xã hội",
        "Sáng tác thơ tự do về tình bạn thời thanh xuân",
        "Tính tích phân suy rộng của hàm 1/(1 + x^2) từ 0 đến vô cùng",
        "Dịch câu tục ngữ Có công mài sắt có ngày nên kim sang tiếng Anh",
        "Tóm tắt truyện ngắn Rừng xà nu của nhà văn Nguyễn Trung Thành",
        # 3. Ẩm thực, Thời tiết, Phần cứng PC, Tài chính, Thể thao, Giải trí (45 câu)
        "Cách làm món thịt kho tàu nước dừa mềm ngon chuẩn vị miền Tây",
        "Công thức nấu phở bò Hà Nội nước dùng trong và thơm đậm đà",
        "Cách nấu bún bò Huế cay nồng thơm mùi mắm ruốc tại nhà",
        "Cách nấu canh chua cá lóc miền Tây Nam Bộ ngon không bị tanh",
        "Cách làm món gà nướng mật ong bằng nồi chiên không dầu",
        "Công thức nấu lẩu thái chua cay hải sản cho 4 người ăn",
        "Cách làm món sườn xào chua ngọt đậm đà đưa cơm",
        "Cách nấu chè bưởi giòn sần sật không bị đắng tại nhà",
        "Thời tiết Vĩnh Long hôm nay có mưa không và nhiệt độ bao nhiêu độ",
        "Dự báo thời tiết TP Hồ Chí Minh 3 ngày cuối tuần như thế nào",
        "Thời tiết Hà Nội tuần này có đợt không khí lạnh nào không",
        "Nhiệt độ hôm nay ở Cần Thơ và Vĩnh Long là bao nhiêu độ C",
        "Trời có mưa không nếu chiều nay mình đi dạo ở bờ kè Vĩnh Long",
        "Tư vấn cấu hình PC gaming tầm giá 15 triệu chơi mượt các tựa game",
        "Build PC đồ họa render video 4K tầm giá 25 triệu gồm linh kiện gì",
        "Tư vấn laptop mỏng nhẹ pin trâu giá dưới 18 triệu cho dân văn phòng",
        "Mua laptop nào tốt nhất hiện nay để thiết kế đồ họa 3D AutoCAD",
        "Tư vấn điện thoại chụp ảnh đẹp pin 5000mAh dưới 10 triệu đồng",
        "So sánh cấu hình PC dùng CPU Intel Core i5 và AMD Ryzen 5",
        "Giá vàng SJC và vàng nhẫn 9999 hôm nay tăng hay giảm bao nhiêu",
        "Tỷ giá USD và tỷ giá ngoại tệ tại ngân hàng Vietcombank hôm nay",
        "Chỉ số chứng khoán VN-Index hôm nay đóng cửa ở mức bao nhiêu điểm",
        "Giá Bitcoin và thị trường tiền ảo hôm nay biến động thế nào",
        "Giá xăng RON 95 và dầu diesel trong kỳ điều chỉnh mới nhất là bao nhiêu",
        "Lịch thi đấu bóng đá Ngoại hạng Anh cuối tuần này có trận nào tâm điểm",
        "Đội tuyển nào vô địch giải bóng đá World Cup năm 2022 tại Qatar",
        "Kết quả bóng đá cúp C1 Champions League rạng sáng nay thế nào",
        "Kết quả xổ số kiến thiết miền Nam và Vietlott hôm nay ra số mấy",
        "Cung hoàng đạo Bạch Dương tháng này có vận may gì về tài lộc",
        "Xem tử vi tuổi Giáp Thân năm 2026 về sự nghiệp và tình duyên",
        "Phong thủy bàn làm việc cho người mệnh Mộc nên đặt hướng nào",
        "Cách làm món bánh xèo miền Tây giòn rụm vàng ươm",
        "Công thức nấu bò kho bánh mì thơm mềm chuẩn vị",
        "Dự báo thời tiết Đà Lạt dịp cuối tuần này có sương mù không",
        "Build PC gaming 20 triệu dùng card màn hình RTX 4060 có ổn không",
        "Mua laptop MacBook Air M2 hay laptop Windows để làm văn phòng",
        "Giá vàng thế giới quy đổi sang tiền Việt Nam hôm nay là bao nhiêu",
        "Tỷ giá USD tự do và ngân hàng chênh lệch bao nhiêu đồng",
        "Bảng xếp hạng bóng đá Ngoại hạng Anh mùa giải năm nay",
        "Lịch thi đấu Champions League vòng tứ kết diễn ra ngày nào",
        "Cung hoàng đạo Thiên Bình hợp với cung nào trong tình yêu",
        "Xem bói chỉ tay đường sinh đạo và trí đạo nói lên điều gì",
        "Cách nấu hủ tiếu Nam Vang ngon ngọt từ xương ống heo",
        "Thời tiết miền Tây Nam Bộ mùa mưa bắt đầu từ tháng mấy",
        "Tư vấn cấu hình PC chạy giả lập Android mượt mà giá rẻ",
        # 4. Đời sống ngoài phạm vi quy chế (Căn tin, KTX, Gửi xe, Xe buýt, Phòng trọ) (45 câu)
        "Căn tin trường mở cửa từ mấy giờ sáng đến mấy giờ chiều",
        "Thực đơn căn tin trường hôm nay có những món cơm và bún gì",
        "Giá một phần cơm trưa ở căng tin trường là bao nhiêu tiền",
        "Cantin trường có bán đồ ăn sáng và cà phê mang đi không",
        "Ký túc xá trường giá bao nhiêu tiền một tháng cho phòng 4 người",
        "Phòng ký túc xá của trường có lắp máy lạnh và bình nước nóng không",
        "Thủ tục đăng ký ở ký túc xá KTX cho tân sinh viên cần gặp ai",
        "Giờ đóng cửa cổng ký túc xá KTX vào buổi tối là mấy giờ",
        "KTX trường có cho phép sinh viên nấu ăn bằng bếp điện trong phòng không",
        "Tiền phòng trọ xung quanh đường Nguyễn Huệ gần trường khoảng bao nhiêu",
        "Thuê trọ gần trường ở phường Long Châu chỗ nào an ninh và giá rẻ",
        "Nhà trọ sinh viên gần cổng trường có tính giá điện nước theo giá nhà nước không",
        "Giá vé gửi xe tháng ở trường cho xe máy sinh viên là bao nhiêu tiền",
        "Bãi giữ xe của trường nhận giữ xe từ mấy giờ đến mấy giờ tối",
        "Gửi xe tháng ở nhà xe sinh viên cần đăng ký với bảo vệ ở đâu",
        "Phí gửi xe máy qua đêm tại bãi giữ xe của trường là bao nhiêu",
        "Nhà xe sinh viên có nhận giữ xe đạp điện và sạc pin không",
        "Tuyến xe buýt số mấy chạy từ Cần Thơ qua cổng trường ở Vĩnh Long",
        "Xe buýt số mấy đi từ bến xe Vĩnh Long ngang qua đường Nguyễn Huệ",
        "Giá vé xe bus số 1 ở Vĩnh Long dành cho học sinh sinh viên là bao nhiêu",
        "Tuyến xe buýt đi từ Tam Bình lên trường mất khoảng bao nhiêu phút",
        "Thư viện mở cửa từ mấy giờ sáng và thứ Bảy có làm việc không",
        "Giờ mở cửa thư viện trường vào buổi trưa có cho sinh viên ở lại đọc sách không",
        "Căn tin khu nhà B của trường có bán trà sữa và đồ ăn vặt không",
        "Ký túc xá trường có sân phơi đồ và máy giặt công cộng không",
        "Tiền điện nước ở KTX trường tính theo đầu người hay theo đồng hồ",
        "Thuê trọ ở ghép gần trường cần lưu ý những gì về hợp đồng thuê nhà",
        "Vé gửi xe lượt mỗi ngày ở bãi giữ xe trường là mấy ngàn đồng",
        "Làm mất thẻ giữ xe ở bãi giữ xe của trường bị phạt bao nhiêu tiền",
        "Tuyến xe buýt từ Trà Vinh sang Vĩnh Long dừng ở trạm nào gần trường nhất",
        "Giờ mở cửa thư viện trong đợt thi cuối kỳ có kéo dài đến tối không",
        "Căng tin trường có cho thanh toán bằng quét mã QR chuyển khoản không",
        "KTX của trường nằm ở khu nào và có bao nhiêu phòng ở",
        "Nhà trọ sinh viên quanh khu vực phường 2 Vĩnh Long giá bao nhiêu",
        "Gửi xe tháng ở trường có được hoàn tiền nếu nghỉ học sớm không",
        "Xe bus số mấy chạy tuyến Vĩnh Long đi Vũng Liêm ngang trường",
        "Căn tin trường có cho thuê mặt bằng mở quầy bán nước không",
        "Ký túc xá trường có giới hạn số lượng thiết bị điện mang vào phòng không",
        "Tiền phòng trọ có máy lạnh gần trường trung bình bao nhiêu một tháng",
        "Bãi giữ xe khu A và khu B cái nào rộng hơn",
        "Tuyến xe buýt nội ô Vĩnh Long chạy chuyến cuối cùng lúc mấy giờ",
        "Thư viện mở cửa cho mượn sách về nhà tối đa bao nhiêu cuốn",
        "Cantin trường nghỉ bán vào chủ nhật hay vẫn mở cửa bình thường",
        "KTX trường có wifi miễn phí cho từng phòng ở không",
        "Vé gửi xe đạp ở nhà xe sinh viên là bao nhiêu tiền một lượt",
        # 5. Tuyển sinh, Điểm chuẩn, Lịch nghỉ Tết/Lễ, Đơn giá 1 tín chỉ, Nghị quyết 71/72/153 (75 câu)
        "Điểm chuẩn ngành Công nghệ thông tin năm 2026 của trường là bao nhiêu điểm",
        "Điểm chuẩn ngành Công nghệ kỹ thuật ô tô năm ngoái lấy bao nhiêu điểm",
        "Điểm sàn xét tuyển học bạ THPT vào trường năm nay là mấy điểm",
        "Chỉ tiêu tuyển sinh đại học chính quy năm 2026 của trường là bao nhiêu sinh viên",
        "Xét học bạ vào trường cần tính điểm trung bình của mấy học kỳ THPT",
        "Mã trường tuyển sinh đại học của Trường ĐH Sư phạm Kỹ thuật Vĩnh Long là gì",
        "Điểm chuẩn xét tuyển bằng điểm thi đánh giá năng lực ĐHQG TP.HCM là bao nhiêu",
        "Chỉ tiêu tuyển sinh ngành Công nghệ kỹ thuật điện điện tử năm nay là bao nhiêu",
        "Xét học bạ tổ hợp A00 và D01 vào ngành CNTT cần tối thiểu bao nhiêu điểm",
        "Điểm chuẩn ngành Kỹ thuật cơ khí và Cơ điện tử chênh nhau bao nhiêu điểm",
        "Điểm sàn xét tuyển bằng điểm thi tốt nghiệp THPT của trường là bao nhiêu",
        "Mã trường tuyển sinh SPK hay VLU được dùng khi đăng ký nguyện vọng Bộ GDĐT",
        "Chỉ tiêu tuyển sinh hệ liên thông và vừa làm vừa học năm 2026 là bao nhiêu",
        "Điểm chuẩn ngành Thú y và Công nghệ thực phẩm năm nay lấy bao nhiêu",
        "Xét học bạ lớp 12 vào trường có cần điều kiện hạnh kiểm Tốt không",
        "Lịch nghỉ Tết Nguyên Đán năm 2026 của sinh viên trường kéo dài bao nhiêu ngày",
        "Tết Nguyên Đán năm nay sinh viên được nghỉ từ ngày mấy âm lịch đến ngày mấy",
        "Lịch nghỉ Tết Âm lịch của trường bắt đầu từ tuần thứ mấy của học kỳ 2",
        "Nghỉ lễ 30/4 và 1/5 năm nay sinh viên trường được nghỉ mấy ngày liên tiếp",
        "Nghỉ lễ 2/9 Quốc khánh sinh viên có được nghỉ bù thêm ngày thứ Sáu không",
        "Lịch nghỉ hè của sinh viên chính quy kéo dài từ tháng mấy đến tháng mấy",
        "Tết Nguyên Đán sinh viên ở xa có được trường hỗ trợ vé xe về quê ăn Tết không",
        "Lịch nghỉ Tết Dương lịch 1/1 sinh viên được nghỉ mấy ngày",
        "Nghỉ lễ 30/4 trường có tổ chức học bù vào ngày Chủ nhật không",
        "Lịch nghỉ hè năm học 2025-2026 kéo dài mấy tuần trước khi vào năm học mới",
        "Đơn giá 1 tín chỉ là bao nhiêu tiền đối với sinh viên khóa mới",
        "1 tín chỉ bao nhiêu tiền ở học kỳ này đối với ngành Công nghệ thông tin",
        "Một tín chỉ bao nhiêu tiền nếu đăng ký học lại học phần thực hành",
        "Đơn giá 1 tín chỉ là bao nhiêu tiền cho hệ đại học chính quy đại trà",
        "1 tín chỉ bao nhiêu tiền đối với các môn đại cương và môn chuyên ngành",
        "Một tín chỉ bao nhiêu tiền khi sinh viên đăng ký học kỳ phụ mùa hè",
        "Nghị quyết 71 quy định những nội dung gì về chiến lược phát triển",
        "Nghị quyết 72 của Chính phủ có những điểm mới nào cần lưu ý",
        "Nghị quyết 153 quy định gì về chương trình hành động hội nhập quốc tế",
        "Tóm tắt nội dung chính của Nghị quyết 71 và Nghị quyết 153 giúp mình",
        "Theo 153/NQ-CP thì mục tiêu hội nhập quốc tế về giáo dục là gì",
        "Theo 71/NQ-CP và 72/NQ-CP thì các nhiệm vụ trọng tâm gồm những gì",
        "Nghị quyết 153/NQ-CP được ban hành vào ngày tháng năm nào",
        "Nội dung về hội nhập quốc tế trong Nghị quyết 153 áp dụng ra sao",
        "Nghị quyết 71/NQ-CP giao nhiệm vụ gì cho các bộ ngành địa phương",
        "Nghị quyết 72/NQ-CP có hiệu lực thi hành từ thời điểm nào",
        "So sánh điểm giống nhau giữa Nghị quyết 71 và Nghị quyết 72",
        "Nghị quyết 153 và Nghị quyết 71 có liên quan gì đến sinh viên không",
        "Điểm chuẩn ngành Công nghệ sinh học của trường năm 2026 là bao nhiêu",
        "Điểm sàn xét tuyển sớm đợt 1 bằng học bạ THPT là bao nhiêu điểm",
        "Chỉ tiêu tuyển sinh ngành Kinh tế và Quản trị kinh doanh năm nay",
        "Xét học bạ ngành Công nghệ thông tin lấy điểm 3 môn hay 6 học kỳ",
        "Mã trường tuyển sinh và mã ngành Công nghệ kỹ thuật ô tô là số mấy",
        "Lịch nghỉ Tết Nguyên Đán năm sau sinh viên tập trung lại vào ngày nào",
        "Tết Nguyên Đán trường có cho học online tuần giáp Tết không",
        "Nghỉ lễ 2/9 trường có thông báo nghỉ học từ thứ mấy",
        "Lịch nghỉ hè có trùng với đợt học giáo dục quốc phòng an ninh không",
        "1 tín chỉ bao nhiêu tiền nếu sinh viên học song ngành thứ hai",
        "Một tín chỉ bao nhiêu tiền đối với học phần đồ án và khóa luận",
        "Nghị quyết 71 ban hành kèm theo kế hoạch triển khai nào",
        "Nghị quyết 72 đề cập đến những giải pháp kinh tế xã hội nào",
        "Nghị quyết 153 về hội nhập quốc tế có bao nhiêu nhóm giải pháp",
        "Điểm chuẩn ngành Sư phạm kỹ thuật công nghiệp năm 2026 là bao nhiêu",
        "Điểm sàn xét tuyển đại học chính quy theo phương thức điểm thi THPT",
        "Chỉ tiêu tuyển sinh theo phương thức xét điểm đánh giá năng lực là bao nhiêu",
        "Xét học bạ đợt bổ sung của trường kết thúc nhận hồ sơ vào ngày nào",
        "Mã trường tuyển sinh của VLUTE trên cổng thông tin Bộ Giáo dục là gì",
        "Lịch nghỉ Tết Nguyên Đán có được cộng gộp với ngày nghỉ cuối tuần không",
        "Tết Nguyên Đán sinh viên được nghỉ tổng cộng mấy tuần lễ",
        "Nghỉ lễ 30/4 và Giỗ tổ Hùng Vương 10/3 được nghỉ mấy ngày",
        "Nghỉ lễ 2/9 có ảnh hưởng đến lịch thi kết thúc học phần không",
        "Lịch nghỉ hè của sinh viên năm cuối khác gì sinh viên năm nhất",
        "Đơn giá 1 tín chỉ là bao nhiêu tiền đối với môn Giáo dục thể chất",
        "1 tín chỉ bao nhiêu tiền cho khối ngành kỹ thuật công nghệ năm 2026",
        "Một tín chỉ bao nhiêu tiền khi tính học phí học kỳ 1 năm nhất",
        "Nghị quyết 71 và 72 được Chính phủ thông qua trong phiên họp nào",
        "Nghị quyết 153 quy định trách nhiệm của các cơ sở giáo dục ra sao",
        "Hội nhập quốc tế theo Nghị quyết 153/NQ-CP đặt mục tiêu đến năm 2030 thế nào",
        "Theo 71/NQ-CP thì các chỉ tiêu cơ bản cần đạt được là gì",
        "Theo 72/NQ-CP thì chính sách hỗ trợ phát triển được quy định thế nào",
    ]
    assert len(oos_questions) == 250, f"Group 2 must have 250 items, got {len(oos_questions)}"
    assert len(set(oos_questions)) == 250, "Group 2 has duplicate items"
    return [
        {
            "group": "2_chatgpt_oos",
            "sub_type": "chatgpt_or_campus_oos",
            "question": q,
            "history": [],
            "expected_source": None,
            "expected_dept": None,
            "expected_verified": False,
            "expected_is_refusal": True,
        }
        for q in oos_questions
    ]


def build_group3_multiturn() -> list[dict]:
    """
    Sinh 150 kịch bản hội thoại đa lượt:
    - 75 cặp hội thoại nối tiếp hợp lệ (3a_multiturn_valid) trên cả 8 tài liệu
    - 75 cặp hội thoại bẫy (3b_multiturn_trap) không được dính ngữ cảnh cũ
    """
    base_contexts = [
        (
            "xet_cap_hoc_bong.pdf",
            "Phòng Công tác Sinh viên (VLUTE)",
            "Điều kiện để sinh viên được xét cấp học bổng khuyến khích học tập (KKHT) là gì?",
            "Sinh viên cần đăng ký tối thiểu 17 tín chỉ, điểm TBC học kỳ từ 2,5 trở lên (không có môn dưới C) và rèn luyện từ loại Khá trở lên.",
            [
                "Vậy nếu có một môn bị điểm D thì có được xét học bổng này không?",
                "Còn đối với học kỳ đầu khóa thì điều kiện số tín chỉ của nó quy định thế nào?",
                "Vậy mức tiền học bổng Mức 1 của chế độ này được tính theo công thức nào?",
                "Còn trường hợp nhiều sinh viên đồng hạng thì thứ tự ưu tiên xét của nó ra sao?",
                "Vậy những học phần học lại hoặc giáo dục quốc phòng có được tính vào 17 tín chỉ của nó không?",
                "Còn nếu sinh viên bị kỷ luật khiển trách thì có được nhận học bổng này không?",
                "Vậy điểm trung bình chung học kỳ để xét loại học bổng này tính theo điểm thi lần mấy?",
                "Còn tỷ lệ tiền học bổng Mức 2, Mức 3 và Mức 4 của nó so với Mức 1 là bao nhiêu?",
                "Vậy sau khi nhận học bổng SPKT Mức 1 của chế độ này thì kỳ sau phải đăng ký mấy tín chỉ SPKT?",
                "Còn phòng ban nào thực hiện chi trả tiền học bổng này cho sinh viên sau khi có quyết định?",
            ],
        ),
        (
            "quy_dinh_mien_giam_hoc_phi.pdf",
            "Phòng Công tác Sinh viên (VLUTE) – Đầu mối tiếp nhận hồ sơ (Phối hợp Phòng Kế hoạch - Tài chính)",
            "Những đối tượng sinh viên nào thuộc diện được miễn 100% học phí theo quy định hiện hành?",
            "Các đối tượng miễn 100% học phí gồm người có công, sinh viên khuyết tật, mồ côi 16-22 tuổi hưởng trợ cấp XH, hệ cử tuyển, dân tộc thiểu số hộ nghèo/cận nghèo và 16 dân tộc thiểu số rất ít người.",
            [
                "Vậy thời hạn nộp hồ sơ đề nghị của chế độ này là bao nhiêu ngày kể từ ngày khai giảng?",
                "Còn những đối tượng nào được giảm 70% học phí theo quy định này?",
                "Vậy sinh viên là con của viên chức, người lao động tại trường thì được giảm bao nhiêu phần trăm theo chính sách này?",
                "Còn trong thời gian bị kỷ luật ngừng học hoặc học lại thì sinh viên có được hưởng chế độ này không?",
                "Vậy kinh phí cấp bù của chế độ này được tính tối đa bao nhiêu tháng trong một năm học?",
                "Còn sinh viên thuộc diện hộ nghèo thì mỗi học kỳ cần nộp bổ sung giấy tờ gì cho chế độ này?",
                "Vậy nếu sinh viên học cùng lúc 2 ngành trong trường thì chế độ này giải quyết thế nào?",
                "Còn mức hỗ trợ chi phí học tập đối với sinh viên dân tộc thiểu số hộ nghèo trong quy định này là bao nhiêu?",
                "Vậy hồ sơ xin hưởng chế độ này nộp trực tiếp tại phòng ban nào của trường?",
                "Còn mẫu đơn đề nghị hưởng chế độ này được quy định tại Phụ lục số mấy?",
            ],
        ),
        (
            "quy_trinh_hoan_tra_hoc_phi.pdf",
            "Tuyến phối hợp xử lý (CTSV – Đào tạo – KHTC)",
            "Quy trình hoàn trả học phí thừa cho sinh viên (QT-SV-04) được thực hiện qua các bước nào?",
            "Quy trình QT-SV-04 gồm 5 bước phối hợp giữa Phòng Công tác Sinh viên, Phòng Đào tạo, Ban Giám hiệu và Phòng Kế hoạch - Tài chính.",
            [
                "Vậy tổng thời gian giải quyết từ khi kết thúc nhận đơn của quy trình này là bao nhiêu ngày làm việc?",
                "Còn ở Bước 1 của quy trình này thì sinh viên cần tải biểu mẫu mã hiệu gì để điền đơn?",
                "Vậy những chứng từ nào bắt buộc phải đính kèm theo đơn trong quy trình này?",
                "Còn Phòng Đào tạo có trách nhiệm kiểm tra xác nhận học phí thừa ở bước mấy của quy trình này?",
                "Vậy sau khi Phòng Đào tạo xác nhận xong thì trong bao nhiêu ngày phải chuyển lại cho Phòng CTSV theo quy trình này?",
                "Còn ở Bước 4 của quy trình này thì lãnh đạo nào phê duyệt danh sách hoàn trả học phí thừa?",
                "Vậy sinh viên nhận lại tiền hoàn trả bằng tiền mặt hay chuyển khoản ở bước cuối của quy trình này?",
                "Còn hồ sơ hoàn tất của quy trình này sẽ được lưu trữ tại những đơn vị nào?",
                "Vậy nếu sinh viên nộp biên lai điện tử trong quy trình này thì có được chấp nhận không?",
            ],
        ),
        (
            "tin_chi_cong_tac_xa_hoi.pdf",
            "Phòng Công tác Sinh viên (VLUTE)",
            "Sinh viên đại học chính quy cần tích lũy tối thiểu bao nhiêu ngày công tác xã hội (CTXH) để xét tốt nghiệp?",
            "Sinh viên đại học chính quy phải tích lũy tối thiểu 12 ngày CTXH trong toàn khóa học mới đủ điều kiện đăng ký học phần tốt nghiệp và xét công nhận tốt nghiệp.",
            [
                "Vậy 12 ngày của hoạt động này được phân bổ cụ thể từ năm nhất đến năm tư như thế nào?",
                "Còn nếu sinh viên tham gia hiến máu tình nguyện thì được quy đổi bao nhiêu ngày cho hoạt động này?",
                "Vậy tham gia chiến dịch Mùa hè xanh hoặc Tiếp sức mùa thi được tính mấy ngày trong quy định này?",
                "Còn sinh viên thuộc diện khuyết tật thì định mức ngày phải tích lũy của quy định này giảm còn bao nhiêu?",
                "Vậy nếu sinh viên chưa tích lũy đủ số ngày của hoạt động này thì có được đăng ký làm khóa luận tốt nghiệp không?",
                "Còn khi tham gia hỗ trợ tổ chức hiến máu theo bảng phân công thì được tính mấy ngày trong quy định này?",
                "Vậy nếu một hoạt động không nằm trong Phụ lục danh mục của quy định này thì ai có thẩm quyền phê duyệt?",
                "Còn hành vi làm giả giấy xác nhận của hoạt động này sẽ bị xử lý kỷ luật như thế nào?",
                "Vậy đơn vị nào cấp giấy chứng nhận hoàn thành chuẩn của hoạt động này cho sinh viên?",
            ],
        ),
        (
            "quy_dinh_cong_tac_sinh_vien.pdf",
            "Phòng Công tác Sinh viên (VLUTE)",
            "Quy định công tác sinh viên đối với chương trình đào tạo đại học chính quy quy định những quyền lợi và nghĩa vụ gì?",
            "Quy định công tác sinh viên (QĐ 1079) quy định rõ nhiệm vụ, quyền lợi sinh viên, hệ thống Ban cán sự lớp, cố vấn học tập và khung xử lý kỷ luật sinh viên.",
            [
                "Vậy theo quy định này thì Ban cán sự lớp gồm những chức danh nào và được hưởng quyền lợi điểm rèn luyện ra sao?",
                "Còn hành vi thi hộ hoặc nhờ người khác thi hộ trong quy định này bị xử lý kỷ luật ở mức nào?",
                "Vậy nếu sinh viên tổ chức học thay hoặc thi thay theo quy định này thì bị xử lý kỷ luật gì ngay từ lần đầu?",
                "Còn khi sinh viên muốn khiếu nại kết quả học tập hoặc rèn luyện theo quy định này thì thời hiệu khiếu nại là bao nhiêu ngày?",
                "Vậy những trường hợp nào sinh viên bị buộc thôi học theo quy định này?",
                "Còn thủ tục xin nghỉ học tạm thời bảo lưu kết quả theo quy định này yêu cầu thời gian học tối thiểu bao lâu?",
                "Vậy hội đồng kỷ luật sinh viên trong quy định này gồm những thành phần nào?",
                "Còn hành vi mang tài liệu trái phép vào phòng thi bị xử lý kỷ luật thế nào theo phụ lục của quy định này?",
                "Vậy lớp trưởng không hoàn thành nhiệm vụ thì có được cộng điểm rèn luyện theo quy định này không?",
            ],
        ),
        (
            "quy_tac_ung_xu.pdf",
            "Phòng Công tác Sinh viên (VLUTE)",
            "Quy tắc ứng xử của sinh viên trong Nhà trường quy định như thế nào về trang phục và thái độ học tập?",
            "Quy tắc ứng xử yêu cầu sinh viên mặc trang phục lịch sự, đeo thẻ sinh viên khi vào trường, tôn trọng giảng viên và ứng xử văn minh trên mạng xã hội.",
            [
                "Vậy theo quy tắc này thì sinh viên cần ứng xử như thế nào khi đăng bài hoặc bình luận trên mạng xã hội?",
                "Còn những hành vi nào bị nghiêm cấm đối với sinh viên trong khuôn viên trường theo quy tắc này?",
                "Vậy khi giao tiếp với giảng viên và viên chức nhà trường thì sinh viên phải giữ thái độ ra sao theo quy tắc này?",
                "Còn đối với tài sản, thiết bị phòng học và cảnh quan môi trường thì quy tắc này yêu cầu sinh viên làm gì?",
                "Vậy việc hút thuốc lá hoặc sử dụng rượu bia trong trường bị cấm như thế nào trong quy tắc này?",
                "Còn khi phát hiện hành vi bạo lực học đường hoặc nói xấu trên mạng thì quy tắc này hướng dẫn xử lý thế nào?",
                "Vậy trang phục khi đi học và khi tham dự lễ trang trọng của trường được quy định ra sao trong quy tắc này?",
                "Còn trong giờ học và giờ thi thì quy tắc này yêu cầu người học phải tuân thủ những chuẩn mực nào?",
                "Vậy sinh viên vi phạm các chuẩn mực của quy tắc này sẽ bị xem xét đánh giá vào điểm gì?",
            ],
        ),
        (
            "quy_che_an_toan_thong_tin.pdf",
            "Trung tâm Công nghệ Thông tin (VLUTE)",
            "Quy chế bảo đảm an toàn thông tin, an ninh mạng của Trường quy định như thế nào về tài khoản và mật khẩu?",
            "Quy chế bảo đảm an toàn thông tin (QĐ 1316) quy định chính sách mật khẩu mạnh tối thiểu 8 ký tự, đổi mật khẩu định kỳ và quản lý email tên miền @vlute.edu.vn, @st.vlute.edu.vn.",
            [
                "Vậy mật khẩu tài khoản email sinh viên theo quy chế này phải được thay đổi định kỳ tối thiểu bao lâu một lần?",
                "Còn chu kỳ đổi mật khẩu đối với tài khoản quản trị máy chủ và ứng dụng trong quy chế này là mấy tháng?",
                "Vậy sinh viên có được dùng email @st.vlute.edu.vn để đăng ký mạng xã hội hay dịch vụ bên ngoài theo quy chế này không?",
                "Còn thiết bị cá nhân như laptop, điện thoại chỉ được kết nối internet qua vùng mạng nào theo quy chế này?",
                "Vậy khi phát hiện email lạ có dấu hiệu lừa đảo phishing thì người dùng phải xử lý thế nào theo quy chế này?",
                "Còn trước khi mang thiết bị CNTT chứa dữ liệu của trường ra ngoài sửa chữa, bảo hành thì quy chế này bắt buộc làm gì?",
                "Vậy hồ sơ quản lý rủi ro an toàn thông tin trong quy chế này phải được rà soát định kỳ bao lâu một lần?",
                "Còn quy chế này được Nhà trường rà soát và cập nhật định kỳ mấy năm một lần?",
                "Vậy đơn vị nào chịu trách nhiệm thu thập ý kiến và soạn thảo cập nhật quy chế này?",
            ],
        ),
        (
            "BM-DT-04_IT1216_PHAN_MEM_MA_NGUON_MO (2026).docx",
            "Phòng Đào tạo (VLUTE)",
            "Học phần Phần mềm mã nguồn mở (IT1216) có bao nhiêu tín chỉ và do những giảng viên nào phụ trách?",
            "Học phần Phần mềm mã nguồn mở (Mã HP: IT1216) có 2 tín chỉ (0 lý thuyết, 2 thực hành tại lớp), do ThS. Nguyễn Vạn Năng phụ trách chính cùng ThS. Trần Hồ Đạt và ThS. Nguyễn Công Kha.",
            [
                "Vậy học phần này có yêu cầu học phần tiên quyết hay học phần học trước nào không?",
                "Còn phương pháp kiểm tra đánh giá và các cột hệ số điểm chuyên cần, quá trình, cuối kỳ của học phần này quy định thế nào?",
                "Vậy giáo trình chính và các sách tham khảo của học phần này gồm những tài liệu nào?",
                "Còn học phần này được tổ chức giảng dạy theo hình thức trực tiếp hay trực tuyến?",
                "Vậy các chuẩn đầu ra 7.1.1, 7.2.1 và 7.3.2 của học phần này đóng góp vào những chuẩn đầu ra nào của chương trình đào tạo?",
                "Còn nhiệm vụ của sinh viên về tỷ lệ dự lớp tối thiểu và hoàn thành bài tập trong học phần này là bao nhiêu phần trăm?",
                "Vậy nội dung thực hành trên hệ điều hành Linux của học phần này gồm những chủ đề chính nào?",
                "Còn trong hoạt động dạy và học của học phần này thì giảng viên hướng dẫn sinh viên sử dụng những công cụ AI và hệ thống nào?",
                "Vậy bài thi kết thúc cuối kỳ B3.1 của học phần này thi theo hình thức trắc nghiệm hay thi thực hành?",
                "Còn mục tiêu về kiến thức và kỹ năng sử dụng Ubuntu/Linux của học phần này được quy định như thế nào?",
            ],
        ),
    ]

    valid_pairs = []
    for src, dept, turn1_q, turn1_a, followups in base_contexts:
        for fq in followups:
            valid_pairs.append(
                {
                    "group": "3a_multiturn_valid",
                    "sub_type": "contextual_followup",
                    "question": fq,
                    "history": [
                        {"role": "user", "content": turn1_q},
                        {"role": "assistant", "content": turn1_a},
                    ],
                    "expected_source": src,
                    "expected_dept": dept,
                    "expected_verified": True,
                    "expected_is_refusal": False,
                }
            )
    assert len(valid_pairs) == 75, f"Group 3a must have 75 items, got {len(valid_pairs)}"

    trap_turns = [
        "đặt câu hỏi đi", "hỏi đi", "hỏi lại đi", "nói đi", "nói gì đi",
        "trả lời đi", "gợi ý đi", "tiếp đi", "bắt đầu đi", "làm đi",
        "ok", "okay", "oke", "oki", "ok cảm ơn",
        "oke cảm ơn", "cảm ơn", "cảm ơn lucas", "cảm ơn bạn", "thanks",
        "thank you", "tks", "rõ rồi", "hiểu rồi", "đã hiểu",
        "biết rồi", "hay quá", "tốt quá", "tuyệt vời", "chuẩn luôn",
        "bạn ăn cơm chưa", "ăn cơm chưa", "buồn ngủ quá", "mệt quá", "chán quá",
        "đói bụng quá", "bạn khỏe không", "bạn mấy tuổi", "bạn có người yêu chưa", "kể chuyện cười đi",
        "hát một bài đi", "tạm biệt", "chúc ngủ ngon", "bye", "test",
        "testing", "asdfghjkl", "qwertyuiop", "123456", "???",
        "!!!", "haha", "hihi", "alo alo alo", "xóa lịch sử đi",
        "viết code đi", "viết code Python giải phương trình bậc 2", "viết đoạn code C++ sắp xếp mảng",
        "dịch đoạn văn sau sang tiếng Anh", "tóm tắt Truyện Kiều",
        "cách làm món thịt kho tàu", "công thức nấu phở bò", "thời tiết Vĩnh Long hôm nay",
        "tư vấn cấu hình PC gaming", "mua laptop nào tốt nhất",
        "giá vàng hôm nay bao nhiêu", "lịch thi đấu bóng đá Ngoại hạng Anh", "căn tin trường mở cửa mấy giờ",
        "ký túc xá trường giá bao nhiêu", "vé gửi xe tháng ở trường bao nhiêu",
        "tuyến xe buýt số mấy qua trường", "điểm chuẩn ngành CNTT năm 2026", "lịch nghỉ Tết Nguyên Đán năm 2026",
        "1 tín chỉ bao nhiêu tiền", "nghị quyết 71 và 153 quy định gì",
    ]
    assert len(trap_turns) == 75, f"Group 3b must have 75 items, got {len(trap_turns)}"

    trap_pairs = []
    for idx, tq in enumerate(trap_turns):
        ctx = base_contexts[idx % len(base_contexts)]
        trap_pairs.append(
            {
                "group": "3b_multiturn_trap",
                "sub_type": "context_bleed_trap",
                "question": tq,
                "history": [
                    {"role": "user", "content": ctx[2]},
                    {"role": "assistant", "content": ctx[3]},
                ],
                "expected_source": None,
                "expected_dept": None,
                "expected_verified": False,
                "expected_is_refusal": True,
            }
        )

    return valid_pairs + trap_pairs


def build_group4_in_scope() -> list[dict]:
    """
    Sinh đúng 350 câu hỏi đúng phạm vi quy chế & Đề cương IT1216 (phân bổ đều trên cả 8 tài liệu):
    - 6 tài liệu × 44 câu + 2 tài liệu × 43 câu = 350 câu.
    - Bao gồm câu hỏi chuẩn, viết tắt (KKHT, CTXH, CTSV, ATTT, IT1216), số liệu bảng biểu,
      và tăng cường câu hỏi tình huống đời thường (đặc biệt nhóm Quy tắc ứng xử).
    """
    counts_per_pdf = {
        "xet_cap_hoc_bong.pdf": 44,
        "quy_dinh_mien_giam_hoc_phi.pdf": 44,
        "quy_trinh_hoan_tra_hoc_phi.pdf": 43,
        "tin_chi_cong_tac_xa_hoi.pdf": 44,
        "quy_dinh_cong_tac_sinh_vien.pdf": 44,
        "quy_tac_ung_xu.pdf": 34,  # + 10 câu tình huống đời thường tăng cường = 44
        "quy_che_an_toan_thong_tin.pdf": 43,
    }

    records = []
    for src_file, take_n in counts_per_pdf.items():
        cfg = QUESTIONS_BY_DOC[src_file]
        exp_dept = cfg["expected_dept"]
        q_list = cfg["questions"][:take_n]
        for topic, style, q_text in q_list:
            records.append(
                {
                    "group": "4_in_scope_regulation",
                    "sub_type": f"{src_file}:{style}",
                    "question": q_text,
                    "history": [],
                    "expected_source": src_file,
                    "expected_dept": exp_dept,
                    "expected_verified": True,
                    "expected_is_refusal": False,
                }
            )

    # Bổ sung 10 câu hỏi tình huống đời thường tăng cường cho quy_tac_ung_xu.pdf (đủ 44 câu)
    ung_xu_situational = [
        "Sinh viên mặc quần đùi, áo ba lỗ hoặc trang phục phản cảm khi vào giảng đường học tập có vi phạm quy tắc ứng xử không?",
        "Khi lên mạng xã hội Facebook bình luận thiếu chuẩn mực hoặc chia sẻ thông tin sai sự thật làm ảnh hưởng uy tín VLUTE thì vi phạm quy định nào?",
        "Sinh viên hút thuốc lá hoặc uống rượu bia ngay trong phòng học và khuôn viên trường bị nghiêm cấm theo quy tắc ứng xử nào?",
        "Khi vào trường học tập nhưng sinh viên quên không đeo thẻ sinh viên thì có vi phạm quy định về trang phục trong quy tắc ứng xử không?",
        "Trong giờ học trên lớp, sinh viên tự ý làm việc riêng, gây mất trật tự và thiếu tôn trọng giảng viên thì vi phạm điều khoản ứng xử nào?",
        "Sinh viên tự ý viết vẽ bậy lên bàn ghế, tường lớp học hoặc làm hư hỏng thiết bị thực hành vi phạm quy tắc ứng xử với tài sản nhà trường ra sao?",
        "Khi giao tiếp với bạn bè quốc tế hoặc sinh viên vùng miền khác, việc kỳ thị dân tộc, tôn giáo, giới tính bị cấm trong quy tắc ứng xử thế nào?",
        "Sinh viên xả rác bừa bãi, không tiết kiệm điện nước khi rời khỏi phòng học vi phạm quy định giữ gìn môi trường học đường ra sao?",
        "Khi tham dự lễ khai giảng hoặc lễ trao bằng tốt nghiệp trang trọng của trường, sinh viên cần tuân thủ quy tắc ứng xử về trang phục thế nào?",
        "Nếu phát hiện bạn học có hành vi bạo lực học đường hoặc quay clip phát tán nói xấu nhau trên mạng xã hội thì quy tắc ứng xử yêu cầu sinh viên làm gì?",
    ]
    for q_ux in ung_xu_situational:
        records.append(
            {
                "group": "4_in_scope_regulation",
                "sub_type": "quy_tac_ung_xu.pdf:situational",
                "question": q_ux,
                "history": [],
                "expected_source": "quy_tac_ung_xu.pdf",
                "expected_dept": "Phòng Công tác Sinh viên (VLUTE)",
                "expected_verified": True,
                "expected_is_refusal": False,
            }
        )

    # 44 câu hỏi toàn diện cho Đề cương học phần BM-DT-04_IT1216_PHAN_MEM_MA_NGUON_MO (2026).docx
    it1216_file = "BM-DT-04_IT1216_PHAN_MEM_MA_NGUON_MO (2026).docx"
    it1216_dept = "Phòng Đào tạo (VLUTE)"
    it1216_questions = [
        "Học phần Phần mềm mã nguồn mở có mã học phần chính thức là gì?",
        "Tên tiếng Anh của học phần Phần mềm mã nguồn mở (IT1216) trong đề cương là gì?",
        "Đề cương học phần Phần mềm mã nguồn mở (IT1216) dùng cho trình độ đào tạo và ngành nào?",
        "Tổng số tín chỉ của học phần Phần mềm mã nguồn mở (IT1216) là bao nhiêu tín chỉ?",
        "Môn Phần mềm mã nguồn mở (IT1216) có bao nhiêu tín chỉ lý thuyết và bao nhiêu tín chỉ thực hành tại lớp?",
        "Số tín chỉ đồ án, tiểu luận, khóa luận và thực hành thực tế ngoài trường của môn IT1216 là bao nhiêu?",
        "Giảng viên phụ trách chính giảng dạy học phần Phần mềm mã nguồn mở (IT1216) là thầy nào?",
        "Những giảng viên nào cùng tham gia giảng dạy môn Phần mềm mã nguồn mở (IT1216)?",
        "Học phần Phần mềm mã nguồn mở (IT1216) có yêu cầu học phần tiên quyết nào không?",
        "Điều kiện về học phần học trước và học phần học song hành của môn IT1216 được quy định thế nào?",
        "Mục tiêu 6.1 về kiến thức của học phần Phần mềm mã nguồn mở (IT1216) là gì?",
        "Mục tiêu 6.2 về kỹ năng cài đặt, cấu hình Ubuntu/Linux của môn IT1216 được nêu như thế nào?",
        "Mục tiêu 6.3 về năng lực tự chủ và tinh thần hợp tác trong cộng đồng mã nguồn mở của môn IT1216 là gì?",
        "Chuẩn đầu ra kiến thức 7.1.1 và 7.1.2 của học phần Phần mềm mã nguồn mở (IT1216) yêu cầu sinh viên đạt được gì?",
        "Chuẩn đầu ra kỹ năng 7.2.1 và 7.2.2 của học phần IT1216 quy định những kỹ năng thực hành nào trên Ubuntu/Linux?",
        "Chuẩn đầu ra 7.3.1 và 7.3.2 về mức độ tự chủ và trách nhiệm của học phần IT1216 là gì?",
        "Các chuẩn đầu ra 7.1.1, 7.2.1 và 7.3.2 của học phần IT1216 đóng góp vào chuẩn đầu ra nào của chương trình đào tạo?",
        "Ma trận tích hợp chuẩn đầu ra học phần IT1216 đóng góp ở mức độ số mấy vào CĐR03, CĐR07 và CĐR13?",
        "Mô tả tóm tắt nội dung học phần Phần mềm mã nguồn mở (IT1216) tại mục 8 gồm những nội dung gì?",
        "Theo mục 9 đề cương học phần IT1216, nhiệm vụ của sinh viên về tỷ lệ dự lớp tối thiểu là bao nhiêu phần trăm số tiết giảng?",
        "Sinh viên học môn Phần mềm mã nguồn mở (IT1216) phải hoàn thành bao nhiêu phần trăm bài tập về nhà do giảng viên giao?",
        "Thiết bị và phương tiện học tập tại mục 10.1 của môn Phần mềm mã nguồn mở (IT1216) yêu cầu những công cụ gì?",
        "Giáo trình chính của học phần Phần mềm mã nguồn mở (IT1216) tại mục 10.2 là cuốn bài giảng nào và xuất bản năm mấy?",
        "Danh mục sách tham khảo tại mục 10.3 của đề cương học phần IT1216 gồm những tài liệu nào của Phan Như Minh, Trần Văn Hùng và William E. Shotts?",
        "Phương pháp giảng dạy và phương pháp học tập tại mục 11 của học phần Phần mềm mã nguồn mở (IT1216) gồm những phương pháp nào?",
        "Bảng phương pháp kiểm tra đánh giá mục 12 của học phần IT1216 gồm mấy nhóm nội dung đánh giá chính?",
        "Cách tính điểm và hệ số các bài đánh giá chuyên cần, quá trình, cuối kỳ của môn IT1216 như thế nào?",
        "Nhóm đánh giá A1 Chuyên cần của môn Phần mềm mã nguồn mở (IT1216) gồm những bài đánh giá nào và có hệ số là bao nhiêu?",
        "Bài đánh giá B1.1 Điểm danh và B1.2 Bài tập trên lớp, về nhà của môn IT1216 có tiêu chí đánh giá và hệ số thế nào?",
        "Nhóm đánh giá A2 Quá trình của học phần IT1216 gồm hai bài đánh giá B2.1 và B2.2 với hệ số mỗi bài là bao nhiêu?",
        "Bài đánh giá B2.1 Trắc nghiệm trên hệ thống Elearning của môn IT1216 đánh giá nội dung gì và hệ số mấy?",
        "Bài đánh giá B2.2 Thực hành trong quá trình học môn IT1216 kiểm tra những nội dung Linux nào và hệ số bao nhiêu?",
        "Nhóm đánh giá A3 Cuối kỳ (Bài đánh giá B3.1) của môn Phần mềm mã nguồn mở (IT1216) thi theo hình thức nào và có hệ số mấy?",
        "Tổng cộng 4 cột hệ số thành phần trong bảng đánh giá học phần Phần mềm mã nguồn mở (IT1216) lần lượt là những con số nào?",
        "Thang điểm đánh giá và cách quy đổi điểm học phần tại mục 12.2 của đề cương IT1216 thực hiện theo quy chế nào?",
        "Nội dung chi tiết học phần IT1216 tại mục 13 chia thành 3 phần lớn với tổng số tiết thực hành là bao nhiêu tiết?",
        "Phần 1 (Hệ điều hành mã nguồn mở GNU/Linux) trong đề cương học phần IT1216 có bao nhiêu tiết thực hành và gồm những bài nào?",
        "Phần 2 (Một số phần mềm mã nguồn mở thông dụng như tiện ích make, ứng dụng văn phòng, quản trị CSDL) của môn IT1216 có bao nhiêu tiết thực hành?",
        "Phần 3 (Giấy phép và tài nguyên giáo dục mở) trong học phần Phần mềm mã nguồn mở (IT1216) gồm những nội dung thực hành nào?",
        "Trong kế hoạch giảng dạy mục 14 của học phần IT1216, giảng viên hướng dẫn sinh viên sử dụng công cụ AI để hỗ trợ tra cứu những gì?",
        "Theo mục 15 của đề cương học phần Phần mềm mã nguồn mở (IT1216), học phần được giảng dạy theo hình thức trực tiếp hay trực tuyến?",
        "Ai là người biên soạn và ai là người phản biện đề cương học phần Phần mềm mã nguồn mở (IT1216) ở cuối văn bản?",
        "Đề cương học phần Phần mềm mã nguồn mở (IT1216) được ban hành theo mẫu biểu BM-DT-04 kèm Quyết định số mấy của Hiệu trưởng?",
        "Khi sinh viên cần hỏi về đề cương học phần, số tín chỉ và kế hoạch đào tạo môn Phần mềm mã nguồn mở (IT1216) thì liên hệ phòng ban nào?",
    ]
    assert len(it1216_questions) == 44, f"IT1216 must have 44 questions, got {len(it1216_questions)}"
    for q_it in it1216_questions:
        records.append(
            {
                "group": "4_in_scope_regulation",
                "sub_type": f"{it1216_file}:syllabus",
                "question": q_it,
                "history": [],
                "expected_source": it1216_file,
                "expected_dept": it1216_dept,
                "expected_verified": True,
                "expected_is_refusal": False,
            }
        )

    assert len(records) == 350, f"Group 4 must have 350 items, got {len(records)}"
    return records


def build_full_1000_dataset() -> list[dict]:
    g1 = build_group1_nonsense_meta_chitchat()
    g2 = build_group2_chatgpt_oos()
    g3 = build_group3_multiturn()
    g4 = build_group4_in_scope()
    all_items = g1 + g2 + g3 + g4
    assert len(all_items) == 1000, f"Total dataset must be 1000 items, got {len(all_items)}"
    for idx, item in enumerate(all_items, 1):
        item["id"] = idx
    return all_items


def dept_matches(expected: str | None, actual_contact: dict | None) -> bool:
    if expected is None:
        return actual_contact is None
    if not actual_contact or not isinstance(actual_contact, dict):
        return False
    act_title = str(actual_contact.get("title", "")).strip()
    exp_norm = expected.strip()
    if exp_norm == act_title:
        return True
    if exp_norm == "Phòng Công tác Sinh viên (VLUTE)" and ("Đầu mối tiếp nhận" in act_title or "Tuyến phối hợp" in act_title):
        return False
    return exp_norm in act_title


def test_20_live_stream_queries(dataset: list[dict]) -> list[dict]:
    """Gửi trực tiếp 20 câu đại diện (5 câu mỗi nhóm) qua POST http://127.0.0.1:8000/api/chat/stream."""
    by_group = defaultdict(list)
    for item in dataset:
        by_group[item["group"]].append(item)

    in_scope_it1216 = [x for x in by_group["4_in_scope_regulation"] if "IT1216" in str(x.get("expected_source", ""))]
    samples = (
        by_group["1_nonsense_meta_chitchat"][:5]
        + by_group["2_chatgpt_oos"][:5]
        + by_group["3a_multiturn_valid"][:3]
        + by_group["3b_multiturn_trap"][:2]
        + by_group["4_in_scope_regulation"][:2]
        + in_scope_it1216[4:7]
    )
    assert len(samples) == 20

    live_results = []
    for item in samples:
        t0 = time.time()
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/chat/stream",
            data=json.dumps({
                "query": item["question"],
                "messages": item.get("history") or [],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        chunks = []
        meta_evt = {}
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                evt = json.loads(payload)
                if evt.get("type") == "chunk":
                    chunks.append(evt.get("content", ""))
                elif evt.get("type") == "meta":
                    meta_evt = evt
        wall_s = round(time.time() - t0, 2)
        ans = "".join(chunks).strip()
        act_verified = bool(meta_evt.get("verified"))
        act_refusal = bool(meta_evt.get("is_refusal"))
        act_contact = meta_evt.get("contact")
        passed = (act_verified == item["expected_verified"]) and (act_refusal == item["expected_is_refusal"])
        if item["expected_dept"]:
            passed = passed and dept_matches(item["expected_dept"], act_contact)
        else:
            passed = passed and (act_contact is None)
        live_results.append({
            "id": item["id"],
            "group": item["group"],
            "question": item["question"],
            "rewritten_query": meta_evt.get("rewritten_query"),
            "verified": act_verified,
            "is_refusal": act_refusal,
            "contact_title": act_contact.get("title") if isinstance(act_contact, dict) else None,
            "wall_s": wall_s,
            "has_pipe_table": "|---" in ans,
            "passed": passed,
            "answer_preview": ans.replace("\n", " ")[:140],
        })
    return live_results


def main():
    os.chdir(ROOT_DIR)
    dataset = build_full_1000_dataset()

    json_path = ROOT_DIR / "evaluation" / "benchmark_1000_adversarial.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    print(f"[1/4] Đã lưu bộ dữ liệu 1.000 câu hỏi tại: {json_path}")

    print("[2/4] Đang nạp Vector DB, BM25 Index và bộ điều phối RAG...")
    vector_db = get_vector_db()
    _ = get_bm25_index()
    chain = SmartRAGChain(vector_db=vector_db, llm=None, prompt=None)
    _ = chain.filter_documents("Điều kiện xét học bổng khuyến khích học tập?", k=6)

    print("[3/4] Đang chạy đo kiểm toàn diện 1.000 câu hỏi (Rewrite + Chitchat Gate + Dual Refusal Gate + Hybrid Retrieval + Dept Routing)...")
    rows = []
    group_stats = defaultdict(list)
    doc_stats = defaultdict(list)

    for item in dataset:
        qid = item["id"]
        grp = item["group"]
        q_raw = item["question"]
        hist = item.get("history") or []
        exp_src = item["expected_source"]
        exp_dept = item["expected_dept"]
        exp_verified = item["expected_verified"]
        exp_refusal = item["expected_is_refusal"]

        t0 = time.perf_counter()

        # Bước 1: Kiểm tra Chitchat / Greeting / Meta-command trước khi rewrite
        chitchat_reply = get_greeting_or_chitchat_reply(q_raw)
        chitchat_flag = chitchat_reply is not None

        # Bước 2: Rewrite conversational query nếu có history
        rewritten_q = rewrite_conversational_query(q_raw, hist) if hist else q_raw
        rewrite_unchanged = (rewritten_q.strip() == q_raw.strip())

        if chitchat_flag:
            docs = []
            act_verified = False
            act_refusal = True
            act_contact = None
            gate_reason = "chitchat_or_meta_command"
        else:
            dept_intercept = check_department_inquiry(rewritten_q)
            if dept_intercept:
                docs = []
                act_verified = False
                act_refusal = False
                act_contact = None
                gate_reason = "dept_inquiry_intercept"
            else:
                docs = chain.filter_documents(rewritten_q, k=6)
                dbg = dict(getattr(chain, "last_retrieval_debug", {}) or {})
                gate_reason = dbg.get("reason", "")
                if not docs:
                    act_verified = False
                    act_refusal = True
                    act_contact = None
                else:
                    act_verified = True
                    act_refusal = False
                    act_contact = get_contact_footer_data(rewritten_q, retrieved_docs=docs, is_refusal=False)

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        retrieved_sources = []
        for d in docs:
            s_base = os.path.basename(str(d.metadata.get("source", ""))).lower()
            if s_base and s_base not in retrieved_sources:
                retrieved_sources.append(s_base)
        top1_src = os.path.basename(str(docs[0].metadata.get("source", ""))).lower() if docs else ""

        source_hit = (exp_src.lower() in retrieved_sources) if exp_src else (len(docs) == 0)
        top1_hit = (top1_src == exp_src.lower()) if exp_src else (len(docs) == 0)
        dept_ok = dept_matches(exp_dept, act_contact)

        if grp == "1_nonsense_meta_chitchat":
            passed = (not act_verified) and act_refusal and (act_contact is None) and (len(docs) == 0)
        elif grp == "2_chatgpt_oos":
            passed = (not act_verified) and act_refusal and (act_contact is None) and (len(docs) == 0)
        elif grp == "3a_multiturn_valid":
            passed = (not rewrite_unchanged) and act_verified and (not act_refusal) and source_hit and dept_ok
        elif grp == "3b_multiturn_trap":
            passed = rewrite_unchanged and (not act_verified) and act_refusal and (act_contact is None) and (len(docs) == 0)
        else:  # 4_in_scope_regulation
            passed = act_verified and (not act_refusal) and source_hit and dept_ok

        row = {
            "id": qid,
            "group": grp,
            "sub_type": item["sub_type"],
            "question": q_raw,
            "has_history": bool(hist),
            "rewritten_query": rewritten_q,
            "rewrite_unchanged": rewrite_unchanged,
            "is_chitchat": chitchat_flag,
            "num_docs": len(docs),
            "expected_source": exp_src or "",
            "top1_source": top1_src,
            "retrieved_sources": ";".join(retrieved_sources),
            "source_hit": source_hit,
            "top1_hit": top1_hit,
            "expected_dept": exp_dept or "",
            "actual_contact": act_contact.get("title", "") if isinstance(act_contact, dict) else "",
            "dept_ok": dept_ok,
            "expected_verified": exp_verified,
            "actual_verified": act_verified,
            "expected_refusal": exp_refusal,
            "actual_refusal": act_refusal,
            "gate_reason": gate_reason,
            "latency_ms": latency_ms,
            "passed": passed,
        }
        rows.append(row)
        group_stats[grp].append(row)
        if exp_src:
            doc_stats[exp_src].append(row)

    csv_path = ROOT_DIR / "evaluation" / "benchmark_1000_results.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Đã lưu kết quả 1.000 câu hỏi tại: {csv_path}\n")

    print("=" * 105)
    print("BẢNG THỐNG KÊ KẾT QUẢ KIỂM THỬ 1.000 CÂU HỎI THEO NHÓM")
    print("=" * 105)
    for grp_name in (
        "1_nonsense_meta_chitchat",
        "2_chatgpt_oos",
        "3a_multiturn_valid",
        "3b_multiturn_trap",
        "4_in_scope_regulation",
    ):
        items = group_stats[grp_name]
        n = len(items)
        pass_cnt = sum(1 for r in items if r["passed"])
        fail_cnt = n - pass_cnt
        avg_ms = sum(r["latency_ms"] for r in items) / max(n, 1)
        print(
            f"- {grp_name:<26}: Total={n:4d} | Pass={pass_cnt:4d} ({pass_cnt/n*100:6.2f}%) | "
            f"Fail={fail_cnt:3d} ({fail_cnt/n*100:5.2f}%) | AvgLatency={avg_ms:6.2f}ms"
        )

    tot_n = len(rows)
    tot_pass = sum(1 for r in rows if r["passed"])
    tot_fail = tot_n - tot_pass
    tot_avg_ms = sum(r["latency_ms"] for r in rows) / tot_n
    print("-" * 105)
    print(
        f"- {'TỔNG HỢP 1.000 CÂU':<26}: Total={tot_n:4d} | Pass={tot_pass:4d} ({tot_pass/tot_n*100:6.2f}%) | "
        f"Fail={tot_fail:3d} ({tot_fail/tot_n*100:5.2f}%) | AvgLatency={tot_avg_ms:6.2f}ms"
    )
    print("=" * 105)

    print("\nTHỐNG KÊ CHI TIẾT THEO TỪNG TÀI LIỆU (NHÓM 3a + NHÓM 4 = 425 CÂU IN-SCOPE):")
    for doc_name, items in doc_stats.items():
        n = len(items)
        hit_cnt = sum(1 for r in items if r["source_hit"])
        top1_cnt = sum(1 for r in items if r["top1_hit"])
        dept_cnt = sum(1 for r in items if r["dept_ok"])
        pass_cnt = sum(1 for r in items if r["passed"])
        print(
            f"  * {doc_name:<50}: N={n:2d} | Hit@k={hit_cnt/n*100:6.2f}% | "
            f"Top1={top1_cnt/n*100:6.2f}% | DeptOK={dept_cnt/n*100:6.2f}% | Pass={pass_cnt/n*100:6.2f}%"
        )

    failures = [r for r in rows if not r["passed"]]
    print(f"\n[DANH SÁCH CÂU FAIL] ({len(failures)} câu):")
    for fl in failures[:30]:
        print(
            f"  - ID={fl['id']} ({fl['group']}) | Q='{fl['question']}' | rewritten='{fl['rewritten_query']}' | "
            f"docs={fl['num_docs']} | top1='{fl['top1_source']}' | verified={fl['actual_verified']} | "
            f"contact='{fl['actual_contact']}' | reason={fl['gate_reason']}"
        )

    print("\n[4/4] Đang kiểm thử trực tiếp 20 câu đại diện qua POST http://127.0.0.1:8000/api/chat/stream...")
    try:
        live_20 = test_20_live_stream_queries(dataset)
        live_pass = sum(1 for x in live_20 if x["passed"])
        print(f"KẾT QUẢ 20 CÂU LIVE STREAM TRÊN CỔNG 8000: Pass={live_pass}/20 ({live_pass/20*100:.1f}%)")
        for x in live_20:
            print(
                f"  - [ID {x['id']} | {x['group']}] Pass={x['passed']} | verified={x['verified']} | "
                f"refusal={x['is_refusal']} | contact={x['contact_title']} | pipe_table={x['has_pipe_table']} | "
                f"time={x['wall_s']}s | Q: {x['question']}"
            )
    except Exception as exc:
        print(f"⚠️ Không thể kết nối cổng 8000 để chạy 20 câu live stream: {exc}")


if __name__ == "__main__":
    main()
