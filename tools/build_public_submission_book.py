"""Build a public Book using numeric aggregates and anonymous coverage labels."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

import nbformat
import pyarrow.parquet as pq


def environment(data):
    return {key:data.get(key) for key in ('platform','python_version','is_google_colab','cpu_only',
                                        'cpu_count_logical','total_memory_mb','library_versions')}


def measurements(data, child_wall=None):
    return {'status':data.get('status'),'runtime_sec':data.get('runtime_sec'),'child_wall_sec':child_wall,
            'processed_papers':data.get('processed_this_run',data.get('results',{}).get('processed_this_run')),
            'environment':environment(data.get('environment',{})),
            'memory':{key:data.get('memory',{}).get(key) for key in ('peak_rss_mb','avg_rss_mb','num_samples','sample_interval_sec')},
            'disk':{key:data.get('disk',{}).get(key) for key in ('peak_bytes','final_bytes','method','sample_interval_sec')},
            'phases':data.get('phases',{})}


def resource_profile(parsed: Path, stats: dict, window_sec=5.0):
    """Aggregate numeric resource samples; omit run IDs and filesystem paths."""
    run_id = stats.get('run_id')
    samples = parsed / 'runs' / str(run_id) / 'resource_samples.jsonl'
    if not run_id or not samples.is_file():
        return None
    windows = {}
    counts = Counter()
    with samples.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            kind = row.get('kind')
            if kind not in {'rss', 'disk'}:
                continue
            elapsed = float(row['elapsed_sec'])
            if elapsed < 0 or elapsed > stats['runtime_sec'] + 1:
                raise ValueError('Resource sample lies outside the measured run')
            bucket = windows.setdefault(int(elapsed // window_sec), {'rss': [], 'disk': []})
            bucket[kind].append(int(row['rss_bytes' if kind == 'rss' else 'total_bytes']))
            counts[kind] += 1
    rows = []
    for index, bucket in sorted(windows.items()):
        rss, disk = bucket['rss'], bucket['disk']
        rows.append({
            'window_start_sec': index * window_sec,
            'window_end_sec': min((index + 1) * window_sec, stats['runtime_sec']),
            'rss_sample_mean_mib': sum(rss) / len(rss) / 1024**2 if rss else None,
            'rss_peak_mib': max(rss) / 1024**2 if rss else None,
            'disk_peak_bytes': max(disk) if disk else None,
        })
    return {'window_sec': window_sec, 'rss_samples': counts['rss'],
            'disk_samples': counts['disk'], 'rows': rows}


def aggregate(snapshot: Path, parsed: Path, colab_run: Path):
    scope=json.loads((snapshot/'snapshot.json').read_text(encoding='utf-8'))
    stat=json.loads((parsed/'stats.json').read_text(encoding='utf-8'))
    quality=json.loads((parsed/'project_validation.json').read_text(encoding='utf-8'))
    papers=pq.read_table(snapshot/'m1/publications.parquet').to_pylist()
    refs=pq.read_table(snapshot/'m1/references.parquet').to_pylist()
    observations=pq.read_table(snapshot/'m1/crawl_status.parquet').to_pylist()
    audit=pq.read_table(snapshot/'source_audit.parquet').to_pylist()
    versions=[{'arxiv_id':p['id'],**v} for p in papers for v in p['versions']]
    verified={(a['arxiv_id'],a['version']):a['verified'] for a in audit}
    eligible=[p for p in papers if p['versions'] and all(v['source_status']=='success' and verified.get((p['id'],v['version'])) for v in p['versions'])]
    sizes={key:[sum(v.get(key) or 0 for v in p['versions']) for p in eligible] for key in ('size_before_bytes','size_after_bytes')}
    complete_refs={o['arxiv_id'] for o in observations if o['reference_status'] in {'success','empty'}}
    reference_counts=Counter(r['arxiv_id'] for r in refs)
    source_summaries=Counter(a['reason'] for a in audit)
    metadata_missing={key:sum(p.get(key) in (None,'',[]) for p in papers)/len(papers) for key in ('title','authors','published','doi','venue')}
    ref_missing={key:sum(r.get(key) in (None,'',[]) for r in refs)/len(refs) if refs else None for key in ('ref_arxiv_id','ref_title','ref_authors','ref_submission_date','ref_s2_id')}
    run=json.loads((colab_run/'stats.json').read_text(encoding='utf-8'))
    meta=json.loads((colab_run/'run_metadata.json').read_text(encoding='utf-8'))
    crawl=measurements(run,meta.get('child_wall_sec') if meta.get('run_id')==run.get('run_id') else None)
    crawl['assigned_ids']=run.get('results',{}).get('total_ids')
    crawl['intervals']={key:run.get('run_args',{}).get(key) for key in ('rate_limit_sec','source_rate_limit_sec','s2_rate_limit_sec')}
    coverage=[]
    mapping={}
    for index,row in enumerate(sorted(stat['publication_coverage'],key=lambda x:x['arxiv_id']),1):
        alias=f'P{index:03d}'; mapping[alias]=row['arxiv_id']
        coverage.append({'paper':alias,**{k:v for k,v in row.items() if k!='arxiv_id'}})
    diagnostics=Counter()
    manifest=json.loads((parsed/'manifest.json').read_text(encoding='utf-8'))
    for row in manifest:
        categories=set()
        for msg in row.get('diagnostics',[]):
            if 'bibliograph' in msg: categories.add('Bibliography thiếu hoặc không đọc được')
            elif 'missing include' in msg: categories.add('Include không có trong corpus')
            elif 'compilation root' in msg: categories.add('Compilation root mơ hồ')
            elif 'include' in msg: categories.add('Include chưa hỗ trợ')
            elif 'item' in msg or 'environment' in msg: categories.add('Môi trường TeX chưa hỗ trợ đầy đủ')
            else: categories.add('Diagnostic khác')
        if row.get('unresolved_cites'): categories.add('Citation chưa resolve')
        if row['status']=='error_missing_source': categories.add('Thiếu source')
        diagnostics.update(categories)
    schemas={}
    for name in ('papers','references'):
        schema=pq.ParquetFile(snapshot/'course'/f'{name}.parquet').schema_arrow
        schemas[name]=[{'column':f.name,'type':str(f.type),'nullable':f.nullable} for f in schema]
    complete_sources={p['id'] for p in papers if p['versions'] and all(verified.get((p['id'],v['version']),False) for v in p['versions'])}
    summary={'report_date':'2026-11-06','scope':{'papers':len(papers),'versions':len(versions),'group_assigned':25000,
              'member_assigned':5000,'checkpoint_reported_ids':scope['latest_checkpoint_ids'],
              'archives_used':len(scope['archives']),'selection':'Các lô mới nhất dưới 8 MiB; không chọn theo parser success và không khôi phục toàn chuỗi.'},
              'm1':{'version_histogram':dict(Counter(len(p['versions']) for p in papers)),
                    'version_status':dict(Counter(v['source_status'] for v in versions)),
                    'source_audit':dict(source_summaries),'source_verified':sum(a['verified'] for a in audit),
                    'metadata_missing_fraction':metadata_missing,'references_missing_fraction':ref_missing,
                    'reference_status':dict(Counter(o['reference_status'] for o in observations)),
                    'working_reference_rows':len(refs),'arxiv_reference_rows':quality['m1']['references'],
                    'verified_reference_papers':len(complete_refs),
                    'mean_references_verified_papers':sum(reference_counts[k] for k in complete_refs)/len(complete_refs) if complete_refs else None,
                    'eligible_size_papers':len(eligible),
                    'mean_before_bytes':sum(sizes['size_before_bytes'])/len(eligible) if eligible else None,
                    'mean_after_bytes':sum(sizes['size_after_bytes'])/len(eligible) if eligible else None,
                    'source_reduction':1-sum(sizes['size_after_bytes'])/sum(sizes['size_before_bytes']) if sum(sizes['size_before_bytes']) else None,
                    'papers_with_all_sources_verified':len(complete_sources),
                    'papers_with_sources_and_s2_verified':len(complete_sources & complete_refs),
                    'missing_version_dates':sum(v.get('created') is None for v in versions),
                    'schemas':schemas},
              'm2':{'status_counts':stat['status_counts'],'deduplication':stat['deduplication'],
                    'unresolved_cites':stat['unresolved_cites'],'bibliography_conflicts':stat['bibliography_conflicts'],
                    'coverage':coverage,'diagnostic_categories':dict(diagnostics),'rows':quality['m2']['rows'],
                    'versions_with_tex':stat.get('versions_with_tex'),
                    'versions_with_unmeasured_counts':stat.get('versions_with_unmeasured_counts'),
                    'structural_valid':quality['structural_valid'],'processing_complete':quality['processing_complete']},
              'crawler_measurement':crawl,'parser_measurement':{**measurements(stat),'final_output_bytes':stat['final_output_bytes'],
                    'avg_sec_per_publication':stat['avg_sec_per_processed_publication'],
                    'resource_profile':resource_profile(parsed,stat)}}
    baseline=parsed.parent/'parsed/stats.json'
    if baseline.exists() and baseline.resolve()!=(parsed/'stats.json').resolve():
        old=json.loads(baseline.read_text(encoding='utf-8'))
        if old.get('publications_input')==stat.get('publications_input') and old.get('versions')==stat.get('versions'):
            summary['m2']['before_fixes_status']=old.get('status_counts',{})
    return summary,mapping


def notebook(title, prose, code, stage):
    common="""from pathlib import Path
