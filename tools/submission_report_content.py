"""Detailed report chapters generated from public aggregates and synthetic demos."""
from __future__ import annotations

from pathlib import Path
import textwrap

import nbformat


CODE_COMMIT = 'e8d409200fa3483bc52eb5a914c602c552def133'
CODE_URL = 'https://github.com/NguyenQuocDat06-AI/arxiv-harvester'
BOOK_URL = 'https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/'


def md(text):
    text = textwrap.dedent(text).strip()
    text = text.replace(r'\[', '\n$$\n').replace(r'\]', '\n$$\n')
    text = text.replace(r'\(', '$').replace(r'\)', '$')
    return nbformat.v4.new_markdown_cell(text)


def code(text):
    return nbformat.v4.new_code_cell(textwrap.dedent(text).strip())


COMMON = """
from pathlib import Path
import json
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown
data = json.loads((Path.cwd().parent / 'report_summary.json').read_text(encoding='utf-8'))
scope, m1, m2 = data['scope'], data['m1'], data['m2']
plt.rcParams.update({'figure.figsize': (9, 4), 'axes.spines.top': False, 'axes.spines.right': False})
print(f"Snapshot: {scope['papers']} paper / {scope['versions']} version; báo cáo ngày {data['report_date']}")
"""


def references(stage, files=()):
    course = 'crawling' if stage == 'M1' else 'parsing'
    lines = [f'- [Đặc tả {stage}](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/{course}/).',
             '- [arXiv API: cấu trúc truy vấn và Atom](https://info.arxiv.org/help/api/user-manual.html).',
             '- [Quy định truy cập arXiv](https://info.arxiv.org/help/api/tou.html).',
             '- [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/graph).']
    lines += [f'- Mã triển khai: [{name}]({CODE_URL}/blob/{CODE_COMMIT}/{name}).' for name in files]
    return md('## Tài liệu và mã tham chiếu\n\n' + '\n'.join(lines))


def chapter_one():
    return [md(r"""
    # 1. Discovery, tổ chức dữ liệu và phạm vi đánh giá

    ## 1.1 Bài toán và đơn vị xử lý

    Đầu vào của crawler là khoảng ID do lớp cấp. Pipeline phân giải metadata của từng paper,
    xác định số revision rồi tải từng nguồn theo version. Một paper là đơn vị thống kê metadata;
    một cặp `(paper, version)` là đơn vị kiểm toán nguồn và parsing. Hai đơn vị này không được
    dùng thay nhau khi tính tỷ lệ thành công.

    Metadata, nguồn và references được lưu thành các lớp riêng. `publications` giữ các version
    và trạng thái nguồn; `references` giữ cạnh thu được; sidecar ghi trạng thái truy vấn.
    M2 tiêu thụ chính các version của M1 và tạo manifest kể cả khi một version empty hoặc lỗi.

    ## 1.2 Luồng dữ liệu

    Sơ đồ dưới đây minh họa kiến trúc chương trình, không phải biểu đồ hiệu năng đo được.
    """), code(COMMON), code("""
    from matplotlib.patches import FancyBboxPatch
    labels = ['Assigned IDs', 'Atom metadata', 'Versioned sources', 'References + checkpoint', 'M1 tables', 'Parser + M2 tables']
    fig, ax = plt.subplots(figsize=(12, 2.4)); ax.set_xlim(0, 12); ax.set_ylim(0, 2); ax.axis('off')
    for i, label in enumerate(labels):
        x = i * 2
        ax.add_patch(FancyBboxPatch((x + .08, .55), 1.75, .85, boxstyle='round,pad=0.06', facecolor='#e8f1fa', edgecolor='#2e5979'))
        ax.text(x + .95, .98, label.replace(' ', '\\n', 1), ha='center', va='center', fontsize=9)
        if i < len(labels)-1: ax.annotate('', xy=(x+2.02, .98), xytext=(x+1.84, .98), arrowprops={'arrowstyle':'->'})
    plt.tight_layout(); plt.show()
    """), md(r"""
    ## 1.3 Phân giải ID và revision

    API được gọi theo danh sách ID thay vì thu thập toàn bộ repository. Crawler đọc ID có suffix
    revision trong Atom để dựng danh sách `v1…vN`. Ngày `published` dùng cho v1, `updated` chỉ là
    bằng chứng trực tiếp cho revision tương ứng. Các ngày trung gian chưa biết được giữ null;
    công cụ bổ sung lịch sử có thể dùng snapshot/OAI có provenance.

    Thuật toán không tự gán v1 khi thiếu bằng chứng version. Một ID vắng khỏi một feed được giữ
    ở diện cần xác minh, tránh biến phản hồi thiếu thành kết luận paper không tồn tại.

    ```text
    resolve(batch_IDs)
      parse Atom entries and reject service error entries
      for each valid entry: validate ID/version and retain known timestamps
      for each unresolved ID: keep a retry/verification state
      persist metadata before expensive source work
    ```

    ## 1.4 Cách chọn snapshot cho báo cáo

    Báo cáo dùng tám archive Drive gần nhất dưới ngưỡng 8 MiB trong lượt liệt kê đã chốt.
    Archive và checkpoint được đối chiếu hash, từng file được kiểm tra với manifest trước
    khi giải nén vào thư mục làm việc riêng. Không tải toàn bộ parent chain.

    Đây là mẫu thuận tiện, chịu thiên lệch bởi thời điểm, kích thước archive và các paper đang
    được retry. Kết quả chỉ mô tả tập này; không ước lượng tỷ lệ thành công hay thời gian cho
    toàn bộ dải bằng phép nhân tuyến tính. Counter checkpoint lớn hơn được trình bày để theo
    dõi tiến độ, không được dùng thay số nguồn đã audit trong snapshot.
    """), code("""
    display(pd.DataFrame([
        {'phạm_vi': 'Snapshot được phân tích', 'paper': scope['papers']},
        {'phạm_vi': 'Dải của một thành viên', 'paper': scope['member_assigned']},
        {'phạm_vi': 'Toàn nhóm được giao', 'paper': scope['group_assigned']},
        {'phạm_vi': 'Counter checkpoint, chưa restore toàn chuỗi', 'paper': scope['checkpoint_reported_ids']},
    ]))
    hist = pd.Series({int(k):v for k,v in m1['version_histogram'].items()}).sort_index()
    display(hist.rename_axis('versions_per_paper').to_frame('papers'))
    hist.plot.bar(xlabel='Số version/paper', ylabel='Số paper', title='Phân bố số version trong snapshot')
    plt.tight_layout(); plt.show()
    display(pd.Series(m1['metadata_missing_fraction'], name='missing_fraction').to_frame())
    display(Markdown(f"Snapshot phủ **{scope['papers']/scope['group_assigned']:.3%}** số paper được giao cho nhóm; "
                     f"trung bình **{scope['versions']/scope['papers']:.2f} version/paper**. "
                     f"Có **{m1.get('missing_version_dates', 'chưa tổng hợp')}** ngày version chưa được xác minh."))
    """), md(r"""
    ## 1.5 Nhận xét

    Metadata title, authors và submission time được đánh giá theo trường bắt buộc của pipeline.
    DOI hoặc venue thiếu có thể do thông tin chưa được cung cấp; không tự xem chúng là lỗi
    tải source. Ngày revision thiếu cần được bổ sung có bằng chứng, thay vì sao chép ngày latest.
    Bảng phân bố version cho biết tải theo paper không đồng nghĩa số request nguồn bằng số paper.

    Trong báo cáo công khai, nhãn P001… chỉ phục vụ coverage. Bảng mã và dữ liệu gốc được nhóm
    giữ riêng; các con số trong Book được tạo lại từ file tổng hợp khi compilation.
    """), references('M1', ('src/crawler/id_range.py','src/crawler/discovery.py','src/crawler/version_history.py','tools/prepare_submission_snapshot.py'))]


