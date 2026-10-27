import re
from typing import Iterator
from src.crawler.discovery import discover_metadata_batch
from src.crawler.exceptions import arXivConnectionError

MAX_ARXIV_SEQ = 99999
_LAST_ID_CACHE: dict[str, int] = {}

def normalize_yymm(month_str: str) -> str:
    """Normalize YYYY-MM or YYMM to YYMM format."""
    if not isinstance(month_str, str):
        raise TypeError("Month must be string")
    cleaned = month_str.strip()

    # YYYY-MM
    match_long = re.match(r"^\d{2}(\d{2})-(0[1-9]|1[0-2])$", cleaned)
    if match_long:
        return match_long.group(1) + match_long.group(2)
    # YYMM
    match_short = re.match(r"^(\d{2})(0[1-9]|1[0-2])$", cleaned)
    if match_short:
        return cleaned

    raise ValueError(f"Invalid month format: {month_str}")


def _get_month_sequence(start_month: str, end_month: str) -> list[str]:
    """Generate sequential YYMM list between start_month and end_month."""
    s_norm = normalize_yymm(start_month)
    e_norm = normalize_yymm(end_month)

    s_yr, s_mo = int(s_norm[:2]), int(s_norm[2:])
    e_yr, e_mo = int(e_norm[:2]), int(e_norm[2:])

    if (s_yr, s_mo) > (e_yr, e_mo):
        raise ValueError(
            f"Start month ({start_month}) must be earlier than or equal to end month ({end_month})"
        )

    months: list[str] = []
    cur_yr, cur_mo = s_yr, s_mo
    while (cur_yr, cur_mo) <= (e_yr, e_mo):
        months.append(f"{cur_yr:02d}{cur_mo:02d}")
        cur_mo += 1
        if cur_mo > 12:
            cur_mo = 1
            cur_yr += 1
    return months


def find_last_id_of_month(
    yymm: str,
    start_seq: int = 1,
    rate_limit_sec: float = 3.0,
    use_cache: bool = True,
) -> int:
    """Find last arxiv ID of month using binary search with error classification."""
    norm_yymm = normalize_yymm(yymm)
    if use_cache and norm_yymm in _LAST_ID_CACHE:
        return _LAST_ID_CACHE[norm_yymm]

    if start_seq < 1 or start_seq > MAX_ARXIV_SEQ:
        raise ValueError(f"start_seq should be between 1 and {MAX_ARXIV_SEQ}, got {start_seq}")

    # 1. Verify that start_seq exists on arXiv
    start_id = f"{norm_yymm}.{start_seq:05d}"
    res_start = discover_metadata_batch([start_id], rate_limit_sec=rate_limit_sec)
    if start_id not in res_start.records_by_id:
        if start_id in res_start.missing_confirmed:
            raise ValueError(f"ID {start_id} does not exist on arXiv.")
        raise arXivConnectionError(
            f"Failed to verify {start_id} on arXiv due to network/API error.",
            failed_ids=[start_id],
        )

    last_found = start_seq
    low = start_seq
    high = min(max(30000, start_seq + 5000), MAX_ARXIV_SEQ)

    # 2. Expand upper bound if necessary without exceeding MAX_ARXIV_SEQ
    while high <= MAX_ARXIV_SEQ:
        probe_id = f"{norm_yymm}.{high:05d}"
        res = discover_metadata_batch([probe_id], rate_limit_sec=rate_limit_sec)
        if probe_id in res.records_by_id:
            last_found = high
            low = high
            if high == MAX_ARXIV_SEQ:
                break
            high = min(high + 5000, MAX_ARXIV_SEQ)
        elif probe_id in res.missing_confirmed:
            break
        else:
            raise arXivConnectionError(
                f"Error checking upper bound {probe_id}: network/API error",
                failed_ids=[probe_id],
            )

    # 3. Binary search safely within [low, high]
    while low <= high:
        mid = (low + high) // 2
        arxiv_id = f"{norm_yymm}.{mid:05d}"
        res = discover_metadata_batch([arxiv_id], rate_limit_sec=rate_limit_sec)

        if arxiv_id in res.records_by_id:
            last_found = mid
            low = mid + 1
        elif arxiv_id in res.missing_confirmed:
            high = mid - 1
        else:
            # Stop safely if encountering network error to avoid narrowing the bound wrongly
            raise arXivConnectionError(
                f"Transient error probing {arxiv_id}, halting binary search safely.",
                failed_ids=[arxiv_id],
            )

    if use_cache:
        _LAST_ID_CACHE[norm_yymm] = last_found

    return last_found


def iter_assigned_arxiv_ids(
    start_month: str,
    start_id: int,
    end_month: str,
    end_id: int,
    rate_limit_sec: float = 3.0,
) -> Iterator[str]:
    """Generate sequential arXiv IDs for any given month range and sequence boundaries."""
    if start_id < 1 or start_id > MAX_ARXIV_SEQ:
        raise ValueError(f"Start ID must be between 1 and {MAX_ARXIV_SEQ}, got {start_id}")
    if end_id < 1 or end_id > MAX_ARXIV_SEQ:
        raise ValueError(f"End ID must be between 1 and {MAX_ARXIV_SEQ}, got {end_id}")

    months = _get_month_sequence(start_month, end_month)

    # Case 1: Range stays within a single month
    if len(months) == 1:
        single_month = months[0]
        if start_id > end_id:
            raise ValueError(
                f"Start ID ({start_id}) must be <= End ID ({end_id}) for the same month ({single_month})"
            )
        for seq in range(start_id, end_id + 1):
            yield f"{single_month}.{seq:05d}"
        return

    # Case 2: Range spans two or more months
    for idx, month in enumerate(months):
        if idx == 0:
            # First month: from start_id to the last paper of this month
            last_seq = find_last_id_of_month(month, start_seq=start_id, rate_limit_sec=rate_limit_sec)
            for seq in range(start_id, last_seq + 1):
                yield f"{month}.{seq:05d}"
        elif idx == len(months) - 1:
            # Last month: from 00001 to end_id
            for seq in range(1, end_id + 1):
                yield f"{month}.{seq:05d}"
        else:
            # Intermediate months (if range spans 3+ months): all papers in that month
            last_seq = find_last_id_of_month(month, start_seq=1, rate_limit_sec=rate_limit_sec)
            for seq in range(1, last_seq + 1):
                yield f"{month}.{seq:05d}"


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

    print("\n=== 2. Test month sequence across multiple months ===")
    seq_months = _get_month_sequence("2024-11", "2025-02")
    assert seq_months == ["2411", "2412", "2501", "2502"]
    print(f"  [OK] Sequence 4 months: {seq_months}")

    print("\n=== 3. Test iter_assigned_arxiv_ids (Same month - No network call) ===")
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

    print("\n=== 4. Test find_last_id_of_month (Personal Range: 2412) ===")
    print("  [*] Finding last ID of 2412 via Binary Search...")
    last_id_2412 = find_last_id_of_month("2412", start_seq=18848)
    print(f"  [+] Result last ID 12/2024: 2412.{last_id_2412:05d}")

    total_papers = (last_id_2412 - 18848 + 1) + 2641
    print(f"  [+] Total papers in personal range (18848 -> {last_id_2412} and 1 -> 2641): {total_papers} papers")
    assert total_papers == 5000, f"Expected 5000 papers, got {total_papers}"
    print("  [OK] 5000 papers assigned range fully verified.")