import json
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display
data=json.loads((Path.cwd().parent/'report_summary.json').read_text(encoding='utf-8'))
print('Phạm vi báo cáo:',data['scope']['papers'],'paper;',data['scope']['versions'],'version')
"""
    book=nbformat.v4.new_notebook()
    book.metadata.kernelspec={'display_name':'Python 3','language':'python','name':'python3'}
    book.cells=[nbformat.v4.new_markdown_cell('# '+title+'\n\n'+prose),
                nbformat.v4.new_code_cell(common),nbformat.v4.new_code_cell(code),
                nbformat.v4.new_markdown_cell('## Tài liệu tham khảo\n\n'
                    f'- [Yêu cầu {stage}](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/{"crawling" if stage=="M1" else "parsing"}/).\n'
                    '- [Source code của nhóm](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/develop).\n'
                    '- [arXiv API](https://info.arxiv.org/help/api/user-manual.html).\n'
                    '- [Semantic Scholar](https://api.semanticscholar.org/api-docs/graph).')]
    return book


CHAPTERS=[
('01_discovery_and_versions','Discovery và version coverage',
 'Atom API phân giải ID được giao và suffix revision; version được tải riêng. Ngày chưa xác minh giữ null. Snapshot gồm một số lô Drive đã kiểm tra, không phải mẫu ngẫu nhiên và chưa phải toàn bộ dải. Counter checkpoint được ghi riêng với dữ liệu thực sự audit.',
 """scope=data['scope']
