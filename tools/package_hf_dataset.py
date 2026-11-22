"""Đóng gói và kiểm chuẩn bộ dữ liệu 6 bảng Parquet chuẩn Hugging Face (M1 + M2 + M3)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from src.crawler.storage import COURSE_PAPERS_SCHEMA, COURSE_REFERENCES_SCHEMA
from src.matching.model import PREDICTIONS_SCHEMA
from src.parser.storage import BIBTEX_SCHEMA, ELEMENTS_SCHEMA, HIERARCHY_SCHEMA

TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "papers": COURSE_PAPERS_SCHEMA,
    "references": COURSE_REFERENCES_SCHEMA,
    "elements": ELEMENTS_SCHEMA,
    "hierarchy": HIERARCHY_SCHEMA,
    "bibtex": BIBTEX_SCHEMA,
    "predictions": PREDICTIONS_SCHEMA,
}

NON_NULL_COLUMNS: dict[str, tuple[str, ...]] = {
    "papers": ("arxiv_id",),
    "references": ("arxiv_id", "ref_arxiv_id"),
    "elements": ("element_id", "arxiv_id"),
    "hierarchy": ("arxiv_id", "element_id", "parent_id"),
    "bibtex": ("arxiv_id", "citation_key"),
    "predictions": ("arxiv_id", "partition", "citation_key"),
}

DEFAULT_MAX_ROWS_PER_SHARD: dict[str, int] = {
    "papers": 250_000,
    "references": 500_000,
    "elements": 1_000_000,
    "hierarchy": 1_500_000,
    "bibtex": 500_000,
    "predictions": 250_000,
}


def _cast_batch_to_schema(batch: pa.RecordBatch, schema: pa.Schema) -> pa.RecordBatch:
    if batch.schema.equals(schema, check_metadata=False):
        return batch
    table = pa.Table.from_batches([batch]).cast(schema)
    return table.to_batches()[0]


def _write_sharded_table(
    src_paths: list[Path],
    dest_dir: Path,
    table_name: str,
    schema: pa.Schema,
    max_rows_per_shard: int,
) -> dict[str, Any]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("*.parquet"):
        old.unlink()

    shard_idx = 0
    rows_in_shard = 0
    total_rows = 0
    total_bytes = 0
    shard_files: list[str] = []
    writer: pq.ParquetWriter | None = None
    tmp_path: Path | None = None
    final_path: Path | None = None

    def _close_writer() -> None:
        nonlocal writer, tmp_path, final_path, total_bytes, shard_idx, rows_in_shard
        if writer is not None:
            writer.close()
            writer = None
            assert tmp_path is not None and final_path is not None
            os.replace(tmp_path, final_path)
            total_bytes += final_path.stat().st_size
            shard_files.append(final_path.name)
            shard_idx += 1
            rows_in_shard = 0

    try:
        for src in src_paths:
            pf = pq.ParquetFile(src)
            for batch in pf.iter_batches(batch_size=65536):
                if batch.num_rows == 0:
                    continue
                casted = _cast_batch_to_schema(batch, schema)
                offset = 0
                while offset < casted.num_rows:
                    if writer is None:
                        final_path = dest_dir / f"{table_name}-{shard_idx:05d}.parquet"
                        tmp_path = final_path.with_suffix(".parquet.tmp")
                        writer = pq.ParquetWriter(tmp_path, schema, compression="snappy")
                    room = max_rows_per_shard - rows_in_shard
                    take = min(room, casted.num_rows - offset)
                    sub_batch = casted.slice(offset, take)
                    writer.write_batch(sub_batch)
                    rows_in_shard += take
                    total_rows += take
                    offset += take
                    if rows_in_shard >= max_rows_per_shard:
                        _close_writer()
        _close_writer()
    finally:
        if writer is not None:
            writer.close()
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # Bảo đảm luôn có ít nhất 1 file Parquet hợp lệ ngay cả khi bảng rỗng
    if not shard_files:
        final_path = dest_dir / f"{table_name}-00000.parquet"
        tmp_path = final_path.with_suffix(".parquet.tmp")
        pq.write_table(schema.empty_table(), tmp_path, compression="snappy")
        os.replace(tmp_path, final_path)
        total_bytes += final_path.stat().st_size
        shard_files.append(final_path.name)

    return {
        "shards": len(shard_files),
        "rows": total_rows,
        "bytes": total_bytes,
    }


def build_dataset_card(table_stats: dict[str, dict[str, Any]]) -> str:
    """Sinh Hugging Face Dataset Card (README.md) kèm YAML configs chuẩn cho 6 bảng."""
    yaml_configs = "\n".join(
        f"- config_name: {name}\n  data_files:\n  - split: train\n    path: data/{name}/*.parquet"
        for name in ("papers", "references", "elements", "hierarchy", "bibtex", "predictions")
    )
    rows_md = "\n".join(
        f"| `{name}` | `data/{name}/*.parquet` | {st['shards']} | {st['rows']:,} | {st['bytes'] / (1024 ** 2):,.2f} MiB |"
        for name, st in table_stats.items()
    )
    return f"""---
