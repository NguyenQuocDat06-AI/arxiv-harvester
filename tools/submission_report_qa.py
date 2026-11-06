"""Apply the instructor's QA clarifications to the public report."""
from pathlib import Path

import nbformat

from tools.submission_report_content import code, md


QA = 'https://docs.google.com/spreadsheets/d/11UDWf52DitCDrV386WkYK0ZySqTGQSCRnEwQ37u9uyQ/edit'


def append_section(output, name, cells):
    path = output / 'chapters' / (name + '.ipynb')
    book = nbformat.read(path, as_version=4)
    position = next((i for i, c in enumerate(book.cells)
                     if c.cell_type == 'markdown' and c.source.startswith('## Tài liệu')), len(book.cells))
    book.cells[position:position] = cells
    for cell in book.cells:
        if cell.cell_type == 'code':
            cell.metadata['tags'] = list(dict.fromkeys([*cell.metadata.get('tags', []), 'hide-input']))
    nbformat.write(book, path)


def session_cells(stage):
    return [code(f'''
    sessions = data['session_measurements']['{stage}']
    frame = pd.DataFrame(sessions['sessions'])
    display(Markdown('**Bảng phiên đo {stage}.** Nhãn S1… dùng trong báo cáo; log và run ID gốc được nhóm giữ để đối chiếu.'))
    for columns in [
        ['session','status','colab_cpu','processed_attempts','profiler_sec','child_wall_sec'],
        ['session','peak_rss_mib','avg_rss_mib','peak_disk_bytes','final_disk_bytes'],
        ['session','publications_reused','versions_reused'],
    ]:
        table = frame[columns]
        display(table.astype(object).where(table.notna(), 'Chưa có'))
    totals = pd.Series(sessions['totals'], name='Giá trị')
    display(totals.astype(object).where(totals.notna(), 'Chưa xác minh').to_frame())
    ''')]


