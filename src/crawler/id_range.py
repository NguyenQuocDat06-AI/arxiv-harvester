from typing import Iterator
import re
from src.crawler.discovery import discover_metadata_batch

def normalize_yymm(month_str: str) -> str:
    """Đưa tháng dạng YYYY-MM hoặc YYMM về YYMM."""
    if not isinstance(month_str, str):
        raise TypeError("Month must be string")
    cleaned = month_str.strip()

    # Regex YYYY-MM (kiểm tra năm 4 số và tháng 01-12)
    match_long = re.match(r"^\d{2}(\d{2})-(0[1-9]|1[0-2])$", cleaned)
    if match_long:
        return match_long.group(1) + match_long.group(2)

    # Regex YYMM (kiểm tra năm 2 số và tháng 01-12)
    match_short = re.match(r"^(\d{2})(0[1-9]|1[0-2])$", cleaned)
    if match_short:
        return cleaned

    raise ValueError(f"Invalid month format: {month_str}")


def find_last_id_of_month(yymm: str, start_seq: int = 1) -> int:
    """Find last arxiv ID of month use binary search."""
    low = start_seq
    high = 30000
    last_found = start_seq

    while bool(discover_metadata_batch([f"{yymm}.{high:05d}"], rate_limit_sec=3.0)):
        low = high
        high += 5000

    while low <= high:
        mid = (low + high) // 2
        arxiv_id = f"{yymm}.{mid:05d}"
        if bool(discover_metadata_batch([arxiv_id], rate_limit_sec=3.0)):
            last_found = mid
            low = mid + 1
        else:
            high = mid - 1

    return last_found


def iter_assigned_arxiv_ids(
    start_month: str,
    start_id: int,
    end_month: str,
    end_id: int,
) -> Iterator[str]:
    """Generate arxiv id range."""
    start_yymm = normalize_yymm(start_month)
    end_yymm = normalize_yymm(end_month)

    if start_id < 1 or end_id < 1:
        raise ValueError("Start ID and end ID must be greater than 0")

    if start_yymm == end_yymm:
        if start_id > end_id:
            raise ValueError(
                "Start ID must be less than or equal to end ID for the same month"
            )
        for seq in range(start_id, end_id + 1):
            yield f"{start_yymm}.{seq:05d}"
    else:
        last_id_month1 = find_last_id_of_month(start_yymm, start_id)
        for seq in range(start_id, last_id_month1 + 1):
            yield f"{start_yymm}.{seq:05d}"
        for seq in range(1, end_id + 1):
            yield f"{end_yymm}.{seq:05d}"


if __name__ == "__main__":
    print("=== 1. Test normalize_yymm ===")
    test_months = [
        ("2024-12", "2412"),
        ("2025-01", "2501"),
        ("2412", "2412"),
        ("2501", "2501"),
    ]
    for raw, expected in test_months:
        result = normalize_yymm(raw)
        assert result == expected, f"Failed: {raw} -> {result} != {expected}"
        print(f"  [OK] {raw} -> {result}")
    invalid_cases = ["2024/12", "2024-13", "2415", "2400", "abcd", 1234]
    for case in invalid_cases:
        try:
            normalize_yymm(case)
            print(f"  [FAIL] Should raise error for: {case}")
        except (ValueError, TypeError):
            print(f"  [OK] Caught expected error for: {case}")

    print("\n=== 2. Test iter_assigned_arxiv_ids (Same month - No request) ===")
    sample_same_month = list(iter_assigned_arxiv_ids("2024-12", 1, "2024-12", 5))
    print(f"  Generated IDs: {sample_same_month}")
    assert sample_same_month == [
        "2412.00001",
        "2412.00002",
        "2412.00003",
        "2412.00004",
        "2412.00005",
    ], "Mismatch in same month ID generation"
    print("  [OK] Same month generation passed")

    print("\n=== 3. Test find_last_id_of_month (Personal Range: 2412) ===")
    print("  [*] Finding last ID of 2412 via Binary Search (takes ~40s)...")
    last_id_2412 = find_last_id_of_month("2412", start_seq=18848)
    print(f"  [+] Result last ID 12/2024: 2412.{last_id_2412:05d}")

    total_papers = (last_id_2412 - 18848 + 1) + 2641
    print(f"  [+] Total papers in personal range (18848 -> {last_id_2412} and 1 -> 2641): {total_papers} papers")
