# Tiến trình tích hợp và phân công — 04/11/2026

Yêu cầu: chia công việc tiếp theo cho 5 thành viên và push GitHub theo phạm vi phụ trách.

## Thay đổi trong đợt này

| File | Thay đổi | Lý do |
|---|---|---|
| `tasks/TEAM_HANDOFF_2026-11-02.md` | Cập nhật tình trạng Drive, phân công M1/M2, thứ tự smoke → repair → full và đầu ra từng người | Bản cũ còn mô tả chưa push và chỉ có 2 version local; không phản ánh lần audit Drive |
| `tasks/TASK_*.md` | Bổ sung việc tiếp theo và dùng `develop` làm đích PR | Giữ dải ID cá nhân, đồng thời làm rõ phần review/kiểm chứng còn thiếu |
| `colab_crawler.ipynb`, `README.md` | Chọn source GitHub `develop`, cập nhật bằng fast-forward; giữ chế độ ZIP dự phòng và nhập S2 key trực tiếp | Sau khi push, Colab phải dùng runner mới thay vì checkout cũ hoặc yêu cầu ZIP local |
| `tools/prepare_handoff.py` | Thêm nhật ký này vào phân công; dùng ngày đóng gói thực tế | Gói bàn giao mới không thiếu tài liệu hoặc mang ngày cũ |

## Phần source đưa lên GitHub

- Đạt: lịch sử version, scanner/gathering, root config; package, CI, tests tích hợp và tài liệu chung.
- Tuấn: downloader, audit/retry nguồn, hierarchy và notebooks 02/06.
- Trí: merge/records, normalization/dedup, storage/validation và notebooks 04/07.
- Tân: references/enrich, bibliography và notebook 03.
- Triết: runner/checkpoint/readiness, parser runner/statistics, Colab/report và notebooks 05/08.

Chia 5 commit theo đầu mối module. Code có phần trợ lý hỗ trợ; thành viên tiếp tục review và chạy dữ liệu thật. Không đưa lại 13 commit đã thu hồi. Không đưa corpus, `.env`, scratch hoặc notebook Kaggle cũ vào đợt push.

## Kiểm tra và push

- Snapshot dự kiến push: 65 file thay đổi, chia thành 5 commit; giữ các thay đổi ngoài phạm vi ở máy.
- `171 passed in 19.05s` khi chạy trên snapshot riêng từ base `2adf1b3` cộng đúng các file được chọn; imports được đối chiếu để không dùng nhầm source ngoài snapshot.
- 9 notebook hợp lệ; compile Python đạt. Gói wheel build/cài offline và 7 CLI `--help` chạy được ngoài repo từ chính gói đã cài.
- Gói bàn giao: 7 ZIP, 74 source file, 73 file được phân công; không trùng hoặc thiếu phân công. Chênh lệch 1 file là source đã có trên Git, không có thay đổi cần phân công.
- Không có giá trị S2 key trong payload. Corpus, checkpoint, `.env`, scratch, artifact build và notebook Kaggle cũ không nằm trong danh sách commit.
- Notebook mặc định `SOURCE_MODE="github"`, `UPDATE_SOURCE=True`, `RUN_MODE="smoke"`. ZIP dự phòng đã được ghim lại SHA-256 sau khi sửa README.

Kết quả tests không thay đổi sau bước cập nhật nhật ký này; chỉ tài liệu tiến trình được bổ sung. Bằng chứng, danh sách commit và trạng thái push thực tế lưu trong `build/team_push_20261104/`. Push chỉ được xác nhận sau khi đối chiếu HEAD GitHub; chưa xác nhận kết quả GitHub Actions trong các kiểm tra local trên.

## Chưa hoàn thành

Chưa sửa trực tiếp dữ liệu Drive, thu thập toàn corpus, chạy benchmark Colab chính thức hoặc xác nhận Pages/Moodle. Việc tiếp theo và người phụ trách ở [bản phân công](TEAM_HANDOFF_2026-11-02.md).

## Khắc phục log smoke `20261103T194025Z-f00fc241`

Log người dùng cung cấp: 5 paper mất 616,243 giây; 2 version tải lỗi (`2412.18849v2`, `2412.18850v1`). Hai truy vấn S2 mất 179/165 giây do retry. Không dùng kết quả này làm bằng chứng smoke đã đạt hoặc cam kết chạy full xong trong 7 ngày.

