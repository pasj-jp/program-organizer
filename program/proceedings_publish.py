"""Publish complete generations using an atomic directory symlink switch."""
import os
import json
import re
import shutil
from pathlib import Path
from contextlib import contextmanager
from tempfile import mkdtemp, TemporaryFile, TemporaryDirectory
from uuid import uuid4
from .proceedings_pdf import pymupdf

from django.conf import settings

CODE_PATTERN = r'[A-Za-z0-9_-]+'
PAGE_DATA_FILE = 'pdf_page_data.txt'
PROCEEDINGS_LIST_FILE = 'proceedings_list.json'


def published_directory(year):
    return Path(settings.PROCEEDINGS_PUBLISH_ROOT) / str(year) / 'web_publish'


def generated_directory(year):
    return published_directory(year).parent / '.generated'


def publish_proceedings(year):
    directory = generated_directory(year).resolve(strict=True)
    if not (directory / PROCEEDINGS_LIST_FILE).is_file():
        raise FileNotFoundError('No generated proceedings')
    pointer = directory.parent / f'.publish-{uuid4().hex}'
    try:
        pointer.symlink_to(directory.name, target_is_directory=True)
        os.replace(pointer, published_directory(year))
    finally:
        pointer.unlink(missing_ok=True)


def unpublish_proceedings(year):
    published = published_directory(year)
    # Preserve publications created before the private generation pointer existed.
    if published.exists() and not generated_directory(year).exists():
        directory = published.resolve(strict=True)
        pointer = directory.parent / f'.generate-{uuid4().hex}'
        try:
            pointer.symlink_to(directory.name, target_is_directory=True)
            os.replace(pointer, generated_directory(year))
        finally:
            pointer.unlink(missing_ok=True)
    published.unlink(missing_ok=True)


@contextmanager
def generation_directory(year):
    """Save a complete private generation only when the caller succeeds."""
    year_dir = published_directory(year).parent
    year_dir.mkdir(parents=True, exist_ok=True)
    generation = Path(mkdtemp(prefix='.proceedings-', dir=year_dir))
    pointer = year_dir / f'.publish-{uuid4().hex}'
    try:
        yield generation
        pointer.symlink_to(generation.name, target_is_directory=True)
        os.replace(pointer, generated_directory(year))
    except Exception:
        pointer.unlink(missing_ok=True)
        shutil.rmtree(generation)
        raise


def download_pdf(year):
    # Resolve once so concurrent generation cannot mix files.
    source = generated_directory(year)
    if not source.exists():
        source = published_directory(year)
    directory = source.resolve(strict=True)
    records = json.loads((directory / PROCEEDINGS_LIST_FILE).read_text(encoding='utf-8'))
    result = TemporaryFile()
    try:
        with pymupdf.open() as merged:
            labels = []
            for record in records:
                if record['start_page'] is None:
                    continue
                code = record['talk_id']
                if not re.fullmatch(CODE_PATTERN, code):
                    raise ValueError('Invalid published program code')
                with pymupdf.open(directory / f'{code}.pdf') as source:
                    labels.append({'startpage': merged.page_count, 'prefix': '', 'style': 'D',
                                   'firstpagenum': record['start_page']})
                    merged.insert_pdf(source)
            if not merged.page_count:
                raise FileNotFoundError('No published PDFs')
            merged.set_page_labels(labels)
            merged.set_metadata({'title': f'PASJ{year} Proceedings'})
            with TemporaryDirectory(prefix='pasj-merged-') as workdir:
                output = Path(workdir) / 'proceedings.pdf'
                merged.save(output, garbage=4, deflate=True)
                with output.open('rb') as source:
                    shutil.copyfileobj(source, result)
        result.seek(0)
        return result
    except Exception:
        result.close()
        raise
