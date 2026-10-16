# Phân công Nhiệm vụ Cá nhân — Trịnh Vỹ Triết

* **MSSV:** `24120474`
* **Nhánh làm việc:** `feat/cli-and-profiling`
* **Khoảng ID được giao (Cột H – K):**
  * `start_month` (Cột H): `2024-06` (`2406`)
  * `start_id` (Cột I): `12938`
  * `end_month` (Cột J): `2024-06` (`2406`)
  * `end_id` (Cột K): `17937`
  * **Phạm vi mã bài báo:** Từ `2406.12938` đến `2406.17937` (5.000 bài báo trong tháng 06/2024).

## 1. Các tệp cần hiện thực trên nhánh này
1. `src/crawler/profiler.py`:
   * Hiện thực class `ResourceProfiler` dùng `psutil` đo Peak RAM, Average RAM, thời gian chạy từng pha (`time.perf_counter`) và dung lượng ổ cứng (`du`), xuất kết quả ra `stats.json`.
2. `src/crawler/main.py`:
   * Hoàn thiện giao diện CLI kết nối các hàm của 4 thành viên còn lại thành luồng chạy hoàn chỉnh và hỗ trợ cờ `--resume`.
3. `docs/05_performance_benchmark.ipynb`:
   * Chạy đánh giá hiệu năng trên Google Colab (CPU-only) với `/usr/bin/time -v` và vẽ biểu đồ phân tích Runtime & Memory Footprint.

## 2. Lệnh chạy thu thập dữ liệu cho khoảng ID cá nhân
```bash
python -m src.crawler.main \
    --member-id 24120474 \
    --start-month 2024-06 \
    --start-id 12938 \
    --end-month 2024-06 \
    --end-id 17937 \
    --output-dir data/shards/24120474
```

## 3. Input, output và các bước cần bổ sung

- `parse_args() -> argparse.Namespace`: nhận đủ `--member-id`, `--start-month`, `--start-id`, `--end-month`, `--end-id`, `--output-dir`; thêm `--batch-size`, `--rate-limit-sec`, `--resume`. Kiểm tra số nguyên dương, tháng, thứ tự khoảng, giá trị mặc định và thư mục đầu ra.
- `main() -> None`: nối các module theo chữ ký thực tế trong source: sinh ID → discovery → download/clean → references → storage; giữ việc chạy riêng từng MSSV trong `data/shards/<MSSV>/`.
- TODO: lưu checkpoint sau từng batch, chạy `--resume` không tải lại bài đã hoàn thành hoặc ghi trùng bản ghi; phân biệt lỗi từng bài với lỗi cấu hình phải dừng toàn bộ.
- `ResourceProfiler.start() -> None` bắt đầu đo; `stop_and_export(output_json_path: str) -> dict` dừng luồng, ghi `stats.json` và trả kết quả đo.
- Output của mỗi lần chạy: `publications.parquet`, `references.parquet`, `stats.json` trong phân vùng cá nhân; thư mục nguồn tạm ở `data/raw/`.
- TODO: thống nhất stats với nhóm: MSSV, khoảng ID, số thành công/thất bại, thời gian tổng/từng pha (giây), peak/average RSS (MB, công bố hệ số quy đổi), dung lượng trước/sau (byte), số mẫu và môi trường thực thi.
- TODO: dọn luồng giám sát và xuất thống kê khi có lỗi; không nhầm RSS của tiến trình với RAM toàn máy hoặc tự cộng peak của các pha.
- TODO: notebook ghi rõ Google Colab CPU-only, phiên bản Python/thư viện, số bài, tham số chạy và lệnh `/usr/bin/time -v`; phân biệt số đo thật với mẫu.

## 4. Hoàn thành và tích hợp

Các lệnh trên là giao diện dự kiến sau khi thành viên tự hiện thực. Khung hiện tại chỉ có chữ ký hàm, docstring và `NotImplementedError`; kể cả bộ nhận tham số CLI cũng là TODO.

Trong trường hợp chữ ký ví dụ ở README khác với source, thống nhất theo source trong nhánh `main` và trao đổi với người tích hợp trước khi thay đổi giao diện.

- Tự viết logic của module được giao; không sửa module của thành viên khác nếu chưa thống nhất.
- Kiểm tra một tập ID nhỏ và trường hợp lỗi trước khi chạy toàn khoảng; ghi lại số liệu thật, không điền kết quả giả vào báo cáo.
- Chỉ commit code, notebook và tài liệu nhiệm vụ. Dữ liệu thô, Parquet trong shards và các tài liệu đầu vào cục bộ đã được bỏ qua bởi Git.
- Mở pull request về `main` khi hoàn tất, mô tả cách kiểm tra và những giới hạn còn lại.
