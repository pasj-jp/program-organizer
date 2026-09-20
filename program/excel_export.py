from io import BytesIO
from math import ceil

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


WEEKDAYS = '月火水木金土日'
SLOT_MINUTES = 5
TITLE_FILL = PatternFill('solid', fgColor='17324D')
DAY_FILL = PatternFill('solid', fgColor='DCE8F1')
VENUE_FILL = PatternFill('solid', fgColor='EAF1F6')
SESSION_FILL = PatternFill('solid', fgColor='DCECF7')
SPECIAL_FILL = PatternFill('solid', fgColor='FFF1D5')
HOUR_BORDER = Side(style='thin', color='B7C8D6')
BLOCK_BORDER = Border(left=Side(style='medium', color='2773A4'),
                      right=HOUR_BORDER, top=HOUR_BORDER, bottom=HOUR_BORDER)


def format_clock(minute):
    return f'{minute // 60:02d}:{minute % 60:02d}'


def venue_positions(venue, first_minute):
    """Allocate columns after rounding session times to five-minute Excel rows."""
    occupied_until = []
    positions = {}
    for block in sorted(venue['blocks'], key=lambda item: (item['start'], item['end'], item['session'].pk)):
        start = max(0, (block['start'] - first_minute) // SLOT_MINUTES)
        end = max(start + 1, ceil((block['end'] - first_minute) / SLOT_MINUTES))
        lane = next((index for index, previous_end in enumerate(occupied_until) if previous_end <= start), None)
        if lane is None:
            lane = len(occupied_until)
            occupied_until.append(end)
        else:
            occupied_until[lane] = end
        positions[block['session'].pk] = (lane, start, end)
    return max(1, len(occupied_until)), positions


def style_header(cell, fill, size=10):
    cell.fill = fill
    cell.font = Font(name='Yu Gothic', size=size, bold=True,
                     color='FFFFFF' if fill is TITLE_FILL else '17324D')
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)


def draw_schedule_sheet(workbook, meeting, days, first_day_number):
    last_day_number = first_day_number + len(days) - 1
    sheet = workbook.create_sheet(f'日程{first_day_number}-{last_day_number}')
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = 'B5'
    first_minute = days[0]['first_minute']
    slot_count = ceil((days[0]['height'] / days[0]['pixels_per_minute']) / SLOT_MINUTES)
    for row in range(5, 5 + slot_count):
        sheet.row_dimensions[row].height = 7.5
    sheet.row_dimensions[1].height = 26
    sheet.row_dimensions[2].height = 19
    sheet.row_dimensions[3].height = 22
    sheet.row_dimensions[4].height = 30

    column = 1
    for day_index, day in enumerate(days):
        day_start = column
        venue_layout = []
        sheet.column_dimensions[get_column_letter(column)].width = 8
        time_column = column
        column += 1
        for venue in day['venues']:
            lanes, positions = venue_positions(venue, first_minute)
            venue_layout.append((venue, column, lanes, positions))
            for lane in range(lanes):
                sheet.column_dimensions[get_column_letter(column + lane)].width = 24
            column += lanes
        day_end = column - 1
        if day_end > day_start:
            sheet.merge_cells(start_row=3, start_column=day_start, end_row=3, end_column=day_end)
        day_cell = sheet.cell(3, day_start)
        day_cell.value = f"{day['date'].month}月{day['date'].day}日（{WEEKDAYS[day['date'].weekday()]}）"
        day_cell.data_type = 's'
        style_header(day_cell, DAY_FILL, 11)
        time_header = sheet.cell(4, time_column, '時刻')
        style_header(time_header, VENUE_FILL)
        for venue, start_column, lanes, positions in venue_layout:
            if lanes > 1:
                sheet.merge_cells(start_row=4, start_column=start_column,
                                  end_row=4, end_column=start_column + lanes - 1)
            venue_cell = sheet.cell(4, start_column, venue['name'])
            venue_cell.data_type = 's'
            style_header(venue_cell, VENUE_FILL)
        background = PatternFill('solid', fgColor='FFFFFF' if day_index % 2 == 0 else 'F7FAFC')
        for slot in range(slot_count):
            row = 5 + slot
            minute = first_minute + slot * SLOT_MINUTES
            if minute % 60 == 0:
                clock = sheet.cell(row, time_column, format_clock(minute))
                clock.font = Font(name='Yu Gothic', size=8, color='526070')
            for current_column in range(day_start, day_end + 1):
                cell = sheet.cell(row, current_column)
                cell.fill = background
                if minute % 60 == 0:
                    cell.border = Border(top=HOUR_BORDER)
        for venue, start_column, lanes, positions in venue_layout:
            for block in venue['blocks']:
                lane, start, end = positions[block['session'].pk]
                start = min(start, slot_count - 1)
                end = min(end, slot_count)
                row_start, row_end = 5 + start, 4 + max(start + 1, end)
                cell_column = start_column + lane
                if row_end > row_start:
                    sheet.merge_cells(start_row=row_start, start_column=cell_column,
                                      end_row=row_end, end_column=cell_column)
                session = block['session']
                name = f'{session.code} {session.name}' if session.code else session.name
                ending = session.end_time.strftime('%H:%M') if session.end_time else '未定'
                lines = [name, f"{session.start_time.strftime('%H:%M')}–{ending}"]
                if block['first_number']:
                    numbers = block['first_number']
                    if block['last_number'] != numbers:
                        numbers += '–' + block['last_number']
                    lines.append(numbers)
                cell = sheet.cell(row_start, cell_column, '\n'.join(lines))
                cell.data_type = 's'
                cell.fill = SESSION_FILL if block['talks'] else SPECIAL_FILL
                cell.font = Font(name='Yu Gothic', size=8, bold=True, color='17324D')
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                cell.border = BLOCK_BORDER
                if session.description:
                    cell.comment = Comment(session.description, 'プログラム編成')

    final_column = column - 1
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=final_column)
    title = sheet.cell(1, 1, meeting.name + ' タイムテーブル')
    title.data_type = 's'
    style_header(title, TITLE_FILL, 15)
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=final_column)
    subtitle = sheet.cell(2, 1, f'{meeting.start_date}〜{meeting.end_date}　{meeting.location}')
    subtitle.data_type = 's'
    subtitle.font = Font(name='Yu Gothic', size=9, color='526070')
    subtitle.alignment = Alignment(horizontal='center', vertical='center')
    sheet.print_area = f'A1:{get_column_letter(final_column)}{4 + slot_count}'
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.print_options.horizontalCentered = True
    sheet.oddHeader.center.text = meeting.name
    sheet.oddFooter.right.text = 'Page &P / &N'


