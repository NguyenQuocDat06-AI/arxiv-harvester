# Tiến trình hoàn thiện dữ liệu M1–M2 — 02/11/2026

Tiếp tục yêu cầu hoàn thiện đồ án, không coi việc code/test chạy được là đã hoàn thành dữ liệu và bài nộp.

> **Trạng thái mới nhất:** theo yêu cầu người dùng, đã dừng tải nền để làm tiếp các phần offline trên tập nguồn cố định đã có. Chi tiết thay đổi tiếp theo ở mục 6; các mục crawl bên dưới là nhật ký những bước đã chạy trước khi dừng.

## Trạng thái xuất phát

- Snapshot metadata đã có 25.000 paper/36.089 version; nguồn local trước đợt này chỉ xác minh được 2 version.
- Parser đã chạy nguồn thật của 1 paper/2 version; chưa xử lý toàn corpus.
- Môi trường hiện tại là Windows, không có biến môi trường Colab; còn khoảng 30,2 GB đĩa và 2,2 GB RAM khả dụng tại thời điểm kiểm tra.
- Chưa có `S2_API_KEY`, HF/GitHub token trong biến môi trường. Token không bắt buộc cho tải nguồn arXiv hoặc đọc dataset public; thiếu token không phải lý do dừng các việc công khai làm được.
- Chưa commit/push các thay đổi; giữ nguyên lịch sử tác giả và gói bàn giao đã chuẩn bị.

## Đang thực hiện

1. Audit lại 5 shard metadata đầy đủ vào `data/audits/remediation_20261102.*` để tạo manifest source đúng đầu vào hiện tại.
2. Kiểm tra truy cập thực tế tới source arXiv, OAI, Atom và Semantic Scholar bằng request hữu hạn; ghi status/timeout/thời gian vào `build/remediation_20261102/remote_access.json`, không ghi token.
3. Khi endpoint nguồn hoạt động, chạy tải thật một nhóm version vào output sửa riêng rồi audit/parse lại; không coi probe mạng là đã tải đủ corpus.

## Điều kiện hoàn thành còn cần xác minh

- Crawl/audit nguồn và sửa metadata/references còn thiếu trên toàn bộ phạm vi; ghi các ca thực sự không có TeX hoặc API chưa lập chỉ mục bằng bằng chứng.
- Parser/validation/thống kê trên toàn corpus.
- Benchmark thật trong Google Colab CPU-only; môi trường Windows hiện tại không thay thế testbed này.
- Xuất bản code/book theo quy trình đóng góp nhóm và xác nhận bài nộp; không tự đổi tác giả hoặc push chung mọi phần dưới một người.

Các bước truy cập dịch vụ tài khoản chỉ được kết luận thiếu quyền khi đã kiểm tra công cụ/môi trường cụ thể; không yêu cầu người dùng gửi mật khẩu/token vào chat.

## Kết quả thực hiện

### 1. Đã dùng dữ liệu Hugging Face, kiểm tra lại toàn bộ file hiện tại

Đọc lại Hub ngày 02/11 bằng REST API sau khi SDK bị reset kết nối. Revision hiện tại vẫn là `36d23e5bc02fe31ac259ad9c710a116b68318e9e`, trùng bản đã tải về.

- Tổng **2.030 file / 598.103.339 byte**, gồm **2.022 Parquet**, 6 JSON, README và `.gitattributes`.
- Các Parquet là publications/references/course export và batch checkpoint. Không có tên bảng khác chứa nội dung source; working schema đã đọc không có cột TeX/full text.
- **Không có `.tex`, `.bib`, `.tar`, `.tar.gz`, `.zip` hoặc archive nguồn** trong tree của revision này.
- Dữ liệu metadata/references có sẵn đã tải ở `data/metadata_snapshot_20261101/shards/` và được dùng để merge/export/báo cáo; không tải lại hoặc crawl lại phần đã có này.
- Inventory đầy đủ có path/size trong `build/remediation_20261102/hf_inventory.json`. Nguồn LaTeX đã crawl trước đó có thể ở runtime/Drive khác, nhưng chưa xuất hiện trên revision Hub này; không khẳng định nó còn tồn tại ở nơi khác khi chưa có bằng chứng.

### 2. Truy cập mạng và dữ liệu thật

