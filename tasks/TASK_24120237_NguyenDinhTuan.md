# Phân công Nhiệm vụ Cá nhân — Nguyễn Đình Tuấn

* **MSSV:** `24120237`
* **Nhánh làm việc:** `feat/source-downloader`
* **Khoảng ID được giao (Cột H – K):**
  * `start_month` (Cột H): `2025-02` (`2502`)
  * `start_id` (Cột I): `3235`
  * `end_month` (Cột J): `2025-02` (`2502`)
  * `end_id` (Cột K): `8234`
  * **Phạm vi mã bài báo:** Từ `2502.03235` đến `2502.08234` (5.000 bài báo trong tháng 02/2025).

## 1. Các tệp cần hiện thực trên nhánh này
1. `src/crawler/source_downloader.py`:
   * Tải tệp nguồn từ `https://export.arxiv.org/e-print/{arxiv_id}` với `stream=True` và nghỉ `3.0 giây` giữa mỗi lần tải.
   * Giải nén gói `.tar.gz` / `.gz` vào `data/raw/unzipped/{arxiv_id}/` (bỏ qua nếu bài báo chỉ có file PDF).
   * Đo dung lượng thư mục giải nén trước khi xóa ảnh (`size_before_bytes`), xóa toàn bộ các tệp ảnh (`.png`, `.jpg`, `.pdf`, `.eps`, `.svg`,...), và đo lại dung lượng sau khi xóa (`size_after_bytes`).
2. `docs/02_source_download_and_cleaning.ipynb`:
   * Phân tích tỷ lệ tải mã nguồn thành công và vẽ biểu đồ so sánh dung lượng trung bình trước/sau khi xóa hình ảnh.

## 2. Lệnh chạy thu thập dữ liệu cho khoảng ID cá nhân
```bash
python -m src.crawler.main \
    --member-id 24120237 \
    --start-month 2025-02 \
    --start-id 3235 \
    --end-month 2025-02 \
    --end-id 8234 \
    --output-dir data/shards/24120237
```

## 3. Input, output và các bước cần bổ sung

- Input: `arxiv_id: str`, `sources_dir: str`, `unzipped_dir: str`, `rate_limit_sec: float = 3.0`, `remove_archive: bool = True`. Dùng chữ ký trong `src/crawler/source_downloader.py` để tích hợp.
- Thư mục tạm: `data/raw/sources/`; mỗi bài giải nén riêng tại `data/raw/unzipped/{arxiv_id}/`.
- Output: `dict` gồm `arxiv_id: str`, `status: str`, `size_before_bytes: int`, `size_after_bytes: int`, `elapsed_sec: float`. Thống nhất các trạng thái thành công, PDF-only, không tìm thấy và lỗi với CLI.
- `get_dir_size_bytes(path: str) -> int` trả tổng byte; `prune_images_and_binaries(path: str) -> None` chỉ thao tác trong thư mục bài báo.
- TODO: tải từng chunk 64 KB, timeout/retry có giới hạn; xóa tệp tải dở khi thất bại, không coi nội dung lỗi HTTP là archive.
- TODO: kiểm tra đường dẫn giải nén, từ chối đường dẫn tuyệt đối, `..`, symlink/hardlink thoát thư mục và archive quá lớn; phân biệt tar.gz, gzip đơn và PDF-only.
- TODO: giữ `.tex/.bib/.bbl/.sty/.cls/.bst/.txt`, thống nhất cách xử lý tệp văn bản mở rộng khác; loại ảnh/nhị phân và đo dung lượng trước/sau. Với ca không có LaTeX, ghi trạng thái riêng thay vì báo làm sạch thành công.
- TODO: chỉ xóa archive theo `remove_archive`, kiểm tra `size_after_bytes <= size_before_bytes`; notebook báo cáo tỷ lệ thành công và tỷ lệ giảm dung lượng với đơn vị rõ ràng.

## 4. Hoàn thành và tích hợp

Các lệnh trên là giao diện dự kiến sau khi thành viên tự hiện thực. Khung hiện tại chỉ có chữ ký hàm, docstring và `NotImplementedError`; kể cả bộ nhận tham số CLI cũng là TODO.

Trong trường hợp chữ ký ví dụ ở README khác với source, thống nhất theo source trong nhánh `main` và trao đổi với người tích hợp trước khi thay đổi giao diện.

- Tự viết logic của module được giao; không sửa module của thành viên khác nếu chưa thống nhất.
- Kiểm tra một tập ID nhỏ và trường hợp lỗi trước khi chạy toàn khoảng; ghi lại số liệu thật, không điền kết quả giả vào báo cáo.
- Chỉ commit code, notebook và tài liệu nhiệm vụ. Dữ liệu thô, Parquet trong shards và các tài liệu đầu vào cục bộ đã được bỏ qua bởi Git.
- Mở pull request về `main` khi hoàn tất, mô tả cách kiểm tra và những giới hạn còn lại.
