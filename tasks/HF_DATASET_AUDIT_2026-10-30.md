# Checklist còn lại để hoàn thành Milestone 1 và Milestone 2

Làm các mục còn lại theo thứ tự **04–12, rồi 19–24**, giữ số mục cũ để đối chiếu nhật ký. Các mục code **01–03, 13–18** đã được triển khai và kiểm thử offline/smoke; bằng chứng đã chuyển sang [nhật ký tiến trình](IMPLEMENTATION_PROGRESS_2026-11-01.md). Xác minh parser trên toàn corpus vẫn thuộc mục 19. Danh sách dựa trên code hiện tại và audit dataset `36d23e5` ngày 30/10/2026; số lỗi là mốc audit, chưa phải kết quả chạy lại. Mục **cần xác nhận** chưa có bằng chứng hoàn tất trong workspace/Hub và có thể đã được làm ở repo hoặc Moodle khác.

Mỗi mục gồm **vị trí sửa**, **các bước thực hiện** và **điều kiện kiểm tra hoàn thành**. Các công cụ audit/retry/dates/enrich/parser đã có CLI thật; phần còn lại chủ yếu là chạy trên dữ liệu đầy đủ, xác minh số đo và công bố/nộp bài. Tên log và cách lưu working data có thể điều chỉnh nhưng phải giữ được bằng chứng đối chiếu.

> **Cập nhật 01/11/2026:** người dùng xác nhận **chưa có corpus `.tex/.bib` đầy đủ**. Metadata/checkpoint không thay thế nguồn M1. Việc sửa code đang được thực hiện và ghi trong [nhật ký tiến trình](IMPLEMENTATION_PROGRESS_2026-11-01.md); chưa đánh dấu hoàn thành các bước cần corpus thật chỉ vì tool/test đã chạy. Cần thu thập nguồn trước khi audit, parse và benchmark toàn bộ 25.000 bài.

> **Cập nhật offline 02/11:** theo yêu cầu, đã dừng tải và làm tiếp phần code/validation/báo cáo. Bộ test đạt **139 passed**; tập cố định 12 paper/20 version có **15 success, 5 partial, 0 error** sau khi sửa root và parser. Validation năm bảng hợp lệ nhưng coverage mới **20/36.089 version**. Xem [tiến trình mới](IMPLEMENTATION_PROGRESS_2026-11-02.md); phần xử lý dữ liệu toàn corpus và Colab/Pages/Moodle vẫn chưa hoàn thành.

Bản merge/export kiểm tra local đã bảo toàn **25.000 paper, 36.089 version và 284.243 cặp reference có arXiv ID**, không trùng khóa hoặc orphan. Kết quả ở `data/course_metadata_20261101/metadata_validation.json`. Vẫn còn **3.770 ngày version**, **151 reference thiếu title**, **51 thiếu authors**, **135.750 thiếu date** và **135.285 thiếu S2 ID**; đây là số sau kiểm tra cấu trúc, chưa phải kết quả enrich. Có **9 xung đột định danh** được giữ riêng trong `data/processed_metadata_20261101/reference_identity_conflicts.json`, cần xác minh trước khi chốt dữ liệu.

## Milestone 1 — hoàn thiện dữ liệu, số đo và báo cáo


- [ ] **04. Bổ sung lịch sử ngày version.** Xác minh **3.770 ngày tạo còn thiếu**, cập nhật **2.458 paper thiếu lịch sử revision**. Export đã bỏ việc gán ngày latest cho version chưa biết ngày; còn thu thập và đối chiếu lịch sử thật.

  **Đã có / còn làm (01/11):** Tool `src/crawler/version_history.py` đã có; export không còn tự gán ngày latest. Lần thử OAI cho `2502.03243` timeout 45 giây, chưa bổ sung được ngày nào. Chạy `arxiv-reconcile-dates` theo README với snapshot lịch sử hoặc `--fetch-missing`; lưu `.history.json` và số thiếu trước/sau.

  **Sửa tại:** `_parse_entry()`/phần bổ sung metadata ở `src/crawler/discovery.py`, `export_to_course_spec()` trong `storage.py`; thêm script bổ sung ngày theo danh sách thiếu nếu cần.

  **Cách làm:**

  1. Đọc working publications, xuất các cặp `(arxiv_id, version)` có `created` null. Đối chiếu lại danh sách thay vì hard-code số 3.770 vào thuật toán.
  2. Lấy ngày của từng version từ metadata snapshot có lịch sử version hoặc nguồn lịch sử chính thức đã xác minh. Ghép bằng ID và số version, lưu nguồn/thời điểm lấy trong manifest hoặc schema đã cập nhật; kiểm tra provenance không bị normalizer loại bỏ khi ghi. Atom hiện chỉ cung cấp trực tiếp ngày v1 và latest nên không tự suy diễn các ngày giữa.
  3. Chuẩn hóa ngày có timezone về UTC; kiểm tra v1 không muộn hơn các revision và sort bằng số nguyên của `vN`. Chỉ bổ sung ngày khi nguồn đủ tin cậy; giữ riêng danh sách chưa xác minh được.
  4. Sau khi bổ sung ngày, chạy lại export bằng code đã sửa. Đối chiếu `revised_dates` với lịch sử đã xác minh và công bố phần vẫn thiếu; không thêm ngày giả để hết null.

  **Kiểm tra hoàn thành:** có ca v1–v4 với ngày khác nhau và ca version giữa chưa biết ngày. Export không tạo ngày giả; ví dụ `2502.03243` hết thiếu lịch sử khi đã xác minh v2/v3. Lưu báo cáo số thiếu trước/sau theo thành viên.

