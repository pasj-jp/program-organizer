"""Generate and publish proceedings without modifying submitted PDFs."""
import json
import logging
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.conf import settings

from .models import Presentation
from .proceedings_publish import (
    CODE_PATTERN, PAGE_DATA_FILE, PROCEEDINGS_LIST_FILE, generation_directory,
)
from .program_data import iter_program_rows
from .proceedings_pdf import process_pdf
from .program_print import strip_html


logger = logging.getLogger(__name__)


class ProceedingsError(Exception):
    pass


def header_defaults(meeting):
    configs = json.loads(Path(__file__).with_name('proceedings_headers.json').read_text())
    return dict(configs.get(str(meeting.year), {'volume': f'PASJ{meeting.year}'}), start_page=1)


def save_uploads(uploads):
    for talk, upload in uploads:
        old_name = talk.proceedings_file.name
        storage = talk.proceedings_file.storage
        talk.proceedings_file.save(upload.name, upload, save=False)
        # Updating only this field avoids triggering session renumbering.
        Presentation.objects.filter(pk=talk.pk).update(proceedings_file=talk.proceedings_file.name)
        if old_name and old_name != talk.proceedings_file.name:
            storage.delete(old_name)


def ordered_presentations(meeting):
    """Match program.xlsx / abstracts.json order, including facility reports once."""
    talks = {talk.submission_number: talk for talk in meeting.presentations.filter(
        session__isnull=False).prefetch_related('authors')}
    return [talks[row[2]] for row in iter_program_rows(meeting) if row[2] in talks and row[8]]


def paper_metadata(talk):
    if talk.author_text_en:
        authors = re.sub(r'\s+', ' ', strip_html(talk.author_text_en).replace('○', '')).strip()
    else:
        authors = ', '.join(
            ' '.join(filter(None, [author.given_name_en, author.middle_name, author.family_name_en]))
            for author in talk.authors.all())
    return SimpleNamespace(talk_id=talk.program_number, title_en=talk.title_en, authors_en=authors)


def process_presentation(talk, directory, source, start_page, options):
    code = talk.program_number
    if not re.fullmatch(CODE_PATTERN, code):
        raise ProceedingsError(f'{code}: PDF出力用のプログラムコードは半角英数字・ハイフン・アンダースコアにしてください。')
    try:
        with talk.proceedings_file.open('rb') as uploaded, source.open('wb') as target:
            shutil.copyfileobj(uploaded, target)
        return process_pdf(
            source, directory / f'{code}.pdf', paper_metadata(talk), start_page,
            options['volume'], options['header1'], options['header2'],
            Path(settings.PROCEEDINGS_FONT_DIR), False)
    except Exception as exc:
        logger.warning('Proceedings PDF processing failed: meeting=%s talk=%s',
                       talk.annual_meeting_id, talk.pk, exc_info=True)
        raise ProceedingsError(f'{code}: PDFを加工できません。PDFの破損・暗号化、保存ファイル、フォント設定を確認してください。') from exc


def write_page_lists(directory, records):
    lines = [f"{record['index']}\t{record['talk_id']}\t{record['start_page'] if record['start_page'] is not None else ''}\n"
             for record in records]
    (directory / PAGE_DATA_FILE).write_text(''.join(lines), encoding='utf-8')
    (directory / PROCEEDINGS_LIST_FILE).write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build_proceedings(meeting, options):
    ordered = ordered_presentations(meeting)
    if not any(talk.proceedings_file for talk in ordered):
        raise ProceedingsError('採番・セッション割り当て済みの演題にPDFがありません。')
    try:
        with generation_directory(meeting.year) as directory, TemporaryDirectory(prefix='pasj-proceedings-') as workdir:
            next_page = options['start_page']
            records = []
            for index, talk in enumerate(ordered, 1):
                start_page = None
                if talk.proceedings_file:
                    start_page = next_page
                    next_page += process_presentation(
                        talk, directory, Path(workdir) / 'source.pdf', start_page, options)
                records.append({'index': index, 'talk_id': talk.program_number, 'start_page': start_page})
            write_page_lists(directory, records)
    except OSError as exc:
        logger.warning('Proceedings generation failed: meeting=%s', meeting.pk, exc_info=True)
        raise ProceedingsError('加工済みPDFを保存できません。管理者は生成先の保存パスと書き込み権限を確認してください。') from exc
