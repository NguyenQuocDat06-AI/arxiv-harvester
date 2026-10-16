# Phân công Nhiệm vụ Cá nhân — Dương Phan Minh Trí

* **MSSV:** `24120470`
* **Nhánh làm việc:** `feat/data-storage`
* **Khoảng ID được giao (Cột H – K):**
  * `start_month` (Cột H): `2024-06` (`2406`)
  * `start_id` (Cột I): `17938`
  * `end_month` (Cột J): `2024-07` (`2407`)
  * `end_id` (Cột K): `2838`
  * **Phạm vi mã bài báo:** Từ `2406.17938` đến hết tháng `06/2024`, nối tiếp từ `2407.00001` đến `2407.02838`.

## 1. Các tệp cần hiện thực trên nhánh này
1. `src/crawler/storage.py`:
   * Khai báo schema `pyarrow` cho 2 bảng `publications.parquet` và `references.parquet`, chuẩn hóa các trường `list`/`struct`/`timestamp` và lưu nén `snappy`.
2. `src/crawler/generate_mock_data.py`:
   * Tạo dữ liệu mẫu cho 5 phân vùng để nhóm kiểm thử biểu đồ báo cáo trước khi cào xong dữ liệu thật.
3. `src/crawler/merge_shards.py`:
   * Gộp dữ liệu từ 5 thư mục `data/shards/<MSSV>/` thành tệp `data/processed/publications.parquet`, `references.parquet` và `overall_stats.json`.
4. `docs/04_schema_and_data_quality.ipynb`:
   * Kiểm chứng schema dữ liệu, thống kê tỷ lệ khuyết thiếu và tổng hợp số lượng bản ghi từ 5 thành viên.

## 2. Lệnh chạy thu thập dữ liệu cho khoảng ID cá nhân
```bash
python -m src.crawler.main \
    --member-id 24120470 \
    --start-month 2024-06 \
    --start-id 17938 \
    --end-month 2024-07 \
    --end-id 2838 \
    --output-dir data/shards/24120470
```

## 3. Input, output và các bước cần bổ sung

- `save_publications_parquet(records: list[dict], output_path: str) -> None` và `save_references_parquet(records: list[dict], output_path: str) -> None`: nhận bản ghi chuẩn hóa, kiểm tra schema và ghi nén snappy. Chốt tên/kiểu/nullability của từng cột từ đặc tả chính thức; không suy đoán schema từ lô đầu tiên.
- TODO: hỗ trợ `list`, `struct`, `timestamp`, null hợp lệ và bảng rỗng; phản hồi lỗi schema đủ rõ để các module sửa bản ghi.
- `generate_mock_data.main() -> None`: sinh bộ mẫu nhỏ vào năm thư mục `data/shards/<MSSV>/` gồm `publications.parquet`, `references.parquet`, `stats.json`. Gắn nhãn dữ liệu mẫu, seed cố định, có ca thiếu trường/versions rỗng/trùng ID và tránh ghi đè dữ liệu thật.
- `merge_all_shards(shards_dir: str, output_dir: str) -> None`: input là các thư mục con trong `data/shards/`; output tại `data/processed/` gồm `publications.parquet`, `references.parquet`, `overall_stats.json`.
- TODO: khử trùng publications theo `id`, sắp xếp ổn định; thống nhất khóa references theo bài nguồn và tài liệu được trích, tránh gộp mọi references của một bài thành một hàng.
- TODO: kiểm tra shard thiếu/hỏng/khác schema, tách dữ liệu mẫu, ghi tệp an toàn và báo số bản ghi trước/sau gộp. Với RAM cực đại dùng max; RAM trung bình cần trọng số theo thời gian/số mẫu, không cộng các giá trị trung bình.
- TODO: notebook kiểm tra chất lượng, null, trùng lặp, kiểu dữ liệu, liên kết hai bảng và số bản ghi theo thành viên.

Lệnh gộp sau khi tự hiện thực CLI:

```bash
python -m src.crawler.merge_shards --shards-dir data/shards --output-dir data/processed
```

Lệnh sinh mẫu sau khi tự hiện thực:

```bash
python -m src.crawler.generate_mock_data
```

## 4. Hoàn thành và tích hợp

Các lệnh trên là giao diện dự kiến sau khi thành viên tự hiện thực. Khung hiện tại chỉ có chữ ký hàm, docstring và `NotImplementedError`; kể cả bộ nhận tham số CLI cũng là TODO.

Trong trường hợp chữ ký ví dụ ở README khác với source, thống nhất theo source trong nhánh `main` và trao đổi với người tích hợp trước khi thay đổi giao diện.

- Tự viết logic của module được giao; không sửa module của thành viên khác nếu chưa thống nhất.
- Kiểm tra một tập ID nhỏ và trường hợp lỗi trước khi chạy toàn khoảng; ghi lại số liệu thật, không điền kết quả giả vào báo cáo.
- Chỉ commit code, notebook và tài liệu nhiệm vụ. Dữ liệu thô, Parquet trong shards và các tài liệu đầu vào cục bộ đã được bỏ qua bởi Git.
- Mở pull request về `main` khi hoàn tất, mô tả cách kiểm tra và những giới hạn còn lại.
