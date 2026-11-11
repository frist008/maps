// Сборщик карт ISW. Выполняется во вкладке understandingwar.org (Chrome пользователя,
// прошедший Cloudflare). Нужен запущенный scripts/receiver.py на 127.0.0.1:18765.
//
// Загрузка во вкладку:
//   eval(await (await fetch('http://127.0.0.1:18765/collect.js')).text())
// Один день:      await iswCollect(2026, 1, 2, '26.10')
// Диапазон в фоне: iswRun('2026-01-01', '2026-10-19', '26.10')   // статус: iswStatus()
// Начало диапазона — день после последнего собранного: python scripts/maps.py next
//
// Сайт не любит частые запросы: страница статьи — не чаще раза в 10 с,
// картинка — не чаще раза в 2 с. Паузы делаются запросом /sleep к приёмнику,
// потому что таймеры фоновой вкладки Chrome троттлятся до раза в минуту.

window.ISW_RECEIVER = 'http://127.0.0.1:18765';
window.ISW_PAGE_DELAY_MS = 10000;
window.ISW_IMAGE_DELAY_MS = 2000;

const ISW_MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july',
  'august', 'september', 'october', 'november', 'december'];
const iswPad = n => String(n).padStart(2, '0');
// fetch с тайм-аутом: зависший запрос не должен вешать весь сбор
const iswFetch = (url, opts = {}, ms = 60000) => {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  return fetch(url, { ...opts, signal: c.signal }).finally(() => clearTimeout(t));
};
const iswSleep = ms => fetch(`${ISW_RECEIVER}/sleep?ms=${ms}`).then(r => r.text());
const iswSave = (path, body) => iswFetch(`${ISW_RECEIVER}/save?path=${encodeURIComponent(path)}`,
  { method: 'POST', body }).then(x => x.text());
const iswExists = path => iswFetch(`${ISW_RECEIVER}/exists?path=${encodeURIComponent(path)}`)
  .then(r => r.text()).then(t => t === '1');

// Папка сессии = квартал, в котором пользователь пришёл за сбором (26.10 = сессия Q4 2026),
// а НЕ квартал даты карты: все дни диапазона одной сессии лежат в одной папке.

