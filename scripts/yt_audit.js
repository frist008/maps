// Снимок ВСЕХ полей страницы studio.youtube.com/video/<id>/edit (вкладка «Сведения») для сверки метаданных.
// Вставить через javascript_tool и вызвать: await ytAudit([document страницы, по умолчанию текущий]) → {поле: значение}.
window.ytAudit = async function (D = document) {
  // пауза через приёмник: в фоновой вкладке Chrome таймеры замедляются до раза в минуту, сетевой запрос — нет
  const sleep = ms => fetch('http://localhost:18765/sleep?ms=' + ms).catch(() => new Promise(r => setTimeout(r, ms)));
  // после цикла — ещё одна проверка: долгая пауза в фоновой вкладке могла съесть всё время ожидания
  const waitFor = async (fn, what, t = 20000) => { const s = Date.now(); while (Date.now() - s < t) { const v = fn(); if (v) return v; await sleep(250); } const v = fn(); if (v) return v; throw new Error('не дождался: ' + what); };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  await waitFor(() => D.querySelector('#title-textarea #textbox'), 'поле названия');
  await sleep(2500);
  // раскрыть «Развернуть» (доп. настройки), если свёрнуто
  const tg = [...D.querySelectorAll('#toggle-button')].find(b => b.offsetParent && /^\s*(Развернуть|Показать (больше|дополнительные))/.test(b.innerText));
  if (tg) { tg.click(); await sleep(2000); }
  const R = D.querySelector('ytcp-video-metadata-editor') || D.body;
  const o = { id: D.location.pathname.split('/')[2] };
  o['Название'] = clean(R.querySelector('#title-textarea #textbox').innerText);
  o['Описание'] = (R.querySelector('#description-textarea #textbox') || {}).innerText || '';
  // значок: выбранная карточка (свой загруженный или кадр из видео)
  const th = R.querySelector('ytcp-thumbnails-compact-editor, #thumbnail-editor, ytcp-video-custom-still-editor');
  o['Значок'] = th ? clean([...th.querySelectorAll('[aria-selected=true], [selected], .selected')].map(e => e.getAttribute('aria-label') || e.className).join(' ; ')) || 'нет выбора' : 'нет блока';
  // теги
  o['Теги'] = [...R.querySelectorAll('ytcp-chip-bar ytcp-chip, ytcp-free-text-chip-bar ytcp-chip')].map(c => clean(c.innerText)).filter(Boolean).join(', ');
  // радиокнопки: группа → выбранный вариант
  const groups = {};
  for (const r of R.querySelectorAll('tp-yt-paper-radio-button')) {
    const g = (r.closest('tp-yt-paper-radio-group') || {}).id || (r.getAttribute('name') || '').replace(/_(YES|NO|MFK|NOT_MFK|SELF|NONE|NOTIFY|OPT_IN|VISUAL.*)$/, '');
    if (!(g in groups)) groups[g] = '—';
    if (r.getAttribute('aria-checked') === 'true') groups[g] = clean(r.innerText).split(' . ')[0].slice(0, 60);
  }
  for (const [g, v] of Object.entries(groups)) o['радио:' + g] = v;
  // галочки
  for (const c of R.querySelectorAll('ytcp-checkbox-lit')) {
    const box = c.querySelector('[role=checkbox]') || c;
    const label = clean((c.querySelector('#label, .label') || c).innerText || c.getAttribute('aria-label')).slice(0, 60) || clean((c.parentElement || {}).innerText).slice(0, 60);
    o['галочка:' + label] = box.getAttribute('aria-checked');
  }
  // выпадающие списки и поля: подпись → значение
  // (по всей странице: в боковой колонке — «Видео по теме», «Субтитры»)
  for (const d of D.querySelectorAll('ytcp-dropdown-trigger')) {
    if (!d.offsetParent) continue;
    const lab = clean((d.querySelector('.label-text') || {}).innerText)
      || (d.closest('ytcp-video-metadata-playlists') ? 'Плейлисты' : '?');
    o['список:' + lab] = clean((d.querySelector('.dropdown-trigger-text') || {}).innerText);
  }
  o['Доступ'] = clean((D.querySelector('ytcp-video-metadata-visibility') || {}).innerText);
  o['Значок: картинка'] = ((D.querySelector('ytcp-video-info ytcp-img-with-fallback img, ytcp-thumbnails-compact-editor img') || {}).src || '').split('?')[0].split('/').slice(-1)[0];
  // текстовые поля (место съёмки и т.п.)
  for (const i of R.querySelectorAll('input')) {
    const lab = clean(i.getAttribute('aria-label') || i.placeholder);
    if (lab && i.offsetParent && i.type !== 'file' && i.type !== 'checkbox' && i.type !== 'radio') o['ввод:' + lab] = i.value;
  }
  // боковая колонка: доступ, видео по теме, субтитры, уведомления
  const side = D.body.innerText;
  for (const lab of ['Параметры доступа', 'Видео по теме', 'Субтитры', 'Уведомления', 'Качество видео', 'Ограничения']) {
    const m = side.match(new RegExp(lab + '\\n([^\\n]*)'));
    if (m) o['бок:' + lab] = clean(m[1]);
  }
  // каждый раздел страницы целиком (категория, ИИ, коллаборация, ремиксы, дата и место …) — чтобы не пропустить поле
  for (const e of R.querySelectorAll('.section-label-with-description')) {
    if (!e.offsetParent) continue;
    const lab = clean(e.innerText).split(' ')[0] && clean((e.innerText || '').split('\n')[0]);
    o['раздел:' + lab] = clean(e.parentElement.innerText).slice(0, 400);
  }
  localStorage.ytAuditLast = JSON.stringify(o);
  // на диск через receiver.py (должен быть запущен): <сессия>/_youtube_аудит/<id>.json
  if (window.ytAuditDir) {
    const r = await fetch('http://localhost:18765/save?path=' + encodeURIComponent(window.ytAuditDir + '/' + o.id + '.json'), { method: 'POST', body: JSON.stringify(o, null, 1) });
    o._saved = r.status;
  }
  return o;
};
