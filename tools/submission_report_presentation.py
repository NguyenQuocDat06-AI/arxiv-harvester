"""Report overview, discussion and bibliography for the public M1–M2 Book."""
from pathlib import Path
from textwrap import dedent

import nbformat


SOURCE = 'https://github.com/NguyenQuocDat06-AI/arxiv-harvester'
BOOK = 'https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/'

COMMON = '''
from pathlib import Path
import json
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown
data = json.loads((Path.cwd().parent / 'report_summary.json').read_text(encoding='utf-8'))
scope, m1, m2 = data['scope'], data['m1'], data['m2']
plt.rcParams.update({'figure.figsize': (9, 4), 'axes.spines.top': False, 'axes.spines.right': False})
'''


def md(text):
    return nbformat.v4.new_markdown_cell(dedent(text).strip())


def code(text):
    return nbformat.v4.new_code_cell(dedent(text).strip(), metadata={'tags': ['hide-input']})


def m1_overview():
    return [md('''
    # Milestone 1 — Thu thập dữ liệu

    ## Mục tiêu và thiết kế

    M1 tạo corpus làm việc cho parser: metadata của paper, nguồn LaTeX/BibTeX của từng
    revision và metadata references từ Semantic Scholar. Đơn vị tải nguồn là một version;
    đơn vị tổng hợp metadata và references là một paper.

    Pipeline gồm bốn bước: **ID được giao → metadata/version → nguồn và references →
    audit, checkpoint và hai bảng M1**. Chương 1–4 giải thích từng bước; chương 5 trình
    bày phép đo crawler. Cách phân chia này tách phương pháp khỏi kết quả thực nghiệm.

    ## Dữ liệu đánh giá

    Báo cáo dùng các lô backup Drive hiện có đã kiểm tra checksum. Đây là tập khôi phục
    một phần, chọn theo giới hạn kích thước archive, không phải mẫu ngẫu nhiên. Counter
    checkpoint và số paper có nguồn được audit là hai đại lượng khác nhau.
    '''), code(COMMON), code('''
    display(Markdown('**Bảng M1.1. Phạm vi dữ liệu và đơn vị thống kê.**'))
    display(pd.DataFrame([
        ('ID được giao cho nhóm', scope['group_assigned'], 'paper'),
        ('ID được giao cho một thành viên', scope['member_assigned'], 'paper'),
        ('Snapshot thực sự được đánh giá', scope['papers'], 'paper'),
        ('Các revision thuộc snapshot', scope['versions'], 'version'),
        ('Lô backup dùng để dựng snapshot', scope['archives_used'], 'archive'),
        ('Counter checkpoint, chưa audit toàn chuỗi', scope['checkpoint_reported_ids'], 'ID'),
    ], columns=['Phạm vi', 'Số lượng', 'Đơn vị']))
    display(Markdown(f"Snapshot chiếm **{scope['papers']/scope['group_assigned']:.3%}** dải của nhóm. "
                     'Mọi tỷ lệ dưới đây chỉ mô tả tập đã kiểm tra.'))
    '''), md('''
    ## Kết quả chính

    “Nguồn hợp lệ” gồm TeX đã xác minh và trường hợp không có LaTeX có manifest làm bằng
    chứng. Tỷ lệ có kết quả S2 dùng cả `success` và `empty` được xác nhận. Paper đủ nguồn
    và S2 được tính bằng giao của hai tập; không lấy tỷ lệ nguồn thay cho tỷ lệ thu thập
    đủ cả hai thành phần. Ngày version còn thiếu được thống kê riêng ở chương 1.
    '''), code('''
    metrics = pd.DataFrame([
        ('Version có TeX đã xác minh', m1['source_audit'].get('tex_verified', 0), scope['versions']),
        ('Version có nguồn hợp lệ, gồm empty', m1['source_verified'], scope['versions']),
        ('Paper có mọi nguồn hợp lệ', m1['papers_with_all_sources_verified'], scope['papers']),
        ('Paper có S2 success/empty', m1['verified_reference_papers'], scope['papers']),
        ('Paper có mọi nguồn hợp lệ và S2', m1['papers_with_sources_and_s2_verified'], scope['papers']),
    ], columns=['Chỉ tiêu', 'Số đạt', 'Mẫu số'])
    metrics['Tỷ lệ (%)'] = (100 * metrics['Số đạt'] / metrics['Mẫu số']).round(2)
    display(Markdown('**Bảng M1.2. Kết quả audit trên snapshot; mẫu số ghi riêng cho từng chỉ tiêu.**'))
    display(metrics)
    plot = metrics.iloc[2:].copy()
    ax = plot.plot.barh(x='Chỉ tiêu', y='Tỷ lệ (%)', legend=False, xlim=(0, 112), color='#2f628e')
    for i, row in enumerate(plot.to_dict('records')):
        ax.text(row['Tỷ lệ (%)'] + 1, i, f"{row['Số đạt']}/{row['Mẫu số']}", va='center')
    ax.set_xlabel('Tỷ lệ paper trong snapshot (%)'); ax.set_ylabel('')
    plt.tight_layout(); plt.show()
    display(Markdown('**Hình M1.1. Độ phủ nguồn và references.** Các thanh có cùng mẫu số paper; '
                     'chênh lệch cho thấy phần references cần được bổ sung.'))
    '''), code('''
    display(Markdown('**Bảng M1.3. Kích thước và references, kèm tập đủ điều kiện.**'))
    display(pd.DataFrame([
        ('Byte trung bình trước lọc', f"{m1['mean_before_bytes']:,.2f}", f"{m1['eligible_size_papers']} paper đủ nguồn TeX"),
        ('Byte trung bình sau lọc', f"{m1['mean_after_bytes']:,.2f}", f"Cùng {m1['eligible_size_papers']} paper"),
        ('Mức giảm byte do lọc', f"{m1['source_reduction']:.2%}", 'Tỷ số hai tổng trên cùng tập'),
        ('References trung bình / paper', f"{m1['mean_references_verified_papers']:.2f}", f"{m1['verified_reference_papers']} paper có S2 success/empty"),
        ('Cạnh references làm việc', str(m1['working_reference_rows']), 'Các cạnh thực có trong snapshot'),
        ('Cạnh có đích arXiv xuất bảng chuẩn', str(m1['arxiv_reference_rows']), 'Tập con của working references'),
    ], columns=['Chỉ tiêu', 'Giá trị', 'Tập tính']))
    '''), md('''
    ## Nhận xét

    Tải và lọc nguồn tạo được đầu vào để tiếp tục M2, còn độ phủ references là hạn chế chính
    của M1 trên snapshot. Việc thiếu DOI, venue hoặc ngày revision cần được diễn giải theo
    từng trường, thay vì gộp thành một nhãn “thành công”. Phép đo Colab đã lưu được báo cáo
    riêng theo đúng 14 paper xử lý trong lượt đó ở [chương 5](05_performance_benchmark.ipynb).

    Tiếp tục đọc [discovery](01_discovery_and_versions.ipynb), [nguồn và kích thước](02_source_download_and_cleaning.ipynb),
    [references](03_reference_extraction.ipynb) và [schema/validation](04_schema_and_data_quality.ipynb).
    ''')]


