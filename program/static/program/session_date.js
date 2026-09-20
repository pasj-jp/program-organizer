document.addEventListener('DOMContentLoaded', () => {
  const meeting = document.getElementById('id_annual_meeting');
  const date = document.getElementById('id_date');
  const room = document.getElementById('id_venue');
  if (!meeting || !date) return;

  function updateDates() {
    for (const option of date.options) {
      option.hidden = Boolean(option.value) && !option.dataset.meeting?.split(' ').includes(meeting.value);
      option.disabled = option.hidden;
    }
    if (date.selectedOptions[0]?.disabled) date.value = '';
    if (room) {
      for (const option of room.options) {
        option.hidden = Boolean(option.value) && option.dataset.meeting !== meeting.value;
        option.disabled = option.hidden;
      }
      if (room.selectedOptions[0]?.disabled) room.value = '';
    }
  }

  meeting.addEventListener('change', updateDates);
  updateDates();
});
