"""Transactional operations used by the program organization board."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from .models import Presentation, Session, Venue


class OrganizingError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class PresentationMoveResult:
    presentation: Presentation
    sessions: list


def _presentations_in(meeting_id, session_id):
    talks = Presentation.objects.filter(annual_meeting_id=meeting_id, session_id=session_id)
    return talks.filter(status=Presentation.Status.ACTIVE) if session_id is None else talks


def _set_presentation_order(talks, order):
    positions = {pk: position for position, pk in enumerate(order, start=1)}
    for talk in talks:
        talk.session_order = positions[talk.pk]
    Presentation.objects.bulk_update(talks, ['session_order'])


@transaction.atomic
def reorder_sessions(meeting, order):
    sessions = list(Session.objects.select_for_update().filter(annual_meeting=meeting))
    if len(order) != len(sessions) or set(order) != {session.pk for session in sessions}:
        raise OrganizingError('セッションの一覧が変更されています。画面を再読み込みしてください。', 409)
    positions = {pk: position for position, pk in enumerate(order, start=1)}
    for session in sessions:
        session.board_order = positions[session.pk]
    Session.objects.bulk_update(sessions, ['board_order'])


@transaction.atomic
def move_presentation(presentation_id, target_id, order, meeting_id):
    moved = Presentation.objects.select_for_update().filter(
        pk=presentation_id, status=Presentation.Status.ACTIVE).first()
    if moved is None:
        raise OrganizingError('演題が見つかりません。', 404)
    if moved.annual_meeting_id != meeting_id:
        raise OrganizingError('異なる年会の演題は移動できません。')

    old_id = moved.session_id
    target_session = None
    if target_id is not None:
        target_session = Session.objects.select_for_update().filter(pk=target_id).first()
        if target_session is None:
            raise OrganizingError('セッションが見つかりません。', 404)
        if target_session.annual_meeting_id != meeting_id:
            raise OrganizingError('異なる年会のセッションには移動できません。')
        if not target_session.accepts_presentation(moved):
            raise OrganizingError('発表形式がセッションと一致しません。')
        if (old_id != target_id and target_session.kind == Session.Kind.ORAL
                and target_session.talk_limit is not None
                and target_session.presentations.count() >= target_session.talk_limit):
            raise OrganizingError('この口頭発表セッションは満員です。')

    target_talks = list(_presentations_in(meeting_id, target_id).select_for_update())
    expected = {talk.pk for talk in target_talks}
    if old_id != target_id:
        expected.add(presentation_id)
    if set(order) != expected:
        raise OrganizingError('他の変更がありました。画面を再読み込みしてください。', 409)

    moved.session_id = target_id
    moved.save(update_fields=['session'])
    ordered_talks = {talk.pk: talk for talk in target_talks}
    ordered_talks[presentation_id] = moved
    _set_presentation_order([ordered_talks[pk] for pk in order], order)

    if old_id != target_id:
        remaining = list(_presentations_in(meeting_id, old_id).select_for_update().order_by('session_order', 'id'))
        _set_presentation_order(remaining, [talk.pk for talk in remaining])

    sessions = list(Session.objects.filter(pk__in={old_id, target_id} - {None}))
    for session in sessions:
        session.recalculate_program_numbers()
    moved.refresh_from_db(fields=['confirmed_category'])
    return PresentationMoveResult(moved, sessions)


@transaction.atomic
def move_session(meeting, session_id, new_start, target_date, target_venue_id,
                 expected_start, expected_duration, expected_date=None, expected_venue_id=None,
                 check_expected_venue=False):
    session = Session.objects.select_for_update().filter(pk=session_id, annual_meeting=meeting).first()
    if session is None:
        raise OrganizingError('セッションが見つかりません。', 404)
    if session.kind == Session.Kind.FACILITY_REPORT:
        raise OrganizingError('施設報告ポスターの時間は対応するポスターセッションで設定してください。')
    if not session.date or not session.start_time:
        raise OrganizingError('日時未設定のセッションは移動できません。')
    target_date = target_date or session.date
    if not meeting.start_date <= target_date <= meeting.end_date:
        raise OrganizingError('会期外の日付には移動できません。')
    if target_venue_id == 'unchanged':
        target_venue_id = session.venue_id
    if target_venue_id is not None and not Venue.objects.filter(
            pk=target_venue_id, annual_meeting=meeting).exists():
        raise OrganizingError('この年会の部屋が見つかりません。')

    duration = session.slot_minutes() or 30
    if (session.start_time.strftime('%H:%M') != expected_start or duration != expected_duration
            or (expected_date and session.date.isoformat() != expected_date)
            or (check_expected_venue and session.venue_id != expected_venue_id)):
        raise OrganizingError('セッションが変更されています。画面を再読み込みしてください。', 409)
    if (datetime.combine(target_date, new_start) + timedelta(minutes=duration)).date() != target_date:
        raise OrganizingError('終了時刻が翌日になる位置には移動できません。')

    delta = datetime.combine(target_date, new_start) - datetime.combine(target_date, session.start_time)
    shifted = []
    for talk in session.presentations.select_for_update():
        fields = {}
        for field in ('start_time', 'end_time'):
            old_time = getattr(talk, field)
            if old_time:
                new_time = datetime.combine(target_date, old_time) + delta
                if new_time.date() != target_date:
                    raise OrganizingError('演題の時刻が会期日を超えます。')
                fields[field] = new_time.time()
        if fields:
            shifted.append((talk.pk, fields))
    session.start_time = new_start
    session.date = target_date
    session.venue_id = target_venue_id
    session.save(update_fields=['start_time', 'date', 'venue'])
    for pk, fields in shifted:
        Presentation.objects.filter(pk=pk).update(**fields)
    return session