def chapter_two():
    return [md(r"""
    # 2. Tải, lọc và kiểm toán nguồn

    ## 2.1 Tải riêng từng version

    Downloader gọi endpoint `/src/<paper>vN` trên mirror export. Tên đích gắn với revision đã
    yêu cầu; không tải latest rồi gán nội dung đó vào một version cũ. Mặc định source và metadata
    chờ 3 giây giữa các request arXiv; số đo lịch sử vẫn ghi đúng cấu hình của lượt lịch sử đó.

    Kết nối được tái sử dụng nhưng các lượt truyền source được tuần tự hóa. Archive tải mới
    được đọc theo luồng. Khi có `.part`, Range request tiếp tục từ byte đã có và phải khớp
    `Content-Range`; khi phản hồi không thể ghép an toàn, chương trình không nối mù hai phần.
    Resume dùng đoạn tăng dần 1–4–8 MiB khi ổn định và giảm lại khi lỗi.

    ## 2.2 Nhận diện và giữ nội dung

    Phản hồi không phải lúc nào cũng là tar.gz. Chương trình kiểm tra dạng tar, gzip, TeX hoặc
    PDF bằng nội dung. Corpus làm việc chỉ giữ file `.tex` và `.bib`, không chỉnh câu lệnh
    figure trong TeX. Vì vậy M2 vẫn nhận diện được vị trí figure/table dù binary ảnh đã bị loại.

    Việc giải nén đi qua staging, kiểm tra đường dẫn và symlink, rồi mới thay nguồn cũ sau khi
    kết quả mới hợp lệ. Nếu tải hoặc giải nén lỗi, trạng thái lỗi và phần có thể resume được giữ.

    | Trạng thái version | Bằng chứng và cách dùng |
    |---|---|
    | success | Có TeX, file đúng allowlist và dung lượng khớp record khi audit |
    | pdf_only / no_latex | Có manifest xác nhận loại nguồn; M2 ghi empty |
    | error / pending / chưa biết | Cần retry hoặc xác minh; không chuyển thành empty |

    ## 2.3 Audit độc lập

    Audit không chỉ đọc counter `success`: nó tìm đúng thư mục version, đếm TeX/Bib, kiểm tra
    file ngoài allowlist, đối chiếu size và manifest của các trường hợp empty. Những version
    không đạt được đưa vào retry manifest. Dưới đây là kết quả trên snapshot hiện tại.
    """), code(COMMON), code("""
    audit = pd.Series(m1['source_audit'], name='versions')
    display(audit.to_frame())
    audit.plot.bar(title='Kết quả audit nguồn', ylabel='Số version'); plt.tight_layout(); plt.show()
    rates = pd.DataFrame([
        {'metric':'TeX đã xác minh / mọi version', 'numerator':m1['source_audit'].get('tex_verified',0), 'denominator':scope['versions']},
        {'metric':'Nguồn hợp lệ gồm empty / mọi version', 'numerator':m1['source_verified'], 'denominator':scope['versions']},
        {'metric':'Paper có mọi nguồn đã xác minh', 'numerator':m1.get('papers_with_all_sources_verified'), 'denominator':scope['papers']},
        {'metric':'Paper đủ nguồn và có S2 success/empty', 'numerator':m1.get('papers_with_sources_and_s2_verified'), 'denominator':scope['papers']},
    ])
    rates['ratio'] = rates['numerator'] / rates['denominator']; display(rates)
    """), md(r"""
    ## 2.4 Kích thước trước và sau lọc

    Gọi \(E\) là tập paper có mọi version TeX đã được audit. Với mỗi paper, cộng byte của các
    version trước khi lấy trung bình. Cả hai trung bình dùng cùng tập \(E\):

    \[
    \overline{B}_{\mathrm{before}}=\frac{\sum_{p\in E}\sum_v B_{p,v,\mathrm{before}}}{|E|},\qquad
    \overline{B}_{\mathrm{after}}=\frac{\sum_{p\in E}\sum_v B_{p,v,\mathrm{after}}}{|E|}.
    \]

    Tỷ lệ giảm byte được tính từ hai tổng trên cùng tập. `before` là byte nội dung giải nén
    trước lọc, không phải byte archive nén hoặc dung lượng mạng thực truyền. `after` là byte
    TeX/Bib được giữ. Tỷ lệ giảm này mô tả lọc nội dung, không mô tả tỷ lệ nén gzip.
    """), code("""
    sizes = pd.DataFrame([{'eligible_papers':m1['eligible_size_papers'],
                          'mean_before_bytes':m1['mean_before_bytes'], 'mean_after_bytes':m1['mean_after_bytes'],
                          'reduction_fraction':m1['source_reduction']}]); display(sizes)
    pd.Series({'Before filtering':m1['mean_before_bytes'], 'TeX/Bib retained':m1['mean_after_bytes']}).plot.bar(
        ylabel='Byte/paper đủ điều kiện', title='Kích thước trung bình trên cùng tập paper')
    plt.tight_layout(); plt.show()
    display(Markdown(f"Trên **{m1['eligible_size_papers']} paper** đủ điều kiện, byte giữ lại giảm "
                     f"**{m1['source_reduction']:.2%}**. Version empty và paper còn lỗi không nằm trong mẫu số này."))
    """), md(r"""
    ## 2.5 Resume, Drive backup và phần còn thiếu

    Trên Colab, source và shard làm việc ở `/content`; archive backup đã xác minh được sao lưu
    theo lô lên Drive. Checkpoint ghi nhận các part đã commit. Khi restore, cần kiểm tra hash và
    chuỗi generation trước khi xem một workspace là bản khôi phục toàn bộ. Snapshot của báo
    cáo chỉ dùng một số lô, nên được ghi rõ là khôi phục một phần.

    Mỗi checkpoint/backup chỉ có một runtime ghi. `LocalMutex` chỉ điều phối các tiến trình
    trên cùng máy, không tạo khóa phân tán giữa nhiều Colab. Bổ sung số runtime không thay cho
    việc tuân thủ giới hạn request chung hoặc bảo vệ checkpoint.

    Version nguồn còn lỗi giữ nguyên trong danh sách cần xử lý. Không tải thêm toàn dải trong
    lần chuẩn bị báo cáo này; dữ liệu nguồn của snapshot được giữ để M2 xử lý và đối chiếu.
    """), references('M1', ('src/crawler/source_downloader.py','src/crawler/validate_sources.py','src/crawler/retry_sources.py','src/crawler/drive_backup.py'))]


