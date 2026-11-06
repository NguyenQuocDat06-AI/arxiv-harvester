# Khôi phục lịch sử đóng góp — 06/11/2026

## Trạng thái trước khi sửa

- Repository source: `NguyenQuocDat06-AI/arxiv-harvester`.
- `develop`: `0e178cf89783b633caf12d0aa8fc034a32aa67a8`, trùng remote và không có thay đổi chưa commit.
- Nhánh mặc định trên GitHub là `main` tại `88aa7381fe5a20f82b9682c18428b8d5a43ce9c5`, chỉ có commit khởi tạo. API Contributors khi kiểm tra chỉ trả về chủ repository với một commit.
- Năm nhánh `feat/*` vẫn tồn tại trên remote. Không có thao tác xóa repository trong đợt sửa này.
- Năm commit gốc của Tân và commit notebook `80e8c17` của Tuấn chưa là ancestor của `develop`.

## Các thay đổi và lý do

| Vị trí | Thay đổi | Lý do |
|---|---|---|
| Lịch sử Git `develop` | Merge `6d1c6148652e093cca11fb2ac4c5be6fe3895f1d` nối hai tip `a83efe7` và `80e8c17`, giữ nguyên tree hiện hành bằng chiến lược `ours` | Khôi phục liên kết tới commit gốc; tránh đưa code/notebook cũ đè lên phiên bản hiện tại |
| Cài đặt repository GitHub | Đặt `develop` làm nhánh mặc định | Mở repository sẽ tới source và lịch sử tích hợp của nhóm |
| `CONTRIBUTIONS.md` | Bảng thành viên, nhánh và commit gốc; giải thích lịch sử gộp/khôi phục | Có đường dẫn cụ thể để đối chiếu đóng góp, phân biệt lịch sử source với lịch sử xuất bản Book |
| `README.md` | Liên kết tới bảng đóng góp và ghi nhánh mặc định | Giúp người xem tìm được bằng chứng từ trang đầu repository |

Lý do giữ tree hiện hành: tree của nhánh references gốc trùng hoàn toàn với `6155348` đã tích hợp; phần duy nhất còn thiếu của nhánh sources là notebook cũ, đã có bản thay thế dùng loader/schema hiện tại. Nội dung notebook cũ vẫn xem được qua commit gốc.

Không đổi metadata của commit gốc, không tạo commit thay cho thành viên và không cân bằng số commit. Đợt khôi phục dùng danh tính Git hiện đang cấu hình của người tích hợp.

## Sao lưu và kiểm tra

- Nhánh backup cục bộ: `backup/develop-before-history-recovery-20261106`.
- Bundle đầy đủ refs trước khi sửa: `build/history_recovery_20261106/before-recovery.bundle`. Bundle giữ local.
- Git tree trước và ngay sau merge khôi phục đều là `68b96ed16dc1e1ab1be8821e7fb3c27586b411aa`.
- Sáu commit được nối lại giữ nguyên SHA và metadata; cả hai nhánh gốc trở thành ancestor của `develop`.
- GitHub API xác nhận commit gốc của cả năm người liên kết được với tài khoản của họ. Git author `NgTan` được liên kết tới `nguyentan10052006-cmyk`.
- Không thêm file trong `tests/`; corpus, log và bundle không nằm trong commit mới.
- Sau merge chỉ bổ sung tài liệu; không cần chạy lại crawler/parser vì source không thay đổi.
- Các kết quả xác nhận remote, nhánh mặc định và URL Book được lưu trong `build/history_recovery_20261106/` sau khi push.

Book tiếp tục dùng https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/. Repository báo cáo và dữ liệu/số đo đã công bố không bị thay đổi trong đợt khôi phục.
