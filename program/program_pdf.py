"""Build the program booklet using the PASJ layout and Vivliostyle CLI."""

import html
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings

from .models import Presentation
from .program_data import HEADERS, iter_program_rows
from .program_json import convert_row
from .program_print import make_blocks, render_html, to_presentation, write_outputs


class ProgramPDFError(Exception):
    pass


def build_program_html(meeting):
    talks = {talk.submission_number: talk for talk in
             Presentation.objects.filter(annual_meeting=meeting, session__isnull=False).prefetch_related('authors')}
    presentations = []
    for index, values in enumerate(iter_program_rows(meeting), 1):
        row = dict(zip(HEADERS, values))
        record = convert_row(row)
        record.update(category=row['セッション名'], chair=row['座長'],
                      author_text_en_html=row['著者情報（英語）'],
                      affiliation_text_en_html=row['著者所属情報（英語）'])
        pres = to_presentation(record, index)
        talk = talks[record['submission_id']]
        pres.session_id = talk.session_id
        pres.withdrawn = talk.status == Presentation.Status.WITHDRAWN
        presenter = next((author for author in talk.authors.all() if author.is_presenter), None)
        if presenter and presenter.affiliation_en:
            pres.presenter_affiliation_en = presenter.affiliation_en
        presentations.append(pres)
    if not presentations:
        raise ProgramPDFError('割り当て済みの演題がないため、PDFを出力できません。')
    document = render_html(make_blocks(presentations, {}), meeting.year)
    return document.replace(f'<title>PASJ{meeting.year} Program</title>',
                            f'<title>{html.escape(meeting.name)} プログラム</title>')


def export_program_pdf(meeting):
    document = build_program_html(meeting)
    with TemporaryDirectory(prefix='pasj-program-') as directory:
        workdir = Path(directory)
        write_outputs(document, workdir)
        try:
            subprocess.run(
                [settings.VIVLIOSTYLE_CLI, 'build', 'program.html', '-o', 'program.pdf',
                 '-t', str(settings.PROGRAM_PDF_TIMEOUT)],
                cwd=workdir, check=True, capture_output=True,
                timeout=settings.PROGRAM_PDF_TIMEOUT + 15,
            )
            result = (workdir / 'program.pdf').read_bytes()
        except subprocess.TimeoutExpired as exc:
            raise ProgramPDFError('PDF生成が制限時間を超えました。管理者にお問い合わせください。') from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ProgramPDFError('PDFを生成できませんでした。管理者はVivliostyle・Node.js・ブラウザの実行環境を確認してください。') from exc
        if not result.startswith(b'%PDF-'):
            raise ProgramPDFError('PDF生成結果が不正です。管理者にお問い合わせください。')
        return result
