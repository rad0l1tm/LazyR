(() => {
  if (window.readerScan) return;
  let generation = 0;
  let activeUnit = null;
  const SKIP = 'script,style,noscript,nav,aside,header,footer,form,button,input,select,textarea,[hidden],[aria-hidden="true"],[role="navigation"],[role="menu"],[data-reader-ui]';
  const MATH = 'math,.katex,.MathJax,.mjx-container,[data-mathml],[role="math"]';
  const VISUAL = 'img,svg,canvas,video,iframe,object,embed,pre,code';
  const BLOCK = new Set(['P','DIV','SECTION','ARTICLE','H1','H2','H3','H4','H5','H6','LI','BLOCKQUOTE','TR','FIGCAPTION','DT','DD','UL','OL','TABLE','BR']);
  const visible = el => {
    if (!el || el.closest(SKIP)) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  let units = [];
  let parts = [], first = null, last = null, anchor = null;
  const flush = () => {
    const text = parts.join(' ').replace(/\s+/g, ' ').trim();
    if (text && first && last) {
      const range = document.createRange();
      range.setStart(first, 0);
      range.setEnd(last, last.textContent.length);
      units.push({ kind: 'text', text, range, anchor });
    }
    parts = []; first = last = anchor = null;
  };
  const addVisual = (el, kind) => {
    flush();
    units.push({ kind, text: '', anchor: el });
  };
  const walk = node => {
    if (node.nodeType === Node.TEXT_NODE) {
      const parent = node.parentElement;
      if (!visible(parent) || parent.closest('sup,[role="doc-noteref"]')) return;
      const value = node.textContent.replace(/\s+/g, ' ').trim();
      if (!value || /^\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]$/.test(value)) return;
      if (parent.closest('a') && /^\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]$/.test(parent.closest('a').textContent.trim())) return;
      if (!first) { first = node; anchor = parent; }
      last = node; parts.push(value);
      if (parts.join(' ').length > 450) flush();
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const el = node;
    if (!visible(el)) return;
    if (el.matches('table,[role="table"],[role="grid"]')) { addVisual(el, 'table'); return; }
    if (el.matches(MATH) || el.matches('pre,code')) { addVisual(el, 'formula/code'); return; }
    if (el.matches(VISUAL)) { addVisual(el, 'image/visual'); return; }
    const block = BLOCK.has(el.tagName);
    if (block) flush();
    for (const child of el.childNodes) walk(child);
    if (block) flush();
  };
  window.readerScan = (region = null) => {
    generation++;
    activeUnit = null;
    box.style.display = 'none';
    if (!box.isConnected) document.documentElement.append(box);
    if (!badge.isConnected) document.documentElement.append(badge);
    window.readerCommands = [];
    units = []; parts = []; first = last = anchor = null;
    const root = document.querySelector('article,main,[role="main"]') || document.body;
    walk(root); flush();
    return units.map((u, i) => {
      const rects = u.range ? Array.from(u.range.getClientRects()) : [u.anchor.getBoundingClientRect()];
      const r = rects.length ? {left:Math.min(...rects.map(r=>r.left))+scrollX, right:Math.max(...rects.map(r=>r.right))+scrollX, top:Math.min(...rects.map(r=>r.top))+scrollY, bottom:Math.max(...rects.map(r=>r.bottom))+scrollY} : null;
      return {index:i, kind:u.kind, text:u.text, bounds:r, areaRatio:r ? (r.right-r.left)*(r.bottom-r.top)/Math.max(1,innerWidth*innerHeight) : 0};
    }).filter(u => !region || u.bounds && u.bounds.right>region.left && u.bounds.left<region.right && u.bounds.bottom>region.top && u.bounds.top<region.bottom);
  };
  const box = document.createElement('div');
  box.dataset.readerUi = '1';
  Object.assign(box.style, {
    position: 'fixed', zIndex: '2147483647', pointerEvents: 'none',
    border: '4px solid #f4b400', borderRadius: '6px',
    background: 'rgba(244,180,0,.17)', boxSizing: 'border-box', display: 'none'
  });
  document.documentElement.append(box);
  const badge = document.createElement('div');
  badge.dataset.readerUi = '1';
  badge.textContent = 'Page Reader · Управление воспроизведением — во вкладке приложения';
  Object.assign(badge.style, {
    position:'fixed', right:'12px', bottom:'12px', zIndex:'2147483647',
    background:'#202124', color:'white', padding:'9px 12px', borderRadius:'7px',
    font:'14px sans-serif', pointerEvents:'none'
  });
  document.documentElement.append(badge);
  badge.style.display = 'none';
  window.readerSetStatus = value => { badge.textContent = value; };
  window.readerCommands = [];
  window.readerPopCommands = () => window.readerCommands.splice(0);
  window.readerStop = () => { generation++; activeUnit = null; box.style.display = 'none'; };
  const rectsFor = u => u.range ? Array.from(u.range.getClientRects()) : [u.anchor.getBoundingClientRect()];
  const drawHighlight = () => {
    if (!activeUnit || !activeUnit.anchor.isConnected) {
      box.style.display = 'none';
      return;
    }
    const now = rectsFor(activeUnit);
    if (!now.length) { box.style.display = 'none'; return; }
    const left = Math.min(innerWidth, Math.max(0, Math.min(...now.map(r => r.left)) - 5));
    const right = Math.min(innerWidth, Math.max(...now.map(r => r.right)) + 5);
    const top = Math.min(innerHeight, Math.max(0, Math.min(...now.map(r => r.top)) - 5));
    const bottom = Math.min(innerHeight, Math.max(...now.map(r => r.bottom)) + 5);
    Object.assign(box.style, { left:`${left}px`, top:`${top}px`, width:`${Math.max(0,right-left)}px`, height:`${Math.max(0,bottom-top)}px`, display:'block' });
  };
  let redrawPending = false;
  const scheduleHighlight = () => {
    if (redrawPending) return;
    redrawPending = true;
    requestAnimationFrame(() => { redrawPending = false; drawHighlight(); });
  };
  window.addEventListener('resize', scheduleHighlight);
  window.addEventListener('scroll', scheduleHighlight, { passive: true });
  window.visualViewport?.addEventListener('resize', scheduleHighlight);
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  window.readerFocus = async (index, speed) => {
    const current = generation;
    const u = units[index];
    if (!u) return false;
    const rects = rectsFor(u);
    if (!rects.length) return false;
    const top = Math.min(...rects.map(r => r.top)) + scrollY;
    const bottom = Math.max(...rects.map(r => r.bottom)) + scrollY;
    const margin = Math.min(48, innerHeight * .1);
    const wanted = bottom - top > innerHeight - margin * 2
      ? top - margin : (top + bottom) / 2 - innerHeight / 2;
    const target = Math.max(0, Math.min(wanted, Math.max(0, document.documentElement.scrollHeight - innerHeight)));
    // Never leave the next frame outside the viewport while slowly catching up.
    if (top - scrollY < margin || bottom - scrollY > innerHeight - margin) {
      scrollTo({ top: target, left: scrollX, behavior: 'instant' });
    }
    activeUnit = u;
    drawHighlight();
    const start = scrollY, distance = target - start;
    const duration = Math.min(12000, Math.abs(distance) / Math.max(speed, 10) * 1000);
    const begin = performance.now();
    let interrupted = false;
    while (performance.now() - begin < duration && Math.abs(scrollY - target) > 2) {
      if (current !== generation) return false;
      if (window.readerCommands.length) {
        if (window.readerCommands.includes('next')) scrollTo({ top: target, left: scrollX, behavior: 'instant' });
        interrupted = true; break;
      }
      const t = Math.min(1, (performance.now() - begin) / duration);
      scrollTo({ top: start + distance * t, left: scrollX, behavior: 'instant' });
      await delay(20);
    }
    if (current !== generation) return false;
    if (!interrupted) scrollTo({ top: target, left: scrollX, behavior: 'instant' });
    drawHighlight();
    const now = rectsFor(u);
    if (!now.length) return false;
    // Measure the full region, before viewport clipping or border padding.
    const width = Math.max(0, Math.max(...now.map(r => r.right)) - Math.min(...now.map(r => r.left)));
    const height = Math.max(0, Math.max(...now.map(r => r.bottom)) - Math.min(...now.map(r => r.top)));
    return { areaRatio: width * height / Math.max(1, innerWidth * innerHeight) };
  };
})();