def m2_overview():
    return [md('''
    # Milestone 2 — Phân tích cấu trúc và chuẩn hóa

    ## Mục tiêu và đầu ra

    M2 chuyển các version của M1 thành nội dung có cấu trúc. Pipeline **gathering →
    hierarchy → chuẩn hóa và bibliography → khử trùng → validation** tạo ba bảng
    `elements`, `hierarchy`, `bibtex`. Manifest theo dõi cả version xử lý được, partial,
    empty và lỗi để không làm mất mẫu số.

    Chương 6 minh họa compilation path và cây phân cấp bằng ví dụ tổng hợp chạy từ parser
    thật. Chương 7 giải thích chuẩn hóa/citation/dedup; chương 8 trình bày phép đo trên
    cùng input. Ví dụ tổng hợp được tách khỏi các thống kê corpus bên dưới.

    ## Kết quả xử lý theo version
    '''), code(COMMON), code('''
    labels = {'success':'Success', 'partial':'Partial', 'empty_no_tex':'Empty có bằng chứng',
              'error':'Lỗi parser/root', 'error_missing_source':'Thiếu nguồn'}
    status = pd.DataFrame([
        {'Trạng thái': label, 'Số version': m2['status_counts'].get(key, 0)}
        for key, label in labels.items()
    ])
    status['Tỷ lệ trên mọi version (%)'] = (100 * status['Số version'] / scope['versions']).round(2)
    display(Markdown('**Bảng M2.1. Trạng thái parser trên toàn bộ version trong snapshot.**'))
    display(status)
    ax = status.plot.barh(x='Trạng thái', y='Số version', legend=False,
                         color=['#34785a', '#bd8b25', '#768a9a', '#b5534a', '#9b6259'])
    for i, row in enumerate(status.to_dict('records')):
        ax.text(row['Số version'] + .6, i, str(row['Số version']), va='center')
    ax.set_xlim(0, max(status['Số version']) * 1.16); ax.set_ylabel('')
    plt.tight_layout(); plt.show()
    display(Markdown('**Hình M2.1. Kết quả parser theo version.** Partial giữ các phần đã đọc được '
                     'nhưng vẫn cần xử lý diagnostics trước khi xác nhận hoàn tất.'))
    '''), code('''
    complete_papers = sum(row['success_versions'] + row['empty_versions'] == row['expected_versions']
                          for row in m2['coverage'])
    success = m2['status_counts'].get('success', 0)
    display(Markdown('**Bảng M2.2. Coverage, số dòng và mức giảm sau khử trùng.**'))
    rows = [
        ('Version success / mọi version', f"{success}/{scope['versions']}", f"{success/scope['versions']:.2%}"),
        ('Version success / version có TeX', f"{success}/{m2['versions_with_tex']}", f"{success/m2['versions_with_tex']:.2%}"),
        ('Paper có mọi version success hoặc empty', f"{complete_papers}/{scope['papers']}", 'Đánh giá theo từng paper'),
    ]
    rows += [(f'Số dòng {name}', f'{count:,}', 'Sau xử lý') for name, count in m2['rows'].items()]
    rows += [(f'Khử trùng {name}', f"{values['before']:,} → {values['after']:,}", f"Giảm {values['reduction_rate']:.2%}")
             for name, values in m2['deduplication'].items()]
    display(pd.DataFrame(rows, columns=['Chỉ tiêu', 'Kết quả', 'Diễn giải']))
    display(Markdown(f"Có **{m2['unresolved_cites']:,} citation occurrence chưa resolve** và "
                     f"**{m2['bibliography_conflicts']:,} xung đột trường bibliography** được lưu để kiểm tra. "
                     'Tỷ lệ dedup chỉ áp dụng các phần có before-count đo được; không xác nhận '
                     'mọi version partial đã được đọc trọn vẹn.'))
    '''), md('''
    ## Đánh giá kết quả

    Kiểm tra năm bảng đạt về schema, khóa và quan hệ graph trên snapshot. Trạng thái
    `processing_complete` còn false vì partial/error; giảm số phần tử sau dedup không
    thay thế điều kiện này. Các trường hợp root mơ hồ và thiếu nguồn được giữ trong
    coverage cùng các version xử lý thành công.

    Số đo parser hiện có là **Windows CPU**, không phải benchmark cuối trên Colab. Để
    cập nhật phép đo Colab, dùng notebook parser với cùng gói input; không cần crawl lại
    dữ liệu chỉ để đo M2. Xem [chương 8](08_parser_benchmark.ipynb) và
    [phụ lục tái lập](09_reproducibility.ipynb).
    ''')]


