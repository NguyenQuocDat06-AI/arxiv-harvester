# Kiểm tra notebook trước khi giao nhóm

## Phạm vi

Kiểm tra `colab_crawler.ipynb` và các module crawler liên quan bằng dữ liệu mô phỏng tại máy Windows. Không gọi API bằng key của nhóm, không sửa corpus hay checkpoint trên Drive. Chưa thực thi notebook trên runtime Colab thật trong lượt kiểm tra này.

## Vấn đề phát hiện

- Notebook mặc định chạy full và lấy source mới nhất của `develop`; các thành viên có thể chạy những bản code khác nhau.
- Log của notebook chỉ được sao lưu sau khi tiến trình kết thúc. RAM/đĩa chỉ được xuất mẫu ở cuối lượt; mất VM giữa chừng có thể làm mất bằng chứng benchmark.
- CLI trả mã 0 khi `completed_with_errors`, nhưng notebook vẫn có thể ghi trạng thái `completed`.
- Validation kiểm tra schema và nguồn nhưng chưa đối chiếu toàn bộ dải ID được giao. Một tập nhỏ hợp lệ không đồng nghĩa đã hoàn tất 5.000 ID.
- Đổi thành viên hoặc sửa cấu hình giữa các cell có thể giữ lại biến/đường dẫn của lượt cũ.
- Thông báo kết quả chưa chỉ rõ nguồn bền vững nằm trong archive Drive khi dùng SSD `/content`.

## Thay đổi đã thực hiện

| File | Thay đổi | Lý do |
| --- | --- | --- |
| `src/crawler/colab_support.py` | Snapshot file có checksum, lấy prefix tại thời điểm mở; gom số đo đúng run ID và mirror sang Drive. | Sao lưu được log đang tăng mà không so hash sai với file vừa được ghi thêm. |
| `src/crawler/profiler.py` | Ghi mẫu tài nguyên trong lúc chạy, vẫn giữ bản tổng hợp cuối lượt. | Giữ các mẫu đã đo khi runtime mất đột ngột. |
| `src/crawler/main.py` | Cấp đường dẫn mẫu tài nguyên cho từng run. | Không trộn mẫu giữa các phiên. |
| `src/crawler/readiness.py` | Đối chiếu MSSV, dải ID, số ID, ranh giới và lỗ hổng; từ chối full bị giới hạn tập con. | Chỉ xác nhận hoàn thành toàn dải khi có đủ bằng chứng. |
| `src/crawler/drive_backup.py` | Không đưa file mẫu còn đang tăng vào archive dữ liệu; bản mẫu cuối được đưa vào sau khi xuất stats. | Tránh archive sai kích thước/checksum khi profiler ghi đồng thời. Mẫu đang chạy được notebook sao lưu riêng. |
| `colab_crawler.ipynb` | Mặc định smoke; pin source, kiểm tra cấu hình/đường dẫn trước chạy; mirror mỗi 60 giây; giữ đúng trạng thái crawler; kiểm tra dung lượng và checksum export. | Phát hiện lỗi sớm và giảm mất tiến trình khi ngắt Colab. |
| `README.md` | Cập nhật thứ tự smoke → full, vị trí corpus và cách bàn giao M2. | Hướng dẫn khớp với hành vi của notebook. |

## Các điểm đã đối chiếu

- Cấu hình của DAT, TUAN, TAN, TRI, TRIET khớp với năm file `tasks/TASK_*.md`.
- Dải vắt tháng vẫn dùng kết quả tìm ID cuối tháng thật; không gán một cận giả để ép số lượng.
- Full tiếp tục dữ liệu cũ và sửa bài còn thiếu; không bắt buộc repair xong riêng rồi mới tải ID mới.
- S2 key nhập qua ô ẩn `getpass`, không lấy từ Colab Secrets và không lưu trong notebook.
- Nguồn giữ `.tex`, `.bib`, `.bbl`; checkpoint và manifest được dùng lại khi resume.

## Kiểm chứng