display(pd.DataFrame([{'scope':'Snapshot trong báo cáo','papers':scope['papers']},
 {'scope':'Dải cá nhân','papers':scope['member_assigned']},{'scope':'Toàn nhóm','papers':scope['group_assigned']},
 {'scope':'Counter checkpoint, chưa restore toàn chuỗi','papers':scope['checkpoint_reported_ids']}]))
print(f"Snapshot phủ {scope['papers']/scope['group_assigned']:.2%} số paper của nhóm.")
print(scope['selection'])
hist=pd.Series(data['m1']['version_histogram'],name='papers'); display(hist.to_frame())
hist.plot.bar(xlabel='Số version/paper',ylabel='Số paper',title='Phân bố version trong snapshot')
plt.tight_layout(); plt.show()
display(pd.Series(data['m1']['metadata_missing_fraction'],name='missing_fraction').to_frame())
"""),
('02_source_download_and_cleaning','Tải nguồn và audit',
 'Downloader giữ `.tex/.bib`, không sửa lệnh figure trong TeX. Audit kiểm tra file và size; PDF-only/no-LaTeX cần manifest. Size trước lọc là byte nội dung giải nén, không phải archive nén. Hai trung bình size được tính trên cùng tập paper có mọi version TeX đã xác minh.',
 """audit=pd.Series(data['m1']['source_audit'],name='versions'); display(audit.to_frame())
