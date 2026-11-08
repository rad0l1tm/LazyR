(() => {
  window.readerInstallPlayer = data => {
    document.getElementById('reader-player-host')?.remove();
    const host = document.createElement('div');
    host.id = 'reader-player-host'; host.dataset.readerUi = '1';
    document.documentElement.append(host);
    const root = host.attachShadow({mode:'open'});
    root.innerHTML = `<style>${data.css}\n:host{all:initial} .player{height:105px;z-index:2147483647} .panel{position:fixed;inset:8vh 10vw 130px;background:#f5f5f1;color:#26352f;overflow:auto;padding:24px;border:1px solid #dfe6d8;border-radius:14px;z-index:2147483647;font:15px system-ui} .panel button{display:block;text-align:left;line-height:1.8;padding:12px;width:100%} .panel .close{width:auto;margin-left:auto} @media(max-width:800px){.player{height:129px}.panel{inset:5vh 12px 145px}}</style>${data.html}<div class="panel" hidden><button class="close">Закрыть ×</button><h2></h2><div class="text"></div></div>`;
    const $ = id => root.getElementById(id);
    const send = (action, value) => window.pageReaderCommand(data.id, action, value).catch(error => { $('player-subtitle').textContent = error.message || 'Не удалось выполнить действие'; });
    const playButton=$('play');
    for(const [key,value] of Object.entries({background:'#284e3c',color:'#ffffff',opacity:'1',visibility:'visible',border:'1px solid #284e3c',display:'grid'})) playButton.style.setProperty(key,value,'important');
    const options=root.querySelector('.player-options');
    const choose=document.createElement('button');choose.textContent='▣ Область';choose.title='Выделить прямоугольную область чтения';
    const extend=document.createElement('button');extend.textContent='↓ До конца';extend.disabled=!data.region;
    options.prepend(choose,extend);
    let selection=data.region;
    const outline=document.createElement('div');outline.style.cssText='position:fixed;border:2px solid #91b568;background:#91b56818;pointer-events:none;z-index:2147483645;box-sizing:border-box';outline.hidden=!selection;root.append(outline);
    function draw(){if(!selection)return;Object.assign(outline.style,{left:(selection.left-scrollX)+'px',top:(selection.top-scrollY)+'px',width:(selection.right-selection.left)+'px',height:(selection.bottom-selection.top)+'px'});}
    draw();
    extend.onclick=()=>{if(selection)send('region',{...selection,bottom:Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)});};
    choose.onclick=()=>{
      send('stop');
      const layer=document.createElement('div');layer.style.cssText='position:fixed;inset:0;background:#10291b18;z-index:2147483647;cursor:crosshair;touch-action:none';root.append(layer);
      $('player-subtitle').textContent='Протяните прямоугольник. Esc — отмена.';
      let start=null;
      const cleanup=()=>{layer.remove();document.removeEventListener('keydown',cancel,true);};
      const cancel=e=>{if(e.key==='Escape'){cleanup();outline.hidden=!selection;draw();}};
      document.addEventListener('keydown',cancel,true);
      layer.onpointerdown=e=>{e.preventDefault();start={x:e.clientX+scrollX,y:e.clientY+scrollY};layer.setPointerCapture(e.pointerId);};
      layer.onpointermove=e=>{if(!start)return;selection={left:Math.min(start.x,e.clientX+scrollX),top:Math.min(start.y,e.clientY+scrollY),right:Math.max(start.x,e.clientX+scrollX),bottom:Math.max(start.y,e.clientY+scrollY)};outline.hidden=false;draw();};
      layer.onpointerup=e=>{if(!start)return;cleanup();if(selection&&selection.right-selection.left>8&&selection.bottom-selection.top>8){extend.disabled=false;send('region',selection);}else{selection=data.region;outline.hidden=!selection;draw();}};
    };
    $('player-title').textContent = data.article.title;
    $('player-subtitle').textContent = 'Подключение к плееру…';
    $('play').onclick = () => { $('player-subtitle').textContent='Переключаем воспроизведение…'; send('toggle'); };
    $('previous').onclick = () => send('previous');
    $('next').onclick = () => send('next');
    $('seek').onchange = () => send('seek', Number($('seek').value));
    $('speed').onchange = () => send('speed', $('speed').value);
    const panel = root.querySelector('.panel');
    panel.querySelector('h2').textContent = data.article.title;
    data.article.units.forEach((unit, i) => {
      const b = document.createElement('button');
      b.textContent = unit.kind === 'text' ? unit.text : '◫ Визуальный материал · адаптивная пауза';
      b.onclick = () => send('jump', i);
      panel.querySelector('.text').append(b);
    });
    $('text-toggle').onclick = () => { panel.hidden = !panel.hidden; $('text-toggle').setAttribute('aria-expanded', String(!panel.hidden)); };
    panel.querySelector('.close').onclick = () => { panel.hidden = true; };
    const key = event => {
      if (['INPUT','TEXTAREA','SELECT','BUTTON'].includes(event.composedPath()[0]?.tagName) || event.target.isContentEditable) return;
      if (['ArrowLeft','ArrowRight'].includes(event.code)) {event.preventDefault();send(event.code==='ArrowLeft'?'previous':'next');return;}
      if (event.code === 'Space') { event.preventDefault(); send('toggle'); }
    };
    document.addEventListener('keydown', key, true);
    const timer = setInterval(async () => {
      if (!host.isConnected) { clearInterval(timer); document.removeEventListener('keydown', key, true); return; }
      try {
        const s = await window.pageReaderState(data.id);
        draw(); choose.disabled=!!s.playing||!!s.loading; extend.disabled=!selection||!!s.playing||!!s.loading;
        $('play').textContent = s.loading ? '…' : s.playing ? 'Ⅱ' : '▶';
        $('play').setAttribute('aria-label', s.playing ? 'Пауза' : 'Воспроизвести');
        $('player-subtitle').textContent = s.inactive ? 'Нажмите ▶, чтобы слушать эту статью' : s.subtitle || 'Подключение к приложению…';
        $('elapsed').textContent = s.elapsed || '0:00'; $('duration').textContent = s.duration || '0:00';
        if (root.activeElement !== $('seek')) $('seek').value = s.seek || 0;
        if (root.activeElement !== $('speed')) $('speed').value = String(s.speed || 1);
      } catch (_) { $('player-subtitle').textContent = 'Приложение недоступно'; }
    }, 400);
  };
})();
