# Đánh giá code M1–M2 — 04/11/2026

Phạm vi: workspace tại commit `f433d53852d40a82f65f35a3e5620c0d19f9a854`, đối chiếu code hiện tại và mẫu Drive đã tải để kiểm tra trước đó. Lần này không sửa crawler/parser, không thay dữ liệu Drive và không chạy lại crawl. Các số liệu Drive bên dưới là snapshot, không phải trạng thái live.

## Kiểm tra đã thực hiện

- `python -m pytest -q`: **263 passed, 1 warning trong 66,00 giây** trên Windows. Warning local báo phiên bản `requests`/`urllib3` hoặc charset không khớp dải được hỗ trợ; không kết luận Colab có cùng warning. Test local không chứng minh benchmark Colab hoặc đủ corpus.
- Trên mẫu Drive 10 paper/20 version ở `build/drive_audit_live_20261104/`, parser ghi **11 success, 5 partial, 4 error**. Validation cấu trúc ba bảng đạt trên mẫu này; không đồng nghĩa xử lý đầy đủ 20 version.
- Hai lỗi parser bên dưới tái hiện được độc lập bằng input nhỏ. Đã xác nhận `gather()` đọc được source của `2412.19115v1` và `2412.19119v1`; lỗi xảy ra ở `parse_hierarchy()` → `sentences()`.

## Việc nên sửa trước

### 1. M2: chia đoạn làm vỡ nhóm TeX

`src/parser/hierarchy.py` hàm `flush()` tách paragraph theo dòng trống trước khi gọi `sentences()`. Nếu một đối số TeX có dòng trống bên trong `{...}`, việc cắt khiến một mảnh còn `{` chưa đóng; `src/parser/latex.py` báo `Unclosed TeX group`. Input một dòng tương ứng chạy được. Đây là lỗi đã tái hiện bằng đoạn nhỏ, không cần tải lại nguồn:

```python
from src.parser.hierarchy import parse_hierarchy

text = "\\documentclass{article}\n\\begin{document}\n\\footnotetext{First paragraph.\n\nSecond paragraph.}\n\\end{document}"
parse_hierarchy(text)  # hiện báo ValueError: Unclosed TeX group
```

**Hướng sửa:** tách paragraph có nhận biết phạm vi nhóm/lệnh và các đoạn literal/math, hoặc thay cách chia để không đưa đối số chưa đóng vào `sentences()`. Thêm regression test cho đoạn nhỏ và hai paper thật; so sánh cây và câu, không chỉ kiểm tra hết exception.

### 2. M2: mất `%` trong URL BibTeX

`src/parser/bibliography.py:parse_bibtex()` gọi `strip_comments()` của TeX trên toàn bộ file `.bib`. Với giá trị URL có mã hóa `%2F`, hàm coi `%` là đầu comment, xóa phần còn lại của dòng và có thể làm mất dấu đóng `}`. Mẫu `2412.19118/v1/Ref.bib` có URL kiểu này và báo `Unclosed TeX group`.

```python
from src.parser.bibliography import parse_bibtex

text = '@article{sample, url={https://doi.org/10.1088%2F123}, title={Example}}'
parse_bibtex(text, 1)  # hiện báo ValueError: Unclosed TeX group
```

**Hướng sửa:** dùng xử lý comment phù hợp BibTeX và giữ nguyên `%` trong giá trị URL/nhóm/chuỗi; kiểm tra các trường hợp comment thật, dấu escape, chuỗi trích dẫn và ngoặc lồng. Chạy lại hai version `2412.19118` partial và xác minh các citation unresolved sau sửa. Không chỉnh source gốc để che lỗi.

### 3. M1: tránh duyệt lại quá nhiều khi S2 đang cooldown

`src/crawler/main.py:run_pipeline()` coi paper có `api_error` là pending; sau một lượt arXiv bị 429, `_run_with_rate_resume()` gọi lại pipeline, nên những paper còn lỗi S2 có thể được duyệt và ghi checkpoint nhiều lần. Ở snapshot Drive 21:38 có 729 ID nhưng 2.774 part publication; đây là dấu hiệu cần đo, chưa đủ để quy toàn bộ thời gian chậm cho I/O hoặc cho một nguyên nhân duy nhất.

**Hướng sửa:** tách lịch xử lý source chưa đủ khỏi hàng đợi references cần retry; khi S2 đang cooldown, không liên tục ghi lại cùng lỗi, vẫn giữ status `api_error` và thử lại khi được phép. Bảo toàn nguồn/refs tốt và dùng một đầu ghi checkpoint. Test mô phỏng 429 kéo dài, resume, crash giữa lô và bảo toàn dữ liệu; không tăng số kết nối để lách rate limit.

### 4. M1: giảm chi phí ghi và quét nhưng đo trước khi đổi

