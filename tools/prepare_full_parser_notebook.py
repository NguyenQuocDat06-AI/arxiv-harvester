"""Generate colab_parser_full.ipynb for CPU-only M2 pilot/full/resume runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import nbformat

ROOT = Path(__file__).resolve().parents[1]


def build_notebook(output: Path, bundle_sha256: str) -> Path:
    runner_src = (ROOT / "tools/m2_colab_runner.py").read_text(encoding="utf-8")
    nb = nbformat.v4.new_notebook()
    nb.metadata.kernelspec = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.cells = [
        nbformat.v4.new_markdown_cell(
            """# Parser Milestone 2 (Colab CPU-only: Full / Pilot / Resume)

Notebook chạy parser M2 trên corpus M1 đã khôi phục từ backup Google Drive, không gọi crawler arXiv hay Semantic Scholar.
Chọn **Runtime -> Change runtime type -> CPU** trước khi chạy. Nếu có sẵn file `/content/m2_run_config.json` trong workspace, notebook tự đọc tham số từ file đó; nếu chạy trực tiếp trên giao diện Colab thì chỉnh các giá trị trong ô cấu hình bên dưới.
"""
        ),
        nbformat.v4.new_code_cell(
            f"""import json, os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get('M2_RUN_CONFIG', '/content/m2_run_config.json'))
if not CONFIG_PATH.is_file():
    DEFAULT_CONFIG = {{
        'member_id': '24120282',
        'short_name': 'DAT',
        'generation': '8bc30379e093456896d3f1d659e9b8ff',
        'head_sha256': '',
        'mode': 'full',  # 'pilot' | 'full' | 'resume'
        'pilot_size': 250,
        'pilot_seed': 20261121,
        'bundle_path': '/content/arxiv_m2_runtime.zip',
        'bundle_sha256': '{bundle_sha256}',
        'drive_backup_dir': '/content/drive/MyDrive/arxiv-harvester-data/team_full_20261115/backups/24120282',
        'chain_manifest_path': '/content/m2_chain.json',
        'drive_output_root': '/content/drive/MyDrive/arxiv-harvester-m2',
        'root_overrides_rel': 'configs/parser_roots.json',
        'sample_interval_sec': 0.5,
        'min_free_gb': 2.0,
        'sync_batch_interval_sec': 120.0,
        'fresh_output': True,
    }}
    CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')

cfg = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
print('Loaded config:', json.dumps({{k: v for k, v in cfg.items() if 'token' not in k}}, ensure_ascii=False, indent=2))
"""
        ),
        nbformat.v4.new_code_cell(
            """from pathlib import Path
import os

if Path('/dev/nvidia0').exists() or os.environ.get('COLAB_TPU_ADDR'):
    raise RuntimeError('M2 yêu cầu runtime CPU-only; hãy đổi Runtime -> CPU rồi chạy lại.')

if not Path('/content/drive/MyDrive').exists():
    from google.colab import drive
    drive.mount('/content/drive')
print('Drive ready:', Path('/content/drive/MyDrive').exists())
"""
        ),
        nbformat.v4.new_code_cell(
            f"""import os, subprocess, sys
from pathlib import Path

runner_path = Path('/content/m2_colab_runner.py')
if not runner_path.is_file():
    runner_path.write_text({runner_src!r}, encoding='utf-8')
subprocess.run([sys.executable, '-u', str(runner_path)], check=True)
"""
        ),
        nbformat.v4.new_code_cell(
            """import json, os
from pathlib import Path

cfg = json.loads(Path(os.environ.get('M2_RUN_CONFIG', '/content/m2_run_config.json')).read_text(encoding='utf-8'))
work = Path(f"/content/m2_work/{cfg['member_id']}/{cfg['generation']}")
out = work / ('parsed_pilot' if cfg['mode'] == 'pilot' else 'parsed_full')
for name in ('runner_summary.json', 'project_validation.json'):
    p = out / name
    if p.is_file():
        print('===', name, '===')
        print(p.read_text(encoding='utf-8')[:4000])
"""
        ),
    ]
    nbformat.write(nb, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "colab_parser_full.ipynb")
    parser.add_argument("--bundle-sha256", default="")
    args = parser.parse_args()
    path = build_notebook(args.output, args.bundle_sha256)
    print("WROTE:", path)


if __name__ == "__main__":
    main()
