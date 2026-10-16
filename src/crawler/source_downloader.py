"""Tải và dọn mã nguồn. Phụ trách: Nguyễn Đình Tuấn (24120237)."""


def get_dir_size_bytes(path: str) -> int:
    """Đo dung lượng tệp trong thư mục bằng byte."""
    # TODO: Cộng kích thước tệp thường, xử lý lỗi đọc và không theo liên kết ra ngoài.
    raise NotImplementedError("TODO: Nguyễn Đình Tuấn (24120237) đo dung lượng")


def prune_images_and_binaries(path: str) -> None:
    """Dọn ảnh và tệp nhị phân trong thư mục nguồn đã giải nén."""
    # TODO: Chốt danh sách giữ lại .tex/.bib/.bbl/.sty/.cls/.bst/.txt với nhóm.
    # TODO: Chỉ xóa trong thư mục đã kiểm tra; ghi nhận tệp bị loại bỏ.
    raise NotImplementedError("TODO: Nguyễn Đình Tuấn (24120237) dọn ảnh")


def download_and_clean_source(
    arxiv_id: str,
    sources_dir: str,
    unzipped_dir: str,
    rate_limit_sec: float = 3.0,
    remove_archive: bool = True,
) -> dict:
    """Trả trạng thái tải, size_before_bytes, size_after_bytes và elapsed_sec."""
    # TODO: Tải e-print theo luồng 64 KB, có timeout, retry và giới hạn tốc độ.
    # TODO: Phân biệt tar.gz/gz/PDF; chặn đường dẫn thoát thư mục và liên kết nguy hiểm.
    # TODO: Đo trước/sau dọn ảnh; xóa gói tạm theo remove_archive, ghi nhận lỗi/PDF-only.
    raise NotImplementedError("TODO: Nguyễn Đình Tuấn (24120237) tải và dọn nguồn")