| File | Sửa gì | Lý do |
|---|---|---|
| `src/crawler/reference_scraper.py` | Retry mặc định 3 lần; tăng nhịp nghỉ sau 429, giữ qua paper, nghỉ chung khi hết lượt; hoãn Retry-After dài | Tránh bắt đầu lại chuỗi chờ 5/10/20/40/80 giây cho từng paper. Bài bị hoãn vẫn là `api_error` và cần retry |
| `src/crawler/rate_limiter.py` | Thêm cooldown theo domain, không rút ngắn thời gian nghỉ đã có | Request tiếp theo vẫn tôn trọng yêu cầu nghỉ của server |
| `src/crawler/source_downloader.py` | Bỏ backoff thừa sau lỗi HTTP cuối, hiện status/attempt/error trong manifest; kiểm tra Content-Length/Range, hiện tiến độ byte và đóng file PDF trước khi xóa | Tránh chờ mà không còn retry; phân biệt lỗi mạng/HTTP, không công bố archive thiếu byte và chạy được trên Windows |
| `src/crawler/main.py`, `readiness.py` | Cấu hình S2 riêng, truyền số lần tải/timeout xuống downloader, lưu tham số và log ETA cho lượt đang chạy | Cấu hình notebook phải có tác dụng; không ngoại suy từ số paper cộng dồn hoặc hứa đã xong phần retry |
| `colab_crawler.ipynb`, `README.md` | Smoke batch 1, full/repair batch 10; thêm tham số retry/pacing, kiểm tra CLI mới và hướng dẫn resume smoke lỗi | Giảm request metadata/ghi checkpoint ở full, giữ dữ liệu cũ để retry đúng phần thiếu |
| `pyproject.toml` | Thêm `nbformat` vào dev dependencies | Bộ test notebook cần thư viện này khi CI cài `.[dev]` |
| `tests/test_s2_request_policy.py`, `test_source_retry_execution.py`, `test_crawler_repairs.py`, `test_colab_workflow.py`, `test_cli_and_profiling.py` | Kiểm tra cooldown/recovery, bảo toàn file tải dở, tham số CLI và ba chế độ notebook; cập nhật fake downloader theo chữ ký mới | Kiểm chứng thay đổi bằng clock/HTTP giả, không lấy fixtures làm số liệu crawl thật |
| `tools/prepare_handoff.py` | Phân công test S2 mới cho Tân | Không bỏ sót file khi tạo gói bàn giao |

Probe giới hạn từ Windows: hai nguồn lỗi có phản hồi gzip ở phần đầu tệp; S2 key được nhận nhưng gặp lại 429 sau một request 200. Không kết luận điều kiện mạng của Windows giống Colab. Kết quả tải đầy đủ/kiểm thử và SHA đợt sửa được lưu trong `build/crawl_tuning_20261104/`.

Đã có lượt `185 passed in 23.17s`, sau đó bổ sung ngân sách tải version và test cho kết nối truyền chậm. `--source-max-seconds 180` được kiểm tra giữa các lần đọc/request; giữ partial để resume. Dùng `read1` khi HTTP client hỗ trợ để không phải đợi đủ chunk lớn mới cập nhật tiến độ. Một lần đọc hoặc cooldown server vẫn có thể kết thúc muộn hơn ngân sách. Lượt tải thử đầu tiên được dừng sau khi nhận khoảng 20,7 MB; partial giữ nguyên, không coi là nguồn đã hoàn tất. Lượt xác minh tiếp theo dùng ngân sách 45 giây/version để kiểm tra resume có giới hạn.

9 notebook hợp lệ và mọi code cell Colab parse được. Hai test ban đầu dùng fake downloader theo chữ ký cũ đã được cập nhật tham số, giữ nguyên assertions về resume và dữ liệu đầu ra. Gói handoff có 7 ZIP, 75 source file, 74 file được phân công, không trùng hoặc thiếu. Source ZIP được ghim lại hash khi chốt code; không chứa giá trị S2 key. Chưa xác nhận smoke mới trên Colab; kết quả HTTP và thời gian từ local không phải benchmark chính thức.