def chapter_three():
    return [md(r"""
    # 3. Thu thập references và độ phủ metadata

    ## 3.1 Truy vấn và ghép kết quả

    S2 batch nhận danh sách paper ID; kết quả được gắn lại bằng `externalIds.ArXiv`, không chỉ
    dựa vào vị trí trả về. Entry null, thiếu hoặc trùng định danh được kiểm tra riêng. Danh sách
    references được đối chiếu với `referenceCount`; khi thiếu, crawler lấy thêm trang và vẫn
    giữ trạng thái partial nếu chưa thu đủ. Batch quá lớn được chia nhỏ thay vì lặp toàn bộ.

    Working data giữ các references đã thu được, gồm cả tài liệu không có arXiv ID. Course
    export chỉ giữ cạnh có đích arXiv. Số dòng của hai lớp vì vậy có thể khác nhau mà không phải
    merger làm mất cạnh hợp lệ theo schema công bố.

    ## 3.2 Ý nghĩa trạng thái

    | Trạng thái | Ý nghĩa thống kê |
    |---|---|
    | success | S2 trả references đã đối chiếu số kỳ vọng |
    | empty | S2 xác nhận referenceCount bằng 0 |
    | partial / unavailable | Chưa có danh sách đầy đủ hoặc phản hồi bất thường |
    | not_indexed | Không có record S2 tương ứng ở lần kiểm tra |
    | bib_fallback | Có thông tin từ nguồn BibTeX, không mặc định là cạnh S2 |
    | api_error | Truy vấn thất bại hoặc đang bị hoãn; không suy ra danh sách rỗng |

    Cạnh trích dẫn và metadata của tài liệu được trích có provenance riêng. Việc bổ sung được
    S2 ID cho một reference fallback không chứng minh S2 đã trả cạnh citing → reference đó.
    Ngày không được tạo từ trường year. Publication date của S2 cũng không tự động chứng minh
    ngày submission trên arXiv.

    ## 3.3 Retry và hạn mức

    Crawler tôn trọng `Retry-After`, ghi cooldown để giữ qua restart và giới hạn số lần thử.
    Khi S2 đang cooldown, phần chỉ còn lỗi references được hoãn để tránh ghi lặp cùng trạng
    thái, trong khi nguồn chưa đủ vẫn cần được xử lý. Không biến API error thành thành công
    để rút ngắn hàng đợi. Các batch dùng chung request được gắn request group để không tính
    một POST thành nhiều HTTP request khi tổng hợp theo paper.
    """), code(COMMON), code("""
    statuses = pd.Series(m1['reference_status'], name='papers'); display(statuses.to_frame())
    statuses.plot.bar(title='Kết quả references theo paper', ylabel='Số paper'); plt.tight_layout(); plt.show()
    n_verified = m1['verified_reference_papers']
    display(pd.DataFrame([{'scope':'S2 success/empty', 'papers':n_verified, 'fraction':n_verified/scope['papers']},
                          {'scope':'API error/chưa đủ bằng chứng', 'papers':scope['papers']-n_verified,
                           'fraction':1-n_verified/scope['papers']}]))
    display(pd.DataFrame([{'working_reference_rows':m1['working_reference_rows'],
                          'course_arxiv_edges':m1['arxiv_reference_rows'],
                          'mean_on_verified_papers':m1['mean_references_verified_papers']}]))
    """), md(r"""
    ## 3.4 Công thức và mẫu số

    Tỷ lệ paper có kết quả API đã xác minh là
    \((N_{\mathrm{success}}+N_{\mathrm{empty}})/N_{\mathrm{paper}}\).
    References trung bình chỉ dùng tập \(Q\) có `success/empty`:
    \(\overline{R}=\sum_{p\in Q}R_p/|Q|\). Empty đã xác minh đóng góp 0; API error không đóng góp
    0 vào trung bình. Trung bình có điều kiện này cũng không được suy ra cho toàn bộ nhóm.

    Bản snapshot không tải toàn parent chain, nên có thể thiếu cạnh cũ không nằm trong các
    lô được chọn. Các trường thiếu dưới đây mô tả các dòng thực sự có trong snapshot,
    không mô tả toàn bộ references của các paper còn lỗi.
    """), code("""
    missing = pd.Series(m1['references_missing_fraction'], name='missing_fraction')
    display(missing.to_frame())
    missing.plot.bar(ylim=(0,1), ylabel='Tỷ lệ thiếu', title='Metadata thiếu trên working references đã có')
    plt.tight_layout(); plt.show()
    display(Markdown(f"Có **{n_verified}/{scope['papers']} paper ({n_verified/scope['papers']:.2%})** có kết quả S2 đã xác minh. "
                     f"Trung bình có điều kiện là **{m1['mean_references_verified_papers']:.2f} references/paper**. "
                     'Không dùng số dòng hiện có chia cho mọi paper như một ước lượng đầy đủ.'))
    """), md(r"""
    ## 3.5 Phân tích và bước hoàn thiện

    Độ phủ references là điểm chưa hoàn tất đáng kể của snapshot. Cần truy vấn lại các paper
    lỗi theo giới hạn dịch vụ, kiểm tra phân trang và lưu trạng thái cùng lần đo. Khi đủ nguồn,
    đối chiếu bibliography giúp phát hiện thông tin thiếu, nhưng không thay thế tùy tiện yêu
    cầu thu thập metadata từ S2. Báo cáo hiện giữ rõ sự khác nhau giữa nguồn đã audit tốt và
    references đã thu đủ; không dùng số paper có TeX làm số paper crawling hoàn tất.
    """), references('M1', ('src/crawler/reference_scraper.py','src/crawler/reference_batch.py','src/crawler/enrich_references.py','src/crawler/observations.py'))]


def chapter_four():
    return [md(r"""
    # 4. Mô hình dữ liệu và validation

    ## 4.1 Working data và năm bảng

    Working publications giữ metadata và trạng thái nguồn theo version. Working references
    giữ các cạnh đã thu được; sidecar giữ trạng thái truy vấn. Từ đó M1 xuất hai bảng `papers`
    và `references`. M2 tạo `elements`, `hierarchy`, `bibtex` cùng manifest để theo dõi version.

    Khóa paper được chuẩn hóa về base ID. Revision vẫn được giữ ở cấu trúc versions và cột
    version của hierarchy. Target reference không bắt buộc thuộc dải nhóm; chỉ citing paper
    phải có trong papers. Null ở metadata không được chuyển thành một giá trị giả để qua kiểm tra.

    ## 4.2 Schema

    Hai bảng M1 được ghi dưới đây từ thống kê schema đã kiểm tra. Schema M2 được đọc trực tiếp
    từ phiên bản source ghim cho các ví dụ thực thi của Book.
    """), code(COMMON), code("""
    for name, rows in m1['schemas'].items():
        print(name); display(pd.DataFrame(rows))
    from parser.storage import SCHEMAS
    for name, schema in SCHEMAS.items():
        print(name)
        display(pd.DataFrame([{'column':f.name,'type':str(f.type),'nullable':f.nullable} for f in schema]))
    """), md(r"""
    ## 4.3 Các invariant được kiểm tra

    - `papers`: ID không rỗng, không trùng; metadata và ngày đúng kiểu schema.
    - `references`: cặp citing/target hợp lệ, không trùng khóa sau gộp; citing ID thuộc papers.
    - `elements`: element ID và paper key hợp lệ, không trùng ID.
    - `hierarchy`: node và parent tồn tại trong store của paper, không self-edge hoặc cycle;
      mỗi graph version có đúng một root dạng document.
    - `bibtex`: citation key không rỗng, không trùng trong paper; metadata có kiểu đúng.
    - Manifest M2: version không trùng, thuộc phạm vi working M1 và khớp run parser; version
      không có TeX chỉ được ghi empty khi M1 đã có bằng chứng tương ứng.

    Validator dùng đọc Parquet theo batch và index trên đĩa để đối chiếu khóa xuyên shard.
    Cách này giảm nhu cầu giữ full text toàn corpus trong RAM. Đĩa tạm của validation thuộc
    phạm vi đo nếu profiler đang theo dõi thư mục chứa nó.

    ## 4.4 Kết quả trên snapshot
    """), code("""
    rows = [{'table':'papers','rows':scope['papers']}, {'table':'references','rows':m1['arxiv_reference_rows']}]
    rows += [{'table':key,'rows':value} for key,value in m2['rows'].items()]
    display(pd.DataFrame(rows))
    display(pd.DataFrame([{'structural_valid':m2['structural_valid'], 'processing_complete':m2['processing_complete'],
                          'expected_versions':scope['versions'], 'recorded_versions':sum(x['recorded_versions'] for x in m2['coverage'])}]))
    print('Các kiểm tra cấu trúc đã qua không chứng minh source/reference hoặc parser đều hoàn tất.')
    """), md(r"""
    ## 4.5 Merge, bảo toàn version và tái lập

    Merge dùng base ID rồi hợp nhất theo version tag, tránh chọn một record mới mà bỏ các
    version cũ. References dùng các định danh có thể xác minh và giữ xung đột để kiểm tra.
    Một shard thiếu stats có thể cung cấp dữ liệu, nhưng không được tự cấp runtime/RAM.

    Kết quả hiện tại hợp lệ về cấu trúc trên snapshot. `processing_complete=false` vẫn được
    giữ vì có partial/error. Khi nhận dữ liệu mới, cần chạy lại source audit, export và
    validation sau parser, thay vì chỉ sửa giá trị boolean trong báo cáo.
    """), references('M2', ('src/crawler/storage.py','src/crawler/records.py','src/crawler/merge_shards.py','src/parser/storage.py','src/parser/validation.py'))]


