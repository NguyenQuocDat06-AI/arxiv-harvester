# Phân công tiếp theo — cập nhật 04/11/2026

Nhánh tích hợp: `develop`. Bản này ghi lại kế hoạch ngày 04/11; phân công hiện tại ở [bảng công việc](PHAN_CONG_SAU_THU_HOI_2026-11-04.md). Mỗi thành viên ghi nhận phần mình trực tiếp thực hiện.

Cập nhật full resume: notebook mặc định `RUN_MODE="full"`, tự dùng checkpoint để sửa phần thiếu và tiếp tục ID mới. Smoke/repair là các lựa chọn kiểm tra hoặc sửa riêng, không còn là điều kiện bắt buộc trước full. Validation đầu ra vẫn cần đạt trước khi chốt bảng/nộp. [Nhật ký thay đổi](DOWNLOAD_SPEED_PROGRESS_2026-11-04.md).

Code có hỗ trợ từ trợ lý. Việc gắn commit theo phạm vi phụ trách không xác nhận mỗi người đã tự viết hoặc kiểm thử toàn bộ phần đó. Thành viên cần review, chạy dữ liệu thật và nộp kết quả thực tế của mình.

## 1. Tình trạng đầu vào

- Dataset Hugging Face có metadata 25.000 paper/36.089 version, chưa có corpus TeX/Bib đầy đủ.
- Snapshot Drive đã audit: 50 paper, 73 version, 1.344 references. Có 67 version nguồn tốt; còn 3 version tải lỗi và 3 PDF-only chưa có manifest chứng minh.
- 17 paper chưa có reference cần xác định trạng thái; 6 ngày version còn thiếu trong mẫu Drive. Không suy rộng số liệu này cho toàn bộ dataset.
- Đã có parser, công cụ audit/retry, validation và notebook Colab. Chưa có benchmark toàn dải trên Colab, kết quả parser toàn corpus hoặc xác nhận Pages/Moodle.

## 2. Công việc từng thành viên

| Thành viên | Làm ngay | M2 sau khi có nguồn | File chính | Đầu ra để nghiệm thu |
|---|---|---|---|---|
| **Đạt — 24120282** | Đối chiếu dải ID và lịch sử revision; xác minh 6 ngày thiếu ở mẫu Drive, sau đó kiểm lại phần thiếu của dataset đầy đủ | Review compilation root/include; thêm override cho paper có nhiều root sau khi đọc TeX | `src/crawler/version_history.py`, `src/parser/latex.py`, `src/parser/gather.py`, `configs/parser_roots.json`, notebook 01 | Publications đã đối chiếu, history report/cache có nguồn ngày; danh sách root mơ hồ và override đã kiểm tra |
| **Tuấn — 24120237** | Retry `2412.18870v1`, `2412.18870v2`, `2412.18883v1`; xác minh `2412.18866v1`, `2412.18896v1`, `2412.18896v2` có thực sự PDF-only; giữ 67 version tốt | Đối chiếu hierarchy với TeX trên nhiều bố cục, kiểm tra section, paragraph, sentence, math, list, figure/table và appendix | `src/crawler/source_downloader.py`, `validate_sources.py`, `retry_sources.py`, `src/parser/hierarchy.py`, notebooks 02/06 | Source audit trước/sau, manifest 6 version, log retry; ví dụ hierarchy đối chiếu với vị trí trong TeX |
| **Tân — 24120438** | Truy vấn lại references và lưu status cho 50 paper, nhất là 17 paper đang rỗng; thống kê metadata thiếu và xác minh xung đột định danh | Kiểm tra BibTeX/bibitem, gộp field và ánh xạ citation key qua version; phối hợp Trí ở notebook 07 | `src/crawler/reference_scraper.py`, `enrich_references.py`, `src/parser/bibliography.py`, notebook 03 | `crawl_status.parquet`, references và report provenance/coverage; không dùng publication date S2 thay ngày nộp arXiv |
| **Trí — 24120470** | Sau Tuấn/Tân, merge và xuất lại bảng; đối chiếu ID/version/reference keys, schema và FK. Mốc audit cũ là 50 paper/729 cạnh có arXiv ID, số mới thay đổi phải giải thích | Chạy validation 5 bảng, kiểm tra normalization giữ math/cites, dedup và liên kết parent; tổng hợp số liệu trước/sau | `src/crawler/records.py`, `merge_shards.py`, `src/parser/{normalize,deduplicate,storage,validation}.py`, notebooks 04/07 | Course export, báo cáo bảo toàn dữ liệu và `project_validation.json`; không coi structural valid là đã đủ corpus |
| **Triết — 24120474** | Chạy notebook mới với full resume; có thể chọn smoke/repair để kiểm tra riêng; thu log và validation sau mỗi run | Chạy parser/benchmark Colab CPU-only; build Book từ inputs đã lưu; phối hợp Đạt chuẩn bị repo báo cáo riêng | `src/crawler/main.py`, `readiness.py`, `reporting.py`, `src/parser/main.py`, `statistics.py`, `colab_crawler.ipynb`, `tools/build_report.py`, notebooks 05/08 | Metadata kết thúc, `crawler.log`, `stats.json`, `time_v.txt`, resource samples, validation và HTML Book có phạm vi dữ liệu rõ ràng |

