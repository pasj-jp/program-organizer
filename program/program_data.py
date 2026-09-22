"""Shared program columns and database rows for XLSX and JSON exports."""

from .models import Session


BASE_HEADERS = (
    'ソート', 'ログインID', '演題登録番号', '参加登録番号', '確定発表形式', 'セッション',
    'セッション名', '発表希望カテゴリー（第１希望）', '講演番号', '開催日', '発表時間', '会場',
    '座長', 'カテゴリ情報', 'メールアドレス', '姓', '名', '姓(かな)', '名(かな)',
    '姓(英語)', '名(英語)', '名(ミドルネーム)', '所属機関名', '部署名・学部名', '国',
    '郵便番号', '住所', '建物名', '所属先名', '電話番号', '内線番号', 'FAX番号',
    '発表形式', '題目', '題目（english）', '要旨', '発表希望カテゴリー（第１希望）',
    '発表希望カテゴリー（第２希望）',
    '年会賞への応募応募', '賞状の敬称', '通信欄', 'スライド（before）',
    'スライド（after）', 'スライドアンケート', 'Procファイル（ソース）',
    'Procファイル（PDF）', 'ソース作成環境', '著者情報', '著者情報（英語）',
    '著者所属情報', '著者所属情報（英語）', '登録日時', '更新日時',
)
AUTHOR_COLUMNS = ('区分', '姓', '名', '姓カナ', '名カナ', '姓英語', '名英語',
                  'ミドルネーム', '所属', '所属 (英語)')
MAX_AUTHORS = 52
AUTHOR_START_COLUMN = len(BASE_HEADERS) + 1
AUTHOR_FIELDS = ('family_name', 'given_name', 'family_name_kana', 'given_name_kana',
                 'family_name_en', 'given_name_en', 'middle_name', 'affiliation', 'affiliation_en')
HEADERS = BASE_HEADERS + tuple(f'連名者[{position}]{column}'
    for position in range(1, MAX_AUTHORS + 1) for column in AUTHOR_COLUMNS)


def author_column(position):
    """Return the one-based column of an author's presenter marker."""
    return AUTHOR_START_COLUMN + (position - 1) * len(AUTHOR_COLUMNS)


def author_export_values(author):
    column = author_column(author.position)
    values = ('登壇者' if author.is_presenter else '連名者',
              *(getattr(author, field) for field in AUTHOR_FIELDS))
    return {column + index: value for index, value in enumerate(values)}


def iter_program_rows(meeting):
    """Yield assigned presentations in program order, including withdrawn talks."""
    sessions = Session.objects.filter(annual_meeting=meeting).select_related(
        'venue', 'poster_session_one', 'poster_session_two').prefetch_related('chairs', 'presentations__authors')
    order = 0
    for session in sessions.order_by('board_order', 'date', 'start_time', 'pk'):
        if session.kind == Session.Kind.FACILITY_REPORT:
            posters = (session.poster_session_one, session.poster_session_two)
            days = '・'.join(f'{poster.date.month}月{poster.date.day}日' for poster in posters)
            slots = '/'.join(f"{poster.start_time:%H:%M}-{poster.end_time:%H:%M}" for poster in posters)
            room = posters[0].venue.name if posters[0].venue else ''
        else:
            days = session.date
            slots = (f'{session.start_time:%H:%M}-{session.end_time:%H:%M}'
                     if session.start_time and session.end_time else '')
            room = session.venue.name if session.venue else ''
        chairs = {chair.category: chair.name for chair in session.chairs.all()}
        for talk in sorted(session.presentations.all(), key=lambda item: (item.session_order, item.pk)):
            order += 1
            row = [None] * len(HEADERS)
            format_name = talk.presentation_format or session.get_kind_display()
            values = {1: order, 2: talk.login_id, 3: talk.submission_number,
                4: talk.registration_number, 5: format_name,
                6: session.name, 7: talk.confirmed_category, 8: talk.category_first,
                9: talk.program_number, 10: days, 11: slots, 12: room,
                13: chairs.get(talk.confirmed_category, ''), 15: talk.email,
                33: format_name, 34: talk.title, 35: talk.title_en,
                36: talk.abstract, 37: talk.category_first, 38: talk.category_second,
                39: 'エントリーする [Entry]' if talk.applies_for_annual_award else 'エントリーしない [Not entry]',
                48: talk.author_text, 49: talk.author_text_en,
                50: talk.affiliation_text, 51: talk.affiliation_text_en}
            authors = sorted(talk.authors.all(), key=lambda author: author.position)
            presenter = next((author for author in authors if author.is_presenter), None)
            if presenter:
                values.update({16: presenter.family_name, 17: presenter.given_name,
                    18: presenter.family_name_kana, 19: presenter.given_name_kana,
                    20: presenter.family_name_en, 21: presenter.given_name_en,
                    22: presenter.middle_name, 23: presenter.affiliation})
            for author in authors:
                if author.position > MAX_AUTHORS:
                    continue
                values.update(author_export_values(author))
            for column, value in values.items():
                row[column - 1] = value
            yield row