def discussion():
    return [md('''
    # Thảo luận và kết luận

    ## Kết quả đã có bằng chứng

    Nhóm đã nối được pipeline M1–M2: từ metadata/version và corpus nguồn đến năm bảng
    có kiểm tra cấu trúc. Snapshot nhỏ cho phép rà từng version, đối chiếu lỗi với source
    và chạy lại parser trên cùng đầu vào. Các biểu đồ của Book lấy từ thống kê của chính
    các lượt này; số đo của nhóm khác không được đưa vào kết quả.

    ## Các điểm còn hạn chế
    '''), code(COMMON), code('''
    missing_sources = scope['versions'] - m1['source_verified']
    unresolved_s2 = scope['papers'] - m1['verified_reference_papers']
    display(Markdown('**Bảng T.1. Phần việc còn lại trên snapshot, theo mức phụ thuộc.**'))
    display(pd.DataFrame([
        (1, 'Nguồn', missing_sources, 'version', 'Xác minh hoặc tải lại đúng revision rồi audit'),
        (2, 'S2 chưa success/empty', unresolved_s2, 'paper', 'Truy vấn lại theo cooldown, kiểm tra phân trang và provenance'),
        (3, 'Parser partial', m2['status_counts'].get('partial', 0), 'version', 'Đối chiếu include, bibliography và citation diagnostics'),
        (4, 'Root/parser error', m2['status_counts'].get('error', 0), 'version', 'Chọn root khi source có bằng chứng, rồi parse lại'),
        (5, 'Benchmark M2 Colab cuối', 'Chưa có', 'lượt đo', 'Chạy notebook CPU-only trên cùng input và lưu output thật'),
    ], columns=['Thứ tự', 'Hạng mục', 'Số lượng', 'Đơn vị', 'Cách hoàn thiện']))
    display(Markdown('Các hàng có thể liên quan cùng một paper; không cộng chúng thành tổng paper lỗi. '
                     '“Chưa có” nghĩa là chưa có phép đo Colab tương ứng.'))
    '''), md('''
    ## Phân tích lỗi và tác động

    References thiếu làm giảm tập ứng viên cho bài toán matching về sau, ngay cả khi paper
    đã có đủ TeX. Unresolved citation khiến việc liên kết nội dung với bibliography chưa
    trọn vẹn; đó là lý do các version này được giữ partial. Một compilation root chưa
    xác định được phải được xử lý riêng, vì chọn nhầm root có thể tạo một cây hợp lệ về
    hình thức nhưng chứa sai tài liệu.

    Các nhóm diagnostic có thể cùng xuất hiện trong một version. Biểu đồ dưới đếm version
    có từng loại diagnostic, không khẳng định một nguyên nhân duy nhất cho mọi lỗi.
    '''), code('''
    diagnostics = pd.Series(m2['diagnostic_categories']).sort_values()
    ax = diagnostics.plot.barh(color='#b57b36', xlabel='Version có diagnostic', ylabel='')
    for i, count in enumerate(diagnostics):
        ax.text(count + .25, i, str(count), va='center')
    ax.set_xlim(0, diagnostics.max() * 1.15)
    plt.tight_layout(); plt.show()
    display(Markdown('**Hình T.1. Các nhóm diagnostic trên snapshot.** Nguồn: tổng hợp manifest parser.'))
    '''), md('''
    ## Hiệu năng và giới hạn suy luận

    M1 chịu ảnh hưởng của API, mạng, kích thước archive và thời gian chờ; M2 chủ yếu thao tác
    trên nguồn cục bộ. Hai lượt đang có khác phạm vi và môi trường, nên không dùng chúng để
    so tốc độ trực tiếp. Số đo mẫu cũng chưa đủ để bảo đảm thời gian hoàn tất 25.000 paper.

    Snapshot được chọn theo archive sẵn có và giới hạn tải, không theo thiết kế lấy mẫu
    ngẫu nhiên. Vì vậy tỷ lệ thành công, kích thước trung bình và mức giảm dedup mô tả tập
    đã kiểm tra; chưa đại diện chắc chắn cho cả dải được giao.

    ## Kết luận

    Kết quả hiện tại cho thấy pipeline có thể tạo đầu ra M1–M2 và phát hiện rõ các trường
    hợp chưa xử lý xong. Để hoàn tất dữ liệu, nhóm cần khép phần nguồn/references còn thiếu,
    xử lý diagnostics, chạy validation lại trên phạm vi M1 đã chốt và bổ sung benchmark
    Colab. Những lần cập nhật tiếp tục dùng cùng repository source và URL Book.
    ''')]


