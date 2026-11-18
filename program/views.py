import json
import re
from datetime import date, datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from .models import AnnualMeeting, Presentation, Session
from .forms import AbstractExcelImportForm, BoardPresentationForm, ProgramExcelImportForm, SessionChairsForm, SessionForm
from .forms import ProceedingsUploadForm, ProceedingsBuildForm
from .proceedings import ProceedingsError, build_proceedings, header_defaults, save_uploads
from .proceedings_publish import CODE_PATTERN, published_directory, download_pdf
from .timetable import build_timetable
from .program_excel import export_program, import_program
from .program_json import export_program_json as build_program_json
from .program_pdf import ProgramPDFError, export_program_pdf as build_program_pdf
from .abstract_excel import import_abstracts
from .organizing import (OrganizingError, move_presentation as move_presentation_service,
                         move_session, reorder_sessions as reorder_sessions_service)


def _require_board_view_permission(user):
    _require_permissions(user, 'view_presentation', 'view_session')


def _require_permissions(user, *permissions):
    if not user.has_perms([f'program.{permission}' for permission in permissions]):
        raise PermissionDenied


@login_required
def procgen_index(request):
    _require_permissions(request.user, 'view_presentation')
    return render(request, 'program/procgen_index.html', {'meetings': AnnualMeeting.objects.all()})


@login_required
@require_http_methods(['GET', 'POST'])
def procgen(request, year):
    _require_permissions(request.user, 'view_presentation')
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    building = request.method == 'POST' and request.POST.get('action') == 'build'
    build_form = ProceedingsBuildForm(request.POST if building else None, initial=header_defaults(meeting))
    form = ProceedingsUploadForm(request.POST if request.method == 'POST' and not building else None,
                                 request.FILES or None, meeting=meeting)
    if request.method == 'POST':
        _require_permissions(request.user, 'change_presentation')
        if building:
            if build_form.is_valid():
                try:
                    build_proceedings(meeting, build_form.cleaned_data)
                except ProceedingsError as exc:
                    build_form.add_error(None, str(exc))
                else:
                    messages.success(request, '加工済みPDFを生成・公開しました。結合PDFはダウンロードボタンから取得できます。')
                    return redirect('procgen', year=year)
        elif form.is_valid():
            save_uploads(form.uploads)
            messages.success(request, f'{len(form.uploads)}件のPDFをアップロードしました。')
            return redirect('procgen', year=year)
    presentations = list(meeting.presentations.prefetch_related('authors').order_by('program_number', 'submission_number'))
    for talk in presentations:
        talk.has_published_pdf = bool(re.fullmatch(CODE_PATTERN, talk.program_number or '') and
            (published_directory(year) / f'{talk.program_number}.pdf').is_file())
    return render(request, 'program/procgen.html', {
        'meeting': meeting, 'form': form, 'build_form': build_form,
        'presentations': presentations,
        'has_published_proceedings': (published_directory(year) / 'proceedings_list.json').is_file(),
        'can_upload': request.user.has_perm('program.change_presentation'),
    })


@login_required
@require_http_methods(['GET', 'HEAD'])
def proceedings_download(request, year):
    _require_permissions(request.user, 'view_presentation')
    get_object_or_404(AnnualMeeting, start_date__year=year)
    try:
        pdf = download_pdf(year)
    except (FileNotFoundError, NotADirectoryError):
        raise Http404
    return FileResponse(pdf, as_attachment=True, filename=f'proceedings-{year}.pdf',
                        content_type='application/pdf')


@login_required
def proceedings_pdf(request, year, program_code):
    _require_permissions(request.user, 'view_presentation')
    talk = get_object_or_404(Presentation, program_number=program_code, annual_meeting__start_date__year=year)
    if not talk.proceedings_file:
        raise Http404
    try:
        pdf = talk.proceedings_file.open('rb')
    except FileNotFoundError:
        raise Http404
    return FileResponse(pdf, as_attachment=True, filename=f'{talk.program_number or talk.submission_number}.pdf',
                        content_type='application/pdf')


@require_http_methods(['GET', 'HEAD'])
@never_cache
def published_proceedings_pdf(request, year, program_code):
    get_object_or_404(AnnualMeeting, start_date__year=year)
    if not re.fullmatch(CODE_PATTERN, program_code):
        raise Http404
    try:
        pdf = (published_directory(year) / f'{program_code}.pdf').open('rb')
    except (FileNotFoundError, NotADirectoryError):
        raise Http404
    return FileResponse(pdf, as_attachment=False, filename=f'{program_code}.pdf',
                        content_type='application/pdf')


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
    ).filter(annual_meeting=meeting).prefetch_related('authors').order_by('session_order', 'submission_number')
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
        'can_edit_session': request.user.has_perm('program.change_session'),
        'can_import_program': meeting is not None and request.user.has_perms([
            'program.add_session', 'program.change_session', 'program.add_presentation',
            'program.change_presentation', 'program.add_venue']),
        'can_import_abstract': meeting is not None and request.user.has_perm('program.add_presentation'),
    })


@login_required
@require_POST
def create_session(request, year):
    _require_permissions(request.user, 'add_session')
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
    _require_permissions(request.user, *permissions)
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
    _require_permissions(request.user, 'add_presentation')
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    form = AbstractExcelImportForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            created, updated = import_abstracts(form.cleaned_data['file'], meeting)
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
    response['Content-Disposition'] = f'attachment; filename="{meeting.abbreviation.lower()}_program.xlsx"'
    return response