def chapter_five():
    return [md(r"""
    # 5. Thời gian và tài nguyên crawler

    ## 5.1 Thiết kế phép đo và phạm vi

    Số đo M1 được giữ từ một lượt Colab CPU-only đã lưu. Lượt đó có dải cấu hình 5.000 ID,
    thực sự xử lý 14 paper trong khoảng đo rồi tạm dừng vì rate limit. Nó không phải lượt
    crawling lại snapshot 73 paper, cũng không chứng minh đã hoàn tất toàn dải.

    Runtime profiler đo các pha được theo dõi. Child wall đo tiến trình con đến lúc kết thúc;
    phạm vi có thể gồm thêm bước ghi output sau khi profiler dừng. Thời gian cell validation
    bên ngoài tiến trình không tự được tính vào child wall.

    ## 5.2 Môi trường và cấu hình thực tế
    """), code(COMMON), code("""
    run = data['crawler_measurement']
    display(pd.Series(run['environment'], name='value').to_frame())
    display(pd.DataFrame([{k:run[k] for k in ['status','runtime_sec','child_wall_sec','processed_papers','assigned_ids']}]))
    display(pd.Series(run['intervals'], name='seconds').to_frame())
    print('Các interval trên là cấu hình lịch sử, không phải mặc định hiện tại của source.')
    """), md(r"""
    ## 5.3 Thời gian theo pha

    Với tập paper thực sự xử lý trong run, trung bình profiler/paper là
    \(\overline{T}=T_{\mathrm{profiler}}/N_{\mathrm{processed}}\). Khi có child wall, có thể trình bày
    thêm \(T_{\mathrm{child}}/N_{\mathrm{processed}}\) và ghi rõ phạm vi. Không chia thời gian run cho
    toàn bộ ID được giao hoặc toàn bộ record checkpoint cũ.

    Các phase phản ánh instrumentation thực tế. Nếu có phase lồng nhau hoặc phần overhead
    ngoài phase, tổng phase không nhất thiết bằng wall time. Không diễn giải chênh lệch đó
    thành thời gian CPU hoặc I/O mà chưa có phép đo tương ứng.
    """), code("""
    phases = pd.DataFrame(run['phases']).T; display(phases)
    phases['elapsed_sec'].sort_values().plot.barh(xlabel='Giây', title='Thời gian pha trong lượt Colab đã lưu')
    plt.tight_layout(); plt.show()
    display(pd.DataFrame([{'profiler_sec_per_processed_paper':run['runtime_sec']/run['processed_papers'],
                          'child_wall_sec_per_processed_paper':run['child_wall_sec']/run['processed_papers'],
                          'wall_scope_difference_sec':run['child_wall_sec']-run['runtime_sec']}]))
    display(Markdown(f"Pha references chiếm **{run['phases']['references']['elapsed_sec']/run['runtime_sec']:.1%}** "
                     'runtime profiler của lượt này. Đây là bằng chứng về chi phí references trong run đã đo, '
                     'không đủ để dự báo thời gian của toàn corpus.'))
    """), md(r"""
    ## 5.4 RAM và dung lượng đĩa

    Profiler lấy mẫu RSS của tiến trình chính và các tiến trình con tại cùng thời điểm.
    RAM trung bình dùng trọng số theo khoảng thời gian giữa các mẫu, thay vì cộng peak riêng
    của từng process. Đơn vị MB trong stats tương ứng \(1024^2\) byte.

    Peak disk là cực đại trong các lần lấy mẫu và checkpoint thao tác trên thư mục được theo
    dõi, không phải một cận trên tuyệt đối của mọi byte tồn tại. Final disk gồm working data
    và checkpoint thuộc phạm vi đo. Backup Drive hoặc log ngoài phạm vi theo dõi phải được
    tính riêng nếu muốn trình bày dung lượng toàn hệ thống.
    """), code("""
    display(pd.Series(run['memory'], name='RAM').to_frame())
    disk = dict(run['disk'])
    for field in ['peak_bytes','final_bytes']:
        disk[field.replace('_bytes','_MiB')] = disk[field]/1024**2
    display(pd.Series(disk, name='disk').to_frame())
    """), md(r"""
    ## 5.5 Diễn giải và điều chỉnh

    Request limit, phân trang, kích thước archive, cache và retry khiến chi phí giữa các paper
    khác nhau. Tăng batch metadata/S2 giảm số lượt gọi ở những chỗ phù hợp; nó không loại bỏ
    thời gian tải từng version và không bảo đảm tốc độ tăng cùng tỷ lệ.

    Lượt lưu có interval source 1 giây. Source mới mặc định 3 giây theo cấu hình đã điều chỉnh;
    số đo cũ vẫn giữ nguyên 1 giây. Muốn so sánh hai cấu hình cần chạy các lượt thật có scope,
    input và cache được công bố. Không sửa log để biến một cấu hình thành cấu hình khác.
    """), references('M1', ('src/crawler/profiler.py','src/crawler/main.py','src/crawler/request_policy.py','colab_crawler.ipynb'))]


