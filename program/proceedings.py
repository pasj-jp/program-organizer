"""Build a downloadable batch without modifying submitted PDFs."""
import json
import logging
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED

from django.conf import settings

from .program_data import iter_program_rows
from .proceedings_pdf import process_pdf
from .program_print import strip_html


logger = logging.getLogger(__name__)


class ProceedingsError(Exception):
    pass


def header_defaults(meeting):
    configs = json.loads(Path(__file__).with_name('proceedings_headers.json').read_text())
    return dict(configs.get(str(meeting.year), {'volume': f'PASJ{meeting.year}'}), start_page=1)


def build_proceedings(meeting, options):
    # Same sequence as program.xlsx / abstracts.json; facility reports appear once.
    talks = {talk.submission_number: talk for talk in meeting.presentations.filter(
        session__isnull=False).prefetch_related('authors')}
    ordered = [talks[row[2]] for row in iter_program_rows(meeting) if row[2] in talks and row[8]]
    if not any(talk.proceedings_file for talk in ordered):
        raise ProceedingsError('採番・セッション割り当て済みの演題にPDFがありません。')
    archive = TemporaryFile()
    try:
        with TemporaryDirectory(prefix='pasj-proceedings-') as directory, ZipFile(archive, 'w', ZIP_DEFLATED) as bundle:
            workdir = Path(directory)
            next_page = options['start_page']
            records = []
            lines = []
            for index, talk in enumerate(ordered, 1):
                code = talk.program_number
                start_page = None
                if talk.proceedings_file:
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', code):
                        raise ProceedingsError(f'{code}: PDF出力用のプログラムコードは半角英数字・ハイフン・アンダースコアにしてください。')
                    paper = SimpleNamespace(talk_id=code, title_en=talk.title_en,
                        authors_en=re.sub(r'\s+', ' ', strip_html(talk.author_text_en).replace('○', '')).strip() if talk.author_text_en else ', '.join(
                            ' '.join(filter(None, [a.given_name_en, a.middle_name, a.family_name_en]))
                            for a in talk.authors.all()))
                    try:
                        source = workdir / 'source.pdf'
                        output = workdir / 'output.pdf'
                        with talk.proceedings_file.open('rb') as uploaded, source.open('wb') as target:
                            shutil.copyfileobj(uploaded, target)
                        pages = process_pdf(source, output, paper, next_page,
                            options['volume'], options['header1'], options['header2'],
                            Path(settings.PROCEEDINGS_FONT_DIR), False)
                        bundle.write(output, f'{code[:4]}/{code}.pdf')
                        output.unlink()
                    except Exception as exc:
                        logger.warning('Proceedings PDF processing failed: meeting=%s talk=%s', meeting.pk, talk.pk, exc_info=True)
                        raise ProceedingsError(f'{code}: PDFを加工できません。PDFの破損・暗号化、保存ファイル、フォント設定を確認してください。') from exc
                    start_page = next_page
                    next_page += pages
                records.append({'index': index, 'talk_id': code, 'start_page': start_page})
                lines.append(f'{index}\t{code}\t{start_page if start_page is not None else ""}\n')
            bundle.writestr('pdf_page_data.txt', ''.join(lines))
            bundle.writestr('proceedings_list.json', json.dumps(records, ensure_ascii=False, indent=2) + '\n')
        archive.seek(0)
        return archive
    except Exception:
        archive.close()
        raise
