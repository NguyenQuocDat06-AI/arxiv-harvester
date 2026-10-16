"""Theo dõi tài nguyên. Phụ trách: Trịnh Vỹ Triết (24120474)."""


class ResourceProfiler:
    """Theo dõi thời gian, RAM và dung lượng đĩa trong lúc chạy pipeline."""

    def start(self) -> None:
        """Bắt đầu bấm giờ và lấy mẫu bộ nhớ."""
        # TODO: Khởi tạo thời gian và luồng lấy mẫu RSS bằng psutil.
        raise NotImplementedError("TODO: Trịnh Vỹ Triết (24120474) bắt đầu đo tài nguyên")

    def stop_and_export(self, output_json_path: str) -> dict:
        """Dừng đo, xuất stats.json và trả lại các số đo cùng đơn vị."""
        # TODO: Dừng luồng; tính runtime, peak/average RAM và dung lượng trước/sau dọn.
        # TODO: Ghi thống kê từng pha, môi trường CPU-only và kết quả xử lý.
        raise NotImplementedError("TODO: Trịnh Vỹ Triết (24120474) xuất thống kê tài nguyên")
