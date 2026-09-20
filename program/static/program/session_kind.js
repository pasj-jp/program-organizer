document.addEventListener('DOMContentLoaded', () => {
  const kind = document.getElementById('id_kind');
  const meeting = document.getElementById('id_annual_meeting');
  if (!kind) return;

  function updateFields() {
    const fields = {
      date: kind.value !== 'facility_report',
      start_time: kind.value !== 'facility_report',
      venue: kind.value !== 'facility_report',
      minutes_per_presentation: kind.value === 'oral' || kind.value === 'other',
      talk_limit: kind.value === 'oral',
      slot_duration_minutes: kind.value === 'poster',
      poster_session_one: kind.value === 'facility_report',
      poster_session_two: kind.value === 'facility_report',
      empty_duration_minutes: kind.value === 'other',
    };
    for (const [name, visible] of Object.entries(fields)) {
      const input = document.getElementById(`id_${name}`);
      const row = input?.closest('p, .form-row');
      if (row) row.style.display = visible ? '' : 'none';
    }
    for (const name of ['poster_session_one', 'poster_session_two']) {
      const select = document.getElementById(`id_${name}`);
      if (!select || !meeting) continue;
      for (const option of select.options) {
        option.hidden = Boolean(option.value) && option.dataset.meeting !== meeting.value;
        option.disabled = option.hidden;
      }
      if (select.selectedOptions[0]?.disabled) select.value = '';
    }
  }

  kind.addEventListener('change', updateFields);
  meeting?.addEventListener('change', updateFields);
  updateFields();
});