REFERENCES = '''
# Tài liệu tham khảo

## Đề bài và tài liệu kỹ thuật

1. HCMUS CS Teaching Assistants. [Quy định và yêu cầu chung](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/), [Milestone 1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/), [Milestone 2](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/). Chuẩn đối chiếu nội dung và phép đo của báo cáo.
2. arXiv. [API User's Manual](https://info.arxiv.org/help/api/user-manual.html), [API Terms of Use](https://info.arxiv.org/help/api/tou.html), [Full-text harvesting](https://info.arxiv.org/help/bulk_data.html). Tham khảo discovery, endpoint và nhịp truy cập.
3. Allen Institute for AI. [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/graph). Tham khảo định danh, trường metadata và phân trang references.

## Các báo cáo cùng bài toán đã tham khảo về cách trình bày

Các nguồn dưới được đọc ngày 06/11/2026. Phần tham khảo là bố cục báo cáo, cách tách
phương pháp/thực nghiệm và cách chỉ rõ input của biểu đồ. Nội dung phân tích, ví dụ
và kết quả của Book này được viết từ source và dữ liệu của nhóm.

4. Nhóm `hcmus-arxiv-nhom1`. [arXiv Citation Pipeline — Group 1](https://hcmus-arxiv-nhom1.github.io/arxiv-book/), source tại [1542331](https://github.com/hcmus-arxiv-nhom1/arxiv-book/tree/1542331e3d7b8a7e5e0ad5f4ee9a082ed82a5208). Tham khảo cách chia overview, methodology, data statistics, performance và discussion; tách phạm vi phép đo khỏi trạng thái corpus.
5. Nhóm `ahtuan171`. [Khung báo cáo M1–M2](https://github.com/ahtuan171/arXiv-Project/tree/dd076d4dbc86d7b8abad54cf9b9bd8abeab80f0e/book). Tham khảo cách chia hai phần milestone và thứ tự các bước xử lý. Tại bản đã đọc, notebook chủ yếu là khung, không dùng làm bằng chứng kết quả hoàn tất.
6. Nhóm `tuandatedu`. [Notebook báo cáo M2](https://github.com/tuandatedu/arXir_project/blob/f2715ba852dd5992bbca3bf945ddfc4cad43fc8a/src/m2_parsing/report_m2.ipynb). Tham khảo cách notebook đọc file metrics riêng, phân biệt run mới/resume và trình bày standardization/dedup.
7. Nhóm `thinhelzan842`. [Các notebook thống kê và hiệu năng](https://github.com/thinhelzan842/intro-ds-arxiv-project/tree/cb5a2905290acb11febb15a1f00851a77106212f/docs/milestone1). Tham khảo thứ tự bảng chỉ tiêu, size trước/sau, version và RAM/đĩa. Các giá trị benchmark không được chuyển sang báo cáo của nhóm.

## Source và khả năng tái lập của nhóm

[Repository code, nhánh main](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/tree/main) ·
[Đóng góp và lịch sử thành viên](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/blob/main/CONTRIBUTIONS.md) ·
[Source dựng báo cáo](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/blob/main/tools/build_public_submission_book.py).

Commit parser cho các ví dụ thực thi được ghim trong `requirements.txt`. Thông tin môi
trường của các lượt đo được hiển thị tại chương benchmark tương ứng. Công cụ trợ lý được
dùng để hỗ trợ chuẩn bị code và nội dung; nhóm chịu trách nhiệm kiểm tra và giải thích bản nộp.
'''