Mỗi người vẫn thu thập **5.000 paper thuộc dải cá nhân** trong README. Việc Tuấn/Tân hỗ trợ sửa mẫu Drive của Đạt là kiểm tra tích hợp; không thay cho dữ liệu của dải mình.

## 3. Thứ tự thực hiện

1. **Triết:** mở notebook từ `develop`, chọn `CURRENT_MEMBER`, dùng `RUN_MODE="full"` để tiếp tục toàn dải; có thể chọn smoke khi muốn kiểm tra 5 paper. Source GitHub phải là bản có runtime mới.
2. **Tuấn + Tân:** giữ bản sao dữ liệu cũ, phối hợp chạy `RUN_MODE="repair"` trên checkpoint 50 paper. Dùng một phiên ghi vào shard đó; người còn lại đọc bản sao để audit. Không xóa nguồn tốt hoặc chạy hai crawler cùng ghi một checkpoint.
3. **Đạt + Trí:** xác minh ngày/root và đối chiếu course export. Full resume có thể tiếp tục phần lỗi và ID mới; chỉ chốt bảng khi validation đạt. `not_indexed`/fallback được báo là thiếu độ phủ, không tự nhận đủ kết quả S2.
4. **Cả 5 người:** chạy full resume dải cá nhân; giữ archive backup đã xác minh, manifests, checkpoint và metrics trên Drive. HF chỉ có metadata không thay được raw corpus.
5. **Đạt → Tuấn/Tân → Trí:** chốt root, kiểm tra hierarchy/bibliography, rồi parse corpus và validate 5 bảng. Ghi rõ partial/error và lý do chưa xử lý.
6. **Triết:** benchmark M1/M2 trên Colab CPU-only, build Book từ dữ liệu/metrics thật. Đạt kiểm tra link code, link Book và yêu cầu nộp trong [checklist chung](HF_DATASET_AUDIT_2026-10-30.md).

## 4. Cách làm trên GitHub

Sau đợt tích hợp này, mỗi người lấy `develop` mới và tạo nhánh công việc tiếp theo. Không chép lại các file đã có để tạo commit trùng.

| Thành viên | Nhánh đề xuất cho việc tiếp theo |
|---|---|
| Đạt | `review/24120282-discovery-gathering` |
| Tuấn | `review/24120237-sources-hierarchy` |
| Tân | `review/24120438-references-bibliography` |
| Trí | `review/24120470-storage-deduplication` |
| Triết | `review/24120474-runner-report` |

Trong clone riêng đã lưu các thay đổi local:

```bash
git switch develop
git pull --ff-only origin develop
git switch -c review/24120237-sources-hierarchy
```

Thay tên nhánh theo bảng. Commit phần sửa thực tế bằng tài khoản của mình, push nhánh cá nhân và mở PR vào `develop`; một người khác review trước khi merge. PR ghi file đã sửa, dữ liệu/phạm vi đã kiểm tra, lệnh và kết quả thật. Không commit key, corpus, checkpoint hoặc log chạy.

Thông tin push đợt trước lưu tại `build/team_push_20261104/execution.json` trên máy tích hợp. Lịch sử `develop` sau đó đã thay đổi; xem Git để biết trạng thái hiện tại.

## 5. Gói bàn giao và tiêu chí kết thúc

Source hiện tại lấy từ GitHub. Nếu cần ZIP để review offline, chạy:

```bash
python tools/prepare_handoff.py --output build/team_handoff_2026-11-04
```

Công cụ tạo snapshot chung, gói riêng theo MSSV và manifest hashes; không tự commit hoặc push. Gói cũ ngày 02/11 chỉ dùng đối chiếu lịch sử. Với Colab không có GitHub, có thể tạo gói runtime bằng `python tools/prepare_colab_bundle.py`; ZIP và notebook phải cùng SHA-256.

Chỉ kết thúc M1–M2 khi đã đối chiếu đủ dải ID, có nguồn hoặc bằng chứng không có TeX cho từng version, references có trạng thái, đầu ra parser/validation đủ phạm vi, benchmark Colab, Book và xác nhận nộp. Test offline hoặc smoke không thay cho các đầu ra này.
