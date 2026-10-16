# Phân công Nhiệm vụ Cá nhân — Nguyễn Quốc Đạt (Trưởng nhóm)

* **MSSV:** `24120282`
* **Nhánh làm việc:** `feat/metadata-discovery`
* **Khoảng ID được giao (Cột H – K):**
  * `start_month` (Cột H): `2024-12` (`2412`)
  * `start_id` (Cột I): `18848`
  * `end_month` (Cột J): `2025-01` (`2501`)
  * `end_id` (Cột K): `2641`
  * **Phạm vi mã bài báo:** Từ `2412.18848` đến hết tháng `12/2024`, nối tiếp từ `2501.00001` đến `2501.02641`.

## 1. Các tệp cần hiện thực trên nhánh này
1. `src/crawler/id_range.py`:
   * Viết hàm `normalize_yymm(month_str)` chuyển `"2024-12"` thành `"2412"`.
   * Viết hàm `find_last_id_of_month(yymm, start_seq)` tìm ID cuối cùng của tháng `2412` (và `2406` cho bạn Trí) bằng Binary Search.
   * Hoàn thiện generator `iter_assigned_arxiv_ids(start_month, start_id, end_month, end_id)`.
2. `src/crawler/discovery.py`:
   * Hoàn thiện hàm `discover_metadata_batch(arxiv_ids, rate_limit_sec=3.0)` gọi arXiv API theo từng lô 100 bài và lấy đủ danh sách các phiên bản (`versions`).
3. `docs/01_discovery_and_versions.ipynb`:
   * Trình bày phương pháp Entry Discovery và vẽ biểu đồ thống kê số lượng phiên bản bài báo.

## 2. Lệnh chạy thu thập dữ liệu cho khoảng ID cá nhân
```bash
python -m src.crawler.main \
    --member-id 24120282 \
    --start-month 2024-12 \
    --start-id 18848 \
    --end-month 2025-01 \
    --end-id 2641 \
    --output-dir data/shards/24120282
```

## 3. Input, output và các bước cần bổ sung

- Input: bốn mốc H–K; tháng nhận `YYYY-MM` hoặc `YYMM`, số thứ tự là số nguyên dương. Hai đầu khoảng đều được tính.
- `normalize_yymm(month_str: str) -> str`: đầu ra bốn ký tự, ví dụ `2024-12` → `2412`; báo lỗi rõ ràng khi tháng không hợp lệ.
- `find_last_id_of_month(yymm: str, start_seq: int = 1) -> int`: trả số thứ tự cuối tháng đã kiểm chứng. Không coi timeout/rate limit là ID không tồn tại; kiểm chứng cận trên thay vì mặc định mọi tháng kết thúc trước 30000.
- `iter_assigned_arxiv_ids(start_month, start_id, end_month, end_id) -> Iterator[str]`: trả ID không kèm `vN`, đệm đủ năm chữ số; không tự đặt số bài tháng đầu để ép đủ 5.000.
- `discover_metadata_batch(arxiv_ids: list[str], rate_limit_sec: float = 3.0) -> list[dict]`: trả metadata gồm ID, tiêu đề, tóm tắt, tác giả, phân loại và toàn bộ versions có thời điểm tạo, theo schema thống nhất với Trí. Phân biệt không tìm thấy với lỗi truy vấn.
- TODO: kiểm tra khoảng cùng tháng của Tuấn/Tân/Triết đủ 5.000 ID; kiểm tra chuyển tháng 12 sang tháng 1 và tháng 6 sang tháng 7.
- TODO: kiểm soát batch 50–100 ID, timeout/retry và thời gian chờ giữa mọi request, kể cả lúc tìm ID cuối tháng; đối chiếu OAI-PMH khi Atom không đủ lịch sử phiên bản.
- TODO: notebook trình bày độ phủ metadata, số phiên bản, ID thiếu và hạn chế của phương pháp.

## 4. Hoàn thành và tích hợp

Các lệnh trên là giao diện dự kiến sau khi thành viên tự hiện thực. Khung hiện tại chỉ có chữ ký hàm, docstring và `NotImplementedError`; kể cả bộ nhận tham số CLI cũng là TODO.

Trong trường hợp chữ ký ví dụ ở README khác với source, thống nhất theo source trong nhánh `main` và trao đổi với người tích hợp trước khi thay đổi giao diện.

- Tự viết logic của module được giao; không sửa module của thành viên khác nếu chưa thống nhất.
- Kiểm tra một tập ID nhỏ và trường hợp lỗi trước khi chạy toàn khoảng; ghi lại số liệu thật, không điền kết quả giả vào báo cáo.
- Chỉ commit code, notebook và tài liệu nhiệm vụ. Dữ liệu thô, Parquet trong shards và các tài liệu đầu vào cục bộ đã được bỏ qua bởi Git.
- Mở pull request về `main` khi hoàn tất, mô tả cách kiểm tra và những giới hạn còn lại.
