import json
import re
from datetime import date, datetime, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST
from .models import AnnualMeeting, Presentation, Session, SessionChair, Venue
from .forms import AbstractExcelImportForm, BoardPresentationForm, ProgramExcelImportForm, SessionChairsForm, SessionForm
from .timetable import build_timetable
from .excel_export import render_timetable_excel
from .program_excel import export_program, import_program
from .importer import import_abstracts


def _require_board_view_permission(user):
    if not user.has_perm('program.view_presentation') or not user.has_perm('program.view_session'):
        raise PermissionDenied


@login_required
def organize_index(request):
    _require_board_view_permission(request.user)
    return render(request, 'program/organize_index.html', {
        'meetings': AnnualMeeting.objects.all(),
        'has_legacy_sessions': Session.objects.filter(annual_meeting__isnull=True).exists(),
    })


@login_required
def organize(request, year):
    _require_board_view_permission(request.user)
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    if request.GET.get('tab') == 'timetable':
        return _render_timetable(request, meeting, editing=True)
    return _organize_board(request, meeting)


@login_required
def organize_legacy(request):
    _require_board_view_permission(request.user)
    return _organize_board(request, None)


def _organize_board(request, meeting, session_form=None, program_form=None, abstract_form=None):
    sessions = list(Session.objects.filter(annual_meeting=meeting).select_related(
        'venue', 'poster_session_one', 'poster_session_two').prefetch_related('chairs').order_by('board_order', 'date', 'start_time', 'name', 'id'))
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
        'session_form': session_form or (SessionForm(meeting_id=meeting.pk) if meeting else None),
        'program_form': program_form or ProgramExcelImportForm(),
        'abstract_form': abstract_form or AbstractExcelImportForm(),
        'meeting': meeting,
        'legacy': meeting is None,
        'can_change': request.user.has_perm('program.change_presentation'),
        'can_add_session': request.user.has_perm('program.add_session'),
        'can_reorder_sessions': meeting is not None and request.user.has_perm('program.change_session'),
        'can_edit_chairs': request.user.has_perm('program.change_session'),
        'can_import_program': meeting is not None and all(request.user.has_perm(f'program.{permission}') for permission in
            ('add_session', 'change_session', 'add_presentation', 'change_presentation', 'add_venue')),
        'can_import_abstract': meeting is not None and request.user.has_perm('program.add_presentation'),
    })


@login_required
@require_POST
def create_session(request, year):
    if not request.user.has_perm('program.add_session'):
        raise PermissionDenied
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    data = request.POST.copy()
    data['annual_meeting'] = meeting.pk
    form = SessionForm(data, meeting_id=meeting.pk)
    if form.is_valid():
        form.save()
        messages.success(request, 'セッションを作成しました。')
    else:
        messages.error(request, 'セッションを作成できませんでした。入力内容を確認してください。')
        return _organize_board(request, meeting, session_form=form)
    return redirect('organize', year=meeting.year)


@login_required
@require_POST
def import_program_excel(request, year):
    permissions = ('add_session', 'change_session', 'add_presentation', 'change_presentation', 'add_venue')
    if not all(request.user.has_perm(f'program.{permission}') for permission in permissions):
        raise PermissionDenied
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    form = ProgramExcelImportForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            created, updated, sessions = import_program(form.cleaned_data['file'], meeting)
        except (ValueError, ValidationError) as exc:
            form.add_error('file', str(exc))
        else:
            messages.success(request, f'プログラムを取り込みました。セッション {sessions} 件、演題 新規 {created} 件・更新 {updated} 件。')
            return redirect('organize', year=year)
    return _organize_board(request, meeting, program_form=form)


@login_required
@require_POST
def import_abstract_excel(request, year):
    if not request.user.has_perm('program.add_presentation'):
        raise PermissionDenied
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    form = AbstractExcelImportForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            created, updated = import_abstracts(form.cleaned_data['file'])
        except (ValueError, OSError) as exc:
            form.add_error('file', str(exc))
        else:
            messages.success(request, f'アブストラクトを取り込みました。新規 {created} 件・更新 {updated} 件。')
            return redirect('organize', year=year)
    return _organize_board(request, meeting, abstract_form=form)


