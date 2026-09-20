import json
from io import BytesIO
from datetime import date, time
from openpyxl import load_workbook
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from .forms import SessionForm
from .models import AnnualMeeting, Presentation, Session, Venue


class OrganizerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('editor', password='secret', is_staff=True)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='program'))
        self.client.force_login(self.user)
        self.meeting = AnnualMeeting.objects.create(name='年会', abbreviation='PASJ2026',
            start_date=date(2026, 9, 19), end_date=date(2026, 9, 21), location='東京')
        self.session = Session.objects.create(name='加速器', code='FRO', annual_meeting=self.meeting,
            start_time=time(10, 0), minutes_per_presentation=20)
        self.first = Presentation.objects.create(submission_number='A1', title='第一演題')
        self.second = Presentation.objects.create(submission_number='A2', title='第二演題')

    def move(self, presentation, session_id, order):
        return self.client.post(reverse('move_presentation'),
                                json.dumps({'presentation_id': presentation.pk, 'session_id': session_id, 'order': order}),
                                content_type='application/json')

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
        third = Presentation.objects.create(submission_number='A3', title='第三演題')
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
        response = self.client.get(reverse('timetable', args=['PASJ2026']))
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
        self.assertContains(response, reverse('timetable_excel', args=['PASJ2026']))
        self.assertContains(self.client.get(reverse('timetable_index')), '/timetable/PASJ2026/')

        excel = self.client.get(reverse('timetable_excel', args=['PASJ2026']))
        self.assertEqual(excel.status_code, 200)
        self.assertEqual(excel['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('timetable_PASJ2026.xlsx', excel['Content-Disposition'])
        workbook = load_workbook(BytesIO(excel.content), read_only=False)
        self.assertIn('日程1-3', workbook.sheetnames)
        self.assertIn('演題一覧', workbook.sheetnames)
        schedule_values = [cell.value for row in workbook['日程1-3'] for cell in row]
        self.assertIn('9月19日（土）', schedule_values)
        self.assertTrue(any(isinstance(value, str) and 'FRO01–FRO02' in value for value in schedule_values))
        talk_values = [cell.value for row in workbook['演題一覧'] for cell in row]
        self.assertIn('第一演題', talk_values)

    def test_withdrawn_talk_keeps_its_timetable_slot(self):
        self.move(self.first, self.session.pk, [self.first.pk])
        self.first.refresh_from_db()
        self.first.status = Presentation.Status.WITHDRAWN
        self.first.save(update_fields=['status'])
        board = self.client.get(reverse('organize', args=['PASJ2026']))
        self.assertContains(board, 'class="card withdrawn"')
        self.assertContains(board, 'data-status="withdrawn"')
        self.assertContains(board, '第一演題')
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        response = self.client.get(reverse('timetable', args=['PASJ2026']))
        self.assertContains(response, 'class="withdrawn-row"')
        self.assertContains(response, '10:00–10:20')
        self.assertContains(response, '第一演題')
        self.assertContains(response, 'FRO01')
        self.session.refresh_from_db()
        self.assertEqual(self.session.end_time, time(10, 20))
        workbook = load_workbook(BytesIO(self.client.get(reverse('timetable_excel', args=['PASJ2026'])).content))
        rows = list(workbook['演題一覧'].values)
        self.assertTrue(any(row[1] == '10:00–10:20' and row[6] == '第一演題' for row in rows))
        moved = self.client.post(reverse('move_session_time', args=['PASJ2026']),
            json.dumps({'session_id': self.session.pk, 'start_time': '11:00',
                        'expected_start': '10:00', 'expected_duration': 20}),
            content_type='application/json')
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['end_time'], '11:20')

    def test_excel_export_keeps_imported_titles_as_text(self):
        self.session.date = date(2026, 9, 19)
        self.session.save(update_fields=['date'])
        self.first.title = '=1+1'
        self.first.save(update_fields=['title'])
        self.move(self.first, self.session.pk, [self.first.pk])
        response = self.client.get(reverse('timetable_excel', args=['PASJ2026']))
        workbook = load_workbook(BytesIO(response.content))
        title_cell = next(cell for row in workbook['演題一覧'] for cell in row if cell.value == '=1+1')
        self.assertEqual(title_cell.data_type, 's')

    def test_empty_session_duration_supports_breaks(self):
        break_session = Session.objects.create(
            name='昼休憩', annual_meeting=self.meeting, date=date(2026, 9, 19),
            start_time=time(12, 0), empty_duration_minutes=60,
        )
        self.assertEqual(break_session.end_time, time(13, 0))
        response = self.client.get(reverse('timetable', args=['PASJ2026']))
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
        response = self.client.post(reverse('move_session_time', args=['PASJ2026']),
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
        url = reverse('move_session_time', args=['PASJ2026'])
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
        response = self.client.post(reverse('move_session_time', args=['PASJ2026']),
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
        page = self.client.get(reverse('timetable', args=['PASJ2026']))
        days = page.context['days']
        self.assertEqual([venue['name'] for venue in days[0]['venues']],
                         [venue['name'] for venue in days[1]['venues']])
        self.assertEqual(len(days[0]['sessions']), 0)
        self.assertEqual(len(days[1]['sessions']), 1)
        invalid = self.client.post(reverse('move_session_time', args=['PASJ2026']),
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
        response = self.client.post(reverse('move_session_time', args=[self.meeting.abbreviation]),
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
        response = self.client.get(reverse('organize', args=[self.meeting.abbreviation]))
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
        self.assertContains(response, 'src="/static/program/organize.js"')
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
        url = reverse('reorder_sessions', args=[self.meeting.abbreviation])
        response = self.client.post(url, json.dumps({'order': [other.pk, self.session.pk]}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        board = self.client.get(reverse('organize', args=[self.meeting.abbreviation]))
        self.assertContains(board, 'data-reorder-url="/organize/PASJ2026/reorder-sessions/"')
        self.assertLess(board.content.index(b'data-session-id="' + str(other.pk).encode()),
                        board.content.index(b'data-session-id="' + str(self.session.pk).encode()))
        invalid = self.client.post(url, json.dumps({'order': [self.session.pk]}),
                                   content_type='application/json')
        self.assertEqual(invalid.status_code, 409)
        self.user.user_permissions.remove(Permission.objects.get(codename='change_session', content_type__app_label='program'))
        denied = self.client.post(url, json.dumps({'order': [self.session.pk, other.pk]}),
                                  content_type='application/json')
        self.assertEqual(denied.status_code, 403)


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
                                  'date': '2026-09-20', 'minutes_per_presentation': '15'})
        self.assertTrue(valid.is_valid(), valid.errors)
        invalid = SessionForm(data={'name': '加速器', 'annual_meeting': self.meeting.pk,
                                    'date': '2026-09-22', 'minutes_per_presentation': '15'})
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
        response = self.client.get(reverse('organize', args=['PASJ2026']))
        self.assertContains(response, '第1回年会 セッション編成')
        self.assertContains(response, 'value="2026-09-20"')
        self.assertNotContains(response, 'value="2027-01-01"')
        response = self.client.post(reverse('create_session', args=['PASJ2026']), {
            'name': '新規セッション', 'annual_meeting': '2',
            'date': '2026-09-20', 'start_time': '10:00',
            'minutes_per_presentation': '20',
        })
        self.assertRedirects(response, reverse('organize', args=['PASJ2026']))
        self.assertEqual(Session.objects.get(name='新規セッション').annual_meeting, self.meeting)
        self.assertContains(self.client.get(reverse('organize_index')), '/organize/PASJ2026/')
        legacy = Session.objects.create(name='古いセッション')
        self.assertContains(self.client.get(reverse('organize_index')), '年会未設定のセッション')
        self.assertContains(self.client.get(reverse('organize_legacy')), legacy.name)
