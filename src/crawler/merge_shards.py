"""Khung gộp phân vùng. Phụ trách: Dương Phan Minh Trí (24120470)."""


def merge_all_shards(shards_dir: str, output_dir: str) -> None:
    """Gộp Parquet và thống kê của năm thành viên thành dữ liệu chung."""
    # TODO: Đọc từng shard, kiểm tra schema và tách dữ liệu mẫu khỏi dữ liệu thật.
    # TODO: Khử trùng publications theo id; chốt khóa references để không mất cạnh trích dẫn.
    # TODO: Ghi publications.parquet, references.parquet và overall_stats.json.
    raise NotImplementedError("TODO: Dương Phan Minh Trí (24120470) gộp phân vùng")


def main() -> None:
    """Nhận --shards-dir và --output-dir rồi gọi merge_all_shards."""
    # TODO: Khai báo argparse, kiểm tra hai thư mục và gọi hàm gộp.
    raise NotImplementedError("TODO: Dương Phan Minh Trí (24120470) viết CLI gộp dữ liệu")


if __name__ == "__main__":
    main()
