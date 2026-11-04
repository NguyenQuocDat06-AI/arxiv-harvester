# KẾ HOẠCH SỬA CHỮA VÀ HOÀN THIỆN `arxiv-harvester` — MILESTONE 1 (HCMUS)

> **Trạng thái tài liệu:** Bản kế hoạch kỹ thuật để giao cho coding agent và chia việc theo thành viên; **không phải** thông báo rằng các thay đổi đã được áp dụng.
>
> **Ngày đối chiếu:** 25/10/2026 (Asia/Ho_Chi_Minh).
>
> **Repository:** <https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/develop>
>
> **Commit nền đã đọc:** `ec5649b36fb565cf8c2cf2f8b98c6c2f4acea66d`.
>
> **Đặc tả chính thức:** <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/>.
>
> **Giới hạn bằng chứng:** Đây là review tĩnh mã nguồn, notebook và CI trên GitHub. Chưa có lần benchmark Colab CPU-only end-to-end được kiểm chứng, chưa chạy `pytest` trực tiếp trên mã nguồn đã clone và chưa xác thực corpus thực tế ở máy thành viên. Mọi tiêu chí “đạt” bên dưới chỉ được công nhận sau khi chạy kiểm thử và kiểm toán dữ liệu thật.

---

## 0. MỤC TIÊU, PHẠM VI VÀ QUY TẮC CHO CODING AGENT

### 0.1. Mục tiêu bắt buộc của Milestone 1

1. Giải quyết **toàn bộ ID thuộc các dải được giao**: paper tồn tại, paper không tồn tại, lỗi API, trạng thái chưa xác minh phải được phân biệt rõ.
2. Với mỗi paper tồn tại, xác định **số version thực có**, tải **từng `v1`, `v2`, ... `vN`** từ endpoint được đề chỉ định: `https://export.arxiv.org/src/{base_id}vN`.
3. **Chỉ trích xuất `.tex` và `.bib`** từ mỗi source archive vào corpus chính; không ghi ảnh hoặc binary trung gian vào corpus. Không chỉnh sửa nội dung TeX hoặc các lệnh `\\includegraphics`.
4. **PDF-only / no-TeX không bị xóa khỏi metadata corpus**: phiên bản có manifest và trạng thái, thư mục source rỗng là hợp lệ.
5. Thu thập references từ **Semantic Scholar theo publication**, lưu toàn bộ references cục bộ, kể cả không có `ref_arxiv_id`; chỉ khi xuất bảng chuẩn của môn mới lọc reference không có arXiv ID.
6. Tạo hai bảng chuẩn theo đề: `papers` có **6 cột** và `references` có **6 cột**. Giữ working schema phong phú hơn trong nội bộ nếu hữu ích.
7. Báo cáo bằng **Jupyter Book công khai ở repo riêng**, biểu đồ/bảng được tạo bằng code trong build; cung cấp dữ liệu thống kê thật, phương pháp và giới hạn.
8. Benchmark trên **Google Colab CPU-only**: end-to-end wall time, average time/paper, discovery time, peak/average RAM, peak/final disk, tỷ lệ crawl thành công và chất lượng references.
9. Source repository dùng chung, **public khi nộp**, README hướng dẫn tái lập đầy đủ; không commit corpus dữ liệu thật hoặc file binary vào Git.

**Không bắt buộc:** tự cào toàn arXiv qua OAI-PMH hoặc Kaggle. Theo đề, các công cụ này là phương án tham khảo cho discovery quy mô kho; nhiệm vụ chấm là dải arXiv ID được giao. Không dành tài nguyên cho OAI-PMH full harvest trước khi hoàn thiện `/src/` từng version.

### 0.2. Quy tắc thực thi cho agent

- **Bắt đầu bằng so sánh commit:** `git rev-parse HEAD`. Nếu nhánh đã thay đổi sau commit nền, đọc diff và điều chỉnh kế hoạch, không ghi đè code mới.
- **Sửa tối thiểu nhưng đúng:** ưu tiên giữ public interface khi có thể; nếu đổi signature phải cập nhật tất cả call sites, tests, notebooks, README cùng PR.
- **Không giả dữ liệu:** không gán `updated` thành ngày của `v2`, `v3` khi không biết lịch sử thực; không coi HTTP error là `not_found`; không tăng `success` khi tải lỗi; không dùng mock benchmark để báo cáo.
- **Không crawl mạng trong unit tests:** dùng fixture Atom/XML, JSON, tar/gz và fake session, test offline deterministically; live smoke test riêng, có throttle, phạm vi nhỏ.
- **Bảo toàn dữ liệu:** không sửa `.tex/.bib` để xóa figure command; không xóa nguồn các version trước; không gộp mất các version trong merger.
- **An toàn tải:** chỉ dùng arXiv mirror `export.arxiv.org`, pacing ít nhất 3 giây/request và một kết nối đồng thời như đề hướng dẫn; tôn trọng `429`, `Retry-After`, không proxy/rotate để vượt giới hạn.
- **Mỗi PR phải có:** lý do, file/hàm sửa, test mới, kết quả lệnh test và ảnh hưởng đến schema/output.
- **Không tự ý chuyển repo sang public hoặc push dữ liệu thật** trong quá trình áp dụng bản kế hoạch; đó là bước nộp bài cần sự đồng thuận của nhóm.

### 0.3. Danh sách P0/P1/P2

| Mức | Ticket | Tác động | Chủ sở hữu gợi ý |
|---|---|---|---|
| **P0** | ARX-01: Version metadata và ngày revision đúng | Đúng dữ liệu theo đề | 24120282 |
| **P0** | ARX-02: `/src/{id}vN` + chỉ `.tex`, `.bib` | Full-version corpus | 24120237 |
| **P0** | ARX-03: Điều phối từng version và bảo toàn publication khi lỗi | End-to-end correctness | 24120474 |
| **P0** | ARX-04: Nối status/size từng version vào working Parquet | Dữ liệu và metric đúng | 24120470 + 24120474 |
| **P0** | ARX-05: Reference failure isolation, provenance, coverage | Không mất paper/references | 24120438 + 24120474 |
| **P1** | ARX-06: Merge/validate corpus, chống mock | Resulted Data | 24120470 |
| **P1** | ARX-07: Profiler benchmark chuẩn Colab | Scraper Performance | 24120474 |
| **P1** | ARX-08: 5 notebook + repo Jupyter Book riêng | Report | Cả nhóm |
| **P1** | ARX-09: Test toàn luồng và CI pytest | Runnable, auditable code | Cả nhóm |
| **P2** | ARX-10: README, dependencies, package layout, cleanup | Reproducibility | Trưởng nhóm |

---

## 1. CẤU TRÚC DỮ LIỆU VÀ INVARIANTS PHẢI THỐNG NHẤT TRƯỚC KHI CODE

### 1.1. Working corpus đề nghị

```text
data/
  raw/
    sources/                        # file archive tạm, có thể xóa sau xử lý
    unzipped/
      2412.18848/
        v1/
          main.tex
          refs.bib
        v2/
          main.tex
          refs.bib
      2501.02641/
        v1/                        # hợp lệ khi rỗng đối với PDF-only
  manifests/
    2412.18848.json               # trạng thái theo base_id và version
  shards/
    24120282/
      publications.parquet
      references.parquet
      stats.json
      _checkpoint/                 # private, không commit
    ...
  processed/
    publications.parquet           # working schema 16 cột hoặc mở rộng có chủ đích
    references.parquet             # working schema 11 cột hoặc mở rộng có chủ đích
    overall_stats.json
  course_export/
    papers.parquet                 # 6 cột đúng đề
    references.parquet             # 6 cột đúng đề
```

**Quy tắc:** Base paper có đúng một publication record. Bên trong record là `versions: list[struct]`, **mỗi version khác nhau có source folder/status riêng**. Với bản PDF-only cần manifest `status=pdf_only`, folder source rỗng; không ép có `.tex`.

Ví dụ manifest (dữ liệu minh họa, không phải kết quả crawl thật):

```json
{
  "arxiv_id": "2401.00001",
  "discovery_status": "found",
  "latest_version": 2,
  "versions": [
    {"version": "v1", "created": null, "source_status": "success", "source_dir": "data/raw/unzipped/2401.00001/v1", "size_before_bytes": 10000, "size_after_bytes": 6000},
    {"version": "v2", "created": null, "source_status": "pdf_only", "source_dir": "data/raw/unzipped/2401.00001/v2", "size_before_bytes": 0, "size_after_bytes": 0}
  ],
  "references_status": "success",
  "references_provenance": "semantic_scholar",
  "fetched_at_utc": null
}
```

