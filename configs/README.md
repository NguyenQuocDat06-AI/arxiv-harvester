# Cấu hình compilation root đã kiểm tra

`parser_roots.json` áp dụng cho metadata snapshot `36d23e5bc02fe31ac259ad9c710a116b68318e9e`.

Paper `2502.03238`, hai version v1/v2, có nhiều file khai báo document class. Root `elsarticle-template-num-camera_ready.tex` được chọn sau khi đối chiếu lệnh `\title` với metadata: *Long-tailed Medical Diagnosis with Relation-aware Representation Learning and Iterative Classifier Calibration*. File `elsdoc.tex` là tài liệu phụ, không phải root được chọn cho paper này.

Chạy parser với `--root-overrides configs/parser_roots.json`. Mapping có thể dùng một đường dẫn cho cả paper hoặc một đường dẫn riêng cho mỗi `vN`; mọi đường dẫn đều tương đối trong thư mục version. Giữ nguyên nguồn TeX, không xóa template/tài liệu phụ để ép parser chọn một file.

Khi thêm paper/version mới, đối chiếu nội dung và ghi lý do chọn root tại đây. Không đoán root theo tên file, thứ tự duyệt thư mục hoặc để một global preferred root áp dụng nhầm cho toàn corpus. Các override ngoài phạm vi chạy được ghi trong stats để rà lại.

## Root của snapshot nộp 06/11

`submission_parser_roots_20261106.json` dùng cho snapshot Drive 73 paper. Các lựa chọn được đối chiếu bằng nội dung title và vai trò của file:

- `2412.18977v1`: `ijcai25.tex` khớp title paper; file còn lại là supplementary.
- `2412.20260v1/v2`: `Main_CA1.tex` là bài chính có title và compilation path; các root còn lại là tài liệu thành phần. Title v1 khác title metadata mới nhất, được giữ đúng theo source v1.
- `2412.20270v1`: `main-arxiv.tex` là bài chính, phân biệt với supplementary.
- `2412.20285v2`: `main_fkrb_management_science.tex` có title khớp metadata; các file còn lại gồm bản thảo, memo và slides.

`2412.20337v1` có hai root cùng title; chưa có bằng chứng chọn root nên parser vẫn ghi lỗi, không thêm override tùy ý.
