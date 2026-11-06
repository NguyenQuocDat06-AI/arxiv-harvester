# Điều chỉnh theo QA của giảng viên — 06/11/2026

Nguồn: [QA Replies 2627-1](https://docs.google.com/spreadsheets/d/11UDWf52DitCDrV386WkYK0ZySqTGQSCRnEwQ37u9uyQ/edit). Nhóm xác nhận học chương trình Chuẩn, Book tiếp tục dùng tiếng Việt.

## Phạm vi và căn cứ

- M1 dòng 7: hạn nộp Book hiện tại là nộp link tiến độ; được cập nhật đến hạn Poster, giữ nguyên URL.
- M1 dòng 13–17: benchmark cuối trên toàn dải của nhóm, tính retry/delay; được chia nhiều phiên Colab nếu giữ log và phân tích tổng hợp.
- M1 dòng 19: thử chuyển bibliography trong `.bbl`; nếu chưa chuyển được thì giữ nguồn đó để tránh mất references.
- M1 dòng 20–21: `ref_submission_date` được dùng `publicationDate` S2 hoặc ngày lấy qua arXiv ID; lưu rõ nguồn.
- M1 dòng 17: Book có hai chương chính tương ứng M1/M2; các trang kỹ thuật sẽ là mục con.
- M3 dòng 2–3: mỗi thành viên ít nhất 5 publication gán nhãn và host phần dữ liệu của mình trên Hugging Face cá nhân; pipeline vẫn dùng chung.

## File sửa và lý do

| File | Thay đổi | Lý do |
|---|---|---|
| `src/crawler/source_downloader.py` | Giữ `.bbl` như bibliography phụ trợ và ghi danh sách vào manifest | Tránh mất nguồn references trước bước M2 |
| `src/crawler/validate_sources.py`, `src/crawler/retry_sources.py` | Đồng bộ allowlist, audit số file `.bbl` | Nguồn đã giữ hợp lệ không bị coi là hỏng hoặc tải lại vô ích |
| `src/parser/bibliography.py`, `src/parser/main.py` | Đọc `.bbl` liên quan compilation; chuyển bibitem thành bản ghi và đưa `.bbl` vào fingerprint | Tránh lẫn bibliography không được dùng và tránh dùng cache cũ khi `.bbl` đổi |
| `src/crawler/enrich_references.py` | Bổ sung ngày S2 còn thiếu, giữ provenance và ngày đã có | Thực hiện quy ước ngày được thầy chấp nhận |
| `tools/prepare_submission_snapshot.py` | Giữ bibliography phụ trợ khi dựng snapshot mới | Không làm mất `.bbl` ở bước chuẩn bị dữ liệu |
| `src/crawler/benchmark_sessions.py` | Tổng hợp từng milestone, loại run trùng, phân biệt profiler/child wall và giữ số chưa biết là null | Hỗ trợ benchmark nhiều phiên mà không đếm trùng hoặc làm mất thời gian retry |
| `tools/submission_report_qa.py` và các template Book | Ghi mốc tiến độ, quy ước ngày, ví dụ `.bbl`, bảng phiên đo và phụ lục QA | Nối thay đổi code với lời giải thích và bằng chứng trong báo cáo |

Số liệu 73 paper/119 version và hai lượt đo lịch sử giữ nguyên. Sửa code mới không tự làm tăng độ phủ hoặc biến benchmark mẫu thành benchmark toàn dải. Các ca `.bbl` minh họa được ghi rõ là tổng hợp.

## Tiến trình

- [x] Đọc QA và xác nhận ngôn ngữ chương trình Chuẩn.
- [x] Hoàn tất xử lý `.bbl`, audit, retry và cache parser.
- [x] Kiểm tra bổ sung ngày references và provenance.
- [x] Thêm công cụ tổng hợp nhiều phiên benchmark và hướng dẫn dùng.
- [x] Cập nhật nội dung Book, hai chương chính và đối chiếu QA.
- [x] Kiểm tra local, build Book và giữ tests local.
- [ ] Commit/push source `main`, đồng bộ `develop`.
- [ ] Deploy vào repository Book hiện có và kiểm tra URL public.

Kiểm tra chức năng: `python -m pytest -q` đạt **281 passed** trong **56,87 giây**. Test giữ local. Công cụ tổng hợp đã đọc hai lượt M1/M2 cũ riêng biệt; số đo giữ 261,958 giây profiler/263,652 giây child wall ở M1 và 143,052 giây Windows ở M2.

Book local build đạt với `--all -W`: **16 trang, 47 code cell thực thi, 15 hình**. Mục lục có một chương chính cho mỗi milestone và các trang kỹ thuật làm mục con. Đã đối chiếu các số liệu cũ không đổi; chỉ thêm bảng tổng hợp phiên đo. URL trang đã có được giữ.

Đã tạo lại `colab_parser_submission.ipynb` và hai ZIP khớp SHA-256 trong `build/qa_review_20261106/colab_package/`. Runtime chứa code QA mới; input vẫn là snapshot 73 paper/119 version. ZIP/input giữ local. Chưa chạy notebook này trên Colab trong đợt sửa.
