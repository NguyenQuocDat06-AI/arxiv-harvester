"""Package workspace files for team review."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "24120282_NguyenQuocDat": {
        "name": "Nguyễn Quốc Đạt", "branch": "review/24120282-discovery-gathering",
        "files": ["src/crawler/id_range.py", "src/crawler/discovery.py", "src/crawler/version_history.py",
                  "src/crawler/rate_limiter.py", "src/crawler/request_policy.py",
                  "src/parser/__init__.py", "src/parser/latex.py", "src/parser/gather.py",
                  "docs/01_discovery_and_versions.ipynb", "configs/parser_roots.json", "configs/README.md",
                  "tasks/TASK_24120282_NguyenQuocDat.md"],
        "review": ["Phân biệt API error với ID không tồn tại; pacing arXiv tối thiểu 3 giây.",
                   "Bổ sung ngày revision bằng snapshot/OAI có bằng chứng, không tự gán ngày latest.",
                   "Kiểm tra root/include/comment/vòng include và source map; bổ sung test hoặc sửa lỗi thực tế phát hiện."],
    },
    "24120237_NguyenDinhTuan": {
        "name": "Nguyễn Đình Tuấn", "branch": "review/24120237-sources-hierarchy",
        "files": ["src/crawler/source_downloader.py", "src/crawler/validate_sources.py", "src/crawler/retry_sources.py",
                  "src/parser/hierarchy.py", "docs/02_source_download_and_cleaning.ipynb",
                  "docs/06_parsing_and_hierarchy.ipynb", "tasks/TASK_24120237_NguyenDinhTuan.md"],
        "review": ["Kiểm tra TeX/PDF/no-LaTeX, archive lỗi và rollback khi thay source thất bại.",
                   "Chạy audit/plan trên nguồn thực có sẵn; ghi rõ corpus đầy đủ chưa có, không tự chạy bulk.",
                   "Đối chiếu hierarchy với TeX: sentence/math/list/figure-table, acknowledgements/appendix và loại bibliography."],
    },
    "24120438_TranNguyenTan": {
        "name": "Trần Nguyên Tân", "branch": "review/24120438-references-bibliography",
        "files": ["src/crawler/reference_scraper.py", "src/crawler/reference_batch.py", "src/crawler/enrich_references.py", "src/parser/bibliography.py",
                  "docs/03_reference_extraction.ipynb", "tasks/TASK_24120438_TranNguyenTan.md"],
        "review": ["Kiểm tra phân trang, empty/not_indexed/API error, Retry-After và provenance cạnh/metadata.",
                   "Xác minh xung đột S2/arXiv và quy tắc ref_submission_date; không coi S2 publication date là ngày nộp đã xác minh.",
                   "Kiểm tra BibTeX/bibitem, field union và citation-key mapping theo version; góp phần bibliography cho notebook 07 qua PR riêng."],
    },
    "24120470_DuongPhanMinhTri": {
        "name": "Dương Phan Minh Trí", "branch": "review/24120470-storage-deduplication",
        "files": ["src/crawler/storage.py", "src/crawler/merge_shards.py", "src/crawler/records.py",
                  "src/crawler/drive_backup.py",
                  "src/crawler/generate_mock_data.py",
                  "src/parser/normalize.py", "src/parser/deduplicate.py", "src/parser/storage.py", "src/parser/validation.py",
                  "docs/04_schema_and_data_quality.ipynb", "docs/07_standardization_and_deduplication.ipynb",
                  "tasks/TASK_24120470_DuongPhanMinhTri.md"],
        "review": ["Đối chiếu khóa/version trước-sau merge; giữ riêng hai arXiv target khác nhau dù chung S2 ID.",
                   "Kiểm tra normalization bảo toàn math/text/cites, exact dedup và quan hệ parent theo version.",
                   "Đọc lại Parquet: schema, FK/cycles, empty/error và counts trước-sau; phối hợp Tân cho notebook 07."],
    },
    "24120474_TrinhVyTriet": {
        "name": "Trịnh Vỹ Triết", "branch": "review/24120474-runner-report",
        "files": ["src/crawler/main.py", "src/crawler/profiler.py", "src/crawler/observations.py", "src/crawler/reporting.py",
                  "src/crawler/readiness.py",
                  "src/parser/main.py", "src/parser/statistics.py", "tools/build_report.py", "colab_crawler.ipynb",
                  "docs/05_performance_benchmark.ipynb", "docs/08_parser_benchmark.ipynb",
                  "tasks/TASK_24120474_TrinhVyTriet.md"],
        "review": ["Kiểm tra resume theo version/reference, checkpoint atomic và export failure được ghi vào run.",
                   "Kiểm tra time-weighted RAM, child RSS, peak disk và mẫu số của từng run.",
                   "Chạy CLI/install/book từ saved inputs; chuẩn bị Colab benchmark sau khi có corpus, không báo smoke là benchmark toàn bộ."],
    },
    "00_SHARED_INTEGRATION": {
        "name": "Tích hợp chung — đề xuất Đạt điều phối, Triết chạy kiểm tra", "branch": "review/shared-integration",
        "files": [".github/workflows/ci.yml", ".gitignore", "README.md", "pyproject.toml", "requirements.txt",
                  "src/crawler/exceptions.py",
                  "tasks/HF_DATASET_AUDIT_2026-10-30.md", "tasks/IMPLEMENTATION_PROGRESS_2026-11-01.md",
                  "tasks/IMPLEMENTATION_PROGRESS_2026-11-02.md",
                  "tasks/IMPLEMENTATION_PROGRESS_2026-11-04.md",
                  "tasks/DOWNLOAD_SPEED_PROGRESS_2026-11-04.md",
                  "tasks/TEAM_HANDOFF_2026-11-02.md", "tools/prepare_handoff.py", "tools/prepare_colab_bundle.py"],
        "review": ["Đây là file liên quan nhiều module; thống nhất một người tích hợp, mọi chủ module review test của mình.",
                   "Không commit cả snapshot một lần để chia công lao. Giữ attribution trung thực cho thay đổi thực tế.",
                   "Chạy full tests, CLI và book sau khi các dependency đã tích hợp. Chưa có corpus đầy đủ/benchmark Colab/Pages/Moodle."],
    },
}
SOURCE_ROOTS = {"src", "docs", "tools", "tasks", ".github", "configs"}
ROOT_FILES = {"README.md", ".gitignore", "pyproject.toml", "requirements.txt", "colab_crawler.ipynb"}
SUFFIXES = {".py", ".ipynb", ".md", ".toml", ".txt", ".yml", ".yaml", ".json"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def names(data: bytes) -> set[str]:
    return {item.decode("utf-8") for item in data.split(b"\0") if item}


def eligible(name: str) -> bool:
    path = Path(name)
    return name in ROOT_FILES or (path.parts[0] in SOURCE_ROOTS and path.suffix in SUFFIXES
                                 and "__pycache__" not in path.parts)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(output: str) -> Path:
    target = Path(output).resolve()
    build = (ROOT / "build").resolve()
    if target == build or not target.is_relative_to(build):
        raise ValueError("Choose a new handoff directory inside build/")
    if target.exists():
        raise FileExistsError("Handoff already exists; choose another --output to preserve the previous snapshot")
    tracked = names(git("ls-files", "-z"))
    changed = names(git("diff", "--name-only", "-z", "HEAD"))
    untracked = names(git("ls-files", "--others", "--exclude-standard", "-z"))
    owners = {}
    for key, group in GROUPS.items():
        for name in group["files"]:
            if name in owners:
                raise ValueError("File assigned twice: " + name)
            if not (ROOT / name).is_file() or (ROOT / name).is_symlink():
                raise ValueError("Assigned file missing/is a link: " + name)
            owners[name] = key
    uncovered = {name for name in changed | untracked if eligible(name)} - owners.keys()
    if uncovered:
        raise ValueError("Assign these current source changes before handing off: " + str(sorted(uncovered)))
    snapshot_names = sorted({name for name in tracked | owners.keys() if eligible(name) and (ROOT / name).is_file()})
    contents = {}
    for name in snapshot_names:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Snapshot contains a link/outside path: " + name)
        contents[name] = path.read_bytes()
    base = git("rev-parse", "HEAD").decode().strip()
    target.mkdir(parents=True)
    handoff_date = datetime.now().astimezone().date()
    manifest = {"handoff_date": handoff_date.isoformat(), "base_commit": base,
                "purpose": "Review and actual follow-up work; assignments do not assert original authorship.",
                "source_hashes": {name: digest(data) for name, data in contents.items()},
                "excluded_changed_or_untracked": sorted((changed | untracked) - set(contents)), "groups": {}}
    with zipfile.ZipFile(target / "00_REFERENCE_SNAPSHOT.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    for key, group in GROUPS.items():
        directory = target / key
        directory.mkdir()
        file_info = {}
        for name in group["files"]:
            destination = directory / "after" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents[name])
            info = {"sha256_after": digest(contents[name]), "git_state": "tracked" if name in tracked else "untracked_before_handoff"}
            if name in tracked:
                before = git("show", base + ":" + name)
                destination = directory / "before" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(before)
                info["sha256_before"] = digest(before)
            file_info[name] = info
        introduction = (
            f"# Bàn giao rà soát — {group['name']}\n\n"
            f"Base commit: `{base}`. Nhánh đề xuất: `{group['branch']}`.\n\n"
            "`after/` chứa bản hiện tại; `before/` chứa bản tại base commit của file đã tracked.\n\n"
            "Dùng `00_REFERENCE_SNAPSHOT.zip` trong thư mục riêng để chạy đủ dependencies. "
            "Chỉ đưa phần đã rà soát vào clone Git; giữ nguyên các thay đổi local đang có.\n\n"
            "Giữ lịch sử cũ. PR ghi rõ công việc thực tế và phần được hỗ trợ; "
            "phân công review không xác định tác giả ban đầu.\n\n"
            "## Việc cần kiểm tra và làm tiếp\n\n" + "\n".join("- " + item for item in group["review"]) +
            "\n\n## File thuộc phạm vi bàn giao\n\n" + "\n".join("- `" + name + "`" for name in group["files"]) +
            "\n\nTheo thứ tự dependency và hướng dẫn Git trong `tasks/TEAM_HANDOFF_2026-11-02.md`. "
            "Sau khi tích hợp đủ modules, kiểm tra cài đặt, CLI và notebook.\n"
        )
        (directory / "README.md").write_text(introduction, encoding="utf-8")
        write_json(directory / "files.json", file_info)
        with zipfile.ZipFile(target / (key + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(directory).as_posix())
        manifest["groups"][key] = {"name": group["name"], "branch": group["branch"], "files": file_info}
    for name, data in contents.items():
        if (ROOT / name).read_bytes() != data:
            raise RuntimeError("Source changed while preparing handoff: " + name)
    for archive_path in sorted(target.glob("*.zip")):
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Broken ZIP: " + archive_path.name)
            if archive_path.name == "00_REFERENCE_SNAPSHOT.zip":
                assert set(archive.namelist()) == set(contents)
                for name, data in contents.items():
                    assert archive.read(name) == data, name
            else:
                for name, info in manifest["groups"][archive_path.stem]["files"].items():
                    assert digest(archive.read("after/" + name)) == info["sha256_after"]
                    if "sha256_before" in info:
                        assert digest(archive.read("before/" + name)) == info["sha256_before"]
    manifest["archive_hashes"] = {path.name: digest(path.read_bytes()) for path in sorted(target.glob("*.zip"))}
    write_json(target / "manifest.json", manifest)
    write_json(target / "verification.json", {"valid": True, "archives": len(manifest["archive_hashes"]),
               "source_files": len(contents), "assigned_files": len(owners), "duplicate_assignments": 0,
               "unassigned_source_changes": [], "git_history_changed": False})
    (target / "README.md").write_text(
        f"# Gói bàn giao nhóm — {handoff_date:%d/%m/%Y}\n\n"
        "Gửi mỗi thành viên ZIP theo MSSV, kèm `00_REFERENCE_SNAPSHOT.zip` và hướng dẫn "
        "`tasks/TEAM_HANDOFF_2026-11-02.md`. Người tích hợp giữ thêm `00_SHARED_INTEGRATION.zip`.\n\n"
        "Snapshot chứa code, notebook và tài liệu; dùng riêng để đối chiếu và chạy tests. "
        "Corpus, token, môi trường Python và `.git` được loại khỏi gói.\n\n"
        "Phân công review không xác định tác giả ban đầu. PR mô tả công việc thực tế.\n\n"
        f"Base commit `{base}`. `manifest.json` ghi SHA-256 và danh sách file; "
        "`verification.json` ghi kết quả kiểm tra ZIP/bản before-after.\n", encoding="utf-8")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/team_handoff_2026-11-02")
    print(prepare(parser.parse_args(argv).output))


if __name__ == "__main__":
    main()