def present(output: Path, summary: dict):
    """Apply the report layout while keeping existing chapter URLs and measurements."""
    additions = [('00_m1_overview', m1_overview), ('00_m2_overview', m2_overview),
                 ('12_discussion_and_conclusion', discussion)]
    for name, builder in additions:
        book = nbformat.v4.new_notebook(cells=builder())
        book.metadata.kernelspec = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
        nbformat.write(book, output / 'chapters' / (name + '.ipynb'))
    (output / 'chapters' / '11_references.md').write_text(dedent(REFERENCES).strip() + '\n', encoding='utf-8')
    for path in (output / 'chapters').glob('*.ipynb'):
        book = nbformat.read(path, as_version=4)
        for cell in book.cells:
            if cell.cell_type == 'code':
                cell.metadata['tags'] = list(dict.fromkeys([*cell.metadata.get('tags', []), 'hide-input']))
        nbformat.write(book, path)
    _write_resource_chapter(output)
    scope = summary['scope']
    (output / 'index.md').write_text(f'''# arXiv Harvester — Thu thập và xử lý dữ liệu bài báo

Báo cáo đồ án **Nhập môn Khoa học dữ liệu**, Milestone 1 và 2. Cập nhật ngày {summary['report_date']}.

## Tóm tắt

Nhóm xây dựng pipeline thu thập metadata, nguồn LaTeX/BibTeX và references của bài báo arXiv,
sau đó phân tích cấu trúc theo version, chuẩn hóa nội dung và khử trùng. Báo cáo trình bày
thiết kế, kết quả kiểm tra, chi phí tài nguyên và các lỗi còn lại trên dữ liệu đã có.

Phạm vi đánh giá hiện tại là **{scope['papers']} paper và {scope['versions']} version**, dựng từ
{scope['archives_used']} lô backup đã kiểm tra checksum. Dải được giao cho toàn nhóm gồm
{scope['group_assigned']:,} paper. Kết quả snapshot và phép đo từng lượt được ghi riêng trong
các bảng để người đọc đối chiếu đúng phạm vi.

## Thành viên và phạm vi phụ trách

- **Nguyễn Quốc Đạt — 24120282:** discovery, metadata/version và tích hợp.
- **Nguyễn Đình Tuấn — 24120237:** tải, giải nén, lọc nguồn và audit.
- **Trần Nguyên Tân — 24120438:** references, Semantic Scholar và provenance.
- **Dương Phan Minh Trí — 24120470:** lưu trữ, schema, parser và chuẩn hóa dữ liệu.
- **Trịnh Vỹ Triết — 24120474:** runner, profiler, benchmark và dựng Book.

[Lịch sử và phần đóng góp của thành viên]({SOURCE}/blob/main/CONTRIBUTIONS.md).

## Nội dung báo cáo

**[Milestone 1 — Thu thập dữ liệu](chapters/00_m1_overview.ipynb)** mở đầu bằng bảng chỉ tiêu,
rồi đi vào discovery, tải nguồn, references, schema và hiệu năng. Các trung bình và tỷ lệ
đều có tập tính và mẫu số.

**[Milestone 2 — Phân tích cấu trúc và chuẩn hóa](chapters/00_m2_overview.ipynb)** trình bày
coverage của parser, gathering/hierarchy, normalization/dedup và tài nguyên đo được.
Các ví dụ thuật toán tổng hợp được đánh dấu riêng với thống kê corpus.

**[Thảo luận và kết luận](chapters/12_discussion_and_conclusion.ipynb)** tổng hợp kết quả,
giới hạn và thứ tự hoàn thiện. Phụ lục cung cấp
[lệnh tái lập](chapters/09_reproducibility.ipynb),
[đối chiếu yêu cầu](chapters/10_requirements_and_limitations.ipynb) và
[tài liệu tham khảo](chapters/11_references.md).

## Dữ liệu và phép đo

Input công khai gồm thống kê tổng hợp và nhãn paper P001…; nguồn TeX/Bib, bảng mã, Parquet và
log gốc được giữ trong workspace của nhóm. Bảng và biểu đồ thống kê được notebook sinh khi
Book biên dịch. Có thể mở phần code thu gọn để kiểm tra công thức.

Snapshot chưa hoàn tất: còn nguồn/references lỗi, version partial và root chưa chọn được.
Số đo M1 là một lượt Colab CPU-only đã tạm dừng, phạm vi 14 paper; số đo M2 là lượt Windows
CPU trên {scope['papers']} paper. Benchmark M2 cuối trên Colab CPU-only vẫn cần bổ sung.

## Liên kết

[Source code — main]({SOURCE}/tree/main) ·
[Repository báo cáo]({SOURCE}-book) ·
[Đề đồ án](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/).

**URL Book cố định:** {BOOK}
''', encoding='utf-8')
    (output / '_toc.yml').write_text('''format: jb-book
root: index
parts:
  - caption: Milestone 1 — Thu thập dữ liệu
    chapters:
      - file: chapters/00_m1_overview
      - file: chapters/01_discovery_and_versions
      - file: chapters/02_source_download_and_cleaning
      - file: chapters/03_reference_extraction
      - file: chapters/04_schema_and_data_quality
      - file: chapters/05_performance_benchmark
  - caption: Milestone 2 — Phân tích cấu trúc và chuẩn hóa
    chapters:
      - file: chapters/00_m2_overview
      - file: chapters/06_parsing_and_hierarchy
      - file: chapters/07_standardization_and_deduplication
      - file: chapters/08_parser_benchmark
  - caption: Thảo luận và phụ lục
    chapters:
      - file: chapters/12_discussion_and_conclusion
      - file: chapters/09_reproducibility
      - file: chapters/10_requirements_and_limitations
      - file: chapters/11_references
''', encoding='utf-8')
    (output / '_config.yml').write_text(f'''title: arXiv Harvester — Milestone 1 và 2
author: Nhóm arXiv Harvester
repository:
  url: {SOURCE}-book
  branch: main
html:
  use_repository_button: true
  use_edit_page_button: true
  extra_css: [report.css]
execute:
  execute_notebooks: force
  allow_errors: false
  timeout: 600
sphinx:
  config:
    language: vi
    exclude_patterns: [_build, README.md, '**.ipynb_checkpoints']
    nb_execution_raise_on_error: true
    html_static_path: [_static]
''', encoding='utf-8')
    static = output / '_static'
    static.mkdir(exist_ok=True)
    (static / 'report.css').write_text('''.bd-article-container { max-width: 58rem; }
.bd-article h1 { line-height: 1.25; }
.bd-article p, .bd-article li { line-height: 1.7; }
.dataframe { font-size: .9rem; }
.dataframe th, .dataframe td { padding: .55rem .7rem; }
.cell_output { margin: .8rem 0 1.6rem; }
''', encoding='utf-8')


