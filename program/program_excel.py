"""Import and export the program.xlsx scheduling columns."""

import re
import unicodedata
from collections import OrderedDict, defaultdict
from datetime import date, datetime, time
from io import BytesIO

from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel

from .models import Author, Presentation, Session, SessionChair, Venue
from .program_data import AUTHOR_FIELDS, HEADERS, MAX_AUTHORS, author_column, iter_program_rows


REQUIRED_COLUMNS = {3, 5, 6, 9, 10, 11, 12, 34}
POSTER_MARKS = '①②③④⑤⑥⑦⑧⑨⑩'


def cell(row, number):
    value = row[number - 1] if number <= len(row) else None
    return str(value).strip() if value is not None else ''


def authors_from_row(row, talk):
    authors = []
    for position in range(1, MAX_AUTHORS + 1):
        column = author_column(position)
        if not (cell(row, column + 1) or cell(row, column + 2)):
            continue
        fields = {name: cell(row, column + index) for index, name in enumerate(AUTHOR_FIELDS, start=1)}
        authors.append(Author(presentation=talk, position=position,
                              is_presenter='登壇者' in cell(row, column), **fields))
    return authors


def parse_day(value, meeting, row_number):
    if isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    elif isinstance(value, (float, int)):
        day = from_excel(value).date()
    else:
        text = str(value).strip()
        try:
            day = date.fromisoformat(text)
        except ValueError:
            match = re.fullmatch(r'(\d{1,2})月(\d{1,2})日', text)
            if not match:
                raise ValueError(f'{row_number}行目: 開催日を読み取れません。')
            day = date(meeting.start_date.year, int(match[1]), int(match[2]))
    if not meeting.start_date <= day <= meeting.end_date:
        raise ValueError(f'{row_number}行目: {day} は「{meeting.name}」の会期外です。年会設定を確認してください。')
    return day


def parse_slot(text, row_number):
    match = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*[-–〜]\s*(\d{1,2}):(\d{2})\s*', text)
    if not match:
        raise ValueError(f'{row_number}行目: 発表時間「{text}」を読み取れません。')
    start = time(int(match[1]), int(match[2]))
    end = time(int(match[3]), int(match[4]))
    duration = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if duration <= 0:
        raise ValueError(f'{row_number}行目: 発表時間の終了は開始より後にしてください。')
    return start, duration


def normalized_category(value):
    value = re.sub(r'^A\s*[-－]\s*\d+\s*', '', value)
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def annual_award_entry(value):
    return value.startswith('エントリーする')


def chosen_category(talk, source):
    if not source:
        return talk.category_first
    chosen = normalized_category(source)
    for preference in (talk.category_first, talk.category_second):
        if preference and normalized_category(preference) == chosen:
            return preference
    return source


def presentation_kind(format_name, session_name):
    kind = Session.Kind.from_presentation_format(format_name)
    if kind != Session.Kind.OTHER:
        return kind
    if len([mark for mark in POSTER_MARKS if mark in session_name]) >= 2:
        return Session.Kind.FACILITY_REPORT
    return Session.Kind.OTHER


def program_column_positions(headers):
    """Match repeated headers by occurrence, preserving the program column layout."""
    positions = defaultdict(list)
    for index, header in enumerate(headers):
        if header is not None:
            positions[str(header).strip()].append(index)
    missing = [HEADERS[index - 1] for index in REQUIRED_COLUMNS
               if not positions[HEADERS[index - 1]]]
    if missing:
        raise ValueError('program.xlsx形式の列がありません: ' + '、'.join(missing))
    occurrences = defaultdict(int)
    source_positions = []
    for header in HEADERS:
        occurrence = occurrences[header]
        matching = positions[header]
        source_positions.append(matching[occurrence] if occurrence < len(matching) else None)
        occurrences[header] += 1
    return source_positions