def chapter_six():
    return [md(r"""
    # 6. Gathering và dựng hierarchy theo version

    ## 6.1 Chọn compilation root

    Parser đọc các file TeX và tìm root có `documentclass/documentstyle`. Nếu chỉ có một ứng viên,
    root đó được dùng. Khi nhiều ứng viên, cấu hình override chỉ được thêm sau đối chiếu nội dung
    title và vai trò main/supplementary/template. Trường hợp chưa đủ bằng chứng vẫn báo lỗi.

    Gathering duyệt `input/include` theo thứ tự, bỏ comment và phát hiện cycle hoặc đường dẫn
    thoát thư mục version. Input thông thường được tìm từ thư mục biên dịch; nếu không tồn tại,
    triển khai còn thử đường dẫn tương đối của file con để tương thích một số bố cục nguồn.
    File không được include không thuộc compilation path. Parser không chạy TeX hoặc giải mã
    mọi macro như một trình biên dịch đầy đủ.

    ## 6.2 Quy tắc hierarchy

    Section stack xác định parent theo mức chapter/section/subsection. List và item tạo các
    container riêng. Paragraph được chia tại dòng trống ngoài nhóm/lệnh TeX và toán; câu được
    chia ở dấu kết thúc phù hợp, có bảo vệ command, URL, số thập phân và một số viết tắt.
    Block math và figure/table là leaf riêng. Acknowledgements và appendix được giữ; bibliography
    được tách khỏi hierarchy để xử lý references.

    Source map liên kết khoảng ký tự trong bản gathered với file và dòng gốc. Thông tin này
    giúp đối chiếu khi một version partial; cây có cấu trúc hợp lệ vẫn có thể thiếu nội dung
    do cú pháp chưa được hỗ trợ.

    ## 6.3 Ví dụ thực thi từ source ghim

    Ví dụ sau là TeX **tổng hợp để minh họa**, không phải nội dung hay số liệu từ corpus.
    Nó chạy chính các hàm gathering/hierarchy của code repository, không gọi API.
    """), code(COMMON), code(r'''
    import tempfile
    from parser.gather import gather
    from parser.hierarchy import parse_hierarchy
    main = r"""\documentclass{article}
    \title{Illustrative document}
    \begin{document}
    \input{sections/body}
    \section*{Acknowledgements}
    We thank the example team.
    \appendix
    \section{Additional detail}
    The appendix is retained.
    \begin{thebibliography}{9}
    \bibitem{demo} A. Example. A sample title. 2020.
    \end{thebibliography}
    \end{document}
    """
    body = r"""\section{Introduction}
    First sentence. See Fig. 1. The value is $1.5$.
    \begin{itemize}\item First point.\item Second point.\end{itemize}
    \input{tables/result}
    \begin{equation}x+y=1\end{equation}
    \begin{figure}\caption{Illustrative figure.}\end{figure}
    """
    table = r"\begin{table}\caption{Illustrative table.}\end{table}"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); (root/'sections').mkdir(); (root/'tables').mkdir()
        (root/'main.tex').write_text(main,encoding='utf-8')
        (root/'sections/body.tex').write_text(body,encoding='utf-8')
        (root/'tables/result.tex').write_text(table,encoding='utf-8')
        (root/'unused.tex').write_text('This file is not included.',encoding='utf-8')
        gathered = gather(root); tree = parse_hierarchy(gathered.text)
        print('Compilation path:',gathered.files)
        print('Diagnostics:',gathered.diagnostics + tree.diagnostics)
        display(pd.DataFrame([{'node':n.node_id,'parent':n.parent_id,'kind':n.kind,'content':n.content[:100]} for n in tree.nodes]))
    '''), md(r"""
    ## 6.4 Kết quả trên snapshot và các sửa đổi đã đối chiếu

    Bảng trước/sau bên dưới, nếu có, dùng hai lượt parser trên cùng input snapshot. Các thay đổi
    gồm sửa cách tìm include từ compilation directory và cấu hình root cho những ca đã đối chiếu.
    So sánh này chứng minh tác động đến trạng thái xử lý trên tập đã biết; không phải thí nghiệm
    lặp độc lập để kết luận tốc độ hoặc khả năng tổng quát cho toàn arXiv.
    """), code("""
    status = pd.Series(m2['status_counts'],name='versions'); display(status.to_frame())
    if m2.get('before_fixes_status'):
        comparison = pd.DataFrame({'Trước sửa':m2['before_fixes_status'],'Sau sửa':m2['status_counts']}).fillna(0).astype(int)
        display(comparison)
        comparison.plot.bar(title='Trạng thái trước/sau trên cùng snapshot',ylabel='Số version'); plt.tight_layout(); plt.show()
    tex = m2.get('versions_with_tex',scope['versions']-m2['status_counts'].get('empty_no_tex',0)-m2['status_counts'].get('error_missing_source',0))
    success = m2['status_counts'].get('success',0); partial = m2['status_counts'].get('partial',0)
    display(pd.DataFrame([
        {'metric':'Recorded / expected','value':sum(r['recorded_versions'] for r in m2['coverage'])/scope['versions']},
        {'metric':'Success / all versions','value':success/scope['versions']},
        {'metric':'Success / versions with TeX','value':success/tex},
        {'metric':'Success + partial / versions with TeX','value':(success+partial)/tex},
    ]))
    """), md(r"""
    ## 6.5 Coverage từng publication

    Nhãn P001…P073 là nhãn công khai cho bảng coverage, không phải arXiv ID. `recorded_versions`
    bao gồm success, partial, empty và error. `parsed_version_coverage` tính success + partial;
    `successful_version_coverage` chỉ tính success. Version empty có bằng chứng là một kết quả
    hợp lệ của pipeline nhưng không có parsed elements.
    """), code("""
    columns=['paper','expected_versions','recorded_versions','versions_with_tex','success_versions',
             'partial_versions','empty_versions','error_versions','parsed_version_coverage','successful_version_coverage']
    with pd.option_context('display.max_rows',None,'display.max_columns',None):
        display(pd.DataFrame(m2['coverage'])[columns])
    diag = pd.Series(m2['diagnostic_categories'],name='versions_with_diagnostic')
    display(diag.to_frame())
    diag.plot.barh(title='Nhóm diagnostic — một version có thể có nhiều nhóm',xlabel='Số version')
    plt.tight_layout(); plt.show()
    """), md(r"""
    ## 6.6 Các giới hạn còn lại

    Missing bibliography, include động và môi trường tự định nghĩa vẫn có thể làm version
    partial. Một version còn nhiều root cùng title được giữ lỗi thay vì đoán theo tên hoặc
    kích thước file. Một version còn thiếu nguồn được ghi `error_missing_source`.
    Việc có manifest cho mọi version chỉ xác nhận khả năng theo dõi trạng thái, không chứng
    minh parser đã tái hiện đầy đủ mọi nội dung biên dịch.
    """), references('M2', ('src/parser/gather.py','src/parser/latex.py','src/parser/hierarchy.py','src/parser/main.py','configs/submission_parser_roots_20261106.json'))]