`created=null` là chính xác hơn một ngày suy đoán. Khi lấy được các ngày version từ nguồn tin đáng tin cậy, cập nhật **riêng từng version** và lưu provenance.

### 1.2. Bảng trạng thái; không trộn ba khái niệm khác nhau

- **Discovery:** `found`, `confirmed_not_found`, `api_error`, `pending`.
- **Source mỗi version:** `success`, `pdf_only`, `no_latex`, `not_found`, `error`, `pending`.
- **References cấp paper:** `success`, `empty_confirmed`, `partial`, `not_indexed`, `api_error`, `pending`.
- **Pipeline result:** `complete`, `partial`, `failed` — suy ra từ các trạng thái trên, không hardcode theo một bước.

Không coi `pdf_only` là source LaTeX thành công, nhưng vẫn coi là **version đã được kiểm tra** và giữ publication. Không dùng `not_found` khi một HTTP request lỗi/timeout. Nếu S2 thiếu bài, publication vẫn hợp lệ.

### 1.3. Bất biến để validation

```text
Discovered base paper -> đúng 1 publication row.
Number of versions discovered (N) -> N version records v1..vN.
For every version -> có source status cụ thể, không bị ghi đè bởi version khác.
For source_status == success -> chỉ có .tex/.bib trong source folder.
For source_status == pdf_only/no_latex -> publication vẫn còn.
All working references -> arxiv_id trỏ tới base paper; ref_arxiv_id có thể null.
Course papers -> đúng 6 cột, arxiv_id non-null và unique.
Course references -> đúng 6 cột, arxiv_id/ref_arxiv_id non-null và pair unique theo quy tắc xuất.
No mock figures/metrics in submission report; mọi kết luận dẫn ra run_id và dữ liệu thật.
```

---

## 2. HƯỚNG DẪN SỬA TỪNG FILE/HÀM (THEO THỨ TỰ TRIỂN KHAI)

### ARX-01 — `src/crawler/discovery.py`: sửa metadata discovery và version history [P0]

**Đang có:** `API_URL`, `_parse_entry(entry)`, `discover_metadata_batch(arxiv_ids, rate_limit_sec=3.0, max_retries=3)`. `_parse_entry` đọc hậu tố `vN`, dựng `v1..vN`, nhưng `created` của tất cả version sau `v1` bị gán cùng `updated`. `discover_metadata_batch` có thể hết retry rồi trả danh sách rỗng khiến caller tưởng bài không tồn tại.

**Sửa cụ thể:**

1. Trong `_parse_entry`:
   - Giữ `base_id`, `max_version`, metadata Atom và `published`, `updated` cấp paper.
   - Sinh `versions=[{"version":"v1",...}, ..., {"version":"vN",...}]` mà **không gán `updated` cho tất cả v2..vN**. Có thể đặt `created` của `v1` từ `published`, `created` của `vN` từ `updated` **chỉ nếu ngữ nghĩa nguồn được xác minh**; các phiên bản trung gian để `None` cho đến khi truy xuất được lịch sử chính xác.
   - Thêm `version_timestamp_provenance` hoặc manifest provenance (`atom_published`, `atom_updated`, `verified_history`, `unknown`) thay vì tạo thông tin giả.
   - Phân biệt base ID mới và hậu tố `vN`, chuẩn hóa và kiểm tra dữ liệu sai định dạng.
2. Trong `discover_metadata_batch`:
   - Bắt buộc phân biệt `not_found` **được xác minh** với `429/503`, connection error, timeout, malformed XML, batch partial response.
   - Đề nghị thay return type bằng `DiscoveryBatchResult(records_by_id, missing_confirmed, failed_ids, error_info)` **hoặc** giữ `list[dict]` và **raise typed exception** khi batch không hoàn thành. Nếu đổi interface, cập nhật `main.py`, tests, notebook 01 cùng PR.
   - Áp dụng retry/bounded backoff; tôn trọng `Retry-After`; khi hết lượt retry không `print` rồi im lặng trả `[]`.
   - Không “lọc lỗi” bằng so khớp `"error" in title.lower()` đơn thuần vì paper hợp lệ có thể có chữ error trong tên. Phải kiểm tra cấu trúc entry lỗi/API.
   - Ghi counters cho số requested/found/missing/retried/failed, latency, API status; ghi theo batch và paper.
3. Nếu cần mốc revision chuẩn: thêm `fetch_version_history(base_id)` **chỉ khi xác định được API/nguồn có lịch sử từng version thật**, có test fixtures thực. OAI-PMH tại thời điểm đề cập có endpoint `https://oaipmh.arxiv.org/oai`, **không dùng** `export.arxiv.org/oai2` đã retired. OAI full harvest **không phải** điều kiện bắt buộc của milestone.

**Pseudocode khuyến nghị:**

```python
@dataclass
class DiscoveryBatchResult:
    records_by_id: dict[str, dict]
    missing_confirmed: set[str]
    failed_ids: dict[str, str]

# Mấu chốt: latest update không phải ngày của mọi revision.
versions = [
    {"version": f"v{k}", "created": None}
    for k in range(1, latest_version + 1)
]
# Chỉ enrich ngày từ trường/nguồn có bằng chứng trực tiếp.
```

**Vì sao:** đề yêu cầu version coverage và `revised_dates` đáng tin; nếu gán nhầm ngày sẽ sai bảng `papers` dù tải đủ file.

**Test phải có (`tests/test_discovery.py` — tạo mới):**

- XML `base_id v1`, `v2`, `v4`; assert số version chính xác.
- `v4` có `published != updated`: assert các ngày trung gian **không bị tự gán updated**.
- ID hợp lệ có chữ “error” trong title không bị bỏ.
- HTTP `429` -> retry và cuối cùng raise/failed, **không** trả confirmed missing.
- malformed XML, batch response thiếu ID, HTTP 200 có API error-entry, các trường nullable.
- Batch 100 ID, pacing >=3s (mock clock) và một kết nối arXiv tại một thời điểm.

**Definition of Done:** chạy test mới pass; không còn inference timestamp không có bằng chứng; main phân biệt missing thật với network failure.

### ARX-01b — `src/crawler/id_range.py`: sửa kiểm tra dải ID [P0/P1]

**Đang có:** `normalize_yymm()`, `find_last_id_of_month(yymm, start_seq=1)`, `iter_assigned_arxiv_ids(...)`. `find_last_id_of_month` dùng binary search nhưng dựa vào list rỗng từ discovery làm “không tồn tại”; đồng thời lấy `last_found=start_seq` dù chưa kiểm chứng. Generator hiện xử lý cùng tháng hoặc đúng mô hình “tháng đầu + tháng cuối” mà không có vòng lặp cho mọi tháng ở giữa.

**Sửa cụ thể:**

1. `find_last_id_of_month`: chỉ dùng kết quả kiểm tra ID **đã xác minh**; lỗi API -> retry hoặc dừng để resume; không giảm upper bound vì timeout. Kiểm tra `start_seq` thực sự tồn tại trước khi dùng làm last_found.
2. Dùng lịch sử/cấu hình `last_id` nếu nguồn xác thực sẵn có và cache theo tháng để giảm gọi API; nếu binary search thì đảm bảo domain phù hợp, **không** tự tăng đến seq trên 5 chữ số.
3. `iter_assigned_arxiv_ids`: kiểm tra thứ tự tháng và ID (kể cả dùng trực tiếp không qua CLI), xử lý khoảng qua nhiều tháng đúng cách **hoặc** từ chối rõ ràng trường hợp không hỗ trợ. Với 5 dải hiện tại chỉ cần chắc chắn hai tháng được xử lý đúng.
4. Đảm bảo định dạng `YYMM.NNNNN`, không phát sinh `00000`; trường hợp unknown/missing phải được audit.

**Tests (`tests/test_id_range.py` — tạo mới):** same-month boundaries, Dec->Jan, June->July, month/year invalid, binary-search boundary, transient error khi probe, sequence gap, range nhiều hơn 2 tháng (support or explicit rejection).

**Vì sao:** lỗi kiểm tra bài cuối tháng có thể tạo ra ID thừa hoặc làm mất ID được giao ngay từ đầu, lan sang sai coverage.

### ARX-02 — `src/crawler/source_downloader.py`: tải đúng `/src/` theo version, extract allowlist [P0]

