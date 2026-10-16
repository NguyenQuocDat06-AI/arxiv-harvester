# Phân công Nhiệm vụ Cá nhân — Trần Nguyên Tân

* **MSSV:** `24120438`
* **Nhánh làm việc:** `feat/reference-extraction`
* **Khoảng ID được giao (Cột H – K):**
  * `start_month` (Cột H): `2024-07` (`2407`)
  * `start_id` (Cột I): `12839`
  * `end_month` (Cột J): `2024-07` (`2407`)
  * `end_id` (Cột K): `17838`
  * **Phạm vi mã bài báo:** Từ `2407.12839` đến `2407.17838` (5.000 bài báo trong tháng 07/2024).

## 1. Các tệp cần hiện thực trên nhánh này
1. `src/crawler/reference_scraper.py`:
   * Truy vấn Semantic Scholar Graph API (`ARXIV:{arxiv_id}`) lấy danh sách trích dẫn (`externalIds`, `title`, `authors`, `year`, `venue`).
   * Quản lý giới hạn tốc độ 100 requests / 5 phút và tự động thử lại (Exponential Backoff) khi gặp lỗi `429`.
   * Bổ sung hàm đọc dự phòng tệp `.bib` / `.bbl` bằng Regex nếu API trả về `404`.
2. `docs/03_reference_extraction.ipynb`:
   * Thống kê tỷ lệ cào trích dẫn thành công, số lượng trích dẫn trung bình trên mỗi bài báo và phân bố năm xuất bản.

## 2. Lệnh chạy thu thập dữ liệu cho khoảng ID cá nhân
```bash
python -m src.crawler.main \
    --member-id 24120438 \
    --start-month 2024-07 \
    --start-id 12839 \
    --end-month 2024-07 \
    --end-id 17838 \
    --output-dir data/shards/24120438
```

## 3. Input, output và các bước cần bổ sung

- Input: `arxiv_id: str`, `unzipped_paper_dir: str | None = None`, `rate_limit_sec: float = 3.1`. Dùng đúng tên tham số trong `src/crawler/reference_scraper.py`.
- Output: `list[dict]` chứa từng tài liệu tham khảo, gắn ID bài nguồn và các thông tin có được: ID arXiv, DOI, tiêu đề, tác giả, năm, venue, `raw_citation`; thống nhất tên trường/kiểu/null với Trí trước khi ghi `references.parquet`.
- TODO: lấy đủ `externalIds`, `title`, `authors`, `year`, `venue`; kiểm tra phân trang để tránh mất references. Chuẩn hóa ID arXiv không kèm URL/phiên bản và DOI không kèm tiền tố URL.
- TODO: xác minh hạn mức API đang áp dụng trước khi chạy thật; cấu hình thời gian chờ, đọc `Retry-After`, backoff có giới hạn cho 429/503 và phân biệt lỗi mạng với danh sách trích dẫn rỗng.
- TODO: khi API trả 404, đọc `.bib/.bbl` nếu thư mục nguồn tồn tại, giữ `raw_citation` khi không bóc đủ trường. Không tạo dữ liệu bịa cho tài liệu chưa nhận diện được.
- TODO: thống nhất cách báo nguồn API/fallback/lỗi cho CLI; không ghi nhiều bản sao của cùng một cạnh trích dẫn.
- TODO: notebook trình bày độ phủ, tỷ lệ fallback, số trích dẫn mỗi bài và phân bố năm, kèm số bản ghi thiếu năm.

## 4. Hoàn thành và tích hợp

Các lệnh trên là giao diện dự kiến sau khi thành viên tự hiện thực. Khung hiện tại chỉ có chữ ký hàm, docstring và `NotImplementedError`; kể cả bộ nhận tham số CLI cũng là TODO.

Trong trường hợp chữ ký ví dụ ở README khác với source, thống nhất theo source trong nhánh `main` và trao đổi với người tích hợp trước khi thay đổi giao diện.

- Tự viết logic của module được giao; không sửa module của thành viên khác nếu chưa thống nhất.
- Kiểm tra một tập ID nhỏ và trường hợp lỗi trước khi chạy toàn khoảng; ghi lại số liệu thật, không điền kết quả giả vào báo cáo.
- Chỉ commit code, notebook và tài liệu nhiệm vụ. Dữ liệu thô, Parquet trong shards và các tài liệu đầu vào cục bộ đã được bỏ qua bởi Git.
- Mở pull request về `main` khi hoàn tất, mô tả cách kiểm tra và những giới hạn còn lại.