audit.plot.bar(title='Audit nguồn theo version',ylabel='Số version'); plt.tight_layout(); plt.show()
print('Version xác minh:',data['m1']['source_verified'],'/',data['scope']['versions'])
display(pd.DataFrame([{'eligible_papers':data['m1']['eligible_size_papers'],
 'mean_before_bytes':data['m1']['mean_before_bytes'],'mean_after_bytes':data['m1']['mean_after_bytes'],
 'reduction_fraction':data['m1']['source_reduction']}]))
print('Version lỗi nguồn còn được giữ trong manifest; không tính là empty hợp lệ.')
"""),
('03_reference_extraction','References và độ phủ metadata',
 'S2 batch được đối chiếu theo paper ID và referenceCount; kết quả thiếu được lấy thêm trang. Khi 429, checkpoint và cooldown được giữ. Working references chứa cạnh đã thu được, course export chỉ giữ đích có arXiv ID. API error và dữ liệu không có trong các lô được chọn không có nghĩa paper không trích dẫn gì.',
 """m=data['m1']; status=pd.Series(m['reference_status'],name='papers'); display(status.to_frame())
status.plot.bar(title='Trạng thái truy vấn references',ylabel='Số paper'); plt.tight_layout(); plt.show()
print('Paper có S2 success/empty:',m['verified_reference_papers'],'/',data['scope']['papers'])
print('Tỷ lệ có kết quả S2 đã xác minh:',m['verified_reference_papers']/data['scope']['papers'])
print('References trung bình trên paper đã xác minh S2:',m['mean_references_verified_papers'])
print('Working reference rows:',m['working_reference_rows'],'; course arXiv edges:',m['arxiv_reference_rows'])
display(pd.Series(m['references_missing_fraction'],name='missing_fraction').to_frame())
print('Không gán 0 reference cho các paper API error hoặc thiếu lịch sử backup.')
"""),
('04_schema_and_data_quality','Schema và validation năm bảng',
 'M1 xuất papers/references; M2 xuất elements/hierarchy/bibtex. Validation kiểm tra kiểu dữ liệu, khóa và quan hệ parent theo version. Cấu trúc hợp lệ và xử lý hoàn tất là hai kết quả được đánh giá riêng.',
 """for name,rows in data['m1']['schemas'].items():
 print(name); display(pd.DataFrame(rows))
display(pd.DataFrame([{'table':'papers','rows':data['scope']['papers']},
 {'table':'references','rows':data['m1']['arxiv_reference_rows']},
 *[{'table':k,'rows':v} for k,v in data['m2']['rows'].items()]]))
print('Structural valid:',data['m2']['structural_valid'])
print('Processing complete:',data['m2']['processing_complete'])
print('Validation này chỉ đối chiếu snapshot 73 paper, không xác nhận đủ toàn nhóm.')
"""),
('05_performance_benchmark','Số đo crawler đã lưu',
 'Số đo dưới đây lấy từ một lượt Colab CPU-only đã lưu, có phạm vi khác snapshot của báo cáo và đã tạm dừng do rate limit. Đây là số đo của khoảng thực sự chạy, chưa phải benchmark hoàn tất toàn dải. Thời gian khôi phục dữ liệu trên Windows không được tính thành crawling Colab.',
 """run=data['crawler_measurement']
display(pd.DataFrame([{k:run[k] for k in ['status','runtime_sec','child_wall_sec','processed_papers','assigned_ids']}]))
display(pd.Series(run['environment'],name='value').to_frame())
display(pd.DataFrame(run['phases']).T)
display(pd.Series(run['memory'],name='RAM').to_frame()); display(pd.Series(run['disk'],name='disk').to_frame())
print('Cấu hình đã ghi:',run['intervals'])
if run['processed_papers']:
 print('Profiler seconds / paper thực sự xử lý:',run['runtime_sec']/run['processed_papers'])