- Source arXiv, OAI arXivRaw và Atom trả HTTP 200 ở lần probe; Semantic Scholar trả HTTP 429, chưa có API key trong environment.
- Audit lại đủ 36.089 version; trước khi tải thêm có 2 version được xác minh local, 36.087 cần nguồn/bằng chứng.
- Đã tải thêm và xác minh nguồn cho **20 version**. Trong lô thử sau khi thêm resume: 15 version được dùng lại, 10 lần tải mới, 5 thành công và 5 lỗi timeout/kết nối ngắt. Đây là phép thử trên tập nhỏ, không báo đã đủ toàn corpus.
- OAI bổ sung **5 ngày version thật** cho shard 24120237: thiếu từ 760 xuống 755; một paper `2502.03270` vẫn timeout. Output ở `data/remediation_20261102/date_shards/24120237/`, cache và `.history.json` giữ bằng chứng.
- Đã chọn **12 paper / 20 version** có đủ nguồn local để thử parser tại `data/remediation_20261102/parser_input/`; parser output ở `data/remediation_20261102/parsed_local/`. Phần partial/error được giữ trong manifest, không tính là thành công.

### 3. Code tiếp tục sửa do chạy trên nhiều paper thật

| File | Sửa gì | Lý do |
|---|---|---|
| `src/crawler/source_downloader.py` | Thêm timeout/số lần thử cấu hình được; kiểm tra Content-Range; giữ phần tải dở khi lỗi mạng | Một số archive bị ngắt sau khoảng 1 MiB. Probe thực xác nhận server hỗ trợ Range, cần tiếp tục từ byte đúng thay vì tải lại từ đầu hoặc ghép sai byte |
| `src/crawler/retry_sources.py` | Dùng lại nguồn có manifest và file/size khớp; limit tính lượt tải mới; log JSONL và report theo run; kiểm tra đĩa; hỗ trợ file STOP | Không retry lại nguồn tốt, không để một paper timeout quá lâu hoặc để lần gián đoạn mất toàn bộ tiến độ |
| `src/parser/latex.py` | Nhận diện `subequations`/`empheq` là block math; chỉ đọc optional argument cho các command phù hợp | Paper `2502.03240` tạo self-edge sau normalization; biểu thức `\nu\in[0,1)` từng bị hiểu nhầm thành optional argument chưa đóng |
| `src/parser/normalize.py` | Giữ dấu phân biệt môi trường/list/item trong content cấu trúc | Hai tầng cấu trúc khác nhau không bị xóa wrapper rồi dedup thành cùng node parent–child |
| `src/parser/main.py` | Lỗi pipeline của một publication được ghi error trong manifest và không chặn paper tiếp theo | Chạy corpus phải giữ bằng chứng paper lỗi, không dừng cả nhóm ở một ca dữ liệu chưa hỗ trợ |
| `tests/test_source_retry_execution.py`, `tests/test_parser_pipeline.py` | Test resume/limit/disk/exception, Range đúng-sai, toán lồng, interval và cô lập publication lỗi | Kiểm tra các hành vi đã phát sinh trên dữ liệu thật |

### 4. Thông tin người dùng đã xác nhận

- Hiện **chưa dùng được Colab**; benchmark Windows không được đổi tên thành Colab benchmark.
- Nhóm **chưa có repository Jupyter Book/Pages**; source book/workflow đã chuẩn bị nhưng chưa publish.
- Chưa push code hoặc đổi lịch sử Git; gói bàn giao trước đó là snapshot cũ. Khi bàn giao lần tiếp theo cần tạo bộ mới chứa các sửa trong đợt này.

Chưa đánh dấu hoàn tất M1/M2. Việc có metadata trên Hub không thay thế corpus LaTeX cần cho M2, và việc bổ sung source một lô nhỏ không thay thế audit toàn bộ.

### 5. Kiểm tra cuối và lần chạy dài

- Bộ kiểm thử sau sửa đạt **112 passed** trong `.venv-report`.
- Parser chạy lại 12 paper/20 version: **13 success, 5 partial, 2 error**; **7.257 elements, 12.145 hierarchy edges, 195 BibTeX entries**, validation cấu trúc hợp lệ. Hai error còn lại thuộc paper có nhiều root cần chọn đúng compilation root; partial còn liên quan bibliography/TeX chưa đủ hoặc cú pháp chưa hỗ trợ. Không đổi các trạng thái này thành success để tăng tỷ lệ.
- Kiểm tra thêm refs trên Hub: chỉ có branch `main`, không có tag; `refs/convert/parquet` là nhánh chuyển đổi tự động. Chưa thấy một branch nguồn TeX riêng. Bằng chứng ở `build/remediation_20261102/hf_refs.json`.
- Bắt đầu worker nguồn chạy nền cho toàn manifest. Lệnh dùng `src.crawler.retry_sources --execute --read-timeout-sec 45 --download-attempts 4 --min-free-gb 4 --prefer-known-sources`. Worker chỉ xử lý nguồn thiếu/chưa xác minh và dùng lại manifest/file đã khớp; không lấy lại các bảng metadata từ Hub.
- PID và log launcher: `build/remediation_20261102/source_worker.json`, `source_worker.stdout.log`, `source_worker.stderr.log`. Tiến độ/checkpoint: `data/remediation_20261102/source_shards/retry_report.json` và `runs/*/events.jsonl`; kết quả phân vùng cập nhật riêng, không ghi đè snapshot metadata gốc.
- Có thể dừng sau version đang làm bằng cách tạo file `data/remediation_20261102/source_shards/STOP`; lần chạy tiếp bỏ qua các bản đã xác minh. Máy/runtime phải còn hoạt động thì worker mới tiếp tục; không cam kết tiến độ khi máy tắt hoặc process bị dừng.
- Chỉ riêng 36.087 request nguồn với pacing tối thiểu 3 giây đã cần khoảng **30 giờ**, chưa tính truyền dữ liệu/retry. Worker hoàn tất lượt thử không đồng nghĩa mọi version thành công; cần audit lại và xử lý danh sách lỗi còn lại trước khi chốt M1/M2.