**Hàm liên quan có thật:** `_validate_arxiv_id`, `_download_and_clean_source_impl`, `download_and_clean_source`, `_download_stream`, `_select_request_url`, `_safe_extract_tar`, `_extract_single_gz`, `prune_images_and_binaries`, `get_dir_size_bytes`, `_rate_limited_get`.

**A. Endpoint chính thức, dải version**

- Trong `_download_and_clean_source_impl`, thay `https://export.arxiv.org/e-print/{arxiv_id}` thành **`https://export.arxiv.org/src/{arxiv_id}`**, với `arxiv_id` phải là versioned ID (`2401.00001v1`, `...v2`).
- Trong `_validate_arxiv_id`, trích rõ `base_id` và `version` hoặc tạo helper `_split_version_id()`. Ở pipeline strict mode, đòi hỏi suffix `vN` để tránh vô tình tải latest version thay cho từng version.
- Tổ chức output `unzipped/<base_id>/<version>/` và temp archive có suffix version. **Không** overwrite `v1` khi xử lý `v2`.
- `download_and_clean_source` tiếp tục trả về per-version `status`, `size_before_bytes`, `size_after_bytes`, `elapsed_sec`, và thêm `version_id`, `source_dir`, HTTP status/attempts nếu có. Status = `success` chỉ khi đã xác thực output thực.

**B. Chỉ lấy `.tex`, `.bib` ngay tại bước giải nén**

- Sửa `_safe_extract_tar(tar, dest_dir, ...)`: giữ cơ chế chặn absolute path, `..`, drive letter, symlink/hardlink, max members và max bytes; **chỉ ghi file có suffix `.tex` hoặc `.bib`**. Không extract rồi xóa images, `.bbl`, `.sty`, `.cls`, `.pdf`, `.png`, `.eps`, ... vào corpus.
- `max_total_bytes` và số members nên kiểm tra cả archive index; giữ giới hạn output bytes cho file được phép và chống decompression bomb. Không giải nén đường dẫn không an toàn kể cả nếu extension hợp lệ.
- `_extract_single_gz`: chỉ lưu thành `.tex` nếu nhận diện được nguồn TeX hợp lệ; không giữ compressed blob sau bước extract.
- `prune_images_and_binaries`: chuyển thành hàm **defense-in-depth/validation** cho corpus; không phụ thuộc vào bước prune để đạt yêu cầu allowlist. Tránh sửa nội dung `.tex`.
- Chức năng fallback `.bbl` hiện có trong reference scraper: nếu muốn dùng `.bbl`, hãy đọc tạm từ archive vào **temporary staging / memory** rồi parse; không đưa `.bbl` vào persistent working corpus vì đề chỉ yêu cầu giữ `.tex/.bib`. Đơn giản hơn: ở M1 ưu tiên `.bib`, fallback `.bbl` chỉ khi có thiết kế tách biệt và test.

**C. Rate limit và host**

- Bỏ đường failover từ `export.arxiv.org` sang `arxiv.org` trong `_select_request_url`/`_activate_cdn_failover`; đề yêu cầu **không** dùng main host để crawl tự động.
- Giữ retry có chờ `Retry-After`, exponential backoff, timeout, stream chunk và HTTP Range chỉ khi nguồn xác nhận hỗ trợ an toàn. Không sử dụng nhiều kết nối song song đến arXiv.
- Thiết kế limiter chung cho cả metadata discovery và source requests trong cùng process (`src/crawler/rate_limiter.py` — mới, nếu cần), bảo đảm tối thiểu 3 giây **giữa các request** và concurrency = 1. Đừng mặc định rằng limiter riêng mỗi module đã giới hạn tổng lưu lượng.

**D. Các trạng thái đặc biệt**

- Với PDF-only, trả `status=pdf_only`, đảm bảo tạo thư mục version rỗng + manifest trạng thái; **không xóa** publication hoặc phiên bản khỏi cấu trúc.
- Với `no_latex`: nếu archive hợp lệ nhưng không có `.tex` và có `.bib`, vẫn giữ `.bib` và báo status phù hợp; không xóa toàn bộ source folder mà không phản ánh nguyên nhân.
- Với lỗi mạng, 429 hết retries hoặc HTML response bất thường: trả `error`/raise typed error, có reason; không coi là `not_found` trừ HTTP 404 rõ ràng và được xác nhận.
- Đo `size_before_bytes` từ *logical uncompressed sizes* của file nguồn archive hoặc dung lượng được kiểm toán **trước bước loại figure**, và `size_after_bytes` là tổng bytes của `.tex/.bib` giữ lại. **Document rõ hai số đo để không gây nhầm “archive compressed size” với “uncompressed size”.**

**Pseudocode bắt buộc (không phải patch đầy đủ):**

```python
version_id = f"{base_id}v{version_no}"
url = f"https://export.arxiv.org/src/{version_id}"
dst_dir = raw_unzipped / base_id / f"v{version_no}"

for member in archive.getmembers():
    check_safe_member_path_and_type(member)
    if member.isfile() and Path(member.name).suffix.lower() in {".tex", ".bib"}:
        extract_one_member_securely(member, dst_dir)
# PDF-only -> tạo dst_dir rỗng + trạng thái, không bỏ bài báo.
```

**Tests (`tests/test_source_downloader.py` — tạo mới):**

- Tạo archive chứa `.tex`, `.bib`, `.bbl`, `.sty`, `.png`, `.eps`, `.pdf`; assert corpus cuối chỉ có `.tex`, `.bib` và bytes giữ nguyên (hash).
- Tar traversal (`../`, `/abs`, drive, symlink/hardlink), duplicate names, zip bomb-like size, malformed gzip.
- `v1` và `v2` cùng base paper giữ **hai** folder và contents riêng, không overwrite.
- HTTP 200 tar, gz single TeX, raw TeX, PDF-only, 404, 429+Retry-After, 503+retry, timeout/range resume.
- Tất cả request automated giữ nguyên host `export.arxiv.org`; không truy cập `arxiv.org/src`.
- Fake clock kiểm chứng cumulative arXiv request pacing >=3s.

**Definition of Done:** `v1..vN` tải độc lập; file corpus chỉ `.tex/.bib`; status đúng; không auto failover main host.

### ARX-03 — `src/crawler/main.py`: sửa điều phối **mỗi version**, lỗi cục bộ và checkpoint [P0]

**Hàm liên quan có thật:** `build_parser`, `parse_args`, `Checkpoint.init_new/load/save`, `_process_paper`, `run_pipeline`, `_read_parts`, `main`.

**Lỗi hiện tại:** `_process_paper(arxiv_id, ...)` gọi downloader **một lần cho base ID**, sau đó gọi Semantic Scholar. `run_pipeline` chỉ append publication sau khi `_process_paper` thành công; reference API lỗi có thể làm mất publication. `counts["succeeded"] += 1` không kiểm tra `download["status"]`; `found[arxiv_id]` được lưu thẳng vào Parquet nên source metrics có thể không đi theo record.

**Sửa cụ thể:**

1. Tách `_process_paper` thành hai nhánh độc lập:
   - `_process_paper_versions(base_id, metadata, ...) -> VersionResults` lặp qua metadata `versions`, gọi downloader cho **từng versioned ID**.
   - `_process_paper_references(base_id, ...) -> ReferenceResult` chỉ query Semantic Scholar **một lần cho publication**, với status riêng.
2. Trong `run_pipeline`, khi metadata hợp lệ:
   - **Luôn** giữ publication record ngay cả khi source hoặc S2 lỗi. Làm giàu `versions[k]` bằng source status/sizes, lưu `references_status` vào per-paper manifest hoặc extension của schema.
   - Không `continue` khiến metadata paper bị bỏ chỉ vì S2 lỗi; failures được lưu vào checkpoint để retry theo **pha** và theo version.
   - Chỉ gọi `counts["source_success_versions"] += 1` khi `status == "success"`; tăng `versions_attempted` cho mọi version đã thử. `papers_metadata_success` tách khỏi `papers_all_versions_source_success` và `references_success`.
   - `pdf_only`/`no_latex` là kết quả hợp lệ của một lần thử source, không đồng nghĩa lỗi pipeline hoặc source LaTeX thành công.
   - `unknown`/API error không được biến thành `not_found`; những ID này phải pending để resume.
