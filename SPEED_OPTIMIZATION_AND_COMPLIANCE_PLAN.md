# Tối ưu tốc độ crawler

## Bản nâng cấp ngày 12/11/2026

Mục tiêu là giảm thời gian chờ giữa các công việc và I/O lặp lại, đồng thời giữ nguồn, references, checkpoint và bằng chứng benchmark. Chưa có phép đo toàn bộ 5.000 bài trên Colab cho bản nâng cấp này, nên không cam kết mốc 7–8 giờ.

## Thay đổi

| Phần | Cách thực hiện |
| --- | --- |
| Nhịp request | Khóa riêng cho arXiv/S2, nhả khóa khi ngủ; giữ nhịp arXiv 3 giây trong notebook và một lượt tải tại một thời điểm. |
| Pipeline | ArXiv tải tuần tự, giải nén tối đa hai worker, S2 một worker; giới hạn 25 bài chờ và 4 tác vụ giải nén đang chạy/chờ. |
| S2 | Batch 50, chỉ lấy thêm trang khi thiếu; null được ghi not_indexed. Partial vẫn cần xử lý tiếp, không được tính thành công. |
| Checkpoint | Full ghi mỗi 25 bài đã xong hoặc sau 30 giây khi có kết quả; smoke ghi từng bài. Không chờ xong toàn bộ batch mới tải tiếp. |
| Backup | Chỉ đưa các ID đã commit vào lô sao lưu bình thường; đợi snapshot ổn định, xác minh checksum rồi cập nhật HEAD. Dừng khi backup lỗi. |
| Profiler | Đọc kích thước file thật, không cache theo mtime thư mục; tách RAM/đĩa thành hai luồng, quét đĩa mỗi 30 giây và đầu/cuối lượt. Peak đĩa được ghi rõ là peak lấy mẫu. |
| Log Drive | Nối phần mới của log/JSONL, kiểm tra phần ghi thêm; file bị thay thế hoặc sửa nội dung được chép nguyên tử. Kiểm tra toàn bộ checksum khi kết thúc. |
| ID cuối tháng | Không coi thiếu entry Atom là xác nhận ID không tồn tại. Dùng bằng chứng OAI phù hợp, cache ranh giới đã kiểm chứng trong network_state. |

Nguồn `.bbl` bổ trợ vẫn được giữ theo QA; không xóa bibliography để làm corpus nhỏ hơn. HTTP 404 của một version được lưu bằng chứng riêng, không được ghi như tải TeX thành công.

## Cấu hình Colab

- Smoke: 5 bài, checkpoint từng bài, một bài chờ xử lý nền.
- Full/repair: discovery batch 50, S2 batch 50, checkpoint 25, backup 25, tối đa 25 bài chờ.
- ArXiv 3 giây, S2 5 giây; retry/cooldown thực tế được ghi vào stats.
- Source/giải nén chạy trên `/content`, backup và log lưu ở Drive.
- Source commit, code hash và ZIP phải khớp; chạy lại smoke sau khi chuyển sang bản notebook mới.

## Cách đánh giá

Kiểm tra offline các tình huống hàng đợi đầy, S2 chậm, nguồn tải dở, Stop, backup lỗi và restore/resume. Giữ tests/corpus local. Phép đo mô phỏng Windows chỉ dùng đánh giá từng thay đổi kỹ thuật, không thay thế benchmark Colab.

Khi chạy thật, đo 100–200 bài có nhiều version và archive lớn trước. Theo dõi version xác minh được mỗi giờ, request/retry/cooldown, độ phủ references và chi phí lưu trữ. Thời gian các pha gối đầu có thể chồng lấn; dùng runtime_sec/child_wall_sec cho thời gian toàn lượt, không cộng các phase lại.

Chi tiết file đã sửa, lý do và kết quả: [nhật ký nâng cấp](tasks/SPEED_UPGRADE_PROGRESS_2026-11-12.md).
