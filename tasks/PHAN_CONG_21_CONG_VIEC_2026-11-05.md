# Phân công M1–M2: 21 đầu việc

**Cập nhật tích hợp source ngày 05/11/2026:** theo yêu cầu của Đạt, source có sẵn được chia commit theo phạm vi phụ trách, dùng tên/email Git đã có của từng thành viên; author và committer của mỗi commit là cùng thành viên phụ trách. Đây là attribution cho source có hỗ trợ từ trợ lý, không xác nhận mỗi người đã tự viết, kiểm thử hoặc hoàn thành 21 đầu việc. Xem [biên bản tích hợp và kiểm tra](PUSH_SOURCE_2026-11-05.md). Mốc Git và phần chuẩn bị dưới đây ghi trạng thái trước đợt tích hợp; sau khi lấy source mới, vẫn cần smoke/validation trước full.

Mốc kiểm tra: `develop` trên GitHub tại `6d34d57`, ngày 05/11/2026. Bảng đếm theo Git author, có tính merge: Đạt 6, Triết 2, Trí 2, Tuấn 2, Tân 1. Nếu Triết, Trí, Tuấn và Tân lần lượt có thêm 5, 5, 5 và 6 commit thì mỗi người đó có 7; Đạt vẫn có 6. Đạt có thể có thêm một commit nếu trực tiếp hoàn thành một việc có giá trị, không tạo commit rỗng để đủ số.

Mỗi mục dưới đây là **một ứng viên commit**, không phải commit đã làm. Người được giao trực tiếp thực hiện, kiểm tra và ghi kết quả; chỉ commit nếu có thay đổi thực chất. Nếu một mục không phát sinh thay đổi hoặc có nhiều phần phụ thuộc chặt nhau, ghi kết quả review hoặc gộp mục thay vì tạo thay đổi giả. Thống kê Git không chứng minh riêng phần đóng góp của từng người.

Thư mục `tests/` được giữ local và **không đưa lên GitHub**. Có thể chạy kiểm tra ở máy cá nhân; đầu ra để nộp là code, notebook, tài liệu và số liệu thực tế, không commit test hoặc API key.

## Chuẩn bị chung

1. Source mới đang có trong workspace và nhánh sao lưu cục bộ, chưa nằm trên `develop` sau lần thu hồi. Nhóm cần thống nhất tích hợp source với attribution đúng trước khi các nhánh phụ thuộc vào source này được gộp; không tự nhận các thay đổi cũ là do mình viết.
2. Nếu chạy thử trước khi tích hợp, dùng `colab_crawler.ipynb` bản local, chọn `SOURCE_MODE="bundle"` và gói `build/colab_fixes_20261104/arxiv_colab_runtime.zip` đi kèm; hash của ZIP đã khớp notebook tại thời điểm lập bảng. Chạy smoke và validation trước full. Không chạy chế độ lấy source GitHub của notebook mới khi `develop` vẫn là mốc cũ.
3. Mỗi người dùng đúng dải ID/MSSV, lưu checkpoint và log riêng. Một checkpoint/backup chỉ có một runtime ghi. Các runtime riêng không có bộ giới hạn arXiv/S2 toàn cục; phối hợp lịch chạy và tôn trọng cooldown.
4. Output lớn, nguồn `.tex/.bib`, checkpoint và log để ở Drive hoặc nơi nhóm thống nhất; commit phần code và báo cáo tổng hợp, ghi đường dẫn bằng chứng và phạm vi, không đưa key hoặc corpus lên Git.

## Triết — 5 đầu việc

