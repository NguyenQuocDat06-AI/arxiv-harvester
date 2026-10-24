"""Kiểm thử tầng lưu trữ Parquet và gộp dữ liệu.

Phụ trách: Dương Phan Minh Trí (24120470) — Nhánh feat/data-storage.
"""

import json
import os
from datetime import datetime, timezone
import pyarrow.parquet as pq
import pytest

from src.crawler.storage import (
    PUBLICATIONS_SCHEMA,
    REFERENCES_SCHEMA,
    COURSE_PAPERS_SCHEMA,
    COURSE_REFERENCES_SCHEMA,
    save_publications_parquet,
    save_references_parquet,
    export_to_course_spec,
    resolve_paper_source_status,
    normalize_publication_record,
    normalize_reference_record,
    _is_null,
    _to_non_negative_int,
    get_synthesized_v1_count,
    reset_synthesized_v1_count,
    get_dropped_ref_dates_count,
    reset_dropped_ref_dates_count,
)


# ---------------------------------------------------------------------------
# 1. Tests cho storage.py (Round-trip, Normalizer, on_invalid, export)
# ---------------------------------------------------------------------------

def test_publications_round_trip(tmp_path):
    """Kiểm thử Round-trip: ghi -> đọc bằng pq.read_table().to_pylist() -> ghi lại.
    Schema và giá trị phải bảo toàn chính xác.
    """
    file_path = str(tmp_path / "pubs.parquet")
    file_path_2 = str(tmp_path / "pubs_re.parquet")

    records = [
        {
            "id": "2406.17938v2",
            "title": "A Sample Paper Title",
            "abstract": "Sample abstract text.",
            "authors": ["Alice Nguyen", "Bob Tran"],
            "primary_category": "cs.AI",
            "categories": ["cs.AI", "cs.LG"],
            "published": "2024-06-15T10:00:00Z",
            "updated": "2024-06-20T12:00:00Z",
            "doi": "10.1234/sample.doi",
            "journal_ref": "Sample Journal 2024",
            "comments": "10 pages, 3 figures",
            "venue": "Sample Conference",
            "source_status": "success",
            "size_before_bytes": 10000,
            "size_after_bytes": 4000,
            "versions": [
                {
                    "version": "v1",
                    "created": "2024-06-15T10:00:00Z",
                    "size_before_bytes": 9000,
                    "size_after_bytes": 3500,
                    "source_status": "success",
                },
                {
                    "version": "v2",
                    "created": "2024-06-20T12:00:00Z",
                    "size_before_bytes": 10000,
                    "size_after_bytes": 4000,
                    "source_status": "success",
                },
            ],
        }
    ]

    # Ghi lần 1
    save_publications_parquet(records, file_path)
    table_1 = pq.read_table(file_path)
    assert table_1.schema == PUBLICATIONS_SCHEMA
    read_back_1 = table_1.to_pylist()

    # ID đã được cắt bỏ v2
    assert read_back_1[0]["id"] == "2406.17938"
    assert read_back_1[0]["title"] == "A Sample Paper Title"
    assert len(read_back_1[0]["versions"]) == 2
    assert isinstance(read_back_1[0]["versions"][0]["created"], datetime)

    # Ghi lần 2 từ dữ liệu đọc lại (round-trip)
    save_publications_parquet(read_back_1, file_path_2)
    table_2 = pq.read_table(file_path_2)
    assert table_2.schema == PUBLICATIONS_SCHEMA
    read_back_2 = table_2.to_pylist()

    assert read_back_1 == read_back_2


def test_references_round_trip(tmp_path):
    """Kiểm thử Round-trip cho bảng references."""
    file_path = str(tmp_path / "refs.parquet")
    file_path_2 = str(tmp_path / "refs_re.parquet")

    records = [
        {
            "arxiv_id": "2406.17938",
            "ref_arxiv_id": "2301.00001v1",
            "ref_title": "Cited Paper Title",
            "ref_authors": ["Charlie Le"],
            "ref_submission_date": "2023-01-10",
            "ref_s2_id": "s2_corpus_12345",
            "ref_doi": "https://doi.org/10.5678/cited.doi",
            "ref_year": 2023,
            "ref_venue": "ICLR",
            "raw_citation": "Raw bibtex citation string",
            "source": "semantic_scholar",
        }
    ]

    save_references_parquet(records, file_path)
    table_1 = pq.read_table(file_path)
    assert table_1.schema == REFERENCES_SCHEMA
    read_back_1 = table_1.to_pylist()

    assert read_back_1[0]["arxiv_id"] == "2406.17938"
    assert read_back_1[0]["ref_arxiv_id"] == "2301.00001"  # Bỏ suffix v1
    assert read_back_1[0]["ref_doi"] == "10.5678/cited.doi"  # Bỏ https://doi.org/

    save_references_parquet(read_back_1, file_path_2)
    table_2 = pq.read_table(file_path_2)
    assert table_2.schema == REFERENCES_SCHEMA
    assert table_1.to_pylist() == table_2.to_pylist()


def test_empty_tables_write_and_read(tmp_path):
    """Bảng rỗng [] vẫn phải ghi ra tệp Parquet với đúng schema chuẩn."""
    pub_path = str(tmp_path / "empty_pub.parquet")
    ref_path = str(tmp_path / "empty_ref.parquet")

    save_publications_parquet([], pub_path)
    save_references_parquet([], ref_path)

    pub_table = pq.read_table(pub_path)
    ref_table = pq.read_table(ref_path)

    assert pub_table.schema == PUBLICATIONS_SCHEMA
    assert ref_table.schema == REFERENCES_SCHEMA
    assert len(pub_table) == 0
    assert len(ref_table) == 0


