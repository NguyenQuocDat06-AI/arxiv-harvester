"""Thu thập trích dẫn. Phụ trách: Trần Nguyên Tân (24120438)."""


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
