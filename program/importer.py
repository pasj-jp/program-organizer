import re
from django.db import transaction
from openpyxl import load_workbook
from .models import Author, Presentation

REQUIRED = ('演題登録番号', '題目', '発表形式', '連名者[1]区分')
SOURCE_FIELDS = {
    'registration_number': '参加登録番号', 'login_id': 'ログインID',
    'email': 'メールアドレス', 'title': '題目', 'title_en': '題目（english）',
    'abstract': '要旨', 'presentation_format': '発表形式',
    'category_first': '発表希望カテゴリー（第１希望）',
    'category_second': '発表希望カテゴリー（第２希望）',
    'author_text': '著者情報', 'author_text_en': '著者情報（英語）',
    'affiliation_text': '著者所属情報', 'affiliation_text_en': '著者所属情報（英語）',
}
AUTHOR_FIELDS = {
    'family_name': '姓', 'given_name': '名', 'family_name_kana': '姓カナ',
    'given_name_kana': '名カナ', 'family_name_en': '姓英語',
    'given_name_en': '名英語', 'middle_name': 'ミドルネーム',
    'affiliation': '所属', 'affiliation_en': '所属 (英語)',
}


def value(row, key):
    v = row.get(key)
    return str(v).strip() if v is not None else ''


@transaction.atomic
def import_abstracts(file, meeting):
    try:
        book = load_workbook(file, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError('Excel ファイルを読み込めません。') from exc
    try:
        sheet = book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        headers = [str(x).strip() if x is not None else '' for x in next(rows)]
        missing = [x for x in REQUIRED if x not in headers]
        if missing:
            raise ValueError('必要な列がありません: ' + ', '.join(missing))
        created = updated = 0
        seen = set()
        author_numbers = sorted({int(m.group(1)) for h in headers if (m := re.fullmatch(r'連名者\[(\d+)\]区分', h))})
        for index, cells in enumerate(rows, start=2):
            row = dict(zip(headers, cells))
            number = value(row, '演題登録番号')
            if not number:
                continue
            if number in seen:
                raise ValueError(f'{index} 行目: 演題登録番号 {number} が重複しています。')
            seen.add(number)
            defaults = {field: value(row, heading) for field, heading in SOURCE_FIELDS.items()}
            if not defaults['title']:
                raise ValueError(f'{index} 行目: 題目がありません。')
            presentation, is_new = Presentation.objects.update_or_create(
                annual_meeting=meeting, submission_number=number, defaults=defaults)
            created += is_new
            updated += not is_new
            # 著者はソースの順序と登壇者区分に合わせて更新する。
            source_positions = set()
            for pos in author_numbers:
                prefix = f'連名者[{pos}]'
                if not any(value(row, prefix + suffix) for suffix in ('姓', '名', '姓英語', '名英語')):
                    continue
                source_positions.add(pos)
                fields = {field: value(row, prefix + heading) for field, heading in AUTHOR_FIELDS.items()}
                fields['is_presenter'] = '登壇者' in value(row, prefix + '区分')
                Author.objects.update_or_create(presentation=presentation, position=pos, defaults=fields)
            presentation.authors.exclude(position__in=source_positions).delete()
        return created, updated
    finally:
        book.close()
