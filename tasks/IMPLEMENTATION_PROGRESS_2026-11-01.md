# Tiến trình sửa đồ án — 01/11/2026

Theo dõi thực hiện checklist trong `tasks/HF_DATASET_AUDIT_2026-10-30.md`.
Chỉ ghi hoàn thành khi đã có thay đổi và kết quả kiểm tra tương ứng.

> **Lưu ý dữ liệu — người dùng xác nhận ngày 01/11/2026:** nhóm **chưa có bộ nguồn `.tex/.bib` đầy đủ** của 25.000 paper. Metadata/checkpoint trên Hugging Face không thay thế corpus nguồn. Vì vậy chưa thể xác nhận tải nguồn hoàn tất, audit/parse toàn corpus hoặc benchmark toàn dải. Các phần triển khai công cụ và smoke test local được ghi riêng; không đánh dấu hoàn thành dữ liệu thật dựa vào test fixture.

## Phạm vi và trạng thái ban đầu

- Đang sửa mã nguồn, công cụ xử lý dữ liệu, kiểm thử và hướng dẫn cho M1–M2.
- Trước khi bắt đầu đã có thay đổi ở `src/crawler/source_downloader.py`; sẽ giữ và sửa tiếp trên nội dung hiện tại.
- Đã có downloader, reference scraper, storage, CLI, profiler, merger và năm notebook M1; chưa thấy package parser M2 trong workspace.
- Các số thiếu/lỗi trong audit ngày 30/10 là mốc lịch sử, chưa phải số liệu sau sửa.
- Chạy crawl thật, benchmark Colab, xuất bản repo/Pages và nộp Moodle cần môi trường/dữ liệu/quyền truy cập tương ứng; kết quả chưa thực hiện sẽ được ghi rõ, không thay bằng số giả.

## Nhật ký thực hiện

### 1. Khảo sát và chuẩn bị

**Đã làm:** đọc checklist, cấu hình package/CI và trạng thái Git; bắt đầu đối chiếu code/tests/dữ liệu local.

**Tệp tạo:** `tasks/IMPLEMENTATION_PROGRESS_2026-11-01.md`.

**Lý do:** giữ lịch sử tệp/hàm sửa, mục đích, kiểm tra và phần còn cần chạy trên dữ liệu thật trong suốt quá trình thực hiện.

**Kiểm tra:** chưa thay đổi hành vi crawler tại bước này.

### 2. Sửa luồng M1 và cách giữ kết quả từng bước

**Đã sửa:**

- `src/crawler/main.py`: checkpoint journal v2, resume theo từng version/bước references, giữ publication khi tải nguồn lỗi, upsert kết quả và tính lại bộ đếm; lưu quan sát references và số đo từng run. Đưa export vào vùng đo, không nuốt lỗi export.
- `src/crawler/records.py` (mới): hợp nhất publication theo version và reference theo định danh, tránh mất dữ liệu khi retry/gộp.
- `src/crawler/observations.py` (mới): sidecar Parquet cho status/provenance/counts của truy vấn references; hai bảng chuẩn sáu cột không đổi.
- `src/crawler/storage.py`: giữ `not_found`/`pending`, không bỏ null trước khi tổng hợp status, không gán ngày latest cho revision chưa biết.
- `src/crawler/profiler.py`: tổng RSS chính/con, trung bình theo thời gian, peak disk có mẫu theo thời điểm và operation checkpoint; xuất samples gốc.
- `src/crawler/source_downloader.py`: giữ thay đổi có sẵn; chuyển staging vào thư mục được theo dõi, kiểm tra đuôi TeX/Bib không phân biệt hoa/thường, không suy ra PDF-only từ việc archive không chứa TeX; thêm mốc đo disk trước khi dọn tạm.
- `discovery.py`, `reference_scraper.py`, `id_range.py` và downloader: dùng import tương đối để package cài đặt hoạt động ngoài thư mục repo; discovery dùng HTTPS; S2 `not_indexed` giữ expected count chưa biết.

