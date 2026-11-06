"""Package a frozen parser input and a Colab CPU benchmark notebook."""
from __future__ import annotations

import argparse
import hashlib
import inspect
from pathlib import Path
import zipfile

import nbformat

from tools.prepare_colab_bundle import allowed_path, build_bundle, install_bundle


def prepare(snapshot: Path, output: Path, notebook: Path):
    output.mkdir(parents=True, exist_ok=True)
    source = build_bundle(output/'arxiv_parser_runtime.zip')
    inputs = output/'arxiv_parser_input.zip'
    with zipfile.ZipFile(inputs,'w',zipfile.ZIP_DEFLATED) as archive:
        for folder in ('raw','m1','course'):
            for path in sorted((snapshot/folder).rglob('*')):
                if path.is_file() and not path.is_symlink():
                    archive.write(path,path.relative_to(snapshot).as_posix())
    input_hash=hashlib.sha256(inputs.read_bytes()).hexdigest()
    book=nbformat.v4.new_notebook()
    book.metadata.kernelspec={'display_name':'Python 3','language':'python','name':'python3'}
    book.cells=[
        nbformat.v4.new_markdown_cell('''# Benchmark parser M2 trên Colab CPU

Chọn Runtime → Change runtime type → CPU. Notebook dùng cùng snapshot Drive 73 paper/119 version với bản nộp 06/11, không gọi arXiv hoặc Semantic Scholar.

Tải lên hai file đi kèm: `arxiv_parser_runtime.zip` và `arxiv_parser_input.zip`. Chạy hết notebook để tải kết quả đo thật về máy. Kết quả này chỉ thuộc snapshot được nêu; không thay cho xử lý toàn dải.
'''),
        nbformat.v4.new_code_cell(f'''from pathlib import Path
import os, sys, json, hashlib, stat, tempfile, zipfile, subprocess
from google.colab import files

if Path('/dev/nvidia0').exists() or os.environ.get('COLAB_TPU_ADDR'):
    raise RuntimeError('Chọn runtime CPU rồi chạy lại.')
SOURCE_SHA256 = '{source['sha256']}'
INPUT_SHA256 = '{input_hash}'
uploaded = files.upload()
expected = {{'arxiv_parser_runtime.zip': SOURCE_SHA256, 'arxiv_parser_input.zip': INPUT_SHA256}}
for name, digest in expected.items():
    if name not in uploaded or hashlib.sha256(uploaded[name]).hexdigest() != digest:
        raise RuntimeError('File thiếu hoặc không đúng hash: ' + name)
    Path('/content', name).write_bytes(uploaded[name])
print('Hai gói đã khớp SHA-256.')
'''),
        nbformat.v4.new_code_cell(inspect.getsource(allowed_path)+'\n'+inspect.getsource(install_bundle)+'''
source_root, source_manifest = install_bundle('/content/arxiv_parser_runtime.zip', '/content/parser-source', SOURCE_SHA256)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-e', str(source_root)], check=True)
os.chdir(source_root)
root = Path('/content/parser-submission')
if root.exists():
    raise RuntimeError('Output đã có; dùng runtime mới để có lượt benchmark không dùng cache.')
root.mkdir()
with zipfile.ZipFile('/content/arxiv_parser_input.zip') as archive:
    members = archive.infolist()
    if len(members)>5000 or sum(m.file_size for m in members)>256*1024**2:
        raise RuntimeError('Gói input vượt kích thước dự kiến.')
    for member in members:
        target = root/member.filename
        if not target.resolve().is_relative_to(root.resolve()) or stat.S_ISLNK(member.external_attr>>16):
            raise RuntimeError('Đường dẫn input không hợp lệ.')
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
print('Input:', root)
'''),
        nbformat.v4.new_code_cell('''out = root/'parsed'
out.mkdir()
command = ['/usr/bin/time', '-v', '-o', str(out/'time_v.txt'), sys.executable, '-u', '-m', 'src.parser.main',
           '--publications', str(root/'m1/publications.parquet'), '--raw-dir', str(root/'raw'),
           '--output-dir', str(out), '--root-overrides', str(source_root/'configs/submission_parser_roots_20261106.json'),
           '--sample-interval-sec', '0.5', '--min-free-gb', '1']
(out/'run_configuration.json').write_text(json.dumps({'command':command,'source_sha256':SOURCE_SHA256,
    'input_sha256':INPUT_SHA256,'source_manifest':source_manifest,'scope':'73 papers / 119 versions'},indent=2))
with (out/'parser.log').open('w') as log:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in process.stdout:
        print(line, end=''); log.write(line); log.flush()
    code = process.wait()
if code:
    raise RuntimeError('Parser exit code: '+str(code))
'''),
        nbformat.v4.new_code_cell('''subprocess.run([sys.executable,'-m','src.parser.validation','--course-dir',str(root/'course'),
                '--parsed-dir',str(out),'--publications',str(root/'m1/publications.parquet'),
                '--output',str(out/'project_validation.json')],check=True)
stats=json.loads((out/'stats.json').read_text())
print('Môi trường:',stats['environment'])
print('Trạng thái:',stats['status_counts'])
print('Wall time:',stats['runtime_sec'],'giây')
import shutil
result=shutil.make_archive('/content/parser_colab_results','zip',root_dir=out)
files.download(result)
'''),
    ]
    nbformat.write(book,notebook)
    return {'runtime':source,'input_zip':str(inputs),'input_sha256':input_hash,'notebook':str(notebook)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--notebook',type=Path,default=Path('colab_parser_submission.ipynb'))
    print(prepare(**vars(parser.parse_args())))
