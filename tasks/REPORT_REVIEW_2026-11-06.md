# Chỉnh báo cáo sau khi tham khảo các nhóm — 06/11/2026

## Nguồn đã đọc

Đọc lại [yêu cầu chung](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/), [M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/) và [M2](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/). Báo cáo cần giải thích triển khai, phân tích kết quả, số đo tài nguyên và sinh bảng/biểu đồ khi biên dịch. Code và Book ở hai repository riêng; source giữ lịch sử tích lũy.

| Nguồn công khai và bản đã đọc | Nội dung kiểm tra | Áp dụng cho báo cáo nhóm |
|---|---|---|
| [Nhóm 1 — arxiv-book](https://github.com/hcmus-arxiv-nhom1/arxiv-book/tree/1542331e3d7b8a7e5e0ad5f4ee9a082ed82a5208) | Có overview, methodology, data statistics, performance, discussion và các lần thử. Tách input biểu đồ khỏi crawler. Một số CSV được ghi rõ là placeholder; M2 tại bản này còn là trang khung. | Bổ sung overview cho từng milestone, phần thảo luận và thông tin phạm vi phép đo. |
| [ahtuan171 — book](https://github.com/ahtuan171/arXiv-Project/tree/dd076d4dbc86d7b8abad54cf9b9bd8abeab80f0e/book) | Hai notebook theo thứ tự M1/M2 và trang giới thiệu thành viên; nội dung notebook chủ yếu là khung. | Giữ hai phần milestone rõ ràng và thêm thông tin thành viên ở trang đầu. |
| [tuandatedu — report_m2.ipynb](https://github.com/tuandatedu/arXir_project/blob/f2715ba852dd5992bbca3bf945ddfc4cad43fc8a/src/m2_parsing/report_m2.ipynb) | Notebook đọc metrics riêng, mô tả gathering/hierarchy, standardization và dedup; có phân biệt thời gian lượt resume. | Dùng overview M2 để nối phương pháp, coverage, số dòng và hạn chế thực nghiệm. |
| [thinhelzan842 — milestone1](https://github.com/thinhelzan842/intro-ds-arxiv-project/tree/cb5a2905290acb11febb15a1f00851a77106212f/docs/milestone1) | Notebook có bảng chỉ tiêu, size trước/sau, phân bố version, RSS và disk. | Gom kết quả chính thành bảng có mẫu số; thêm diễn biến tài nguyên khi có mẫu thật. |

Trang Pages của Nhóm 1 và ahtuan171 đều trả HTTP 200 tại thời điểm kiểm tra. Các repository còn lại cung cấp nguồn notebook/tài liệu công khai. Tình trạng bản tham khảo không được dùng để kết luận kết quả chấm điểm hoặc mức hoàn thành của nhóm khác.

## Những chỗ được sửa

| File | Thay đổi | Lý do |
|---|---|---|
| `tools/submission_report_presentation.py` | Trang đầu có thành viên, đường dẫn source `main`, lộ trình đọc; thêm overview M1/M2, thảo luận/kết luận và tài liệu tham khảo; code phân tích có nút mở; CSS cho bảng và bài viết. | Giúp người đọc thấy mục tiêu, kết quả và giới hạn trước khi đi vào các chương chi tiết. |
| `tools/submission_report_content.py` | Gọi lớp trình bày mới sau khi sinh các chương. | Dựng lại bằng generator sẽ giữ được các chỉnh sửa, thay vì chỉ sửa bản trong `build/`. |
| `tools/build_public_submission_book.py` | Tổng hợp mẫu RSS/disk của parser thành cửa sổ 5 giây, chỉ xuất giá trị số. | Có biểu đồ tài nguyên thật mà không công bố log gốc, đường dẫn hay định danh dữ liệu. |
| Source Book: `index.md`, `_toc.yml`, `_config.yml`, `chapters/`, `_static/report.css` | Áp dụng nội dung mới, giữ URL các chương đã có; bảng/biểu đồ mới sinh qua notebook. | Cập nhật Book nộp ở cùng repository và cùng URL. |

## Phạm vi số liệu

Giữ snapshot 73 paper/119 version và các số đo đã lưu. M1 là lượt Colab tạm dừng, xử lý 14 paper; M2 là lượt Windows CPU trên 73 paper. Biểu đồ mới dùng 384 mẫu RSS và 30 mẫu disk của chính lượt parser đã có, tổng hợp thành 29 cửa sổ. Các peak sau tổng hợp khớp `stats.json`. Thống kê references, parser và dedup lấy từ dữ liệu nhóm.

## Tiến trình kiểm tra

- [x] Đọc đề và nguồn báo cáo của bốn nhóm; lưu bản tham khảo cục bộ trong `build/report_reference_20261106/`.
- [x] Viết template, sửa generator và bổ sung bảng có mẫu số.
- [x] Kiểm tra cú pháp và đối chiếu số mẫu/peak của profile tài nguyên.
- [x] Dựng Book với notebook thực thi, warnings được coi là lỗi.
- [x] Đối chiếu toàn bộ số liệu cũ; chỉ thêm profile số mới từ cùng run.
- [x] Kiểm tra 15 trang HTML, 44 code cell thực thi và 15 hình; không thiếu liên kết/tệp nội bộ. Đã xem trực tiếp hình overview M1 và profile RAM/disk.
- [x] Commit/push source trên `main`, đồng bộ `develop`, giữ lịch sử thành viên.
- [x] Push source Book tại `8d218e9` vào repository báo cáo hiện có.
- [x] Kiểm tra workflow Pages và các trang công khai trên URL nộp cố định.

## Kết quả xuất bản

- Book commit: `8d218e9a0759958aed1f22b3835a093956e6477e`.
- [Workflow build và deploy](https://github.com/NguyenQuocDat06-AI/arxiv-harvester-book/actions/runs/42217533196): thành công, gồm thực thi notebook trên Ubuntu/Python 3.12 bằng `jupyter-book build . --all -W`.
- Kiểm tra public: 15 trang, 15 hình và `_static/report.css` trả HTTP 200; trang đầu hiển thị nội dung mới. Tệp kết quả ở `build/submission_20261106/public_verification.json`.
- Source Book gồm 24 file, không lưu output notebook; dữ liệu nguồn và log gốc không được đưa lên GitHub.
- Source crawler/parser không thay đổi trong đợt chỉnh trình bày này. Hai repository và URL nộp được giữ nguyên.

URL giữ xuyên suốt: https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/.

File kiểm tra, bản tải tham khảo, corpus và log giữ local; không đưa `tests/` vào commit.
