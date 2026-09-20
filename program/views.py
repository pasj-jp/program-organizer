import json
import re
from datetime import date, datetime, timedelta
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST
from .models import AnnualMeeting, Presentation, Session, Venue
from .forms import BoardPresentationForm, SessionForm
from .timetable import build_timetable
from .excel_export import render_timetable_excel


def _require_board_view_permission(user):
    if not user.has_perm('program.view_presentation') or not user.has_perm('program.view_session'):
        raise PermissionDenied


@staff_member_required
def organize_index(request):
    _require_board_view_permission(request.user)
    return render(request, 'program/organize_index.html', {
        'meetings': AnnualMeeting.objects.all(),
        'has_legacy_sessions': Session.objects.filter(annual_meeting__isnull=True).exists(),
    })


@staff_member_required
def organize(request, abbreviation):
    _require_board_view_permission(request.user)
    meeting = get_object_or_404(AnnualMeeting, abbreviation=abbreviation)
    return _organize_board(request, meeting)


@staff_member_required
def organize_legacy(request):
    _require_board_view_permission(request.user)
    return _organize_board(request, None)


def _organize_board(request, meeting):
    sessions = list(Session.objects.filter(annual_meeting=meeting).select_related('venue').order_by('board_order', 'date', 'start_time', 'name', 'id'))
    presentations = Presentation.objects.filter(
        Q(status=Presentation.Status.ACTIVE) | Q(status=Presentation.Status.WITHDRAWN, session__isnull=False)
    ).filter(
        Q(session__isnull=True) | Q(session__annual_meeting=meeting)
    ).prefetch_related('authors').order_by('session_order', 'submission_number')
    cards = {session.id: [] for session in sessions}
    unassigned = []
    presentation_formats = set()
    presentation_categories = set()
    for presentation in presentations:
        presentation_formats.add(presentation.presentation_format)
        presentation_categories.update(filter(None, (presentation.category_first, presentation.category_second)))
        if presentation.session_id in cards:
            cards[presentation.session_id].append(presentation)
        else:
            unassigned.append(presentation)
    return render(request, 'program/organize.html', {
        'sessions': [(session, cards[session.id]) for session in sessions],
        'unassigned': unassigned,
        'presentation_formats': sorted(presentation_formats),
        'presentation_categories': sorted(presentation_categories),
        'session_form': SessionForm(meeting_id=meeting.pk) if meeting else None,
        'meeting': meeting,
        'legacy': meeting is None,
        'can_change': request.user.has_perm('program.change_presentation'),
        'can_add_session': request.user.has_perm('program.add_session'),
        'can_reorder_sessions': meeting is not None and request.user.has_perm('program.change_session'),
    })


@staff_member_required
@require_POST
def create_session(request, abbreviation):
    if not request.user.has_perm('program.add_session'):
        raise PermissionDenied
    meeting = get_object_or_404(AnnualMeeting, abbreviation=abbreviation)
    data = request.POST.copy()
    data['annual_meeting'] = meeting.pk
    form = SessionForm(data, meeting_id=meeting.pk)
    if form.is_valid():
        form.save()
        messages.success(request, 'セッションを作成しました。')
    else:
        messages.error(request, 'セッションを作成できませんでした。入力内容を確認してください。')
    return redirect('organize', abbreviation=meeting.abbreviation)


@staff_member_required
@require_http_methods(['GET', 'POST'])
def edit_presentation(request, presentation_id):
    if not request.user.has_perm('program.change_presentation'):
        raise PermissionDenied
    talk = get_object_or_404(Presentation, pk=presentation_id)
    form = BoardPresentationForm(request.POST or None, instance=talk)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return JsonResponse({'ok': True})
    return render(request, 'program/_presentation_form.html', {'form': form, 'talk': talk},
                  status=400 if request.method == 'POST' else 200)


