# Tối ưu tải nguồn — 04/11/2026

Yêu cầu: metadata giữ nhịp 3 giây; nguồn tải tối đa 1 request/giây với một kết nối; resume tăng đoạn 1 → 4 → 8 MiB; Colab dùng ổ `/content` và sao lưu theo lô lên Drive.

## Đã sửa

| File | Thay đổi | Lý do |
|---|---|---|
| `src/crawler/source_downloader.py` | Nhịp nguồn riêng, đoạn Range thích ứng | Giảm chờ giữa nguồn và giảm request khi tải tiếp, giữ kiểm tra đủ byte |
| `src/crawler/rate_limiter.py` | Chỉ đặt chỗ request sau khi hết khoảng nghỉ cục bộ | Tránh ghi state trước thời điểm có thể gửi, giảm I/O với state chung |
| `src/crawler/main.py`, `retry_sources.py` | Tham số nhịp nguồn; sao lưu sau checkpoint | Cấu hình phải có tác dụng trong crawler và retry |
| `src/crawler/drive_backup.py` | Archive tăng dần, checksum, commit sau kiểm tra; restore có staging | Giữ nguyên lô tốt khi copy bị ngắt; giảm đọc/ghi file nhỏ trên Drive |
| `colab_crawler.ipynb` | Raw/shard trên `/content`, restore dữ liệu cũ và backup Drive | Tải và giải nén dùng ổ cục bộ, dữ liệu cũ tiếp tục dùng được |
| Tests, README, readiness và handoff | Kiểm tra resume, gián đoạn, dữ liệu cũ và CLI | Không dùng tốc độ lý thuyết làm số đo thật |

## Kiểm chứng

- **254 tests đạt trong 46,41 giây**; JUnit tại `build/download_speed_20261104/pytest_release.xml`.
- HTTP/clock giả xác nhận nguồn gửi cách 1 giây, metadata chờ 3 giây; cả hai vẫn giữ cooldown. Hai lượt tải nguồn khác paper được chạy nối tiếp khi gọi từ nhiều thread.
- Tải tiếp phần còn lại 20 MiB dùng 4 request, nhận các đoạn 1/4/8/7 MiB; Range cuối yêu cầu tối đa 8 MiB. Khi đoạn thứ ba lỗi, lần tiếp theo giảm còn 4 MiB và giữ đúng offset. Đây là số request trong kiểm thử, không phải tốc độ mạng Colab.
- Kiểm tra copy Drive bị ngắt hoặc sai checksum: HEAD cũ giữ nguyên, crawler dừng trước paper mới. Archive hỏng hoặc đường dẫn không hợp lệ không được công bố khi restore.
- Kiểm tra restore vào workspace mới rồi resume: 5 paper đã xong không phát sinh lần tải nguồn hay S2 mới. Thư mục version rỗng, partial, working tables và checkpoint parts được giữ.
- Cell notebook được chạy với module Colab/HF giả để kiểm tra đường dẫn SSD, import dữ liệu Drive cũ và lưu log đã kết thúc; không gọi dịch vụ thật.

Chưa thay đổi Drive của người dùng hoặc gọi API tải thật trong đợt sửa này. Chưa có benchmark tốc độ Colab mới. Kết quả đóng gói, commit và push lưu riêng ở `build/download_speed_20261104/`.

## Cách chạy

1. Dừng lượt cũ. Mở notebook mới từ `develop`, restart runtime và chạy từ đầu.
2. Giữ `USE_GOOGLE_DRIVE=True`, `USE_LOCAL_WORKSPACE=True`, `SOURCE_RATE_LIMIT_SEC=1.0`, `RATE_LIMIT_SEC=3.0`, `BACKUP_EVERY_PAPERS=10`.
3. Chọn `RUN_MODE="full"` để tiếp tục toàn dải; khi có checkpoint, notebook tự thêm `--resume` để xử lý phần thiếu và ID mới. Sau khi đổi chế độ, chạy lại cell đường dẫn và checkpoint. Smoke/repair có thể chạy riêng khi cần kiểm tra nhỏ. Dữ liệu cũ được copy và đối chiếu vào `/content`, không bị xóa khỏi Drive.
4. Khi VM mới khởi động, cell checkpoint tự khôi phục từ `backups/<MSSV>/HEAD.json` và chuỗi archive. Raw nằm ở `/content/arxiv-harvester-data/workspaces/<MSSV>/raw`; smoke có thêm nhánh `smoke/<N>_papers`.
5. Giữ toàn bộ archive/commit JSON, HEAD và `network_state`. Raw/shard Drive cũ giữ làm lịch sử; dữ liệu mới nằm trong backup archive. Log sau khi kết thúc/validation ở `logs/<MSSV>/<run_id>`; course export chỉ cập nhật khi validation đạt.

Lô chưa sao lưu có thể cần làm lại nếu VM bị xóa. Mặc định sau tối đa 10 paper sẽ có một lần sao lưu dữ liệu; lúc thoát bình thường hoặc Stop có thêm bước lưu phần còn lại. Một lần tải rất lâu chưa kết thúc paper có thể chưa tới mốc backup. Chỉ dùng một runtime ghi vào backup của mỗi thành viên. Không có cơ chế tăng kết nối hoặc đổi IP để né 429.