pd.Series({k:v['elapsed_sec'] for k,v in run['phases'].items()}).plot.bar(title='Thời gian pha của lượt đã lưu',ylabel='Giây')
plt.tight_layout(); plt.show()
print('Profiler time và child wall khác phạm vi; không sửa log để đổi cấu hình hoặc giả lượt đã hoàn tất.')
"""),
('06_parsing_and_hierarchy','Gathering và hierarchy theo version',
 'Parser tìm root có documentclass, duyệt include từ thư mục biên dịch và lưu source map. Paragraph/sentence được chia ngoài nhóm TeX và toán. Các node list, figure/table, acknowledgements và appendix được giữ, bibliography tách khỏi hierarchy. Root mơ hồ được cấu hình khi có bằng chứng; ca chưa chọn được vẫn là lỗi. Mã P001… chỉ là nhãn coverage, không công bố ID hoặc nội dung source.',
 """m=data['m2']; display(pd.Series(m['status_counts'],name='versions').to_frame())
pd.Series(m['status_counts']).plot.bar(title='Kết quả parser theo version',ylabel='Số version'); plt.tight_layout(); plt.show()
with pd.option_context('display.max_rows',None,'display.max_columns',None):
 display(pd.DataFrame(m['coverage']))
display(pd.Series(m['diagnostic_categories'],name='versions_with_diagnostic').to_frame())
print('Mỗi version trong snapshot đều có manifest, kể cả empty và lỗi; recorded coverage không đồng nghĩa success.')
"""),
('07_standardization_and_deduplication','Chuẩn hóa và khử trùng',
 'Chuẩn hóa bỏ wrapper trình bày, thống nhất toán và citation keys. Nội dung giống hệt sau cleanup dùng chung element, quan hệ parent vẫn phân biệt theo version. Reference trùng được hợp nhất trường và ghi xung đột. Missing bibliography và unresolved citation được giữ rõ trong kết quả.',
 """m=data['m2']; frame=pd.DataFrame(m['deduplication']).T; display(frame)
frame[['before','after']].plot.bar(title='Số phần tử trước và sau dedup'); plt.tight_layout(); plt.show()
print('Citation chưa resolve:',m['unresolved_cites'])
print('Bibliography field conflicts:',m['bibliography_conflicts'])
print('Dedup được đo sau chuẩn hóa; việc giảm số dòng không chứng minh các version partial đã xử lý trọn vẹn.')
"""),
('08_parser_benchmark','Thời gian và tài nguyên parser',
 'Lượt mới của snapshot được đo trên Windows CPU, gồm parse và validation. Benchmark M2 cuối trên Colab CPU-only chưa có. Notebook Colab đi kèm source cho phép chạy lại cùng tập input mà không gọi arXiv hoặc S2; kết quả mới cần được thu trước khi thay số đo local.',
 """run=data['parser_measurement']; display(pd.Series(run['environment'],name='value').to_frame())
