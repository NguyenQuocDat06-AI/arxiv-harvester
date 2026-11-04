# Tích hợp source M1–M2 ngày 05/11/2026

Nhánh đích: `develop`, từ mốc `6d34d57a23b758359e1f97d51f1f91323d099c12`. Remote được fetch lại trước khi tích hợp; tại thời điểm kiểm tra, local và `origin/develop` trùng mốc này.

Đạt yêu cầu đưa source chưa push lên GitHub, gắn tên thành viên theo [bảng phân công](PHAN_CONG_21_CONG_VIEC_2026-11-05.md). Git author và committer của mỗi commit dùng cùng tên/email thành viên phụ trách đã tồn tại trong lịch sử repo. Attribution ghi phạm vi phụ trách cho source có hỗ trợ từ trợ lý, không chứng minh mỗi thành viên đã trực tiếp viết hoặc nghiệm thu phần đó. Theo yêu cầu tiếp theo của Đạt, metadata của 11 commit tích hợp được cập nhật để mỗi commit chỉ hiện một thành viên. Ngày author và lịch sử trước mốc nền được giữ nguyên.

## Phạm vi commit

| Người phụ trách | Git author / committer | Số commit mới | Nội dung |
|---|---|---:|---|
| Đạt | `Quoc-Dat Nguyen <nquocdat06.work@gmail.com>` | 2 | Discovery, lịch sử revision, request policy/rate limiter; cấu hình cài đặt, CI, hướng dẫn và công cụ bàn giao chung. |
| Tuấn | `tuan0306 <nguyentuan22032006@gmail.com>` | 2 | Tải/resume/retry source; audit nguồn, backup và notebook 02. |
| Tân | `NgTan <nguyentan10052006@gmail.com>` | 2 | S2 scraper/batch, quan sát request; enrich/provenance và notebook 03. |
| Trí | `takryudor <dpmtri12@gmail.com>` | 2 | Parser TeX/BibTeX, hierarchy, root config; normalization/dedup, schema, validation, merge và notebooks 04/06/07. |
| Triết | `AIVIETNAM-AIO-Triet-Descartes <triettrinhvy@gmail.com>` | 3 | Runner/readiness và Colab/Kaggle; profiler/thống kê/benchmark; công cụ build Book. |

11 commit tương ứng các nhóm thay đổi có sẵn; không dùng số commit để đánh dấu hoàn thành 21 đầu việc hoặc làm đều thống kê thành viên. Các commit phụ thuộc nhau và cần được lấy cùng nhau ở đầu nhánh tích hợp.

## Kiểm tra thực hiện trong đợt tích hợp

- Windows, Python 3.12.0: `python -m pytest -q` đạt **271 passed**, 1 warning, trong **55,78 giây**. Warning thuộc môi trường `requests`/`urllib3`/charset hiện có. Test được giữ local.
- `python -m compileall -q src tools` thành công.
- Cả 10 notebook qua kiểm tra JSON, cú pháp cell Python và `nbformat.validate`; không có output cell được lưu. Không chạy notebook trên Colab/Kaggle trong đợt này.
- Cài editable `arxiv-harvester 0.2.0` trong venv tạm bên dưới `build/push_check_20261105/`, dùng dependency đã có với `--no-deps --no-build-isolation`. Cả 7 entrypoint `--help` chạy thành công ngoài root repo: harvester, parser, audit sources, validate project, retry sources, reconcile dates và enrich references.
- Quét mẫu khóa GitHub, Google, AWS, Hugging Face, private key và literal API key trên các file dự kiến đưa lên Git: không phát hiện. Notebook không chứa kết quả crawl hoặc output runtime.
- Kiểm tra whitespace có tính CRLF của Windows bằng `git -c core.whitespace=cr-at-eol diff --check`.

`tests/`, corpus, checkpoint, log, ZIP/build, thư mục `scratch/`, `.env` và bản chép đề `crawling_content.txt` được giữ local. Không push các nhánh backup hoặc nhánh feature cũ.

## Phần vẫn cần thực hiện

Các báo cáo ngày trước được giữ làm lịch sử, không phải phép đo mới. Đợt này không crawl dữ liệu thật, không chạy benchmark Colab, không dựng lại Book hay triển khai Pages. Các đầu việc kiểm chứng source/reference, parser toàn corpus, benchmark, review của từng thành viên và nghiệm thu trong bảng phân công vẫn cần bằng chứng riêng.

Sau khi cập nhật `develop`, chạy smoke và validation với source mới, đúng MSSV/checkpoint trước full. Khi cần chạy offline, ZIP và notebook phải khớp SHA-256; không dùng ZIP cũ cho source đã sửa thêm.