Gói bàn giao v2 được tạo riêng để chứa các sửa mới; giữ nguyên ZIP snapshot đầu tiên và lịch sử Git. Chưa publish code, dataset hoặc Pages.

### 6. Hoàn thiện offline theo yêu cầu, để dữ liệu tải thêm làm sau

**Worker đã dừng:** `stopped_by_request`, 33 lượt tải mới trong run dài, 20 bản được dùng lại, 4 lượt lỗi. Đã tạo file STOP, giữ nguyên nguồn/checkpoint; không khởi động lại crawl/OAI/S2 trong đợt offline này. Tập kiểm tra parser cố định vẫn là 12 paper/20 version, không mở rộng theo dữ liệu vừa tải.

**Thay đổi và lý do:**

| File | Sửa gì | Lý do |
|---|---|---|
| `src/parser/main.py`, `configs/parser_roots.json`, `configs/README.md` | Root overrides theo paper/version, đưa lựa chọn vào fingerprint; kiểm tra dung lượng trước parse/validation | Chọn đúng root cho `2502.03238` sau khi đối chiếu title, không áp một filename cho cả corpus; giữ đầu ra cũ khi thiếu đĩa |
| `src/parser/storage.py` | Validator đọc batch, index SQLite tạm, kiểm tra từng graph/version; phát hiện root/cycles không dùng recursion | Không giữ full text tất cả paper trong RAM; vẫn kiểm tra được duplicate/FK xuyên shard và cây sâu |
| `src/parser/gather.py`, `latex.py` | Dừng ở end-document/endinput; không nuốt group sau font declarations; nhận diện display-math alias zero-argument đã khai báo | Không parse draft/tệp dư sau compilation path, không bỏ sót bibitems trong group có small/frenchspacing, không tách nhầm toán thành prose |
| `src/parser/bibliography.py` | Tìm bibliography từ compiled text và source map | Bỏ resource không còn được compile, giữ đúng đường dẫn .bib tương đối theo file include |
| `src/parser/normalize.py`, `deduplicate.py`, `hierarchy.py` | Canonical citation keys cả trong math, giữ danh tính container và hỗ trợ math aliases được khai báo | Không để cite cũ tồn tại trong công thức hoặc hai tầng cấu trúc bị gộp thành self-edge |
| `src/parser/statistics.py` | Tách recorded/parsed/success coverage, tổng hợp diagnostics, unresolved/conflicts và counts chưa đo | Coverage có manifest không đồng nghĩa parse success hoặc đủ nguồn; lỗi không được giả thành counts đo được |
| `src/parser/validation.py`, `pyproject.toml` | CLI `arxiv-validate-project` đối chiếu năm bảng và expected versions từ toàn M1; strict exit khi thiếu | Tập parser nhỏ hợp lệ về cấu trúc vẫn được báo chưa phủ đủ corpus |
| `src/crawler/validate_sources.py` | Validator course tables chỉ đọc các cột khóa sau khi kiểm tra schema | Giảm RAM khi kiểm tra toàn bộ M1 offline |
| `src/crawler/reporting.py`, `docs/06...08*.ipynb`, `tools/build_report.py` | Chỉ đọc run hoàn tất/validation đúng run; hiển thị partial/diagnostics/coverage; hash cả code/config | Không ghép số liệu cũ vào báo cáo mới hoặc coi build thành công là milestone hoàn tất |
| `tests/test_parser_configuration.py`, `test_parser_validation.py`, `test_parser_compilation_path.py`, `test_project_validation.py`, `test_parser_pipeline.py` | Test root/resume/disk, cross-shard/deep graph, active includes/bibitems/math aliases, citation trong math và báo cáo stale | Kiểm tra hành vi mới bằng fixture offline, không gọi API |