@login_required
@require_http_methods(['GET'])
def export_program_json(request, year):
    _require_board_view_permission(request.user)
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    response = HttpResponse(build_program_json(meeting), content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{meeting.abbreviation.lower()}_program.json"'
    return response


@login_required
@require_http_methods(['GET'])
@never_cache
def export_program_pdf(request, year):
    _require_board_view_permission(request.user)
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    try:
        content = build_program_pdf(meeting)
    except ProgramPDFError as exc:
        messages.error(request, str(exc))
        return redirect('organize', year=year)
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{meeting.abbreviation.lower()}_program.pdf"'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
def edit_presentation(request, presentation_id):
    _require_permissions(request.user, 'change_presentation')
    talk = get_object_or_404(Presentation, pk=presentation_id)
    form = BoardPresentationForm(request.POST or None, instance=talk)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return JsonResponse({'ok': True})
    return render(request, 'program/_presentation_form.html', {'form': form, 'talk': talk},
                  status=400 if request.method == 'POST' else 200)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_session(request, session_id):
    _require_permissions(request.user, 'change_session')
    session = get_object_or_404(Session, pk=session_id)
    data = None
    if request.method == 'POST':
        data = request.POST.copy()
        data['session-annual_meeting'] = session.annual_meeting_id or ''
        # The end time is derived again on save, not an editable field.
        session.end_time = None
    form = SessionForm(data, instance=session, meeting_id=session.annual_meeting_id,
                       prefix='session')
    chairs_form = SessionChairsForm(data, session=session, prefix='chairs')
    if request.method == 'POST':
        valid = form.is_valid()
        edit_chairs = form.cleaned_data.get('kind') == Session.Kind.ORAL
        chairs_valid = chairs_form.is_valid() if edit_chairs else True
        if valid and chairs_valid:
            try:
                with transaction.atomic():
                    form.save()
                    if edit_chairs:
                        chairs_form.save(session)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                return JsonResponse({'ok': True})
    return render(request, 'program/_session_form.html',
                  {'form': form, 'chairs_form': chairs_form, 'session': session},
                  status=400 if request.method == 'POST' else 200)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_session_chairs(request, session_id):
    _require_permissions(request.user, 'change_session')
    session = get_object_or_404(Session, pk=session_id, kind=Session.Kind.ORAL)
    form = SessionChairsForm(request.POST or None, session=session)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save(session)
        return JsonResponse({'ok': True})
    return render(request, 'program/_session_chairs_form.html', {'form': form, 'session': session},
                  status=400 if request.method == 'POST' else 200)


@login_required
@require_POST
def reorder_sessions(request, year):
    _require_permissions(request.user, 'change_session')
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    try:
        order = [int(pk) for pk in json.loads(request.body)['order']]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({'error': 'セッションの順序が不正です。'}, status=400)
    try:
        reorder_sessions_service(meeting, order)
    except OrganizingError as exc:
        return JsonResponse({'error': exc.message}, status=exc.status)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def move_presentation(request):
    _require_permissions(request.user, 'change_presentation')
    try:
        data = json.loads(request.body)
        presentation_id = int(data['presentation_id'])
        target_id = data['session_id']
        target_id = int(target_id) if target_id is not None else None
        order = [int(x) for x in data['order']]
        meeting_id = data.get('meeting_id')
        meeting_id = int(meeting_id) if meeting_id is not None else None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({'error': '不正なデータです。'}, status=400)
    if len(order) != len(set(order)) or presentation_id not in order:
        return JsonResponse({'error': '演題の順序が不正です。'}, status=400)
    try:
        result = move_presentation_service(presentation_id, target_id, order, meeting_id)
    except OrganizingError as exc:
        return JsonResponse({'error': exc.message}, status=exc.status)
    moved = result.presentation
    changed_sessions = result.sessions
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


@never_cache
def timetable_index(request):
    return render(request, 'program/timetable_index.html', {
        'meetings': AnnualMeeting.objects.filter(timetable_published=True)})


@never_cache
def timetable(request, year):
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    if not meeting.timetable_published:
        return render(request, 'program/timetable_pending.html', {'meeting': meeting})
    return _render_timetable(request, meeting, editing=False)


@login_required
@require_POST
def set_timetable_publication(request, year):
    _require_board_view_permission(request.user)
    _require_permissions(request.user, 'change_annualmeeting')
    meeting = get_object_or_404(AnnualMeeting, start_date__year=year)
    published = request.POST.get('published')
    if published not in ('true', 'false'):
        return HttpResponse('公開状態の指定が不正です。', status=400)
    meeting.timetable_published = published == 'true'
    meeting.save(update_fields=['timetable_published'])
    response = redirect('organize', year=year)
    if request.POST.get('tab') == 'timetable':
        response['Location'] += '?tab=timetable'
    return response


def _render_timetable(request, meeting, editing):
    venue_width = 250 if editing else 180
    days, unscheduled = build_timetable(meeting, venue_width=venue_width)
    return render(request, 'program/timetable.html', {
        'meeting': meeting, 'days': days, 'unscheduled': unscheduled,
        'editing': editing, 'venue_width': venue_width,
        'can_move_sessions': editing and request.user.has_perm('program.change_session'),
    })


@login_required
@require_POST
def move_session_time(request, year):
    _require_permissions(request.user, 'change_session')
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
    try:
        session = move_session(
            meeting, session_id, new_start, target_date, target_venue_id,
            expected_start, expected_duration, data.get('expected_date'),
            data.get('expected_venue_id'), 'expected_venue_id' in data)
    except OrganizingError as exc:
        return JsonResponse({'error': exc.message}, status=exc.status)
    return JsonResponse({'ok': True, 'date': session.date.isoformat(), 'venue_id': session.venue_id,
                         'start_time': session.start_time.strftime('%H:%M'),
                         'end_time': session.end_time.strftime('%H:%M') if session.end_time else ''})