def program_slots(row, meeting, row_number, kind):
    """Parse one session slot or the two linked facility-report poster slots."""
    day_values = str(cell(row, 10)).split('・') if isinstance(row[9], str) and '・' in row[9] else [row[9]]
    if len(day_values) > 1:
        month_match = re.search(r'(\d{1,2})月', day_values[0])
        if month_match:
            day_values = [day if '月' in day else f'{month_match[1]}月{day}' for day in day_values]
    time_values = cell(row, 11).split('/')
    if len(day_values) != len(time_values):
        raise ValueError(f'{row_number}行目: 開催日と発表時間の枠数が一致しません。')
    slots = tuple((parse_day(day, meeting, row_number), *parse_slot(slot, row_number))
                  for day, slot in zip(day_values, time_values))
    if kind == Session.Kind.FACILITY_REPORT and len(slots) != 2:
        raise ValueError(f'{row_number}行目: 2つのポスター枠の開催日と時間が必要です。')
    if kind != Session.Kind.FACILITY_REPORT and len(slots) != 1:
        raise ValueError(f'{row_number}行目: 発表形式に対して時間枠が複数あります。')
    return slots


def read_program(file, meeting):
    try:
        book = load_workbook(file, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError('Excelファイルを読み込めません。') from exc
    try:
        sheet = book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, ())
        source_positions = program_column_positions(headers)
        groups = OrderedDict()
        seen = set()
        for row_number, source_row in enumerate(rows, start=2):
            row = [source_row[index] if index is not None and index < len(source_row) else None
                   for index in source_positions]
            first_summary, first_detail = cell(row, 8), cell(row, 37)
            if first_summary and first_detail and first_summary != first_detail:
                raise ValueError(f'{row_number}行目: 同じ見出しの第1希望カテゴリー列で値が異なります。')
            row[7] = row[36] = first_detail or first_summary
            row = tuple(row)
            number = cell(row, 3)
            if not number:
                continue
            if number in seen:
                raise ValueError(f'{row_number}行目: 演題登録番号「{number}」が重複しています。')
            seen.add(number)
            name, format_name, room = cell(row, 6), cell(row, 5), cell(row, 12)
            if not name or not format_name or not room:
                raise ValueError(f'{row_number}行目: セッション、確定発表形式、会場が必要です。')
            kind = presentation_kind(format_name, name)
            slots = program_slots(row, meeting, row_number, kind)
            key = (name, kind, room, slots)
            groups.setdefault(key, []).append((row_number, row))
        if not groups:
            raise ValueError('取り込む演題がありません。')
        return groups
    finally:
        book.close()