- **122 ca đạt**, 44,32 giây: notebook, bundle, crawler theo lô, readiness, backup và profiler. Chạy offline trên Windows với dung lượng đĩa thật; không gọi API arXiv/S2. Các ca bao gồm 5 thành viên × 3 chế độ, cấu hình sai, log tăng trong lúc sao lưu, copy sai checksum, source đã cache và restore/resume không tải lại phần hợp lệ.
- **310 ca hồi quy đạt**, 62,42 giây: gồm cả parser. Ổ C còn khoảng 3,06 GiB, trong khi parser/retry đặt ngưỡng 4 GiB; lần chạy này mô phỏng dung lượng 8 GiB riêng cho thư mục dữ liệu pytest. Các ca chủ động mô phỏng hết đĩa vẫn chạy và kiểm tra việc dừng. Không thay ngưỡng trong code sản phẩm, không xóa file người dùng.
- Notebook qua kiểm tra nbformat, AST của từng code cell và không có output đã lưu.
- Đối chiếu checksum các file crawler trong commit đã pin với checksum notebook; cài ZIP bằng chính hàm trong notebook rồi probe subprocess, kết quả khớp.
- Source runtime: `16fd9d13c98128a3bdd4c03b76b9c970c8c9be5f`.
- ZIP dự phòng: `build/colab_handoff_audit_20261107/arxiv_colab_runtime.zip`, 42 file, SHA-256 `b973469d3505edab4570340c85d7aecb94d0c8b8aa7c47901c9fa0013b20dab6`. ZIP không chứa `.env`, corpus hay tests.
- Môi trường Python Windows có một cảnh báo tương thích dependency của `requests`. Chưa dùng kết quả này để khẳng định tương thích cài đặt trên Colab thật.

File kiểm thử và dữ liệu mô phỏng chỉ lưu local, không đưa lên GitHub. Đây là kiểm tra chức năng, không phải số đo benchmark Colab để nộp.

## Cách giao cho thành viên

1. Gửi [notebook từ main](https://colab.research.google.com/github/NguyenQuocDat06-AI/arxiv-harvester/blob/main/colab_crawler.ipynb). Mỗi người lưu một bản riêng, chọn CPU và đúng `CURRENT_MEMBER`.
2. Giữ mặc định `RUN_MODE="smoke"`, Drive bật, upload/restore HF tắt. Nhập key của mình và chạy tuần tự đến validation.
3. Khi smoke đạt, đổi `RUN_MODE="full"`, chạy lại từ cell cấu hình. `MAX_PAPERS` tự thành 0, `--existing-only` không được thêm. Không dùng `repair` để kỳ vọng tải tiếp toàn dải.
4. Nếu đang có một lượt cào cũ chạy ổn, để lượt đó kết thúc hoặc Stop và chờ lưu checkpoint; không cập nhật source trong lúc tiến trình cũ còn chạy. Sau đó mới mở bản notebook mới, giữ đúng Drive và MSSV để resume.
5. Bàn giao `backups/<MSSV>`, `logs/<MSSV>` của mọi phiên và bảng chuẩn. Giữ cả chuỗi archive/record cùng `HEAD.json`; không chỉ gửi archive mới nhất hoặc thư mục raw Drive cũ. Khôi phục raw/shard rồi chạy parser M2 trên nguồn đó.

## Giới hạn cần giữ trong báo cáo

- Chưa chạy thử runtime Colab thật trong lượt audit này. Mỗi thành viên vẫn cần smoke trên key, Drive và mạng của chính mình trước khi chạy dài.
- Không bảo đảm dịch vụ hết 429/503 hay Colab không bị ngắt. Code giữ cooldown và tận dụng lại phần nguồn đã xác minh. Ngắt đột ngột có thể mất phần chưa vào bản backup nguồn hoặc mirror log thành công gần nhất.
- Một MSSV chỉ có một runtime ghi dữ liệu. Nhiều runtime dùng cùng S2 key vẫn chung quota; dùng key được cấp riêng hoặc chạy các lượt dùng chung key lần lượt.
- Validation có thể báo cảnh báo ngày revision chưa xác minh hoặc S2 chưa index. Giữ các cảnh báo và bổ sung metadata sau; không coi chúng là bằng chứng đã đáp ứng mọi mục chấm điểm.
- Crawler chuẩn bị đầu vào M2. Parser, audit kết quả M2 và benchmark M2 trên Colab CPU vẫn là các bước riêng theo [đề bài](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/).
