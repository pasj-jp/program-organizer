import json
from io import BytesIO
from datetime import date, time
from openpyxl import Workbook, load_workbook
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from .forms import SessionForm
from .models import AnnualMeeting, Presentation, Session, SessionChair, Venue
from .timetable import build_timetable
from .program_excel import HEADERS, import_program, export_program, read_program


class OrganizerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('editor', password='secret', is_staff=True)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='program'))
        self.client.force_login(self.user)
        self.meeting = AnnualMeeting.objects.create(name='年会', abbreviation='PASJ2026',
            start_date=date(2026, 9, 19), end_date=date(2026, 9, 21), location='東京')
        self.session = Session.objects.create(name='加速器', code='FRO', annual_meeting=self.meeting,
            start_time=time(10, 0), minutes_per_presentation=20)
        self.first = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A1', title='第一演題')
        self.second = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A2', title='第二演題')

    def move(self, presentation, session_id, order):
        return self.client.post(reverse('move_presentation'),
                                json.dumps({'presentation_id': presentation.pk, 'session_id': session_id,
                                            'meeting_id': self.meeting.pk, 'order': order}),
                                content_type='application/json')

    def test_presentations_are_scoped_to_meeting(self):
        other = AnnualMeeting.objects.create(name='翌年会', abbreviation='PASJ2027',
            start_date=date(2027, 9, 19), end_date=date(2027, 9, 21), location='大阪')
        self.assertNotContains(self.client.get(reverse('organize', args=[2027])), '第一演題')
        other_talk = Presentation.objects.create(annual_meeting=other, submission_number='A1', title='翌年の演題')
        self.assertContains(self.client.get(reverse('organize', args=[2027])), '翌年の演題')
        self.assertNotContains(self.client.get(reverse('organize', args=[2026])), '翌年の演題')
        self.assertEqual(self.move(other_talk, self.session.pk, [other_talk.pk]).status_code, 400)
        self.assertEqual(self.move(self.first, None, [self.first.pk, self.second.pk, other_talk.pk]).status_code, 409)

    def test_abstract_import_can_reuse_submission_number_in_another_meeting(self):
        other = AnnualMeeting.objects.create(name='翌年会', abbreviation='PASJ2027',
            start_date=date(2027, 9, 19), end_date=date(2027, 9, 21), location='大阪')
        book = Workbook()
        sheet = book.active
        sheet.append(['演題登録番号', '題目', '発表形式', '連名者[1]区分'])
        sheet.append(['A1', '翌年の演題', '口頭発表', ''])
        output = BytesIO()
        book.save(output)
        output.seek(0)
        output.name = 'abstract.xlsx'
        response = self.client.post(reverse('import_abstract_excel', args=[other.year]), {'file': output})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Presentation.objects.get(annual_meeting=other, submission_number='A1').title, '翌年の演題')
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, '第一演題')

    def test_public_timetable_is_read_only_and_editor_has_tabs(self):
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        public = self.client.get(reverse('timetable', args=[2026]))
        self.assertEqual(public.status_code, 200)
        self.assertFalse(public.context['can_move_sessions'])
        self.assertNotContains(public, 'class="session-block draggable-session"')
        self.assertNotContains(public, 'timetable-csrf')
        self.assertNotContains(public, reverse('move_session_time', args=[2026]))
        self.assertNotContains(public, 'aria-label="編成画面"')
        self.assertEqual(self.client.get(reverse('timetable_legacy', args=[2026])).status_code, 200)
        board = self.client.get(reverse('organize', args=[2026]))
        self.assertContains(board, 'aria-current="page">セッション編成</a>')
        editor = self.client.get(reverse('organize', args=[2026]) + '?tab=timetable')
        self.assertEqual(editor.status_code, 200)
        self.assertTrue(editor.context['can_move_sessions'])
        self.assertContains(editor, 'aria-current="page">タイムテーブル</a>')
        self.assertContains(editor, 'draggable-session')
        self.assertContains(editor, reverse('move_session_time', args=[2026]))
        self.client.logout()
        self.assertEqual(self.client.get(reverse('timetable', args=[2026])).status_code, 200)
        denied = self.client.get(reverse('organize', args=[2026]) + '?tab=timetable')
        self.assertRedirects(denied, '/login/?next=/organize/2026/%3Ftab%3Dtimetable')
        move_denied = self.client.post(reverse('move_session_time', args=[2026]),
            json.dumps({'session_id': self.session.pk}), content_type='application/json')
        self.assertEqual(move_denied.status_code, 302)
        self.assertTrue(move_denied['Location'].startswith('/login/?next='))
        self.assertRedirects(self.client.post(reverse('login'), {
            'username': 'editor', 'password': 'secret', 'next': reverse('organize', args=[2026]),
        }), reverse('organize', args=[2026]))

    def test_nonstaff_account_with_permissions_can_edit(self):
        editor = get_user_model().objects.create_user('organizer', password='secret')
        editor.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='program', codename__in=('view_session', 'view_presentation', 'change_session')))
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse('organize', args=[2026])).status_code, 200)
        self.assertTrue(self.client.get(reverse('organize', args=[2026]) + '?tab=timetable').context['can_move_sessions'])

    def test_program_excel_import_and_export_roundtrip(self):
        book = Workbook()
        sheet = book.active
        sheet.append(HEADERS)
        def add(number, session_name, format_name, category, program_number, day, slot, room, chair=''):
            row = [None] * len(HEADERS)
            for column, value in {3: number, 5: format_name, 6: session_name, 7: category,
                                  9: program_number, 10: day, 11: slot, 12: room,
                                  13: chair, 34: f'{number}の題目', 37: category}.items():
                row[column - 1] = value
            sheet.append(row)
        add('A1', '口頭発表①', '口頭発表 [Oral]', '加速器', 'FRO01', date(2026, 9, 19),
            '10:00-10:40', 'A会場', '山田')
        add('A2', '口頭発表①', '口頭発表 [Oral]', 'ビーム', 'FRO02', date(2026, 9, 19),
            '10:00-10:40', 'A会場', '佐藤')
        add('P1', 'ポスターセッション①', 'ポスター発表 [Poster]', '加速器', 'P001',
            date(2026, 9, 19), '12:00-13:00', '展示室')
        add('P2', 'ポスターセッション②', 'ポスター発表 [Poster]', '加速器', 'P002',
            date(2026, 9, 20), '12:00-13:00', '展示室')
        add('F1', 'ポスターセッション①②', '施設技術報告ポスター [Status report]', '加速器',
            'FP001', '9月19日・20日', '12:00-13:00/12:00-13:00', '展示室')
        output = BytesIO()
        book.save(output)
        output.seek(0)
        output.name = 'program.xlsx'
        response = self.client.post(reverse('import_program_excel', args=[self.meeting.year]), {'file': output})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Presentation.objects.filter(session__annual_meeting=self.meeting).count(), 5)
        self.assertEqual(Session.objects.filter(annual_meeting=self.meeting, kind=Session.Kind.ORAL).count(), 1)
        oral = Session.objects.get(annual_meeting=self.meeting, kind=Session.Kind.ORAL)
        self.assertEqual(dict(oral.chairs.values_list('category', 'name')), {'加速器': '山田', 'ビーム': '佐藤'})
        report = Session.objects.get(annual_meeting=self.meeting, kind=Session.Kind.FACILITY_REPORT)
        self.assertNotEqual(report.poster_session_one_id, report.poster_session_two_id)
        exported = self.client.get(reverse('export_program_excel', args=[self.meeting.year]))
        self.assertEqual(exported.status_code, 200)
        self.assertIn('filename="program.xlsx"', exported['Content-Disposition'])
        rows = list(load_workbook(BytesIO(exported.content), read_only=True, data_only=True).active.values)
        self.assertEqual(len(rows[0]), len(HEADERS))
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(read_program(BytesIO(exported.content), self.meeting)), 4)
        reordered = Workbook()
        order = list(range(len(HEADERS)))
        order[2], order[33] = order[33], order[2]
        for row in rows:
            reordered.active.append([row[index] for index in order])
        reordered_bytes = BytesIO()
        reordered.save(reordered_bytes)
        reordered_bytes.seek(0)
        self.assertEqual(len(read_program(reordered_bytes, self.meeting)), 4)

    def test_abstract_import_button_in_unassigned_panel(self):
        board = self.client.get(reverse('organize', args=[self.meeting.year]))
        self.assertContains(board, 'data-open-dialog="abstract-import-dialog"')
        self.assertContains(board, 'aria-label="abstract.xlsx をインポート"')
        book = Workbook()
        sheet = book.active
        sheet.append(['演題登録番号', '題目', '発表形式', '連名者[1]区分', '連名者[1]姓', '連名者[1]名'])
        sheet.append(['A3', '追加演題', '口頭発表 [Oral]', '登壇者', '山田', '太郎'])
        output = BytesIO()
        book.save(output)
        output.seek(0)
        output.name = 'abstract.xlsx'
        response = self.client.post(reverse('import_abstract_excel', args=[self.meeting.year]), {'file': output})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(Presentation.objects.get(submission_number='A3').session_id)
        self.assertContains(self.client.get(reverse('organize', args=[self.meeting.year])), '追加演題')

    def test_program_import_rejects_wrong_meeting_date_without_changes(self):
        book = Workbook()
        sheet = book.active
        sheet.append(HEADERS)
        row = [None] * len(HEADERS)
        for column, value in {3: 'A1', 5: '口頭発表 [Oral]', 6: '口頭発表①',
                              10: date(2025, 8, 26), 11: '10:00-10:20',
                              12: 'A会場', 34: '第一演題'}.items():
            row[column - 1] = value
        sheet.append(row)
        output = BytesIO()
        book.save(output)
        output.seek(0)
        output.name = 'program.xlsx'
        response = self.client.post(reverse('import_program_excel', args=[self.meeting.year]), {'file': output})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '会期外です')
        self.assertEqual(Session.objects.count(), 1)
        self.assertIsNone(Presentation.objects.get(pk=self.first.pk).session_id)

    def test_board_actions_use_icons_and_create_dialog_keeps_errors(self):
        board = self.client.get(reverse('organize', args=[self.meeting.year]))
        self.assertContains(board, 'data-open-dialog="session-create-dialog"')
        self.assertContains(board, 'data-open-dialog="program-import-dialog"')
        self.assertContains(board, 'data-open-dialog="abstract-import-dialog"')
        self.assertContains(board, 'aria-label="program.xlsx をエクスポート"')
        self.assertContains(board, '<dialog id="session-create-dialog"')
        self.assertNotContains(board, '<details class="create"')
        invalid = self.client.post(reverse('create_session', args=[self.meeting.year]), {
            'name': '定員なし', 'kind': Session.Kind.ORAL,
            'date': '2026-09-19', 'start_time': '11:00',
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, 'data-open-on-error="true"')
        self.assertContains(invalid, '講演数を1件以上指定してください。')

    def test_confirmed_category_defaults_on_assignment_and_can_be_changed(self):
        self.first.category_first = '加速器技術'
        self.first.category_second = 'ビーム物理'
        self.first.save(update_fields=['category_first', 'category_second'])
        moved = self.move(self.first, self.session.pk, [self.first.pk])
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['confirmed_category'], '加速器技術')
        self.first.refresh_from_db()
        self.assertEqual(self.first.confirmed_category, '加速器技術')
        board = self.client.get(reverse('organize', args=[2026]))
        self.assertContains(board, '<span class="program-number">FRO01</span><span class="assigned-category"><span class="category-value">加速器技術</span></span>', html=True)
        url = reverse('edit_presentation', args=[self.first.pk])
        response = self.client.post(url, {
            'title': self.first.title, 'category_first': '加速器技術',
            'category_second': 'ビーム物理', 'confirmed_category': 'ビーム物理',
            'status': Presentation.Status.ACTIVE,
        })
        self.assertEqual(response.status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.confirmed_category, 'ビーム物理')
        self.assertContains(self.client.get(reverse('organize', args=[2026])), '<span class="category-value">ビーム物理</span>', html=True)
        self.assertEqual(self.move(self.first, self.session.pk, [self.first.pk]).status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.confirmed_category, 'ビーム物理')
        self.assertEqual(self.move(self.first, None, [self.second.pk, self.first.pk]).status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.confirmed_category, '')

    def test_oral_session_has_chair_for_each_confirmed_category(self):
        oral = Session.objects.create(name='口頭', kind=Session.Kind.ORAL, talk_limit=2,
            annual_meeting=self.meeting, date=date(2026, 9, 19), start_time=time(11, 0))
        for talk, category in ((self.first, '加速器技術'), (self.second, 'ビーム物理')):
            talk.presentation_format = '口頭発表'
            talk.category_first = category
            talk.save(update_fields=['presentation_format', 'category_first'])
        self.assertEqual(self.move(self.first, oral.pk, [self.first.pk]).status_code, 200)
        self.assertEqual(self.move(self.second, oral.pk, [self.first.pk, self.second.pk]).status_code, 200)
        url = reverse('edit_session_chairs', args=[oral.pk])
        self.assertContains(self.client.get(url), '加速器技術')
        self.assertEqual(self.client.post(url, {'chair_0': '山田', 'chair_1': '佐藤'}).status_code, 200)
        self.assertEqual(dict(oral.chairs.values_list('category', 'name')),
                         {'ビーム物理': '山田', '加速器技術': '佐藤'})
        self.assertContains(self.client.get(reverse('organize', args=[2026])), '座長を編集')
        self.assertContains(self.client.get(reverse('timetable', args=[2026])), '座長（ビーム物理）: 山田')
        self.assertEqual(self.client.get(reverse('edit_session_chairs', args=[self.session.pk])).status_code, 404)

    def test_move_and_reorder_and_unassign(self):
        self.assertEqual(self.move(self.first, self.session.pk, [self.first.pk]).status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(10, 20))
        self.first.refresh_from_db()
        self.assertEqual(self.first.program_number, 'FRO01')
        self.assertEqual(self.move(self.second, self.session.pk, [self.second.pk, self.first.pk]).status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(10, 40))
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual((self.second.session_order, self.first.session_order), (1, 2))
        self.assertEqual((self.second.program_number, self.first.program_number), ('FRO01', 'FRO02'))
        self.assertEqual(self.move(self.first, None, [self.first.pk]).status_code, 200)
        self.first.refresh_from_db()
        self.assertIsNone(self.first.session_id)
        self.assertIsNone(self.first.program_number)
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(10, 20))
        self.second.refresh_from_db()
        self.assertEqual(self.second.program_number, 'FRO01')

    def test_withdrawal_preserves_program_numbers(self):
        self.move(self.first, self.session.pk, [self.first.pk])
        self.move(self.second, self.session.pk, [self.first.pk, self.second.pk])
        response = self.move(self.second, self.session.pk, [self.second.pk, self.first.pk])
        self.assertEqual(response.status_code, 200)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual((self.second.program_number, self.first.program_number), ('FRO01', 'FRO02'))
        self.second.status = Presentation.Status.WITHDRAWN
        self.second.save(update_fields=['status'])
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.program_number, 'FRO02')
        self.assertEqual(self.second.program_number, 'FRO01')
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(10, 40))
        third = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A3', title='第三演題')
        self.assertEqual(self.move(third, self.session.pk,
                                   [self.second.pk, self.first.pk, third.pk]).status_code, 200)
        self.second.refresh_from_db()
        self.assertEqual(self.second.program_number, 'FRO01')
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(11, 0))

    def test_session_code_change_renumbers(self):
        self.move(self.first, self.session.pk, [self.first.pk])
        self.session.code = 'XYZ'
        self.session.save(update_fields=['code'])
        self.first.refresh_from_db()
        self.assertEqual(self.first.program_number, 'XYZ01')
        self.session.code = None
        self.session.save(update_fields=['code'])
        self.first.refresh_from_db()
        self.assertIsNone(self.first.program_number)

    def test_deleting_presentation_renumbers_session(self):
        self.move(self.first, self.session.pk, [self.first.pk])
        self.move(self.second, self.session.pk, [self.first.pk, self.second.pk])
        self.first.delete()
        self.second.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(self.second.program_number, 'FRO01')
        self.assertEqual(self.session.end_time, time(10, 20))

    def test_timetable_groups_by_day_and_venue_and_shows_talks(self):
        venue = Venue.objects.create(name='A会場', annual_meeting=self.meeting)
        self.session.date = date(2026, 9, 19)
        self.session.venue = venue
        self.session.save(update_fields=['date', 'venue'])
        self.move(self.first, self.session.pk, [self.first.pk])
        self.move(self.second, self.session.pk, [self.first.pk, self.second.pk])
        response = self.client.get(reverse('timetable', args=[2026]))
        self.assertContains(response, 'A会場')
        self.assertContains(response, 'FRO01–FRO02')
        self.assertContains(response, '10:00–10:20')
        self.assertContains(response, '10:20–10:40')
        self.assertContains(response, '第一演題')
        self.assertContains(response, '第二演題')
        self.assertContains(response, f'#session-{self.session.pk}')
        self.assertContains(response, 'class="day" data-date=', count=3)
        self.assertContains(response, 'data-date="2026-09-20"')
        self.assertNotContains(response, 'role="tab"')
        self.assertContains(self.client.get(reverse('timetable_index')), '/2026/')

    def test_withdrawn_talk_keeps_its_timetable_slot(self):
        self.move(self.first, self.session.pk, [self.first.pk])
        self.first.refresh_from_db()
        self.first.status = Presentation.Status.WITHDRAWN
        self.first.save(update_fields=['status'])
        board = self.client.get(reverse('organize', args=[2026]))
        self.assertContains(board, 'class="card withdrawn"')
        self.assertContains(board, 'data-status="withdrawn"')
        self.assertContains(board, '第一演題')
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        response = self.client.get(reverse('timetable', args=[2026]))
        self.assertContains(response, 'class="withdrawn-row"')
        self.assertContains(response, '10:00–10:20')
        self.assertContains(response, '第一演題')
        self.assertContains(response, 'FRO01')
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(10, 20))
        moved = self.client.post(reverse('move_session_time', args=[2026]),
            json.dumps({'session_id': self.session.pk, 'start_time': '11:00',
                        'expected_start': '10:00', 'expected_duration': 20}),
            content_type='application/json')
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['end_time'], '11:20')

    def test_empty_session_duration_supports_breaks(self):
        break_session = Session.objects.create(
            name='昼休憩', annual_meeting=self.meeting, date=date(2026, 9, 19),
            start_time=time(12, 0), empty_duration_minutes=60,
        )
        self.assertEqual(break_session.end_time, time(13, 0))
        response = self.client.get(reverse('timetable', args=[2026]))
        self.assertContains(response, '昼休憩')
        self.assertContains(response, '12:00–13:00')

    def test_dragging_session_time_preserves_duration_and_shifts_talk_times(self):
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        self.move(self.first, self.session.pk, [self.first.pk])
        self.move(self.second, self.session.pk, [self.first.pk, self.second.pk])
        self.first.refresh_from_db()
        self.first.start_time = time(10, 0)
        self.first.end_time = time(10, 20)
        self.first.save(update_fields=['start_time', 'end_time'])
        response = self.client.post(reverse('move_session_time', args=[2026]),
            json.dumps({'session_id': self.session.pk, 'start_time': '11:15',
                        'expected_start': '10:00', 'expected_duration': 40}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.first.refresh_from_db()
        self.assertEqual((self.session.start_time, self.session.end_time), (time(11, 15), time(11, 55)))
        self.assertEqual((self.first.start_time, self.first.end_time), (time(11, 15), time(11, 35)))

    def test_dragging_session_time_rejects_stale_and_unauthorized_changes(self):
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        payload = {'session_id': self.session.pk, 'start_time': '11:00',
                   'expected_start': '09:00', 'expected_duration': 30}
        url = reverse('move_session_time', args=[2026])
        self.assertEqual(self.client.post(url, json.dumps(payload), content_type='application/json').status_code, 409)
        self.user.user_permissions.remove(Permission.objects.get(codename='change_session', content_type__app_label='program'))
        payload['expected_start'] = '10:00'
        self.assertEqual(self.client.post(url, json.dumps(payload), content_type='application/json').status_code, 403)

    def test_dragging_session_to_another_day_and_venue(self):
        first_venue = Venue.objects.create(name='A会場', annual_meeting=self.meeting)
        second_venue = Venue.objects.create(name='B会場', annual_meeting=self.meeting)
        self.session.date = date(2026, 9, 19)
        self.session.venue = first_venue
        self.session.save(update_fields=['date', 'venue'])
        self.move(self.first, self.session.pk, [self.first.pk])
        self.first.refresh_from_db()
        self.first.start_time = time(10, 0)
        self.first.end_time = time(10, 20)
        self.first.save(update_fields=['start_time', 'end_time'])
        response = self.client.post(reverse('move_session_time', args=[2026]),
            json.dumps({'session_id': self.session.pk, 'date': '2026-09-20',
                        'venue_id': second_venue.pk, 'start_time': '11:00',
                        'expected_date': '2026-09-19', 'expected_venue_id': first_venue.pk,
                        'expected_start': '10:00', 'expected_duration': 20}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.first.refresh_from_db()
        self.assertEqual((self.session.date, self.session.venue, self.session.start_time, self.session.end_time),
                         (date(2026, 9, 20), second_venue, time(11, 0), time(11, 20)))
        self.assertEqual((self.first.start_time, self.first.end_time), (time(11, 0), time(11, 20)))
        page = self.client.get(reverse('timetable', args=[2026]))
        days = page.context['days']
        self.assertEqual([venue['name'] for venue in days[0]['venues']],
                         [venue['name'] for venue in days[1]['venues']])
        self.assertEqual(len(days[0]['sessions']), 0)
        self.assertEqual(len(days[1]['sessions']), 1)
        invalid = self.client.post(reverse('move_session_time', args=[2026]),
            json.dumps({'session_id': self.session.pk, 'date': '2026-09-22',
                        'venue_id': second_venue.pk, 'start_time': '11:00',
                        'expected_date': '2026-09-20', 'expected_venue_id': second_venue.pk,
                        'expected_start': '11:00', 'expected_duration': 20}),
            content_type='application/json')
        self.assertEqual(invalid.status_code, 400)

    def test_cannot_move_session_to_another_meetings_room(self):
        other = AnnualMeeting.objects.create(name='別の年会', abbreviation='PASJ2027',
            start_date=date(2027, 1, 1), end_date=date(2027, 1, 2), location='大阪')
        room = Venue.objects.create(name='大会議室', annual_meeting=other)
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        response = self.client.post(reverse('move_session_time', args=[self.meeting.year]),
            json.dumps({'session_id': self.session.pk, 'date': '2026-09-19',
                        'venue_id': room.pk, 'start_time': '11:00',
                        'expected_start': '10:00', 'expected_duration': 30}),
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_rejects_stale_order(self):
        response = self.move(self.first, self.session.pk, [self.first.pk, self.second.pk])
        self.assertEqual(response.status_code, 409)
        self.first.refresh_from_db()
        self.assertIsNone(self.first.session_id)

    def test_requires_change_permission(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.move(self.first, self.session.pk, [self.first.pk]).status_code, 403)

    def test_board_displays_cards(self):
        self.first.presentation_format = '口頭発表'
        self.first.save(update_fields=['presentation_format'])
        self.second.presentation_format = 'ポスター発表'
        self.second.save(update_fields=['presentation_format'])
        self.first.category_first = '加速器技術'
        self.first.category_second = 'ビーム物理'
        self.first.save(update_fields=['category_first', 'category_second'])
        self.second.category_first = '加速器技術'
        self.second.save(update_fields=['category_first'])
        response = self.client.get(reverse('organize', args=[self.meeting.year]))
        self.assertContains(response, '第一演題')
        self.assertContains(response, '加速器')
        self.assertContains(response, '<section class="column unassigned">')
        self.assertContains(response, '<label for="format-filter">発表形式</label>')
        self.assertContains(response, '<option value="format:口頭発表">口頭発表</option>')
        self.assertContains(response, '<option value="format:ポスター発表">ポスター発表</option>')
        self.assertContains(response, 'data-format="口頭発表"')
        self.assertContains(response, '<select id="category-filter">')
        self.assertContains(response, '<option value="加速器技術">加速器技術</option>', count=1)
        self.assertContains(response, '<option value="ビーム物理">ビーム物理</option>')
        self.assertContains(response, 'data-category-first="加速器技術" data-category-second="ビーム物理"')
        self.assertContains(response, '第1希望: 加速器技術')
        self.assertContains(response, '第2希望: ビーム物理')
        self.assertContains(response, 'class="edit-presentation"')
        self.assertNotContains(response, reverse('admin:program_presentation_change', args=[self.first.pk]))
        self.assertContains(response, 'src="/static/program/organize.js?v=6"')
        self.assertContains(response, 'data-move-url="/organize/move/"')

    def test_presentation_edit_popup_saves_and_validates(self):
        url = reverse('edit_presentation', args=[self.first.pk])
        self.assertContains(self.client.get(url), 'id="presentation-edit-form"')
        invalid = self.client.post(url, {'title': '', 'status': Presentation.Status.ACTIVE})
        self.assertEqual(invalid.status_code, 400)
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, '第一演題')
        saved = self.client.post(url, {
            'title': '変更後の演題', 'title_en': 'Updated talk',
            'category_first': '加速器', 'category_second': 'ビーム',
            'presentation_format': '口頭発表', 'status': Presentation.Status.ACTIVE,
            'organizer_note': '確認済み',
        })
        self.assertEqual(saved.status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual((self.first.title, self.first.category_first, self.first.category_second),
                         ('変更後の演題', '加速器', 'ビーム'))
        self.user.user_permissions.remove(Permission.objects.get(codename='change_presentation', content_type__app_label='program'))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'title': '再変更'}).status_code, 403)

    def test_session_cards_can_be_reordered(self):
        other = Session.objects.create(name='ビーム', annual_meeting=self.meeting)
        url = reverse('reorder_sessions', args=[self.meeting.year])
        response = self.client.post(url, json.dumps({'order': [other.pk, self.session.pk]}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        board = self.client.get(reverse('organize', args=[self.meeting.year]))
        self.assertContains(board, 'data-reorder-url="/organize/2026/reorder-sessions/"')
        self.assertLess(board.content.index(b'data-session-id="' + str(other.pk).encode()),
                        board.content.index(b'data-session-id="' + str(self.session.pk).encode()))
        invalid = self.client.post(url, json.dumps({'order': [self.session.pk]}),
                                   content_type='application/json')
        self.assertEqual(invalid.status_code, 409)
        self.user.user_permissions.remove(Permission.objects.get(codename='change_session', content_type__app_label='program'))
        denied = self.client.post(url, json.dumps({'order': [self.session.pk, other.pk]}),
                                  content_type='application/json')
        self.assertEqual(denied.status_code, 403)

    def test_oral_session_reserves_capacity_and_rejects_extra_talk(self):
        invalid = self.client.post(reverse('create_session', args=[2026]), {
            'name': '定員なし', 'kind': Session.Kind.ORAL,
            'date': '2026-09-19', 'start_time': '11:00',
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, '講演数を1件以上指定してください。')
        form = SessionForm(data={
            'name': '口頭枠', 'annual_meeting': self.meeting.pk, 'kind': Session.Kind.ORAL,
            'date': '2026-09-19', 'start_time': '11:00',
            'minutes_per_presentation': 20, 'talk_limit': 2,
        }, meeting_id=self.meeting.pk)
        self.assertTrue(form.is_valid(), form.errors)
        oral = form.save()
        self.assertEqual(oral.end_time, time(11, 40))
        days, _ = build_timetable(self.meeting)
        oral_block = next(block for day in days for block in day['sessions'] if block['session'].pk == oral.pk)
        self.assertEqual(oral_block['duration'], 40)
        self.first.presentation_format = '口頭発表 [Oral]'
        self.first.save(update_fields=['presentation_format'])
        self.second.presentation_format = '口頭発表 [Oral]'
        self.second.save(update_fields=['presentation_format'])
        self.assertEqual(self.move(self.first, oral.pk, [self.first.pk]).status_code, 200)
        mismatched_edit = self.client.post(reverse('edit_presentation', args=[self.first.pk]), {
            'title': self.first.title, 'presentation_format': 'ポスター発表 [Poster]',
            'status': Presentation.Status.ACTIVE,
        })
        self.assertEqual(mismatched_edit.status_code, 400)
        self.assertContains(mismatched_edit, '発表形式がセッションと一致しません。', status_code=400)
        self.assertEqual(self.move(self.second, oral.pk, [self.first.pk, self.second.pk]).status_code, 200)
        third = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A3', title='第三演題',
                                             presentation_format='口頭発表 [Oral]')
        full = self.move(third, oral.pk, [self.first.pk, self.second.pk, third.pk])
        self.assertEqual(full.status_code, 400)
        self.assertIn('満員', full.json()['error'])
        poster_talk = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A4', title='ポスター演題',
                                                   presentation_format='ポスター発表 [Poster]')
        mismatch = self.move(poster_talk, oral.pk, [self.first.pk, self.second.pk, poster_talk.pk])
        self.assertEqual(mismatch.status_code, 400)
        self.first.status = Presentation.Status.WITHDRAWN
        self.first.save(update_fields=['status'])
        self.assertEqual(self.move(third, oral.pk,
                                   [self.first.pk, self.second.pk, third.pk]).status_code, 400)
        oral.refresh_from_db()
        self.assertEqual(oral.end_time, time(11, 40))

    def test_facility_report_appears_in_two_poster_slots(self):
        poster_form = SessionForm(data={
            'name': 'ポスター前半', 'annual_meeting': self.meeting.pk,
            'kind': Session.Kind.POSTER, 'date': '2026-09-19',
            'start_time': '10:00', 'slot_duration_minutes': 60,
        }, meeting_id=self.meeting.pk)
        self.assertTrue(poster_form.is_valid(), poster_form.errors)
        poster_one = poster_form.save()
        poster_two = Session.objects.create(name='ポスター後半', kind=Session.Kind.POSTER,
            annual_meeting=self.meeting, date=date(2026, 9, 20), start_time=time(13, 0),
            slot_duration_minutes=90)
        report_data = {
            'name': '施設報告', 'annual_meeting': self.meeting.pk,
            'kind': Session.Kind.FACILITY_REPORT,
            'poster_session_one': poster_one.pk, 'poster_session_two': poster_two.pk,
        }
        form = SessionForm(data=report_data, meeting_id=self.meeting.pk)
        self.assertTrue(form.is_valid(), form.errors)
        created = self.client.post(reverse('create_session', args=[2026]), report_data)
        self.assertRedirects(created, reverse('organize', args=[2026]))
        report = Session.objects.get(name='施設報告')
        self.first.presentation_format = '施設技術報告ポスター [Status report]'
        self.first.save(update_fields=['presentation_format'])
        self.assertEqual(self.move(self.first, report.pk, [self.first.pk]).status_code, 200)
        days, _ = build_timetable(self.meeting)
        rows = [row for day in days for block in day['sessions'] for row in block['talk_rows']
                if row['talk'].pk == self.first.pk]
        self.assertEqual([(row['start'], row['end']) for row in rows],
                         [('10:00', '11:00'), ('13:00', '14:30')])
        self.assertEqual(report.end_time, None)
        poster_one.refresh_from_db()
        poster_two.refresh_from_db()
        self.assertEqual((poster_one.end_time, poster_two.end_time), (time(11, 0), time(14, 30)))
        poster_one.full_clean()
        poster_one.kind = Session.Kind.OTHER
        with self.assertRaises(ValidationError):
            poster_one.full_clean()
        poster_one.kind = Session.Kind.POSTER
        duplicate = SessionForm(data={
            'name': '誤った施設報告', 'annual_meeting': self.meeting.pk,
            'kind': Session.Kind.FACILITY_REPORT, 'minutes_per_presentation': 20,
            'poster_session_one': poster_one.pk, 'poster_session_two': poster_one.pk,
        }, meeting_id=self.meeting.pk)
        self.assertFalse(duplicate.is_valid())
        other_meeting = AnnualMeeting.objects.create(name='別年会', abbreviation='PASJ2027',
            start_date=date(2027, 1, 1), end_date=date(2027, 1, 2), location='大阪')
        other_poster = Session.objects.create(name='別年会ポスター', kind=Session.Kind.POSTER,
            annual_meeting=other_meeting, slot_duration_minutes=60)
        cross_meeting = SessionForm(data={
            'name': '誤った施設報告', 'annual_meeting': self.meeting.pk,
            'kind': Session.Kind.FACILITY_REPORT, 'minutes_per_presentation': 20,
            'poster_session_one': poster_one.pk, 'poster_session_two': other_poster.pk,
        }, meeting_id=self.meeting.pk)
        self.assertFalse(cross_meeting.is_valid())
        second_talk = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A3', title='追加報告',
            presentation_format='施設技術報告ポスター [Status report]')
        self.assertEqual(self.move(second_talk, report.pk, [self.first.pk, second_talk.pk]).status_code, 200)
        poster_one.refresh_from_db()
        self.assertEqual(poster_one.end_time, time(11, 0))
        moved = self.client.post(reverse('move_session_time', args=[2026]),
            json.dumps({'session_id': poster_one.pk, 'start_time': '11:00',
                        'expected_start': '10:00', 'expected_duration': 60}),
            content_type='application/json')
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['end_time'], '12:00')
        self.second.presentation_format = 'ポスター発表 [Poster]'
        self.second.save(update_fields=['presentation_format'])
        self.assertEqual(self.move(self.second, poster_one.pk, [self.second.pk]).status_code, 200)
        extra_poster = Presentation.objects.create(annual_meeting=self.meeting, submission_number='A4', title='追加ポスター',
            presentation_format='ポスター発表 [Poster]')
        self.assertEqual(self.move(extra_poster, poster_one.pk,
                                   [self.second.pk, extra_poster.pk]).status_code, 200)
        poster_one.refresh_from_db()
        self.assertEqual(poster_one.end_time, time(12, 0))


class AnnualMeetingTests(TestCase):
    def setUp(self):
        self.meeting = AnnualMeeting.objects.create(
            name='第1回年会', abbreviation='PASJ2026', start_date=date(2026, 9, 19),
            end_date=date(2026, 9, 21), location='東京国際会議場',
        )

    def test_session_date_choices_and_validation(self):
        form = SessionForm()
        self.assertEqual([value for value, _ in form.fields['date'].choices],
                         ['', '2026-09-19', '2026-09-20', '2026-09-21'])
        valid = SessionForm(data={'name': '加速器', 'annual_meeting': self.meeting.pk,
                                  'kind': Session.Kind.ORAL, 'date': '2026-09-20',
                                  'start_time': '10:00', 'talk_limit': '3',
                                  'minutes_per_presentation': '15'})
        self.assertTrue(valid.is_valid(), valid.errors)
        invalid = SessionForm(data={'name': '加速器', 'annual_meeting': self.meeting.pk,
                                    'kind': Session.Kind.ORAL, 'date': '2026-09-22',
                                    'start_time': '10:00', 'talk_limit': '3',
                                    'minutes_per_presentation': '15'})
        self.assertFalse(invalid.is_valid())
        session = Session(name='加速器', annual_meeting=self.meeting, date=date(2026, 9, 22))
        with self.assertRaises(ValidationError):
            session.full_clean()

    def test_meeting_date_order(self):
        meeting = AnnualMeeting(name='逆転', start_date=date(2026, 9, 21),
                                end_date=date(2026, 9, 19), location='東京')
        with self.assertRaises(ValidationError):
            meeting.full_clean()
        meeting.abbreviation = 'PASJ2026'
        with self.assertRaises(ValidationError):
            meeting.full_clean()

    def test_abbreviation_is_unique_and_url_safe(self):
        meeting = AnnualMeeting(name='別の年会', abbreviation='bad/path',
                                start_date=date(2027, 1, 1), end_date=date(2027, 1, 2), location='大阪')
        with self.assertRaises(ValidationError):
            meeting.full_clean()

    def test_meeting_year_is_unique_in_admin_and_database(self):
        duplicate = AnnualMeeting(name='同年の年会', abbreviation='ANOTHER2026',
            start_date=date(2026, 12, 1), end_date=date(2026, 12, 2), location='大阪')
        with self.assertRaises(ValidationError) as error:
            duplicate.full_clean()
        self.assertIn('2026年の年会は既に登録されています。', str(error.exception))
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate.save()
        admin_user = get_user_model().objects.create_superuser('administrator', 'admin@example.com', 'secret')
        self.client.force_login(admin_user)
        response = self.client.post(reverse('admin:program_annualmeeting_add'), {
            'name': '同年の年会', 'abbreviation': 'ANOTHER2026',
            'start_date': '2026-12-01', 'end_date': '2026-12-02', 'location': '大阪',
            'rooms-TOTAL_FORMS': '0', 'rooms-INITIAL_FORMS': '0',
            'rooms-MIN_NUM_FORMS': '0', 'rooms-MAX_NUM_FORMS': '1000',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2026年の年会は既に登録されています。')
        self.assertEqual(AnnualMeeting.objects.count(), 1)

    def test_rooms_are_scoped_to_meeting(self):
        other = AnnualMeeting.objects.create(name='別の年会', abbreviation='PASJ2027',
            start_date=date(2027, 1, 1), end_date=date(2027, 1, 2), location='大阪')
        room = Venue.objects.create(name='大会議室', annual_meeting=self.meeting)
        other_room = Venue.objects.create(name='大会議室', annual_meeting=other)
        form = SessionForm(meeting_id=self.meeting.pk)
        self.assertEqual(list(form.fields['venue'].queryset), [room])
        invalid = SessionForm(data={'name': '別年会の部屋', 'annual_meeting': self.meeting.pk,
                                    'venue': other_room.pk}, meeting_id=self.meeting.pk)
        self.assertFalse(invalid.is_valid())
        session = Session(name='別年会の部屋', annual_meeting=self.meeting, venue=other_room)
        with self.assertRaises(ValidationError):
            session.full_clean()

    def test_organize_url_selects_meeting_for_session_creation(self):
        user = get_user_model().objects.create_user('editor', password='secret', is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='program'))
        self.client.force_login(user)
        AnnualMeeting.objects.create(name='別の年会', abbreviation='PASJ2027', start_date=date(2027, 1, 1),
                                             end_date=date(2027, 1, 2), location='大阪')
        response = self.client.get(reverse('organize', args=[2026]))
        self.assertContains(response, '第1回年会 編成ページ')
        self.assertContains(response, 'value="2026-09-20"')
        self.assertNotContains(response, 'value="2027-01-01"')
        response = self.client.post(reverse('create_session', args=[2026]), {
            'name': '新規セッション', 'annual_meeting': '2',
            'kind': Session.Kind.ORAL, 'talk_limit': '2',
            'date': '2026-09-20', 'start_time': '10:00',
            'minutes_per_presentation': '20',
        })
        self.assertRedirects(response, reverse('organize', args=[2026]))
        self.assertEqual(Session.objects.get(name='新規セッション').annual_meeting, self.meeting)
        index = self.client.get(reverse('organize_index'))
        self.assertContains(index, '/2026/')
        self.assertContains(index, '<strong>第1回年会（PASJ2026）</strong>', html=True)
        self.assertNotContains(index, '東京国際会議場　/2026/')
        self.assertEqual(reverse('organize', args=[2026]), '/organize/2026/')
        self.assertEqual(reverse('timetable', args=[2026]), '/2026/')
        self.assertEqual(self.client.get('/organize/2026/').status_code, 200)
        legacy = Session.objects.create(name='古いセッション')
        self.assertContains(self.client.get(reverse('organize_index')), '年会未設定のセッション')
        self.assertContains(self.client.get(reverse('organize_legacy')), legacy.name)