@staff_member_required
@require_POST
def reorder_sessions(request, abbreviation):
    if not request.user.has_perm('program.change_session'):
        raise PermissionDenied
    meeting = get_object_or_404(AnnualMeeting, abbreviation=abbreviation)
    try:
        order = [int(pk) for pk in json.loads(request.body)['order']]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({'error': 'セッションの順序が不正です。'}, status=400)
    with transaction.atomic():
        sessions = list(Session.objects.select_for_update().filter(annual_meeting=meeting))
        if len(order) != len(sessions) or set(order) != {session.pk for session in sessions}:
            return JsonResponse({'error': 'セッションの一覧が変更されています。画面を再読み込みしてください。'}, status=409)
        positions = {pk: index for index, pk in enumerate(order, start=1)}
        for session in sessions:
            session.board_order = positions[session.pk]
        Session.objects.bulk_update(sessions, ['board_order'])
    return JsonResponse({'ok': True})


@staff_member_required
@require_POST
def move_presentation(request):
    if not request.user.has_perm('program.change_presentation'):
        raise PermissionDenied
    try:
        data = json.loads(request.body)
        presentation_id = int(data['presentation_id'])
        target_id = data['session_id']
        target_id = int(target_id) if target_id is not None else None
        order = [int(x) for x in data['order']]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({'error': '不正なデータです。'}, status=400)
    if len(order) != len(set(order)) or presentation_id not in order:
        return JsonResponse({'error': '演題の順序が不正です。'}, status=400)
    if target_id is not None and not Session.objects.filter(pk=target_id).exists():
        return JsonResponse({'error': 'セッションが見つかりません。'}, status=404)
    with transaction.atomic():
        moved = get_object_or_404(Presentation.objects.select_for_update(), pk=presentation_id, status=Presentation.Status.ACTIVE)
        old_id = moved.session_id
        target_talks = Presentation.objects.filter(session_id=target_id)
        if target_id is None:
            target_talks = target_talks.filter(status=Presentation.Status.ACTIVE)
        expected = set(target_talks.values_list('id', flat=True))
        if old_id != target_id:
            expected.add(presentation_id)
        if set(order) != expected:
            return JsonResponse({'error': '他の変更がありました。画面を再読み込みしてください。'}, status=409)
        moved.session_id = target_id
        moved.save(update_fields=['session'])
        for position, pk in enumerate(order, start=1):
            Presentation.objects.filter(pk=pk).update(session_order=position)
        if old_id != target_id:
            remaining = Presentation.objects.filter(session_id=old_id)
            if old_id is None:
                remaining = remaining.filter(status=Presentation.Status.ACTIVE)
            remaining = remaining.order_by('session_order', 'id')
            for position, item in enumerate(remaining, start=1):
                if item.session_order != position:
                    Presentation.objects.filter(pk=item.pk).update(session_order=position)
        for session in Session.objects.filter(pk__in={old_id, target_id} - {None}):
            session.recalculate_program_numbers()
    changed_sessions = list(Session.objects.filter(pk__in={old_id, target_id} - {None}))
    changed_ids = {session.pk for session in changed_sessions}
    changed_talks = Presentation.objects.filter(Q(session_id__in=changed_ids) | Q(pk=presentation_id))
    program_numbers = {
        str(pk): {'number': number or '', 'submission': submission}
        for pk, number, submission in changed_talks.values_list('pk', 'program_number', 'submission_number')
    }
    return JsonResponse({'ok': True, 'program_numbers': program_numbers, 'end_times': {
        str(session.pk): session.end_time.strftime('%H:%M') if session.end_time else ''
        for session in changed_sessions
    }})


def timetable_index(request):
    return render(request, 'program/timetable_index.html', {'meetings': AnnualMeeting.objects.all()})


def timetable(request, abbreviation):
    meeting = get_object_or_404(AnnualMeeting, abbreviation=abbreviation)
    days, unscheduled = build_timetable(meeting)
    return render(request, 'program/timetable.html', {
        'meeting': meeting, 'days': days, 'unscheduled': unscheduled,
        'can_move_sessions': request.user.is_staff and request.user.has_perm('program.change_session'),
    })