def _write_resource_chapter(output):
    path = output / 'chapters' / '08_parser_benchmark.ipynb'
    book = nbformat.read(path, as_version=4)
    position = next(i for i, cell in enumerate(book.cells)
                    if cell.cell_type == 'markdown' and '## 8.4' in cell.source)
    book.cells[position:position] = [md('''
    ### Diễn biến RSS và dung lượng đĩa

    Các mẫu tài nguyên gốc của lượt Windows được tổng hợp theo cửa sổ 5 giây. Mỗi cửa sổ
    giữ trung bình các mẫu RSS, RSS lớn nhất và disk lớn nhất đã quan sát. Trung bình RSS
    trong cửa sổ là trung bình mẫu; chỉ số RAM trung bình toàn run ở trên dùng trọng số
    thời gian và được giữ nguyên từ profiler. Điểm disk chỉ hiện ở cửa sổ có mẫu, không
    điền thêm quan sát cho khoảng trống. Đơn vị MiB bằng 1.048.576 byte.
    '''), code('''
    profile = run.get('resource_profile')
    if profile and profile['rows']:
        frame = pd.DataFrame(profile['rows'])
        fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
        rss = frame.dropna(subset=['rss_peak_mib'])
        axes[0].plot(rss['window_end_sec'], rss['rss_peak_mib'], label='Peak trong cửa sổ', color='#2f628e')
        axes[0].plot(rss['window_end_sec'], rss['rss_sample_mean_mib'], label='Mean mẫu trong cửa sổ', color='#7c9bb2')
        axes[0].set(xlabel='Giây từ đầu profiler', ylabel='RSS (MiB)', title='RAM của lượt parser Windows')
        axes[0].legend(fontsize=8)
        disk = frame.dropna(subset=['disk_peak_bytes'])
        axes[1].scatter(disk['window_end_sec'], disk['disk_peak_bytes']/1024**2, color='#b57b36', s=16)
        axes[1].set(xlabel='Giây từ đầu profiler', ylabel='Disk workspace (MiB)', title='Peak disk quan sát theo cửa sổ')
        plt.tight_layout(); plt.show()
        display(Markdown('**Hình M2.2. Tài nguyên parser theo thời gian.** '
                         f"Tổng hợp {profile['rss_samples']} mẫu RSS và {profile['disk_samples']} mẫu disk, "
                         f"cửa sổ {profile['window_sec']:g} giây. Đây là số đo Windows của snapshot, không phải Colab."))
    else:
        print('Chưa có chuỗi mẫu tài nguyên cho run này; chỉ trình bày chỉ số tổng hợp đã lưu.')
    ''')]
    nbformat.write(book, path)
