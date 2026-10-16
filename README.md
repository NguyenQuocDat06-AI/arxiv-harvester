# arxiv-harvester — Project Milestone 1: Data Crawling Pipeline

Dự án thu thập dữ liệu bài báo khoa học từ kho lưu trữ mở **arXiv** (mã nguồn LaTeX toàn văn, metadata đa phiên bản và mạng lưới trích dẫn từ Semantic Scholar) thuộc học phần **Nhập môn Khoa học Dữ liệu (Introduction to Data Science)** — thực hiện theo đặc tả tại [Project Milestone 1 — Data Crawling](https://www.google.com/search?q=https%3A%2F%2Fhcmus-cs-ta.github.io%2Flab-book%2Fintro-ds%2Fstatement%2Fcrawling%2F).

## 1. Thông tin chung & Liên kết nộp bài

* **Đặc tả đề bài:** [Project Milestone 1 — Data Crawling](https://www.google.com/search?q=https%3A%2F%2Fhcmus-cs-ta.github.io%2Flab-book%2Fintro-ds%2Fstatement%2Fcrawling%2F)
* **Source Code Repository:** `https://github.com/<username>/arxiv-harvester`
* **Jupyter Book Repository (Milestone 1 & 2):** `https://github.com/<username>/arxiv-harvester-book`
* **Link nộp chính thức (GitHub Pages — cố định URL):** `https://<username>.github.io/arxiv-harvester-book/`

> **Lưu ý nộp bài đốc thúc tiến độ:** Đại diện nhóm nộp đường dẫn GitHub Pages (`github.io`) của Jupyter Book tương ứng với Milestone 1 và 2. Nhóm tiếp tục cập nhật số liệu và hoàn thiện nội dung sau hạn nộp này cho đến trước hạn nộp Poster trên cùng đường link cố định.

## 2. Danh sách Thành viên, Nhánh Làm việc & Khoảng ID Cá nhân (Cột H – K)

Mỗi thành viên đảm nhận một khoảng ID riêng được cấp trên trang tính đăng ký (Cột H: `start_month`, Cột I: `start_id`, Cột J: `end_month`, Cột K: `end_id`) và làm việc trên **nhánh Git riêng** cùng **1 module kỹ thuật độc lập**:

| STT | MSSV | Họ và tên | Vai trò | `start_month` (Cột H) | `start_id` (Cột I) | `end_month` (Cột J) | `end_id` (Cột K) | Dải mã arXiv (`YYMM.NNNNN`) | Nhánh làm việc (`Git Branch`) | File đặc tả cá nhân trên nhánh |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `24120282` | **Nguyễn Quốc Đạt** | Trưởng nhóm | `2024-12` | `18848` | `2025-01` | `2641` | `2412.18848` → `2501.02641` *(vắt qua 2 tháng)* | `feat/metadata-discovery` | `tasks/TASK_24120282_NguyenQuocDat.md` |
| **2** | `24120237` | **Nguyễn Đình Tuấn** | Thành viên | `2025-02` | `3235` | `2025-02` | `8234` | `2502.03235` → `2502.08234` *(5.000 ID cùng tháng)* | `feat/source-downloader` | `tasks/TASK_24120237_NguyenDinhTuan.md` |
| **3** | `24120438` | **Trần Nguyên Tân** | Thành viên | `2024-07` | `12839` | `2024-07` | `17838` | `2407.12839` → `2407.17838` *(5.000 ID cùng tháng)* | `feat/reference-extraction` | `tasks/TASK_24120438_TranNguyenTan.md` |
| **4** | `24120470` | **Dương Phan Minh Trí** | Thành viên | `2024-06` | `17938` | `2024-07` | `2838` | `2406.17938` → `2407.02838` *(vắt qua 2 tháng)* | `feat/data-storage` | `tasks/TASK_24120470_DuongPhanMinhTri.md` |
| **5** | `24120474` | **Trịnh Vỹ Triết** | Thành viên | `2024-06` | `12938` | `2024-06` | `17937` | `2406.12938` → `2406.17937` *(5.000 ID cùng tháng)* | `feat/cli-and-profiling` | `tasks/TASK_24120474_TrinhVyTriet.md` |

## 3. Phân công Module Kỹ thuật & Chương Báo cáo Độc lập

Để 5 thành viên code độc lập mà không phải chờ nhau và không xảy ra xung đột Git (merge conflict), dự án tách biệt hoàn toàn theo từng tệp:

| Thành viên | Module Code phụ trách (`src/crawler/`) | Chương Jupyter Book (`docs/`) | Phân vùng dữ liệu cá nhân (`data/shards/`) | Tóm tắt nhiệm vụ kỹ thuật cần tự hiện thực |
| :--- | :--- | :--- | :--- | :--- |
| **1. Nguyễn Quốc Đạt** (`24120282`) | `id_range.py`<br>`discovery.py` | `01_discovery_and_versions.ipynb` | `data/shards/24120282/` | • Chuyển đổi `YYYY-MM` sang `YYMM` và sinh dải ID (xử lý dải cùng tháng và dải vắt tháng bằng Binary Search tìm ID cuối tháng).<br>• Truy vấn theo lô (Batch Query `id_list`) qua arXiv API & [arXiv OAI-PMH](https://www.google.com/search?q=https%3A%2F%2Fexport.arxiv.org%2Foai2) lấy đủ các phiên bản (`v1`, `v2`,...).<br>• Khởi tạo repo `arxiv-harvester` và `arxiv-harvester-book` (GitHub Pages). |
| **2. Nguyễn Đình Tuấn** (`24120237`) | `source_downloader.py` | `02_source_download_and_cleaning.ipynb` | `data/shards/24120237/` | • Tải tệp nguồn từ `https://export.arxiv.org/e-print/{id}` theo luồng (Streaming Download), kiểm soát rate limit 1 request / 3 giây.<br>• Kiểm tra định dạng tệp nén (`.tar.gz`, `.gz` đơn hay `.pdf`), giải nén vào `data/raw/unzipped/{id}/`.<br>• Đo dung lượng trước và sau khi lọc xóa toàn bộ tệp hình ảnh (`.png`, `.jpg`, `.pdf`, `.eps`,...). |
| **3. Trần Nguyên Tân** (`24120438`) | `reference_scraper.py` | `03_reference_extraction.ipynb` | `data/shards/24120438/` | • Thu thập danh sách tài liệu tham khảo qua Semantic Scholar API (`ARXIV:{id}` hoặc Batch POST endpoint).<br>• Quản lý giới hạn 100 requests / 5 phút, tự động chờ và thử lại (Exponential Backoff) khi gặp HTTP `429`.<br>• Viết bộ lọc Regex đọc tệp `.bib`/`.bbl` dự phòng khi bài báo chưa có trên Semantic Scholar. |
| **4. Dương Phan Minh Trí** (`24120470`) | `storage.py`<br>`generate_mock_data.py`<br>`merge_shards.py` | `04_schema_and_data_quality.ipynb` | `data/shards/24120470/` | • Khai báo schema `pyarrow` cho `publications.parquet` và `references.parquet`.<br>• Viết script sinh dữ liệu mẫu (`generate_mock_data.py`) để cả nhóm test biểu đồ báo cáo trước khi cào xong.<br>• Viết script `merge_shards.py` gộp 5 thư mục `data/shards/<MSSV>/` thành bộ dữ liệu tổng. |
| **5. Trịnh Vỹ Triết** (`24120474`) | `profiler.py`<br>`main.py` | `05_performance_benchmark.ipynb` | `data/shards/24120474/` | • Xây dựng CLI (`main.py`) nhận 4 tham số `--start-month`, `--start-id`, `--end-month`, `--end-id`.<br>• Đo thời gian thực thi từng pha (`time.perf_counter`), Peak/Avg RAM (`psutil`, `/usr/bin/time -v`) và dung lượng ổ cứng (`du`) trên Google Colab CPU-only. |

## 4. Đặc tả Chi tiết Công việc & Kỹ thuật cho Từng Thành viên

### 4.1. Nguyễn Quốc Đạt (`24120282` — Trưởng nhóm): Entry Discovery & Quản lý Dải ID

* **Nhánh làm việc:** `feat/metadata-discovery`
* **Khoảng ID cá nhân cần cào:** `start_month = 2024-12`, `start_id = 18848`, `end_month = 2025-01`, `end_id = 2641` (`2412.18848` → hết tháng `12/2024` và `2501.00001` → `2501.02641`).
* **Các kỹ thuật cần hiện thực trong `src/crawler/id_range.py` và `src/crawler/discovery.py`:**
  1. **Chuẩn hóa chuỗi tháng (`normalize_yymm`):** Chuyển định dạng `"2024-12"` trên Sheet đăng ký thành `"2412"` (lấy 2 chữ số cuối của năm ghép với 2 chữ số tháng).
  2. **Xử lý dải ID vắt qua 2 tháng (`iter_assigned_ids`):**
     * Với các thành viên cùng tháng (`24120237`, `24120438`, `24120474`): vòng lặp chạy thẳng từ `start_id` đến `end_id`.
     * Với các thành viên khác tháng (`24120282` từ `2024-12` sang `2025-01`, và `24120470` từ `2024-06` sang `2024-07`): cài đặt hàm `find_last_id_of_month(yymm, low_id)` dùng **Tìm kiếm nhị phân (Binary Search)** trong khoảng `[low_id, 30000]` bằng truy vấn kiểm tra tồn tại trên arXiv API để tìm đúng mã bài báo cuối cùng của tháng đầu, sau đó mới sinh tiếp từ `00001` đến `end_id` của tháng kế tiếp.
  3. **Gộp lô truy vấn (`Batch Querying`):** Gom mỗi lần 50–100 ID vào tham số `id_list` của arXiv API (`http://export.arxiv.org/api/query?id_list=...&max_results=100`), nghỉ `3.0 giây` giữa các request để không vi phạm rate limit.
  4. **Thu thập đầy đủ các phiên bản (`versions`):** Trích xuất lịch sử mọi phiên bản `v1`, `v2`,... kèm thời điểm tạo (`created`) từ metadata trả về hoặc đối chiếu [arXiv OAI-PMH](https://www.google.com/search?q=https%3A%2F%2Fexport.arxiv.org%2Foai2).

### 4.2. Nguyễn Đình Tuấn (`24120237`): Full-Text Source Downloader & Image Cleaner

* **Nhánh làm việc:** `feat/source-downloader`
* **Khoảng ID cá nhân cần cào:** `start_month = 2025-02`, `start_id = 3235`, `end_month = 2025-02`, `end_id = 8234` (`2502.03235` → `2502.08234`).
* **Các kỹ thuật cần hiện thực trong `src/crawler/source_downloader.py`:**
  1. **Streaming Download có kiểm soát tốc độ:** Dùng `requests.Session` với `stream=True` tải từng chunk `64 KB` từ `https://export.arxiv.org/e-print/{arxiv_id}` lưu vào `data/raw/sources/{arxiv_id}.tar.gz`, nghỉ tối thiểu `3.0 giây` giữa 2 request.
  2. **Phân loại và giải nén an toàn:** Kiểm tra byte đầu của file tải về (hoặc `tarfile.is_tarfile`) để phân biệt gói `.tar.gz` nhiều file, file `.gz` chứa 1 file `.tex` đơn lẻ, hay bài báo chỉ nộp `.pdf` (không có LaTeX source). Giải nén vào `data/raw/unzipped/{arxiv_id}/`.
  3. **Đo dung lượng và xóa tệp hình ảnh:**
     * Viết hàm `get_dir_size_bytes(path)` đo tổng dung lượng thư mục giải nén trước khi dọn (`size_before_bytes`).
     * Viết hàm `prune_images_and_binaries(path)` xóa các file ảnh/đồ họa nặng (`.png`, `.jpg`, `.jpeg`, `.pdf`, `.eps`, `.ps`, `.svg`, `.bmp`, `.tif`, `.gif`), chỉ giữ lại các file mã nguồn văn bản (`.tex`, `.bib`, `.bbl`, `.sty`, `.cls`, `.bst`, `.txt`).
     * Đo lại `size_after_bytes` và xóa gói nén `.tar.gz` tạm để tránh đầy ổ cứng Google Colab.

### 4.3. Trần Nguyên Tân (`24120438`): Reference Scraper (Semantic Scholar API)

* **Nhánh làm việc:** `feat/reference-extraction`
* **Khoảng ID cá nhân cần cào:** `start_month = 2024-07`, `start_id = 12839`, `end_month = 2024-07`, `end_id = 17838` (`2407.12839` → `2407.17838`).
* **Các kỹ thuật cần hiện thực trong `src/crawler/reference_scraper.py`:**
  1. **Truy vấn Semantic Scholar Graph API:** Hỗ trợ gọi endpoint đơn `GET https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}?fields=references.externalIds,references.title,references.authors,references.year,references.venue` hoặc endpoint theo lô `POST /graph/v1/paper/batch`.
  2. **Xử lý Rate Limit & Retry:** Giới hạn tốc độ gọi dưới 100 requests / 5 phút (~1 request / 3.1 giây); khi gặp HTTP `429` hoặc `503`, áp dụng thuật toán chờ tăng dần (Exponential Backoff) trước khi gọi lại.
  3. **Chuẩn hóa danh sách trích dẫn & Fallback `.bib`:** Trích xuất `arxiv_id` từ `externalIds.ArXiv` và `doi` từ `externalIds.DOI`. Nếu API trả về `404`, quét dự phòng tệp `.bib`/`.bbl` trong thư mục đã giải nén để lấy chuỗi trích dẫn thô (`raw_citation`).

### 4.4. Dương Phan Minh Trí (`24120470`): Storage Schema, Mock Data & Shard Merger

* **Nhánh làm việc:** `feat/data-storage`
* **Khoảng ID cá nhân cần cào:** `start_month = 2024-06`, `start_id = 17938`, `end_month = 2024-07`, `end_id = 2838` (`2406.17938` → hết tháng `06/2024` và `2407.00001` → `2407.02838`).
* **Các kỹ thuật cần hiện thực trong `src/crawler/storage.py`, `generate_mock_data.py` và `merge_shards.py`:**
  1. **Định nghĩa Schema PyArrow:** Thiết lập schema chuẩn cho `publications.parquet` (14 cột) và `references.parquet` (10 cột) theo đúng yêu cầu tại [Project Milestone 1 — Data Crawling](https://www.google.com/search?q=https%3A%2F%2Fhcmus-cs-ta.github.io%2Flab-book%2Fintro-ds%2Fstatement%2Fcrawling%2F), xử lý giá trị rỗng (`None`) và ghi nén `snappy`.
  2. **Sinh dữ liệu giả lập (`generate_mock_data.py`):** Tạo dữ liệu mẫu nhỏ cho 5 thư mục `data/shards/<MSSV>/` để các thành viên kiểm thử code vẽ biểu đồ trong Jupyter Book ngay khi chưa cào xong.
  3. **Gộp phân vùng (`merge_shards.py`):** Đọc toàn bộ tệp Parquet và `stats.json` từ 5 thư mục `data/shards/24120282/` .. `24120474/`, khử trùng lặp theo `id`, sắp xếp tăng dần và xuất ra `data/processed/publications.parquet`, `data/processed/references.parquet` cùng `data/processed/overall_stats.json`.

### 4.5. Trịnh Vỹ Triết (`24120474`): CLI Runner & Hardware Performance Profiler

* **Nhánh làm việc:** `feat/cli-and-profiling`
* **Khoảng ID cá nhân cần cào:** `start_month = 2024-06`, `start_id = 12938`, `end_month = 2024-06`, `end_id = 17937` (`2406.12938` → `2406.17937`).
* **Các kỹ thuật cần hiện thực trong `src/crawler/profiler.py` và `src/crawler/main.py`:**
  1. **Giám sát bộ nhớ & thời gian (`profiler.py`):** Sử dụng `psutil.Process().memory_info().rss` trên luồng nền để ghi nhận **Peak RAM (MB)** và **Average RAM (MB)**; dùng `time.perf_counter()` đo thời gian thực thi của từng bước (Discovery, Download & Clean, Reference Scrape) và dùng `du` / `os.scandir` đo dung lượng ổ cứng.
  2. **Giao diện dòng lệnh (`main.py`):** Dùng `argparse` nhận các tham số `--member-id`, `--start-month`, `--start-id`, `--end-month`, `--end-id`, `--output-dir`, `--batch-size`, `--rate-limit-sec`, `--resume` và điều phối tuần tự qua các module của nhóm.

## 5. Khung Sườn Giao Diện Hàm Chung (Interface Skeleton)

Các tệp trong `src/crawler/` tuân thủ chữ ký hàm (function signatures) dưới đây để 5 thành viên ghép code không bị lệch tham số:

```python
# src/crawler/id_range.py (Phụ trách: Nguyễn Quốc Đạt - 24120282)
from typing import Iterator

def normalize_yymm(month_str: str) -> str:
    """Chuyển '2024-12' hoặc '2412' về định dạng chuẩn 4 ký tự '2412'."""
    raise NotImplementedError("TODO: Hiện thực chuẩn hóa chuỗi tháng")

def iter_assigned_arxiv_ids(
    start_month: str,
    start_id: int,
    end_month: str,
    end_id: int,
) -> Iterator[str]:
    """Sinh tuần tự mã arXiv ID trong khoảng (start_month, start_id) -> (end_month, end_id)."""
    raise NotImplementedError("TODO: Hiện thực bộ sinh ID cùng tháng và khác tháng")
```

```python
# src/crawler/discovery.py (Phụ trách: Nguyễn Quốc Đạt - 24120282)
def discover_Metadata_batch(arxiv_ids: list[str], rate_limit_sec: float = 3.0) -> list[dict]:
    """Truy vấn metadata và danh sách versions của một lô arXiv ID."""
    raise NotImplementedError("TODO: Hiện thực truy vấn arXiv API / OAI-PMH")
```

```python
# src/crawler/source_downloader.py (Phụ trách: Nguyễn Đình Tuấn - 24120237)
def download_and_clean_source(arxiv_id: str, raw_dir: str, remove_archive: bool = True) -> dict:
    """
    Tải nguồn LaTeX, giải nén, xóa tệp ảnh và trả về dict:
    {'arxiv_id': str, 'status': str, 'size_before_bytes': int, 'size_after_bytes': int, 'elapsed_sec': float}
    """
    raise NotImplementedError("TODO: Hiện thực tải source, giải nén và lọc xóa ảnh")
```

```python
# src/crawler/reference_scraper.py (Phụ trách: Trần Nguyên Tân - 24120438)
def scrape_references_for_paper(arxiv_id: str, unzipped_dir: str | None = None) -> list[dict]:
    """Lấy danh sách trích dẫn từ Semantic Scholar API (kèm fallback đọc .bib/.bbl)."""
    raise NotImplementedError("TODO: Hiện thực cào trích dẫn Semantic Scholar")
```

```python
# src/crawler/storage.py (Phụ trách: Dương Phan Minh Trí - 24120470)
def save_publications_parquet(records: list[dict], output_path: str) -> None:
    """Kiểm tra schema và ghi danh sách bài báo ra tệp publications.parquet."""
    raise NotImplementedError("TODO: Hiện thực lưu bảng publications.parquet")

def save_references_parquet(records: list[dict], output_path: str) -> None:
    """Kiểm tra schema và ghi danh sách trích dẫn ra tệp references.parquet."""
    raise NotImplementedError("TODO: Hiện thực lưu bảng references.parquet")
```

```python
# src/crawler/profiler.py (Phụ trách: Trịnh Vỹ Triết - 24120474)
class ResourceProfiler:
    """Đo lường thời gian chạy, Peak/Avg RAM (psutil) và dung lượng ổ cứng."""
    def start(self) -> None:
        raise NotImplementedError("TODO: Bắt đầu lấy mẫu bộ nhớ và thời gian")

    def stop_and_export(self, output_json_path: str) -> dict:
        raise NotImplementedError("TODO: Dừng đo và xuất tệp stats.json")
```

## 6. Cấu trúc Thư mục Repository `arxiv-harvester`

```text
arxiv-harvester/
├── .github/
│   └── workflows/
│       └── ci.yml
├── data/
│   ├── raw/
│   │   ├── sources/                      # Chứa tệp nén (.tar.gz) tải về
│   │   └── unzipped/                     # Chứa thư mục LaTeX đã giải nén & xóa ảnh
│   ├── shards/                           # Kết quả cào độc lập của 5 thành viên
│   │   ├── 24120282/                     # Nguyễn Quốc Đạt (2024-12, 18848 -> 2025-01, 2641)
│   │   ├── 24120237/                     # Nguyễn Đình Tuấn (2025-02, 3235 -> 2025-02, 8234)
│   │   ├── 24120438/                     # Trần Nguyên Tân (2024-07, 12839 -> 2024-07, 17838)
│   │   ├── 24120470/                     # Dương Phan Minh Trí (2024-06, 17938 -> 2024-07, 2838)
│   │   └── 24120474/                     # Trịnh Vỹ Triết (2024-06, 12938 -> 2024-06, 17937)
│   └── processed/                        # Dữ liệu tổng hợp cuối cùng (publications.parquet, references.parquet)
├── docs/                                 # Các chương báo cáo Jupyter Book (.ipynb)
├── src/
│   └── crawler/
│       ├── __init__.py
│       ├── id_range.py                   # [24120282 - Nguyễn Quốc Đạt]
│       ├── discovery.py                  # [24120282 - Nguyễn Quốc Đạt]
│       ├── source_downloader.py          # [24120237 - Nguyễn Đình Tuấn]
│       ├── reference_scraper.py          # [24120438 - Trần Nguyên Tân]
│       ├── storage.py                    # [24120470 - Dương Phan Minh Trí]
│       ├── generate_mock_data.py         # [24120470 - Dương Phan Minh Trí]
│       ├── merge_shards.py               # [24120470 - Dương Phan Minh Trí]
│       ├── profiler.py                   # [24120474 - Trịnh Vỹ Triết]
│       └── main.py                       # [24120474 - Trịnh Vỹ Triết]
├── tasks/                                # Chứa file đặc tả nhiệm vụ riêng trên từng nhánh thành viên
├── .gitignore
├── LICENSE
├── README.md
└── pyproject.toml
```

## 7. Hướng dẫn Cài đặt & Câu lệnh Chạy cho Từng Thành viên

### 7.1. Thiết lập môi trường

```bash
git clone https://github.com/<username>/arxiv-harvester.git
cd arxiv-harvester
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 7.2. Lệnh chạy theo khoảng ID riêng của 5 thành viên

```bash
# 1. Nguyễn Quốc Đạt (24120282): 2024-12 (18848) -> 2025-01 (2641)
python -m src.crawler.main --member-id 24120282 --start-month 2024-12 --start-id 18848 --end-month 2025-01 --end-id 2641 --output-dir data/shards/24120282

# 2. Nguyễn Đình Tuấn (24120237): 2025-02 (3235) -> 2025-02 (8234)
python -m src.crawler.main --member-id 24120237 --start-month 2025-02 --start-id 3235 --end-month 2025-02 --end-id 8234 --output-dir data/shards/24120237

# 3. Trần Nguyên Tân (24120438): 2024-07 (12839) -> 2024-07 (17838)
python -m src.crawler.main --member-id 24120438 --start-month 2024-07 --start-id 12839 --end-month 2024-07 --end-id 17838 --output-dir data/shards/24120438

# 4. Dương Phan Minh Trí (24120470): 2024-06 (17938) -> 2024-07 (2838)
python -m src.crawler.main --member-id 24120470 --start-month 2024-06 --start-id 17938 --end-month 2024-07 --end-id 2838 --output-dir data/shards/24120470

# 5. Trịnh Vỹ Triết (24120474): 2024-06 (12938) -> 2024-06 (17937)
python -m src.crawler.main --member-id 24120474 --start-month 2024-06 --start-id 12938 --end-month 2024-06 --end-id 17937 --output-dir data/shards/24120474
```

### 7.3. Hợp nhất dữ liệu từ 5 thành viên

```bash
python -m src.crawler.merge_shards --shards-dir data/shards --output-dir data/processed
```
