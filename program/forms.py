from datetime import timedelta

from django import forms

from .models import AnnualMeeting, Presentation, Session, Venue


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        values = data if isinstance(data, (list, tuple)) else [data]
        if not values:
            values = [None]
        return [super(MultipleFileField, self).clean(value, initial) for value in values]


class ProceedingsUploadForm(forms.Form):
    file = MultipleFileField(label='プロシーディングスPDF', widget=MultipleFileInput(
        attrs={'accept': '.pdf,application/pdf', 'aria-describedby': 'selected-files'}))

    def __init__(self, *args, meeting, **kwargs):
        super().__init__(*args, **kwargs)
        self.meeting = meeting

    def clean_file(self):
        uploads = self.cleaned_data['file']
        self.uploads = []
        errors = []
        names = set()
        for upload in uploads:
            try:
                if upload.name in names:
                    raise forms.ValidationError('同じファイル名が重複しています。')
                names.add(upload.name)
                talk = self.validate_upload(upload)
                self.uploads.append((talk, upload))
            except forms.ValidationError as exc:
                errors.extend(f'{upload.name}: {message}' for message in exc.messages)
        if errors:
            raise forms.ValidationError(errors)
        return uploads

    def validate_upload(self, upload):
        if not upload.name.endswith('.pdf') or not upload.name[:-4]:
            raise forms.ValidationError('ファイル名はプログラムコード.pdf（例: FRP001.pdf）にしてください。')
        if upload.size > 50 * 1024 * 1024:
            raise forms.ValidationError('PDFは50MB以下にしてください。')
        header = upload.read(8)
        upload.seek(0)
        if not header.startswith(b'%PDF-'):
            raise forms.ValidationError('PDF形式のファイルを選択してください。')
        presentation = Presentation.objects.filter(
            annual_meeting=self.meeting, program_number=upload.name[:-4]).first()
        if presentation is None:
            raise forms.ValidationError('この年会にファイル名と一致するプログラムコードの演題がありません。')
        from .models import proceedings_upload_path
        destination = proceedings_upload_path(presentation, upload.name)
        if Presentation.objects.filter(proceedings_file=destination).exclude(pk=presentation.pk).exists():
            raise forms.ValidationError('この保存先には再採番前の別演題のPDFがあります。保存済みPDFの配置を確認してください。')
        return presentation


class ProceedingsBuildForm(forms.Form):
    volume = forms.CharField(label='巻名', max_length=40)
    header1 = forms.CharField(label='ヘッダー1行目', max_length=150,
                             widget=forms.TextInput(attrs={'size': 90}))
    header2 = forms.CharField(label='ヘッダー2行目（会期・開催地）', max_length=150,
                             widget=forms.TextInput(attrs={'size': 90}))
    start_page = forms.IntegerField(label='開始ページ番号', min_value=1, max_value=999999, initial=1)

    def clean(self):
        cleaned = super().clean()
        from .proceedings_pdf import fitz
        from django.conf import settings
        from pathlib import Path
        if fitz is None:
            raise forms.ValidationError('PDF加工にはPyMuPDFが必要です。管理者にお問い合わせください。')
        font_dir = Path(settings.PROCEEDINGS_FONT_DIR)
        use_files = all((font_dir / name).exists() for name in ('times.ttf', 'timesi.ttf', 'timesbd.ttf'))
        for field in ('volume', 'header1', 'header2'):
            value = cleaned.get(field, '')
            if any(ord(char) < 32 or ord(char) > 126 for char in value):
                self.add_error(field, '元ビルダーの欧文フォントに合わせ、半角英数字・記号で入力してください。')
            if field.startswith('header') and value:
                try:
                    font = fitz.Font(fontfile=str(font_dir / 'timesi.ttf')) if use_files else fitz.Font(fontname='tiit')
                except Exception as exc:
                    raise forms.ValidationError('フォントを読み込めません。管理者はPROCEEDINGS_FONT_DIRを確認してください。') from exc
                if font.text_length(value, 10) > 575:
                    self.add_error(field, 'ヘッダーが用紙幅を超えます。文言を短くしてください。')
        return cleaned


class MeetingDateSelect(forms.Select):
    def __init__(self, *args, meeting_dates=None, **kwargs):
        self.meeting_dates = meeting_dates or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            option['attrs']['data-meeting'] = self.meeting_dates.get(str(value), '')
        return option


