# Đóng góp thành viên và lịch sử source

Repository source của nhóm là [arxiv-harvester](https://github.com/NguyenQuocDat06-AI/arxiv-harvester), nhánh chính và mặc định `main`. Nhánh `develop` dùng để tích hợp thay đổi. Đây là nơi đối chiếu code, tác giả và lịch sử thay đổi của thành viên.

[arxiv-harvester-book](https://github.com/NguyenQuocDat06-AI/arxiv-harvester-book) chứa báo cáo được dựng từ source và số liệu tổng hợp. Lịch sử xuất bản Book không thay thế lịch sử đóng góp ở repository source. URL nộp Book giữ nguyên: https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/.

## Nhánh và commit ban đầu

Bảng dưới liên kết phần triển khai ban đầu trong Git và nhiệm vụ cá nhân. Các module tiếp tục được sửa trong các đợt tích hợp sau đó.

| Thành viên | Phần triển khai ban đầu | Nhánh gốc | Commit để đối chiếu |
|---|---|---|---|
| [Nguyễn Quốc Đạt — 24120282](tasks/TASK_24120282_NguyenQuocDat.md) | Sinh dải ID, discovery metadata/version, notebook 01 | [feat/metadata-discovery](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/feat/metadata-discovery) | [8ce6d34](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/8ce6d34fa370b2c6c11c69d6e9fa64cef1c6c077) |
| [Nguyễn Đình Tuấn — 24120237](tasks/TASK_24120237_NguyenDinhTuan.md) | Tải, giải nén và lọc nguồn; notebook 02 | [feat/source-downloader](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/feat/source-downloader) | [f342e6d](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/f342e6d34ffc664651daf6cc0259b330f932aa2c), [2d32d3d](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/2d32d3df86b07ab23c5498cc68c09996b74d66fd), [80e8c17](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/80e8c170bbdbafe90f6162c2fd17ead19eef8385) |
| [Trần Nguyên Tân — 24120438](tasks/TASK_24120438_TranNguyenTan.md) | References qua S2, fallback bibliography và notebook 03 | [feat/reference-extraction](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/feat/reference-extraction) | [cd33179](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/cd33179e8312b8da423f0c72784e842174893e6a) → [a83efe7](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/a83efe7b8cd1dd7bae3235267694a8066d4d3e6e) |
| [Dương Phan Minh Trí — 24120470](tasks/TASK_24120470_DuongPhanMinhTri.md) | Schema/Parquet, gộp shards, dữ liệu mẫu và notebook 04 | [feat/data-storage](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/feat/data-storage) | [f3ab9b9](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/f3ab9b98fe09782bcca26e3c639900da19cb5ddd) |
| [Trịnh Vỹ Triết — 24120474](tasks/TASK_24120474_TrinhVyTriet.md) | CLI/resume, profiler và notebook 05 | [feat/cli-and-profiling](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/feat/cli-and-profiling) | [5c1a673](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/5c1a67364cafb8e6f5ce16553f8dc72871f01bb2) |

Các commit tích hợp ngày 05/11 được mô tả riêng tại [biên bản tích hợp](tasks/PUSH_SOURCE_2026-11-05.md), gồm phạm vi hỗ trợ từ trợ lý. Bảng nhiệm vụ và Git author cần được đối chiếu với diff, kết quả chạy và giải thích của từng thành viên khi đánh giá đóng góp.

GitHub đã liên kết các commit gốc trong bảng với đúng năm tài khoản: [Đạt](https://github.com/NguyenQuocDat06-AI), [Tuấn](https://github.com/tuan0306), [Tân](https://github.com/nguyentan10052006-cmyk), [Trí](https://github.com/takryudor) và [Triết](https://github.com/AIVIETNAM-AIO-Triet-Descartes). Tên Git `NgTan` của Tân khác tên tài khoản GitHub; không cần sửa tác giả commit để đổi cách hiển thị này.

## Khôi phục liên kết lịch sử ngày 06/11/2026

Trước khi sửa, GitHub lấy `main` làm nhánh mặc định nhưng nhánh này chỉ có commit khởi tạo. Source mới và lịch sử tích hợp nằm ở `develop`. Cả năm nhánh feature vẫn tồn tại trên GitHub.

Commit [6d1c614](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commit/6d1c6148652e093cca11fb2ac4c5be6fe3895f1d) nối lại hai nhánh gốc vào `develop`:

- Tân: giữ năm commit `cd33179`, `ffda145`, `8de1581`, `bdcdf9a`, `a83efe7`. Toàn bộ Git tree tại `a83efe7` trùng với commit gộp `6155348` đã có trên `develop`. Hai cách biểu diễn này thuộc cùng một phần triển khai, không phải hai lần làm độc lập.
- Tuấn: giữ commit notebook `80e8c17`. Notebook lịch sử xem được tại commit đó; bản hiện hành tiếp tục dùng reporting loader và schema mới, không khôi phục fallback sinh dữ liệu mẫu của notebook cũ.

Đợt sửa chỉ nối ancestry và bổ sung tài liệu. SHA, tên/email tác giả và ngày của các commit gốc được giữ nguyên. Git tree ngay sau merge khôi phục bằng tree trước merge; source chạy và notebook hiện tại không bị ghi đè. Nhánh `main` và các nhánh feature được giữ lại.

Chi tiết kiểm tra: [biên bản khôi phục](tasks/HISTORY_RECOVERY_2026-11-06.md).

Theo yêu cầu tiếp theo của nhóm, `main` được fast-forward từ `develop` sau khi khôi phục, rồi đặt lại làm nhánh mặc định. Vì giữ nguyên lịch sử Git, toàn bộ commit gốc của các thành viên cũng nằm trên `main`.

## Cách xem và tiếp tục đóng góp

Xem [lịch sử main](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/commits/main/) hoặc chạy:

```bash
git fetch origin
git log origin/main --graph --decorate --oneline
git shortlog -sne origin/main
git log origin/main --author="nguyentan10052006@gmail.com" --stat
```

`shortlog` đếm Git commit, gồm cả merge và bản gộp còn giữ trong lịch sử; số này không đo khối lượng hay chất lượng công việc.

Từ mốc `develop` mới nhất, mỗi thành viên tạo nhánh cho phần mình thực hiện, commit bằng danh tính của mình và mở PR về `develop`. Sau khi kiểm tra phần tích hợp, cập nhật `main` bằng fast-forward hoặc merge giữ lịch sử. Khi cần giữ từng commit gốc, dùng merge commit thay vì squash. Giữ các nhánh gốc tới hết đợt chấm; hạn chế viết lại lịch sử đã chia sẻ. Việc sửa tiếp Book vẫn dùng repository báo cáo hiện có để giữ nguyên URL nộp.
