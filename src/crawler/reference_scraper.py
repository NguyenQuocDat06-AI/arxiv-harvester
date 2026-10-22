"""Thu thập trích dẫn. Phụ trách: Trần Nguyên Tân (24120438)."""

# Danh sách khóa của MỘT bản ghi trích dẫn mà hàm trả về: mỗi bản ghi có đúng các khóa này, không thừa không thiếu.
# Đây là "nguồn sự thật duy nhất" cho tên khóa: code tạo bản ghi, test và storage.py đều đọc từ đây.
# - 6 khóa đầu là cột bảng `references` theo đề M1, giữ đúng thứ tự:
#   https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/
# - 5 khóa sau là khóa nội bộ do Tân đề xuất, CHỜ Trí (storage.py) xác nhận.
# - Thiếu dữ liệu thì để None, riêng ref_authors để [] (danh sách rỗng); không bịa giá trị.
# Dùng tuple (không sửa được lúc chạy) để không đoạn code nào lỡ tay thêm/bớt khóa.
REFERENCE_KEYS: tuple[str, ...] = (
    # --- 6 cột của đề ---
    "arxiv_id",  # bài ĐANG trích dẫn (bài trong khoảng ID được giao), không có đuôi phiên bản
    "ref_arxiv_id",  # bài ĐƯỢC trích, lấy từ externalIds.ArXiv; None nếu tài liệu không có trên arXiv
    "ref_title",
    "ref_authors",  # list[str] tên tác giả, giữ thứ tự
    "ref_submission_date",  # lấy từ publicationDate của S2 ("YYYY-MM-DD"); không tự dựng từ năm
    "ref_s2_id",  # paperId của Semantic Scholar; thường None với mục S2 chưa nhận diện được
    # --- 5 khóa nội bộ (đề xuất) ---
    "ref_doi",  # DOI đã bỏ tiền tố "https://doi.org/" hoặc "doi:"
    "ref_year",  # int
    "ref_venue",  # chuỗi rỗng từ S2 coi là thiếu, đổi thành None
    "raw_citation",  # chuỗi gốc trong .bib/.bbl (nhánh dự phòng); None với bản ghi từ API
    "source",  # chỉ nhận "semantic_scholar" hoặc "bib_fallback"
)


def scrape_references_for_paper(
    arxiv_id: str,
    unzipped_paper_dir: str | None = None,
    rate_limit_sec: float = 3.1,
) -> list[dict]:
    """Lấy references qua Semantic Scholar, dự phòng bằng .bib/.bbl."""
    # TODO: Lấy references.externalIds/title/authors/year/venue và xử lý phân trang.
    # TODO: Kiểm soát tốc độ, Retry-After và backoff có giới hạn cho 429/503.
    # TODO: Đọc .bib/.bbl khi API trả 404; chuẩn hóa ID, DOI và raw_citation.
    raise NotImplementedError("TODO: Trần Nguyên Tân (24120438) thu thập trích dẫn")