| Mã | Công việc thực tế | File dự kiến | Kiểm tra và bàn giao |
|---|---|---|---|
| V1 | Kiểm tra cấu hình Colab theo từng thành viên, CPU-only, source hash và chế độ smoke/full; sửa thông báo hoặc cấu hình nếu phát hiện sai. | `colab_crawler.ipynb` | Ghi run ID, MSSV, phạm vi, hash và kết quả validation của lượt smoke. |
| V2 | Kiểm tra dừng/resume và khôi phục từ backup trên một bản dữ liệu thử; sửa lỗi checkpoint nếu có. | `src/crawler/main.py`, `src/crawler/readiness.py`, `colab_crawler.ipynb` | Đối chiếu ID, trạng thái và file trước/sau khôi phục; không ghi đè backup của lượt đang chạy. |
| V3 | Đo M1 trên Colab CPU, làm rõ phạm vi `runtime_sec`, wall time và kích thước đĩa; bổ sung hiển thị số đo nếu còn thiếu. | `src/crawler/profiler.py`, `src/crawler/reporting.py`, `docs/05_performance_benchmark.ipynb` | Bảng số liệu thật theo run, nêu thời gian chờ/backup và phạm vi thư mục được đo. |
| V4 | Đo M2 trên dữ liệu nguồn đã có và cập nhật phần benchmark parser. | `docs/08_parser_benchmark.ipynb`, phần thống kê liên quan | Ghi CPU, RAM, thời gian, số paper/version, cache và tỷ lệ partial/error; không gọi mẫu là toàn corpus. |
| V5 | Dựng lại Jupyter Book từ input được chốt và chuẩn bị triển khai Pages. | `tools/build_report.py`, cấu hình Book, hướng dẫn triển khai | Build không lỗi, ghi nguồn input và hash; xác nhận URL public sau khi nhóm triển khai. |

## Trí — 5 đầu việc

| Mã | Công việc thực tế | File dự kiến | Kiểm tra và bàn giao |
|---|---|---|---|
| I1 | Rà compilation root và `\\input` không dùng ngoặc, đặc biệt mẫu `2412.19116v1`; chỉ hỗ trợ thêm khi xác định được đường dẫn an toàn. | `src/parser/gather.py`, `src/parser/latex.py` | Đối chiếu source map và diagnostics với TeX; trường hợp thiếu file vẫn báo thiếu. |
| I2 | Đối chiếu hierarchy của đoạn văn, toán, list và figure trên nhiều version đã tải; sửa sai lệch có thể tái hiện. | `src/parser/hierarchy.py`, `docs/06_parsing_and_hierarchy.ipynb` | Ví dụ TeX và các node/quan hệ tương ứng, kèm ID/version và kết quả kiểm tra. |
| I3 | Kiểm tra citation mapping và bibliography thiếu của `2412.19119v1`, `2412.19121v2/v3`; phân biệt thiếu source với lỗi parser. | `src/parser/bibliography.py`, `src/parser/main.py` | Danh sách unresolved trước/sau và lý do cho trường hợp chưa xử lý được; không tự tạo BibTeX. |
| I4 | Đối chiếu normalization, dedup và quan hệ parent–child giữa các version. | `src/parser/normalize.py`, `src/parser/deduplicate.py`, `docs/07_standardization_and_deduplication.ipynb` | So sánh số phần tử trước/sau, xác minh không mất nội dung hoặc tạo self-edge. |
| I5 | Merge/export và kiểm tra năm bảng M1–M2 trên input nhóm đã chốt. | `src/crawler/records.py`, `src/crawler/merge_shards.py`, `src/parser/validation.py`, `docs/04_schema_and_data_quality.ipynb` | Ghi schema, khóa trùng, orphan, số version kỳ vọng/đã parse và các lỗi còn lại. |

## Tuấn — 5 đầu việc