window.iswCollect = async function (y, m, d, session) {
  if (!session) throw new Error('нужна папка сессии, например 26.10');
  const date = `${y}-${iswPad(m)}-${iswPad(d)}`;
  const art = `/research/russia-ukraine/russian-offensive-campaign-assessment-${ISW_MONTHS[m - 1]}-${d}-${y}/`;

  await iswSleep(ISW_PAGE_DELAY_MS);
  const r = await iswFetch(art);
  const isHtml = (r.headers.get('content-type') || '').includes('html');
  if (r.status === 403) return { date, status: 403, note: 'Cloudflare — попросить пользователя пройти проверку' };
  if (r.status !== 200 || !isHtml) {
    const res = { date, article: location.origin + art, status: r.status, maps: [] };
    // Свежий день без статьи — возможно, её ещё не выложили: манифест не пишем, чтобы перепроверить позже.
    if (Date.now() - new Date(date + 'T00:00:00Z').getTime() < 3 * 86400e3) return res;
    // «статьи нет» — только 404/410; 429/5xx/200-не-HTML — сбой сайта: без манифеста, день перекачается
    if (r.status !== 404 && r.status !== 410) return { ...res, incomplete: `ответ ${r.status} — повторить позже` };
    await iswSave(`${session}/_manifest/${date}.json`, JSON.stringify(res, null, 1));
    return res;
  }
  const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
  const items = [...doc.querySelectorAll('a[href*="/map/"] img')]
    .map(i => ({ src: i.getAttribute('src'), page: i.closest('a').getAttribute('href') }));

  const seen = new Set();
  const maps = [];
  let blocked = false;
  let failsInRow = 0;
  for (const it of items) {
    if (seen.has(it.src)) continue;
    seen.add(it.src);
    const file = it.src.split('/').pop().replace(/\.\w+$/, '');
    const mm = file.match(/^(.*)-(January|February|March|April|May|June|July|August|September|October|November|December)-(\d{1,2})-(\d{4})(.*)$/i);
    let name = file, md = null, extra = '';
    if (mm) { name = mm[1]; md = [+mm[4], ISW_MONTHS.indexOf(mm[2].toLowerCase()) + 1, +mm[3]]; extra = mm[5]; }
    // Имя папки: без "-Direction"; общая карта войны — Overview.
    let folder = name.replace(/-Direction$/, '');
    if (/^Russo-Ukrainian-War$/i.test(folder)) folder = 'Overview';
    // Карта контроля территории (а не тематическая: захват судна, пожары NASA FIRMS, удары по НПЗ …):
    // страница /map/ начинается с "(a)ssessed-control-of-terrain" / "control-of-terrain" / "russo-ukrainian-war-"
    // или с короткого (≤4 слов) имени самой карты ("eastern-dnipropetrovsk-oblast-april-26-…").
    const slug = (it.page.split('/map/')[1] || '').toLowerCase();
    const onTopic = !!mm && (/^a?ssessed-control-of-terrain|^control-of-terrain/.test(slug) ||
      slug.startsWith('russo-ukrainian-war-') ||
      (slug.startsWith(name.toLowerCase() + '-') && name.split('-').length <= 4));
    const offTopic = !onTopic;

    let blob = null, used = '', lastStatus = 0;
    if (!offTopic) {
      // .png того же разрешения без потерь; запасной — исходный файл из статьи (webp/gif/…)
      for (const u of [it.src.replace(/\.\w+$/, '.png'), it.src]) {
        await iswSleep(ISW_IMAGE_DELAY_MS);
        const rr = await iswFetch(u, {}, 120000);
        lastStatus = rr.status;
        if (rr.ok && /image/.test(rr.headers.get('content-type') || '')) { blob = await rr.blob(); used = u; break; }
      }
      // две карты направлений подряд не скачались — скорее всего Cloudflare
      failsInRow = blob ? 0 : failsInRow + 1;
      if (failsInRow >= 2) blocked = true;
    }
    const day = md ? `${String(md[0]).slice(2)}.${iswPad(md[1])}.${iswPad(md[2])}` : `${String(y).slice(2)}.${iswPad(m)}.${iswPad(d)}`;
    const fname = day + (extra ? '_' + extra.replace(/^-/, '') : '');
    const entry = { folder, page: it.page, off_topic: offTopic,
      date_mismatch: !!(md && (md[0] !== y || md[1] !== m || md[2] !== d)) };
    if (blob) {
      // размер узнаём и сразу освобождаем декодированную картинку (~16 МБ): без close()
      // память копится и вкладка падает через 4–5 дней сбора
      const bm = await createImageBitmap(blob);
      const size = `${bm.width}x${bm.height}`;
      bm.close();
      const path = `${session}/_raw/${folder}/${fname}.${used.split('.').pop()}`;
      entry.saved = await iswSave(path, blob);
      Object.assign(entry, { file: path, image_url: used, size });
      // приёмник ответил не «saved <столько же байт>» — файл не записан или обрезан
      if (entry.saved !== `saved ${blob.size}`) entry.error = `приёмник: ${entry.saved} — повторить позже`;
    } else if (offTopic) {
      entry.image_url = it.src;  // тематическую карту не качаем, только помним
    } else {
      Object.assign(entry, { image_url: it.src, error: `image ${lastStatus} — повторить позже` });
    }
    maps.push(entry);
    if (blocked) break;
  }
  const res = { date, article: location.origin + art, status: blocked ? 403 : 200, maps };
  // статья есть, а карт по теме нет: страница-заглушка Cloudflare или ISW сменил имена файлов — не считать днём
  if (!maps.some(x => !x.off_topic)) res.incomplete = 'нет ни одной карты по теме — проверить страницу';
  // Манифест пишем только для полностью скачанного дня — иначе iswRun перекачает его.
  if (!blocked && !res.incomplete && !maps.some(x => x.error))
    await iswSave(`${session}/_manifest/${date}.json`, JSON.stringify(res, null, 1));
  return res;
};