- [ ] **05. Đối chiếu nguồn thật với status.** Kiểm tra **32.645 version ghi success** có TeX/Bib hợp lệ; xác minh **2.531 version PDF-only** và giữ bản ghi rỗng đúng trường hợp; ghi lại mọi status không khớp tệp thực tế.

  **Đã có / còn làm (01/11):** Đã audit metadata local: 36.089 version, chỉ 2 version có TeX được xác minh; 36.087 version còn cần nguồn/bằng chứng local. Nhóm xác nhận chưa có corpus đầy đủ. Thu thập nguồn rồi chạy lại `arxiv-audit-sources --publications data/shards --raw-dir data/raw --output data/audits/sources.parquet`.

  **Sửa tại:** thêm script kiểm toán corpus, ví dụ `src/crawler/validate_sources.py` (đã triển khai); dùng lại `get_dir_size_bytes()` và quy tắc phân loại của `source_downloader.py`.

  **Cách làm:**

  1. Duyệt toàn bộ `(arxiv_id, version)` trong working publications và tìm đúng thư mục nguồn theo quy ước downloader. Ghi riêng thiếu thư mục, không đọc được tệp, sai size và tệp ngoài `.tex/.bib`; kiểm tra đuôi tệp không phân biệt hoa/thường.
  2. Với status success, kiểm tra có TeX thực tế và nguồn không rỗng; so size trên đĩa với `size_after_bytes`. Không yêu cầu compile PDF vì corpus chủ động bỏ ảnh/style; việc có `.bib` đơn độc cũng chưa xác nhận có full-text TeX.
  3. Với PDF-only, dùng bằng chứng phân loại còn lưu như magic bytes/response/archive đã nhận. Nếu không còn bằng chứng, ghi chưa xác minh và đưa vào danh sách kiểm tra lại; không suy ra PDF-only chỉ vì thư mục TeX rỗng.
  4. Xuất một bảng audit theo version, gồm status đang lưu, kết quả đối chiếu, đường dẫn và lý do. Tạo danh sách cần sửa/tải lại từ bảng này; không xóa dữ liệu đã xác nhận hợp lệ.

  **Kiểm tra hoàn thành:** mọi version trong snapshot có một dòng kiểm toán; phân biệt thành công đã xác nhận, empty được xác nhận, thiếu nguồn và lỗi. Số 32.645/2.531 chỉ là mốc đối chiếu, không phải giá trị mặc định của kết quả mới.

- [ ] **06. Tải bù đúng các version còn lỗi.** Xử lý **806 version lỗi + 107 version chưa có status**, cập nhật nguồn/status/size và checkpoint. Dùng endpoint theo version, pacing arXiv tối thiểu ba giây; ghi nguyên nhân những trường hợp vẫn chưa lấy được.

  **Đã có / còn làm (01/11):** Tool `arxiv-retry-sources` đã có, thử plan 10 version, chưa execute. Chạy plan trên manifest mục 05, xem kết quả rồi dùng `--execute`; sau khi có nguồn chạy audit lại. Danh sách local có thể lớn hơn 913 vì thiếu cả corpus, không chỉ các status lỗi cũ.

  **Sửa tại:** một script retry có manifest, ví dụ `src/crawler/retry_sources.py` (đã triển khai), kết hợp `download_and_clean_source()` và cơ chế resume đã sửa ở mục 01.

  **Cách làm:**

  1. Hợp nhất danh sách 806 lỗi + 107 thiếu status với các trường hợp không khớp corpus ở mục 05; khử trùng theo ID/version, chia theo MSSV và ghi `attempts/last_error/next_retry` nếu cần.
  2. Truyền ID kèm version, ví dụ `2502.03243v2`, vào downloader hiện có; dùng một kết nối arXiv, delay ít nhất ba giây và số lần retry hữu hạn. Tái sử dụng chức năng giải nén/lọc đang có thay vì viết downloader khác.
  3. Chỉ thay nguồn cũ sau khi staging mới đã kiểm tra thành công. Upsert đúng version vào working data, giữ các version khác, trạng thái references và lịch sử lỗi; cập nhật tổng size/status paper từ các version sau upsert.
  4. Thử trên vài ID gồm thành công/PDF-only/lỗi trước khi chạy cả danh sách. Với lỗi vẫn tồn tại, giữ trạng thái và bằng chứng; không tạo success để đóng danh sách.

  **Kiểm tra hoàn thành:** mỗi dòng manifest có kết quả lần thử, số chưa giải quyết và lý do; chạy lại không tải các version đã xác nhận xong hoặc tăng tổng size. Mọi CLI mới cho retry phải được hiện thực trước khi ghi lệnh sử dụng vào README.

