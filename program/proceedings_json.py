"""Metadata snapshots matching pasj_proceedings_builder's data format."""
import json

from .program_json import export_program_json

METADATA_FILE = 'proceedings_metadata.json'
COPYRIGHT_NOTICE = (
    '本プロシーディングスの著作権は日本加速器学会に帰属します。'
    '本プロシーディングス全体または個々の論文を転載する場合には、'
    '予め日本加速器学会の許可を必要とします。'
)


def write_metadata_snapshot(directory, meeting, page_records):
    program = {record['talk_id']: record for record in json.loads(export_program_json(meeting))}
    records = []
    for pages in page_records:
        record = dict(program[pages['talk_id']], **pages)
        record['pdf_path'] = f"{pages['talk_id']}.pdf" if pages['start_page'] is not None else None
        records.append(record)
    (directory / METADATA_FILE).write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