def draw_talks_sheet(workbook, days):
    sheet = workbook.create_sheet('演題一覧')
    sheet.sheet_view.showGridLines = False
    headers = ('日付', '発表時刻', '部屋', 'セッションコード', 'セッション名', 'プログラム番号', '演題', '登壇者')
    sheet.append(headers)
    for cell in sheet[1]:
        style_header(cell, TITLE_FILL)
    for day in days:
        for block in day['sessions']:
            for row in block['talk_rows']:
                talk = row['talk']
                sheet.append((day['date'].isoformat(), f"{row['start']}–{row['end']}",
                              block['venue_name'], block['session'].code or '', block['session'].name,
                              talk.program_number or '', talk.title,
                              '、'.join(str(author) for author in row['presenters'])))
                for cell in sheet[sheet.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = 's'
                if row['withdrawn']:
                    sheet.cell(sheet.max_row, 7).font = Font(name='Yu Gothic', strike=True, color='8A959F')
    for index, width in enumerate((14, 17, 22, 20, 28, 18, 60, 35), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:H{max(1, sheet.max_row)}'
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0


def draw_unscheduled_sheet(workbook, sessions):
    if not sessions:
        return
    sheet = workbook.create_sheet('日時未設定')
    sheet.append(('セッションコード', 'セッション名', '日付', '開始時刻', '部屋', '備考'))
    for cell in sheet[1]:
        style_header(cell, TITLE_FILL)
    for session in sessions:
        sheet.append((session.code or '', session.name,
                      session.date.isoformat() if session.date else '',
                      session.start_time.strftime('%H:%M') if session.start_time else '',
                      session.venue.name if session.venue else '', session.description))
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    for index, width in enumerate((20, 35, 15, 14, 25, 50), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = 'A2'


def render_timetable_excel(meeting, days, unscheduled):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index in range(0, len(days), 3):
        draw_schedule_sheet(workbook, meeting, days[index:index + 3], index + 1)
    draw_talks_sheet(workbook, days)
    draw_unscheduled_sheet(workbook, unscheduled)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