def apply_qa(output: Path):
    index = (output / 'index.md').read_text(encoding='utf-8')
    note = f'''## Mốc nộp và trạng thái bản này

Theo [phản hồi của giảng viên tại dòng 7]({QA}#gid=0&range=A7:B7), đợt nộp Book hiện tại
là nộp link để ghi nhận tiến độ. Nhóm được tiếp tục hoàn thiện nội dung đến deadline Poster
trên Moodle, giữ nguyên URL. Bản này vì vậy trình bày kết quả đã có và các phần cần làm tiếp;
benchmark cuối vẫn phải đáp ứng phạm vi toàn nhóm trên Colab CPU-only.

Các điều chỉnh về `.bbl`, ngày references và benchmark nhiều phiên được giải thích tại
[phụ lục QA](chapters/13_teacher_qa.md). Book dùng tiếng Việt cho chương trình Chuẩn.

'''
    index = index.replace('## Thành viên và phạm vi phụ trách', note + '## Thành viên và phạm vi phụ trách')
    (output / 'index.md').write_text(index, encoding='utf-8')
    append_section(output, '05_performance_benchmark', [md(r'''
    ## 5.6 Benchmark qua nhiều phiên Colab

    QA dòng 13–17 yêu cầu benchmark cuối trên toàn dải của nhóm, tính cả retry/delay và cho
    phép chia nhiều phiên Colab. Mỗi phiên giữ log, stats, phạm vi ID, code/config, phần xử lý
    mới và phần dùng lại. M1 và M2 được tổng hợp thành hai báo cáo riêng.

    Với các phiên cùng loại, tổng thời gian được đo là $\sum_i T_i$. Retry và delay đã nằm
    trong runtime, nên không cộng thêm từ log. Tổng này loại khoảng nghỉ giữa các phiên và
    khác thời gian lịch từ lúc bắt đầu phiên đầu đến lúc kết thúc phiên cuối. Chỉ cộng child
    wall khi mọi phiên đều có số đo đó; profiler time vẫn mang phạm vi profiler.

    RAM trung bình gộp xấp xỉ $\sum_i \bar{R}_i T_i/\sum_i T_i$, dùng thời lượng profiler
    tương ứng với mẫu RSS. Peak được ghi là lớn nhất trong các peak phiên, không cộng chúng.
    Nếu các phiên chồng thời gian, số này không mô tả tổng RAM đồng thời của nhiều runtime.
    Final disk đo trên output hợp nhất đã chốt, không cộng các bản checkpoint trùng nhau.

    Công cụ `src/crawler/benchmark_sessions.py` loại bản sao cùng run ID, từ chối stats mâu
    thuẫn và giữ null khi thiếu bằng chứng. Tổng số lượt xử lý có thể lặp paper khi repair;
    độ phủ ID/version duy nhất vẫn phải kiểm tra bằng dữ liệu và audit.

    Bảng dưới hiện chỉ có một phiên M1 đã lưu. Việc có công cụ gộp phiên chưa làm số đo mẫu
    này trở thành benchmark đủ 25.000 paper.
    '''), *session_cells('M1')])
    append_section(output, '08_parser_benchmark', [md('''
    ## 8.6 Phạm vi phiên đo parser

    Số liệu Windows hiện có được giữ làm mốc tiến độ trước các điều chỉnh `.bbl` theo QA.
    Các ví dụ thuật toán mới dùng commit ghim trong requirements; số liệu corpus bên trên
    không được tính lại chỉ vì ví dụ mới chạy thành công. Phiên Windows được ghi riêng và
    không được gộp với phiên crawler Colab thành một benchmark của cả pipeline.
    '''), *session_cells('M2')])
    append_section(output, '07_standardization_and_deduplication', [md('''
    ## 7.6 Bibliography chỉ có trong `.bbl`

    Theo QA dòng 19, downloader giữ `.bbl` bổ trợ cùng revision. Khi thiếu hoặc không đọc
    được `.bib`, parser ưu tiên `.bbl` trùng tên compilation root; nếu không có, chỉ xét
    tên bibliography được khai báo trên luồng biên dịch. Nhiều ứng viên chưa phân giải được
    hoặc cú pháp chưa hỗ trợ được giữ diagnostic, không ghép mọi `.bbl` trong thư mục.

    Các `bibitem` đọc được chuyển thành bản ghi bibliography, giữ raw citation trong working
    data. Bản gốc `.bbl` được giữ nguyên vì không thể bảo đảm phục hồi đầy đủ `.bib` ban đầu.
    Fingerprint có tính `.bbl`, nên thay file này làm parser xử lý lại publication khi resume.

    Ví dụ tổng hợp sau chạy parser thật với TeX gọi một `.bib` bị thiếu nhưng có `main.bbl`.
    Nó minh họa chức năng mới, không bổ sung paper hay số đếm vào snapshot.
    '''), code(r'''
    import tempfile
    from parser.main import process_publication
    with tempfile.TemporaryDirectory() as work:
        raw = Path(work)
        folder = raw / 'unzipped' / '2502.90001' / 'v1'
        folder.mkdir(parents=True)
        (folder / 'main.tex').write_text(
            r'\documentclass{article}\begin{document}A result \cite{key}.\bibliography{missing}\end{document}',
            encoding='utf-8')
        (folder / 'main.bbl').write_text(
            r'\begin{thebibliography}{9}\bibitem{key}Alice.\newblock Example reference.\newblock Journal, 2020.\end{thebibliography}',
            encoding='utf-8')
        result = process_publication({'id':'2502.90001', 'versions':[{'version':'v1','source_status':'success'}]}, raw)
        assert result['manifests'][0]['status'] == 'success'
        assert result['bibtex'][0]['citation_key'] == 'key'
        display(pd.DataFrame(result['bibtex']))
        display(pd.DataFrame([{'status':result['manifests'][0]['status'],
                               'bibliography_files':result['manifests'][0]['bibliography_files'],
                               'unresolved_cites':result['manifests'][0]['unresolved_cites']}]))
    ''')])
    append_section(output, '09_reproducibility', [md('''
    ## A.6 Tổng hợp log benchmark theo phiên

    Dùng cùng input/phạm vi đã chốt và ghi code/config của từng phiên Colab. Giữ nguyên
    `stats.json`, `run_metadata.json` và resource samples của từng run; đưa từng bản stats
    vào lệnh dưới đây đúng một lần. File metadata, nếu có, nằm cạnh stats và phải trùng run ID.

    ```bash
    python -m src.crawler.benchmark_sessions --stats LOGS/run1/stats.json LOGS/run2/stats.json --final-output-dir OUTPUT_FINAL --output benchmark_m1_sessions.json
    ```

    Với M2, dùng các stats của parser trong một lệnh riêng. Output phân biệt profiler time,
    child wall, số lượt xử lý, cache, RAM/đĩa và môi trường. Thiếu child wall ở một phiên làm
    tổng child wall giữ null; không dùng profiler time của phiên đó để điền vào cùng cột.

    Đối chiếu ID và version trên output hợp nhất bằng source audit và project validation.
    Không dùng tổng counter theo phiên để suy ra số paper duy nhất. Khác phần cứng hoặc
    code giữa phiên cần được công bố khi phân tích hiệu năng.
    ''')])
    (output / 'chapters' / '13_teacher_qa.md').write_text(f'''# Phụ lục C. Đối chiếu hướng dẫn QA

Nguồn: [QA Replies 2627-1]({QA}), đọc ngày 06/11/2026. Đây là phần đối chiếu các hướng dẫn
ảnh hưởng đến báo cáo; các phản hồi gốc xem tại từng liên kết.

- [M1 dòng 7]({QA}#gid=0&range=A7:B7): nộp link Book theo mốc tiến độ; hoàn thiện đến hạn Poster và giữ URL. Trang đầu đã phân biệt hai mốc này.
- [M1 dòng 13–17]({QA}#gid=0&range=A13:B17): benchmark cuối trên toàn dải, gồm retry/delay; được chia phiên Colab có log. Chương 5 và phụ lục A mô tả cách gộp.
- [M1 dòng 15]({QA}#gid=0&range=A15:B15): chương trình Chuẩn dùng tiếng Việt. Nhóm đã xác nhận chương trình này.
- [M1 dòng 19]({QA}#gid=0&range=A19:B19): thử chuyển `.bbl`, giữ nguồn khi chưa chuyển được. Chương 2 và 7 trình bày xử lý bổ trợ và giới hạn.
- [M1 dòng 20–21]({QA}#gid=0&range=A20:B21): references được dùng ngày S2 hoặc ngày qua arXiv ID. Chương 3 ghi quy ước và provenance.
- [M1 dòng 17, 22]({QA}#gid=0&range=A17:B22): hai chương chính M1/M2, thông tin thành viên và các mục kỹ thuật rõ ràng. URL các trang đã có được giữ.

## Phần chuẩn bị cho Milestone 3

[M3 dòng 2–3]({QA}#gid=1061532440&range=A2:B3) quy định ít nhất 5 publication gán nhãn
cho mỗi thành viên; nhóm 5 người tương ứng ít nhất 25 publication. Pipeline dùng chung,
còn mỗi người trích output theo dải ID của mình để host trên Hugging Face cá nhân.

Đây là kế hoạch cho M3, không phải kết quả gán nhãn hoặc dataset cuối đã nộp. Dataset làm
việc chung hiện có vẫn phục vụ xử lý và kiểm tra trong nhóm.

## Bằng chứng hiện còn thiếu

Snapshot vẫn là 73 paper/119 version. Cần khép phần nguồn/references thiếu, xử lý các version
partial/error và thực hiện benchmark cuối trên Colab. Các cập nhật code theo QA không tự
thay đổi số liệu của những lượt lịch sử. Các ví dụ `.bbl` trong Book là dữ liệu tổng hợp.
''', encoding='utf-8')
    refs = output / 'chapters' / '11_references.md'
    refs.write_text(refs.read_text(encoding='utf-8') + f'''

## Hướng dẫn bổ sung của giảng viên

[QA Replies 2627-1]({QA}), đọc ngày 06/11/2026. Các nội dung được áp dụng và liên kết đến
dòng phản hồi gốc nằm tại [phụ lục QA](13_teacher_qa.md).
''', encoding='utf-8')
