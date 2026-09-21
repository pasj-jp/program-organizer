from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Prefetch

from .models import Presentation, Session


PIXELS_PER_MINUTE = 1.2


def minutes(value):
    return value.hour * 60 + value.minute


def assign_lanes(blocks):
    """Place overlapping sessions in separate lanes within one venue."""
    cluster = []
    lane_ends = []
    cluster_end = -1
    for block in sorted(blocks, key=lambda item: (item['start'], item['end'], item['session'].pk)):
        if cluster and block['start'] >= cluster_end:
            for item in cluster:
                item['lane_count'] = len(lane_ends)
            cluster = []
            lane_ends = []
        lane = next((index for index, end in enumerate(lane_ends) if end <= block['start']), None)
        if lane is None:
            lane = len(lane_ends)
            lane_ends.append(block['end'])
        else:
            lane_ends[lane] = block['end']
        block['lane'] = lane
        cluster.append(block)
        cluster_end = max(cluster_end, block['end'])
    for item in cluster:
        item['lane_count'] = len(lane_ends)


def build_timetable(meeting, venue_width=250):
    session_talks = Presentation.objects.prefetch_related('authors', 'venue')
    sessions = list(Session.objects.filter(annual_meeting=meeting).select_related('venue').prefetch_related('chairs',
        Prefetch('presentations', queryset=session_talks, to_attr='session_talks')
    ).order_by('date', 'start_time', 'name', 'pk'))
    facility_by_poster = defaultdict(list)
    for report in sessions:
        if report.kind != Session.Kind.FACILITY_REPORT:
            continue
        report_talks = sorted(report.session_talks,
                              key=lambda talk: (talk.session_order, talk.submission_number, talk.pk))
        for poster_id in (report.poster_session_one_id, report.poster_session_two_id):
            if poster_id:
                facility_by_poster[poster_id].extend(report_talks)
    by_date = defaultdict(list)
    unscheduled = []
    for session in sessions:
        if session.kind == Session.Kind.FACILITY_REPORT:
            continue
        talks = sorted(session.session_talks,
                       key=lambda talk: (talk.session_order, talk.submission_number, talk.pk))
        session.timetable_talks = talks
        if not session.date or not session.start_time or not meeting.start_date <= session.date <= meeting.end_date:
            unscheduled.append(session)
            continue
        start = minutes(session.start_time)
        duration = session.slot_minutes() or 30
        end = start + duration
        talk_rows = []
        displayed_talks = talks + (facility_by_poster[session.pk] if session.kind == Session.Kind.POSTER else [])
        for index, talk in enumerate(displayed_talks):
            if session.kind == Session.Kind.POSTER:
                display_start = session.start_time
                display_end = (datetime.combine(session.date, display_start)
                               + timedelta(minutes=duration)).time()
            else:
                computed_start = datetime.combine(session.date, session.start_time) + timedelta(
                    minutes=index * session.minutes_per_presentation)
                display_start = talk.start_time or computed_start.time()
                display_end = talk.end_time or (datetime.combine(session.date, display_start)
                                                + timedelta(minutes=session.minutes_per_presentation)).time()
            talk_rows.append({
                'talk': talk,
                'withdrawn': talk.status == Presentation.Status.WITHDRAWN,
                'start': display_start.strftime('%H:%M'),
                'end': display_end.strftime('%H:%M'),
                'presenters': [author for author in talk.authors.all() if author.is_presenter],
            })
        by_date[session.date].append({
            'session': session, 'talks': talks, 'talk_rows': talk_rows,
            'start': start, 'end': end,
            'duration': duration,
            'facility_count': len(facility_by_poster[session.pk]) if session.kind == Session.Kind.POSTER else 0,
            'venue_key': session.venue_id, 'venue_name': session.venue.name if session.venue else '部屋未設定',
            'first_number': talks[0].program_number if talks else None,
            'last_number': talks[-1].program_number if talks else None,
        })

    all_blocks = [block for blocks in by_date.values() for block in blocks]
    first_hour = min(8, min((block['start'] for block in all_blocks), default=8 * 60) // 60)
    last_hour = max(18, (max((block['end'] for block in all_blocks), default=18 * 60) + 59) // 60)
    start_minute = first_hour * 60
    height = (last_hour - first_hour) * 60 * PIXELS_PER_MINUTE
    venue_names = {block['venue_key']: block['venue_name'] for block in all_blocks}
    venue_keys = sorted(venue_names, key=lambda key: (key is None, venue_names[key]))
    days = []
    day = meeting.start_date
    while day <= meeting.end_date:
        blocks = by_date[day]
        venues = []
        for venue_key in venue_keys:
            venue_blocks = [block for block in blocks if block['venue_key'] == venue_key]
            assign_lanes(venue_blocks)
            for block in venue_blocks:
                block['top'] = (block['start'] - start_minute) * PIXELS_PER_MINUTE
                block['height'] = max((block['end'] - block['start']) * PIXELS_PER_MINUTE, 22)
                block['show_meta'] = block['height'] >= 48
                block['left'] = round(block['lane'] * 100 / block['lane_count'], 4)
                block['width'] = round(100 / block['lane_count'], 4)
            venues.append({'id': venue_key, 'name': venue_names[venue_key], 'blocks': venue_blocks})
        days.append({
            'date': day, 'venues': venues, 'height': height, 'grid_width': 64 + len(venues) * venue_width,
            'first_minute': start_minute, 'pixels_per_minute': PIXELS_PER_MINUTE,
            'hours': [{'label': f'{hour:02d}:00', 'top': (hour - first_hour) * 60 * PIXELS_PER_MINUTE}
                      for hour in range(first_hour, last_hour + 1)],
            'sessions': sorted(blocks, key=lambda block: (block['start'], block['venue_name'], block['session'].pk)),
        })
        day += timedelta(days=1)
    return days, unscheduled
