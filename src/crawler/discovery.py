"""Metadata và lịch sử phiên bản. Phụ trách: Nguyễn Quốc Đạt (24120282)."""


def discover_metadata_batch(
    arxiv_ids: list[str], rate_limit_sec: float = 3.0
) -> list[dict]:
    """Lấy metadata và đầy đủ versions cho một lô ID không kèm phiên bản."""
    # TODO: Gửi id_list theo lô 50-100 ID, xử lý lỗi và giới hạn tốc độ.
    # TODO: Đọc metadata, đối chiếu OAI-PMH để có đủ version và created.
    # TODO: Chuẩn hóa bản ghi theo schema dùng chung, ghi nhận ID không tìm thấy.
    raise NotImplementedError("TODO: Nguyễn Quốc Đạt (24120282) thu thập metadata")