3. `Checkpoint`:
   - Đổi `done_ids` kiểu một cờ đơn sang per-paper progress: `metadata_done`, `versions_done: {"v1":..., ...}`, `references_done`, `export_done` **hoặc** đảm bảo một ID chỉ `done` khi tất cả pha đạt terminal status.
   - Khi resume, chỉ retry version/phần còn lỗi; không tải lại version đã hoàn tất. Dùng file tạm + atomic rename; kiểm tra index part Parquet thật sự tồn tại/có thể đọc.
   - Bảo đảm checkpoint tương thích migration hoặc fail rõ ràng đối với checkpoint cũ; **không âm thầm nhập trạng thái cũ chưa có coverage phiên bản**.
4. `_read_parts` hiện đọc toàn bộ fragments vào một list RAM; với corpus lớn có thể tăng memory. Đề nghị đọc/merge theo batch hoặc dùng PyArrow dataset streaming/chunked merge ở P1; vẫn ưu tiên correctness trước optimization.
5. Bổ sung `--max-papers` và `--dry-run` tùy chọn cho smoke test **không sửa semantics** của dải chính; `--max-papers` không dùng cho benchmark cuối nếu không ghi rõ subset.
6. `main` ghi `stats.json`: `run_id`, commit SHA, flags (`is_mock=false`), counts per phase/status, failures by reason, `required_version_count`, `attempted_version_count`, `success_version_count`, `raw_reference_count`, `references_with_arxiv_id`, environment, timing, resource samples.
7. Tích hợp `export_to_course_spec(...)` như explicit command/option **sau khi merge**; README cần chỉ cách tạo outputs 6 cột. Không dựa vào việc hàm tồn tại nhưng không được gọi.

**Pseudocode luồng chuẩn:**

```python
for base_id in assigned_ids:
    discovery = get_verified_discovery_result(base_id)
    if discovery.status == "api_error":
        record_retryable_failure(base_id, "discovery")
        continue
    if discovery.status == "confirmed_not_found":
        record_confirmed_missing(base_id)
        continue

    paper = discovery.metadata
    version_results = []
    for version in paper["versions"]:
        result = download_or_resume_version(f"{base_id}{version['version']}")
        version_results.append(result)
    paper["versions"] = merge_version_metrics(paper["versions"], version_results)
    save_paper_even_if_versions_partially_failed(paper)

    try:
        refs = scrape_references_for_paper(base_id, version_local_sources=...)
        save_refs_and_reference_status(refs)
    except ReferenceScrapeError as exc:
        record_reference_failure_without_dropping_paper(base_id, exc)
```

**Quan trọng:** đây là mô tả kiến trúc; agent phải dùng đúng signatures và schema sau khi đã sửa các module nguồn.

**Tests cập nhật `tests/test_cli_and_profiling.py`:**

- Metadata paper với `v1,v2,v3` -> downloader được gọi đúng 3 lần với URL/ID versioned.
- `v1` success, `v2` pdf_only, `v3` timeout -> paper vẫn nằm ở publication table, trạng thái partial đúng; resume chỉ thử lại `v3`.
- S2 404 hoặc API error -> paper vẫn nằm trong publications, reference status `not_indexed`/`api_error`.
- Downloader trả dict `status=error` -> không tính `source_success`.
- Crash giữa ghi Parquet của batch -> resume không mất/nhân đôi records.
- Bài không có arXiv ID xác nhận -> missing_count tăng, không được “tạo” publication giả.

**Definition of Done:** một paper multi-version thật được chạy end-to-end; `sources` không ghi đè; cả ba tập thống kê discovery/source/reference nhất quán.

### ARX-04 — `src/crawler/storage.py`: nối metrics và bảo vệ schema [P0]

**Hàm có thật:** `normalize_publication_record`, `normalize_reference_record`, `resolve_paper_source_status`, `save_publications_parquet`, `save_references_parquet`, `export_to_course_spec`; schema `VERSION_STRUCT_TYPE`, `PUBLICATIONS_SCHEMA`, `REFERENCES_SCHEMA`, `COURSE_PAPERS_SCHEMA`, `COURSE_REFERENCES_SCHEMA`.

**Đang có:** working publications 16 cột, working references 11 cột; course export 6+6 cột là đúng hướng. Nhưng input từ `main.py` chưa gắn download metric. `normalize_publication_record` có nhánh “tự tổng hợp v1 nếu rỗng”, và nếu chỉ có metrics cấp paper thì gán cho last version — điều đó **không thể thay thế** version-level crawling. `export_to_course_spec` suy ra revised_dates từ `versions.created`, nên nếu timestamps thượng nguồn sai thì output sai.

**Sửa cụ thể:**

1. `VERSION_STRUCT_TYPE`: giữ tối thiểu `version`, `created`, `size_before_bytes`, `size_after_bytes`, `source_status`. Có thể bổ sung `source_dir`, `error_code`, `timestamp_provenance` vào working schema **chỉ sau khi sửa mọi test/merger**.
2. `normalize_publication_record`:
   - Kiểm tra unique version numbers, sort numerically, reject `v0`, gap `v1,v3` nếu metadata khẳng định latest v3 mà thiếu v2.
   - **Không** tự coi `v1` synthesized là “version đã được crawl”. Nếu synthesis cần để duy trì compatibility, đặt provenance `synthetic`, `source_status=pending` và đếm riêng.
   - Kiểm tra không âm và `size_after_bytes <= size_before_bytes` cho mỗi version thành công; nếu thiếu dữ liệu, để null thay vì 0 giả.
   - Tổng size paper = tổng size các version **có số đo**, không xem đó là một source archive duy nhất.
   - `source_status` cấp paper tính từ toàn bộ version (`success`, `partial_success`, `pdf_only`, `no_latex`, `error`); không ép các trạng thái khác thành success.
3. `normalize_reference_record`: `ref_submission_date` nullable; giữ `ref_arxiv_id=None` ở working refs; kiểm tra `arxiv_id` source, external ID, author list, DOI; giữ `source` và `raw_citation` provenance.
4. `save_*_parquet`: giữ atomic write, quarantine; trong `on_invalid="quarantine"`, **xuất count và lý do rejects** ra stats. Nghiêm cấm công bố dataset “đủ” khi nhiều record lỗi đã bị loại âm thầm.
5. `export_to_course_spec`:
   - `papers.parquet`: chính xác `[arxiv_id, title, authors, submission_date, revised_dates, venue]`.
   - `submission_date` lấy ngày submit v1 có bằng chứng; nếu chưa biết, field nullable theo schema, **không bịa**.
   - `revised_dates` chỉ chứa ngày từng revision được xác minh; nếu không biết đủ, lưu missingness/completeness metric, không fallback cùng `updated` cho mọi vN. `[]` chỉ dùng khi đã xác nhận chỉ có một version hoặc khi thiết kế rõ “không có ngày revision đã biết” với cảnh báo, tránh hiểu sai.
   - `references.parquet`: `[arxiv_id, ref_arxiv_id, ref_title, ref_authors, ref_submission_date, ref_s2_id]`; chỉ giữ `ref_arxiv_id` non-null, dedupe theo `(arxiv_id, ref_arxiv_id)`, giữ một bản có nhiều trường đầy đủ hơn khi trùng.
   - Thêm schema assertion sau export, kiểm tra uniqueness, nullability, date format và file readability.
6. Tránh nhầm lẫn giữa `ref_submission_date` trong course schema và S2 `publicationDate`: nêu rõ provenance trong báo cáo; không tuyên bố đó là ngày nộp arXiv nếu nguồn chỉ cho publication date.

**Tests cập nhật `tests/test_storage_and_merge.py`:** status mixed versions, null dates, unknown actual revision timestamps, PDF-only paper retained, 6-column exact export, duplicate references retained locally but filtered/dedup in course output, timestamp timezone and `v10` order.

**Definition of Done:** working dataset biểu diễn được **từng version**, course export đúng 6+6 cột, không tự tạo ngày revision sai.

### ARX-05 — `src/crawler/reference_scraper.py`: giữ đúng semantics references và không làm rơi paper [P0]

**Hàm có thật:** `scrape_references_for_paper`, `_fetch_s2_references`, `_fetch_s2_pages`, `_get_json`, `_read_local_references`, `_dedupe`, `get_request_stats`, `reset_request_stats`, `_record_from_s2`.

**Ưu điểm giữ lại:** status-aware retry, phân trang, `referenceCount` check, parser BibTeX `.bib`, `paperId` và `externalIds.ArXiv`, lọc bib dựa vào citation thực trong `.tex`.

**Sửa cụ thể:**

