"""Package a verified source snapshot for Colab."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def allowed_path(name: str) -> bool:
    path = Path(name)
    return (path.as_posix() == name and not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name
            and (name in {"pyproject.toml", "requirements.txt", "README.md", "LICENSE"}
                 or (name.startswith("src/") and name.endswith(".py"))
                 or (name.startswith("configs/") and path.suffix in {".json", ".md"})))


def build_bundle(output: str | Path) -> dict:
    files = [p for p in (ROOT / "src").rglob("*.py") if "__pycache__" not in p.parts]
    files += [p for p in (ROOT / "configs").glob("*") if p.is_file()]
    files += [ROOT / name for name in ("pyproject.toml", "requirements.txt", "README.md", "LICENSE") if (ROOT / name).is_file()]
    contents = {}
    for path in files:
        name = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or not allowed_path(name):
            raise ValueError("Unsupported source path: " + name)
        contents[name] = path.read_bytes()
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {"format_version": 1, "runtime_protocol": 1, "source_base_commit": base,
                "includes_local_changes": True,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}}
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            archive.writestr(name, data)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "files": len(contents), "bytes": target.stat().st_size, "source_base_commit": base}


def install_bundle(archive_path: str | Path, target_root: str | Path, expected_sha256: str) -> tuple[Path, dict]:
    archive_path, target_root = Path(archive_path), Path(target_root).resolve()
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if not expected_sha256 or digest != expected_sha256:
        raise ValueError("Gói source không đúng SHA-256 của notebook")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [row.filename for row in entries]
        if len(names) != len(set(names)) or len(names) > 150 or sum(row.file_size for row in entries) > 8 * 1024**2:
            raise ValueError("Gói source có cấu trúc hoặc dung lượng không hợp lệ")
        manifest = json.loads(archive.read("bundle_manifest.json"))
        if manifest.get("format_version") != 1 or manifest.get("runtime_protocol") != 1:
            raise ValueError("Gói source khác phiên bản runtime")
        if set(names) != set(manifest["files"]) | {"bundle_manifest.json"}:
            raise ValueError("Danh sách file không khớp manifest")
        for row in entries:
            if row.filename != "bundle_manifest.json" and not allowed_path(row.filename):
                raise ValueError("File không thuộc source allowlist")
            if stat.S_ISLNK(row.external_attr >> 16) or row.flag_bits & 1:
                raise ValueError("Gói source chứa symlink hoặc file mã hóa")
        contents = {name: archive.read(name) for name in names}
        for name, expected in manifest["files"].items():
            if hashlib.sha256(contents[name]).hexdigest() != expected:
                raise ValueError("Hash file không khớp: " + name)
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / digest[:16]
    if destination.exists():
        if destination.is_symlink() or not destination.resolve().is_relative_to(target_root):
            raise ValueError("Runtime source path is a symlink or outside the target root")
        expected_python = {name for name in manifest["files"] if name.startswith("src/") and name.endswith(".py")}
        actual_python = {p.relative_to(destination).as_posix() for p in (destination / "src").rglob("*.py")}
        if actual_python != expected_python:
            raise ValueError("Runtime source contains unexpected Python files")
        if any(not (destination / name).is_file() or (destination / name).is_symlink()
               or hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected
               for name, expected in manifest["files"].items()):
            raise ValueError("Source đã cài có thay đổi; chọn thư mục source mới")
    else:
        with tempfile.TemporaryDirectory(prefix=".source-", dir=target_root) as temporary:
            staging = Path(temporary).resolve()
            if not staging.is_relative_to(target_root) or not destination.resolve().is_relative_to(target_root):
                raise ValueError("Source destination escapes runtime root")
            unpacked = staging / "runtime"
            for name, data in contents.items():
                target = unpacked / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            unpacked.rename(destination)
    return destination, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/colab_fix_20261103/arxiv_colab_runtime.zip")
    parser.add_argument("--notebook", default="colab_crawler.ipynb")
    args = parser.parse_args()
    report = build_bundle(args.output)
    notebook_path = Path(args.notebook)
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    matches = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        source, count = re.subn(r'^EXPECTED_BUNDLE_SHA256 = "[^"]*"',
                               'EXPECTED_BUNDLE_SHA256 = "' + report["sha256"] + '"',
                               "".join(cell["source"]), flags=re.M)
        matches += count
        cell["source"] = source.splitlines(keepends=True)
    if matches != 1:
        raise ValueError("Notebook must contain one EXPECTED_BUNDLE_SHA256 setting")
    notebook_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    report["notebook"] = str(notebook_path)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