Kết quả cuối: `186 passed in 15.34s`. Tải thật cả `2412.18849v2` và `2412.18850v1` thành công, source audit xác nhận đúng TeX và dung lượng; version đầu có dùng lại partial từ lượt trước. Hai truy vấn S2 cho `2412.18851`/`2412.18852` trả đủ 22/49 references, 2 HTTP 200, không retry trong lượt xác minh này. Không suy ra 429 đã hết lâu dài hoặc tốc độ toàn corpus từ mẫu nhỏ. Dữ liệu kiểm tra nằm riêng ở `build/crawl_tuning_20261104/verified_raw/`; Drive chưa được sửa.

Tham chiếu: [S2 API tutorial](https://webflow.semanticscholar.org/product/api/tutorial), [arXiv API terms](https://info.arxiv.org/help/api/tou.html). Giữ một kết nối và khoảng nghỉ arXiv tối thiểu 3 giây; không tăng số phiên để né giới hạn.

## Chuyển S2 sang batch

Người dùng đồng ý triển khai batch và xác nhận lượt repair Colab vẫn đang chạy. Đợt triển khai không gọi S2 bằng cùng key, không sửa checkpoint/Drive của lượt đang chạy. Kiểm tra HTTP được thực hiện bằng fixtures; chưa có benchmark batch thật trên Colab.

| File | Sửa gì | Lý do |
|---|---|---|
| `src/crawler/reference_batch.py` | POST theo nhóm 25 ID; map theo externalIds.ArXiv, kiểm tra referenceCount, tách nhóm quá lớn, lấy trang hoặc truy vấn riêng cho entry thiếu | Giảm request mà vẫn xác minh đúng bài nguồn và đủ references; null không tự thành empty/not_indexed |
| `src/crawler/reference_scraper.py` | Dùng chung GET/POST với pacing/backoff; phát hiện giới hạn kích thước; kiểm tra ID ở fallback GET; đếm request theo method | Batch vẫn tôn trọng cooldown; tránh gán nhầm references và đo sai số request |
| `src/crawler/main.py` | Prefetch nhóm cần references, lưu sau từng paper; CLI tách batch API với chu kỳ checkpoint; stats và phân bổ thời gian batch | Giữ kết quả trước khi hoàn tất cả lô; resume không gọi lại bài đã xong |
| `src/crawler/observations.py` | Thêm request group, group size và cộng metrics | Một request chung chỉ được đếm một lần thay vì nhân theo số paper |
| `src/crawler/readiness.py`, `colab_crawler.ipynb` | Kiểm tra runtime batch; cấu hình 25 paper/POST, checkpoint mỗi paper; chặn mode/member khác cấu hình đường dẫn | Colab phải sử dụng CLI mới; xử lý tình huống repair nhầm thư mục smoke |
| `tests/test_reference_batch.py`, `tests/test_crawler_batch_pipeline.py` | Kiểm tra identity, null, partial/pages, size split, 429, bảo toàn cạnh và khôi phục sau ngắt; so sánh GET với batch | Đối chiếu cả dữ liệu đầu ra và số request, không chỉ kiểm tra hình dạng lệnh |
| Các test CLI/readiness/Colab hiện có | Giữ coverage gọi riêng bằng `--s2-batch-size 1`; thêm coverage mặc định batch và cấu hình Colab | Không để test cũ vô tình gọi mạng; bộ test mới kiểm tra luồng batch thực qua HTTP giả |
| `README.md`, `tools/prepare_handoff.py` | Cập nhật cách chạy, metrics và phân công file mới | Tài liệu và gói bàn giao khớp implementation |

Kiểm tra đầu tiên: 100 paper giả lập dùng 4 POST, resume không có request mới; 50 paper qua 2 POST cho bảng references giống 50 GET. Đây là kiểm chứng số request bằng HTTP giả, không phải số đo tốc độ mạng thật. Hạn chế API tham chiếu: [S2 Graph API](https://api.semanticscholar.org/api-docs) (500 ID và 10 MB mỗi batch); mặc định chọn 25, vẫn đối chiếu coverage và phân trang nếu cần.

Kiểm tra chốt implementation: `211 passed in 34.42s`; báo cáo JUnit ở `build/s2_batch_20261104/pytest_release.xml`. Gói handoff có 7 ZIP, 78 source file, 77 file được phân công, không thiếu/trùng. Chưa xác nhận POST batch thật hoặc thời gian hoàn tất corpus; lượt repair hiện tại tiếp tục dùng source đã nạp trước đó.

Chi tiết tests, bộ source, commit và kết quả push cuối lưu tại `build/s2_batch_20261104/`. Khi chuyển sang bản mới, dừng lượt cũ hoặc đợi kết thúc, sau đó mở notebook mới và chạy lại smoke/validation với cùng dữ liệu; không khởi chạy thêm tiến trình ghi vào shard đang dùng.

## Xử lý 429 có trạng thái lưu lại

Yêu cầu: xử lý 429 đầy đủ ở phía client. Giới hạn phía server vẫn có thể xuất hiện; không dùng đổi IP/key hoặc tăng số máy để né giới hạn. Đợt này giữ dữ liệu cũ và sửa các điểm retry sớm, reset cooldown và thiếu chẩn đoán.

| File | Sửa gì | Lý do |
|---|---|---|
| `src/crawler/request_policy.py` | Lưu deadline UTC, số 429 liên tiếp, nhịp request theo provider/key; khóa OS cục bộ; đọc Retry-After dạng số/HTTP-date; che key và ghi chẩn đoán | Restart không xóa thời gian nghỉ; khóa tự nhả khi crash, không dùng khóa OS trên Drive/FUSE; có dữ liệu để xác định lỗi dịch vụ |
| `src/crawler/rate_limiter.py` | Request phải đặt chỗ qua state chung, tôn trọng cả pacing và cooldown; hoãn khi chờ quá ngưỡng | Các tiến trình cùng runtime/state không gửi sớm hoặc chạy trùng |
| `src/crawler/reference_scraper.py` | Chờ ít nhất 60 giây ngay sau 429, tăng dần nếu tiếp tục lỗi; không reset state lưu trên đĩa | Loại chuỗi retry 10/20 giây trong lúc dịch vụ vẫn hạn chế |
| `src/crawler/discovery.py`, `version_history.py` | Metadata/OAI dùng cùng cooldown arXiv; 429 dừng thay vì suy ra ID không tồn tại | Tất cả request arXiv của các công cụ được phối hợp trong cùng state |
| `src/crawler/source_downloader.py` | 429 giữ partial và dừng sớm; resume theo đoạn 1 MiB, chỉ công bố archive sau khi đủ byte | Tránh gọi tiếp các version trong khi bị hạn chế và khôi phục archive lớn từng bị IncompleteRead |
| `src/crawler/main.py` | Runtime state chung, dừng sau checkpoint khi arXiv bị giới hạn; status `paused_rate_limit`, số ID chưa xử lý và retry_after | Không trình bày một lượt tạm dừng như đã crawl xong; giữ tiến độ thật |
| `retry_sources.py`, `enrich_references.py` | CLI nhận state dir; giữ kết quả rồi dừng/hoãn khi provider đang cooldown | Các công cụ sửa dữ liệu không bỏ qua chính sách mới |
| `readiness.py`, `colab_crawler.ipynb` | Batch mặc định 5; state chung trên Drive; validation nhận diện pause, không công bố export cuối | Người dùng biết đang chờ dịch vụ, không nhầm paused với completed hoặc mất dữ liệu |
| Các test request policy/source/CLI/Colab và `tools/prepare_handoff.py` | Kiểm tra restart, khóa nhiều tiến trình/crash, redaction, pause, partial/Range và phân công file mới | Kiểm chứng cả liveness, bảo toàn dữ liệu và giới hạn request |

Khóa cục bộ chỉ đảm bảo các tiến trình trong cùng máy/runtime dùng chung thư mục state; không phải distributed lock cho nhiều Colab VM. Không gọi thêm API thật để cố tạo lại 429. Kết quả kiểm thử và bộ source sẽ ghi ở `build/rate_limit_20261104/`; chưa xác nhận lượt repair mới trên Colab.

Kiểm tra chốt: `232 passed in 41.24s`, JUnit tại `build/rate_limit_20261104/pytest_release.xml`. Có kiểm tra bằng tiến trình con cho tranh chấp request và nhả khóa sau crash; HTTP/clock giả kiểm tra 429 qua restart, Retry-After dạng ngày, che token, dừng metadata/OAI và bảo toàn dữ liệu khi pause. Đây là kiểm chứng code, chưa phải kết quả crawl mới trên Colab.

Khi dùng notebook mới: dừng lượt cũ, nạp lại source, giữ `network_state` cùng corpus/checkpoint; chạy smoke và validation trước khi repair/full. Nếu nhận `paused_rate_limit`, chờ số giây được báo rồi chạy lại cùng chế độ. Chỉ dùng một Colab runtime với cùng S2 key.
