"""Prepare Jupyter Book sources and optionally build HTML."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare_book(output: str, m1_dir: str | None = None, m2_dir: str | None = None, build=False) -> Path:
    target = Path(output).resolve()
    if target == ROOT or target == ROOT.parent or target in ROOT.parents:
        raise ValueError("Book target must not replace the source repository/its ancestors")
    target.mkdir(parents=True, exist_ok=True)
    source = target / "chapters"
    source.mkdir(exist_ok=True)
    notebooks = sorted((ROOT / "docs").glob("*.ipynb"))
    for path in notebooks:
        shutil.copyfile(path, source / path.name)
    helper = target / "crawler"
    helper.mkdir(exist_ok=True)
    (helper / "__init__.py").write_text('"""Data reader for report notebooks."""\n', encoding="utf-8")
    shutil.copyfile(ROOT / "src/crawler/reporting.py", helper / "reporting.py")
    (target / "index.md").write_text("""# arXiv Harvester — Milestone 1 và 2

Báo cáo thực thi các bảng và biểu đồ từ dữ liệu, số đo đã lưu.
Mỗi chương ghi phạm vi đầu vào, coverage và trạng thái xử lý.

M1 dùng metadata; M2 cần thêm corpus TeX/Bib và có thể chỉ xử lý một tập con.
Kết quả thử local được ghi riêng với benchmark Colab CPU-only.

## Milestone 1

Discovery, sources, references, chất lượng dữ liệu và benchmark crawler.

## Milestone 2

Gathering/hierarchy, chuẩn hóa/dedup và benchmark parser trên cùng corpus.
""", encoding="utf-8")
    config = """title: arXiv Harvester — M1 và M2
author: Nhóm arXiv Harvester
execute:
  execute_notebooks: force
  allow_errors: false
  timeout: 600
html:
  use_repository_button: false
sphinx:
  config:
    language: vi
    exclude_patterns: [_build, '**.ipynb_checkpoints', .jupyter_cache, README.md]
    nb_execution_raise_on_error: true
"""
    (target / "_config.yml").write_text(config, encoding="utf-8")
    toc = "format: jb-book\nroot: index\nparts:\n"
    for caption, selected in (("Milestone 1 — Crawling", notebooks[:5]), ("Milestone 2 — Parsing", notebooks[5:])):
        toc += "  - caption: " + caption + "\n    chapters:\n"
        toc += "".join("      - file: chapters/" + path.stem + "\n" for path in selected)
    (target / "_toc.yml").write_text(toc, encoding="utf-8")
    (target / "requirements.txt").write_text("jupyter-book>=1,<2\npandas\npyarrow\nmatplotlib\nhuggingface_hub\n", encoding="utf-8")
    (target / ".gitignore").write_text("_build/\n.jupyter_cache/\n__pycache__/\ninputs/\n.ipynb_checkpoints/\n", encoding="utf-8")
    workflow = target / ".github/workflows"
    workflow.mkdir(parents=True, exist_ok=True)
    (workflow / "pages.yml").write_text("""name: Build and deploy book
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  pages:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements.txt
      - name: Fetch pinned real report inputs
        env:
          HF_DATASET_ID: ${{ vars.HF_DATASET_ID }}
          HF_DATASET_REVISION: ${{ vars.HF_DATASET_REVISION }}
          M1_INPUT_PREFIX: ${{ vars.M1_INPUT_PREFIX }}
          M2_INPUT_PREFIX: ${{ vars.M2_INPUT_PREFIX }}
          HF_TOKEN: ${{ secrets.HF_READ_TOKEN }}
        run: python fetch_inputs.py
      - name: Build executed book
        env:
          PYTHONPATH: .
          ARXIV_M1_DATA_DIR: inputs/m1
          ARXIV_M2_DATA_DIR: inputs/m2
        run: jupyter-book build . --all -W
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v4
        with:
          path: _build/html
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4
""", encoding="utf-8")
    (target / "fetch_inputs.py").write_text('''import os
from pathlib import Path
import shutil
from huggingface_hub import snapshot_download
repo = os.environ.get("HF_DATASET_ID")
revision = os.environ.get("HF_DATASET_REVISION")
if not repo or not revision or len(revision) != 40:
    raise RuntimeError("Set HF_DATASET_ID and pinned full HF_DATASET_REVISION repository variables")
for stage, variable in (("m1", "M1_INPUT_PREFIX"), ("m2", "M2_INPUT_PREFIX")):
    prefix = os.environ.get(variable, "").strip("/")
    if not prefix or ".." in Path(prefix).parts:
        raise RuntimeError("Set a safe dataset input prefix: " + variable)
    snapshot = Path(snapshot_download(repo_id=repo, repo_type="dataset", revision=revision,
                                     allow_patterns=[prefix + "/*"], token=os.environ.get("HF_TOKEN") or False))
    source = snapshot / prefix
    if not source.exists():
        raise RuntimeError("Dataset does not contain " + prefix)
    shutil.copytree(source, Path("inputs") / stage, dirs_exist_ok=True)
''', encoding="utf-8")
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    import hashlib
    source_files = [*notebooks, *sorted((ROOT / "src").rglob("*.py")), *sorted((ROOT / "configs").glob("*")),
                    ROOT / "pyproject.toml", Path(__file__).resolve()]
    manifest = {"source_base_commit": commit, "source_files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source_files if p.is_file()}, "m1_input": m1_dir, "m2_input": m2_dir,
                "note": "Source hashes include local changes beyond the base commit."}
    input_paths = []
    if m1_dir:
        data = Path(m1_dir).resolve()
        input_paths.extend(p for name in ("publications.parquet", "references.parquet", "crawl_status.parquet", "stats.json", "overall_stats.json") if (p := data / name).exists())
        input_paths.extend((data / "runs").glob("*/stats.json"))
    if m2_dir:
        data = Path(m2_dir).resolve()
        input_paths.extend(p for name in ("manifest.json", "stats.json", "project_validation.json") if (p := data / name).exists())
        input_paths.extend(sorted((data / "working").glob("*.json"))[:2])
        input_paths.extend((data / "runs").glob("*/stats.json"))
    manifest["input_hashes"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in input_paths}
    (target / "report_build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "README.md").write_text("""# Jupyter Book M1–M2