- [ ] **07. Bổ sung metadata references.** Truy vấn/enrich nhóm **135.285 reference từ BibTeX fallback**; bổ sung ngày/title/authors khi xác minh được. Phân loại **10.394 paper chưa có arXiv-keyed reference** thành không có reference phù hợp, chưa lập chỉ mục hoặc lỗi truy vấn; báo rõ phần còn thiếu.

  **Đã có / còn làm (01/11):** Tool `arxiv-enrich-references` đã có; chỉ mới lập plan, chưa requery/enrich bulk. Sidecar cho dữ liệu cũ chưa được khôi phục từ API. Quy tắc ngày S2 khác ngày nộp arXiv phải được xác minh trước khi điền vào course export.

  **Sửa tại:** tái sử dụng `_fetch_s2_references()`/các hàm gọi API trong `reference_scraper.py`; thêm luồng enrich và cache metadata theo reference ID nếu cần.

  **Cách làm:**

  1. Ưu tiên truy vấn lại danh sách references của citing paper để xác nhận quan hệ trích dẫn và lấy đủ phân trang. Dùng status ở mục 02 lập danh sách chưa lập chỉ mục/lỗi/partial; dữ liệu cũ chưa có status phải được xác minh lại.
  2. Với reference đã có arXiv ID nhưng thiếu trường, tra metadata theo ID đó và cache theo ID duy nhất để nhiều citing paper dùng chung kết quả. Điền `paperId`, title, authors và ngày khi có; giữ nguồn của từng lần bổ sung.
  3. Tách provenance của cạnh trích dẫn khỏi provenance metadata: việc lấy được S2 ID cho một tài liệu fallback không chứng minh S2 đã trả cạnh citing → reference đó. Giữ thông tin gốc, không đổi toàn bộ fallback thành API success.
  4. Phân loại paper không có arXiv-keyed reference bằng kết quả thật: API trả rỗng, có references nhưng không có arXiv ID, chưa lập chỉ mục, partial hoặc lỗi. Tính lại số lượng sau khử trùng; không lấy `len(references)` làm số request thành công.
  5. Định nghĩa rõ ngày từ S2 và ngày nộp arXiv trong working data; chỉ điền `ref_submission_date` theo quy ước đã công bố, không tạo ngày từ năm hoặc điền tùy tiện để hết null. Tôn trọng hạn mức/backoff của API.

  **Kiểm tra hoàn thành:** có bảng số references theo nguồn, số đã enrich và số còn thiếu từng trường; các paper rỗng/lỗi có status kiểm chứng được. API tham chiếu: [Semantic Scholar Graph](https://api.semanticscholar.org/api-docs/graph).

- [ ] **08. Gộp và xuất lại dữ liệu M1 sau khi sửa.** Chạy lại merge/export hiện có cho `papers` và `references`; kiểm tra đủ 25.000 paper của snapshot, không trùng khóa, không mất version, không có citing paper mồ côi; cập nhật tỷ lệ thiếu và coverage theo từng thành viên/toàn nhóm.

  **Đã có / còn làm (01/11):** Đã merge toàn metadata snapshot pin `36d23e5bc02fe31ac259ad9c710a116b68318e9e` vào `data/processed_metadata_20261101/`: 25.000 paper, 36.089 version, 836.257 working references, không orphan. Course export có 284.243 cặp arXiv reference, bảo toàn toàn bộ khóa từ 5 shard. Đây là bản kiểm tra metadata trước repair; sau mục 04–07 vẫn phải merge/export lại. Stats 2 bài không dùng để tính tài nguyên toàn shard; 4 shard thiếu stats giữ metric null. Xác minh thêm 9 xung đột S2/DOI alias; không tự gộp hai arXiv ID khác nhau để giảm số dòng.

  **Sửa tại:** `merge_all_shards()` trong `merge_shards.py`, writer/export trong `storage.py`; bổ sung script validation cho working data và course export.

  **Cách làm:**

  1. Khi có nhiều bản cùng paper, merge versions theo số version, ưu tiên thông tin đã xác minh; không chỉ chọn một publication mới hơn rồi làm mất các version từ bản còn lại. Với references, nhận diện trường hợp cùng arXiv ID nhưng một bản có S2 ID, một bản chỉ có fallback để hợp nhất metadata, tránh giữ hai bản khác khóa phụ.
  2. Kiểm tra điều kiện đầu vào merger: hiện mỗi shard phải có `publications.parquet`, `references.parquet`, `stats.json`. Tìm stats gốc nếu có; nếu thiếu, cho phép một chế độ merge dữ liệu hợp lệ có báo cáo thiếu stats và metric null, không bịa số đo hoặc dùng `--skip-corrupted` để âm thầm mất cả shard.
  3. Chạy merge hiện có, sau đó gọi `export_to_course_spec()` trên thư mục đã gộp. Ví dụ lệnh merge ở repo root: `python -m src.crawler.merge_shards --shards-dir data/shards --output-dir data/processed`; chỉ chạy sau khi đã xử lý điều kiện ở bước trên.
  4. Validation: so tập ID với dải được giao, kiểm tra unique paper/cặp reference, khóa bắt buộc, ngày/version và tổng size. Mọi citing paper phải có trong papers; reference target không cần thuộc dải ID nhóm.
  5. Sửa thống kê đang cộng `success + partial_success` thành paper success và đếm mọi status khác null thành version có nguồn: xuất riêng tỷ lệ TeX success, version đã xác nhận và phần partial/lỗi. Ghi cùng revision dữ liệu và số thay đổi trước/sau.

  **Kiểm tra hoàn thành:** đủ 25.000 paper của snapshot đã chọn, không mất version sau retry/merge, không có khóa lỗi hoặc orphan citing paper; số liệu metadata không bị dùng thay cho benchmark chưa có.

- [ ] **09. Chạy benchmark M1 chính thức trên Colab CPU-only.** Lưu thời gian từng bài/trung bình/discovery/toàn pipeline, peak/average RAM, peak/final disk, môi trường và phạm vi thực sự chạy. Tệp benchmark công khai hiện chỉ là run hai bài ngoài Colab.

  **Đã có / còn làm (01/11):** Đã có profiler theo run/paper, peak disk và tổng RSS chính/con; `colab_crawler.ipynb` qua 11 kiểm tra offline. Chưa chạy benchmark Colab. Cần đưa source mới lên commit mà notebook dùng và chạy trong Colab CPU-only với dữ liệu thật.

  **Sửa tại:** kịch bản Colab/CLI, phần lưu run ở `main.py` và notebook `docs/05_performance_benchmark.ipynb`.

  **Cách làm:**

  1. Chọn Colab CPU-only, cài đúng commit và dependencies; tạo thư mục logs trước khi chạy, ghi cấu hình/CPU/RAM/Python và phạm vi ID. Dùng raw/output dir riêng để cache/checkpoint cũ không làm sai ý nghĩa một lần crawl mới.
  2. Chạy end-to-end trên phạm vi được báo cáo, gồm discovery, nguồn, references, lưu/gộp/export. Không dùng `--max-papers 2` làm số đo đại diện toàn dải; smoke test nhỏ được lưu riêng.
  3. Trên Colab có thể bọc lệnh hiện có bằng `/usr/bin/time -v -o logs/<run_id>.time.txt python -m src.crawler.main ...`. Thay `...` bằng đủ tham số dải ID, raw/output dir và pacing; dùng profiler ở mục 03 để có average RAM, peak disk và thời gian từng paper.
  4. Nếu gián đoạn, lưu stats từng run rồi resume. Báo các lần chạy và thời gian xử lý thực; nếu cộng wall time các phiên thì ghi đó là tổng thời gian chạy, không coi như một phiên liên tục hoặc chia cho bộ đếm checkpoint sai phạm vi.

  **Kiểm tra hoàn thành:** có log CPU-only, số bài/version thực sự xử lý, thời gian từng bài/trung bình/discovery/toàn hệ thống, peak/average RAM và peak/final disk; dữ liệu cache hoặc nguồn bị thiếu được công bố đúng.

- [ ] **10. Hoàn thiện số liệu trong năm notebook M1 đã có.** Cập nhật tỷ lệ thành công, version coverage, dung lượng trung bình trước/sau trên cùng tập hợp lệ, số references trung bình và tỷ lệ lấy metadata thành công; thêm benchmark, nhận xét và giới hạn bằng số liệu thật. Bảng/biểu đồ phải sinh khi build book.

  **Đã có / còn làm (01/11):** Năm notebook đã chuyển sang đọc saved inputs và sinh bảng/biểu đồ khi build. Cần thay inputs đã sửa đủ và benchmark Colab thật; không lấy smoke local hoặc reported status làm bằng chứng corpus đã đủ.

  **Sửa tại:** năm notebook `docs/01_discovery_and_versions.ipynb` đến `docs/05_performance_benchmark.ipynb`.

  **Cách làm:**

  1. Đổi cell đọc dữ liệu sang working tables/validation/run logs đã chốt, có đường dẫn cấu hình và kiểm tra `is_mock`; không dựa vào outputs cũ còn trong notebook.
  2. Notebook 01 trình bày version coverage/ngày còn thiếu; notebook 02 trình bày status nguồn và size trước/sau trên cùng tập hợp lệ; notebook 03 trình bày references theo nguồn, API success/fallback/missing; notebook 04 kiểm tra khóa/schema/coverage; notebook 05 đọc benchmark chính thức.
  3. Tính lại công thức từ dữ liệu: size trung bình là tổng size các version theo paper rồi lấy trung bình tập hợp lệ; references trung bình dùng working references và trạng thái rỗng/lỗi; tỷ lệ API thành công nêu mẫu số paper/request rõ ràng. Không đổi missing thành 0 để tăng mẫu số.
  4. Để code tạo bảng/plot khi build, thêm nhận xét theo kết quả thật và giới hạn. Khi thiếu dữ liệu thì build phải thông báo rõ; không tự sinh mock hoặc gọi crawler để bù trong lúc build.

  **Kiểm tra hoàn thành:** xóa outputs rồi build lại từ đúng revision dữ liệu vẫn sinh đủ bảng/biểu đồ và số liệu khớp validation, không có request crawl thật phát sinh trong build.

- [ ] **11. Hoàn thiện README và bản báo cáo M1 công khai — cần xác nhận phần đã làm ở repo khác.** Thay link placeholder và hướng dẫn/TODO cũ bằng thông tin thực tế; kiểm tra cài/chạy từ môi trường sạch. Build các notebook thành Jupyter Book ở repo riêng, host GitHub Pages và kiểm tra link không cần đăng nhập.

  **Đã có / còn làm (01/11):** README/entry points/CI đã cập nhật; đã build HTML local của book 8 chương. Source repo book và workflow Pages đã chuẩn bị trong `build/book_source/`, chưa publish hoặc kiểm tra public URL. Nếu nhóm đã có repo book, cập nhật chính repo đó.

  **Sửa tại:** `README.md`, `requirements.txt`/`pyproject.toml`, imports liên quan packaging; cấu hình và workflow trong repo Jupyter Book riêng nếu đã có.

  **Cách làm:**

  1. Xác nhận repo book/Pages hiện có trước khi tạo mới; thay `<username>`, link search trung gian, mô tả skeleton/TODO và endpoint/allowlist cũ bằng thông tin thật. Ghi rõ cách cài, thư mục chạy, input/output và cách resume/retry.
  2. Kiểm tra entry point sau `pip install -e .`. `pyproject.toml` cài package `crawler` nhưng một số imports đang đi qua `src.crawler`: chuẩn hóa imports tương đối/nội bộ và chọn một cách chạy cài đặt nhất quán; thử cả CLI từ ngoài repo để phát hiện phụ thuộc thư mục hiện tại. Không chỉ kiểm tra cài thành công.
  3. Trong repo book, pin phiên bản Jupyter Book, lấy các chương và dữ liệu thống kê đúng commit/revision. Chọn cấu hình/lệnh theo bản đang dùng: v1 dùng `_config.yml`, `_toc.yml`, `jupyter-book build .`; v2 dùng cấu hình MyST và `jupyter book build --html`. Không trộn hai hệ cấu hình. Tham chiếu [v1](https://jupyterbook.org/v1/start/build.html), [v2](https://jupyterbook.org/latest/build-and-publish/publish/).
  4. Bật thực thi notebook khi build theo phiên bản đã chọn; workflow tải inputs thống kê được pin rồi build/deploy HTML lên Pages. Đảm bảo inputs không chứa corpus thô trong source repo và build không gọi crawler.

  **Kiểm tra hoàn thành:** cài/chạy CLI trên môi trường sạch được; book build thành công, link Pages mở được khi không đăng nhập và hiển thị đúng số liệu mới. Phần nào đã xong ở repo khác chỉ cần đối chiếu và ghi link bằng chứng.

- [ ] **12. Nộp hoặc xác nhận đã nộp M1.** Kiểm tra hạn nộp và xác nhận Moodle cho hai link public: source repo và Jupyter Book M1; lưu commit/bản báo cáo dùng khi nộp.

  **Đã có / còn làm (01/11):** Chưa thao tác Moodle hoặc xác minh bài nộp hiện có trong lần sửa này.

  **Thực hiện tại:** Moodle và hai trang public, không cần viết thêm module crawler.

  **Cách làm:**

  1. Kiểm tra trạng thái bài nộp hiện tại và thông báo/hạn nộp chính thức; nếu đã nộp thì đối chiếu link và bản báo cáo, không tự xem đó là chưa nộp hoặc tự thay bài.
  2. Mở source repo và trang chương M1 ở chế độ không đăng nhập; kiểm tra public, không phải link file local, không lỗi Pages và nội dung đúng ngôn ngữ yêu cầu.
  3. Người đại diện nhóm nộp hai link theo form Moodle nếu còn cần nộp. Lưu xác nhận cùng commit code, revision dữ liệu, URL và bản báo cáo dùng tại thời điểm nộp.

  **Kiểm tra hoàn thành:** có xác nhận nộp M1, hai link đúng và bản nội dung tương ứng; việc dữ liệu có trên Hub không thay thế xác nhận này.

## Milestone 2 — hiện thực parser, xử lý toàn corpus và nộp báo cáo

Parser ở `src/parser/` và ba chương báo cáo M2 đã triển khai, kiểm thử và chạy trên tập cố định 12 paper/20 version. Các mục dưới đây còn cần corpus đầy đủ, xác minh chất lượng trên dữ liệu thật, benchmark Colab và công bố/nộp bài.


- [ ] **19. Kiểm tra parser trên tập nhỏ rồi xử lý toàn corpus.** Kiểm tra nhiều tệp, nhiều version, include/comment, toán, list và cite trùng; đối chiếu TeX với kết quả. Sau đó chạy mọi paper/version từ M1, lưu empty/lỗi riêng và kiểm tra liên kết cả năm bảng M1–M2.

  **Đã có / còn làm (02/11):** 139 tests qua; tập 12 paper/20 version có 15 success, 5 partial, 0 error; 7.690 elements, 12.924 edges, 272 BibTeX entries. Đã có root overrides theo paper/version, validation theo batch/index trên đĩa và CLI kiểm tra năm bảng. Còn đối chiếu các partial và chạy mọi paper/version sau khi có corpus; không dùng metadata thiếu nguồn làm bản rỗng hợp lệ.

  **Làm tại:** `tests/test_parser_*.py` và `src/parser/main.py` (đã triển khai), dùng các module ở mục 13–18.

  **Cách làm:**

  1. Tạo fixture offline nhỏ cho include lồng/comment, heading có dấu sao, math, list, figure/table, sentence edge cases, cite đổi key và text chuyển parent. Mỗi ca kiểm tra nội dung/cạnh đầu ra mong muốn, không chỉ kiểm tra hàm có trả kết quả.
  2. Viết orchestrator đọc manifest M1, xử lý các version theo số thứ tự cho từng paper: gather → hierarchy → normalization/canonical cites → dedup → export. Ghi `success`, `partial`, `empty_no_tex`, `error` và nguyên nhân tách biệt.
  3. Thử trên paper thật có nhiều version rồi đối chiếu thủ công với TeX/source map. Sửa nguyên nhân trước khi chạy toàn bộ; đoạn chưa hỗ trợ phải được báo partial/lỗi thay vì âm thầm bỏ.
  4. Khi chạy toàn corpus, checkpoint theo paper/version cùng hash input và code/config. Chỉ tái sử dụng kết quả khi các giá trị đó còn khớp; nếu thay quy tắc dedup của paper thì tái xử lý các version liên quan và cập nhật mapping nhất quán.
  5. Chạy validation năm bảng sau mỗi shard và khi hoàn tất; không làm mất paper/version không parse được khỏi manifest hoặc tự coi chúng là version rỗng.

  **Lệnh kiểm tra hiện có:** `arxiv-validate-project --course-dir data/course_export --parsed-dir data/parsed --publications data/processed/publications.parquet --output data/parsed/project_validation.json --require-full`. Cấu trúc hợp lệ nhưng scope còn thiếu/partial/error trả exit code 2; không dùng một lần validation subset thành công để xác nhận toàn corpus.

  **Kiểm tra hoàn thành:** tests về nội dung và cấu trúc qua được, có báo cáo validation cho corpus thật, resume không ghi trùng và sửa cấu hình không trộn đầu ra của hai quy tắc khác nhau.

- [ ] **20. Tổng hợp thống kê M2.** Tính parsing success rate, coverage từng paper/version, số elements và BibTeX entries trước/sau dedup; nêu mẫu số, version rỗng, lỗi và cite chưa resolve.

  **Đã có / còn làm (02/11):** Thống kê đã tách recorded/parsed/success coverage, diagnostics, unresolved/conflicts và counts chưa đo. Có kết quả 12 paper/20 version và đối chiếu 20/36.089 version với toàn M1; cần thống kê lại sau run toàn corpus, không ngoại suy tỷ lệ từ tập nhỏ.

  **Làm tại:** một script thống kê M2, ví dụ `src/parser/statistics.py`, đọc manifest và counts trước/sau đã lưu.

  **Cách làm:**

  1. Lấy mẫu số từ danh sách paper/version M1; thống kê riêng có nguồn, không có TeX, chưa có nguồn, parse thành công/partial/lỗi. Báo parsing success trên version có nguồn và coverage trên toàn version kỳ vọng, ghi rõ công thức.
  2. Xuất bảng theo publication: expected versions, versions có nguồn, success, partial, empty và error. Đảm bảo tổng các nhóm khớp mẫu số và không chỉ đếm latest version.
  3. Đếm occurrences/elements sau chuẩn hóa nhưng trước dedup và unique elements sau dedup; làm tương tự với BibTeX entries. Khi tính mức giảm dùng `(before - after) / before` và ghi không áp dụng nếu before bằng 0.
  4. Báo theo loại nội dung và theo paper, số cite unresolved, field conflicts và lỗi parser chính. Counts phải lấy từ pipeline/manifest trước và sau biến đổi; không thể dựng counts trước dedup chỉ từ bảng cuối.

  **Kiểm tra hoàn thành:** tổng counts khớp ba bảng và manifest, có bảng coverage từng paper cùng số trước/sau dedup thực sự đo được, không suy diễn từ tỷ lệ mẫu.

- [ ] **21. Chạy benchmark parser trên Colab CPU-only.** Đo wall time end-to-end, thời gian trung bình/publication, peak RAM và dung lượng đầu ra cuối; lưu cấu hình/log riêng với benchmark crawler.

  **Đã có / còn làm (01/11):** CLI parser đã có profiler/run history; chưa benchmark Colab. Tải corpus đúng revision trước khi đo rồi chạy `arxiv-parser` với input/output riêng; lưu `/usr/bin/time -v`, stats/samples và phạm vi đã xử lý.

  **Làm tại:** kịch bản Colab cho parser, phần ghi run metrics trong `src/parser/main.py`, tái sử dụng profiler đã sửa ở mục 03 khi phù hợp.

  **Cách làm:**

  1. Chọn Colab CPU-only và tải corpus M1 đúng revision trước khi đo; ghi cấu hình parser/input hash, commit và giới hạn bộ nhớ/đĩa. Thời gian tải corpus/cài môi trường được ghi riêng với thời gian chạy parser.
  2. Bắt đầu đo trước gathering, dừng sau khi normalize, dedup và ghi hết dữ liệu cuối. Lưu thời gian từng paper và wall time toàn run; nêu cách xử lý các lỗi/empty và mẫu số thời gian trung bình.
  3. Lấy peak RAM của tiến trình chính và các tiến trình con; đo dung lượng cuối của ba bảng và các đầu ra parser thực sự cần giữ. Nếu báo cả working data thì tách khỏi kích thước Parquet xuất chuẩn.
  4. Lưu log/samples riêng từng run; kiểm chứng bằng `/usr/bin/time -v` nếu dùng. Khi thêm CLI parser, công bố rõ lệnh benchmark và cấu hình, không dùng lệnh đề xuất chưa hiện thực làm bằng chứng đã chạy.

  **Kiểm tra hoàn thành:** có wall time end-to-end, trung bình/publication, peak RAM, final output size trên corpus được nêu rõ; báo cáo M2 dùng số đo parser này thay vì số đo crawler.

- [ ] **22. Viết chương M2 vào cùng Jupyter Book M1.** Giải thích gathering, hierarchy, normalization và hai mức dedup; thêm ví dụ trước/sau, thống kê, benchmark và giới hạn. Sinh bảng/biểu đồ bằng code khi build.

  **Đã có / còn làm (02/11):** Book 8 chương đã build lại với toàn metadata M1 và tập M2 cố định 12 paper/20 version. Các trang hiện rõ partial/diagnostics/coverage và từ chối input/run stale. Cần cập nhật thống kê/benchmark toàn corpus và rà ví dụ trước/sau khi mục 19–21 xong.

  **Làm tại:** các chương mới trong cùng repo Jupyter Book M1; có thể chia thành gathering/hierarchy, standardization/dedup và benchmark M2.

  **Cách làm:**

  1. Thêm chương vào mục lục book hiện có; giữ các chương M1 và ghi rõ corpus/code revision dùng cho M2, không tạo một book riêng thay thế lịch sử báo cáo.
  2. Với gathering/hierarchy, chọn ví dụ root/include, tệp dư và một đoạn nhiều loại leaf; tạo bằng code bảng/cây minh họa từ output thật và nguồn tương ứng.
  3. Với normalization/dedup, thể hiện raw → normalized, đổi key/union fields và element chung qua hai version; giải thích các lựa chọn và ca chưa hỗ trợ, không chỉ trình bày số dòng cuối.
  4. Đọc thống kê mục 20 và log mục 21 khi build để sinh bảng/biểu đồ; kiểm tra input thiếu thì báo rõ, không tự chạy parser toàn corpus trong quá trình build báo cáo.

  **Kiểm tra hoàn thành:** build mới từ các inputs đã chốt sinh được chương M2, ví dụ trước/sau và benchmark; người đọc truy được mỗi kết quả về output/manifest liên quan.

- [ ] **23. Hoàn thiện bản code và báo cáo M2 có thể chạy lại.** Đưa parser vào source repo chung, cập nhật dependencies/README/lệnh chạy; kiểm tra môi trường sạch, build book và bản GitHub Pages public chứa cả M1–M2.

  **Đã có / còn làm (01/11):** Đã bổ sung package/dependencies/CLI/README/CI offline. Còn publish source mới và cập nhật Pages của cùng repo book; kiểm tra public URL và tái tạo từ commit/input revision đã chốt.

  **Sửa tại:** `README.md`, dependency files, package configuration và `.github/workflows/ci.yml` của source repo; workflow deploy trong repo book.

  **Cách làm:**

  1. Thêm parser vào package của cùng source repo và chốt module/CLI thật sau khi hiện thực. Ghi đầy đủ tham số input corpus, output, checkpoint/resume và chế độ chạy mẫu/toàn bộ; không để ví dụ gọi module hoặc cờ chưa có.
  2. Pin môi trường đã kiểm chứng, kiểm tra imports và entry points sau cài đặt; chạy smoke từ môi trường sạch theo đúng README. Ghi cách lấy dữ liệu đúng revision thay vì phụ thuộc đường dẫn trên máy thành viên.
  3. Mở rộng CI hiện chỉ kiểm tra syntax/notebook JSON/install: cài dependencies kiểm thử, chạy `python -m pytest -q` cho các tests hành vi M1 và parser mới bằng fixture offline. Kiểm tra entry point hoạt động, không gọi arXiv/S2 trong unit tests; lỗi test phải làm CI thất bại.
  4. Build lại book và kiểm tra chương M1/M2, asset, đường dẫn tương đối và public URL. Source repo chỉ giữ code/notebook/tài liệu cần thiết; corpus và artifact dữ liệu được tham chiếu từ vị trí phù hợp.

  **Kiểm tra hoàn thành:** người khác cài sạch, chạy mẫu M1/M2 và tái tạo bảng/biểu đồ theo hướng dẫn được; CI kiểm tra hành vi qua được, các link public đúng nội dung mới.

- [ ] **24. Nộp hoặc xác nhận đã nộp M2.** Kiểm tra hạn nộp và xác nhận Moodle cho link source repo cùng Jupyter Book M2; lưu commit, bản corpus và báo cáo tương ứng.

  **Đã có / còn làm (01/11):** Chưa thao tác Moodle. Chỉ xác nhận hoàn tất khi có bằng chứng nộp cùng commit code, revision corpus và URL book đúng bản.

  **Thực hiện tại:** Moodle, source repo và GitHub Pages của cùng Jupyter Book.

  **Cách làm:**

  1. Kiểm tra bài nộp M2 hiện có, yêu cầu/hạn nộp và người đại diện nhóm; nếu đã nộp thì đối chiếu nội dung thay vì mặc định cần gửi lại.
  2. Mở source repo và chương M2 không đăng nhập; xác nhận có code parser, hướng dẫn chạy, số liệu/parser benchmark và vẫn truy cập được phần M1.
  3. Nộp hai link theo form Moodle khi còn cần nộp; lưu xác nhận cùng commit code, revision corpus, URL book và bản báo cáo tương ứng.
  4. Bàn giao manifest, năm bảng/working data, mapping cite/element và danh sách giới hạn cho cả nhóm để giai đoạn sau dùng đúng đầu vào.

  **Kiểm tra hoàn thành:** có xác nhận nộp M2 với hai link hợp lệ và bộ kết quả M1–M2 truy được về đúng phiên bản; các việc matching/poster được theo dõi riêng ở M3.

Yêu cầu đối chiếu: [Milestone 1 — Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/) và [Milestone 2 — Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/). Hai milestone này nộp link code/báo cáo; dữ liệu giữ để xử lý tiếp và nộp ở M3.