**Kết quả đã kiểm tra:**

- Full suite: **139 passed** trong môi trường riêng, không cần API hoặc tải thêm dữ liệu. Compile Python, `pip check` và whitespace check cho line endings Windows qua.
- Đã cài wheel và chạy parser từ CLI **ngoài repo** trên đúng 12 paper/20 version: **15 success, 5 partial, 0 error**; **7.690 elements, 12.924 edges, 272 BibTeX entries**. Hai version root mơ hồ đã xử lý bằng config có bằng chứng, không sửa nguồn. Năm partial còn được giữ đúng diagnostics; tổng 152 citation occurrences chưa resolve trong tập này.
- Cả năm bảng hợp lệ về cấu trúc/FK; checker đối chiếu full M1 cho biết chỉ có **20/36.089 version**, còn **36.069 version chưa nằm trong run M2 này**. `processing_complete=false`; strict mode trả đúng exit code 2. Đây không phải kết luận audit nguồn hay đồ án hoàn tất.
- CLI mới: `arxiv-validate-project`; JSON đối chiếu ở [project_validation.json](../data/remediation_20261102/parsed_offline/project_validation.json), gắn với run ID/code hash/manifest hash cụ thể để không ghép nhầm kết quả cũ.
- [Book offline mới](../build/book_offline_20261102/_build/html/index.html) đã build nghiêm ngặt `--all -W`; **8 chương thực thi**, không có code-cell error, hash source/config/inputs không đổi trong lúc build. [Kết quả kiểm tra book](../build/offline_20261102/book_validation.json) cũng xác nhận code hash của run package đã cài khớp source workspace.
- Ba chương M2 hiện riêng recorded/parsed/success coverage, diagnostics, unresolved keys, counts chưa đo, root/source-map examples và phạm vi validation toàn M1. Không trình bày số local như benchmark Colab.
- Gói bàn giao **v3** chứa code/config/tests mới, có phân công từng file; giữ nguyên các snapshot ZIP cũ. Tải dữ liệu vẫn dừng, chưa push Git hoặc publish Pages.

**Lệnh tái tạo phần offline:**

```powershell
.venv-report/Scripts/python.exe -m pytest -q
arxiv-parser --publications data/remediation_20261102/parser_input/publications.parquet --raw-dir data/raw --output-dir data/remediation_20261102/parsed_offline --root-overrides configs/parser_roots.json --resume
arxiv-validate-project --course-dir data/course_metadata_20261101 --parsed-dir data/remediation_20261102/parsed_offline --publications data/processed_metadata_20261101/publications.parquet --output data/remediation_20261102/parsed_offline/project_validation.json
.venv-report/Scripts/python.exe tools/build_report.py --output build/book_offline_20261102 --m1-dir data/processed_metadata_20261101 --m2-dir data/remediation_20261102/parsed_offline --build
```

Sau một run parser mới, cần tạo lại `project_validation.json` rồi mới build book. Phần dữ liệu toàn corpus và benchmark Colab vẫn để sau theo yêu cầu, không đánh dấu hoàn thành chỉ dựa vào các kiểm tra offline trên đây.

### 7. Chuẩn bị commit cục bộ theo author người dùng chỉ định

- Người dùng yêu cầu commit riêng theo tên từng thành viên, không thêm co-author. Dùng tên/email author đã xuất hiện trong lịch sử Git, giữ committer hiện tại `Quoc-Dat Nguyen`.
- Phạm vi là 64 file được phân công trong bộ v3. Chia thành 13 commit theo dependency: nền tảng storage/profiler/discovery → sources/normalize/references → runners → tài liệu/tests/báo cáo → cấu hình tích hợp. Phần tích hợp chung do Đạt nhận.
- Không đổi tác giả/ngày của commit cũ, không đổi branch và không push. Các file dữ liệu/scratch hoặc file cũ ngoài bộ v3 vẫn nằm ngoài phạm vi commit.
- Kế hoạch có danh sách file và hash tại `build/author_commits_20261102/plan.json`; kết quả thực thi từng commit được ghi riêng vào `execution.json`. Phân công author là metadata theo yêu cầu, không xác nhận thay cho việc từng thành viên review và đóng góp thực tế.
- `.git` hiện bị giới hạn quyền đọc trong cấu hình workspace; chỉ thực hiện bước ghi Git sau khi công cụ cấp quyền. Kiểm tra source runtime so với snapshot v3 đã qua 139 tests trước khi thực hiện.
