"""Sinh dải ID được giao. Phụ trách: Nguyễn Quốc Đạt (24120282)."""

from typing import Iterator


def normalize_yymm(month_str: str) -> str:
    """Đưa tháng dạng YYYY-MM hoặc YYMM về YYMM."""
    # TODO: Kiểm tra định dạng và giá trị tháng trước khi chuẩn hóa.
    raise NotImplementedError("TODO: Nguyễn Quốc Đạt (24120282) chuẩn hóa tháng")


def find_last_id_of_month(yymm: str, start_seq: int = 1) -> int:
    """Tìm số thứ tự cuối tháng khi khoảng ID vắt qua hai tháng."""
    # TODO: Kiểm tra ID tồn tại qua arXiv API, có giới hạn tốc độ và retry.
    # TODO: Tìm kiếm nhị phân từ start_seq đến cận trên đã kiểm chứng.
    raise NotImplementedError("TODO: Nguyễn Quốc Đạt (24120282) tìm ID cuối tháng")


def iter_assigned_arxiv_ids(
    start_month: str,
    start_id: int,
    end_month: str,
    end_id: int,
) -> Iterator[str]:
    """Sinh ID dạng YYMM.NNNNN, tính cả hai đầu khoảng được giao."""
    # TODO: Chuẩn hóa tháng và kiểm tra thứ tự các mốc đầu/cuối.
    # TODO: Sinh khoảng cùng tháng hoặc tìm ID cuối tháng trước khi nối tháng sau.
    raise NotImplementedError("TODO: Nguyễn Quốc Đạt (24120282) sinh dải ID")