1. `scrape_references_for_paper`: chuẩn hóa return contract để phân biệt **empty thật** (`200`, `referenceCount=0`), **not indexed** (`404`), **partial** (S2 báo > số items thực nhận), **API failure**, fallback `.bib` có dữ liệu. Có thể trả `ReferenceResult(records, status, source, expected_count, received_count, request_stats)` hoặc giữ list và cung cấp side-channel manifest; đồng bộ `main.py`.
2. `_fetch_s2_references`: hiện log warning rồi giữ danh sách một phần; **đồng thời** phải đánh dấu `partial` để notebook không tính là 100% thành công.
3. `_fetch_s2_pages`: bảo vệ loop, offset, malformed `citedPaper` đã có, bổ sung tests.
4. `_read_local_references`: theo yêu cầu chỉ `.tex/.bib` nằm trong corpus. Fallback `.bbl` chỉ đọc tạm nếu triển khai rõ artifact transient, không lưu `.bbl` persistent. Không “lấy cả `.bib`” khi không có citation trong `.tex` mà làm tăng giả references.
5. `_record_from_s2`: chỉ lấy `ref_arxiv_id` từ `externalIds.ArXiv` khi thật sự có; giữ missing. Không biến DOI hoặc year thành arXiv ID. Với legacy `hep-th/9901001`, giữ nguyên định danh.
6. `get_request_stats`: gọi reset theo run/phase, xuất số request, HTTP 429, retries, S2 404, partials, fallback into `stats.json`. Tách `reference_api_success_rate` khỏi `fraction_with_arxiv_id`.
7. Vì đề chỉ đòi S2 **per publication**, không được claim rằng S2 phân biệt citations từng version. Đặt `references_scope="publication"`; snapshot references chung, `.bib` thuộc từng version.

**Tests (`tests/test_reference_scraper.py` — tạo mới):** S2 JSON 200 empty, 200 multiple, pagination, 404 + cited `.bib`, 404 no fallback, 429/503 with Retry-After, nested/missing fields, duplicate S2 IDs, legacy IDs, partial response status.

**Definition of Done:** không làm mất paper do S2 lỗi, đo được reference coverage, không bịa `ref_submission_date`/ID.

### ARX-06 — `src/crawler/merge_shards.py`: merge + audit không mất coverage [P1]

**Hàm có thật:** `merge_all_shards`, `_check_id_coverage`, `_clean_base_id`, `_normalize_title_for_dedup`, `main`.

**Sửa cụ thể:**

1. `merge_all_shards`: giữ việc từ chối mock mặc định và cấm trộn mock/real; kiểm tra các shard thực sự được hoàn tất và có `stats.json` hợp lệ; không coi `is_mock=False` đơn lẻ là bằng chứng crawl thật.
2. Kiểm tra `required_member_ids` và khoảng ID nhóm đã đăng ký (cấu hình riêng hoặc CLI); nếu thiếu một shard, fail/ghi cảnh báo nổi bật, không báo “đủ toàn nhóm”.
3. Khử trùng publication theo base ID nhưng **merge version entries** theo `(base_id, version)`, chọn bản ghi có nguồn và timestamp xác minh tốt hơn; hiện tại chọn toàn bộ record có `updated` mới hơn có nguy cơ bỏ version có trong record còn lại.
4. Khử trùng reference dùng key `ref_s2_id`, `ref_arxiv_id`, DOI, normalized title như đang có; nếu hai records có key đồng nhất nhưng metadata khác, chọn record đầy đủ hơn và log conflict. Dedupe theo `(citing_paper, cited_paper)` khi xuất bảng chuẩn.
5. `_check_id_coverage`: xuất `expected`, `resolved`, `confirmed_missing`, `unverified`, `outside_range`; với dải vắt tháng kiểm tra thật tail boundary hoặc `tail_unverified=True` và không tuyên bố đủ 100%.
6. `overall_stats.json` bổ sung:
   - version_count, version_attempted, version_success_latex, version_pdf_only, version_failed, version_coverage_rate;
   - papers_metadata_resolved, papers_source_complete, papers_partial, papers_missing_confirmed;
   - references_query_attempted, references_api_success, references_partial, references_not_indexed, references_with_arxiv_id;
   - raw totals, unique totals, rejects, orphans, mock=false, run/commit provenance.
7. Tránh cộng peak RAM của các máy thành viên và gọi đó là peak của **một lần chạy end-to-end**. Tách `aggregate_member_stats` khỏi `official_colab_benchmark`.
8. Sau merge, cung cấp command tường minh gọi `export_to_course_spec` để xuất `papers.parquet`, `references.parquet` chuẩn đề.

**Tests:** duplicate publication có bổ sung version không bị mất, thiếu shard không được “complete”, cross-month ID coverage, mixed mock/real hard fail, valid course export sau merge.

**Definition of Done:** merged corpus không mất version, audit range có thể truy vết được, số liệu phù hợp bài nộp.

### ARX-06b — TẠO MỚI `src/crawler/validate_corpus.py` [P1]

**CLI đề nghị:**

```bash
python -m crawler.validate_corpus \
  --processed-dir data/processed \
  --corpus-dir data/raw/unzipped \
  --manifest-dir data/manifests \
  --course-export-dir data/course_export \
  --out data/processed/validation_report.json
```

**Kiểm tra:**

1. Assigned range coverage, số ID found/confirmed_missing/unverified.
2. Với từng paper: số version đúng `latest_version`; không thiếu `vN`, source folder path đúng, `success` phải có file `.tex`/`.bib` phù hợp status.
3. Từng version: không có extension ngoài allowlist; checksum file nếu có; không có symlink, escaped path.
4. Không có record source = error nhưng counts/success rate ghi thành success.
5. Mỗi reference source ID tồn tại trong publications; local refs giữ missing ref_arxiv_id; course refs không null.
6. Schema exact 6+6, type, uniqueness, date semantics, no mock; so sánh raw/merged/export counts.
7. Xuất machine-readable `validation_report.json`: `passed`, `critical_failures[]`, `warnings[]`, `metrics`, `run_id`, `commit_sha`.

**Exit code:** `0` nếu không có critical failures; nonzero nếu violated invariants. CI chạy validation trên fixtures nhỏ; benchmark thật chạy trên corpus thật.

### ARX-07 — `src/crawler/profiler.py`: benchmark đúng yêu cầu [P1]

**Hàm có thật:** `ResourceProfiler.start`, `_sample`, `_sampling_loop`, `.phase`, `stop_and_export`, `dir_size_bytes`, `_environment`.

**Hiện tại:** đo RSS theo chu kỳ, wall time và disk đầu/cuối, nhưng **chưa đo peak disk xuyên suốt quá trình**. Peak của `psutil.Process().memory_info().rss` chỉ là RSS tiến trình Python mẹ, có thể thiếu subprocess (nếu được tạo). Report yêu cầu memory của toàn hệ thống khi nhiều programs.

**Sửa cụ thể:**

1. `_sampling_loop`: giữ lấy mẫu RSS; thêm tracking disk `peak_disk_bytes` của đúng những thư mục **không chồng lắp**, với chu kỳ disk riêng (ví dụ 5–10 giây) và cộng phần tạm nếu có. Nếu scan toàn bộ tree tốn tài nguyên, đo thư mục/partition và `du` theo mốc, nêu giới hạn sampling.
2. `ResourceProfiler._sample`: nếu pipeline có subprocess thì giám sát cây process RSS, ghi metric riêng `process_tree_rss_mb`; đừng claim sum RSS = unique physical memory (shared pages có thể bị tính nhiều lần). Với phiên bản tuần tự Python thuần, parent RSS đủ đại diện hơn.
3. `.phase`: lưu cả elapsed và số lần gọi; bổ sung per-paper elapsed (including discovery, all versions, S2, storage) để tính **average wall time/paper**, không chỉ `total runtime / successful papers`.
4. `stop_and_export`: thêm `peak_disk_bytes`, `final_output_disk_bytes`, `total_input_ids`, `total_processing_wall_sec`, `average_wall_sec_per_assigned_paper`, `discovery_wall_sec`, `memory_sample_count`, `disk_sample_count`, environment (CPU-only true/false).
5. Thêm `run_id` và timestamps, Python/platform/library versions, git commit, constraints của Colab; báo cáo đơn vị MB/MiB nhất quán và rõ.
6. Đối chiếu `/usr/bin/time -v`: sử dụng `Maximum resident set size` (KB) và wall time. Nếu số đo khác `psutil`, giải thích tại sao.
7. Chạy Colab CPU-only **end-to-end thực**; không thay bằng tổng thời gian 5 máy khác nhau, không trích mock numbers.

