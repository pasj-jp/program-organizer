from datetime import datetime, timedelta
from .storage import ProceedingsStorage

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import Max
from django.db.models.functions import ExtractYear


def proceedings_upload_path(instance, filename):
    code = instance.program_number
    if not code or any(character in code for character in ('/', '\\', '\x00')) or code in {'.', '..'}:
        raise ValidationError('保存できないプログラムコードです。')
    return f'{instance.annual_meeting.year}/{code}.pdf'


class AnnualMeeting(models.Model):
    name = models.CharField('年会名', max_length=200)
    abbreviation = models.CharField('略称', max_length=50, unique=True, validators=[
        RegexValidator(r'^[A-Za-z0-9_-]+$', '半角英数字、ハイフン、アンダースコアで入力してください。'),
    ], help_text='年会を識別する略称です（例: PASJ2026）。URLには開催年を使います。')
    start_date = models.DateField('会期開始日')
    end_date = models.DateField('会期終了日')
    location = models.CharField('会場', max_length=200)

    class Meta:
        verbose_name = '年会情報'
        verbose_name_plural = '年会情報'
        ordering = ['-start_date']
        constraints = [models.UniqueConstraint(ExtractYear('start_date'), name='unique_annual_meeting_year')]

    def __str__(self):
        return self.name

    @property
    def year(self):
        return self.start_date.year if self.start_date else None

    def clean(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({'end_date': '会期終了日は開始日以降にしてください。'})
        if self.start_date and type(self).objects.filter(start_date__year=self.start_date.year).exclude(pk=self.pk).exists():
            raise ValidationError({'start_date': f'{self.start_date.year}年の年会は既に登録されています。'})


class Venue(models.Model):
    annual_meeting = models.ForeignKey(AnnualMeeting, verbose_name='年会情報', on_delete=models.PROTECT,
                                       null=True, related_name='rooms')
    name = models.CharField('部屋名', max_length=200)

    class Meta:
        verbose_name = '部屋'
        verbose_name_plural = '部屋'
        constraints = [models.UniqueConstraint(fields=['annual_meeting', 'name'], name='unique_room_per_meeting')]

    def __str__(self):
        return self.name


class Session(models.Model):
    class Kind(models.TextChoices):
        ORAL = 'oral', '口頭発表'
        POSTER = 'poster', 'ポスター発表'
        FACILITY_REPORT = 'facility_report', '施設報告ポスター'
        OTHER = 'other', 'その他・従来形式'

    name = models.CharField('セッション名', max_length=200)
    kind = models.CharField('発表形式', max_length=20, choices=Kind.choices, default=Kind.OTHER)
    code = models.CharField('セッションコード', max_length=20, unique=True, null=True, blank=True,
                            validators=[RegexValidator(r'^[A-Z0-9]+$', '半角英大文字と数字で入力してください。')],
                            help_text='例: FRO。発表順に FRO01、FRO02… を割り当てます。')
    annual_meeting = models.ForeignKey(AnnualMeeting, verbose_name='年会情報', on_delete=models.PROTECT, null=True, blank=True, related_name='sessions')
    date = models.DateField('開催日', null=True, blank=True)
    start_time = models.TimeField('開始時刻', null=True, blank=True)
    end_time = models.TimeField('終了時刻', null=True, blank=True)
    minutes_per_presentation = models.PositiveSmallIntegerField('1講演あたりの時間（分）', default=20)
    talk_limit = models.PositiveSmallIntegerField('講演数', null=True, blank=True)
    slot_duration_minutes = models.PositiveSmallIntegerField('時間枠の長さ（分）', null=True, blank=True)
    poster_session_one = models.ForeignKey('self', verbose_name='対応するポスターセッション1',
        on_delete=models.PROTECT, null=True, blank=True, related_name='facility_reports_first')
    poster_session_two = models.ForeignKey('self', verbose_name='対応するポスターセッション2',
        on_delete=models.PROTECT, null=True, blank=True, related_name='facility_reports_second')
    empty_duration_minutes = models.PositiveSmallIntegerField('講演なしの枠の長さ（分）', null=True, blank=True,
        help_text='休憩や式典など、演題を割り当てない枠だけに使用します。')
    venue = models.ForeignKey(Venue, verbose_name='部屋', on_delete=models.PROTECT, null=True, blank=True)
    description = models.TextField('備考', blank=True)
    board_order = models.PositiveIntegerField('編成画面の表示順', default=0)

    class Meta:
        verbose_name = 'セッション'
        verbose_name_plural = 'セッション'
        ordering = ['date', 'start_time', 'name']

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('終了時刻は開始時刻より後にしてください。')
        if self.annual_meeting_id and self.date:
            meeting = self.annual_meeting
            if not meeting.start_date <= self.date <= meeting.end_date:
                raise ValidationError({'date': '開催日は年会の会期内から選んでください。'})
        if self.venue_id and self.venue.annual_meeting_id != self.annual_meeting_id:
            raise ValidationError({'venue': 'この年会の部屋を選んでください。'})
        if self.minutes_per_presentation == 0:
            raise ValidationError({'minutes_per_presentation': '1分以上を指定してください。'})
        if self.empty_duration_minutes == 0:
            raise ValidationError({'empty_duration_minutes': '1分以上を指定してください。'})
        if self.kind == self.Kind.ORAL:
            if not self.talk_limit:
                raise ValidationError({'talk_limit': '講演数を1件以上指定してください。'})
            if self.pk and self.presentations.count() > self.talk_limit:
                raise ValidationError({'talk_limit': '割り当て済みの演題数より少なくできません。'})
        elif self.pk and self.chairs.exists():
            raise ValidationError({'kind': '座長が登録されているため口頭発表以外に変更できません。'})
        if self.kind == self.Kind.POSTER and not self.slot_duration_minutes:
            raise ValidationError({'slot_duration_minutes': '時間枠の長さを1分以上指定してください。'})
        if self.kind == self.Kind.FACILITY_REPORT:
            first, second = self.poster_session_one, self.poster_session_two
            if not first or not second or first.pk == second.pk:
                raise ValidationError('異なるポスターセッションを2つ選んでください。')
            for field, poster in (('poster_session_one', first), ('poster_session_two', second)):
                if poster.kind != self.Kind.POSTER or poster.annual_meeting_id != self.annual_meeting_id:
                    raise ValidationError({field: '同じ年会のポスターセッションを選んでください。'})
        if self.pk:
            if self.presentations.exclude(annual_meeting_id=self.annual_meeting_id).exists():
                raise ValidationError({'annual_meeting': '割り当て済みの演題と異なる年会へ変更できません。'})
            linked_reports = self.facility_reports_first.all() | self.facility_reports_second.all()
            if self.kind != self.Kind.POSTER and linked_reports.exists():
                raise ValidationError({'kind': '施設報告ポスターから参照されているため変更できません。'})
            if linked_reports.exclude(annual_meeting_id=self.annual_meeting_id).exists():
                raise ValidationError({'annual_meeting': '施設報告ポスターと異なる年会へ変更できません。'})
            if self.kind != self.Kind.OTHER and any(
                    not self.accepts_presentation(talk) for talk in self.presentations.all()):
                raise ValidationError({'kind': '割り当て済み演題の発表形式と一致しません。'})

    def accepts_presentation(self, presentation):
        if self.kind == self.Kind.OTHER:
            return True
        return self.kind == presentation.format_kind

    def slot_minutes(self):
        if self.kind == self.Kind.ORAL:
            return (self.talk_limit or 0) * self.minutes_per_presentation
        if self.kind == self.Kind.POSTER:
            return self.slot_duration_minutes
        if self.kind == self.Kind.FACILITY_REPORT:
            return None
        count = self.presentations.count()
        return count * self.minutes_per_presentation if count else self.empty_duration_minutes

    def recalculate_end_time(self):
        end_time = None
        duration = self.slot_minutes()
        if self.start_time and duration:
            end_time = (datetime.combine(self.date or datetime.today().date(), self.start_time)
                        + timedelta(minutes=duration)).time()
        if self.end_time != end_time:
            type(self).objects.filter(pk=self.pk).update(end_time=end_time)
            self.end_time = end_time

    def recalculate_program_numbers(self, previous_code=None):
        if not self.code:
            if previous_code:
                self.presentations.filter(program_number__startswith=previous_code).update(program_number=None)
            return
        talks = list(self.presentations.order_by('session_order', 'submission_number', 'pk'))
        numbers = [f'{self.code}{position:02d}' for position in range(1, len(talks) + 1)]
        conflict = Presentation.objects.filter(annual_meeting_id=self.annual_meeting_id,
            program_number__in=numbers).exclude(session=self).exists()
        if conflict:
            raise ValidationError({'code': '生成されるプログラム番号が他の演題と重複します。'})
        with transaction.atomic():
            self.presentations.update(program_number=None)
            for talk, number in zip(talks, numbers):
                Presentation.objects.filter(pk=talk.pk).update(program_number=number)

    def save(self, *args, **kwargs):
        previous_code = None
        if self.pk:
            previous_code = type(self).objects.filter(pk=self.pk).values_list('code', flat=True).first()
        with transaction.atomic():
            if self._state.adding and not self.board_order:
                highest = type(self).objects.filter(annual_meeting_id=self.annual_meeting_id).aggregate(Max('board_order'))['board_order__max'] or 0
                self.board_order = highest + 1
            super().save(*args, **kwargs)
            self.recalculate_end_time()
            if self.code != previous_code:
                self.recalculate_program_numbers(previous_code=previous_code)


class Presentation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', '発表予定'
        WITHDRAWN = 'withdrawn', '発表取り消し'

    annual_meeting = models.ForeignKey(AnnualMeeting, verbose_name='年会情報', on_delete=models.PROTECT,
        null=True, blank=True, related_name='presentations')
    submission_number = models.CharField('演題登録番号', max_length=50)
    registration_number = models.CharField('参加登録番号', max_length=50, blank=True)
    login_id = models.CharField('ログインID', max_length=100, blank=True)
    email = models.EmailField('メールアドレス', blank=True)
    title = models.TextField('題目')
    title_en = models.TextField('題目（英語）', blank=True)
    abstract = models.TextField('要旨', blank=True)
    presentation_format = models.CharField('発表形式', max_length=200, blank=True)
    category_first = models.CharField('第1希望カテゴリー', max_length=200, blank=True)
    category_second = models.CharField('第2希望カテゴリー', max_length=200, blank=True)
    applies_for_annual_award = models.BooleanField('年会賞に応募', default=False)
    confirmed_category = models.CharField('カテゴリー', max_length=200, blank=True)
    author_text = models.TextField('著者情報', blank=True)
    author_text_en = models.TextField('著者情報（英語）', blank=True)
    affiliation_text = models.TextField('著者所属情報', blank=True)
    affiliation_text_en = models.TextField('著者所属情報（英語）', blank=True)
    program_number = models.CharField('プログラム番号', max_length=50, null=True, blank=True)
    proceedings_file = models.FileField('プロシーディングスPDF', upload_to=proceedings_upload_path,
                                       storage=ProceedingsStorage(), blank=True)
    session = models.ForeignKey(Session, verbose_name='セッション', on_delete=models.SET_NULL, null=True, blank=True, related_name='presentations')
    start_time = models.TimeField('発表開始時刻', null=True, blank=True)
    end_time = models.TimeField('発表終了時刻', null=True, blank=True)
    venue = models.ForeignKey(Venue, verbose_name='部屋（個別指定）', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField('状態', max_length=20, choices=Status.choices, default=Status.ACTIVE)
    withdrawal_note = models.TextField('取り消し理由・備考', blank=True)
    organizer_note = models.TextField('編成メモ', blank=True)
    session_order = models.PositiveIntegerField('セッション内の順序', default=0)

    class Meta:
        verbose_name = '演題'
        verbose_name_plural = '演題'
        ordering = ['program_number', 'submission_number']
        constraints = [
            models.UniqueConstraint(fields=['annual_meeting', 'submission_number'], name='unique_submission_per_meeting'),
            models.UniqueConstraint(fields=['annual_meeting', 'program_number'], name='unique_program_per_meeting'),
        ]

    def __str__(self):
        return f'{self.submission_number} {self.title}'

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('発表終了時刻は開始時刻より後にしてください。')
        if self.session_id:
            if self.session.annual_meeting_id != self.annual_meeting_id:
                raise ValidationError({'session': '演題と同じ年会のセッションを選んでください。'})
            if not self.session.accepts_presentation(self):
                raise ValidationError('発表形式がセッションと一致しません。')
            if (self.session.kind == Session.Kind.ORAL and self.session.talk_limit
                    and self.session.presentations.exclude(pk=self.pk).count() >= self.session.talk_limit):
                raise ValidationError('この口頭発表セッションは満員です。')
        if self.venue_id and self.session_id and self.venue.annual_meeting_id != self.session.annual_meeting_id:
            raise ValidationError('セッションと同じ年会の部屋を選んでください。')
        if self.confirmed_category and self.confirmed_category not in {self.category_first, self.category_second}:
            raise ValidationError({'confirmed_category': '第1希望または第2希望のカテゴリーを選んでください。'})

    def save(self, *args, **kwargs):
        old_session_id = None
        if self.pk:
            old_session_id = type(self).objects.filter(pk=self.pk).values_list('session_id', flat=True).first()
        with transaction.atomic():
            if old_session_id != self.session_id:
                self.confirmed_category = self.category_first if self.session_id else ''
                if kwargs.get('update_fields') is not None:
                    kwargs['update_fields'] = set(kwargs['update_fields']) | {'confirmed_category'}
            if old_session_id != self.session_id and old_session_id:
                old_session = Session.objects.filter(pk=old_session_id).first()
                if old_session and old_session.code:
                    self.program_number = None
                    if kwargs.get('update_fields') is not None:
                        kwargs['update_fields'] = set(kwargs['update_fields']) | {'program_number'}
            super().save(*args, **kwargs)
            for session in Session.objects.filter(pk__in={self.session_id, old_session_id} - {None}):
                session.recalculate_end_time()
                session.recalculate_program_numbers()

    @property
    def effective_venue(self):
        return self.venue or (self.session.venue if self.session_id else None)

    @property
    def format_kind(self):
        value = self.presentation_format
        if value.startswith('口頭発表'):
            return Session.Kind.ORAL
        if value.startswith('ポスター発表'):
            return Session.Kind.POSTER
        if value.startswith(('施設技術報告ポスター', '施設報告ポスター')):
            return Session.Kind.FACILITY_REPORT
        return Session.Kind.OTHER


class SessionChair(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='chairs', verbose_name='セッション')
    category = models.CharField('カテゴリー', max_length=200)
    name = models.CharField('座長', max_length=200)

    class Meta:
        verbose_name = '座長'
        verbose_name_plural = '座長'
        ordering = ['category', 'pk']
        constraints = [models.UniqueConstraint(fields=['session', 'category'], name='unique_session_chair_category')]

    def __str__(self):
        return f'{self.category}: {self.name}'

    def clean(self):
        if self.session_id and self.session.kind != Session.Kind.ORAL:
            raise ValidationError({'session': '座長は口頭発表セッションにのみ登録できます。'})
        if self.session_id and self.category and not self.session.presentations.filter(confirmed_category=self.category).exists():
            raise ValidationError({'category': 'このセッションの演題にあるカテゴリーを指定してください。'})


class Author(models.Model):
    presentation = models.ForeignKey(Presentation, on_delete=models.CASCADE, related_name='authors', verbose_name='演題')
    position = models.PositiveSmallIntegerField('著者順')
    is_presenter = models.BooleanField('登壇者', default=False)
    family_name = models.CharField('姓', max_length=200, blank=True)
    given_name = models.CharField('名', max_length=200, blank=True)
    family_name_kana = models.CharField('姓カナ', max_length=200, blank=True)
    given_name_kana = models.CharField('名カナ', max_length=200, blank=True)
    family_name_en = models.CharField('姓（英語）', max_length=200, blank=True)
    given_name_en = models.CharField('名（英語）', max_length=200, blank=True)
    middle_name = models.CharField('ミドルネーム', max_length=200, blank=True)
    affiliation = models.TextField('所属', blank=True)
    affiliation_en = models.TextField('所属（英語）', blank=True)

    class Meta:
        verbose_name = '著者'
        verbose_name_plural = '著者'
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['presentation', 'position'], name='unique_author_position')]

    def __str__(self):
        return f'{self.family_name} {self.given_name}'.strip() or f'著者 {self.position}'