| Mã | Công việc thực tế | File dự kiến | Kiểm tra và bàn giao |
|---|---|---|---|
| U1 | Kiểm tra downloader version cụ thể và xử lý PDF-only/no-LaTeX trên các source đã tải. | `src/crawler/source_downloader.py` | Đối chiếu version ID, loại file và manifest bằng mẫu thật; giữ nguyên source hợp lệ. |
| U2 | Kiểm tra resume `.part`, `Content-Range` và giới hạn thời gian khi bị ngắt; sửa lỗi nếu tái hiện được. | `src/crawler/source_downloader.py`, `src/crawler/retry_sources.py` | Bằng chứng byte/range và kết quả khôi phục trên bản sao; không ghép dữ liệu sai revision. |
| U3 | Audit source/version của dải được giao và lập manifest phần thiếu. | `src/crawler/validate_sources.py` | Số version đã xác minh, thiếu, lỗi và empty có bằng chứng, kèm snapshot đầu vào. |
| U4 | Chạy thử retry có kiểm soát trên các version còn lỗi sau U3; xử lý và báo các trường hợp chưa lấy được. | `src/crawler/retry_sources.py`, tài liệu kết quả | Ghi ID/version, status trước/sau và lỗi còn lại; giữ pacing/cooldown, không thay source tốt. |
| U5 | Kiểm tra khôi phục bản sao lưu và thống kê size trước/sau trên cùng tập đã xác minh. | `src/crawler/drive_backup.py`, `docs/02_source_download_and_cleaning.ipynb` | Đối chiếu checksum/checkpoint và bảng size có mẫu số rõ ràng; không sửa backup đang dùng. |

## Tân — 6 đầu việc

| Mã | Công việc thực tế | File dự kiến | Kiểm tra và bàn giao |
|---|---|---|---|
| N1 | Đối chiếu kết quả S2 batch theo paper ID, gồm entry null hoặc thiếu. | `src/crawler/reference_batch.py` | Mẫu đầu vào/đầu ra và status cho từng paper; không gán references nhầm bài. |
| N2 | Kiểm tra 429, `Retry-After`, cooldown và resume; sửa lỗi tái hiện được. | `src/crawler/reference_scraper.py`, `src/crawler/request_policy.py` | Ghi status và thời điểm retry trên lượt thử hợp lệ; không chia key để vượt hạn mức. |
| N3 | Xác minh references phân trang và số `referenceCount`; giữ trạng thái partial khi chưa đủ. | `src/crawler/reference_scraper.py` | Đối chiếu số kỳ vọng/số nhận được trên mẫu thích hợp, kèm lý do nếu thiếu. |
| N4 | Phân biệt API `empty`, `not_indexed`, `api_error` và fallback BibTeX khi tổng hợp. | `src/crawler/enrich_references.py`, `src/crawler/observations.py` | Bảng đếm từng trạng thái và provenance; không tính fallback thành S2 success. |
| N5 | Bổ sung metadata thiếu trên các references có thể xác minh, giữ nguồn từng trường. | `src/crawler/enrich_references.py`, tài liệu kết quả | Số trường được bổ sung, còn thiếu và nguồn; không suy ngày submission từ năm/publication date. |
| N6 | Cập nhật thống kê references cho báo cáo M1 theo dữ liệu thực tế. | `docs/03_reference_extraction.ipynb` | Bảng tỷ lệ theo nguồn/trạng thái, mẫu số và snapshot; không dùng số cũ làm kết quả mới. |

## Tích hợp và nộp

Các file dùng chung như `src/crawler/main.py`, `request_policy.py` và notebook báo cáo cần thống nhất người tích hợp trước khi sửa để tránh ghi đè. Mỗi thành viên làm việc trên nhánh của mình và mở PR cho nhóm review; không tự tạo commit dưới tên người khác. Không commit thư mục `tests/`.

Triết tổng hợp Book sau khi có đầu vào đã chốt; Trí kiểm tra validation; Tuấn và Tân bàn giao tình trạng source/references; Đạt đối chiếu dải ID và điều phối. Khi còn thiếu corpus hoặc benchmark, báo đúng phần đã làm và phần còn thiếu. Việc xuất bản Pages và nộp link vẫn cần được nhóm thực hiện/xác nhận.
