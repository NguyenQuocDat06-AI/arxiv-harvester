# Tiến trình sửa M1 và M2 — 04/11/2026

Phạm vi: sửa và kiểm thử trong workspace; không thay dữ liệu Drive hoặc lượt Colab đang chạy. Kết quả mẫu không thay thế dữ liệu đầy đủ và benchmark Colab CPU-only.

- [x] Sửa parser TeX và BibTeX; test đơn vị và test pipeline parser: 26 passed. Mẫu 10 bài/20 version chuyển từ 11 success, 5 partial, 4 error sang 16 success, 4 partial, 0 error; validation cấu trúc đạt.
- [x] Rà soát và sửa các trường hợp discovery, retry và checkpoint đã ghi bên dưới.
- [x] Rà soát cấu hình Colab và ghi rõ phạm vi đo benchmark.
- [x] Chạy kiểm thử cuối, ghi kết quả và phần công việc còn cần dữ liệu thật.

## Thay đổi đã thực hiện

| File | Thay đổi và lý do |
|---|---|
| `src/parser/hierarchy.py` | Chỉ tách đoạn tại dòng trống ngoài nhóm/lệnh TeX, literal và toán; tính lại vị trí đoạn theo văn bản gốc. Tránh lỗi nhóm chưa đóng và sai offset. |
| `src/parser/bibliography.py` | Xử lý comment theo ngữ cảnh BibTeX, giữ `%` trong giá trị đặt trong ngoặc hoặc chuỗi; tránh cắt URL được mã hóa. |
| `tests/test_parser_regressions.py` | Kiểm tra cây đoạn/câu, offset, URL `%2F`, comment, dấu escape và giá trị lồng nhau. |
| `src/crawler/discovery.py`, `src/crawler/records.py`, `src/crawler/main.py` | Không tự suy v1 hoặc ngày revision; ID vắng trong feed được giữ để xác minh lại. Metadata thiếu versions được đưa trở lại discovery. `--recheck-missing` kiểm lại trạng thái missing cũ; notebook bật cho full. |
| `src/crawler/main.py` | Hoãn bài đã đủ source nhưng còn lỗi S2 khi cooldown đang hiệu lực, giữ trạng thái retry và hạn chế ghi checkpoint lặp. Không bỏ qua bài còn thiếu source. |
| `src/crawler/profiler.py` | Lấy mẫu RAM theo chu kỳ cũ, quét đĩa định kỳ 5 giây và tại checkpoint thao tác. Ghi rõ chu kỳ để hiểu giới hạn số đo đỉnh. |
| `colab_crawler.ipynb`, `src/crawler/main.py`, `src/crawler/source_downloader.py`, `src/crawler/retry_sources.py` | Tách batch xử lý/metadata 25 ID khỏi batch S2 5 ID; giữ checkpoint mỗi bài. Đổi mặc định source sang 3 giây theo đề, vẫn cho phép cấu hình 1 giây kèm cảnh báo. Lượt đang chạy không bị thay đổi. |
| `src/crawler/main.py`, `src/crawler/reporting.py` | Ghi rõ phạm vi thời gian profiler và phạm vi đĩa; đổi tên trung bình theo thời gian profiler để không gọi nhầm là end-to-end. Backup output cuối và validation notebook không thuộc thời gian này. |
| `tests/test_discovery_evidence.py`, `tests/test_crawler_batch_pipeline.py`, `tests/test_cli_and_profiling.py`, `tests/test_colab_workflow.py`, `tests/test_source_retry_execution.py` | Kiểm tra metadata chưa đủ bằng chứng, hoãn S2, resume sau cooldown, kiểm tra lại missing cũ, tần suất đo và cấu hình notebook. |

Kết quả mẫu mới ở `build/parser_fixes_20261104/`. Bốn version partial gồm include động của `2412.19116v1`, thiếu `biblio.bib` của `2412.19119v1` và thiếu `bib.bib` của `2412.19121v2/v3`; cần xử lý hoặc giải thích theo source thực tế, không gọi là hoàn thành.

Lưu ý: lượt full mới mặc định yêu cầu kiểm tra lại các ID `confirmed_missing` của checkpoint cũ. ID vẫn không có trong feed được ghi là cần xác minh, không tự kết luận không tồn tại. Tốc độ mới cần đo bằng lượt chạy mới; không sửa log của lượt cũ.

## Kết quả và cách dùng bản mới

- `build/parser_fixes_20261104/project_validation.json`: cấu trúc hợp lệ, nhưng chỉ ghi nhận 20/36.089 version của snapshot metadata; có 4 version partial. Đây không phải báo cáo hoàn thành toàn corpus.
- Toàn bộ test local: **271 passed**, một warning về phiên bản dependency `requests`/`urllib3`/charset trên máy Windows; chưa kiểm tra được môi trường Colab từ lượt test này.
- `build/book_fixes_20261104/_build/html/index.html`: bản Book offline build thành công với tám chương và `--all -W`, dùng snapshot metadata 01/11 và parser mẫu nói trên; source hash khớp workspace. Đây không phải link GitHub Pages.
- `build/colab_fixes_20261104/arxiv_colab_runtime.zip`: gói 39 file source/config, SHA-256 `d5b0f0356f13f155c37aba654df8165cb21e2e9405f4173b1743fe184d14270a`; hash cũng được cập nhật vào notebook. Gói và notebook phải dùng cùng nhau.
- Sau khi lượt Colab hiện tại dừng an toàn: mở notebook mới, chọn thành viên, chạy `smoke` và validation; sau đó chạy `full`/resume với checkpoint đúng thành viên. Notebook mặc định lấy source từ nhánh `develop`; nếu dùng `bundle`, cần tải lên ZIP có hash tương ứng. Chỉ một runtime được ghi vào cùng backup/checkpoint.
- M1 và M2 vẫn cần corpus thật đủ dải, kiểm tra source/ID/reference, chạy parser toàn phạm vi, xử lý hoặc giải trình partial và chạy benchmark Colab CPU-only. Đăng Jupyter Book lên Pages và nộp link vẫn là bước riêng.

Các đường dẫn trong `build/` là sản phẩm trên máy, không được đưa vào Git. Phân công tiếp theo ở `tasks/PHAN_CONG_2026-11-04.md`.

## Gỡ test khỏi Git

- Gỡ 21 file trong `tests/` khỏi Git và thêm `/tests/` vào `.gitignore`; các file local được giữ nguyên.
- `.github/workflows/ci.yml` kiểm tra cú pháp, notebook, cài đặt và CLI thay vì chạy pytest. `README.md` và `pyproject.toml` được cập nhật theo cấu hình này.
- `tools/prepare_handoff.py` không còn yêu cầu hoặc đóng gói file trong `tests/`. Các test từng được ghi trong lịch sử Git trước đó vẫn thuộc lịch sử cũ.
