(() => {
  const buttons = Array.from(document.querySelectorAll('[data-hours]'));
  const status = document.querySelector('.period-status');
  const allowed = new Set([1, 24, 168]);
  const storageKey = 'bars-aw-period-hours-25878';
  let selected = 24;
  try {
    const saved = Number(sessionStorage.getItem(storageKey));
    if (allowed.has(saved)) selected = saved;
  } catch {}

  function apply(hours) {
    if (!allowed.has(hours)) return;
    if (typeof setFilter !== 'function') {
      status.textContent = 'Фильтр доступен при просмотре панели AW.';
      return;
    }
    const now = new Date();
    const from = new Date(now.getTime() - hours * 60 * 60 * 1000);
    const value = from.toISOString().slice(0, 19).replace('T', ' ');
    try {
      setFilter('opened_at_utc', value, '>=', 'column');
    } catch {
      status.textContent = 'Не удалось применить фильтр. Повторите выбор периода.';
      return;
    }
    selected = hours;
    for (const button of buttons) {
      button.setAttribute('aria-pressed', String(Number(button.dataset.hours) === selected));
    }
    try { sessionStorage.setItem(storageKey, String(selected)); } catch {}
    const label = hours === 1 ? 'Последний час' : hours === 24 ? 'Последние 24 часа' : 'Последние 7 дней';
    status.textContent = label + ' · с ' + value + ' UTC · повторное нажатие обновит окно';
  }

  const initial = setTimeout(() => apply(selected), 500);
  for (const button of buttons) {
    button.addEventListener('click', () => {
      clearTimeout(initial);
      apply(Number(button.dataset.hours));
    });
  }
})();
