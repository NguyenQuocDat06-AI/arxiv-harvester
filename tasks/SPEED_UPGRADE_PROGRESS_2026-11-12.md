# Nâng cấp tốc độ crawler

## Phạm vi

Giữ dữ liệu và checkpoint cũ; sửa tiếp các thay đổi local đang có. Bản trước sửa được lưu trong `build/speed_upgrade_20261112/baseline` cùng checksum. Không gọi API bằng key của nhóm trong kiểm thử offline.

## Tiến trình

| Phần | Vấn đề | Cách xử lý | Trạng thái |
| --- | --- | --- | --- |
| `rate_limiter.py`, `request_policy.py` | S2 ngủ trong khóa chung và chặn arXiv | Tách khóa theo provider; nhả khóa khi chờ, đặt lịch request nguyên tử | Đã sửa |
| `profiler.py` | Cache mtime thư mục bỏ sót file tăng kích thước | Đo kích thước thật; tách luồng RAM/đĩa, quét đĩa mỗi 30 giây và đầu/cuối | Đã sửa |
| `main.py`, `pipeline_support.py` | Chờ hết batch, hàng đợi và metadata dùng closure thay đổi | Hàng đợi giới hạn, gom kết quả đã xong, giữ context riêng cho từng bài | Đã sửa |
| `main.py` / backup | Backup có thể nhận ID chưa hoàn tất | Chỉ sao lưu ID đã commit; giữ snapshot ổn định và kiểm tra checksum; không thử lại backup sau khi lỗi trong cùng run | Đã sửa |
| `id_range.py`, `discovery.py` | `not confirmed` bị coi là xác nhận không tồn tại | Chỉ dùng bằng chứng rõ ràng; xác minh OAI và lưu ranh giới tháng đã kiểm chứng | Đã sửa |
| `colab_support.py` | Chép lại toàn bộ file đang tăng mỗi phút | Đồng bộ phần nối thêm; xử lý file bị thay thế và kiểm tra đầy đủ ở cuối | Đã sửa |
| `records.py`, `validate_sources.py`, `readiness.py` | Partial references từng bị coi là terminal; bằng chứng 404 quá rộng | Partial phải retry; chỉ nhận http_404 đúng version và báo độ phủ thiếu | Đã sửa |
| `colab_crawler.ipynb`, `kaggle_crawler.ipynb` | Commit và code hash đang lệch; batch chưa đồng bộ | Batch 50, checkpoint/backup 25 cho full; smoke checkpoint 1; bỏ gọi API thử ngoài cơ chế cooldown ở Kaggle | Đã ghim và kiểm thử |

## Kiểm chứng

- Lần kiểm tra rộng trước khi ghim notebook: **322 ca đạt**. Các ca bổ sung bao gồm tải qua ranh giới batch khi S2 còn chờ, checkpoint khi Stop, restore/resume, lỗi backup, cùng provider vẫn giữ nhịp, file tăng kích thước và log bị thay thế.
- Kiểm tra riêng pipeline/notebook/Stop sau cập nhật: **80 ca đạt**; kiểm tra độ phủ references và nguồn sau khi sửa partial: **46 ca đạt**. Các bộ này có ca trùng nhau, không cộng số ca thành tổng độc lập.
- Kiểm thử chạy với HTTP thật bị chặn; không gọi API bằng key của nhóm. Chạy trực tiếp trên Windows với dung lượng đĩa thật.
- Phép đo mô phỏng lấy trung vị 3 lượt: arXiv bị chặn bởi S2 giảm từ **0,230 giây** xuống khoảng **0,0001 giây** trong ca S2 ngủ 0,25 giây, arXiv không có lịch chờ riêng. Đây là đo khóa, không phải giảm nhịp arXiv thực tế.
- Đồng bộ 20 lần, mỗi lần nối 256 KiB: lượng payload chép giảm **52,5 MiB → 5 MiB**, thời gian local **0,565 → 0,344 giây**. Kết quả ở `build/speed_upgrade_20261112/measurements.json`; không suy diễn thành tốc độ Google Drive hay toàn bộ crawler.

## Bản phát hành

- **355 ca kiểm tra đạt**, 30,19 giây, với HTTP thật bị chặn. Bộ cuối gồm cả các ca kiểm tra notebook đã ghim commit và cài ZIP bằng chính hàm của notebook rồi probe subprocess. Không dùng mô phỏng dung lượng đĩa trong lượt kiểm tra này.
- Cả hai notebook hợp lệ theo nbformat/AST, không lưu output; source qua compileall và kiểm tra whitespace theo định dạng xuống dòng hiện có.
- Runtime commit: `0fcc359b1c9af77b4a9014b3d8b4664a9f44816c`.
- Code hash: `435e9a4e1df200f00175def529003335e7920434de428078925fb6c48be5199d`.
- Gói dự phòng local: `build/speed_upgrade_20261112/arxiv_colab_runtime.zip`, 43 file, SHA-256 `709866a2806d2063cf4845ba70acdc080142cb7b1d793e8b75ca240a0ddb3373`.
- Tests và corpus giữ local. Hai commit phát hành dùng tác giả Git hiện cấu hình, giữ lịch sử nhóm và nhánh chính `main`.

## Cách chuyển sang bản mới

1. Để lượt cũ kết thúc hoặc Stop và chờ lưu checkpoint; sau đó mới mở notebook mới.
2. Chọn CPU, đúng `CURRENT_MEMBER`, giữ nguyên Drive và MSSV để dùng lại backup/nguồn đã có.
3. Chạy smoke 5 bài đến validation; sau đó đổi sang full và chạy lại từ cell cấu hình.
4. Giữ toàn bộ chuỗi `backups/<MSSV>`, `logs/<MSSV>` và `network_state`. Mất VM có thể phải chạy lại phần chưa vào backup thành công gần nhất.

Các phép đo offline không được dùng làm benchmark Colab để nộp. Chưa đo throughput toàn dải trên Colab cho bản mới; không cam kết thời gian 7–8 giờ hay hết lỗi 429 phía dịch vụ.