def test_quarantine_rejected_records(tmp_path):
    """Bản ghi mất ID được cách ly ra _rejected_*.jsonl, các bản ghi tốt vẫn được ghi."""
    pub_path = str(tmp_path / "quarantine_pub.parquet")
    records = [
        {"id": "2406.00001", "title": "Good Paper"},
        {"id": None, "title": "Bad Paper without ID"},
        {"id": "   ", "title": "Bad Paper with empty ID"},
        {"id": "2406.00002", "title": "Another Good Paper"},
    ]

    save_publications_parquet(records, pub_path, on_invalid="quarantine")

    # Kiểm tra file Parquet chỉ chứa 2 bài tốt
    table = pq.read_table(pub_path)
    assert len(table) == 2
    assert [p["id"] for p in table.to_pylist()] == ["2406.00001", "2406.00002"]

    # Kiểm tra file _rejected_quarantine_pub.jsonl
    rej_path = str(tmp_path / "_rejected_quarantine_pub.jsonl")
    assert os.path.exists(rej_path)
    with open(rej_path, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2


def test_on_invalid_raise_mode(tmp_path):
    """Chế độ on_invalid='raise' ném ValueError khi có bản ghi hỏng."""
    records = [{"id": None, "title": "Broken"}]
    with pytest.raises(ValueError, match="mất hẳn id hoặc id rỗng"):
        save_publications_parquet(records, str(tmp_path / "dummy.parquet"), on_invalid="raise")


def test_negative_sizes_become_none(tmp_path):
    """Số âm ở size_before_bytes / size_after_bytes được chuyển thành None."""
    pub_path = str(tmp_path / "negative_size.parquet")
    records = [{
        "id": "2406.00001",
        "size_before_bytes": -100,
        "size_after_bytes": -50,
    }]
    save_publications_parquet(records, pub_path)
    table = pq.read_table(pub_path)
    rec = table.to_pylist()[0]
    assert rec["size_before_bytes"] is None
    assert rec["size_after_bytes"] is None


def test_paper_level_metrics_assigned_to_last_version(tmp_path):
    """Khi chỉ có metrics cấp bài, gán vào version cuối cùng vN, các version trước để None."""
    pub_path = str(tmp_path / "multi_ver.parquet")
    records = [{
        "id": "2406.00001",
        "size_before_bytes": 5000,
        "size_after_bytes": 2000,
        "source_status": "success",
        "versions": [
            {"version": "v1", "created": "2024-06-01T00:00:00Z"},
            {"version": "v2", "created": "2024-06-05T00:00:00Z"},
            {"version": "v3", "created": "2024-06-10T00:00:00Z"},
        ]
    }]
    save_publications_parquet(records, pub_path)
    table = pq.read_table(pub_path)
    versions = table.to_pylist()[0]["versions"]
    assert len(versions) == 3
    assert versions[0]["source_status"] is None
    assert versions[1]["source_status"] is None
    assert versions[2]["source_status"] == "success"
    assert versions[2]["size_before_bytes"] == 5000
    assert versions[2]["size_after_bytes"] == 2000


def test_resolve_paper_source_status():
    """Kiểm thử quy tắc phân giải source_status cấp bài."""
    assert resolve_paper_source_status(["success", "success"]) == "success"
    assert resolve_paper_source_status(["success", "error"]) == "partial_success"
    assert resolve_paper_source_status(["no_latex", "error"]) == "error"
    assert resolve_paper_source_status(["no_latex", "no_latex"]) == "no_latex"
    assert resolve_paper_source_status(["pdf_only", "pdf_only"]) == "pdf_only"


def test_export_to_course_spec(tmp_path):
    """Kiểm thử hàm xuất chuẩn đề môn học."""
    processed_dir = str(tmp_path / "processed")
    export_dir = str(tmp_path / "export")
    os.makedirs(processed_dir, exist_ok=True)

    pubs = [
        # Paper 1: 1 version -> revised_dates rỗng
        {
            "id": "2406.00001",
            "title": "Single Version Paper",
            "authors": ["Author One"],
            "published": "2024-06-01T00:00:00Z",
            "updated": "2024-06-05T00:00:00Z",
            "venue": "Journal A",
            "versions": [{"version": "v1", "created": "2024-06-01T00:00:00Z"}],
        },
        # Paper 2: 3 version (v2 và v3 trùng ngày created) -> khử trùng revised_dates
        {
            "id": "2406.00002",
            "title": "Multi Version Paper",
            "authors": ["Author Two"],
            "published": "2024-06-02T00:00:00Z",
            "updated": "2024-06-10T00:00:00Z",
            "venue": None,
            "versions": [
                {"version": "v1", "created": "2024-06-02T00:00:00Z"},
                {"version": "v2", "created": "2024-06-10T00:00:00Z"},
                {"version": "v3", "created": "2024-06-10T00:00:00Z"},
            ],
        },
    ]

    refs = [
        # Ref có arXiv ID -> giữ lại
        {"arxiv_id": "2406.00001", "ref_arxiv_id": "2301.00005", "ref_title": "Cited Arxiv"},
        # Ref không có arXiv ID -> bị lọc bỏ theo đề
        {"arxiv_id": "2406.00001", "ref_arxiv_id": None, "ref_title": "Cited Non-Arxiv"},
        # Ref trùng lặp cùng paper -> khử trùng
        {"arxiv_id": "2406.00001", "ref_arxiv_id": "2301.00005", "ref_title": "Cited Arxiv Dup"},
    ]

    save_publications_parquet(pubs, os.path.join(processed_dir, "publications.parquet"))
    save_references_parquet(refs, os.path.join(processed_dir, "references.parquet"))

    papers_out, refs_out = export_to_course_spec(processed_dir, export_dir)

    papers_table = pq.read_table(papers_out)
    refs_table = pq.read_table(refs_out)

    assert papers_table.schema == COURSE_PAPERS_SCHEMA
    assert refs_table.schema == COURSE_REFERENCES_SCHEMA

    papers_list = papers_table.to_pylist()
    assert len(papers_list) == 2
    assert papers_list[0]["arxiv_id"] == "2406.00001"
    assert papers_list[0]["revised_dates"] == []  # 1 version -> rỗng

    assert papers_list[1]["arxiv_id"] == "2406.00002"
    assert papers_list[1]["revised_dates"] == ["2024-06-10T00:00:00+00:00"]  # Đã khử trùng

    refs_list = refs_table.to_pylist()
    assert len(refs_list) == 1  # Đã lọc None và khử trùng
    assert refs_list[0]["arxiv_id"] == "2406.00001"
    assert refs_list[0]["ref_arxiv_id"] == "2301.00005"


# ---------------------------------------------------------------------------
# 2. Tests cho generate_mock_data.py
# ---------------------------------------------------------------------------

from src.crawler.generate_mock_data import generate_all_mock_data, MEMBERS_CONFIG


def test_generate_mock_data_all_shards(tmp_path):
    """Kiểm thử sinh mock data cho cả 5 thành viên."""
    shards_dir = str(tmp_path / "shards")
    generate_all_mock_data(shards_dir=shards_dir, force=False, seed=42)

    for cfg in MEMBERS_CONFIG:
        member_dir = os.path.join(shards_dir, cfg["member_id"])
        pub_file = os.path.join(member_dir, "publications.parquet")
        ref_file = os.path.join(member_dir, "references.parquet")
        stats_file = os.path.join(member_dir, "stats.json")

        assert os.path.exists(pub_file)
        assert os.path.exists(ref_file)
        assert os.path.exists(stats_file)

        # Kiểm tra Parquet schema
        pub_table = pq.read_table(pub_file)
        ref_table = pq.read_table(ref_file)
        assert pub_table.schema == PUBLICATIONS_SCHEMA
        assert ref_table.schema == REFERENCES_SCHEMA

        # Kiểm tra stats.json
        import json
        with open(stats_file, encoding="utf-8") as f:
            stats = json.load(f)
        assert stats["is_mock"] is True
        assert stats["member_id"] == cfg["member_id"]


def test_mock_data_guard_against_overwriting_real_data(tmp_path):
    """Không ghi đè lên thư mục đang có dữ liệu thật (không có is_mock=True) trừ khi dùng force."""
    shards_dir = str(tmp_path / "shards")
    member_dir = os.path.join(shards_dir, "24120470")
    os.makedirs(member_dir, exist_ok=True)

    # Giả lập file dữ liệu thật và stats.json của cào thật (is_mock: False)
    real_stats = {"member_id": "24120470", "is_mock": False}
    with open(os.path.join(member_dir, "stats.json"), "w", encoding="utf-8") as f:
        import json
        json.dump(real_stats, f)

    fake_file = os.path.join(member_dir, "real_checkpoint.tmp")
    with open(fake_file, "w") as f:
        f.write("real data")

    # Gọi sinh mock data không force -> phải bỏ qua
    generate_all_mock_data(shards_dir=shards_dir, force=False, seed=42)
    assert os.path.exists(fake_file)
    with open(os.path.join(member_dir, "stats.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert data["is_mock"] is False  # Vẫn là dữ liệu thật

    # Gọi có force -> ghi đè
    generate_all_mock_data(shards_dir=shards_dir, force=True, seed=42)
    with open(os.path.join(member_dir, "stats.json"), encoding="utf-8") as f:
        data_forced = json.load(f)
    assert data_forced["is_mock"] is True


# ---------------------------------------------------------------------------
# 3. Tests cho merge_shards.py
# ---------------------------------------------------------------------------

from src.crawler.merge_shards import merge_all_shards


def test_merge_shards_default_rejects_mock(tmp_path):
    """Mặc định allow_mock=False từ chối gộp khi phát hiện dữ liệu mock."""
    shards_dir = str(tmp_path / "shards")
    output_dir = str(tmp_path / "processed")
    generate_all_mock_data(shards_dir=shards_dir, force=True, seed=42)

    with pytest.raises(ValueError, match="Dữ liệu trong shards là dữ liệu MOCK"):
        merge_all_shards(shards_dir=shards_dir, output_dir=output_dir, allow_mock=False)


def test_merge_shards_with_allow_mock(tmp_path):
    """Bật allow_mock=True cho phép gộp mock data và tính toán đầy đủ các chỉ số."""
    shards_dir = str(tmp_path / "shards")
    output_dir = str(tmp_path / "processed")
    generate_all_mock_data(shards_dir=shards_dir, force=True, seed=42)

    stats = merge_all_shards(shards_dir=shards_dir, output_dir=output_dir, allow_mock=True)

    assert stats["is_mock"] is True
    assert stats["total_publications"] > 0
    assert stats["total_references"] > 0
    assert stats["resource_performance"]["total_compute_sec"] > 0
    assert stats["resource_performance"]["max_member_wall_sec"] > 0
    assert stats["resource_performance"]["peak_rss_mb"] > 0
    assert stats["resource_performance"]["weighted_avg_rss_mb"] > 0
    assert 0.0 <= stats["source_version_coverage_rate"] <= 1.0

    # Kiểm tra file sinh ra trong processed
    assert os.path.exists(os.path.join(output_dir, "publications.parquet"))
    assert os.path.exists(os.path.join(output_dir, "references.parquet"))
    assert os.path.exists(os.path.join(output_dir, "overall_stats.json"))


def test_merge_shards_rejects_mixed_mock_and_real(tmp_path):
    """Cấm tuyệt đối trộn lẫn shard mock và shard thật."""
    shards_dir = str(tmp_path / "shards")
    output_dir = str(tmp_path / "processed")
    generate_all_mock_data(shards_dir=shards_dir, force=True, seed=42)

    # Đổi 1 shard thành shard thật (is_mock: False)
    real_stats_path = os.path.join(shards_dir, "24120470", "stats.json")
    with open(real_stats_path, encoding="utf-8") as f:
        s = json.load(f)
    s["is_mock"] = False
    with open(real_stats_path, "w", encoding="utf-8") as f:
        json.dump(s, f)

    with pytest.raises(ValueError, match="CẢNH BÁO VI PHẠM: Tồn tại đồng thời cả shard Mock và shard Thật"):
        merge_all_shards(shards_dir=shards_dir, output_dir=output_dir, allow_mock=True)


def test_quarantine_datetime_serializable(tmp_path):
    """Bản ghi mất ID chứa datetime trong published và versions[].created vẫn serialize được qua jsonl (default=str)."""
    pub_path = str(tmp_path / "quarantine_dt.parquet")
    records = [
        {
            "id": None,  # Mất id -> bị cách ly
            "title": "Unsalvageable Paper",
            "published": datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
            "versions": [{"version": "v1", "created": datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)}],
        }
    ]
    save_publications_parquet(records, pub_path, on_invalid="quarantine")
    rej_path = str(tmp_path / "_rejected_quarantine_dt.jsonl")
    assert os.path.exists(rej_path)
    with open(rej_path, encoding="utf-8") as f:
        line = f.readline()
    assert "2024-06-01" in line
    assert "Unsalvageable Paper" in line


def test_check_id_coverage_split_month():
    """Kiểm thử _check_id_coverage cho dải vắt tháng (2406.17938 -> 2407.02838) với 1 ID bị thiếu ở mỗi tháng."""
    from src.crawler.merge_shards import _check_id_coverage

    assigned_range = {
        "start_month": "2024-06",
        "start_id": 17938,
        "end_month": "2024-07",
        "end_id": 2838,
    }
    # Giả lập tháng đầu (2406): dải ID tìm thấy từ 17938 đến 17942, cố tình khuyết 17940 (1 ID thiếu)
    month_1_ids = {f"2406.{seq:05d}" for seq in range(17938, 17943) if seq != 17940}
    # Giả lập tháng sau (2407): dải ID kỳ vọng từ 00001 đến 02838, cố tình khuyết 00005 (1 ID thiếu)
    month_2_ids = {f"2407.{seq:05d}" for seq in range(1, 2839) if seq != 5}
    found_ids = month_1_ids | month_2_ids

    res = _check_id_coverage(assigned_range, found_ids)
    assert res["has_assigned_range"] is True
    assert res["tail_unverified"] is True
    assert res["missing_count"] == 2
    assert "2406.17940" in res["missing_ids_sample"]
    assert "2407.00005" in res["missing_ids_sample"]


def test_mock_data_separation_defaults():
    """Kiểm tra giá trị mặc định của generate_mock_data và merge_shards tách biệt thư mục mock/real."""
    import inspect
    from src.crawler.generate_mock_data import generate_all_mock_data

    sig_gen = inspect.signature(generate_all_mock_data)
    assert sig_gen.parameters["shards_dir"].default == "data/mock/shards"


def test_merge_shards_missing_status_and_size(tmp_path):
    """Khi bài báo trong shard không có source_status và size:
    - paper_crawl_success_rate = None
    - source_version_coverage_rate = None
    - total_source_size_before_bytes = None
    - total_source_size_after_bytes = None
    - source_status_breakdown = {}
    - paper_success_rate_from_stats tính từ stats.json dự phòng."""
    shards_dir = str(tmp_path / "shards")
    output_dir = str(tmp_path / "processed")
    member_dir = os.path.join(shards_dir, "24120470")
    os.makedirs(member_dir, exist_ok=True)

    pubs = [
        {
            "id": "2406.17938",
            "title": "Paper Without Status",
            "source_status": None,
            "size_before_bytes": None,
            "size_after_bytes": None,
            "versions": [{"version": "v1", "source_status": None, "size_before_bytes": None, "size_after_bytes": None}],
        }
    ]
    refs = [
        {
            "arxiv_id": "2406.17938",
            "ref_arxiv_id": "2301.00001",
            "ref_title": "Ref Title",
        }
    ]
    save_publications_parquet(pubs, os.path.join(member_dir, "publications.parquet"))
    save_references_parquet(refs, os.path.join(member_dir, "references.parquet"))

    stats_data = {
        "member_id": "24120470",
        "is_mock": False,
        "runtime_sec": 10.0,
        "results": {
            "total_ids": 1,
            "succeeded": 1,
            "failed": 0,
            "not_found": 0,
            "source_size_before_bytes": 5000,
            "source_size_after_bytes": 2000,
        },
    }
    with open(os.path.join(member_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats_data, f)

    res = merge_all_shards(shards_dir=shards_dir, output_dir=output_dir, allow_mock=False)
    assert res["paper_crawl_success_rate"] is None
    assert res["source_version_coverage_rate"] is None
    assert res["total_source_size_before_bytes"] is None
    assert res["total_source_size_after_bytes"] is None
    assert res["source_status_breakdown"] == {}
    assert res["paper_success_rate_from_stats"] == 1.0
    assert res["stats_results_backup"]["source_size_before_bytes"] == 5000


def test_merge_shards_directory_defaults(tmp_path, monkeypatch):
    """Kiểm tra mặc định thư mục của merge_shards bằng monkeypatch.chdir(tmp_path) không mock exists:
    - Khi shards_dir=None: allow_mock=False trỏ về data/shards, allow_mock=True trỏ về data/mock/shards.
    - Khi shards_dir tùy biến (không phải mặc định) và output_dir=None: xuất ra processed cạnh shards_dir.
    """
    monkeypatch.chdir(tmp_path)

    # 1. shards_dir=None, allow_mock=False -> FileNotFoundError trỏ tới data/shards
    with pytest.raises(FileNotFoundError, match="data/shards"):
        merge_all_shards(shards_dir=None, output_dir=None, allow_mock=False)

    # 2. shards_dir=None, allow_mock=True -> FileNotFoundError trỏ tới data/mock/shards
    with pytest.raises(FileNotFoundError, match="data/mock/shards"):
        merge_all_shards(shards_dir=None, output_dir=None, allow_mock=True)

    # 3. shards_dir tùy biến và output_dir=None -> xuất ra processed cạnh shards_dir
    custom_shards = tmp_path / "custom" / "shards"
    custom_member = custom_shards / "24120470"
    custom_member.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([{"id": "2406.17938", "title": "Custom Test"}], str(custom_member / "publications.parquet"))
    save_references_parquet([], str(custom_member / "references.parquet"))
    with open(custom_member / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    res = merge_all_shards(shards_dir=str(custom_shards), output_dir=None, allow_mock=False)
    expected_processed = tmp_path / "custom" / "processed"
    assert (expected_processed / "publications.parquet").exists()
    assert (expected_processed / "overall_stats.json").exists()
    assert not (tmp_path / "data" / "processed").exists()


def test_version_sorting_v10_v2_v1():
    """Kiểm tra sắp xếp version theo số nguyên: v10, v2, v1 -> v1, v2, v10 và gán chỉ số bài vào v10."""
    raw = {
        "id": "2406.17938",
        "title": "Version Sorting Paper",
        "source_status": "success",
        "size_before_bytes": 10000,
        "size_after_bytes": 4000,
        "versions": [
            {"version": "v10", "created": "2024-06-10T00:00:00Z"},
            {"version": "v2", "created": "2024-06-02T00:00:00Z"},
            {"version": "v1", "created": "2024-06-01T00:00:00Z"},
        ],
    }
    norm, errs = normalize_publication_record(raw)
    assert not errs
    ver_names = [v["version"] for v in norm["versions"]]
    assert ver_names == ["v1", "v2", "v10"]
    # Metric cấp bài gán vào version cuối cùng (v10)
    assert norm["versions"][-1]["version"] == "v10"
    assert norm["versions"][-1]["source_status"] == "success"
    assert norm["versions"][-1]["size_before_bytes"] == 10000
    assert norm["versions"][0]["source_status"] is None


def test_unknown_source_status_paper_and_version(caplog):
    """Trạng thái lạ cấp bài và cấp version phải chuyển thành None và log cảnh báo."""
    import logging
    raw = {
        "id": "2406.17938",
        "title": "Unknown Status Paper",
        "source_status": "corrupted_archive_status",  # Lạ cấp bài
        "versions": [
            {"version": "v1", "source_status": "weird_sub_status"},  # Lạ cấp version
        ],
    }
    with caplog.at_level(logging.WARNING):
        norm, errs = normalize_publication_record(raw)
    assert not errs
    assert norm["source_status"] is None
    assert norm["versions"][0]["source_status"] is None
    assert any("corrupted_archive_status" in r.message for r in caplog.records)
    assert any("weird_sub_status" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. Tests Bổ sung: Schema Nullability, String Preservation, Inf, Quarantine Dedup, Date Validation
# ---------------------------------------------------------------------------

def test_schemas_nullability():
    """Kiểm tra tính nullability của các trường trong Schema:
    - PUBLICATIONS_SCHEMA: duy nhất 'id' có nullable=False, 15 trường còn lại nullable=True.
    - REFERENCES_SCHEMA: duy nhất 'arxiv_id' có nullable=False, 10 trường còn lại nullable=True.
    """
    id_field = PUBLICATIONS_SCHEMA.field("id")
    assert id_field.nullable is False
    for f in PUBLICATIONS_SCHEMA:
        if f.name != "id":
            assert f.nullable is True, f"Trường {f.name} trong PUBLICATIONS_SCHEMA phải nullable=True"

    arxiv_id_field = REFERENCES_SCHEMA.field("arxiv_id")
    assert arxiv_id_field.nullable is False
    for f in REFERENCES_SCHEMA:
        if f.name != "arxiv_id":
            assert f.nullable is True, f"Trường {f.name} trong REFERENCES_SCHEMA phải nullable=True"


def test_is_null_string_and_nan_preservation(tmp_path):
    """Kiểm tra _is_null không xem các chuỗi 'nan', 'NaN', '<NA>', 'NaT' là null,
    đồng thời bảo toàn các chuỗi này khi ghi Parquet.
    """
    import math
    import pandas as pd
    import numpy as np

    # Không xem chuỗi là null
    assert _is_null("nan") is False
    assert _is_null("NaN") is False
    assert _is_null("<NA>") is False
    assert _is_null("NaT") is False

    # Xem các giá trị null thực sự là null
    assert _is_null(None) is True
    assert _is_null(float("nan")) is True
    assert _is_null(np.nan) is True
    assert _is_null(pd.NA) is True
    assert _is_null(pd.NaT) is True

    # Kiểm tra Round-trip bảo toàn tiêu đề chứa 'NaN'
    pub_path = str(tmp_path / "nan_title.parquet")
    records = [{
        "id": "2406.17938",
        "title": "A Study of NaN and <NA> Representations in NLP",
    }]
    save_publications_parquet(records, pub_path)
    tbl = pq.read_table(pub_path)
    res = tbl.to_pylist()[0]
    assert res["title"] == "A Study of NaN and <NA> Representations in NLP"


def test_to_non_negative_int_handles_inf_and_negative():
    """Kiểm tra _to_non_negative_int bắt OverflowError/inf và số âm -> chuyển thành None."""
    assert _to_non_negative_int(float("inf")) is None
    assert _to_non_negative_int(-float("inf")) is None
    assert _to_non_negative_int(-100) is None
    assert _to_non_negative_int(-1) is None
    assert _to_non_negative_int(0) == 0
    assert _to_non_negative_int(5000) == 5000
    assert _to_non_negative_int("12345") == 12345
    assert _to_non_negative_int(None) is None


def test_quarantine_deduplication_on_rerun(tmp_path):
    """Kiểm tra file cách ly _rejected_*.jsonl không bị ghi trùng lặp dòng khi chạy lại."""
    pub_path = str(tmp_path / "rerun_quarantine.parquet")
    bad_record = [{"id": None, "title": "Missing ID Paper"}]

    # Ghi lần 1
    save_publications_parquet(bad_record, pub_path, on_invalid="quarantine")
    rej_path = str(tmp_path / "_rejected_rerun_quarantine.jsonl")
    assert os.path.exists(rej_path)
    with open(rej_path, "r", encoding="utf-8") as f:
        lines_1 = [line.strip() for line in f if line.strip()]
    assert len(lines_1) == 1

    # Ghi lần 2 với cùng bản ghi hỏng đó
    save_publications_parquet(bad_record, pub_path, on_invalid="quarantine")
    with open(rej_path, "r", encoding="utf-8") as f:
        lines_2 = [line.strip() for line in f if line.strip()]
    assert len(lines_2) == 1  # Không bị nhân đôi dòng trùng lặp


def test_ref_submission_date_strict_calendar_validation():
    """Kiểm tra ref_submission_date chỉ nhận chuỗi YYYY-MM-DD hợp lệ, không suy đoán từ ref_year."""
    # Ngày hợp lệ
    rec1 = {"arxiv_id": "2406.00001", "ref_submission_date": "2024-06-15", "ref_year": 2024}
    norm1, _ = normalize_reference_record(rec1)
    assert norm1["ref_submission_date"] == "2024-06-15"

    # Ngày nhuận hợp lệ (năm 2024 nhuận có 29 ngày)
    rec_leap = {"arxiv_id": "2406.00001", "ref_submission_date": "2024-02-29"}
    norm_leap, _ = normalize_reference_record(rec_leap)
    assert norm_leap["ref_submission_date"] == "2024-02-29"

    # Ngày không hợp lệ theo lịch (năm 2023 không nhuận)
    rec2 = {"arxiv_id": "2406.00001", "ref_submission_date": "2023-02-29"}
    norm2, _ = normalize_reference_record(rec2)
    assert norm2["ref_submission_date"] is None

    # Sai format (chỉ có năm hoặc tháng không hợp lệ)
    rec3 = {"arxiv_id": "2406.00001", "ref_submission_date": "2024", "ref_year": 2024}
    norm3, _ = normalize_reference_record(rec3)
    assert norm3["ref_submission_date"] is None  # Không suy đoán từ ref_year

    rec4 = {"arxiv_id": "2406.00001", "ref_submission_date": "2024-13-01"}
    norm4, _ = normalize_reference_record(rec4)
    assert norm4["ref_submission_date"] is None


def test_empty_versions_synthesizes_v1_and_counts(caplog):
    """Kiểm tra bài báo có versions rỗng [] sẽ tự động tạo struct version v1 mặc định,
    log cảnh báo và tăng bộ đếm papers_with_synthesized_v1.
    """
    import logging
    reset_synthesized_v1_count()
    start_count = get_synthesized_v1_count()

    raw = {
        "id": "2406.17938",
        "title": "Empty Versions Paper",
        "published": "2024-06-01T00:00:00Z",
        "size_before_bytes": 1000,
        "size_after_bytes": 500,
        "source_status": "success",
        "versions": [],  # Rỗng
    }

    with caplog.at_level(logging.WARNING):
        norm, errs = normalize_publication_record(raw)

    assert not errs
    assert len(norm["versions"]) == 1
    assert norm["versions"][0]["version"] == "v1"
    assert norm["versions"][0]["size_before_bytes"] == 1000
    assert norm["versions"][0]["source_status"] == "success"
    assert get_synthesized_v1_count() == start_count + 1
    assert any("tự động tổng hợp v1 mặc định" in r.message for r in caplog.records)


def test_mock_data_edge_cases_and_merge_stats(tmp_path):
    """Kiểm thử dữ liệu mock bao gồm các ca biên theo yêu cầu:
    1. Bài thiếu title, authors, abstract.
    2. Bài versions rỗng (được tổng hợp v1).
    3. Reference có ref_arxiv_id = None.
    4. overall_stats có papers_with_synthesized_v1 > 0.
    """
    reset_synthesized_v1_count()
    shards_dir = str(tmp_path / "shards")
    output_dir = str(tmp_path / "processed")

    generate_all_mock_data(shards_dir=shards_dir, force=True, seed=42)

    # Đọc shard 24120470 để kiểm tra các ca biên
    tri_pub_path = os.path.join(shards_dir, "24120470", "publications.parquet")
    tri_ref_path = os.path.join(shards_dir, "24120470", "references.parquet")
    pubs = pq.read_table(tri_pub_path).to_pylist()
    refs = pq.read_table(tri_ref_path).to_pylist()

    # Ca 1: Bài thiếu title, authors, abstract
    missing_meta_pub = next((p for p in pubs if p["id"] == "2406.17939"), None)
    assert missing_meta_pub is not None
    assert missing_meta_pub["title"] is None
    assert missing_meta_pub["abstract"] is None
    assert missing_meta_pub["authors"] == []

    # Ca 2: Bài versions rỗng đã được tổng hợp v1
    synthesized_pub = next((p for p in pubs if p["id"] == "2407.00001"), None)
    assert synthesized_pub is not None
    assert len(synthesized_pub["versions"]) == 1
    assert synthesized_pub["versions"][0]["version"] == "v1"

    # Ca 3: Reference có ref_arxiv_id is None
    ref_with_none_arxiv = next((r for r in refs if r["ref_arxiv_id"] is None), None)
    assert ref_with_none_arxiv is not None
    assert ref_with_none_arxiv["ref_title"] is not None

    # Gộp shard và kiểm tra overall_stats
    stats = merge_all_shards(shards_dir=shards_dir, output_dir=output_dir, allow_mock=True)
    assert stats.get("papers_with_synthesized_v1", 0) > 0
    assert stats.get("synthesized_v1_note") == "Chỉ tính từ các shard có báo cáo số này trong stats.json."


def test_merge_shard_without_synthesized_v1_key_ignores_global_counter(tmp_path):
    """(a) Merge một shard không có key papers_with_synthesized_v1 trong stats.json,
    trong khi trước đó cùng tiến trình test đã gọi save_publications_parquet với bản ghi versions rỗng
    (làm bộ đếm toàn cục tăng).
    Assert overall_stats KHÔNG có key papers_with_synthesized_v1.
    """
    # 1. Gọi save_publications_parquet với versions rỗng để tăng bộ đếm toàn cục
    dummy_pub = str(tmp_path / "dummy_synth.parquet")
    save_publications_parquet([{"id": "2406.99999", "versions": []}], dummy_pub)
    assert get_synthesized_v1_count() > 0

    # 2. Tạo shard không có key papers_with_synthesized_v1 trong stats.json
    shards_dir = tmp_path / "shards"
    member_dir = shards_dir / "24120470"
    member_dir.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([{"id": "2406.17938", "title": "Paper 1"}], str(member_dir / "publications.parquet"))
    save_references_parquet([], str(member_dir / "references.parquet"))

    # stats.json KHÔNG có key papers_with_synthesized_v1 (cả ở root lẫn trong results)
    stats_data = {
        "member_id": "24120470",
        "is_mock": False,
        "runtime_sec": 5.0,
        "results": {
            "total_ids": 1,
            "succeeded": 1,
            "failed": 0,
            "not_found": 0,
        },
    }
    with open(member_dir / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_data, f)

    # 3. Merge shards
    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    # 4. Assert overall_stats không có key papers_with_synthesized_v1
    assert "papers_with_synthesized_v1" not in res
    assert "synthesized_v1_note" not in res


def test_merge_shards_with_synthesized_v1_key_sums_and_adds_note(tmp_path):
    """(b) Merge hai shard mock có key này (ví dụ 1 và 2).
    Assert kết quả là 3 và có synthesized_v1_note.
    """
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard2 = shards_dir / "24120474"
    shard1.mkdir(parents=True, exist_ok=True)
    shard2.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([{"id": "2406.17938", "title": "Paper 1"}], str(shard1 / "publications.parquet"))
    save_references_parquet([], str(shard1 / "references.parquet"))
    # Shard 1: key ở root level
    stats1 = {
        "member_id": "24120470",
        "is_mock": True,
        "runtime_sec": 1.0,
        "papers_with_synthesized_v1": 1,
        "results": {"total_ids": 1},
    }
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats1, f)

    save_publications_parquet([{"id": "2406.12938", "title": "Paper 2"}], str(shard2 / "publications.parquet"))
    save_references_parquet([], str(shard2 / "references.parquet"))
    # Shard 2: key trong results
    stats2 = {
        "member_id": "24120474",
        "is_mock": True,
        "runtime_sec": 1.0,
        "results": {"total_ids": 1, "papers_with_synthesized_v1": 2},
    }
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats2, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=True)

    assert res["papers_with_synthesized_v1"] == 3
    assert res["synthesized_v1_note"] == "Chỉ tính từ các shard có báo cáo số này trong stats.json."


def test_dropped_ref_dates_count_and_retention(tmp_path):
    """(c) Gọi reset_dropped_ref_dates_count(), ghi references với ngày
    '2023-13-45', '2023-01', '2023-01-15' và None.
    Assert bộ đếm bằng 2 (chỉ hai giá trị không hợp lệ khác null)
    và hai bản ghi hợp lệ/null được giữ đúng.
    """
    reset_dropped_ref_dates_count()

    refs = [
        {"arxiv_id": "2406.00001", "ref_submission_date": "2023-13-45"},
        {"arxiv_id": "2406.00001", "ref_submission_date": "2023-01"},
        {"arxiv_id": "2406.00001", "ref_submission_date": "2023-01-15"},
        {"arxiv_id": "2406.00001", "ref_submission_date": None},
    ]
    ref_path = str(tmp_path / "refs_dates.parquet")
    save_references_parquet(refs, ref_path)

    # Assert bộ đếm bằng 2 (chỉ hai giá trị không hợp lệ khác null)
    assert get_dropped_ref_dates_count() == 2

    # Đọc lại và kiểm tra hai bản ghi hợp lệ/null được giữ đúng
    table = pq.read_table(ref_path).to_pylist()
    assert len(table) == 4
    assert table[0]["ref_submission_date"] is None  # '2023-13-45' -> None
    assert table[1]["ref_submission_date"] is None  # '2023-01' -> None
    assert table[2]["ref_submission_date"] == "2023-01-15"  # hợp lệ -> giữ nguyên
    assert table[3]["ref_submission_date"] is None  # vốn là None -> giữ nguyên


# ---------------------------------------------------------------------------
# 5. Tests bổ sung cho Deduplication, ID Coverage robustness, và Before Dedup
# ---------------------------------------------------------------------------

def test_dedup_publications_newer_updated_wins(tmp_path):
    """Hai shard cùng id 2406.17937, updated khác nhau, title khác nhau.
    Assert bản có updated mới hơn thắng (kiểm bằng title) và duplicate_publications_removed == 1.
    """
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard2 = shards_dir / "24120474"
    shard1.mkdir(parents=True, exist_ok=True)
    shard2.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([
        {"id": "2406.17937", "updated": "2024-06-10", "title": "Older Title"}
    ], str(shard1 / "publications.parquet"))
    save_references_parquet([], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    save_publications_parquet([
        {"id": "2406.17937", "updated": "2024-06-20", "title": "Newer Title"}
    ], str(shard2 / "publications.parquet"))
    save_references_parquet([], str(shard2 / "references.parquet"))
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120474", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    assert res["duplicate_publications_removed"] == 1
    assert res["total_publications"] == 1

    merged_pubs = pq.read_table(str(out_dir / "publications.parquet")).to_pylist()
    assert len(merged_pubs) == 1
    assert merged_pubs[0]["title"] == "Newer Title"
    assert merged_pubs[0]["updated"].strftime("%Y-%m-%d") == "2024-06-20"


def test_dedup_publications_tie_fewer_nulls_wins(tmp_path):
    """Cùng id, cùng updated, một bản có doi/journal_ref và một bản thiếu (None).
    Assert bản ít None thắng.
    """
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard2 = shards_dir / "24120474"
    shard1.mkdir(parents=True, exist_ok=True)
    shard2.mkdir(parents=True, exist_ok=True)

    # Shard 1: nhiều trường None hơn
    save_publications_parquet([{
        "id": "2406.17937",
        "updated": "2024-06-15",
        "title": "Less Complete",
        "doi": None,
        "journal_ref": None,
    }], str(shard1 / "publications.parquet"))
    save_references_parquet([], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    # Shard 2: ít trường None hơn (có doi và journal_ref)
    save_publications_parquet([{
        "id": "2406.17937",
        "updated": "2024-06-15",
        "title": "More Complete",
        "doi": "10.1234/example",
        "journal_ref": "J. Phys. A",
    }], str(shard2 / "publications.parquet"))
    save_references_parquet([], str(shard2 / "references.parquet"))
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120474", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    assert res["duplicate_publications_removed"] == 1
    assert res["total_publications"] == 1

    merged_pubs = pq.read_table(str(out_dir / "publications.parquet")).to_pylist()
    assert len(merged_pubs) == 1
    assert merged_pubs[0]["title"] == "More Complete"
    assert merged_pubs[0]["doi"] == "10.1234/example"
    assert merged_pubs[0]["journal_ref"] == "J. Phys. A"


def test_merged_publications_sorted_by_id(tmp_path):
    """Nhiều id đảo thứ tự giữa các shard; đọc publications.parquet gộp và assert danh sách id đã sắp tăng dần."""
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard2 = shards_dir / "24120474"
    shard1.mkdir(parents=True, exist_ok=True)
    shard2.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([
        {"id": "2406.17940", "title": "Paper 40"},
        {"id": "2406.17938", "title": "Paper 38"},
    ], str(shard1 / "publications.parquet"))
    save_references_parquet([], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    save_publications_parquet([
        {"id": "2406.17939", "title": "Paper 39"},
        {"id": "2406.17937", "title": "Paper 37"},
    ], str(shard2 / "publications.parquet"))
    save_references_parquet([], str(shard2 / "references.parquet"))
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120474", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir = tmp_path / "processed"
    merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    merged_pubs = pq.read_table(str(out_dir / "publications.parquet")).to_pylist()
    merged_ids = [p["id"] for p in merged_pubs]
    assert merged_ids == ["2406.17937", "2406.17938", "2406.17939", "2406.17940"]
    assert merged_ids == sorted(merged_ids)


def test_references_same_source_stay_multiple_rows(tmp_path):
    """Một bài nguồn có 3 reference khác nhau (khác s2 id/arxiv id/title) -> kết quả đủ 3 hàng, không bị gộp."""
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard1.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([{"id": "2406.17937", "title": "Source Paper"}], str(shard1 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.17937", "ref_s2_id": "s2_abc", "ref_title": "Ref A"},
        {"arxiv_id": "2406.17937", "ref_arxiv_id": "1901.00001", "ref_title": "Ref B"},
        {"arxiv_id": "2406.17937", "ref_title": "Ref C Unique Title"},
    ], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    assert res["total_references"] == 3
    assert res["duplicate_references_removed"] == 0

    merged_refs = pq.read_table(str(out_dir / "references.parquet")).to_pylist()
    assert len(merged_refs) == 3


def test_references_cross_shard_duplicate_removed(tmp_path):
    """Cùng (arxiv_id, ref_s2_id) ở hai shard -> còn 1 hàng, duplicate_references_removed == 1."""
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard2 = shards_dir / "24120474"
    shard1.mkdir(parents=True, exist_ok=True)
    shard2.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([{"id": "2406.17937", "title": "Paper 1"}], str(shard1 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.17937", "ref_s2_id": "s2_common", "ref_title": "Title From Shard 1"}
    ], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    save_publications_parquet([{"id": "2406.17937", "title": "Paper 1"}], str(shard2 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.17937", "ref_s2_id": "s2_common", "ref_title": "Title From Shard 2"}
    ], str(shard2 / "references.parquet"))
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120474", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    assert res["total_references"] == 1
    assert res["duplicate_references_removed"] == 1

    merged_refs = pq.read_table(str(out_dir / "references.parquet")).to_pylist()
    assert len(merged_refs) == 1


def test_references_fallback_dedup_no_identifiers(tmp_path):
    """Hai reference chỉ khác ref_year (không s2/arxiv/doi/title/raw_citation) -> ra 2 hàng;
    hai reference y hệt nhau -> ra 1 hàng.
    """
    # Ca 1: Khác ref_year -> 2 hàng
    shards_dir1 = tmp_path / "shards_diff_year"
    shard1 = shards_dir1 / "24120470"
    shard1.mkdir(parents=True, exist_ok=True)
    save_publications_parquet([{"id": "2406.17937", "title": "Paper"}], str(shard1 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.17937", "ref_year": 2020},
        {"arxiv_id": "2406.17937", "ref_year": 2021},
    ], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir1 = tmp_path / "processed_diff_year"
    res1 = merge_all_shards(shards_dir=str(shards_dir1), output_dir=str(out_dir1), allow_mock=False)
    assert res1["total_references"] == 2
    assert res1["duplicate_references_removed"] == 0

    # Ca 2: Hai reference y hệt nhau (không định danh) -> ra 1 hàng, lọc 1 trùng lặp
    shards_dir2 = tmp_path / "shards_identical"
    shard2 = shards_dir2 / "24120470"
    shard2.mkdir(parents=True, exist_ok=True)
    save_publications_parquet([{"id": "2406.17937", "title": "Paper"}], str(shard2 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.17937", "ref_year": 2020},
        {"arxiv_id": "2406.17937", "ref_year": 2020},
    ], str(shard2 / "references.parquet"))
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir2 = tmp_path / "processed_identical"
    res2 = merge_all_shards(shards_dir=str(shards_dir2), output_dir=str(out_dir2), allow_mock=False)
    assert res2["total_references"] == 1
    assert res2["duplicate_references_removed"] == 1


def test_check_id_coverage_malformed_inputs():
    """_check_id_coverage với id_range = 'abc', {'start_id': 'x'}, {} -> không ném, has_assigned_range False."""
    from src.crawler.merge_shards import _check_id_coverage

    # 1. id_range là chuỗi
    res_str = _check_id_coverage("abc", {"2406.00001"})
    assert res_str["has_assigned_range"] is False
    assert res_str["total_found"] == 1
    assert res_str["missing_count"] == 0
    assert res_str["out_of_range_count"] == 0
    assert res_str["tail_unverified"] is False
    assert "coverage_error" in res_str

    # 2. id_range có start_id không parse được int hoặc thiếu end_id
    res_val = _check_id_coverage({"start_id": "x"}, {"2406.00001"})
    assert res_val["has_assigned_range"] is False
    assert res_val["total_found"] == 1
    assert res_val["missing_count"] == 0
    assert "coverage_error" in res_val

    # 3. id_range rỗng {} (giữ nguyên hành vi gốc, không thêm coverage_error)
    res_empty = _check_id_coverage({}, {"2406.00001"})
    assert res_empty["has_assigned_range"] is False
    assert res_empty["total_found"] == 1
    assert res_empty["missing_count"] == 0
    assert res_empty["out_of_range_count"] == 0
    assert res_empty["tail_unverified"] is False
    assert "coverage_error" not in res_empty


def test_merge_all_shards_with_malformed_id_range(tmp_path):
    """merge_all_shards với một shard có id_range sai định dạng -> chạy xong, shard vẫn được gộp,
    member_breakdown của shard đó có id_coverage.has_assigned_range == False.
    """
    shards_dir = tmp_path / "shards"
    shard = shards_dir / "24120470"
    shard.mkdir(parents=True, exist_ok=True)

    save_publications_parquet([{"id": "2406.17938", "title": "Paper 1"}], str(shard / "publications.parquet"))
    save_references_parquet([], str(shard / "references.parquet"))

    stats_data = {
        "member_id": "24120470",
        "is_mock": False,
        "runtime_sec": 2.0,
        "id_range": "sai_dinh_dang_chuoi",
    }
    with open(shard / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_data, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    assert res["total_publications"] == 1
    mb = res["member_breakdown"][0]
    assert mb["member_id"] == "24120470"
    assert mb["id_coverage"]["has_assigned_range"] is False
    assert "coverage_error" in mb["id_coverage"]


def test_check_id_coverage_same_month_missing_id():
    """_check_id_coverage cùng tháng (ví dụ 2502.03235 -> 2502.03240, thiếu 1 ID)
    -> missing_count == 1, tail_unverified False.
    """
    from src.crawler.merge_shards import _check_id_coverage

    assigned_range = {
        "start_month": "2502",
        "start_id": 3235,
        "end_month": "2502",
        "end_id": 3240,
    }
    # 6 IDs kỳ vọng: 03235, 03236, 03237, 03238, 03239, 03240. Thiếu 03239.
    found_ids = {
        "2502.03235",
        "2502.03236",
        "2502.03237",
        "2502.03238",
        "2502.03240",
    }
    res = _check_id_coverage(assigned_range, found_ids)
    assert res["has_assigned_range"] is True
    assert res["missing_count"] == 1
    assert res["tail_unverified"] is False
    assert "2502.03239" in res["missing_ids_sample"]
    assert res["out_of_range_count"] == 0


def test_overall_stats_records_before_dedup(tmp_path):
    """Thêm số bản ghi TRƯỚC gộp vào overall_stats:
    assert before_pub == total_publications + duplicate_publications_removed,
    và before_ref == total_references + duplicate_references_removed.
    Dựng dữ liệu sao cho không có bản ghi mất id.
    """
    shards_dir = tmp_path / "shards"
    shard1 = shards_dir / "24120470"
    shard2 = shards_dir / "24120474"
    shard1.mkdir(parents=True, exist_ok=True)
    shard2.mkdir(parents=True, exist_ok=True)

    # Shard 1: 3 bài, 3 trích dẫn
    save_publications_parquet([
        {"id": "2406.00001", "title": "Paper 1"},
        {"id": "2406.00002", "title": "Paper 2"},
        {"id": "2406.00003", "title": "Paper 3"},
    ], str(shard1 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.00001", "ref_s2_id": "s1", "ref_title": "Ref 1"},
        {"arxiv_id": "2406.00001", "ref_s2_id": "s2", "ref_title": "Ref 2"},
        {"arxiv_id": "2406.00001", "ref_s2_id": "s3", "ref_title": "Ref 3"},
    ], str(shard1 / "references.parquet"))
    with open(shard1 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120470", "is_mock": False, "runtime_sec": 1.0}, f)

    # Shard 2: 2 bài (1 trùng: 2406.00002, 1 mới: 2406.00004),
    # 2 trích dẫn (1 trùng: s2 cho 2406.00001, 1 mới: s4 cho 2406.00004)
    save_publications_parquet([
        {"id": "2406.00002", "title": "Paper 2 Duplicate"},
        {"id": "2406.00004", "title": "Paper 4"},
    ], str(shard2 / "publications.parquet"))
    save_references_parquet([
        {"arxiv_id": "2406.00001", "ref_s2_id": "s2", "ref_title": "Ref 2 Duplicate"},
        {"arxiv_id": "2406.00004", "ref_s2_id": "s4", "ref_title": "Ref 4"},
    ], str(shard2 / "references.parquet"))
    with open(shard2 / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"member_id": "24120474", "is_mock": False, "runtime_sec": 1.0}, f)

    out_dir = tmp_path / "processed"
    res = merge_all_shards(shards_dir=str(shards_dir), output_dir=str(out_dir), allow_mock=False)

    # Kỳ vọng tính tay:
    # raw_pubs = 3 + 2 = 5. unique_pubs = 4. dup_pub_count = 1.
    assert res["total_publications_before_dedup"] == 5
    assert res["total_publications"] == 4
    assert res["duplicate_publications_removed"] == 1
    assert res["total_publications_before_dedup"] == res["total_publications"] + res["duplicate_publications_removed"]

    # raw_refs = 3 + 2 = 5. unique_refs = 4. dup_ref_count = 1.
    assert res["total_references_before_dedup"] == 5
    assert res["total_references"] == 4
    assert res["duplicate_references_removed"] == 1
    assert res["total_references_before_dedup"] == res["total_references"] + res["duplicate_references_removed"]