class SessionForm(forms.ModelForm):
    date = forms.ChoiceField(label='開催日', required=False)

    class Meta:
        model = Session
        fields = ('name', 'code', 'annual_meeting', 'kind', 'date', 'start_time', 'venue',
                  'minutes_per_presentation', 'talk_limit', 'slot_duration_minutes',
                  'poster_session_one', 'poster_session_two', 'empty_duration_minutes', 'description')
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'description': forms.Textarea(attrs={'rows': 2, 'cols': 40}),
        }

    class Media:
        js = ('program/session_date.js', 'program/session_kind.js')

    def __init__(self, *args, **kwargs):
        meeting_id = kwargs.pop('meeting_id', None)
        super().__init__(*args, **kwargs)
        self.fields['minutes_per_presentation'].required = False
        if not self.instance.pk:
            self.fields['kind'].initial = Session.Kind.ORAL
        if meeting_id is not None:
            self.fields['venue'].queryset = Venue.objects.filter(annual_meeting_id=meeting_id)
        rooms = self.fields['venue'].queryset
        self.fields['venue'].widget = MeetingDateSelect(
            choices=self.fields['venue'].choices,
            meeting_dates={str(room.pk): str(room.annual_meeting_id or '') for room in rooms},
        )
        choices = [('', '---------')]
        meeting_dates = {}
        meetings = AnnualMeeting.objects.all()
        if meeting_id is not None:
            meetings = meetings.filter(pk=meeting_id)
        for meeting in meetings:
            day = meeting.start_date
            while day <= meeting.end_date:
                value = day.isoformat()
                if value not in meeting_dates:
                    choices.append((value, day.strftime('%Y年%m月%d日')))
                    meeting_dates[value] = str(meeting.pk)
                else:
                    meeting_dates[value] += f' {meeting.pk}'
                day += timedelta(days=1)
        self.fields['date'].choices = choices
        self.fields['date'].widget = MeetingDateSelect(choices=choices, meeting_dates=meeting_dates)
        posters = Session.objects.filter(kind=Session.Kind.POSTER)
        if meeting_id is not None:
            posters = posters.filter(annual_meeting_id=meeting_id)
        if self.instance.pk:
            posters = posters.exclude(pk=self.instance.pk)
        for field_name in ('poster_session_one', 'poster_session_two'):
            field = self.fields[field_name]
            field.queryset = posters
            field.widget = MeetingDateSelect(
                choices=field.choices,
                meeting_dates={str(poster.pk): str(poster.annual_meeting_id or '') for poster in posters},
            )
        self.fields['annual_meeting'].required = True

    def clean_date(self):
        value = self.cleaned_data['date']
        return forms.DateField().clean(value) if value else None

    def clean(self):
        cleaned = super().clean()
        meeting = cleaned.get('annual_meeting')
        date = cleaned.get('date')
        if meeting and date and not meeting.start_date <= date <= meeting.end_date:
            self.add_error('date', '開催日は選択した年会の会期内から選んでください。')
        room = cleaned.get('venue')
        if meeting and room and room.annual_meeting_id != meeting.pk:
            self.add_error('venue', 'この年会の部屋を選んでください。')
        kind = cleaned.get('kind')
        if cleaned.get('minutes_per_presentation') is None:
            cleaned['minutes_per_presentation'] = 20
        if kind in (Session.Kind.ORAL, Session.Kind.POSTER):
            if not date:
                self.add_error('date', '開催日を選んでください。')
            if not cleaned.get('start_time'):
                self.add_error('start_time', '開始時刻を入力してください。')
            cleaned['poster_session_one'] = None
            cleaned['poster_session_two'] = None
        if kind == Session.Kind.FACILITY_REPORT:
            cleaned['date'] = None
            cleaned['start_time'] = None
            cleaned['venue'] = None
            cleaned['talk_limit'] = None
            cleaned['slot_duration_minutes'] = None
        elif kind == Session.Kind.ORAL:
            cleaned['slot_duration_minutes'] = None
        elif kind == Session.Kind.POSTER:
            cleaned['talk_limit'] = None
        return cleaned


class PresentationForm(forms.ModelForm):
    class Meta:
        model = Presentation
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['annual_meeting'].required = True
        session_id = self.data.get('session') if self.is_bound else self.instance.session_id
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            session_id = None
        meeting_id = Session.objects.filter(pk=session_id).values_list('annual_meeting_id', flat=True).first()
        rooms = Venue.objects.filter(annual_meeting_id=meeting_id) if meeting_id else Venue.objects.none()
        if self.instance.venue_id:
            rooms = rooms | Venue.objects.filter(pk=self.instance.venue_id)
        self.fields['venue'].queryset = rooms


class BoardPresentationForm(forms.ModelForm):
    confirmed_category = forms.ChoiceField(label='カテゴリー', required=False)

    class Meta:
        model = Presentation
        fields = ('title', 'title_en', 'abstract', 'presentation_format',
                  'category_first', 'category_second', 'applies_for_annual_award',
                  'confirmed_category', 'organizer_note',
                  'status', 'withdrawal_note')
        widgets = {
            'title': forms.Textarea(attrs={'rows': 2}),
            'title_en': forms.Textarea(attrs={'rows': 2}),
            'abstract': forms.Textarea(attrs={'rows': 5}),
            'organizer_note': forms.Textarea(attrs={'rows': 3}),
            'withdrawal_note': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        first = self.data.get('category_first') if self.is_bound else self.instance.category_first
        second = self.data.get('category_second') if self.is_bound else self.instance.category_second
        choices = [('', '未設定')]
        for label, value in (('第1希望', first), ('第2希望', second)):
            if value and value not in [choice[0] for choice in choices]:
                choices.append((value, f'{label}: {value}'))
        self.fields['confirmed_category'].choices = choices


class SessionChairsForm(forms.Form):
    def __init__(self, *args, session, **kwargs):
        super().__init__(*args, **kwargs)
        names = {chair.category: chair.name for chair in session.chairs.all()}
        categories = set(session.presentations.exclude(confirmed_category='').values_list('confirmed_category', flat=True)) | set(names)
        self.categories = sorted(categories)
        for index, category in enumerate(self.categories):
            self.fields[f'chair_{index}'] = forms.CharField(label=category, max_length=200, required=False,
                initial=names.get(category, ''), help_text='空欄で保存すると座長を削除します。')

    def save(self, session):
        for index, category in enumerate(self.categories):
            name = self.cleaned_data[f'chair_{index}'].strip()
            if name:
                session.chairs.update_or_create(category=category, defaults={'name': name})
            else:
                session.chairs.filter(category=category).delete()


class ProgramExcelImportForm(forms.Form):
    file = forms.FileField(label='program.xlsx 形式のExcelファイル')

    def clean_file(self):
        file = self.cleaned_data['file']
        if not file.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('.xlsx ファイルを選択してください。')
        return file


class AbstractExcelImportForm(ProgramExcelImportForm):
    file = forms.FileField(label='abstract.xlsx 形式のExcelファイル')