def chapter_seven():
    return [md(r"""
    # 7. Chuẩn hóa, hợp nhất references và khử trùng

    ## 7.1 Chuẩn hóa nội dung

    Normalizer bỏ các wrapper trình bày trong tập đã hỗ trợ, giữ nội dung bên trong và chuẩn
    hóa whitespace/Unicode NFC. Inline math đưa về `$…$`, block math về môi trường equation.
    Các đoạn text trong toán và literal được bảo vệ để tránh xóa khoảng trắng có ý nghĩa.
    Những lệnh chưa biết không bị xóa mù, nên một số cú pháp vẫn còn trong content chuẩn hóa.

    Citation key được đổi bằng mapping của từng version, kể cả cite nằm trong toán.
    Chuẩn hóa là thao tác trên chuỗi TeX, không phải chứng minh hai biểu thức toán tương đương.
    """), code(COMMON), code(r'''
    from parser.normalize import normalize
    examples = [r"\textbf{Shared} text with \(x + y\).", r"\centering Shared text with $x+y$."]
    display(pd.DataFrame([{'illustrative_raw':text,'normalized':normalize(text)} for text in examples]))
    '''), md(r"""
    ## 7.2 Trích và hợp nhất BibTeX

    Entries được lấy từ bibliography thuộc compilation path và các bibitem trong TeX.
    Bibitem được phân tích thành trường có thể xác định; không tự điền DOI/year khi không có
    bằng chứng. Parser BibTeX giữ `%` trong giá trị hoặc URL, phân biệt với comment bên ngoài.

    Hợp nhất ưu tiên định danh mạnh có thể nhận diện, sau đó dùng chữ ký title/author khi
    không có mâu thuẫn year/DOI. Nếu chưa có nhận diện đủ tin cậy, entry không bị gộp chỉ vì
    key giống nhau. Field mới bổ sung vào bản hợp nhất; giá trị mâu thuẫn được ghi riêng,
    không tùy tiện ghi đè để làm mất thông tin.

    Ví dụ sau dùng entries tổng hợp. Version 1 có year, version 2 thêm DOI và dùng key khác.
    Kết quả cho thấy field union và mapping được tạo bởi code thực thi.
    """), code(r'''
    from parser.bibliography import parse_bibtex, unify_entries
    entries = parse_bibtex('@article{first,title={Sample reference},author={A. Example},year={2020}}',1)
    entries += parse_bibtex('@article{second,title={Sample reference},author={A. Example},doi={10.0000/demo}}',2)
    rows, mappings, conflicts = unify_entries('demo',entries)
    display(pd.DataFrame(rows).drop(columns=['arxiv_id']))
    print('Citation mapping:',mappings)
    print('Normalized cite, version 2:',normalize(r'We cite \cite{second}.',mappings[2]))
    print('Conflicts:',conflicts)
    '''), md(r"""
    ## 7.3 Content store dùng chung giữa các version

    Lookup dùng cặp `(kind, normalized_content)`. Nội dung chuẩn hóa giống hệt và cùng kind
    được lưu một lần; ID được tạo ổn định từ nội dung và paper key. Các occurrence vẫn giữ
    node gốc, version và vị trí. Bảng hierarchy lưu cạnh riêng cho từng version, nên một
    sentence dùng chung có thể nằm dưới hai heading khác nhau.

    Không gộp hai publication với nhau. Không dùng fuzzy matching, embedding hoặc độ tương
    đồng xấp xỉ để quyết định content dedup của milestone này. Mọi self-edge phát sinh do
    gộp cấu trúc phải bị phát hiện, không được lặng lẽ xóa để validator đi qua.

    Ví dụ tổng hợp dưới đây có một câu dùng chung nhưng heading đổi giữa hai version.
    """), code(r'''
    from parser.hierarchy import parse_hierarchy
    from parser.deduplicate import deduplicate
    first = r"\documentclass{article}\title{Demo}\begin{document}\section{Background}Shared sentence.\end{document}"
    second = r"\documentclass{article}\title{Demo}\begin{document}\section{Method}Shared sentence. New sentence.\end{document}"
    trees={1:parse_hierarchy(first),2:parse_hierarchy(second)}
    elements,edges,occurrences=deduplicate('demo',trees,{})
    aliases={row['element_id']:f'E{i:02d}' for i,row in enumerate(elements,1)}
    display(pd.DataFrame([{'element':aliases[r['element_id']],'kind':r['kind'],'content':r['content']} for r in elements]))
    display(pd.DataFrame([{'version':r['version'],'element':aliases[r['element_id']],'parent':aliases[r['parent_id']]} for r in edges]))
    print('Occurrences trước dedup:',sum(len(t.nodes) for t in trees.values()),'; store sau dedup:',len(elements))
    '''), md(r"""
    ## 7.4 Kết quả và công thức

    Với mỗi loại store, tỷ lệ giảm là \((N_{before}-N_{after})/N_{before}\).
    Before-counts lấy từ version có đo được; after-counts là số row store của các paper đã
    xử lý. Các version chưa parse được không được tự cấp before-counts bằng một số ước lượng.
    """), code("""
    dedup=pd.DataFrame(m2['deduplication']).T
    dedup['removed']=dedup['before']-dedup['after']; display(dedup)
    dedup[['before','after']].plot.bar(title='Counts trước/sau dedup trên phần đã đo')
    plt.tight_layout(); plt.show()
    print('Version chưa đo before-counts:',m2.get('versions_with_unmeasured_counts'))
    print('Tổng unresolved citation keys theo version:',m2['unresolved_cites'])
    print('Bibliography field conflicts ghi nhận:',m2['bibliography_conflicts'])
    display(Markdown(f"Elements giảm **{m2['deduplication']['elements']['reduction_rate']:.2%}**; "
                     f"BibTeX entries giảm **{m2['deduplication']['bibtex']['reduction_rate']:.2%}** trên phần kết quả đã đo."))
    """), md(r"""
    ## 7.5 Diễn giải

    Giảm số dòng cho thấy nội dung giữa các version có thể dùng chung store; nó không tự
    chứng minh kết quả đúng ngữ nghĩa hay toàn bộ references đã có. Unresolved keys được
    đếm theo version nên cùng một key còn thiếu ở hai version đóng góp hai lần. Field conflict
    là số sự kiện mâu thuẫn được ghi nhận, không phải số publication lỗi.

    Cần đọc các ca partial, đối chiếu nguồn bibliography và kiểm tra những key cùng tên
    trỏ tới nội dung khác nhau. Đó là phần hoàn thiện dữ liệu thực tế, không phải thay đổi
    số liệu để giảm unresolved hoặc tăng tỷ lệ success.
    """), references('M2', ('src/parser/normalize.py','src/parser/bibliography.py','src/parser/deduplicate.py','src/parser/statistics.py'))]


def chapter_eight():
    return [md(r"""
    # 8. Thời gian và tài nguyên parser

    ## 8.1 Thiết lập thực nghiệm

    Parser được chạy mới trên snapshot cố định, output riêng và không dùng cache của lượt
    trước. Phạm vi gồm xử lý từng publication, ghi ba store, checkpoint và validation cuối.
    Input giữ cả version empty và version nguồn lỗi để coverage phản ánh tập M1 thực sự có.

    Lượt mới được đo trên Windows CPU. Thông tin hệ điều hành, Python, thư viện và RAM được
    công bố bên dưới. Đây không phải benchmark M2 cuối trên Colab CPU-only.
    """), code(COMMON), code("""
    run=data['parser_measurement']
    display(pd.Series(run['environment'],name='value').to_frame())
    display(pd.DataFrame([{k:run[k] for k in ['status','runtime_sec','processed_papers','avg_sec_per_publication','final_output_bytes']}]))
    """), md(r"""
    ## 8.2 Runtime và trung bình theo publication

    Wall time được chia cho số publication thực sự xử lý mới. `parse_publication` hiện gom
    gathering, hierarchy, bibliography, normalization và dedup trong một pha cấp publication;
    không có số đo tách riêng cho từng thuật toán đó. Storage và validation có pha riêng.

    Một run resume dùng lại output không được so sánh trực tiếp với run mới nếu không công bố
    số publication mới và số đã reuse. Phân bố độ dài TeX, số version và số references cũng
    ảnh hưởng runtime, nên báo cáo không ngoại suy thời gian toàn corpus từ phép đo nhỏ.
    """), code("""
    phases=pd.DataFrame(run['phases']).T; display(phases)
    phases['elapsed_sec'].plot.bar(title='Pha parser trong lượt Windows CPU',ylabel='Giây')
    plt.tight_layout(); plt.show()
    print('Runtime / publication xử lý mới:',run['runtime_sec']/run['processed_papers'])
    print('Trung bình đã lưu:',run['avg_sec_per_publication'])
    """), md(r"""
    ## 8.3 RAM, peak disk và output chuẩn

    RSS chính/con được lấy mẫu như crawler. Peak disk theo dõi output workspace, có thể gồm
    working JSON, checkpoint, samples và index tạm. `final_output_bytes` chỉ cộng các Parquet
    của ba bảng chuẩn. Vì phạm vi khác nhau, final disk workspace lớn hơn kích thước ba
    bảng chuẩn là điều có thể xảy ra; không được đồng nhất hai metric này.
    """), code("""
    display(pd.Series(run['memory'],name='RAM').to_frame())
    display(pd.Series(run['disk'],name='disk').to_frame())
    display(pd.DataFrame([
        {'scope':'Peak output workspace được lấy mẫu','bytes':run['disk']['peak_bytes']},
        {'scope':'Final output workspace','bytes':run['disk']['final_bytes']},
        {'scope':'Ba Parquet store chuẩn','bytes':run['final_output_bytes']},
    ]).assign(MiB=lambda frame:frame['bytes']/1024**2))
    """), md(r"""
    ## 8.4 Đo tiếp trên Colab và cập nhật đúng link

    `colab_parser_submission.ipynb` trong source repository dùng đúng input snapshot và gói
    runtime đã ghim SHA-256. Chọn CPU, tải hai ZIP đi kèm lên, chạy parser và validation, rồi
    lấy archive output gồm stats, log, manifest và `time -v`. Không cần truy vấn arXiv/S2 khi
    chỉ đo parser trên nguồn đã có.

    Chỉ cập nhật số đo Book sau khi có output thật của Colab, kiểm tra scope/input hash và
    kết quả validation. Nội dung được deploy vào repository Book hiện tại; URL nộp giữ nguyên.

    [Notebook Colab cho parser](https://colab.research.google.com/github/NguyenQuocDat06-AI/arxiv-harvester/blob/develop/colab_parser_submission.ipynb)

    ## 8.5 Kết luận thực nghiệm

    Pipeline đã tạo được ba store và validation cấu trúc trên snapshot, nhưng còn partial/error,
    thiếu references và thiếu benchmark M2 Colab cuối. Việc làm đầy đủ phần trình bày không
    thay thế các bước xử lý và đo còn thiếu. Các kết quả hiện tại được giữ làm mốc tiến độ
    có thể đối chiếu, cập nhật sau trên cùng Book.
    """), references('M2', ('src/parser/main.py','src/crawler/profiler.py','colab_parser_submission.ipynb','tools/prepare_parser_colab.py'))]