**Tests cập nhật `tests/test_cli_and_profiling.py`:** timer, phase on exception, file growth peak vs final, memory sampling, idempotent stop, stats shape và repeated benchmark reproducibility.

**Definition of Done:** số peak disk có căn cứ, wall time E2E và average/per-paper có định nghĩa chuẩn, notebook 05 đọc metrics thật.

### ARX-08 — CẬP NHẬT TỪNG NOTEBOOK VÀ TẠO JUPYTER BOOK RIÊNG [P1]

> Đề yêu cầu **repo báo cáo riêng** cho Jupyter Book trên GitHub Pages. 5 notebook trong `arxiv-harvester/docs` chỉ là nguồn nội dung ban đầu, chưa thay thế một book đã build/public.

#### `docs/01_discovery_and_versions.ipynb`

- **Sửa:** bỏ hoặc đổi phát biểu “5.000 bài crawl dưới 3 phút”, “100% metadata” nếu không có run evidence; kết quả 5.000 hiện là **số ID được phân công** trong dải, không phải số publication đã tải full source.
- **Code:** đọc `overall_stats.json` và audit `discovery_status`, version distributions thật; hiển thị missing/error; không fallback sang một sample API live khi đang build report nếu mục đích là reproducibility.
- **Ngày revision:** hiển thị tỷ lệ version có timestamp verified; không vẽ dữ liệu ngày suy đoán.
- **Đầu ra:** bảng assigned/resolved/missing; biểu đồ versions/paper; latency và rate-limit counts.

#### `docs/02_source_download_and_cleaning.ipynb`

- **Sửa toàn bộ các code cell `# TODO`**; đọc version-level metrics và manifest.
- **Đầu ra:** tổng version, downloaded successfully, PDF-only/no-TeX/error; histogram source sizes; before/after bytes per version/paper; tỷ lệ giảm do bỏ figure; mẫu directory tree thật và checksum preservation.
- **Giải thích:** không chỉnh sửa TeX, chỉ filter archive members trong extraction; giữ folder rỗng hợp lệ.

#### `docs/03_reference_extraction.ipynb`

- **Sửa:** thống kê dựa trên `references_status` thật do main ghi; không phụ thuộc vào `reference_status` giả định không có trong `stats.json`.
- **Đầu ra:** S2 success/error/404/partial, số refs/paper, fraction refs có arXiv ID, fallback `.bib`, missing values, legacy ID.
- **Phân biệt:** reference count cấp publication, không chứng minh version-specific citations.

#### `docs/04_schema_and_data_quality.ipynb`

- **Sửa:** không tự chọn `data/mock/processed` khi build bản nộp; với production book thì missing real data -> fail build hoặc hiện banner “No validated real data” và **không xuất kết luận**.
- **Đầu ra:** schema 6+6 chuẩn, working schemas, null rate, orphan rate, rejects, duplication, version coverage, source coverage, validation_report status.
- **Giải quyết dữ liệu mock đã lưu:** ghi nhãn rõ phần demonstration hoặc loại khỏi bản nộp. Hiện notebook có cached output từ `../data/mock/processed` (24 publications, 20 references) — không dùng số đó làm kết quả crawl thực.

#### `docs/05_performance_benchmark.ipynb`

- **Sửa:** đưa output từ lần chạy Colab CPU-only thật vào benchmark records; `RUN_BENCHMARK=False` được giữ để book build không tự phát request, nhưng đã phải có artifacts số đo thật cung cấp cho report.
- **Đầu ra:** hardware/software, wall time E2E, discovery time, time per assigned paper, phase breakdown, peak/avg RAM, peak/final disk, rate limits/retries.
- **Giải thích:** so sánh metric benchmark một Colab với breakdown các shard thành viên; không gộp sai peak RAM.

#### Repo report mới, ví dụ `NguyenQuocDat06-AI/arxiv-harvester-book`

**Tạo riêng:**

```text
arxiv-harvester-book/
  _config.yml
  _toc.yml
  intro.md
  milestone-1/
    01_discovery_and_versions.ipynb
    02_source_download_and_cleaning.ipynb
    03_reference_extraction.ipynb
    04_schema_and_data_quality.ipynb
    05_performance_benchmark.ipynb
  scripts/
    prepare_report_metrics.py       # convert validated stats to report inputs
    check_book_inputs.py            # fail if is_mock or validation failed
  .github/workflows/deploy.yml
  README.md
```

- Book build phải thực thi code vẽ hình/tạo bảng từ metrics; **không chụp screenshot rồi nhúng**.
- Chỉ commit code/report và summary metrics không nhạy cảm cần thiết để build (nếu được phép), không commit toàn bộ corpus; có thể publish metrics nhỏ đã kiểm toán hoặc fetch build artifact được cấp phép, không để public CI tự crawl 25.000 papers.
- `deploy.yml` phải build/test và deploy GitHub Pages; link GitHub Pages/public repo phải thật sự truy cập được trước khi nộp Moodle.
- Tiếp tục dùng book này cho Milestone 2, không thay URL sau nộp.

### ARX-09 — TESTS + CI + PACKAGE LAYOUT [P1]

#### Tạo test mới

| File mới | Coverage bắt buộc |
|---|---|
| `tests/test_discovery.py` | Atom parsing, vN metadata, 429, partial batch, missing vs error |
| `tests/test_id_range.py` | same/cross month, boundary, errors, 5 personal ranges |
| `tests/test_source_downloader.py` | versioned `/src`, tar/gz, TeX/Bib only, security, PDF-only, 429 |
| `tests/test_reference_scraper.py` | S2 200/404/429, pagination, fallback, missing IDs, partial |
| `tests/test_pipeline_integration.py` | mock HTTP end-to-end -> real Parquet -> merge -> course export |
| `tests/test_validate_corpus.py` | intentional missing version, binary leakage, wrong schema, mock guard |

#### `.github/workflows/ci.yml`

**Hiện tại:** syntax check, notebook JSON check, `pip install --no-deps .`; **không chạy pytest**.

**Sửa:**

```yaml
name: CI
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -e ".[test]"
      - run: python -m compileall -q src
      - run: python -m pytest -q
      - run: python -m crawler.main --help
```

`[test]` là optional dependency group **phải bổ sung** ở `pyproject.toml`. CI phải offline/network-mocked, không gửi requests thật đến arXiv/S2.

#### `pyproject.toml` và `requirements.txt`

- Đang dùng `[tool.setuptools.packages.find] where=["src"]` và console entry point `arxiv-harvester = "crawler.main:main"`, trong khi README và tests còn import `src.crawler.*`. **Chuẩn hóa một import path duy nhất**.
- Đề nghị chuẩn package `crawler`: trong modules dùng relative imports (`from .discovery import ...`), CLI `python -m crawler.main`, installed entry `arxiv-harvester`; cập nhật tests/notebooks/README. Nếu giữ `src.crawler`, phải chỉnh build/entry tương ứng, kiểm thử trong thư mục không phải repo.
- Thêm `[project.optional-dependencies] test = ["pytest", ...]` và nhóm `report` (Jupyter Book, seaborn, matplotlib, pandas) để môi trường crawl nhẹ hơn khi benchmark; bảo đảm `requirements.txt` đồng bộ hoặc chỉ dẫn rõ cách cài extras.
- Cố định hoặc giới hạn major versions có rủi ro incompatibility; ghi Python version hỗ trợ và lock/snapshot dependency tại benchmark.
- Cần test installation clean: `pip install -e ".[test]"`, `arxiv-harvester --help` bên ngoài working directory.

### ARX-10 — `README.md`, `.gitignore`, `tasks/*.md` [P2]

#### `README.md`

- Thay mọi placeholder `<username>` bằng link thật khi repos được tạo; sửa link đặc tả đang trỏ vòng qua `google.com/search?q=...` về URL trực tiếp Lab Book.
- Bỏ các `raise NotImplementedError` trong phần “Interface Skeleton” **nếu code đã triển khai** hoặc đổi thành code minh họa chính xác; tránh khiến reviewer tưởng project vẫn là skeleton.
- Cập nhật endpoint `/src/{base}vN`, rule `.tex/.bib`, S2 per publication, new data layout và semantics `pdf_only`.
- Nêu đầy đủ: install, offline tests, small live smoke, production crawl theo từng dải, `--resume`, merge, validate, export 6+6, build book, benchmark Colab CPU-only.
- Công bố rõ “working schemas ≠ final course schemas”; corpus không upload ở Milestone 1, dùng tiếp cho M2/M3.
- Không công bố số liệu mock như số liệu thực; link Jupyter Book riêng và tình trạng phiên bản.

