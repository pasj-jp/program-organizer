from datetime import timedelta

from django import forms

from .models import AnnualMeeting, Presentation, Session, Venue


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
        fields = ('name', 'code', 'annual_meeting', 'date', 'start_time', 'minutes_per_presentation', 'empty_duration_minutes', 'venue', 'description')
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'description': forms.Textarea(attrs={'rows': 2, 'cols': 40}),
        }

    class Media:
        js = ('program/session_date.js',)

    def __init__(self, *args, **kwargs):
        meeting_id = kwargs.pop('meeting_id', None)
        super().__init__(*args, **kwargs)
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
        return cleaned


class PresentationForm(forms.ModelForm):
    class Meta:
        model = Presentation
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
    class Meta:
        model = Presentation
        fields = ('title', 'title_en', 'abstract', 'presentation_format',
                  'category_first', 'category_second', 'organizer_note',
                  'status', 'withdrawal_note')
        widgets = {
            'title': forms.Textarea(attrs={'rows': 2}),
            'title_en': forms.Textarea(attrs={'rows': 2}),
            'abstract': forms.Textarea(attrs={'rows': 5}),
            'organizer_note': forms.Textarea(attrs={'rows': 3}),
            'withdrawal_note': forms.Textarea(attrs={'rows': 2}),
        }