**Lý do:** checkpoint cũ chỉ nhớ ID bài và có thể bỏ qua nguồn lỗi; status references bị mất; bộ đếm cộng dồn có thể đếm trùng khi chạy lại; export và peak tạm chưa được đo đúng.

**Kiểm tra nền:** trước khi sửa, `python -m pytest -q` đạt **71 passed**. Đang chạy lại và bổ sung test cho hành vi mới; chưa đánh dấu các mục hoàn tất tại bước này.

### 3. Bổ sung công cụ sửa dữ liệu và pipeline M2

**Tệp mới cho M1:**

- `src/crawler/version_history.py`: đọc arXivRaw hoặc snapshot JSONL, cache lịch sử ngày, bổ sung đúng version và xuất bằng chứng; mặc định không gọi mạng.
- `src/crawler/validate_sources.py`: đối chiếu metadata với corpus, xuất audit Parquet và manifest retry; phân biệt PDF-only có bằng chứng với thư mục rỗng chưa xác minh.
- `src/crawler/retry_sources.py`: retry đúng manifest, lưu shard sửa vào thư mục riêng, giữ các version khác và không dùng stats cũ làm số đo sửa dữ liệu.
- `src/crawler/enrich_references.py`: truy vấn lại citing paper/enrich metadata có cache, giữ riêng provenance cạnh trích dẫn và provenance metadata; yêu cầu `--execute` khi gọi mạng.
- `src/crawler/merge_shards.py`: hợp nhất versions/fields thay vì chọn bỏ một bản; bổ sung chế độ thiếu stats có khai báo; tách tỷ lệ TeX success khỏi partial/lỗi và xuất sidecar references.

**Tệp mới cho M2:**

- `src/parser/latex.py`, `gather.py`: scanner ngoặc cân bằng, comment/verbatim, compilation root/include bắc cầu, source map và diagnostics.
- `src/parser/hierarchy.py`: cây occurrence theo version, sentence/math/figure/table/list, giữ acknowledgements/appendices, loại bibliography khỏi prose.
- `src/parser/normalize.py`: cleanup bảo toàn nội dung và chuẩn hóa math/cite.
- `src/parser/bibliography.py`: đọc BibTeX/bibitem, hợp nhất trường và citation mapping theo từng version.
- `src/parser/deduplicate.py`: content store dùng chung qua version, giữ occurrence và cạnh từng version.
- `src/parser/storage.py`, `statistics.py`, `main.py`, `__init__.py`: ba bảng Parquet phẳng, validation, manifest/coverage/dedup counts, checkpoint theo hash input/code/output và CLI parser có profiler.

**Lý do:** workspace chưa có parser M2; cần xử lý được nhiều version và giữ bằng chứng trước/sau thay vì chỉ tạo schema rỗng hoặc thống kê từ bảng cuối.

**Kiểm tra đã chạy:** 8 test parser mới đã qua, gồm nhiều tệp/comment/include lặp/vòng include, sentence boundaries, bibitem, field union/key collision, shared element qua version, bảng Parquet, resume và thay input. Các kiểm tra này dùng fixture offline, không phải benchmark toàn corpus.

**Kiểm tra M1 sau đổi hành vi:** nhóm CLI/storage hiện có đã đạt 63 test ở lần chạy trung gian; đã cập nhật fixture cũ để tạo nguồn TeX thực và kiểm tra metadata paper vẫn được giữ khi tải nguồn lỗi. Đang bổ sung test hồi quy cho các lỗi mới sửa và chạy toàn bộ lại sau khi tích hợp.

### 4. Kiểm thử hồi quy và chạy trên dữ liệu thật local

**Tệp kiểm thử:** `tests/test_crawler_repairs.py`, `tests/test_parser_pipeline.py`; cập nhật fixture trong `tests/test_cli_and_profiling.py` cho hành vi giữ publication khi nguồn lỗi.

**Kết quả đã có:**

