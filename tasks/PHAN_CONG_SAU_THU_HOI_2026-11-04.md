# Phân công sau khi thu hồi

Nhánh `develop` từng được đưa về `2adf1b3`. Source được giữ trong workspace và nhánh sao lưu cục bộ `backup/develop-before-withdrawal-20261104` để tích hợp lại.

Các đầu việc dưới đây dành cho từng người kiểm tra, thực hiện và xác nhận bằng kết quả của mình. Phân công không thay thế việc đóng góp thực tế.

| Thành viên | Phần phụ trách | Việc cần làm và kiểm tra |
|---|---|---|
| Đạt | Discovery và lịch sử version: `src/crawler/discovery.py`, `version_history.py`, `request_policy.py`, `rate_limiter.py` | Kiểm tra khoảng ID, metadata, ngày revision và các trường hợp chưa xác minh; chạy test discovery và request policy. |
| Tuấn | Tải và kiểm tra source: `src/crawler/source_downloader.py`, `retry_sources.py`, `validate_sources.py`, `drive_backup.py` | Kiểm tra tải từng version, resume, backup và trạng thái PDF-only; chạy test source và backup. |
| Tân | References: `src/crawler/reference_scraper.py`, `reference_batch.py`, `enrich_references.py` | Kiểm tra S2, cooldown, references thiếu và provenance; chạy test references. |
| Trí | Parser và dữ liệu: `src/parser/`, `src/crawler/records.py`, `merge_shards.py` | Đối chiếu TeX/BibTeX, hierarchy, dedup và các bảng; chạy test parser và schema. |
| Triết | Runner và báo cáo: `colab_crawler.ipynb`, `src/crawler/main.py`, `profiler.py`, `readiness.py`, `reporting.py`, `tools/build_report.py` | Kiểm tra smoke/full, checkpoint, benchmark và Book; chạy test notebook và profiler. |

## Chia nhỏ công việc

Mỗi người có hai đầu việc để tự kiểm tra và hoàn thiện. File trong workspace là bản tham khảo đã có, không mặc định là phần người được phân công đã viết.

| Thành viên | Đầu việc 1 | Đầu việc 2 |
|---|---|---|
| Đạt | Đối chiếu discovery và version với mẫu, kiểm tra ID chưa xác minh. | Kiểm tra rate limit và lịch sử revision; ghi kết quả test. |
| Tuấn | Kiểm tra tải, resume và phân loại source theo version. | Kiểm tra backup/restore và chạy audit các version lỗi. |
| Tân | Kiểm tra batch references và xử lý S2 429. | Đối chiếu references với BibTeX, thống kê trường còn thiếu. |
| Trí | Đối chiếu parser TeX/BibTeX và hierarchy với source mẫu. | Kiểm tra dedup, merge và khóa của các bảng kết quả. |
| Triết | Kiểm tra notebook, checkpoint và chạy smoke. | Kiểm tra profiler, tổng hợp số đo và dựng Book. |

Mỗi người lưu bằng chứng kiểm thử, commit phần mình thực hiện và mở PR. Số commit tùy phần việc; không chia nhỏ thay đổi chỉ để làm đều thống kê.

## Tích hợp

1. Thống nhất interface và thứ tự tích hợp vì runner phụ thuộc các module khác; test lại sau mỗi lần gộp.
2. Mỗi người tạo nhánh từ `develop`, làm việc trên phần của mình và mở PR để thành viên khác review.
3. Phối hợp kiểm tra các file chung như `README.md`, cấu hình và test tích hợp; chỉ ghi người thực hiện thực tế.
4. Chạy smoke trên Colab CPU trước full, lưu log và validation, sau đó xử lý source và references còn thiếu.

Notebook mặc định lấy source từ GitHub. Kiểm tra commit và chạy smoke trước khi dùng để crawl full; có thể dùng gói bundle đi kèm sau khi xác minh hash.