- Notebook đang ghép `BATCH_SIZE` bằng `S2_BATCH_SIZE=5`, trong khi CLI có tham số batch discovery và S2 riêng. `discover_metadata_batch()` hỗ trợ chia lô tối đa 100 ID. Có thể thử batch xử lý lớn hơn, giữ batch S2 riêng; khi đó số request metadata có thể giảm nếu lô chứa nhiều ID mới. Không suy ra tổng thời gian sẽ giảm theo cùng tỷ lệ.
- `CHECKPOINT_EVERY_PAPERS=1`: mỗi lần flush tạo part và tính lại summary/paper state trên các bản ghi hiện có. Profiler cũng quét kích thước các thư mục được theo dõi mỗi `PROFILE_INTERVAL_SEC=0.5`; khi corpus tăng, việc quét và ghi có thể tốn I/O. Chưa có số đo chứng minh đây là nút thắt lớn nhất.
- **Hướng sửa/thử:** tách hai kích thước batch trong notebook, thử checkpoint theo lô nhỏ và giảm tần suất quét đĩa độc lập với lấy mẫu RAM; đo phase, số request và độ trễ trên snapshot riêng. Test mất runtime trước/sau checkpoint và backup; lô lớn hơn có thể làm nhiều việc chưa được lưu hơn. Không đổi workload Colab đang chạy.

### 5. M1: xác minh ID/version trước khi kết luận

`src/crawler/discovery.py` hiện mặc định `v1` khi ID Atom không có suffix version, và đánh dấu ID không xuất hiện trong feed HTTP 200 là `missing_confirmed`. Một phép thử offline với feed hợp lệ chỉ chứa 1 trong 2 ID cho thấy ID còn lại được đánh dấu missing mà không kiểm tra riêng; chưa có bằng chứng feed thực tế đang bị trả thiếu. `_process_paper()` cũng có fallback `v1` nếu thiếu danh sách versions.

**Hướng sửa:** ghi `unknown`/`needs_verification` khi thiếu bằng chứng version hoặc feed không đủ để xác nhận; kiểm tra lại ID thiếu bằng cách được API hỗ trợ trước khi loại khỏi hàng đợi. Thêm test feed thiếu ID, lỗi entry, vắng suffix, ID thực sự không tồn tại và version metadata nhiều revision.

`REFERENCE_TERMINAL` gồm cả `not_indexed` và `bib_fallback`; validation đã đưa warning cho hai loại này. Khi báo cáo cần tách chúng khỏi số `success`/`empty` của Semantic Scholar, không gọi tất cả paper terminal là S2 thành công.

## Benchmark và triển khai

- `stats.runtime_sec` được chốt bằng `profiler.stop_and_export()` trước lần backup cuối có `include_outputs=True` trong `src/crawler/main.py`. `child_wall_sec` trong `run_metadata.json` của notebook bao gồm thời gian tiến trình con đến khi kết thúc, gồm backup cuối; nó vẫn không bao gồm cell validation chạy sau. Book cần phân biệt các mốc, dùng tổng wall time đúng phạm vi và tính riêng validation nếu có yêu cầu báo cáo.
- Profiler theo dõi các thư mục raw, shard và network state; `course_export_dir`/log ngoài shard và thư mục backup Drive không nằm trong danh sách `watch_dirs`. Cần xác định rõ phạm vi đĩa Colab và Drive, đo bổ sung nếu trình bày tổng dung lượng/đỉnh đĩa toàn pipeline.
- `LocalMutex` đặt lock trong thư mục tạm của từng VM, không đồng bộ nhiều runtime qua Drive. Không cho nhiều Colab cùng ghi một checkpoint/backup hoặc giả định cùng `network_state` là một rate limiter toàn cục.
- `colab_crawler.ipynb` hiện mặc định source 1 giây; [đề M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/) hướng dẫn 3 giây. Ghi đúng cấu hình của từng lượt; thay cấu hình chỉ ảnh hưởng lượt mới. Full hiện thông báo nếu chưa có smoke cùng hash nhưng không chặn; sau khi sửa code cần chủ động smoke/validation trên source mới.
- Book `build/book_offline_20261102/` là bản build cũ theo manifest base `630248c4ecf7796900e83718a1f4c8976468561c`, không phải bằng chứng cho code/data mới nhất. Cần build lại với input được chốt, ghi rõ phạm vi mẫu, benchmark CPU-only và triển khai Pages.

## Thứ tự thực hiện đề xuất

1. Giữ nguyên lượt Colab và backup hiện có; thực hiện sửa trên workspace/nhánh riêng.
2. Sửa hai lỗi parser, thêm test và chạy lại mẫu 20 version; kiểm tra thủ công TeX/Bib và các trường hợp partial.
3. Viết test mô phỏng S2 429/replay và cải tiến hàng đợi; sau đó thử tách batch và đo I/O ở dữ liệu mẫu, không đoán tốc độ toàn dải.
4. Rà soát discovery thiếu bằng chứng, metric end-to-end/disk và phân loại trạng thái references. Smoke source mới trước khi áp dụng lượt tiếp theo.
5. Hoàn thành audit source, retry phần lỗi, parser và validation theo các dải thực tế; build Book với phạm vi/số liệu thật và benchmark Colab CPU-only.