- 13 test hồi quy M1 qua: retry status lỗi, resume không tải lại version tốt, retry references riêng, export lỗi làm run thất bại, dry-run tách dữ liệu, ngày không bị dựng giả, OAI identity, peak disk không đếm trùng và tar/PDF/gzip-PDF/no-TeX có evidence.
- Parser đã chạy trên `data/test_single/publications.parquet` với nguồn ở `data/raw`: **1 publication / 2 version**, kết quả ở `data/parsed_smoke_20261101/` gồm **668 elements, 1.225 hierarchy edges và 51 BibTeX entries**; validation hợp lệ, hai version ghi parse success.
- Lần chạy thật phát hiện vòng hierarchy do môi trường formatting `sloppypar` bị xem là parent của section mới. Đã sửa `src/parser/hierarchy.py` để wrapper layout không làm sai cấp section/prose, và thêm fixture hồi quy.

**Giới hạn số đo:** đây là smoke test Windows trên dữ liệu local, không phải benchmark Colab hoặc bằng chứng đã xử lý 25.000 paper.

### 5. Xác minh phạm vi corpus và chuẩn bị báo cáo

**Xác nhận từ người dùng:** chưa có corpus TeX/Bib đầy đủ; ghi việc cần thu thập nguồn trước khi chạy toàn đồ án, không tự coi metadata đã đủ cho M2.

**Audit đã chạy:** `validate_sources` đọc toàn bộ metadata cache của 5 shard: **36.089 version**, xác minh được **2 version có TeX local**, còn **36.087 version cần kiểm tra/nguồn bổ sung**. Phân loại gồm 32.643 success chưa đối chiếu được nguồn/size, 913 pending/error và 2.531 empty chưa có bằng chứng local. Đây là kết quả kiểm tra **bản local**, không khẳng định tất cả các version còn lại lỗi trên arXiv. Artifacts: `data/audits/hf_cache_20261101.parquet`, `.json` và `.retry.jsonl`.

**Kiểm thử tại bước 5:** **96 passed**, một warning dependency từ Python global hiện tại; môi trường report được cài riêng trong `.venv-report`. Kết quả cuối cập nhật tại bước 6–7 bên dưới.

**Các tệp báo cáo/đóng gói đã sửa:**

- `docs/01...05*.ipynb`: bỏ fallback crawl/mock khi build, dùng dữ liệu đã lưu và sidecar mới; nêu phạm vi/mẫu số và thiếu benchmark Colab.
- `docs/06_parsing_and_hierarchy.ipynb`, `07_standardization_and_deduplication.ipynb`, `08_parser_benchmark.ipynb`: các chương M2 thực thi bảng/biểu đồ từ manifest/working/stats thật.
- `src/crawler/reporting.py`: reader dùng chung, từ chối mock, giữ giá trị thiếu và chỉ lấy một ít working examples để không nạp toàn corpus vào RAM.
- `tools/build_report.py`: chuẩn bị source cho repo book riêng, force-execute notebooks, manifest hash và workflow Pages đọc inputs thật được pin.
- `README.md`, `pyproject.toml`, `requirements.txt`, `.github/workflows/ci.yml`, `.gitignore`: lệnh chạy thật M1/M2/repair/report, entry points, report/dev extras, CI chạy test offline và dữ liệu đầu ra không đưa vào Git.
- `colab_crawler.ipynb`: giữ thêm status part/sidecar và lịch sử run khi sync, tương thích checkpoint mới.

**Lý do:** có notebook hoặc schema không đủ chứng minh báo cáo/dữ liệu đã hoàn thành; cần build bằng inputs thật, phân biệt smoke/local với benchmark chính thức và giữ khả năng tái lập.

### 6. Kiểm tra hoàn thiện và sửa lỗi phát hiện khi chạy thật

**Các tệp tiếp tục sửa và lý do:**