Source cho repo báo cáo riêng. Dữ liệu đầu vào được lưu ngoài repo.

Cài `python -m pip install -r requirements.txt`, đặt `ARXIV_M1_DATA_DIR` và
`ARXIV_M2_DATA_DIR` tới inputs thật, rồi chạy `jupyter-book build . --all`.
Build thực thi lại notebook, dừng khi thiếu input hoặc gặp dữ liệu mock.

Để deploy trên repo báo cáo, bật Pages → GitHub Actions và đặt repository
variables `HF_DATASET_ID`, `HF_DATASET_REVISION` (full commit SHA),
`M1_INPUT_PREFIX`, `M2_INPUT_PREFIX` tới outputs thật đã xuất bản. Dataset
private dùng secret `HF_READ_TOKEN`. Workflow không tự tạo dữ liệu hoặc crawl.

Kiểm tra source/input hashes trong `report_build_manifest.json` trước khi deploy.
""", encoding="utf-8")
    if build:
        if not m1_dir or not m2_dir:
            raise ValueError("--build needs both --m1-dir and --m2-dir")
        env = os.environ.copy()
        env.update(ARXIV_M1_DATA_DIR=str(Path(m1_dir).resolve()), ARXIV_M2_DATA_DIR=str(Path(m2_dir).resolve()))
        env["PYTHONPATH"] = str(target) + os.pathsep + env.get("PYTHONPATH", "")
        local_executable = Path(sys.executable).with_name("jupyter-book.exe" if os.name == "nt" else "jupyter-book")
        executable = str(local_executable) if local_executable.exists() else shutil.which("jupyter-book")
        if not executable:
            raise RuntimeError("Install report dependencies: python -m pip install -e '.[report]'")
        subprocess.run([executable, "build", str(target), "--all", "-W"], env=env, check=True)
        changed = [str(p) for p in input_paths if hashlib.sha256(p.read_bytes()).hexdigest() != manifest["input_hashes"][str(p)]]
        if changed:
            raise RuntimeError("Report inputs changed during build; rebuild with frozen inputs: " + str(changed))
        changed_source = [name for name, digest in manifest["source_files"].items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
        if changed_source:
            raise RuntimeError("Report source changed during build: " + str(changed_source))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/book_source")
    parser.add_argument("--m1-dir")
    parser.add_argument("--m2-dir")
    parser.add_argument("--build", action="store_true")
    print(prepare_book(**vars(parser.parse_args(argv))))


if __name__ == "__main__":
    main()