def timetable_excel(request, abbreviation):
    meeting = get_object_or_404(AnnualMeeting, abbreviation=abbreviation)
    days, unscheduled = build_timetable(meeting)
    response = HttpResponse(render_timetable_excel(meeting, days, unscheduled),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="timetable_{meeting.abbreviation}.xlsx"'
    return response


@staff_member_required
@require_POST
def move_session_time(request, abbreviation):
    if not request.user.has_perm('program.change_session'):
        raise PermissionDenied
    try:
        data = json.loads(request.body)
        session_id = int(data['session_id'])
        value = data['start_time']
        expected_start = data['expected_start']
        expected_duration = int(data['expected_duration'])
        date_value = data.get('date')
        target_date = None
        if date_value is not None:
            if not isinstance(date_value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_value):
                raise ValueError
            target_date = date.fromisoformat(date_value)
        venue_value = data.get('venue_id', 'unchanged')
        target_venue_id = None if venue_value is None else (int(venue_value) if venue_value != 'unchanged' else 'unchanged')
        if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
            raise ValueError
        new_start = datetime.strptime(value, '%H:%M').time()
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({'error': '開始時刻が不正です。'}, status=400)
    meeting = get_object_or_404(AnnualMeeting, abbreviation=abbreviation)
    with transaction.atomic():
        session = get_object_or_404(Session.objects.select_for_update(), pk=session_id, annual_meeting=meeting)
        if not session.date or not session.start_time:
            return JsonResponse({'error': '日時未設定のセッションは移動できません。'}, status=400)
        target_date = target_date or session.date
        if not meeting.start_date <= target_date <= meeting.end_date:
            return JsonResponse({'error': '会期外の日付には移動できません。'}, status=400)
        if target_venue_id == 'unchanged':
            target_venue_id = session.venue_id
        if target_venue_id is not None and not Venue.objects.filter(pk=target_venue_id, annual_meeting=meeting).exists():
            return JsonResponse({'error': 'この年会の部屋が見つかりません。'}, status=400)
        count = session.presentations.count()
        duration = count * session.minutes_per_presentation if count else (session.empty_duration_minutes or 30)
        if (session.start_time.strftime('%H:%M') != expected_start or duration != expected_duration
                or (data.get('expected_date') and session.date.isoformat() != data['expected_date'])
                or ('expected_venue_id' in data and session.venue_id != data['expected_venue_id'])):
            return JsonResponse({'error': 'セッションが変更されています。画面を再読み込みしてください。'}, status=409)
        new_start_dt = datetime.combine(target_date, new_start)
        if (new_start_dt + timedelta(minutes=duration)).date() != target_date:
            return JsonResponse({'error': '終了時刻が翌日になる位置には移動できません。'}, status=400)
        delta = datetime.combine(target_date, new_start) - datetime.combine(target_date, session.start_time)
        shifted = []
        for talk in session.presentations.all():
            fields = {}
            for field in ('start_time', 'end_time'):
                old_time = getattr(talk, field)
                if old_time:
                    new_time = datetime.combine(target_date, old_time) + delta
                    if new_time.date() != target_date:
                        return JsonResponse({'error': '演題の時刻が会期日を超えます。'}, status=400)
                    fields[field] = new_time.time()
            if fields:
                shifted.append((talk.pk, fields))
        session.start_time = new_start
        session.date = target_date
        session.venue_id = target_venue_id
        session.save(update_fields=['start_time', 'date', 'venue'])
        for pk, fields in shifted:
            Presentation.objects.filter(pk=pk).update(**fields)
    return JsonResponse({'ok': True, 'date': session.date.isoformat(), 'venue_id': session.venue_id,
                         'start_time': session.start_time.strftime('%H:%M'),
                         'end_time': session.end_time.strftime('%H:%M') if session.end_time else ''})