configs:
{yaml_configs}
license: cc-by-4.0
task_categories:
- text-retrieval
- feature-extraction
language:
- en
tags:
- arxiv
- scientific-publications
- latex
- bibtex
- reference-matching
size_categories:
- 10K<n<100K
---

# arXiv Harvester — Bộ dữ liệu 25.000 bài báo đa phiên bản (M1–M3)

Bộ dữ liệu Parquet phân mảnh phục vụ đồ án **arXiv Harvester** (Khoa Công nghệ Thông tin, Trường Đại học Khoa học Tự nhiên — ĐHQG TP.HCM), bao phủ **25.000 bài báo / 41.498 phiên bản** của 5 thành viên từ Milestone 1 (thu thập metadata & trích dẫn), Milestone 2 (phân tích cấu trúc phân cấp LaTeX/BibTeX & khử trùng) đến Milestone 3 (khớp tài liệu tham khảo BibTeX ↔ Semantic Scholar arXiv ID).

- **Mã nguồn & tài liệu đầy đủ:** [NguyenQuocDat06-AI/arxiv-harvester](https://github.com/NguyenQuocDat06-AI/arxiv-harvester)
- **Báo cáo Jupyter Book (M1–M2):** [nguyenquocdat06-ai.github.io/arxiv-harvester-book](https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/)

## Tổng hợp 6 bảng Parquet

| Bảng | Đường dẫn | Số shard | Số dòng | Dung lượng |
|---|---|---:|---:|---:|
{rows_md}

## Cách tải bằng `datasets`

```python
from datasets import load_dataset

papers = load_dataset("nquocdat06/arxiv-harvester-data", name="papers", split="train")
predictions = load_dataset("nquocdat06/arxiv-harvester-data", name="predictions", split="train")
```
"""


def validate_hf_staging(staging_dir: str | Path) -> dict[str, Any]:
    """Kiểm tra toàn diện cấu trúc thư mục, YAML card, Arrow schema và dữ liệu của 6 bảng."""
    root = Path(staging_dir).resolve()
    errors: list[str] = []
    table_reports: dict[str, Any] = {}

    readme_path = root / "README.md"
    if not readme_path.is_file():
        errors.append("Missing README.md dataset card")
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        for tbl in TABLE_SCHEMAS:
            if f"config_name: {tbl}" not in readme_text or f"path: data/{tbl}/*.parquet" not in readme_text:
                errors.append(f"README.md missing YAML config entry for {tbl}")

    for name, expected_schema in TABLE_SCHEMAS.items():
        tdir = root / "data" / name
        shards = sorted(tdir.glob("*.parquet")) if tdir.is_dir() else []
        if not shards:
            errors.append(f"Missing parquet shards for table {name}")
            table_reports[name] = {"shards": 0, "rows": 0, "bytes": 0, "valid": False}
            continue

        tbl_rows = 0
        tbl_bytes = 0
        tbl_ok = True
        for sp in shards:
            tbl_bytes += sp.stat().st_size
            pf = pq.ParquetFile(sp)
            if not pf.schema_arrow.equals(expected_schema, check_metadata=False):
                errors.append(f"Schema mismatch in {name}/{sp.name}")
                tbl_ok = False
                continue
            tbl_rows += pf.metadata.num_rows
            check_cols = list(NON_NULL_COLUMNS[name])
            for batch in pf.iter_batches(batch_size=65536, columns=check_cols):
                for col_name in check_cols:
                    arr = batch.column(col_name)
                    if arr.null_count > 0:
                        errors.append(f"Null values in required column {name}.{col_name} ({sp.name})")
                        tbl_ok = False
                    if pa.types.is_string(arr.type) and pc.any(pc.equal(arr, "")).as_py():
                        errors.append(f"Empty string in key column {name}.{col_name} ({sp.name})")
                        tbl_ok = False
                if name == "predictions":
                    parts = set(batch.column("partition").to_pylist())
                    bad = parts - {"train", "valid", "test"}
                    if bad:
                        errors.append(f"Invalid prediction partitions {sorted(bad)} in {sp.name}")
                        tbl_ok = False

        table_reports[name] = {
            "shards": len(shards),
            "rows": tbl_rows,
            "bytes": tbl_bytes,
            "valid": tbl_ok,
        }

    return {
        "valid": len(errors) == 0,
        "errors": sorted(set(errors)),
        "tables": table_reports,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def package_hf_dataset(
    *,
    course_dir: str | Path,
    parsed_dir: str | Path,
    predictions_dir: str | Path,
    output_dir: str | Path,
    max_rows_per_shard: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Đóng gói và kiểm chuẩn đủ 6 bảng Parquet chuẩn Hugging Face vào output_dir."""
    course_root = Path(course_dir)
    parsed_root = Path(parsed_dir)
    pred_root = Path(predictions_dir)
    out_root = Path(output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    limits = {**DEFAULT_MAX_ROWS_PER_SHARD, **(max_rows_per_shard or {})}

    sources: dict[str, list[Path]] = {
        "papers": [course_root / "papers.parquet"] if (course_root / "papers.parquet").is_file() else sorted((course_root / "papers").glob("*.parquet")),
        "references": [course_root / "references.parquet"] if (course_root / "references.parquet").is_file() else sorted((course_root / "references").glob("*.parquet")),
        "elements": sorted((parsed_root / "elements").glob("*.parquet")),
        "hierarchy": sorted((parsed_root / "hierarchy").glob("*.parquet")),
        "bibtex": sorted((parsed_root / "bibtex").glob("*.parquet")),
        "predictions": sorted(pred_root.glob("*.parquet")) if pred_root.is_dir() else ([pred_root] if pred_root.is_file() else []),
    }

    for tbl, paths in sources.items():
        if not paths:
            raise FileNotFoundError(f"No source Parquet files found for table '{tbl}'")

    table_stats: dict[str, dict[str, Any]] = {}
    for tbl in ("papers", "references", "elements", "hierarchy", "bibtex", "predictions"):
        table_stats[tbl] = _write_sharded_table(
            sources[tbl],
            out_root / "data" / tbl,
            tbl,
            TABLE_SCHEMAS[tbl],
            limits[tbl],
        )

    card_text = build_dataset_card(table_stats)
    (out_root / "README.md").write_text(card_text, encoding="utf-8")

    validation = validate_hf_staging(out_root)
    if not validation["valid"]:
        raise RuntimeError(f"HF staging validation failed: {validation['errors']}")

    manifest = {
        "staging_dir": str(out_root),
        "total_bytes": sum(v["bytes"] for v in table_stats.values()),
        **validation,
    }
    (out_root / "hf_staging_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Package all 6 M1-M3 Parquet tables into a Hugging Face staging directory.",
    )
    parser.add_argument("--course-dir", required=True, help="Directory holding papers.parquet and references.parquet")
    parser.add_argument("--parsed-dir", required=True, help="M2 parsed directory holding elements/, hierarchy/, bibtex/")
    parser.add_argument("--predictions-dir", required=True, help="M3 predictions Parquet file or directory")
    parser.add_argument("--output-dir", required=True, help="Destination Hugging Face staging directory")
    args = parser.parse_args(argv)

    manifest = package_hf_dataset(
        course_dir=args.course_dir,
        parsed_dir=args.parsed_dir,
        predictions_dir=args.predictions_dir,
        output_dir=args.output_dir,
    )
    print(
        f"[package_hf_dataset] valid={manifest['valid']} "
        f"total_mb={manifest['total_bytes'] / (1024 ** 2):.2f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