Tham chiếu: [arXiv full-text harvesting](https://info.arxiv.org/help/bulk_data.html#play-nice), [API metadata](https://info.arxiv.org/help/api/tou.html), [Colab I/O](https://research.google.com/colaboratory/faq.html).

## Cho phép full tiếp tục phần thiếu

Người dùng gặp lỗi chặn full vì smoke proof thuộc code cũ. Log hiện có 70 version nguồn tái sử dụng, 3 version cần kiểm tra và 12 paper cần xác minh references; đây là các phần mà full resume có thể xử lý tiếp.

- `colab_crawler.ipynb`: bỏ hai điều kiện bắt buộc smoke/repair trước full; preflight ghi nhận tình trạng và thông báo phần cần xử lý. Mặc định chuyển sang full. Run metadata lưu preflight để đối chiếu.
- `tests/test_colab_workflow.py`: kiểm tra full không bị chặn khi thiếu smoke hoặc còn pending; lệnh có resume, bao phủ toàn dải và không có existing-only/max-papers.
- `tests/test_crawler_batch_pipeline.py`: kiểm tra full sửa nguồn/references cũ, giữ nguồn tốt và thêm ID mới; không nhân đôi references.
- `README.md`: cập nhật cách chạy. Kiểm tra checkpoint sai MSSV/dải ID hoặc thiếu part vẫn dừng; validation cuối vẫn giữ tiêu chí dữ liệu thật và export.

Kiểm chứng sau thay đổi full resume: **258 tests đạt trong 49,93 giây**, JUnit tại `build/full_resume_20261104/pytest_release.xml`. Chưa thay đổi dữ liệu Drive hoặc chạy full trên Colab thay người dùng. Mở notebook mới; cập nhật Git checkout trong notebook cũ không tự thay code của cell đang mở.

## Tự tiếp tục sau arXiv 429

Log `20261104T115511Z-d7e4bba4` đã chạy đúng full: 4.964 ID cần xử lý sau khi bỏ qua 36 ID đã đủ. Lượt này xử lý 14 ID rồi dừng vì `2412.18883v1` bị arXiv trả 429. Trước đó S2 mất 196,29 giây cho ba request 429; `2412.18870v1/v2` đã tải thành công trong 1,40/7,78 giây. Số `batch-size=5` là kích thước lô, không phải giới hạn tổng số paper.

| File | Thay đổi | Lý do |
|---|---|---|
| `src/crawler/main.py` | Thêm `--auto-resume-rate-limit`, backup trước khi chờ, tiếp tục trong cùng tiến trình; đưa paper bị giới hạn về cuối hàng đợi | Full không phải khởi động lại thủ công sau mỗi arXiv 429; một paper lỗi không đứng mãi trước các ID mới |
| `src/crawler/main.py` | Giữ danh sách ID trong run, append metrics qua các lần tiếp tục; tách ID duy nhất khỏi số lượt xử lý | Không chạy lại bước dò tháng đã hoàn tất, không ghi đè số đo cũ hoặc nhân số paper vì retry |
| `src/crawler/reference_scraper.py` | Khi cấu hình một lần thử, hoãn ngay cooldown S2 lưu trên đĩa | Không giữ bước tải nguồn hàng phút trong khi S2 chưa cho truy vấn |
| `colab_crawler.ipynb`, `readiness.py` | Full mặc định auto-resume arXiv; S2 mặc định một lần thử; kiểm tra CLI/runtime mới | Tham số UI có tác dụng và notebook không chạy nhầm source cũ |
| Các test pipeline/Colab/persistent policy | HTTP/clock giả kiểm tra chờ, tiếp tục, Stop, backup và metrics | Không tạo thêm request bằng key/IP đang dùng trên Colab |

CLI không bật auto-resume vẫn pause như cũ. Auto-resume chỉ xử lý cooldown arXiv; S2 lỗi vẫn được giữ là chưa hoàn tất. Có thể Stop khi đang chờ; không có bảo đảm hoàn tất 5.000 bài trong một khoảng thời gian cố định nếu dịch vụ tiếp tục hạn chế.

Kiểm chứng: **263 tests đạt trong 60,08 giây**, JUnit tại `build/auto_resume_20261104/pytest_release.xml`. Có ca chờ rồi chạy hết phạm vi, metadata bị 429 trước/khi đang có paper cũ, Stop trong lúc chờ, restore backup và bảo toàn metrics qua các lần retry. Ca S2 một lần thử xác nhận cooldown lưu từ lượt trước được hoãn ngay, không gửi HTTP hoặc sleep để giữ bước tải nguồn. Kiểm tra nhả khóa sau crash cho Windows có thời gian chờ hữu hạn hai giây để tránh đua với kernel cleanup; vẫn từ chối tiến trình khác khi chủ khóa còn chạy. Các kiểm tra đều offline, chưa chạy lại Colab của người dùng.