| Tệp | Thay đổi | Lý do |
|---|---|---|
| `src/crawler/discovery.py` | Atom error entry hoặc HTML HTTP 200 trở thành lỗi truy vấn, giữ `failed_ids`; pacing request arXiv tối thiểu 3 giây | Không được xác nhận ID không tồn tại khi API trả trang lỗi |
| `src/crawler/source_downloader.py` | Thay thư mục version qua backup/staging và khôi phục nếu install thất bại; giữ nguồn TeX cũ khi response mới không hợp lệ | Tránh mất nguồn đã có trong lúc retry; giữ staging trong phạm vi đo disk |
| `src/crawler/rate_limiter.py` | Dùng monotonic clock và khóa giữa các thread, từ chối interval âm/NaN/inf | Đồng hồ hệ thống đổi giờ hoặc request đồng thời không làm sai pacing |
| `src/crawler/reference_scraper.py` | Hiểu `Retry-After` dạng HTTP-date và không rút ngắn thời gian server yêu cầu | Tránh tiếp tục truy vấn trước thời điểm được phép |
| `src/crawler/merge_shards.py` | Tách stats smoke/resume không bao phủ shard vào `unmatched_run_stats`; thêm `stats_coverage`, giữ tài nguyên chưa biết là null | Stats 2 bài trên Hub không đại diện cho shard 5.000 bài hoặc toàn corpus |
| `src/crawler/records.py` | Không dùng S2/DOI alias để gộp hai target có arXiv ID khác nhau; lưu conflict khi merge | Đối chiếu toàn snapshot phát hiện 9 cặp khóa reference bị mất bởi quy tắc alias cũ; phải giữ cả hai để xác minh |
| `tools/build_report.py` | Giữ `_build` trong exclude patterns, force-execute và `-W`, dừng khi notebook lỗi; kiểm tra hash input trước/sau build | Bản build lại từng đọc notebook đã execute dưới `_build`, tạo warning ngoài toctree; không được xuất book khi code cell lỗi |
| `src/crawler/reporting.py`, `docs/04_schema_and_data_quality.ipynb` | Provenance chưa biết được in rõ; status terminal được gọi là reported thay vì verified | Metadata chưa chứng minh nguồn local đã được kiểm toán |
| `tasks/TASK_*.md`, `README.md`, `.gitignore` | Cập nhật 5 phân công đã có code, sửa allowlist/mốc dữ liệu mẫu, hướng dẫn UTF-8 Windows và loại backup/artifact khỏi Git | Bỏ mô tả skeleton/TODO cũ, thống nhất cách dùng source hiện tại và giữ repo code sạch |
| `tests/test_crawler_repairs.py` | Thêm kiểm tra Atom error/HTML, rollback nguồn, monotonic pacing, child RSS, server Retry-After, stats lệch scope và alias xung đột | Các lỗi này ảnh hưởng dữ liệu hoặc tính đúng đắn của số đo, cần test hành vi đầu ra |

**Kết quả đã xác minh:**

- `python -X utf8 -m pytest -q`: **104 passed** sau lần sửa alias; Python global còn một dependency warning của `requests`. Kiểm tra thêm trong `.venv-report` đủ dependencies cũng đạt **104 passed**, không có warning này; `pip check` báo không có dependency hỏng.
- `python -X utf8 scratch/check_colab_notebook.py`: **11 kiểm tra offline qua**, gồm restore/checkpoint, snapshot/upload ordering, validation export, runner/interrupt, timer sync và ngăn upload output cũ. Không chạy crawl hoặc upload thật.
- Build nghiêm ngặt 8 notebook với `jupyter-book ... --all -W` đã thành công trên inputs thật local nhỏ. Lần build cuối dùng **toàn metadata M1**, M2 vẫn chỉ có smoke 1 paper, cũng thành công; HTML ở `build/book_source/_build/html/index.html`. Chưa publish Pages.
- Wheel `arxiv-harvester 0.2.0` đã build/cài; 6 CLI `--help` chạy được từ `C:/Users/Mr.Dat09/Documents/python`, ngoài thư mục repo. Không dùng import `src.*` để che lỗi package đã cài.
- Thử bổ sung lịch sử qua OAI cho `2502.03243`: timeout sau 45 giây, **0 ngày được bổ sung**. Artifact `data/repaired_dates/24120237/publications.history.json` ghi rõ lỗi; số ngày thiếu của shard vẫn 760. Không đánh dấu mục 04 xong.
- Retry nguồn: mới lập plan 10 version; enrich references: mới lập plan 1 paper. **Chưa execute bulk** hai luồng này.