#### `.gitignore`

- Ignore **mọi** Parquet trong `data/` (không chỉ `data/shards/*/*.parquet`), raw, checkpoints, stats và version manifests nếu là dữ liệu chạy; giữ `.gitkeep`.
- Xem xét `data/processed/*`, `data/course_export/*`, `data/manifests/*`, logs, `.part`, temporary archives, benchmark raw outputs.
- Không commit `.env`, API key Semantic Scholar, tokens, source text, PDFs, binaries; riêng báo cáo public chỉ có aggregate metrics cho phép.

#### `tasks/TASK_*.md`

- Thay đặc tả module “dự kiến” bằng trạng thái thực, ticket IDs, acceptance tests, PR links, owner và reviewer.
- Giữ trách nhiệm phân vùng dữ liệu cá nhân độc lập với trách nhiệm kỹ thuật module: **mỗi thành viên vẫn phải crawl và kiểm tra dải ID cá nhân**, không chỉ viết phần code được giao.

---

## 3. KẾ HOẠCH CHIA VIỆC CHO 5 THÀNH VIÊN

| MSSV / Owner | Module chính | PR đề nghị | Kết quả cần bàn giao |
|---|---|---|---|
| **24120282** | `id_range.py`, `discovery.py`, notebook 01 | `fix/version-discovery` | Dải IDs đúng, latest vN đúng, không bịa revision dates, tests discovery |
| **24120237** | `source_downloader.py`, notebook 02 | `fix/versioned-source-corpus` | `/src/vN`, allowlist `.tex/.bib`, source statuses, tests security/archive |
| **24120438** | `reference_scraper.py`, notebook 03 | `fix/reference-coverage` | S2 status/provenance, partial/404/fallback, tests API |
| **24120470** | `storage.py`, `merge_shards.py`, `validate_corpus.py`, notebook 04 | `fix/schema-merge-validation` | Metrics vào Parquet, merge version, course export, validation report |
| **24120474** | `main.py`, `profiler.py`, notebook 05, CI | `fix/pipeline-and-benchmark` | Version loop, phase retry, E2E metrics, Colab benchmark, pytest CI |

**Quy tắc merge:** `develop` chỉ nhận PR có tests pass; không merge patch điều phối (`main.py`) trước khi thống nhất contracts giữa discovery, downloader, scraper, storage. Khi module đổi return type, owner phải cung cấp fixtures và migration notes.

### Thứ tự làm tối ưu để tránh conflict

1. **PR 1 — Contracts:** thống nhất `DiscoveryBatchResult`, `VersionDownloadResult`, `ReferenceResult`, schema version status, `manifest`, invariants. Có tests fixture trước.
2. **PR 2 — Discovery + Range:** fix source-of-truth versions & boundary/error.
3. **PR 3 — Downloader:** versioned `/src`, allowlist, security, status.
4. **PR 4 — References:** enrich statuses/provenance, no silent partial.
5. **PR 5 — Main/Storage integration:** loop versions, persist metrics, checkpoint, survive S2 outage.
6. **PR 6 — Merge/Validation:** end-to-end parity + 6-column export.
7. **PR 7 — Profiling + notebooks:** benchmark thật Colab, metrics thật, Jupyter Book build/public.
8. **PR 8 — CI/README cleanup:** tests gate, package install smoke, link thật.

Bất kỳ tối ưu performance nào làm thay đổi rate limit hoặc kết quả corpus phải được kiểm tra bằng regression trước khi chấp nhận.

---

## 4. TEST MATRIX VÀ CASES BẮT BUỘC TRƯỚC KHI CRAWL HÀNG LOẠT

| Case | Fixture / đầu vào | Kết quả bắt buộc |
|---|---|---|
| T01 | Atom ID có `v3` | 3 version `v1..v3`, không bịa ngày của v2 |
| T02 | Batch arXiv HTTP 429 liên tiếp | Failed/retryable, **không** thành not_found |
| T03 | Paper không tồn tại được xác nhận | `confirmed_not_found`, không tạo publication giả |
| T04 | Tar chứa `.tex/.bib/.png/.bbl/.sty` | Corpus chỉ `.tex/.bib` |
| T05 | Tar malicious `../escape.tex` hoặc symlink | Reject archive, không viết ra ngoài |
| T06 | `v1`/`v2` có nội dung khác nhau | Cả hai được giữ độc lập, checksum đúng |
| T07 | `v2` PDF-only | Manifest có v2, folder rỗng hợp lệ, paper vẫn xuất hiện |
| T08 | Một version download trả `status=error` | Source success không tăng, paper không biến mất |
| T09 | S2 API 404 không có fallback | `not_indexed`, paper vẫn có metadata |
| T10 | S2 trả 100 references nhưng chỉ lấy 80 | `partial`, coverage 80%; không claim complete |
| T11 | References thiếu arXiv ID | Có ở working refs, vắng ở course refs |
| T12 | Crash sau 2/3 versions, rồi `--resume` | Không tải lại 2 version đã xong; không duplicate |
| T13 | Merge 2 shards trùng paper nhưng bổ sung version | Không mất version trong merged publication |
| T14 | Report input `is_mock=true` | Build submission fail hoặc explicit reject |
| T15 | Export course tables | Đúng 6+6 columns, keys non-null theo đề |
| T16 | Cài package sạch ngoài repo | `arxiv-harvester --help` chạy được |
| T17 | CI offline | `pytest` thành công, không gọi API thật |
| T18 | Colab CPU-only với corpus thật | Có wall/RSS/peak disk và log provenance |

**Live smoke test có kiểm soát:** chọn 1 paper v1, 1 paper multi-version, 1 paper có source không chuẩn và 1 ID xác nhận không tồn tại (chỉ chọn sau khi kiểm tra thật); giới hạn requests/rate, ghi log ID và HTTP status. Không dùng ID/số liệu giả trong báo cáo. Nếu live smoke thất bại, sửa trước khi crawl 25.000 assigned IDs.

---

## 5. KIỂM TOÁN KẾT QUẢ CRAWL THỰC TẾ: CẦN XUẤT NHỮNG CHỈ SỐ NÀO?

### 5.1. Discovery/coverage

- `assigned_id_count` (có thể 5.000 mỗi thành viên, nhưng phải xác minh theo spreadsheet), `found_count`, `confirmed_not_found_count`, `discovery_error_count`.
- `expected_version_count = sum(latest_version_of_each_found_paper)`.
- `version_attempted_count`, `version_terminal_count`, `version_source_success_count`, `version_pdf_only_count`, `version_no_latex_count`, `version_error_count`, `version_retry_pending_count`.
- `version_attempt_coverage = version_terminal_count / expected_version_count` (diễn giải rõ terminal gồm cả PDF-only/no-TeX); `latex_source_success_rate = success / expected_version_count` là metric riêng, **không đánh đồng** với coverage.

### 5.2. Source storage

- Total/avg **uncompressed bytes before figure filtering** và total/avg kept `.tex/.bib` bytes after filtering, theo **version** và theo **paper**.
- Median, p95, max kích thước và phần trăm giảm dung lượng; chỉ so sánh trên nguồn có size hợp lệ, nêu mẫu N.
- Mọi source TeX file không bị biến đổi (checksum hoặc byte-level comparison khi test).

### 5.3. References

- Tổng paper có S2 request; thành công, empty-confirmed, partial, not-indexed, API error, Bib fallback.
- `raw_references`, `unique_working_references`, `references_with_arxiv_id`, orphan/duplicate rates.
- Average references/paper tính theo mẫu và định nghĩa rõ; có thể báo riêng “trên toàn assigned” và “trên paper S2 thành công”.

### 5.4. Performance

- **Colab CPU-only official run**: start/end UTC; wall time; entry discovery time; total time/source version; average time/assigned paper; successful processed paper count.
- Peak RSS, average RSS và sample frequency; max disk during execution, final storage, temporary archive size; CPU, memory capacity, Python/library versions.
- S2/API wait/backoff chiếm bao nhiêu thời gian, số 429, failure distribution.
- Nếu benchmark bị gián đoạn rồi resume, báo rõ **tổng wall time kể cả các lượt bị ngắt và chờ cần thiết** hoặc nêu chính xác phạm vi đã tính; không trình bày đoạn cuối làm toàn bộ thời gian.

---

## 6. QUY TRÌNH CHẠY / LỆNH NGHIỆM THU (CẦN CẬP NHẬT SAU KHI CODE)

