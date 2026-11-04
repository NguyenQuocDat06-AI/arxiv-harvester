# Cấu hình compilation root đã kiểm tra

`parser_roots.json` áp dụng cho metadata snapshot `36d23e5bc02fe31ac259ad9c710a116b68318e9e`.

Paper `2502.03238`, hai version v1/v2, có nhiều file khai báo document class. Root `elsarticle-template-num-camera_ready.tex` được chọn sau khi đối chiếu lệnh `\title` với metadata: *Long-tailed Medical Diagnosis with Relation-aware Representation Learning and Iterative Classifier Calibration*. File `elsdoc.tex` là tài liệu phụ, không phải root được chọn cho paper này.

Chạy parser với `--root-overrides configs/parser_roots.json`. Mapping có thể dùng một đường dẫn cho cả paper hoặc một đường dẫn riêng cho mỗi `vN`; mọi đường dẫn đều tương đối trong thư mục version. Giữ nguyên nguồn TeX, không xóa template/tài liệu phụ để ép parser chọn một file.

Khi thêm paper/version mới, đối chiếu nội dung và ghi lý do chọn root tại đây. Không đoán root theo tên file, thứ tự duyệt thư mục hoặc để một global preferred root áp dụng nhầm cho toàn corpus. Các override ngoài phạm vi chạy được ghi trong stats để rà lại.
