# Chuẩn bị nộp Milestone 1 và 2 — 06/11/2026

Phạm vi được yêu cầu: dùng tạm dữ liệu Drive đã có, không cần thu thập hết trước khi chuẩn bị bản nộp. Báo cáo phải ghi rõ tập đã xử lý, phần thiếu và môi trường đo thật.

- [x] Đọc lại đề M1/M2 và kiểm tra source hiện tại tại `92b4b47`.
- [x] Đọc thư mục Drive; backup mới nhất ghi 2.217 ID đã xử lý. Đây là counter checkpoint, chưa phải số nguồn độc lập được xác minh.
- [x] Tải 17 file từ Drive: HEAD, tám manifest và tám archive (khoảng 12 MB); kiểm tra hash archive/state và checksum tệp trong từng lô.
- [x] Tạo snapshot 73 paper/119 version; audit xác minh 118 version (113 TeX, 5 empty), còn một version nguồn lỗi. Course export có 73 paper/200 cạnh arXiv, cấu trúc hợp lệ.
- [x] Chạy parser và validation: 81 success, 31 partial, 5 empty, 1 root mơ hồ, 1 thiếu nguồn. Năm bảng hợp lệ; chưa đạt processing_complete.
- [x] Hoàn thiện báo cáo tám chương, bảng/biểu đồ được sinh khi build và ghi rõ giới hạn benchmark.
- [x] Dựng Book và xuất bản trên repository báo cáo riêng. Workflow Pages đạt; HTTP không đăng nhập cho trang mở đầu, tám chương và bảy hình đều 200.
- [x] Ghi link và hướng dẫn thao tác nộp Moodle trong `tasks/NOP_M1_M2_2026-11-06.md`; chưa thao tác nút nộp trong Moodle.

Không thay dữ liệu gốc trên Drive. File test giữ local theo yêu cầu trước đó.

## Các sửa đổi

- `tools/prepare_submission_snapshot.py`: dựng snapshot một phần từ các archive đã xác minh, giữ provenance và trạng thái references chưa đủ.
- `src/parser/gather.py`: tìm include từ thư mục compilation trước khi dùng đường dẫn của file con. Mẫu `2412.18966`, `2412.20258` có file thật ở root nhưng trước đây bị báo thiếu.
- `configs/submission_parser_roots_20261106.json`: chọn root cho bốn paper sau khi đối chiếu title và file; giữ `2412.20337v1` lỗi vì hai root cùng title chưa có bằng chứng để chọn.
- `src/crawler/reporting.py`: đọc audit và phạm vi các run, ghép wall time từ run metadata chỉ khi trùng run ID.
- `tools/build_public_submission_book.py`: chuẩn bị repository Book độc lập chỉ dùng thống kê tổng hợp và nhãn coverage, nêu rõ snapshot chưa đủ corpus và M2 chưa có benchmark Colab. Bản có working inputs chi tiết chỉ giữ local dưới `build/`.
- `tools/prepare_parser_colab.py`, `colab_parser_submission.ipynb`: đóng gói input đã chốt và notebook đo lại M2 trên Colab CPU, không cần gọi arXiv/S2.

25 kiểm tra parser/gathering local đạt. Parser mới thực sự chạy trên Windows CPU trong 143,052 giây cho 73 paper; không trình bày thành số đo Colab. Lượt Colab gốc `20261104T115511Z-d7e4bba4` được giữ riêng: 261,958 giây profiler, 263,652 giây child wall, trạng thái paused_rate_limit.

Lần push bản chứa Parquet và metadata Drive bị automatic approval review từ chối. Đã giữ bản đó local và dựng repository sạch khác: chỉ 17 file source/thống kê tổng hợp, không có ID/text paper, Parquet, manifest hoặc log Drive. Bản công khai đã được push tới repository `NguyenQuocDat06-AI/arxiv-harvester-book`; Pages đã deploy thành công.

Link Book: https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/

Link code: https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/develop

## Mở rộng báo cáo chi tiết

- `tools/submission_report_content.py`: viết lại tám chương với phương pháp, công thức/mẫu số, diễn giải kết quả và ví dụ TeX/BibTeX tổng hợp chạy từ source ghim.
- Thêm hai phụ lục về tái lập, URL cố định, đối chiếu yêu cầu và phần dữ liệu/benchmark còn thiếu.
- `tools/build_public_submission_book.py`: bổ sung số paper đủ nguồn, số paper đủ nguồn + S2, ngày version còn thiếu và so sánh trạng thái trước/sau sửa trên cùng input. Chỉ bổ sung số liệu tổng hợp, không công bố dữ liệu gốc.
- Bản mở rộng có khoảng 5.320 từ Markdown và 33 code cell; số lượng paper/version và kết quả đo gốc không bị thay đổi.
