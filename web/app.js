'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="reader-token"]').content;
let articles = [], current = null, filter = 'all', playing = false, loading = false;
let audio = null, objectURL = null, generation = 0, visualStart = 0, visualBase = 0;
let saveQueue = Promise.resolve(), pendingDelete = null, savedAt = 0;
let pauseMin = 1, pauseMax = 8;
try { const p = JSON.parse(localStorage.getItem('reader-pauses')); if(p){pauseMin=p.min;pauseMax=p.max;} } catch (_) {}
$('pause-min').value=pauseMin; $('pause-max').value=pauseMax;
for(const id of ['pause-min','pause-max']) $(id).onchange=()=>{
  pauseMin=Math.max(0,Math.min(120,Number($('pause-min').value)||0));
  pauseMax=Math.max(pauseMin,Math.min(120,Number($('pause-max').value)||0));
  $('pause-min').value=pauseMin;$('pause-max').value=pauseMax;
  try{localStorage.setItem('reader-pauses',JSON.stringify({min:pauseMin,max:pauseMax}));}catch(_){}
};
const rate = () => Number($('speed').value);
try { const speed = localStorage.getItem('reader-speed'); if ([...$('speed').options].some(o => o.value === speed)) $('speed').value = speed; } catch (_) {}
async function api(path, method = 'GET', body) {
  const response = await fetch('/api/' + path, {method, headers: {'X-Reader-Token': token, ...(body ? {'Content-Type': 'application/json'} : {})}, body: body ? JSON.stringify(body) : undefined});
  if (!response.ok) {
    let message = 'Не удалось связаться с приложением.';
    try { const data = await response.json(); message = data.error || message; } catch (_) {}
    throw new Error(message);
  }
  return response;
}
const json = async (...args) => (await api(...args)).json();
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = !message; }
function escapeHTML(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function seconds(unit) { return unit.kind === 'text' ? Math.max(1, unit.text.split(/\s+/).length / 2.6) : pauseMin+(pauseMax-pauseMin)*Math.sqrt(Math.min(1,Math.max(0,unit.areaRatio||0)/.5)); }
function total(a) { return a.units.reduce((s, u) => s + seconds(u), 0); }
function position(a) { return a.units.slice(0, a.cursor).reduce((s, u) => s + seconds(u), 0) + (a.units[a.cursor] ? seconds(a.units[a.cursor]) * a.fraction : 0); }
function percent(a) { return Math.min(100, Math.round(100 * position(a) / (total(a) || 1))); }
function time(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
function done(a) { return a.cursor >= a.units.length; }
function domain(a) { try { return a.url.startsWith('local://') ? 'Локальный файл' : new URL(a.url).hostname.replace(/^www\./, ''); } catch (_) { return a.url; } }
function syncPlayer() {
  const enabled = !!current;
  for (const id of ['play','previous','next','seek','text-toggle']) $(id).disabled = !enabled;
  $('play').textContent = loading ? '…' : playing ? 'Ⅱ' : '▶';
  $('play').setAttribute('aria-label', playing ? 'Пауза' : 'Воспроизвести');
  $('player-title').textContent = current ? current.title : 'Что послушаем сегодня?';
  $('player-subtitle').textContent = current ? (loading ? 'Подготавливаем локальный голос…' : playing ? (current?.units[current.cursor]?.kind !== 'text' ? 'Просмотр визуального блока · ' : 'Сейчас звучит · ') : done(current) ? 'Прослушано · ' : 'На паузе · ') + domain(current) : 'Добавьте статью, чтобы начать';
  $('elapsed').textContent = time(current ? position(current) / rate() : 0);
  $('duration').textContent = time(current ? total(current) / rate() : 0);
  if (document.activeElement !== $('seek')) $('seek').value = current ? Math.round(percentFloat(current) * 10) : 0;
  $('seek').title = 'Примерная позиция · ' + (current ? percent(current) : 0) + '%';
}
function percentFloat(a) { return Math.min(100, 100 * position(a) / (total(a) || 1)); }
function render() {
  $('nav-count').textContent = $('article-count').textContent = articles.length;
  const query = $('search').value.trim().toLowerCase();
  const visible = articles.filter(a => (filter === 'all' || (filter === 'done' ? done(a) : !done(a) && position(a) > 0)) && (a.title + ' ' + a.url).toLowerCase().includes(query));
  $('list-count').textContent = visible.length + ' из ' + articles.length;
  $('history').innerHTML = visible.map(a => `<article class="article ${current?.id === a.id ? 'is-current' : ''}" data-id="${a.id}"><div class="card-top"><div class="cover" aria-hidden="true">${escapeHTML(domain(a).charAt(0).toUpperCase())}</div><div class="card-actions"><button data-action="open" title="Открыть исходную страницу" aria-label="Открыть исходную страницу">↗</button><button data-action="delete" title="Удалить статью" aria-label="Удалить статью">×</button></div></div><div class="domain">${escapeHTML(domain(a))}</div><h3 title="${escapeHTML(a.title)}">${escapeHTML(a.title)}</h3><div class="card-meta"><span>≈ ${Math.max(1, Math.round(total(a) / 60))} мин · RU / EN</span><span>${new Date(a.updated).toLocaleDateString('ru', {day:'numeric', month:'short'})}</span></div><div class="progress-line"><div ></div></div><div class="card-bottom"><span data-progress>${done(a) ? '✓ Прослушано' : percent(a) > 0 ? percent(a) + '% прослушано' : 'Ещё не слушали'}</span><button data-action="play" class="card-play">${done(a) ? '↻ Ещё раз' : a.cursor || a.fraction ? '▶ Продолжить' : '▶ Слушать'}</button></div></article>`).join('');
  $('empty').hidden = visible.length > 0;
  $('empty').querySelector('h3').textContent = articles.length ? 'Здесь пока нет статей' : 'Ваша следующая история — по ссылке';
  $('empty').querySelector('p').textContent = articles.length ? 'Измените поисковый запрос или выберите другой фильтр.' : 'Добавьте первую статью выше. Она останется здесь вместе с вашим прогрессом.';
  for (const card of $('history').children) { const a = articles.find(item => item.id === card.dataset.id); if (a) card.querySelector('.progress-line div').style.width = percent(a) + '%'; }
  syncPlayer();
}
function refreshProgress() {
  if (!current) return;
  const card = [...$('history').children].find(el => el.dataset.id === current.id);
  if (card) { card.querySelector('.progress-line div').style.width = percent(current) + '%'; card.querySelector('[data-progress]').textContent = done(current) ? '✓ Прослушано' : percent(current) + '% прослушано'; }
  syncPlayer();
}
function capture() {
  if (!current || !playing) return;
  if (audio && Number.isFinite(audio.duration) && audio.duration > 0) current.fraction = Math.min(.999, audio.currentTime / audio.duration);
  else if (visualStart && current.units[current.cursor]) current.fraction = Math.min(.999, visualBase + (performance.now() - visualStart) / 1000 * rate() / seconds(current.units[current.cursor]));
}
function save() {
  if (!current) return saveQueue;
  const id = current.id, data = {cursor: current.cursor, fraction: current.fraction};
  current.updated = new Date().toISOString();
  saveQueue = saveQueue.catch(() => {}).then(() => json(`articles/${id}/progress`, 'POST', data)).catch(error => notice('Не удалось сохранить позицию: ' + error.message, true));
  return saveQueue;
}
function stop() {
  capture(); generation++; playing = false; loading = false; visualStart = 0;
  if (audio) { audio.onended=null; audio.onerror=null; audio.onloadedmetadata=null; audio.pause(); audio.removeAttribute('src'); audio.load(); audio = null; }
  if (objectURL) { URL.revokeObjectURL(objectURL); objectURL = null; }
  syncPlayer();
}
function renderText() {
  if (!current) return;
  $('reader-title').textContent = current.title;
  $('reader-content').innerHTML = current.units.map((u, i) => `<button class="text-unit ${i === current.cursor ? 'current' : ''} ${u.kind !== 'text' ? 'visual' : ''}" data-index="${i}">${u.kind === 'text' ? escapeHTML(u.text) : '◫ Визуальный материал · адаптивная пауза'}</button>`).join('');
}
function highlightText() {
  for (const el of $('reader-content').children) el.classList.toggle('current', Number(el.dataset.index) === current?.cursor);
}
async function playUnit() {
  if (!current) return;
  if (done(current)) { stop(); await save(); render(); return; }
  const gen = generation, article = current, i = article.cursor, unit = article.units[i];
  playing = true; loading = unit.kind === 'text'; syncPlayer(); highlightText();
  json(`articles/${article.id}/focus`, 'POST', {index: i}).catch(() => {});
  if (unit.kind !== 'text') { visualBase = article.fraction; visualStart = performance.now(); loading = false; syncPlayer(); return; }
  try {
    const response = await api(`articles/${article.id}/audio/${i}`);
    const blob = await response.blob();
    if (generation !== gen || current !== article) return;
    objectURL = URL.createObjectURL(blob);
    const player = new Audio(objectURL); audio = player;
    player.playbackRate = rate();
    player.onloadedmetadata = () => { if (generation === gen && Number.isFinite(player.duration)) player.currentTime = Math.min(player.duration - .01, Math.max(0, article.fraction * player.duration)); };
    player.onended = () => { if (generation === gen) advance(); };
    player.onerror = () => { if (generation === gen) { stop(); save(); notice('Не удалось воспроизвести звук. Повторите запуск фрагмента.', true); } };
    await player.play();
    if (generation !== gen) { player.pause(); return; }
    loading = false; syncPlayer();
  } catch (error) {
    if (generation !== gen) return;
    stop(); await save(); notice(error.name === 'NotAllowedError' ? 'Браузер ожидает нажатия: нажмите кнопку воспроизведения.' : error.message, true);
  }
}
async function advance() {
  if (!current) return;
  const article = current;
  stop(); article.cursor++; article.fraction = 0;
  save(); refreshProgress(); highlightText();
  if (done(article)) { notice('Статья прослушана. Хорошая история остаётся с вами.'); render(); return; }
  playUnit();
}
async function selectArticle(article, autoplay = true) {
  stop(); const selection = generation; await save(); if (generation !== selection) return; current = article;
  if (done(article) && autoplay) { article.cursor = 0; article.fraction = 0; }
  try { localStorage.setItem('reader-current', article.id); } catch (_) {}
  notice(''); render(); renderText(); if (autoplay) playUnit();
}
async function jump(index, fraction = 0, resume = playing) {
  if (!current) return;
  stop(); current.cursor = Math.max(0, Math.min(current.units.length, index)); current.fraction = fraction;
  save(); refreshProgress(); highlightText(); if (resume) playUnit();
}
$('url-form').addEventListener('submit', async event => {
  event.preventDefault();
  const url = $('url-input').value.trim(); if (!url) return;
  $('add-button').disabled = true; $('add-button').textContent = 'Открываем статью…';
  notice('Статья открывается в отдельной вкладке. Загружаем доступный текст…');
  try {
    stop(); await save();
    const article = await json('articles', 'POST', {url});
    articles = articles.filter(a => a.id !== article.id); articles.unshift(article);
    $('url-input').value = ''; await selectArticle(article, false);
  } catch (error) { notice(error.message, true); }
  finally { $('add-button').disabled = false; $('add-button').innerHTML = '<span>＋</span> Добавить и слушать'; }
});
$('history').addEventListener('click', async event => {
  const button = event.target.closest('[data-action]'), card = event.target.closest('[data-id]'); if (!button || !card) return;
  const article = articles.find(a => a.id === card.dataset.id); if (!article) return;
  if (button.dataset.action === 'play') { stop(); await save(); const updated = await json(`articles/${article.id}/open`, 'POST', {}); articles = articles.map(a => a.id === updated.id ? updated : a); selectArticle(updated); }
  if (button.dataset.action === 'open') { try { await json(`articles/${article.id}/open`, 'POST', {}); } catch (e) { notice(e.message, true); } }
  if (button.dataset.action === 'delete') { pendingDelete = article; $('delete-dialog').showModal(); }
});
$('cancel-delete').onclick = () => $('delete-dialog').close();
$('confirm-delete').onclick = async () => {
  const article = pendingDelete; if (!article) return;
  $('confirm-delete').disabled = true;
  try {
    if (current?.id === article.id) { stop(); await save(); current = null; }
    await json(`articles/${article.id}`, 'DELETE'); articles = articles.filter(a => a.id !== article.id);
    $('delete-dialog').close(); render();
  } catch (e) { notice(e.message, true); } finally { $('confirm-delete').disabled = false; }
};
$('play').onclick = async () => { if (!current) return; if (playing) { stop(); save(); } else { if (done(current)) { current.cursor = 0; current.fraction = 0; } playUnit(); } };
$('stop-reading').onclick=async()=>{stop(); await save(); notice('Озвучивание остановлено. Позиция сохранена.');};
async function showModels() {
  const data=await json('models');
  for(const lang of ['ru','en']) {
    $('voice-'+lang).innerHTML=data.catalog[lang].map(v=>`<option value="${v.name}">${v.name}${v.installed ? ' · установлен' : ' · скачать'}</option>`).join('');
    $('voice-'+lang).value=data.selected[lang];
  }
  return data;
}
for(const lang of ['ru','en']) $('voice-'+lang).onchange=async()=>{
  const name=$('voice-'+lang).value;
  stop(); await save();
  $('voice-ru').disabled=$('voice-en').disabled=true;
  $('voice-status').textContent='Проверяем голос; при необходимости скачиваем модель…';
  try { await json('models','POST',{lang,name}); $('voice-status').textContent='Голос готов. Продолжите воспроизведение.'; }
  catch(e){$('voice-status').textContent='Не удалось применить голос: '+e.message;}
  finally{try{await showModels();}catch(_){} $('voice-ru').disabled=$('voice-en').disabled=false;}
};
showModels().then(()=>{$('voice-status').textContent='Модель скачивается автоматически при выборе. Нужен интернет только для загрузки.';}).catch(e=>{$('voice-status').textContent=e.message;});
$('previous').onclick = () => jump(current.cursor - 1, 0, true);
$('next').onclick = () => jump(current.cursor + 1, 0, true);
$('seek').addEventListener('change', () => {
  if (!current) return;
  let target = total(current) * Number($('seek').value) / 1000, index = 0;
  while (index < current.units.length && target >= seconds(current.units[index])) target -= seconds(current.units[index++]);
  jump(index, index < current.units.length ? Math.min(.999, target / seconds(current.units[index])) : 0);
});
$('speed').onchange = () => {
  // The visual timer must account for elapsed time at the previous rate.
  if (playing && visualStart) { current.fraction = Math.min(.999, visualBase + (performance.now() - visualStart) / 1000 * Number($('speed').dataset.previous || 1) / seconds(current.units[current.cursor])); visualBase = current.fraction; visualStart = performance.now(); }
  if (audio) audio.playbackRate = rate();
  $('speed').dataset.previous = rate();
  try { localStorage.setItem('reader-speed', rate()); } catch (_) {} syncPlayer();
};
$('speed').dataset.previous = rate();
$('text-toggle').onclick = () => { if (!current) return; renderText(); $('reader-panel').showModal(); $('text-toggle').setAttribute('aria-expanded', 'true'); setTimeout(() => $('reader-content').querySelector('.current')?.scrollIntoView({block:'center'}), 10); };
$('close-text').onclick = () => $('reader-panel').close();
$('reader-panel').addEventListener('close', () => $('text-toggle').setAttribute('aria-expanded', 'false'));
$('reader-content').onclick = event => { const el = event.target.closest('[data-index]'); if (el) jump(Number(el.dataset.index), 0, true); };
$('search').oninput = render;
for (const button of document.querySelectorAll('[data-filter]')) button.onclick = () => { filter = button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(b => b.classList.toggle('selected', b === button)); render(); };
$('library-nav').onclick = () => { $('search').value = ''; filter = 'all'; document.querySelector('[data-filter="all"]').click(); document.querySelector('.library').scrollIntoView({behavior:'smooth'}); };
document.addEventListener('keydown', event => { if (['ArrowLeft','ArrowRight'].includes(event.code) && !['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName) && !document.querySelector('dialog[open]')) { event.preventDefault();$(event.code==='ArrowLeft'?'previous':'next').click();return; } if (event.code === 'Space' && !['INPUT','SELECT','TEXTAREA','BUTTON'].includes(event.target.tagName) && !document.querySelector('dialog[open]')) { event.preventDefault(); $('play').click(); } });
setInterval(() => {
  capture(); refreshProgress();
  if (playing && visualStart && performance.now() - visualStart >= (1 - visualBase) * seconds(current.units[current.cursor]) / rate() * 1000) advance();
  if (playing && Date.now() - savedAt > 3000) { savedAt = Date.now(); save(); }
}, 250);
let pollingCommands = false;
setInterval(async () => {
  if (pollingCommands) return;
  pollingCommands = true;
  try {
    capture();
    await json('playback', 'POST', {id:current?.id, playing, loading, title:current?.title,
      subtitle:$('player-subtitle').textContent, elapsed:$('elapsed').textContent,
      duration:$('duration').textContent, seek:$('seek').value, speed:rate()});
    for (const command of await json('commands')) {
      if (command.action === 'stop') { stop(); await save(); continue; }
      if (command.action === 'select') {
        const article = command.article;
        articles = articles.filter(a => a.id !== article.id); articles.unshift(article);
        await selectArticle(article, command.autoplay !== false); await save(); continue;
      }
      if (command.id && command.id !== current?.id) {
        const article = articles.find(a => a.id === command.id);
        if (!article) continue;
        await selectArticle(article, false);
      }
      if (command.action === 'toggle') $('play').click();
      if (command.action === 'next') $('next').click();
      if (command.action === 'previous') $('previous').click();
      if (command.action === 'seek') { $('seek').value = command.value; $('seek').dispatchEvent(new Event('change')); }
      if (command.action === 'speed') { $('speed').value = command.value; $('speed').dispatchEvent(new Event('change')); }
      if (command.action === 'jump') jump(Number(command.value), 0, true);
    }
  } catch (_) {} finally { pollingCommands = false; }
}, 300);
function flushOnExit() {
  capture(); if (!current) return;
  fetch(`/api/articles/${current.id}/progress`, {method:'POST', headers:{'X-Reader-Token':token,'Content-Type':'application/json'}, body:JSON.stringify({cursor:current.cursor,fraction:current.fraction}), keepalive:true}).catch(() => {});
}
window.addEventListener('pagehide', flushOnExit);
document.addEventListener('visibilitychange', () => { if (document.hidden) { capture(); save(); } });
(async () => {
  try {
    articles = await json('articles');
    let last; try { last = localStorage.getItem('reader-current'); } catch (_) {}
    current = articles.find(a => a.id === last) || articles[0] || null;
    render(); renderText();
    const status = await json('status');
    if (!status.models.ru || !status.models.en) notice('Для локальной озвучки нужны голосовые модели. Выполните python setup.py по инструкции README.', true);
  } catch (error) { render(); notice(error.message, true); }
})();

$('file-form').addEventListener('submit', async event => {
  event.preventDefault();
  const file=$('local-file').files[0]; if(!file)return;
  if(file.size>64*1024*1024){notice('Максимальный размер файла — 64 МБ.',true);return;}
  $('import-file').disabled=true; notice('Извлекаем текст и открываем документ…');
  try {
    stop(); await save();
    const form=new FormData();form.append('file',file);
    const response=await fetch('/api/import',{method:'POST',headers:{'X-Reader-Token':token},body:form});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'Не удалось прочитать файл.');
    articles=articles.filter(a=>a.id!==data.id);articles.unshift(data);
    await selectArticle(data,false);$('local-file').value='';
  } catch(error){notice(error.message,true);}finally{$('import-file').disabled=false;}
});
