from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from django import forms
from .models import AnnualMeeting, Author, Presentation, Session, SessionChair, Venue
from .forms import PresentationForm, SessionForm
from .importer import import_abstracts


class ImportForm(forms.Form):
    file = forms.FileField(label='アブストラクト Excel ファイル (.xlsx)')

    def clean_file(self):
        file = self.cleaned_data['file']
        if not file.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('.xlsx ファイルを選択してください。')
        return file


class AuthorInline(admin.StackedInline):
    model = Author
    extra = 0
    fields = (
        ('position', 'is_presenter'),
        ('family_name', 'given_name'),
        ('family_name_kana', 'given_name_kana'),
        ('family_name_en', 'given_name_en', 'middle_name'),
        ('affiliation', 'affiliation_en'),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ('affiliation', 'affiliation_en'):
            kwargs['widget'] = forms.Textarea(attrs={'rows': 2, 'cols': 40})
        return super().formfield_for_dbfield(db_field, request, **kwargs)


@admin.register(Presentation)
class PresentationAdmin(admin.ModelAdmin):
    form = PresentationForm
    change_list_template = 'admin/program/presentation/change_list.html'
    list_display = ('submission_number', 'program_number', 'short_title', 'presenter', 'presentation_format', 'confirmed_category', 'session', 'start_time', 'effective_venue', 'status')
    list_filter = ('status', 'presentation_format', 'session', 'venue')
    search_fields = ('submission_number', 'program_number', 'title', 'title_en', 'authors__family_name', 'authors__given_name', 'authors__family_name_en', 'authors__given_name_en')
    inlines = [AuthorInline]
    actions = ['withdraw', 'restore']
    fieldsets = (
        ('編成', {'fields': ('program_number', 'session', 'start_time', 'end_time', 'venue', 'status', 'withdrawal_note', 'organizer_note')}),
        ('演題', {'fields': ('submission_number', 'registration_number', 'presentation_format', 'title', 'title_en', 'abstract', 'category_first', 'category_second', 'confirmed_category')}),
        ('登録者', {'fields': ('login_id', 'email')}),
        ('元データの著者表記', {'classes': ('collapse',), 'fields': ('author_text', 'author_text_en', 'affiliation_text', 'affiliation_text_en')}),
    )

    @admin.display(description='題目')
    def short_title(self, obj):
        return obj.title[:70]

    @admin.display(description='登壇者')
    def presenter(self, obj):
        return ', '.join(str(a) for a in obj.authors.all() if a.is_presenter)

    @admin.display(description='部屋')
    def effective_venue(self, obj):
        return obj.effective_venue

    @admin.action(description='選択した演題を発表取り消しにする')
    def withdraw(self, request, queryset):
        session_ids = set(queryset.values_list('session_id', flat=True))
        queryset.update(status=Presentation.Status.WITHDRAWN)
        for session in Session.objects.filter(pk__in=session_ids):
            session.recalculate_end_time()
            session.recalculate_program_numbers()

    @admin.action(description='選択した演題を発表予定に戻す')
    def restore(self, request, queryset):
        session_ids = set(queryset.values_list('session_id', flat=True))
        queryset.update(status=Presentation.Status.ACTIVE)
        for session in Session.objects.filter(pk__in=session_ids):
            session.recalculate_end_time()
            session.recalculate_program_numbers()

    def get_urls(self):
        return [path('import/', self.admin_site.admin_view(self.import_view), name='program_presentation_import')] + super().get_urls()

    def import_view(self, request):
        if not self.has_add_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = ImportForm(request.POST or None, request.FILES or None)
        if request.method == 'POST' and form.is_valid():
            try:
                created, updated = import_abstracts(form.cleaned_data['file'])
            except (ValueError, OSError) as exc:
                form.add_error('file', str(exc))
            else:
                self.message_user(request, f'インポート完了: 新規 {created} 件、更新 {updated} 件。', messages.SUCCESS)
                return redirect('admin:program_presentation_changelist')
        return render(request, 'admin/program/presentation/import.html', {'form': form, 'opts': self.model._meta, 'title': 'アブストラクトのインポート'})


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ('presentation', 'position', 'is_presenter', 'family_name', 'given_name', 'family_name_en', 'given_name_en', 'affiliation')
    search_fields = ('presentation__submission_number', 'family_name', 'given_name', 'family_name_en', 'given_name_en')
    list_filter = ('is_presenter',)


class SessionChairInline(admin.TabularInline):
    model = SessionChair
    extra = 0
    fields = ('category', 'name')


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    form = SessionForm
    readonly_fields = ('end_time',)
    fields = ('name', 'code', 'annual_meeting', 'kind', 'date', 'start_time', 'venue',
              'minutes_per_presentation', 'talk_limit', 'slot_duration_minutes',
              'poster_session_one', 'poster_session_two', 'empty_duration_minutes', 'end_time', 'description')
    list_display = ('name', 'code', 'annual_meeting', 'kind', 'date', 'start_time', 'end_time', 'talk_limit', 'venue')
    list_filter = ('annual_meeting', 'kind', 'date', 'venue')

    def get_inlines(self, request, obj):
        return [SessionChairInline] if obj and obj.kind == Session.Kind.ORAL else []


class RoomInline(admin.TabularInline):
    model = Venue
    extra = 0
    fields = ('name',)


@admin.register(AnnualMeeting)
class AnnualMeetingAdmin(admin.ModelAdmin):
    list_display = ('name', 'meeting_year', 'abbreviation', 'start_date', 'end_date', 'location')
    search_fields = ('name', 'abbreviation', 'location')
    inlines = [RoomInline]

    @admin.display(description='開催年')
    def meeting_year(self, obj):
        return obj.year


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'annual_meeting')
    list_filter = ('annual_meeting',)
    search_fields = ('name',)