// Проход по диапазону дат в фоне. Дни с готовым манифестом пропускаются,
// поэтому после остановки (капча, перезагрузка вкладки) просто запустить снова.
window.iswRun = async function (from, to, session) {
  if (!session) throw new Error('нужна папка сессии, например 26.10');
  window.iswLog = [];
  window.iswRunning = true;
  const status = { session, from, to, started: new Date().toISOString(), incomplete: [] };
  try {
    // пульс сразу: старый heartbeat.txt от прошлого прогона иначе поднимет тревогу у наблюдателя
    // (внутри try: приёмник не запущен — iswRun завершится со stopped, а не повиснет в running)
    await iswSave(`${session}/_collect/heartbeat.txt`, `${new Date().toISOString()} старт ${from}`);
    for (let t = new Date(from + 'T12:00:00Z'); t <= new Date(to + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() + 1)) {
      const y = t.getUTCFullYear(), m = t.getUTCMonth() + 1, d = t.getUTCDate();
      const date = `${y}-${iswPad(m)}-${iswPad(d)}`;
      if (await iswExists(`${session}/_manifest/${date}.json`)) continue;
      let res = null;
      for (let attempt = 1; attempt <= 4; attempt++) {
        try {
          res = await iswCollect(y, m, d, session);
        } catch (e) {
          // сетевой сбой — подождать минуту и повторить день
          res = { date, status: 'neterr', error: String(e) };
          await iswSleep(60000);
          continue;
        }
        if (res.status !== 403) break;
        // Cloudflare: открыть статью в скрытом фрейме — проверка обычно проходит сама
        await iswRefreshClearance(res.article || location.href);
      }
      iswLog.push(iswSummary(res));
      status.last = date;
      // день без манифеста (ошибка картинки, сбой сайта, нет карт) — в статус: `next` его не увидит как дыру
      if (res.incomplete || (res.maps || []).some(x => x.error)) status.incomplete.push(date);
      // пульс: наблюдатель снаружи поднимает тревогу, если он не обновлялся 10 мин
      await iswSave(`${session}/_collect/heartbeat.txt`, `${new Date().toISOString()} ${date}`);
      if (res.status === 403) { status.stopped = `403 на ${date}: Cloudflare, сам не прошёл`; break; }
      if (res.status === 'neterr') { status.stopped = `сеть на ${date}: ${res.error}`; break; }
    }
  } catch (e) {
    status.stopped = 'ошибка: ' + e;
  }
  status.finished = new Date().toISOString();
  status.log = iswLog;
  window.iswRunning = false;
  await iswSave(`${session}/_collect/status.json`, JSON.stringify(status, null, 1));
};

// Обновить допуск Cloudflare без перехода вкладки (переход стёр бы сборщик).
window.iswRefreshClearance = async function (url) {
  await iswSleep(30000);
  const f = document.createElement('iframe');
  f.style.cssText = 'position:fixed;width:400px;height:300px;left:-9999px;top:0';
  f.src = url;
  document.body.appendChild(f);
  await iswSleep(30000);  // время на проверку Cloudflare внутри фрейма
  f.remove();
};

window.iswStatus = () => ({ running: window.iswRunning, done: (window.iswLog || []).length,
  last: (window.iswLog || []).slice(-3) });

// Короткая сводка без URL (длинные URL в ответе инструмента иногда маскируются).
window.iswSummary = res => `${res.date} status=${res.status} maps=${(res.maps || []).length}` +
  (res.incomplete ? ` [НЕПОЛНЫЙ: ${res.incomplete}]` : '') + ' :: ' +
  (res.maps || []).map(x => x.folder + (x.off_topic ? '[skip]' : '') + (x.error ? '[ERR]' : '') +
    (x.date_mismatch ? '[DATE]' : '')).join(', ');