> Các lệnh sử dụng namespace `crawler` sau khi chuẩn hóa package như ARX-09. Trước khi refactor xong, repository vẫn đang chạy theo `python -m src.crawler.main`; **đừng sao chép lệnh mới vào README rồi tuyên bố chạy được khi chưa test**.

### 6.1. Unit + integration tests (offline)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
python -m crawler.main --help
```

Windows PowerShell: `\.venv\Scripts\Activate.ps1` thay `source .venv/bin/activate`.

### 6.2. Chạy dải cá nhân (ví dụ 24120282)

```bash
python -m crawler.main \
  --member-id 24120282 \
  --start-month 2024-12 --start-id 18848 \
  --end-month 2025-01 --end-id 2641 \
  --output-dir data/shards/24120282 \
  --batch-size 50 --rate-limit-sec 3.0

# Nếu bị ngắt, chạy lại cùng args và --resume.
```

### 6.3. Merge, validate, export

```bash
python -m crawler.merge_shards \
  --shards-dir data/shards \
  --output-dir data/processed

python -m crawler.validate_corpus \
  --processed-dir data/processed \
  --corpus-dir data/raw/unzipped \
  --manifest-dir data/manifests \
  --course-export-dir data/course_export \
  --out data/processed/validation_report.json
```

**Cần bổ sung trong code:** `crawler.export_course` CLI wrapper hoặc lệnh module tương ứng gọi `storage.export_to_course_spec('data/processed','data/course_export')`. Hàm hiện tại tồn tại nhưng chưa có CLI đóng gói tường minh. Không chạy validation course table trước export.

### 6.4. Colab CPU-only official benchmark

- Vào Colab Runtime -> Change runtime type -> Hardware accelerator: **None/CPU**.
- Clone source code commit cố định, cài dependency đã pin/snapshot; xuất stdout/stderr, `/usr/bin/time -v`, `stats.json`, machine environment.
- Chạy end-to-end với dải/đầu vào công bố; lưu `run_id`, commit SHA và network request counts.

```bash
/usr/bin/time -v python -m crawler.main \
  --member-id 24120474 \
  --start-month 2024-06 --start-id 12938 \
  --end-month 2024-06 --end-id 17937 \
  --output-dir data/shards/24120474 \
  --rate-limit-sec 3.0 \
  2> data/shards/24120474/time_v.txt
```

**Ghi chú:** Tạo sẵn output directory trước khi redirect `2> ...` (shell redirect được mở trước chương trình); lưu stderr và profiler riêng để không mất logs. Với các dải khác phải thay tham số đúng spreadsheet.

### 6.5. Build book

```bash
# Trong repository Jupyter Book riêng sau khi tạo _config.yml và _toc.yml:
jupyter-book build .
# Cần kiểm tra mọi notebook tạo figure từ validated, non-mock metrics trong build.
```

Đảm bảo CI/pages workflow của Jupyter Book có thể build mà **không cần network crawl arXiv/S2**. Khi có thông tin runtime dữ liệu thật mới được cập nhật report metrics.

---

## 7. CHỈ DẪN REVIEW PR THEO HÀM: CHECKLIST NGẮN CHO CODING AGENT

### Nhóm discovery

- [ ] `discovery._parse_entry`: không gán ngày `updated` cho mọi revision.
- [ ] `discovery.discover_metadata_batch`: phân biệt API failed và confirmed missing.
- [ ] `id_range.find_last_id_of_month`: binary search không dùng response lỗi làm chứng cứ ID cuối.
- [ ] `id_range.iter_assigned_arxiv_ids`: tất cả dải thành viên tạo đúng ID và boundary.

### Nhóm source

- [ ] `source_downloader._download_and_clean_source_impl`: gọi `/src/{id}vN`, không `/e-print/{base_id}`.
- [ ] `source_downloader._safe_extract_tar`: chỉ ghi `.tex/.bib` trong extraction, không ghi hình vào corpus.
- [ ] `source_downloader._select_request_url`: không tự chuyển sang main arxiv.org.
- [ ] `source_downloader.download_and_clean_source`: status chính xác và version folder riêng.
- [ ] PDF-only/no-TeX: empty version record, không mất publication.

### Nhóm references

- [ ] `reference_scraper.scrape_references_for_paper`: có status/provenance, giữ all refs.
- [ ] `reference_scraper._fetch_s2_references`: partial được đánh dấu, không chỉ warning.
- [ ] `reference_scraper._read_local_references`: phù hợp corpus chỉ `.tex/.bib`.
- [ ] `main`: S2 failure không làm mất publication.

### Nhóm integration/storage

- [ ] `main._process_paper`/`run_pipeline`: lặp mọi versions và tổng hợp metrics đúng.
- [ ] `main.Checkpoint`: resume từng phase/version; không duplicate.
- [ ] `storage.normalize_publication_record`: giữ metrics và status từng version.
- [ ] `storage.export_to_course_spec`: 6+6 exact schema, revised dates đáng tin.
- [ ] `merge_shards.merge_all_shards`: không làm mất versions khi trùng publication.
- [ ] `validate_corpus`: không có critical failures ở dữ liệu thật.

### Nhóm reproducibility/report

- [ ] `profiler.ResourceProfiler`: peak RAM + average RAM + peak disk + wall time thật.
- [ ] `docs/02_...`: hết TODO.
- [ ] `docs/04_...`: bỏ mock khỏi report chính.
- [ ] `docs/05_...`: có Colab CPU-only real run evidence.
- [ ] `.github/workflows/ci.yml`: chạy tests offline.
- [ ] `pyproject.toml`: CLI chạy ngoài repo.
- [ ] `README.md`: endpoint, cách chạy, links, versions thực; không placeholder.
- [ ] Có Jupyter Book repo riêng, public Pages build thành công.

---

## 8. TIÊU CHÍ CHẤP NHẬN CUỐI CÙNG / NO-GO

**Không nộp như “đã hoàn chỉnh” nếu còn bất kỳ lỗi P0:**

1. Một paper có nhiều versions nhưng chỉ tải latest.
2. Archive có figure/binary trong working corpus khi đề yêu cầu chỉ `.tex`/`.bib`.
3. `revised_dates` có timestamp gán giả hoặc trùng `updated` do inference.
4. `download.status=error` vẫn làm tăng source success rate.
5. Một bài có metadata bị loại chỉ vì S2 lỗi hoặc PDF-only.
6. API outage làm biến ID thành `confirmed_not_found`.
7. Mock data dùng làm số liệu report cuối.
8. Không thể tái lập bằng một command trên test fixtures, hoặc course export 6+6 schema lỗi.

**Đạt điều kiện nộp mạnh khi:**

- `pytest` pass; CI xanh; source repo được kiểm tra public trước submission.
- Validation corpus thật pass; còn lỗi network/ID không tồn tại thì được giải thích và thống kê đầy đủ, không che giấu.
- Các paper có `latest_version=N` đều có manifest `v1..vN`; mọi version có status và source files đúng định dạng khi có LaTeX.
- Course export đúng schema, refs có arXiv IDs và authors/dates nullable theo đúng nguồn.
- Colab CPU-only benchmark thực có đầy đủ wall time, RAM, peak/final disk, logs.
- Jupyter Book repository riêng đã deploy GitHub Pages, biểu đồ/bảng sinh từ code, URL được nộp qua Moodle cùng URL source repo.

**Lưu ý cuối:** Điểm đánh giá trước đây là ước lượng chuyên môn từ review tĩnh, **không phải điểm giảng viên**. Ưu tiên correctness, traceability và report evidence hơn các tính năng tối ưu không cần thiết.

---

## 9. TÀI LIỆU / SOURCE OF TRUTH

1. [HCMUS Course Lab Book — Project Milestone 1: Data Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/) — đặc tả bắt buộc: từng revision, `/src/`, `.tex/.bib`, 6+6 schemas, Colab CPU-only, public source + Jupyter Book.
2. [Source repository / develop](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/develop) — mã nguồn được kiểm tra tại commit `ec5649b36fb565cf8c2cf2f8b98c6c2f4acea66d`.
3. [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html), [arXiv Media Types](https://info.arxiv.org/help/mimetypes.html), [Semantic Scholar API Docs](https://api.semanticscholar.org/api-docs/) — tài liệu vận hành API, tuân thủ giới hạn tốc độ.

**Đề xuất tên branch triển khai tổng:** `fix/milestone1-spec-compliance` hoặc các PR nhỏ như mục 3. Không push trực tiếp lên `main` khi chưa có CI + validation.