display(pd.DataFrame([{k:run[k] for k in ['runtime_sec','processed_papers','avg_sec_per_publication','final_output_bytes']}]))
display(pd.Series(run['memory'],name='RAM').to_frame()); display(pd.Series(run['disk'],name='disk').to_frame())
display(pd.DataFrame(run['phases']).T)
print('Các bước gathering/normalization/dedup nằm trong parse_publication; không suy đoán thời gian tách riêng.')
pd.Series({k:v['elapsed_sec'] for k,v in run['phases'].items()}).plot.bar(title='Pha parser đo trên Windows CPU',ylabel='Giây')
plt.tight_layout(); plt.show()
print('CHƯA CÓ benchmark M2 Colab CPU-only cho snapshot này.')
"""),
]


def prepare(snapshot: Path, parsed: Path, colab_run: Path, output: Path, build=False):
    if output.exists(): raise FileExistsError(output)
    summary,mapping=aggregate(snapshot,parsed,colab_run)
    output.mkdir(parents=True)
    (output/'chapters').mkdir()
    (output/'report_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    # The crosswalk stays outside the public repository.
    (output.parent/'private_paper_mapping.json').write_text(json.dumps(mapping,indent=2),encoding='utf-8')
    for name,title,prose,code in CHAPTERS:
        nbformat.write(notebook(title,prose,code,'M1' if int(name[:2])<=5 else 'M2'),output/'chapters'/f'{name}.ipynb')
    (output/'index.md').write_text(f'''# arXiv Harvester — Milestone 1 và 2

**Bản nộp tiến độ ngày 06/11/2026.** Báo cáo dùng thống kê tổng hợp của snapshot Drive gồm **73 paper, 119 version**. Đây là phần dữ liệu hiện có, chưa phải toàn bộ 25.000 paper được giao cho nhóm.

| Nội dung | Kết quả |
|---|---:|
| Version nguồn được audit xác minh | {summary['m1']['source_verified']}/119 |
| Version có bản ghi parser | 119/119 |
| Version parse success | {summary['m2']['status_counts'].get('success',0)} |
| Cấu trúc năm bảng | Hợp lệ trên snapshot |
| Xử lý hoàn tất snapshot | Chưa đạt, xem partial/error trong M2 |

M1 còn references lỗi API và một version nguồn lỗi. M2 còn partial và root chưa xác minh. Số đo M1 từ lượt Colab đã lưu có phạm vi riêng; số đo M2 mới ở Windows CPU, chưa có benchmark M2 cuối trên Colab CPU-only.

Các bảng và biểu đồ được sinh khi Jupyter Book thực thi tám notebook. Repository báo cáo chỉ chứa số liệu tổng hợp và nhãn coverage P001…P073; không chứa ID/text nguồn từng paper, Parquet, manifest gốc hoặc log Drive. Các dữ liệu làm việc đó được nhóm giữ riêng.

[Source code M1–M2](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/develop) · [Đề đồ án](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/)

Link Book được giữ để nhóm cập nhật khi có thêm nguồn và benchmark. Công cụ trợ lý được dùng để hỗ trợ chuẩn bị code/báo cáo; nhóm cần đọc, kiểm tra và giải thích phần nộp.
''',encoding='utf-8')
    (output/'_config.yml').write_text('''title: arXiv Harvester — M1 và M2
author: Nhóm arXiv Harvester
execute:
  execute_notebooks: force
  allow_errors: false
  timeout: 600
sphinx:
  config:
    language: vi
    exclude_patterns: [_build, README.md, '**.ipynb_checkpoints']
    nb_execution_raise_on_error: true
''',encoding='utf-8')
    toc='format: jb-book\nroot: index\nparts:\n'
    for title,items in [('Milestone 1 — Crawling',CHAPTERS[:5]),('Milestone 2 — Parsing',CHAPTERS[5:])]:
        toc+='  - caption: '+title+'\n    chapters:\n'
        toc+=''.join('      - file: chapters/'+item[0]+'\n' for item in items)
    (output/'_toc.yml').write_text(toc,encoding='utf-8')
    (output/'.gitignore').write_text('_build/\n.jupyter_cache/\n__pycache__/\n.ipynb_checkpoints/\n',encoding='utf-8')
    (output/'.gitattributes').write_text('* -text\n',encoding='utf-8')
    (output/'requirements.txt').write_text('jupyter-book==1.0.4.post1\npandas==3.1.0\npyarrow==26.0.0\nmatplotlib==3.11.2\nnbformat==5.11.1\n',encoding='utf-8')
    (output/'README.md').write_text('''# Jupyter Book M1–M2

Báo cáo tiến độ với số liệu tổng hợp. Input biểu đồ được giữ trong `report_summary.json`; dữ liệu gốc và bảng mã paper giữ riêng.

```bash
python -m pip install -r requirements.txt
jupyter-book build . --all -W
```

Workflow Pages thực thi lại notebook và sinh bảng/biểu đồ khi build. Snapshot chưa hoàn thành toàn corpus và chưa có benchmark M2 cuối trên Colab CPU-only.
''',encoding='utf-8')
    workflow=output/'.github/workflows'; workflow.mkdir(parents=True)
    # The workflow contains no data-fetch or token-dependent step.
    (workflow/'pages.yml').write_text('''name: Build and deploy Jupyter Book
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
          cache: pip
      - run: python -m pip install -r requirements.txt
      - run: jupyter-book build . --all -W
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v4
        with:
          path: _build/html
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4
''',encoding='utf-8')
    from tools.submission_report_content import enrich
    enrich(output,summary)
    if build:
        executable=Path(sys.executable).with_name('jupyter-book.exe' if os.name=='nt' else 'jupyter-book')
        subprocess.run([str(executable),'build',str(output),'--all','-W'],check=True)
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','parsed','colab-run','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--build',action='store_true')
    print(prepare(**vars(p.parse_args())))