def appendix_reproduction():
    return [md(r"""
    # Phụ lục A. Tái lập và cập nhật báo cáo

    ## A.1 Hai mức tái lập

    **Tái lập Book công khai:** clone repository báo cáo, cài requirements và build. Các notebook
    đọc `report_summary.json`, sinh bảng/biểu đồ và chạy ví dụ tổng hợp. Không cần API key,
    quyền Drive hoặc corpus gốc để xem lại phần trình bày.

    **Tái lập xử lý từ nguồn:** cần snapshot M1 riêng của nhóm, code parser và cấu hình root.
    Chạy source audit, export M1, parser và validation để thu kết quả mới; sau đó mới tổng hợp
    số liệu công khai. Lệnh dưới đây là template, cần thay các đường dẫn bằng input thật.

    ```bash
    python -m pip install -e ".[report]"
    python -m src.crawler.validate_sources --publications INPUT/publications.parquet --raw-dir INPUT/raw --output OUTPUT/source_audit.parquet
    python -m src.parser.main --publications INPUT/publications.parquet --raw-dir INPUT/raw --output-dir OUTPUT/parsed --root-overrides configs/submission_parser_roots_20261106.json
    python -m src.parser.validation --course-dir INPUT/course --parsed-dir OUTPUT/parsed --publications INPUT/publications.parquet --output OUTPUT/parsed/project_validation.json
    ```

    `--resume` chỉ dùng khi tiếp tục cùng output và phạm vi hợp lệ. Khi thay input, root hoặc
    source, fingerprint giúp xác định publication cần xử lý lại. Không dùng output cũ mà
    ghép vào manifest của một run khác.

    ## A.2 Môi trường dùng cho phép đo và môi trường compile

    Các số đo lịch sử giữ Python/thư viện của chính run đó. Môi trường compile Book được pin
    riêng trong requirements, không làm thay đổi ý nghĩa của số đo đã ghi trước đây.
    Các ví dụ thuật toán của báo cáo import code từ commit ghim, không dùng dữ liệu nghiên cứu thật.
    """), code(COMMON), code("""
    import sys, importlib.metadata
    print('Python compile Book:',sys.version.split()[0])
    packages=['jupyter-book','pandas','pyarrow','matplotlib','nbformat','arxiv-harvester']
    display(pd.DataFrame([{'package':name,'installed_version':importlib.metadata.version(name)} for name in packages]))
    """), md(r"""
    ## A.3 Build Book và deploy

    ```bash
    git clone https://github.com/NguyenQuocDat06-AI/arxiv-harvester-book.git
    cd arxiv-harvester-book
    python -m pip install -r requirements.txt
    jupyter-book build . --all -W
    ```

    Sửa `index.md`, notebook trong `chapters/` hoặc nội dung tổng hợp đã xác minh. Sau khi build
    đạt, commit và push `main` của repository Book. Workflow thực thi lại notebook rồi deploy
    Pages; không dùng ảnh chụp màn hình làm nguồn cho các bảng thống kê.

    URL nộp cố định:

    **https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/**

    Giữ nguyên tên tài khoản, repository và Pages. Code M1/M2 tiếp tục nằm ở repository code
    chung, nhánh `develop`; không cần đổi tên repository Book khi bổ sung dữ liệu.

    ## A.4 Những gì giữ ngoài GitHub

    Corpus TeX/Bib, Parquet làm việc, manifest gốc, log đầy đủ, bảng mã paper và credential
    được giữ ở nơi làm việc của nhóm. Book công khai chỉ có thống kê tổng hợp, nhãn coverage
    và ví dụ tổng hợp. Test được giữ local theo cách tổ chức hiện tại của nhóm.

    ## A.5 Thao tác nộp

    Mở Book không đăng nhập, kiểm tra hai phần M1/M2, dán link Book và link source vào Moodle,
    lưu bài rồi kiểm tra trạng thái nộp. Việc có Pages không tự thực hiện bước nộp trên Moodle.
    """), references('M2', ('tools/build_public_submission_book.py','tools/prepare_submission_snapshot.py','tools/prepare_parser_colab.py'))]


def appendix_checklist():
    return [md(r"""
    # Phụ lục B. Đối chiếu yêu cầu, giới hạn và việc còn lại

    Bảng này phân biệt phần code đã triển khai, dữ liệu đã kiểm tra và bằng chứng còn thiếu.
    Trạng thái của snapshot không được thay cho trạng thái toàn dải được giao.
    """), code(COMMON), code("""
    table = [
        ('M1','Discovery theo ID/version','Có triển khai','Atom, version validation và lịch sử ngày có provenance'),
        ('M1','Nguồn mọi version trong snapshot',f\"{m1['source_verified']}/{scope['versions']} đã xác minh\",'Còn version nguồn lỗi'),
        ('M1','References S2',f\"{m1['verified_reference_papers']}/{scope['papers']} paper success/empty\",'Các paper API error cần truy vấn/xác minh lại'),
        ('M1','Hai bảng đúng schema','Đạt trên snapshot','Không chứng minh đủ toàn nhóm'),
        ('M1','Thống kê và biểu đồ','Sinh khi compile Book','Mẫu số/phạm vi được ghi trong từng chương'),
        ('M1','Benchmark Colab CPU','Có lượt đã lưu, bị tạm dừng','Chưa có phép đo hoàn tất toàn dải'),
        ('M2','Theo dõi mọi version',f\"{sum(r['recorded_versions'] for r in m2['coverage'])}/{scope['versions']} bản ghi\",'Gồm cả partial, empty và error'),
        ('M2','Gathering và hierarchy','Có triển khai và ví dụ thực thi','Còn root/cú pháp chưa xử lý đầy đủ'),
        ('M2','Normalization và dedup','Có triển khai và số đo','Còn unresolved/conflicts được giữ rõ'),
        ('M2','Ba bảng và validation','Đạt cấu trúc trên snapshot','processing_complete vẫn false'),
        ('M2','Benchmark Colab CPU cuối','Chưa có','Số đo mới hiện ở Windows CPU'),
        ('Chung','Repository code public','Có','Đường dẫn source ở trang mở đầu'),
        ('Chung','Book riêng và URL cố định','Có workflow Pages','Kiểm tra public trước khi nộp'),
        ('Chung','Nộp Moodle','Nhóm thực hiện/xác nhận','Không suy từ build/deploy thành công'),
    ]
    with pd.option_context('display.max_rows',None,'display.max_colwidth',100):
        display(pd.DataFrame(table,columns=['milestone','hạng_mục','hiện_trạng','giới_hạn_hoặc_bước_tiếp']))
    """), md(r"""
    ## B.1 Thứ tự hoàn thiện dữ liệu

    1. Xác minh/tải bù version nguồn lỗi và giữ đúng revision; audit lại trên output ổn định.
    2. Bổ sung references theo trạng thái truy vấn, giữ provenance và tôn trọng cooldown.
    3. Đối chiếu các ca root mơ hồ, missing bibliography và cú pháp chưa hỗ trợ; chỉ thêm override
       hoặc sửa parser khi có bằng chứng từ source.
    4. Chạy lại parser/validation trên toàn phạm vi M1 đã chốt, công bố cả empty và lỗi còn lại.
    5. Đo M2 trên Colab CPU-only và cập nhật đúng số đo của run mới; build lại cùng URL Book.

    ## B.2 Giới hạn của kết quả hiện tại

    Snapshot nhỏ và không ngẫu nhiên; nhiều references chưa đủ; các before-counts không đo được
    ở mọi version; môi trường M1/M2 khác nhau. Vì vậy báo cáo không tuyên bố thành công toàn
    nhóm, không coi mọi null là lỗi thu thập và không dùng runtime của mẫu để bảo đảm thời gian
    hoàn thành toàn bộ dải.

    Các ví dụ TeX/BibTeX là ví dụ tổng hợp có ghi rõ, chỉ minh họa hành vi code. Chúng không làm
    tăng số paper/version, tỷ lệ thành công hoặc counts đo từ corpus.
    """), references('M2')]


