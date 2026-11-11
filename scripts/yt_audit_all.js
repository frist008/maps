// Снимок всех полей ВСЕХ видео и шортсов канала: страницы видео по очереди грузятся во встроенный iframe,
// ytAudit (yt_audit.js, загрузить до этого) читает поля, receiver.py сохраняет <dir>/<id>.json.
// Запуск (не ждать — идёт долго): ytAuditAll('26.10/_youtube_аудит_канал'); прогресс: window.ytAuditAllState
window.ytAuditAll = async function (dir) {
  // пауза через приёмник: в фоновой вкладке Chrome таймеры замедляются до раза в минуту, сетевой запрос — нет
  const sleep = ms => fetch('http://localhost:18765/sleep?ms=' + ms).catch(() => new Promise(r => setTimeout(r, ms)));
  const st = window.ytAuditAllState = { total: 0, done: 0, errors: [], running: true };
  // список всех видео канала (API Studio)
  const api = async (path, body) => {
    const sid = (document.cookie.match(/SAPISID=([^;]+)/) || [])[1], ts = Math.floor(Date.now() / 1000);
    const h = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(ts + ' ' + sid + ' https://studio.youtube.com'));
    const auth = 'SAPISIDHASH ' + ts + '_' + [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
    const r = await fetch('/youtubei/v1/' + path + '?alt=json&key=' + ytcfg.get('INNERTUBE_API_KEY'), { method: 'POST', credentials: 'include',
      headers: { 'content-type': 'application/json', authorization: auth, 'x-origin': 'https://studio.youtube.com', 'x-goog-authuser': ytcfg.get('SESSION_INDEX') || '0', 'x-goog-pageid': ytcfg.get('DELEGATED_SESSION_ID') || '' },
      body: JSON.stringify({ context: ytcfg.get('INNERTUBE_CONTEXT'), ...body }) });
    return r.json();
  };
  const ch = ytcfg.get('CHANNEL_ID') || location.pathname.split('/')[2];
  let ids = [], tok;
  do {
    const L = await api('creator/list_creator_videos', { filter: { and: { operands: [{ channelIdIs: { value: ch } }] } }, order: 'VIDEO_ORDER_DISPLAY_TIME_DESC', pageSize: 50, mask: { videoId: true }, ...(tok ? { pageToken: tok } : {}) });
    ids.push(...(L.videos || []).map(v => v.videoId)); tok = L.nextPageToken;
  } while (tok && ids.length < 5000);
  st.total = ids.length; st.ids = ids;
  // iframe пересоздаётся каждые 15 видео: иначе память вкладки растёт и она перестаёт отвечать (зависло на 46-м)
  let f = null, used = 0;
  const fresh = () => {
    if (f) f.remove();
    f = document.createElement('iframe');
    f.style.cssText = 'position:fixed;left:0;top:0;width:1400px;height:900px;z-index:99999;background:#fff';
    document.body.appendChild(f); used = 0;
  };
  for (const id of ids) {
    if (!st.running) break;
    try {
      // уже снятые (прошлый прогон) — пропускать (до счётчика: пересоздание iframe — только по загруженным)
      if ((await (await fetch('http://localhost:18765/exists?path=' + encodeURIComponent(dir + '/' + id + '.json'))).text()) === '1') { st.done++; continue; }
      if (!f || used >= 15) fresh();
      used++;
      // ждать onload короткими паузами: один /sleep на 40 с держал соединение с приёмником даже после загрузки,
      // а у Chrome их 6 на хост — остальные запросы (exists/save/sleep) вставали в очередь и цикл «зависал»
      let loaded = false;
      f.onload = () => { loaded = true; };
      f.src = '/video/' + id + '/edit';
      for (const s0 = Date.now(); !loaded && Date.now() - s0 < 40000;) await sleep(500);
      if (!loaded) throw new Error('загрузка');
      const o = await window.ytAudit(f.contentDocument);
      if (o.id !== id) throw new Error('не та страница: ' + o.id);
      const r = await fetch('http://localhost:18765/save?path=' + encodeURIComponent(dir + '/' + id + '.json'), { method: 'POST', body: JSON.stringify(o, null, 1) });
      if (r.status !== 200) throw new Error('save ' + r.status);
    } catch (e) { st.errors.push(id + ': ' + e.message); }
    st.done++;
    await sleep(500);
  }
  st.running = false;
  if (f) f.remove();
  return st;
};
