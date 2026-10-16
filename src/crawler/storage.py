"""Schema và ghi Parquet. Phụ trách: Dương Phan Minh Trí (24120470)."""


def save_publications_parquet(records: list[dict], output_path: str) -> None:
    """Kiểm tra schema rồi ghi bảng publications nén snappy."""
    # TODO: Chốt PUBLICATIONS_SCHEMA từ đặc tả chính thức; giữ đúng list/struct/timestamp.
    # TODO: Chuẩn hóa null, kiểm tra kiểu dữ liệu và ghi tệp an toàn.
    raise NotImplementedError("TODO: Dương Phan Minh Trí (24120470) lưu publications")


def save_references_parquet(records: list[dict], output_path: str) -> None:
    """Kiểm tra schema rồi ghi bảng references nén snappy."""
    # TODO: Chốt REFERENCES_SCHEMA và khóa bản ghi với nhóm, giữ các giá trị null hợp lệ.
    # TODO: Kiểm tra kiểu dữ liệu và ghi tệp an toàn, kể cả danh sách rỗng.
    raise NotImplementedError("TODO: Dương Phan Minh Trí (24120470) lưu references")