CHAPTER_BUILDERS = [
    ('01_discovery_and_versions',chapter_one),
    ('02_source_download_and_cleaning',chapter_two),
    ('03_reference_extraction',chapter_three),
    ('04_schema_and_data_quality',chapter_four),
    ('05_performance_benchmark',chapter_five),
    ('06_parsing_and_hierarchy',chapter_six),
    ('07_standardization_and_deduplication',chapter_seven),
    ('08_parser_benchmark',chapter_eight),
    ('09_reproducibility',appendix_reproduction),
    ('10_requirements_and_limitations',appendix_checklist),
]


def enrich(output: Path, summary: dict):
    """Write the detailed chapters without changing measured values."""
    for name,builder in CHAPTER_BUILDERS:
        book=nbformat.v4.new_notebook(cells=builder())
        book.metadata.kernelspec={'display_name':'Python 3','language':'python','name':'python3'}
        nbformat.write(book,output/'chapters'/f'{name}.ipynb')
    toc='format: jb-book\nroot: index\nparts:\n'
    for title,items in [('Milestone 1 — Crawling',CHAPTER_BUILDERS[:5]),('Milestone 2 — Parsing',CHAPTER_BUILDERS[5:8]),('Phụ lục',CHAPTER_BUILDERS[8:])]:
        toc+='  - caption: '+title+'\n    chapters:\n'
        toc+=''.join('      - file: chapters/'+name+'\n' for name,_ in items)
    (output/'_toc.yml').write_text(toc,encoding='utf-8')
    requirements=(output/'requirements.txt').read_text(encoding='utf-8')
    requirements='\n'.join(line for line in requirements.splitlines() if not line.startswith('arxiv-harvester @'))+'\n'
    requirements+=f'arxiv-harvester @ git+{CODE_URL}.git@{CODE_COMMIT}\n'
    (output/'requirements.txt').write_text(requirements,encoding='utf-8')
    scope,m1,m2=summary['scope'],summary['m1'],summary['m2']
    status=m2['status_counts']
    (output/'index.md').write_text(f'''# arXiv Harvester — Báo cáo Milestone 1 và 2

**Ngày cập nhật: 06/11/2026.** Đây là báo cáo triển khai và kết quả trên snapshot hiện có của nhóm. Book trình bày đầy đủ phương pháp, công thức thống kê, ví dụ thuật toán thực thi, phân tích lỗi, cách tái lập và phần công việc chưa hoàn tất. Phạm vi dữ liệu vẫn là **{scope['papers']} paper/{scope['versions']} version**, không phải toàn bộ {scope['group_assigned']:,} paper được giao.

## Tóm tắt

M1 phân giải paper/revision, tải nguồn theo version, lọc TeX/Bib và lấy references. M2 duyệt compilation path, dựng hierarchy, chuẩn hóa nội dung, hợp nhất references và khử trùng qua version. Các store được kiểm tra schema, khóa và graph; version empty hoặc lỗi được theo dõi thay vì bỏ khỏi coverage.

Snapshot được dựng từ {scope['archives_used']} lô backup đã kiểm tra checksum. Audit nguồn xác minh {m1['source_verified']}/{scope['versions']} version. Parser có {status.get('success',0)} success, {status.get('partial',0)} partial, {status.get('empty_no_tex',0)} empty và {sum(v for k,v in status.items() if k.startswith('error'))} lỗi. Kết quả năm bảng hợp lệ về cấu trúc nhưng chưa xử lý hoàn tất snapshot. References API error và benchmark M2 Colab CPU-only còn thiếu được công bố trong từng chương.

## Cách đọc báo cáo

- **M1:** phạm vi và discovery → source audit/size → references → validation → số đo crawler.
- **M2:** gathering/hierarchy và coverage từng paper → normalization/dedup → số đo parser.
- **Phụ lục:** môi trường/lệnh tái lập, đối chiếu yêu cầu và thứ tự hoàn thiện.

Các bảng và biểu đồ được sinh khi Book thực thi notebook. Ví dụ TeX/BibTeX được đánh dấu là tổng hợp và chạy từ source ghim; chúng không được tính vào thống kê corpus. Input công khai chỉ chứa số liệu tổng hợp và nhãn P001…; corpus, ID/text từng paper, Parquet và log gốc được nhóm giữ riêng.

## Trạng thái và link nộp

**URL Book cố định:** {BOOK_URL}

[Repository báo cáo]({CODE_URL}-book) · [Source code M1–M2]({CODE_URL}/tree/develop) · [Đề đồ án](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/)

Phần trình bày được hoàn thiện trên dữ liệu hiện có; việc đủ source/references toàn nhóm và benchmark cuối vẫn cần được hoàn thành bằng các lượt thực tế. Xem phụ lục đối chiếu để phân biệt yêu cầu đã có bằng chứng và phần còn thiếu. Nhóm thực hiện/xác nhận bước nộp link trên Moodle.

Công cụ trợ lý được dùng để hỗ trợ chuẩn bị code/báo cáo; nhóm cần đọc, kiểm tra và giải thích phần nộp.
''',encoding='utf-8')
    (output/'README.md').write_text(f'''# Báo cáo Jupyter Book M1–M2

Link nộp cố định: {BOOK_URL}

```bash
python -m pip install -r requirements.txt
jupyter-book build . --all -W
```

Notebook đọc `report_summary.json` và sinh bảng/biểu đồ khi build. Các ví dụ tổng hợp import parser từ commit source ghim trong requirements. Build không gọi Drive, arXiv hoặc S2. Corpus và log gốc không nằm trong repository này.

Sửa `index.md`, notebook trong `chapters/` hoặc cập nhật thống kê có bằng chứng; build đạt rồi push `main`. Giữ nguyên tên tài khoản/repository và Pages để URL nộp không đổi. Không sửa trực tiếp HTML trong `_build/`.
''',encoding='utf-8')
    from tools.submission_report_presentation import present
    present(output, summary)