**Điều chỉnh checklist:** `tasks/HF_DATASET_AUDIT_2026-10-30.md` chỉ giữ các mục còn việc **04–12 và 19–24**. Các mục code **01–03, 13–18** chuyển bằng chứng sang nhật ký này; điều đó không đồng nghĩa parser đã được kiểm chứng trên 25.000 bài. Mỗi mục còn lại có ghi phần đã triển khai và bước chạy/xác minh tiếp theo.

### 7. Kết quả đối chiếu toàn metadata và bản bàn giao local

**Input:** tải bản public của dataset `nquocdat06/arxiv-harvester-data`, pin revision `36d23e5bc02fe31ac259ad9c710a116b68318e9e`. Bản sao local ở `data/metadata_snapshot_20261101/shards/`, gồm hai bảng working của đủ 5 thành viên; mỗi người 5.000 publication. Đây là metadata/references, **không có corpus nguồn TeX/Bib đầy đủ**.

**Đã chạy:** merge bằng code mới, export course schema, kiểm tra unique keys/FK, so tập publication/version/reference keys với toàn bộ shard gốc. Lần đối chiếu đầu phát hiện 9 cặp reference bị gộp do alias chung nhưng arXiv ID khác; đã sửa code, thêm test và chạy lại. Kết quả cuối:

| Kiểm tra | Kết quả |
|---|---:|
| Publication trước/sau merge | 25.000 / 25.000 |
| Version keys trước/sau merge | 36.089 / 36.089 |
| Working reference rows trước/sau merge | 838.902 / 836.257 |
| Working reference rows trùng đã gộp | 2.645 |
| Course reference keys trước/sau merge-export | 284.243 / 284.243 |
| Duplicate course keys / orphan citing papers | 0 / 0 |
| Xung đột alias được giữ riêng để xác minh | 9 |
| Version còn thiếu ngày | 3.770 |
| Course reference thiếu title / authors | 151 / 51 |
| Course reference thiếu date / S2 ID | 135.750 / 135.285 |

**Artifacts:**

- [Working metadata sau merge](../data/processed_metadata_20261101/): `publications.parquet`, `references.parquet`, `crawl_status.parquet`, `overall_stats.json` và `metadata_validation.json`.
- [Course export và validation](../data/course_metadata_20261101/metadata_validation.json): `papers.parquet`, `references.parquet` đúng 6+6 cột. JSON ghi source revision, counts, thiếu trường, hashes và kiểm tra bảo toàn keys.
- [9 xung đột định danh](../data/processed_metadata_20261101/reference_identity_conflicts.json): giữ riêng các arXiv target khác nhau, cần xác minh bằng nguồn chính thức trước khi chốt dữ liệu.
- [HTML Jupyter Book](../build/book_source/_build/html/index.html) và [manifest build](../build/book_source/report_build_manifest.json): M1 đọc 25.000 paper/36.089 version/836.257 working references; M2 đọc output thật của 1 paper/2 version. Mọi cell code trong 8 chương đã thực thi, không có error output, hashes inputs/source khớp sau build.
- [Kiểm tra notebooks](../build/final_notebook_validation_20261101.json): 8 notebook report và notebook Colab đều hợp lệ theo nbformat; code cells compile được sau xử lý IPython magic.
- [Môi trường đã kiểm chứng](../build/validated_environment_20261101.txt): `pip freeze` UTF-8 của môi trường riêng; Python 3.12 trên Windows. Đây là snapshot môi trường local, không phải cấu hình/số đo Colab.
- [Parser từ package đã cài](../build/installed_parser_smoke_20261101/stats.json): chạy từ ngoài repo bằng `arxiv-parser`; **668 elements / 1.225 edges / 51 BibTeX**, hai version success và validation hợp lệ. Runtime khoảng **1,091 giây**, chỉ là smoke local.

