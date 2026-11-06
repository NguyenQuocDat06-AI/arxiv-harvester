# arXiv Harvester — Milestone 1 và 2

Thu thập mọi version của paper trong dải ID được giao, giữ nguồn `.tex/.bib`, lấy references và parse thành dữ liệu phân cấp đã chuẩn hóa/khử trùng.

- Đặc tả: [M1 — Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/), [M2 — Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/).
- Dataset đang dùng: [nquocdat06/arxiv-harvester-data](https://huggingface.co/datasets/nquocdat06/arxiv-harvester-data).
- Báo cáo M1–M2: [Jupyter Book](https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/) trong [repository báo cáo riêng](https://github.com/NguyenQuocDat06-AI/arxiv-harvester-book).
- Đóng góp thành viên: [nhánh gốc, commit và cách đối chiếu](CONTRIBUTIONS.md). Nhánh chính và mặc định của repository source là `main`; `develop` dùng để tích hợp thay đổi.
- [Checklist và hướng dẫn sửa](tasks/HF_DATASET_AUDIT_2026-10-30.md), [nhật ký thực hiện và bằng chứng](tasks/IMPLEMENTATION_PROGRESS_2026-11-01.md).

M1–M2 nộp link code và Jupyter Book. Dữ liệu làm việc giữ để xử lý tiếp; việc xuất bản/nộp dữ liệu cuối thuộc M3. Bản báo cáo dùng số liệu tổng hợp được chuẩn bị bằng `tools/build_public_submission_book.py`; bộ dựng Book từ working tables vẫn có trong `tools/build_report.py`.

Bản nộp tiến độ 06/11 dùng snapshot Drive 73 paper/119 version. Audit nguồn xác minh 118 version; parser có 81 success, 31 partial, 5 empty và 2 lỗi. Năm bảng hợp lệ về cấu trúc trên snapshot; chưa xử lý đủ toàn nhóm và chưa có benchmark M2 Colab CPU-only. [Link và hướng dẫn nộp](tasks/NOP_M1_M2_2026-11-06.md).

Book có tám chương chính và hai phụ lục, gồm công thức thống kê, ví dụ parser thực thi từ source ghim, phân tích lỗi và lệnh tái lập. Nội dung chi tiết được sinh từ `tools/submission_report_content.py` qua bộ dựng báo cáo.

## 1. Cài đặt và kiểm tra

Dùng Python 3.10 trở lên trong môi trường riêng. Cài từ root repo:

```bash
python -m pip install -e ".[report]"
python -m compileall -q src tools
arxiv-harvester --help
arxiv-parser --help
```

`.[report]` pin Jupyter Book 1.x cho cấu hình `_config.yml`/`_toc.yml` của bộ báo cáo này. Crawler chỉ cần `pip install -e .`; Colab không cần cài phần report. Key Semantic Scholar lấy từ biến môi trường `S2_API_KEY`, hoặc `.env` ở gốc repo khi chưa có biến môi trường. Notebook Colab nhận key qua ô nhập trực tiếp ở mục 2; log từng bước được hiển thị và lưu tại `RUN_DIR/crawler.log`.

Trên Windows khi redirect log, dùng `python -X utf8 -m ...` hoặc đặt `PYTHONUTF8=1` để giữ tiếng Việt trong output.

Notebook Colab có ba chế độ: `smoke` chạy 5 bài trong thư mục riêng, `repair` bổ sung nguồn/references của checkpoint cũ, `full` tiếp tục toàn dải và xử lý lại phần thiếu. Mặc định lấy source GitHub nhánh `develop` và cập nhật bằng fast-forward; source cũ thiếu runtime mới sẽ bị từ chối. Nếu cần dùng ZIP, tạo bằng `python tools/prepare_colab_bundle.py`, chọn `SOURCE_MODE="bundle"` và dùng notebook đã ghim cùng SHA-256; không đưa `.env` hoặc corpus vào gói.

CLI hỗ trợ `--resume --existing-only` để sửa các bài đã có mà không khám phá ID mới. Checkpoint legacy được sao lưu trước khi ghi tiếp; source tốt được giữ lại. Trạng thái `not_indexed`/`bib_fallback` được lưu rõ để báo cáo độ phủ, không đổi thành lỗi API hoặc tự nhận là kết quả S2 đầy đủ.

S2 mặc định dùng `--s2-batch-size 5`: một POST cho nhóm bài cần references, không truy vấn lại bài đã hoàn tất. Có thể tăng lên 25 sau khi chạy ổn định. Kết quả được gắn theo ID bài nguồn và đối chiếu `referenceCount`; entry null được xác minh riêng, entry thiếu được lấy thêm trang. Phản hồi quá lớn được tách thành nhóm nhỏ. Đặt `--s2-batch-size 1` để gọi từng bài.

Pacing S2 dùng `--s2-rate-limit-sec 5`, `--s2-max-attempts 3` và `--s2-cooldown-sec 60`, độc lập với arXiv. Ngay lần 429 đầu tiên, cooldown ít nhất 60 giây; nếu tiếp tục 429 thì tăng 120/240/... tới 900 giây, có jitter. `Retry-After` dài hơn luôn được giữ. Batch thất bại không tạo hàng loạt GET; `api_error`/`partial` vẫn cần retry.

Notebook mặc định `S2_MAX_ATTEMPTS=1` để giảm chờ khi S2 lỗi; có thể tăng lại trong cấu hình. Với một lần thử, cooldown S2 lưu từ lượt trước được hoãn ngay thay vì giữ bước tải nguồn để chờ. References còn lỗi giữ trạng thái `api_error`, không được tự tính là hoàn tất.

`--rate-state-dir` lưu cooldown theo provider/key qua các lượt chạy; mặc định ở `<output-dir>/_request_state`. Colab dùng chung `DATA_BASE_ROOT/network_state` cho smoke/repair/full. Giữ thư mục này khi restart. `--max-rate-wait-sec 180` giới hạn chờ inline; lâu hơn thì kết thúc với `paused_rate_limit`, giữ checkpoint và ghi thời gian cần chờ vào stats. Chạy lại cùng lệnh/đường dẫn sau cooldown; cooldown đang còn không bị xóa khi mở tiến trình mới.

Khóa OS chặn tiến trình trùng dùng cùng network state trong một máy/runtime và tự nhả khi tiến trình thoát hoặc bị kill. File trạng thái có thể lưu trên Drive; khóa đặt ở ổ cục bộ để không phụ thuộc locking của FUSE. Khóa này không điều phối các máy/Colab VM độc lập: chỉ chạy một runtime với một S2 key và không ghi đồng thời vào cùng shard. Điều kiện phía server/IP hoặc chương trình khác dùng key vẫn có thể gây 429.

`runs/<run_id>/http_diagnostics.jsonl` ghi response 429: Retry-After/rate-limit/request-id, phần đầu thông báo lỗi và fingerprint key. Key/token được che; không ghi request headers có xác thực. Chỉ gửi bản đã che key khi cần đối chiếu lỗi. Các CLI retry nguồn, enrich references và reconcile dates đều nhận `--rate-state-dir`; dùng cùng thư mục nếu cần cùng chính sách nghỉ.

`--batch-size` điều khiển lô discovery; `--s2-batch-size` giới hạn số paper mỗi POST; `--checkpoint-every-papers 1` lưu từng paper độc lập với hai lô API. Stats có `s2_requests` và `by_method` ghi số GET/POST thực. Chi phí request dùng chung được ghi đúng một lần ở paper đầu nhóm; sidecar có `request_group`/`request_group_size` để đối chiếu. Thời gian batch được phân bổ vào paper metrics, không nhân thời gian request cho mọi paper.

Metadata dùng `--rate-limit-sec 3`; tải full-text dùng `--source-rate-limit-sec 1`, mỗi lần một kết nối. Hai bước giữ chung cooldown arXiv, kể cả sau restart. Công cụ `arxiv-retry-sources` cũng nhận `--source-rate-limit-sec`. Cấu hình này dựa trên [hướng dẫn full-text harvesting](https://info.arxiv.org/help/bulk_data.html#play-nice); nhịp API metadata vẫn tối thiểu ba giây.

Tải nguồn có `--source-download-attempts 3`, `--source-read-timeout-sec 90` và `--source-max-seconds 180`. Ngân sách được kiểm tra giữa request/chunk; một lần đọc hoặc cooldown có thể kết thúc muộn hơn. File mới tải bằng một GET đầy đủ; resume bắt đầu ở đoạn 1 MiB, tăng 4 rồi 8 MiB khi đoạn trước hoàn tất trong 10 giây. Lỗi hoặc đoạn chậm làm giảm kích thước. HTTP 429 dừng lượt và giữ `.part`. Content-Range/Content-Length được kiểm tra trước khi công bố archive; đoạn thành công không tiêu hao số lần retry. ETA chưa gồm retry hoặc thời gian Colab bị ngắt.

Colab mặc định `USE_LOCAL_WORKSPACE=True`: raw, giải nén, shard và log chạy trên `/content`; `network_state` tiếp tục lưu trên Drive. `BACKUP_EVERY_PAPERS=10` tương ứng CLI `--backup-dir <Drive>/backups/<MSSV> --backup-every-papers 10`. Mỗi lô đóng gói các nguồn thay đổi và part mới, kiểm tra archive/checksum ở Drive rồi công bố `HEAD.json` sau cùng. Sao lưu lỗi làm crawler dừng; checkpoint Drive đã xác minh trước đó vẫn dùng được. Không có thao tác xóa corpus cũ trên Drive.

Notebook mặc định `RUN_MODE="full"`. Khi có checkpoint, full tự thêm `--resume`, kiểm tra lại phần thiếu rồi tiếp tục ID mới trên toàn dải. Smoke chưa đạt với code hiện tại hoặc dữ liệu cũ còn thiếu được thông báo trong preflight, không bắt buộc chạy riêng smoke/repair trước full. `repair` chỉ sửa paper đã có; `smoke` là lựa chọn kiểm tra nhỏ. Kiểm tra đúng MSSV/dải ID, file checkpoint và validation cuối vẫn áp dụng; chỉ validation đạt mới cập nhật course export hoặc upload bảng cuối.

Full mặc định `AUTO_RESUME_ARXIV=True`, truyền `--auto-resume-rate-limit` xuống CLI. Khi arXiv trả 429, crawler ghi checkpoint/backup rồi chờ đúng deadline, báo tiến độ mỗi 15 giây và tự tiếp tục trong cùng tiến trình. Paper vừa bị giới hạn được đưa cuối hàng đợi sau cooldown. Có thể bấm Stop khi đang chờ; không reset cooldown hoặc tăng kết nối. CLI không có flag này vẫn kết thúc với `paused_rate_limit` như trước.

Stats có `auto_rate_limit_resumes`, `auto_rate_limit_wait_sec` và `pipeline_passes`; metrics từng paper được giữ qua các lần tiếp tục. `processed_this_run` đếm ID duy nhất, `paper_attempts_this_run` đếm cả lần thử lại. Chờ dịch vụ không đảm bảo xong trước thời hạn. Nếu đã duyệt hết dải nhưng S2 còn lỗi, run vẫn báo phần thiếu và validation chưa đạt.

Sau khi VM bị xóa, cell kiểm tra checkpoint tự khôi phục archive đã commit vào workspace trống. Khi chưa có backup, cell này sao chép và đối chiếu dữ liệu ở `raw/<MSSV>` và `shards/<MSSV>` cũ sang ổ cục bộ. Phần chưa commit sau lô gần nhất cần xử lý lại nếu mất VM. Giữ cả chuỗi archive, các file commit, `HEAD.json` và `network_state`; chỉ một runtime ghi vào một backup. Không sửa thủ công thư mục Drive cũ rồi mong bản backup tự cập nhật.

Log/run metadata được sao lưu vào `logs/<MSSV>/<run_id>` sau khi dừng và sau validation. Hai bảng course export chỉ cập nhật khi validation đạt. Dữ liệu mới nằm trong archive ở `backups/<MSSV>`, thư mục raw/shard Drive cũ giữ làm đầu vào lịch sử. Profiler ghi thời gian sao lưu dữ liệu trong pha `drive_backup`; `child_wall_sec` của notebook bao gồm cả bước lưu stats/đầu ra cuối. Chưa có benchmark tốc độ Colab cho thay đổi này. [Nhật ký sửa và kiểm chứng](tasks/DOWNLOAD_SPEED_PROGRESS_2026-11-04.md).

| MSSV | Thành viên | Dải ID |
|---|---|---|
| 24120282 | Nguyễn Quốc Đạt | `2412.18848` → `2501.02641` |
| 24120237 | Nguyễn Đình Tuấn | `2502.03235` → `2502.08234` |
| 24120438 | Trần Nguyên Tân | `2407.12839` → `2407.17838` |
| 24120470 | Dương Phan Minh Trí | `2406.17938` → `2407.02838` |
| 24120474 | Trịnh Vỹ Triết | `2406.12938` → `2406.17937` |

## 2. Chạy Milestone 1

Ví dụ dải của 24120237:

```bash
arxiv-harvester --member-id 24120237 --start-month 2025-02 --start-id 3235 --end-month 2025-02 --end-id 8234 --raw-dir data/raw --output-dir data/shards/24120237 --export-course
```

Thêm `--resume` để chạy tiếp. Smoke test dùng `--max-papers 5` và **output directory riêng**. `--dry-run` chỉ discovery, ghi vào nhánh `_dry_run` và gắn nhãn, không trộn vào kết quả crawl thật. Ở repo root vẫn hỗ trợ `python -m src.crawler.main ...`.

Các đầu ra:

```text
data/raw/
  sources/                         # archive tạm
  unzipped/<arxiv_id>/<version>/    # chỉ .tex/.bib
  manifests/<versioned_id>.json    # bằng chứng nguồn/PDF-only/no-TeX
data/shards/<MSSV>/
  publications.parquet
  references.parquet
  crawl_status.parquet             # status/counts/provenance truy vấn theo paper
  _checkpoint/                    # batch journal, không commit Git
  runs/<run_id>/
    stats.json
    paper_metrics.jsonl
    resource_samples.jsonl
  stats.json                       # bản tiện đọc của run mới nhất
  course_export/
    papers.parquet
    references.parquet
```

Resume kiểm tra từng version và bước references; nguồn lỗi không làm mất publication. `succeeded` là paper có các nguồn đã xác nhận và references API hoàn tất/rỗng được xác nhận; `source_succeeded` đếm paper có mọi version TeX success. PDF-only/no-TeX không bị tính thành TeX success. Fallback/partial/API error vẫn được giữ và báo còn việc; `completed_with_errors` không có nghĩa corpus đã đủ.

References working giữ cả tài liệu không có arXiv ID. Khi xuất course table mới lọc arXiv-keyed rows. Ngày lịch sử chưa biết giữ null; không gán ngày latest cho version giữa. Trường ngày S2 trong dữ liệu cũ có thể là publication date, cần provenance/xác minh trước khi diễn giải là ngày nộp arXiv.

## 3. Audit và sửa dữ liệu đã thu thập

Các công cụ mạng mặc định lập kế hoạch/đọc cache; cần cờ rõ ràng khi muốn gọi API. Chọn **output mới** để giữ dữ liệu đầu vào.

### Kiểm tra corpus và tạo danh sách retry

```bash
arxiv-audit-sources --publications data/shards --raw-dir data/raw --output data/audits/sources.parquet
arxiv-retry-sources --manifest data/audits/sources.retry.jsonl --output-dir data/repaired_sources --limit 10
```

Sau khi xem kế hoạch, thêm `--execute` để tải bù đúng version. Retry có manifest và vẫn dùng pacing tối thiểu ba giây; không dùng thư mục rỗng làm bằng chứng PDF-only. Chạy lại vào cùng output repair sẽ giữ các sửa trước đó. Stats gốc không bị sao chép thành benchmark của lần sửa.

Retry xác minh manifest/file/size trước khi dùng lại nguồn, giới hạn bằng `--limit` số lượt tải mới. Có thể đặt `--read-timeout-sec 45 --download-attempts 4 --min-free-gb 4`; log JSONL và report lưu theo run. Tạo file `STOP` trong output repair để dừng sau version đang làm; giữ file này khi muốn hoãn tải và chỉ bỏ nó khi chủ động chạy tiếp. Lỗi mạng giữ phần archive đã tải để tiếp tục bằng HTTP Range đã kiểm tra offset.

### Bổ sung ngày revision

```bash
arxiv-reconcile-dates --publications data/shards/24120237/publications.parquet --output data/repaired_dates/24120237/publications.parquet --cache-dir data/cache/version_history
```

Có snapshot JSONL thì thêm `--snapshot <duong_dan_snapshot>`. Muốn truy vấn arXivRaw cho phần thiếu thì thêm `--fetch-missing --limit 10` trước khi chạy phạm vi lớn. File `.history.json` đi cùng output ghi ngày đã bổ sung, nguồn và lỗi; không coi OAI datestamp là ngày submission.

### Truy vấn lại và enrich references

```bash
arxiv-enrich-references --shard-dir data/shards/24120237 --output-dir data/enriched_references/24120237 --raw-dir data/raw --limit 10
```

Thêm `--execute` để truy vấn citing papers; thêm `--enrich-targets` nếu muốn bổ sung metadata mục tiêu có cache. Enrich S2 ID cho một tài liệu fallback không tự xác nhận cạnh trích dẫn do API trả về. Tool giữ edge source và field provenance riêng, không tự dựng ngày nộp từ publication year/date.

### Gộp và xuất chuẩn

```bash
python -m crawler.merge_shards --shards-dir data/shards --output-dir data/processed
python -c "from crawler.storage import export_to_course_spec; export_to_course_spec('data/processed','data/course_export')"
```

Nếu thiếu `stats.json` nhưng hai bảng working có thật, thêm `--allow-missing-stats` và kiểm tra `shards_without_stats` trong báo cáo. Runtime/RAM chưa biết là null, không phải 0. Không dùng `--skip-corrupted` để bỏ dữ liệu mà vẫn tuyên bố đủ dải ID. Khi chuyển shard đã sửa vào bộ dữ liệu chung, kiểm tra provenance/version/status rồi chạy lại validation.

Stats của smoke/resume chỉ xử lý một phần shard được giữ trong `unmatched_run_stats`, tách khỏi metrics toàn shard. `stats_coverage` cho biết bao nhiêu shard có stats dùng được; các tỷ lệ nguồn từ metadata vẫn cần đối chiếu corpus bằng `validate_sources`.

## 4. Chạy trên Google Colab

Mở [colab_crawler.ipynb](colab_crawler.ipynb), chọn CPU và `CURRENT_MEMBER`; chạy tuần tự các cell. Mặc định dữ liệu nguồn và checkpoint cùng nằm trên Google Drive. Smoke test dùng thư mục riêng. Nhập `S2_API_KEY` trực tiếp ở mục 2; `HF_KEY` chỉ đọc qua Secrets khi bật restore/upload Hub.

Nếu smoke kết thúc `completed_with_errors`, giữ `RUN_MODE="smoke"` và chạy lại cùng thư mục để bổ sung đúng phần thiếu; không tăng số bài hoặc xóa checkpoint. Chạy cell validation sau khi crawler kết thúc. Full/repair dùng lô 25, smoke gộp các bài trong mẫu; mặc định checkpoint vẫn ghi sau từng paper. Sau khi đổi chế độ/thành viên, chạy lại các cell cấu hình và Drive/đường dẫn; notebook chặn dùng đường dẫn của cấu hình cũ.

Để chạy source mới, đưa code lên nhánh/commit GitHub được chọn trong notebook. Checkpoint trên Hub có thể chỉ chứa metadata; notebook kiểm tra nguồn tương ứng trước khi resume. Sidecar trạng thái và run metrics được giữ khi đồng bộ các phiên bản source mới.

Benchmark chính thức phải chạy trên Colab CPU-only. Số đo trên Windows/local và smoke test không được trình bày như benchmark toàn dải. `runs/` giữ từng lần thực thi, bao gồm phạm vi đã làm và phần dùng lại; không chia thời gian run cuối cho số paper cộng dồn.

## 5. Milestone 2 — parser

```bash
arxiv-parser --publications data/processed/publications.parquet --raw-dir data/raw --output-dir data/parsed
```

Ở repo root có thể dùng `python -m src.parser.main ...`. Input cũng có thể là thư mục shards; raw có thể là `raw/unzipped` chung hoặc `raw/<MSSV>/unzipped` như Colab. Thêm `--limit 5` vào **output riêng** cho smoke test. Root mơ hồ cần kiểm tra; `--preferred-root <relative.tex>` chỉ phù hợp phạm vi dùng cùng tên root. Với toàn corpus, cấu hình riêng từng paper/version:

```bash
arxiv-parser --publications data/processed/publications.parquet --raw-dir data/raw --output-dir data/parsed --root-overrides configs/parser_roots.json
```

Mapping có thể là `{"2502.03238": {"v1": "main.tex", "v2": "revised.tex"}}`. File [cấu hình có sẵn](configs/README.md) ghi root đã kiểm tra với metadata. Override được đưa vào fingerprint; thay root của một paper chỉ làm paper đó phải parse lại khi code/input khác vẫn khớp. Nguồn M1 giữ nguyên.

```bash
arxiv-parser --publications data/processed/publications.parquet --raw-dir data/raw --output-dir data/parsed --resume
```

Pipeline: compilation root/include → occurrence hierarchy → normalize/canonical cites → exact content dedup → Parquet. Có hỗ trợ BibTeX/bibitem, field union và mapping key theo version. Trường hợp thiếu nguồn, include động không resolve hoặc cú pháp chưa hỗ trợ được ghi lỗi/partial; parser không phải TeX engine đầy đủ.

Gathering dừng tại `\end{document}`/`\endinput`; font declarations không được che các `\bibitem`. Các macro zero-argument khai báo rõ `\begin`/`\end` của display math được nhận diện; citation keys được đổi cả trong inline/block math. Macro động có tham số vẫn cần kiểm tra diagnostics.

```text
data/parsed/
  elements/*.parquet
  hierarchy/*.parquet
  bibtex/*.parquet
  working/*.json                  # occurrence/source maps, keys, conflicts, before counts
  checkpoint.json                 # hash input + code/config + các output
  manifest.json                   # tình trạng mọi version, gồm empty/lỗi
  runs/<run_id>/stats.json
  runs/<run_id>/resource_samples.jsonl
  stats.json
```

Resume chỉ dùng cache khi input/code/config và hashes đầu ra còn khớp. Nguồn không có TeX được xác nhận tạo empty record và không có elements giả; mất source không bị đổi thành empty hợp lệ. Số liệu M2 gồm coverage theo paper/version, counts trước/sau dedup và unresolved citations.

Parser dừng trước paper mới hoặc validation nếu còn dưới `--min-free-gb` (mặc định 4 GiB), giữ checkpoint/đầu ra trước đó. Validation đọc Parquet theo batch, dùng index tạm trên đĩa và kiểm tra một graph/version mỗi lần; không nạp full text toàn corpus vào RAM. Có kiểm tra duplicate keys xuyên shard, node/parent, root và cycles.

Kiểm tra liên kết cả năm bảng và coverage so với **toàn bộ** working M1:

```bash
arxiv-validate-project --course-dir data/course_export --parsed-dir data/parsed --publications data/processed/publications.parquet --output data/parsed/project_validation.json
```

`structural_valid` cho biết schema/khóa/liên kết hợp lệ; `processing_complete` chỉ xác nhận phủ đủ version với trạng thái success/empty, không thay thế audit nguồn, benchmark hoặc xác nhận nộp bài. Thêm `--require-full` để nhận exit code 2 nếu còn thiếu/partial/error; cấu trúc sai trả code 1. Chạy lại validation sau mỗi lần parser tạo run mới để báo cáo không dùng kết quả kiểm tra cũ.

## 6. Build Jupyter Book M1–M2

Tám notebook ở `docs/` chỉ đọc inputs đã lưu, không gọi API, không tự sinh mock hoặc crawl khi compile. Hai biến môi trường dùng khi chạy notebook là `ARXIV_M1_DATA_DIR` (working tables) và `ARXIV_M2_DATA_DIR` (parser output).

```bash
python tools/build_report.py --output build/book_source --m1-dir data/processed --m2-dir data/parsed --build
```

HTML nằm ở `build/book_source/_build/html/index.html`. Khi inputs là tập nhỏ, các trang ghi rõ phạm vi nhỏ và thiếu benchmark Colab; không ngoại suy kết quả. Inputs thiếu hoặc là mock làm build thất bại.

Book cũng từ chối ghép manifest với run parser thất bại hoặc validation thuộc run trước. Manifest build lưu hash source/config và inputs, kiểm tra chúng không đổi trong lúc compile. Các chương M2 hiển thị phần còn thiếu/partial, diagnostics và coverage so với M1 nếu có `project_validation.json`.

`build/book_source/` là source đã chuẩn bị cho **repo báo cáo riêng**, có workflow Pages và README triển khai. Sau khi nhóm xuất bản dữ liệu/metrics thật, đặt biến repo Hub ID, full revision SHA và prefixes inputs cho workflow. Cần kiểm tra link Pages public và nộp hai link source/book trên Moodle; công cụ build không tự publish hoặc nộp bài.

## 7. Kiểm tra và bằng chứng

```bash
python -m compileall -q src tools
```

CI kiểm tra cú pháp, cấu trúc notebook, cài đặt package và các lệnh CLI. Các kết quả chạy thật, phạm vi chưa thực hiện và từng tệp đã sửa được cập nhật ở [nhật ký tiến trình](tasks/IMPLEMENTATION_PROGRESS_2026-11-01.md).

Việc tiếp theo cho 5 thành viên và thứ tự chạy dữ liệu ở [bản phân công cập nhật 04/11](tasks/TEAM_HANDOFF_2026-11-02.md); tình trạng tích hợp ở [tiến trình 04/11](tasks/IMPLEMENTATION_PROGRESS_2026-11-04.md).