@transaction.atomic
def import_program(file, meeting):
    groups = read_program(file, meeting)
    numbers = [cell(row, 3) for rows in groups.values() for _, row in rows]
    existing = {talk.submission_number: talk for talk in Presentation.objects.filter(
        annual_meeting=meeting, submission_number__in=numbers)}
    previous_session_ids = {talk.session_id for talk in existing.values() if talk.session_id}
    missing_titles = [f'{line}行目: {number} の題目がありません。'
                      for rows in groups.values() for line, row in rows
                      if (number := cell(row, 3)) not in existing and not cell(row, 34)]
    if missing_titles:
        raise ValueError(missing_titles[0])
    room_names = {key[2] for key in groups}
    rooms = {}
    for name in room_names:
        rooms[name], _ = Venue.objects.get_or_create(annual_meeting=meeting, name=name)
    sessions = {}
    poster_slots = {}
    for key, rows in groups.items():
        name, kind, room_name, slots = key
        if kind == Session.Kind.FACILITY_REPORT:
            continue
        day, start, duration = slots[0]
        session = Session.objects.filter(annual_meeting=meeting, name=name, kind=kind,
            date=day, start_time=start, venue=rooms[room_name], code__isnull=True).first()
        if session is None:
            options = {'name': name, 'kind': kind, 'annual_meeting': meeting,
                       'date': day, 'start_time': start, 'venue': rooms[room_name]}
            if kind == Session.Kind.ORAL:
                options['talk_limit'] = len(rows)
                options['minutes_per_presentation'] = max(1, duration // len(rows))
            elif kind == Session.Kind.POSTER:
                options['slot_duration_minutes'] = duration
            else:
                options['empty_duration_minutes'] = duration
                options['minutes_per_presentation'] = max(1, duration // len(rows))
            session = Session.objects.create(**options)
        elif kind == Session.Kind.ORAL and (session.talk_limit or 0) < len(rows):
            session.talk_limit = len(rows)
            session.save(update_fields=['talk_limit'])
        sessions[key] = session
        if kind == Session.Kind.POSTER:
            poster_slots[(room_name, day, start)] = session
    for key, rows in groups.items():
        name, kind, room_name, slots = key
        if kind != Session.Kind.FACILITY_REPORT:
            continue
        posters = [poster_slots.get((room_name, day, start)) for day, start, _ in slots]
        if not all(posters) or posters[0] == posters[1]:
            raise ValueError(f'施設報告「{name}」に対応する2つのポスターセッションが見つかりません。')
        session = Session.objects.filter(annual_meeting=meeting, name=name, kind=kind,
            poster_session_one=posters[0], poster_session_two=posters[1], code__isnull=True).first()
        if session is None:
            session = Session.objects.create(name=name, kind=kind, annual_meeting=meeting,
                poster_session_one=posters[0], poster_session_two=posters[1])
        sessions[key] = session
    imported_numbers = [cell(row, 9) for rows in groups.values() for _, row in rows if cell(row, 9)]
    if len(imported_numbers) != len(set(imported_numbers)):
        raise ValueError('講演番号が重複しています。')
    collisions = Presentation.objects.filter(annual_meeting=meeting).exclude(
        submission_number__in=numbers).filter(program_number__in=imported_numbers)
    if collisions.exists():
        raise ValueError(f'講演番号「{collisions.first().program_number}」が別の演題で使用されています。')
    Presentation.objects.filter(annual_meeting=meeting, submission_number__in=numbers).update(program_number=None)
    created = 0
    updated = 0
    chair_names = {}
    for key, rows in groups.items():
        session = sessions[key]
        for position, (line, row) in enumerate(rows, start=1):
            number = cell(row, 3)
            talk = existing.get(number)
            if talk is None:
                talk = Presentation.objects.create(annual_meeting=meeting, submission_number=number, title=cell(row, 34),
                    title_en=cell(row, 35), abstract=cell(row, 36), login_id=cell(row, 2),
                    registration_number=cell(row, 4), email=cell(row, 15),
                    category_first=cell(row, 37) or cell(row, 8), category_second=cell(row, 38),
                    applies_for_annual_award=annual_award_entry(cell(row, 39)))
                created += 1
            else:
                updated += 1
            if not talk.authors.exists():
                Author.objects.bulk_create(authors_from_row(row, talk))
            category = chosen_category(talk, cell(row, 7))
            Presentation.objects.filter(pk=talk.pk).update(
                session=session, session_order=position, confirmed_category=category,
                presentation_format=cell(row, 5), program_number=cell(row, 9) or None,
                applies_for_annual_award=annual_award_entry(cell(row, 39)))
            chair = cell(row, 13)
            if session.kind == Session.Kind.ORAL and category and chair:
                chair_key = (session.pk, category)
                chair_names.setdefault(chair_key, [])
                if chair not in chair_names[chair_key]:
                    chair_names[chair_key].append(chair)
    for (session_id, category), names in chair_names.items():
        SessionChair.objects.update_or_create(session_id=session_id, category=category,
            defaults={'name': '、'.join(names)})
    for session in Session.objects.filter(pk__in=previous_session_ids - {item.pk for item in sessions.values()}):
        session.recalculate_end_time()
        session.recalculate_program_numbers()
    for session in sessions.values():
        session.recalculate_end_time()
    return created, updated, len(sessions)


def export_program(meeting):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'program'
    sheet.append(HEADERS)
    sheet.freeze_panes = 'I2'
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(HEADERS))}1'
    for cell_ in sheet[1]:
        cell_.fill = PatternFill('solid', fgColor='17324D')
        cell_.font = Font(color='FFFFFF', bold=True)
    for row in iter_program_rows(meeting):
        sheet.append(row)
        for exported_cell in sheet[sheet.max_row]:
            if isinstance(exported_cell.value, str):
                exported_cell.data_type = 's'
        if isinstance(row[9], date):
            sheet.cell(sheet.max_row, 10).number_format = 'yyyy/mm/dd'
    for column, width in {'A': 8, 'C': 18, 'E': 34, 'F': 24, 'G': 32,
                          'H': 32, 'I': 18, 'J': 18, 'K': 28, 'L': 20,
                          'M': 24, 'AH': 70}.items():
        sheet.column_dimensions[column].width = width
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
