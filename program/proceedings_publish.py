"""Publish complete generations using an atomic directory symlink switch."""
import os
import re
import shutil
from pathlib import Path
from tempfile import mkdtemp, TemporaryFile
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from django.conf import settings

CODE_PATTERN = r'[A-Za-z0-9_-]+'


def published_directory(year):
    return Path(settings.PROCEEDINGS_PUBLISH_ROOT) / str(year) / 'web_publish'


def publish_archive(year, archive):
    year_dir = published_directory(year).parent
    year_dir.mkdir(parents=True, exist_ok=True)
    generation = Path(mkdtemp(prefix='.proceedings-', dir=year_dir))
    pointer = year_dir / f'.publish-{uuid4().hex}'
    try:
        archive.seek(0)
        with ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                name = Path(entry.filename).name
                if name not in ('pdf_page_data.txt', 'proceedings_list.json') and not re.fullmatch(CODE_PATTERN + r'\.pdf', name):
                    raise ValueError('Unexpected proceedings artifact')
                with bundle.open(entry) as source, (generation / name).open('wb') as target:
                    shutil.copyfileobj(source, target)
        pointer.symlink_to(generation.name, target_is_directory=True)
        os.replace(pointer, published_directory(year))
    except Exception:
        pointer.unlink(missing_ok=True)
        shutil.rmtree(generation)
        raise
    finally:
        archive.seek(0)


def download_archive(year):
    # Resolve once so a concurrent publication cannot mix generations in the ZIP.
    directory = published_directory(year).resolve(strict=True)
    archive = TemporaryFile()
    try:
        with ZipFile(archive, 'w', ZIP_DEFLATED) as bundle:
            for path in sorted(directory.iterdir()):
                if re.fullmatch(CODE_PATTERN + r'\.pdf', path.name):
                    bundle.write(path, f'{path.stem[:4]}/{path.name}')
            for name in ('pdf_page_data.txt', 'proceedings_list.json'):
                bundle.write(directory / name, name)
        archive.seek(0)
        return archive
    except Exception:
        archive.close()
        raise
