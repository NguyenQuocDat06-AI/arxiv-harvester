"""Khung CLI điều phối. Phụ trách: Trịnh Vỹ Triết (24120474)."""

import argparse


def parse_args() -> argparse.Namespace:
    """Nhận MSSV, bốn mốc ID, thư mục đầu ra và các tùy chọn chạy."""
    # TODO: Khai báo --member-id, --start-month, --start-id (int), --end-month,
    # TODO: --end-id (int), --output-dir; kiểm tra đủ tham số và khoảng hợp lệ.
    # TODO: Thêm --batch-size, --rate-limit-sec và --resume với giá trị mặc định rõ ràng.
    raise NotImplementedError("TODO: Trịnh Vỹ Triết (24120474) viết bộ nhận tham số CLI")


def main() -> None:
    """Điều phối các module và lưu kết quả vào phân vùng cá nhân."""
    # TODO: Gọi parse_args, bật profiler và sinh ID được giao.
    # TODO: Chạy discovery, tải/dọn nguồn, lấy references và lưu Parquet theo lô.
    # TODO: Lưu checkpoint cho --resume; xuất stats.json kể cả khi một bước lỗi.
    raise NotImplementedError("TODO: Trịnh Vỹ Triết (24120474) kết nối pipeline")


if __name__ == "__main__":
    main()