@login_required
def export_program_excel(request, year):
    _require_board_view_permission(request.user)
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    response = HttpResponse(export_program(meeting),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="program.xlsx"'
    return response


@login_required
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


@login_required
@require_http_methods(['GET', 'POST'])
def edit_session_chairs(request, session_id):
    if not request.user.has_perm('program.change_session'):
        raise PermissionDenied
    session = get_object_or_404(Session, pk=session_id, kind=Session.Kind.ORAL)
    form = SessionChairsForm(request.POST or None, session=session)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            for index, category in enumerate(form.categories):
                name = form.cleaned_data[f'chair_{index}'].strip()
                if name:
                    SessionChair.objects.update_or_create(session=session, category=category, defaults={'name': name})
                else:
                    SessionChair.objects.filter(session=session, category=category).delete()
        return JsonResponse({'ok': True})
    return render(request, 'program/_session_chairs_form.html', {'form': form, 'session': session},
                  status=400 if request.method == 'POST' else 200)


@login_required
@require_POST
def reorder_sessions(request, year):
    if not request.user.has_perm('program.change_session'):
        raise PermissionDenied
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
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


@login_required
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
    with transaction.atomic():
        moved = get_object_or_404(Presentation.objects.select_for_update(), pk=presentation_id, status=Presentation.Status.ACTIVE)
        old_id = moved.session_id
        target_session = None
        if target_id is not None:
            target_session = Session.objects.select_for_update().filter(pk=target_id).first()
            if target_session is None:
                return JsonResponse({'error': 'セッションが見つかりません。'}, status=404)
            if not target_session.accepts_presentation(moved):
                return JsonResponse({'error': '発表形式がセッションと一致しません。'}, status=400)
            if (old_id != target_id and target_session.kind == Session.Kind.ORAL
                    and target_session.talk_limit is not None
                    and target_session.presentations.count() >= target_session.talk_limit):
                return JsonResponse({'error': 'この口頭発表セッションは満員です。'}, status=400)
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
    return JsonResponse({'ok': True, 'program_numbers': program_numbers,
        'confirmed_category': moved.confirmed_category, 'end_times': {
        str(session.pk): session.end_time.strftime('%H:%M') if session.end_time else ''
        for session in changed_sessions
    }})


def timetable_index(request):
    return render(request, 'program/timetable_index.html', {'meetings': AnnualMeeting.objects.all()})


def timetable(request, year):
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    return _render_timetable(request, meeting, editing=False)


def _render_timetable(request, meeting, editing):
    days, unscheduled = build_timetable(meeting)
    return render(request, 'program/timetable.html', {
        'meeting': meeting, 'days': days, 'unscheduled': unscheduled,
        'editing': editing,
        'can_move_sessions': editing and request.user.has_perm('program.change_session'),
    })


def timetable_excel(request, year):
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    days, unscheduled = build_timetable(meeting)
    response = HttpResponse(render_timetable_excel(meeting, days, unscheduled),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="timetable_{meeting.abbreviation}.xlsx"'
    return response


@login_required
@require_POST
def move_session_time(request, year):
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
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    with transaction.atomic():
        session = get_object_or_404(Session.objects.select_for_update(), pk=session_id, annual_meeting=meeting)
        if session.kind == Session.Kind.FACILITY_REPORT:
            return JsonResponse({'error': '施設報告ポスターの時間は対応するポスターセッションで設定してください。'}, status=400)
        if not session.date or not session.start_time:
            return JsonResponse({'error': '日時未設定のセッションは移動できません。'}, status=400)
        target_date = target_date or session.date
        if not meeting.start_date <= target_date <= meeting.end_date:
            return JsonResponse({'error': '会期外の日付には移動できません。'}, status=400)
        if target_venue_id == 'unchanged':
            target_venue_id = session.venue_id
        if target_venue_id is not None and not Venue.objects.filter(pk=target_venue_id, annual_meeting=meeting).exists():
            return JsonResponse({'error': 'この年会の部屋が見つかりません。'}, status=400)
        duration = session.slot_minutes() or 30
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
