// Заполнение окна загрузки YouTube Studio после выбора файла (file_upload). Вставить целиком через
// javascript_tool и вызвать: await ytFill(<запись из 26.10/_youtube_план.json>)
// same=true  — карта уже была на канале: копируем ВСЁ из прошлого шортса (описание, теги, плейлист, категорию).
// same=false — новая карта: копируем из «Херсон — Осень, Зима 2025» БЕЗ описания, теги города заменяем на p.tags.
// Сохраняет сам, только если: название совпало, «не для детей», «Ограниченный доступ», плейлист есть,
// описание есть/пусто как положено. Иначе возвращает сводку без сохранения.
window.ytFill = async function (p) {
  // пауза через приёмник: в фоновой вкладке Chrome setTimeout тормозится до раза в минуту, сетевой запрос — нет
  const sleep = ms => fetch('http://localhost:18765/sleep?ms=' + ms).catch(() => new Promise(r => setTimeout(r, ms)));
  // после цикла — ещё одна проверка: долгая пауза могла съесть всё время ожидания
  const waitFor = async (fn, what, t = 20000) => { const s = Date.now(); while (Date.now() - s < t) { const v = fn(); if (v) return v; await sleep(250); } const v = fn(); if (v) return v; throw new Error('не дождался: ' + what); };
  const dlg = () => document.querySelector('ytcp-uploads-dialog');
  const byText = (root, sel, txt) => [...root.querySelectorAll(sel)].find(e => e.innerText && e.innerText.trim() === txt);
  const chips = () => [...dlg().querySelectorAll('ytcp-free-text-chip-bar ytcp-chip')].filter(c => c.innerText.trim());
  const BASE = ['Россия', 'Украина', 'война', 'war', 'Russia', 'Ukraine'];

  await waitFor(() => dlg() && dlg().querySelector('#title-textarea #textbox'), 'окно загрузки');
  (await waitFor(() => byText(dlg(), 'ytcp-button, button', 'Импортировать сведения'), 'кнопка импорта')).click();
  const search = await waitFor(() => [...document.querySelectorAll('input')].find(i => i.placeholder === 'Найти свои видео' && i.offsetParent), 'поиск видео');
  search.focus(); search.value = p.src.split(' — ')[0];
  search.dispatchEvent(new Event('input', { bubbles: true }));
  search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
  (await waitFor(() => [...document.querySelectorAll('[role=option]')].find(o => (o.getAttribute('aria-label') || '').startsWith(p.src)), 'источник ' + p.src)).click();
  const copyBtn = await waitFor(() => [...document.querySelectorAll('ytcp-button, button')].find(b => b.innerText.trim() === 'Скопировать' && b.offsetParent), 'кнопка Скопировать');
  if (!p.same) {
    const box = copyBtn.closest('tp-yt-paper-dialog, ytcp-dialog') || document;
    // подпись и состояние — у самой галочки (общий контейнер может начинаться с «Описание» у всех)
    for (const cb of box.querySelectorAll('ytcp-checkbox-lit')) {
      const txt = (cb.innerText || cb.getAttribute('aria-label') || '').trim();
      const on = (cb.querySelector('[role=checkbox]') || cb).getAttribute('aria-checked') === 'true';
      if (txt.startsWith('Описание') && on) cb.click();
    }
  }
  // «Скопировать» иногда не срабатывает с первого клика — повторять, пока окно выбора не закроется
  const copyOpen = () => [...document.querySelectorAll('ytcp-button, button')].find(b => b.innerText.trim() === 'Скопировать' && b.offsetParent);
  for (let k = 0; k < 5 && copyOpen(); k++) { copyOpen().click(); await sleep(1500); }
  if (copyOpen()) throw new Error('окно «Скопировать» не закрылось');
  await sleep(2000);  // импорт иногда применяется с задержкой и перезаписывает поля — ждём
  const title = dlg().querySelector('#title-textarea #textbox');
  // импорт ставит название источника: дождаться его (до 10 с), иначе он перезапишет наше
  await waitFor(() => title.innerText.trim().startsWith(p.src), 'название из импорта', 10000).catch(() => {});
  for (let k = 0; k < 3 && title.innerText.trim() !== p.title; k++) {
    title.focus(); document.execCommand('selectAll', false); document.execCommand('insertText', false, p.title);
    await sleep(1500);
  }
  dlg().querySelector('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').click();
  if (!p.same) {  // описание новой карты — пустое, даже если галочка «Описание» не снялась
    const d = dlg().querySelector('#description-textarea #textbox');
    if (d && d.innerText.trim()) { d.focus(); document.execCommand('selectAll', false); document.execCommand('delete', false); }
  }

  // доп. настройки (теги, ИИ, реклама) раскрыть один раз: кнопка с подписью «Развернуть» / «Показать
  // дополнительные настройки» (у раскрытого блока подпись другая — повторный поиск её не найдёт и не свернёт)
  const tg = [...dlg().querySelectorAll('#toggle-button')].find(b => b.offsetParent && /^\s*(Развернуть|Показать (больше|дополнительные))/.test(b.innerText));
  if (tg) { tg.click(); await sleep(1200); }

  if (!p.same) {  // теги: базовые 6 + город(а) + карта, map — удалять по одному, перечитывая список
    const tagInput = () => dlg().querySelector('ytcp-free-text-chip-bar input, input[aria-label*="Теги"]');
    if (!tagInput() || !tagInput().offsetParent) throw new Error('поле тегов не видно — блок доп. настроек не раскрылся');
    for (let g = 0; g < 30; g++) {
      const c = chips().find(c => !BASE.includes(c.innerText.trim()));
      if (!c) break;
      (c.querySelector('#delete-icon') || c.querySelector('ytcp-icon-button, tp-yt-iron-icon')).click();
      await sleep(300);
    }
    const inp = dlg().querySelector('ytcp-free-text-chip-bar input, input[aria-label*="Теги"]');
    for (const t of [...(p.tags || []), 'карта', 'map']) {
      inp.focus(); inp.value = t; inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
      await sleep(300);
    }
  }
  // «ИИ — Нет» и «Прямая реклама — Нет»: если эти переключатели есть в окне загрузки — поставить сразу
  // (импорт их не ставит); нет — поставит ytFix после заливки (чек-лист isw-youtube)
  const radios = {};
  for (const n of ['VIDEO_HAS_ALTERED_CONTENT_NO', 'VIDEO_PAID_PRODUCT_PLACEMENT_NO']) {
    const r = dlg().querySelector(`tp-yt-paper-radio-button[name="${n}"]`);
    if (!r) { radios[n] = 'нет в окне'; continue; }
    if (r.getAttribute('aria-checked') !== 'true') { r.scrollIntoView({ block: 'center' }); r.click(); await sleep(400); }
    radios[n] = r.getAttribute('aria-checked');
  }
  const info = {
    radios,
    n: p.n, title: dlg().querySelector('#title-textarea #textbox').innerText,
    desc: ((dlg().querySelector('#description-textarea #textbox') || {}).innerText || '').slice(0, 40),
    kids: dlg().querySelector('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').getAttribute('aria-checked'),
    tags: p.same ? '(скопированы)' : chips().map(c => c.innerText.trim()).join(', '),
    playlist: byText(dlg(), '*', 'Россия против Украины') ? 'ok' : '—',
  };
  for (let i = 0; i < 3; i++) { dlg().querySelector('#next-button').click(); await sleep(1200); }
  (await waitFor(() => dlg().querySelector('tp-yt-paper-radio-button[name="PRIVATE"]'), 'шаг Доступ')).click();
  await sleep(500);
  info.access = dlg().querySelector('tp-yt-paper-radio-button[name="PRIVATE"]').getAttribute('aria-checked');
  info.link = (dlg().innerText.match(/https:\/\/youtube\.com\/\S+/) || [''])[0];
  const tagsOk = p.same || (p.tags || []).every(t => info.tags.includes(t)) && !/Херсон|Kherson/.test(info.tags);
  info.ok = info.title === p.title && info.kids === 'true' && info.access === 'true' && info.playlist === 'ok'
    && (p.same ? info.desc.length > 0 : info.desc.length === 0) && tagsOk
    && Object.values(radios).every(v => v === 'true' || v === 'нет в окне');
  // перед сохранением ещё раз: название в шапке окна — новое
  info.ok = info.ok && dlg().innerText.includes(p.title.slice(0, 40));
  if (info.ok) { dlg().querySelector('#done-button').click(); await sleep(3000); info.saved = !document.querySelector('ytcp-uploads-dialog #title-textarea'); }
  return info;
};
