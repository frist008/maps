// Правка уже залитого видео на странице studio.youtube.com/video/<id>/edit. Вставить целиком через
// javascript_tool и вызвать: await ytFix({rel: '<полное название связанного видео>', title?: '<новое название>',
//   reps?: [['было', 'стало'], …]})
// rel — «Видео по теме» (у шортса — ссылка под видео). Сохраняет и возвращает, что стоит в полях после сохранения.
window.ytFix = async function (p) {
  // пауза через приёмник: в фоновой вкладке Chrome setTimeout тормозится до раза в минуту, сетевой запрос — нет
  const sleep = ms => fetch('http://localhost:18765/sleep?ms=' + ms).catch(() => new Promise(r => setTimeout(r, ms)));
  // после цикла — ещё одна проверка: долгая пауза могла съесть всё время ожидания
  const waitFor = async (fn, what, t = 20000) => { const s = Date.now(); while (Date.now() - s < t) { const v = fn(); if (v) return v; await sleep(250); } const v = fn(); if (v) return v; throw new Error('не дождался: ' + what); };
  const setText = (el, txt) => { el.focus(); document.execCommand('selectAll', false); document.execCommand('insertText', false, txt); };
  const res = { miss: [] };
  let changed = false;  // что-то правили — тогда без ответа сервера на «Сохранить» ok не будет
  const title = await waitFor(() => document.querySelector('#title-textarea #textbox'), 'поле названия');
  const desc = await waitFor(() => document.querySelector('#description-textarea #textbox'), 'поле описания');
  await sleep(1500);  // поля дозаполняются после появления
  if (p.title && title.innerText.trim() !== p.title) { setText(title, p.title); changed = true; }
  if (p.reps && p.reps.length) {
    let d = desc.innerText;
    // все вхождения; если «было» — часть «стало» (['Сум','Сумы']) и «стало» уже есть — не трогать (иначе «Сумыы»)
    // «было» внутри «стало» (['Сум','Сумы']): готовые «стало» прячем под метку, чтобы не получить «Сумыы»
    const M = '\u0000';
    for (const [a, b] of p.reps) {
      const rest = b.includes(a) ? d.split(b).join(M) : d;
      if (rest.includes(a)) d = rest.split(a).join(b).split(M).join(b);
      else if (!d.includes(b)) res.miss.push(a);  // ни «было», ни «стало» — фраза не найдена
    }
    if (d !== desc.innerText) { setText(desc, d); changed = true; }
  }
  const relNow = () => (document.body.innerText.match(/Видео по теме\n([^\n]*)/) || [])[1];
  if (p.rel && relNow() !== p.rel) {
    // поле «Видео по теме» — выпадающий список (карандаш справа), клик открывает окно выбора
    const trig = [...document.querySelectorAll('ytcp-dropdown-trigger')].find(e => e.offsetParent && (e.innerText || '').trim().startsWith('Видео по теме'));
    if (!trig) throw new Error('не нашёл поле «Видео по теме»');
    trig.click(); changed = true;
    const dlg = await waitFor(() => [...document.querySelectorAll('ytcp-dialog')].find(x => (x.innerText || '').includes('Выберите видео') && x.querySelector('ytcp-entity-card')), 'окно выбора видео');
    const inp = dlg.querySelector('input');
    inp.focus(); inp.value = p.rel.split(' — ')[0];
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
    (await waitFor(() => [...dlg.querySelectorAll('ytcp-entity-card')].find(c => (c.getAttribute('aria-label') || '').startsWith(p.rel + ', ')), 'карточка ' + p.rel)).click();
    await waitFor(() => relNow() === p.rel, 'связанное видео в поле');
  }
  // переключатели по имени (radios: ['VIDEO_HAS_ALTERED_CONTENT_NO', 'VIDEO_PAID_PRODUCT_PLACEMENT_NO']);
  // часть из них в свёрнутом блоке «Развернуть»
  if (p.radios && p.radios.length) {
    const rb = n => document.querySelector(`tp-yt-paper-radio-button[name="${n}"]`);
    if (p.radios.some(n => !rb(n) || !rb(n).offsetParent)) {
      const tg = [...document.querySelectorAll('#toggle-button')].find(b => b.offsetParent && /^\s*(Развернуть|Показать (больше|дополнительные))/.test(b.innerText));
      if (tg) { tg.click(); await sleep(1500); }
    }
    res.radios = {};
    for (const n of p.radios) {
      const r = await waitFor(() => rb(n), 'переключатель ' + n);
      if (r.getAttribute('aria-checked') !== 'true') { r.scrollIntoView({ block: 'center' }); r.click(); changed = true; await sleep(400); }
      res.radios[n] = r.getAttribute('aria-checked');
    }
  }
  await sleep(800);
  const save = [...document.querySelectorAll('ytcp-button')].find(b => b.innerText.trim() === 'Сохранить' && b.offsetParent);
  if (save && save.getAttribute('aria-disabled') !== 'true') {
    // ждать ответа сервера на сохранение: кнопка гаснет сразу при клике, а запрос ещё идёт — уйти со страницы
    // в этот момент = изменения теряются (так потерялись «ИИ/реклама» у 30 шортсов)
    // запрос сохранения — youtubei/v1/video_manager/metadata_update (XHR); в ответе по каждому полю resultCode
    const sent = new Promise(res => {
      const XO = XMLHttpRequest.prototype.open, XS = XMLHttpRequest.prototype.send;
      // вернуть исходные open/send — и по ответу, и по тайм-ауту (иначе обёртки копятся при следующем ytFix)
      let done = false;
      const restore = () => { if (done) return; done = true; XMLHttpRequest.prototype.open = XO; XMLHttpRequest.prototype.send = XS; };
      XMLHttpRequest.prototype.open = function (m, u) { this._u = String(u); return XO.apply(this, arguments); };
      XMLHttpRequest.prototype.send = function () {
        // loadend — и при сетевой ошибке (status 0), чтобы не ждать тайм-аут
        if ((this._u || '').includes('metadata_update')) this.addEventListener('loadend', () => {
          restore();
          let bad = []; try { const j = JSON.parse(this.responseText); bad = JSON.stringify(j).match(/"resultCode":"(?!UPDATE_SUCCESS)[A-Z_]+"/g) || []; } catch (e) { bad = ['не JSON']; }
          res(this.status === 200 && !bad.length ? 200 : this.status + ' ' + bad.join(','));
        });
        return XS.apply(this, arguments);
      };
      // тайм-аут — обычным таймером: долгий /sleep занял бы соединение с приёмником (у Chrome их 6 на хост)
      setTimeout(() => { if (!done) { restore(); res('timeout'); } }, 20000);
    });
    save.click();
    res.saveStatus = await sent;
    await waitFor(() => save.getAttribute('aria-disabled') === 'true', 'сохранение').catch(() => { res.saveBtn = 'не погасла'; });
    await sleep(1500);
  }
  Object.assign(res, { title: title.innerText.trim(), rel: relNow(), desc: desc.innerText.slice(0, 60) });
  res.ok = (!p.rel || res.rel === p.rel) && (!p.title || res.title === p.title) && !res.miss.length
    && Object.values(res.radios || {}).every(v => v === 'true')
    && (p.reps || []).every(([a, b]) => !(b.includes(a) ? desc.innerText.split(b).join('') : desc.innerText).includes(a))
    && (changed ? res.saveStatus === 200 : res.saveStatus === undefined || res.saveStatus === 200);
  return res;
};