**Stats chưa đủ:** 4 shard không có `stats.json`; stats duy nhất trên Hub là run 2 bài, không bao phủ shard 5.000 bài. Vì vậy `stats_coverage` là **0/5 shard dùng được**; runtime, RAM và average time toàn nhóm giữ null. Tệp run nhỏ vẫn giữ trong `unmatched_run_stats`, không bị xóa và không dùng thay benchmark. Các tỷ lệ nguồn trong merged metadata chỉ là **reported status**, đối chiếu nguồn local vẫn theo audit ở bước 5.

**Lệnh đã dùng để tái tạo:**

```powershell
python -X utf8 -m src.crawler.merge_shards --shards-dir data/metadata_snapshot_20261101/shards --output-dir data/processed_metadata_20261101 --allow-missing-stats
python -X utf8 scratch/implementation_20261101/validate_full_metadata.py
.venv-report/Scripts/python.exe -m pytest -q
.venv-report/Scripts/python.exe -m pip check
.venv-report/Scripts/python.exe tools/build_report.py --output build/book_source --m1-dir data/processed_metadata_20261101 --m2-dir data/parsed_smoke_20261101 --build
.venv-report/Scripts/python.exe scratch/implementation_20261101/check_notebooks.py
```

Các script kiểm tra/bản backup tạm trong `scratch/implementation_20261101/` và artifact `data/`, `build/` được bỏ qua bởi Git; giữ tại máy để đối chiếu. Chức năng chính dùng CLI/package ở `src/`, không phụ thuộc thư mục scratch. `git -c core.whitespace=cr-at-eol diff --check` qua với line endings Windows hiện tại.

**Việc tiếp theo theo thứ tự:** bổ sung lịch sử ngày → thu thập corpus/audit/retry nguồn → enrich và xác minh 9 xung đột references → merge/export bản sau repair → benchmark M1 trên Colab → cập nhật/publish/xác nhận nộp M1 → parser toàn corpus/thống kê/benchmark Colab → cập nhật cùng book và xác nhận nộp M2. Chi tiết từng mục còn lại ở checklist chung. Chưa push code, upload dữ liệu, publish Pages hoặc thao tác Moodle trong lần sửa này.

## Bảng theo dõi checklist

| Mục | Trạng thái | Bằng chứng / việc tiếp theo |
|---|---|---|
| 01–03: resume, reference status, profiler | Đã sửa code và kiểm thử | Test resume theo version/reference, export failure, delta status, child RSS và peak disk |
| 04: lịch sử version | Có tool, chưa bổ sung đủ dữ liệu | OAI smoke timeout; còn thiếu 3.770 ngày trên toàn snapshot |
| 05–07: audit/retry/enrich | Có tool và audit local/plan | Chưa có corpus đầy đủ; cần thu thập nguồn, chạy retry/enrich thật và audit lại |
| 08: merge/export | Đã kiểm tra bản metadata trước repair | Bảo toàn 25.000 paper, 36.089 version, 284.243 course reference keys; còn xác minh 9 xung đột và xuất lại sau repair |
| 09–12: benchmark, báo cáo, nộp M1 | Có notebook/Colab/book source | Chưa benchmark Colab CPU-only, publish Pages hoặc xác nhận nộp Moodle |
| 13–18: parser, chuẩn hóa/dedup, schema M2 | Đã triển khai và smoke thật | 1 paper / 2 version; 668 elements, 1.225 edges, 51 BibTeX entries; validation hợp lệ |
| 19–20: chạy và thống kê toàn corpus M2 | Có orchestrator/checkpoint/statistics | Cần corpus trước khi chạy toàn bộ; chưa có thống kê đại diện toàn nhóm |
| 21–24: benchmark, báo cáo, nộp M2 | Có CLI/report chapters/workflow | Chưa có số đo Colab parser, Pages public hoặc xác nhận Moodle |
