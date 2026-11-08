#!/usr/bin/env python3
"""Local Page Reader. Python 3.10+, loopback HTTP, managed Chromium tabs."""
import argparse
import asyncio
import io
import json
import logging
import os
import secrets
import sys
import wave
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from core import Store, normalize_url, prepare_units
from models import VoiceModels
from documents import import_document, MAX_BYTES

ROOT = Path(__file__).resolve().parent
STATE = web.AppKey('state', object)


class Runtime:
    def __init__(self, data_dir, model_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir, self.model_dir = data_dir, model_dir
        self.store = Store(data_dir / 'history.sqlite3')
        self.token = secrets.token_urlsafe(32)
        self.context = self.playwright = None
        self.pages = {}
        self.speech_lock = asyncio.Lock()
        self.load_lock = asyncio.Lock()
        self.cache = OrderedDict()
        self.commands = []
        self.playback = {}
        self.watchers = set()
        self.document_base = 'http://127.0.0.1:8765'
        
        self.models = VoiceModels(data_dir, model_dir)

    async def install(self, page, url, region=None):
        # The document identity does not depend on the HTTP port used at launch.
        parsed = urlsplit(url)
        import re
        if parsed.hostname in ('127.0.0.1', 'localhost') and re.fullmatch(r'/documents/[0-9a-f]{64}', parsed.path):
            url = 'local://' + parsed.path.rsplit('/', 1)[1]
        if region is None:
            row = self.store.db.execute('SELECT region FROM articles WHERE url=?', (url,)).fetchone()
            region = json.loads(row['region'] or 'null') if row else None
        await page.evaluate((ROOT / 'scanner.js').read_text('utf-8'))
        units = prepare_units(await page.evaluate('region => readerScan(region)', region))
        article = self.store.put(url, await page.title() or url, units)
        self.store.db.execute('UPDATE articles SET region=? WHERE id=?', (json.dumps(region), article['id']))
        self.store.db.commit()
        article['region'] = region
        for key, value in list(self.pages.items()):
            if value == page:
                del self.pages[key]
        previous = self.pages.get(article['id'])
        self.pages[article['id']] = page
        if previous and previous != page and not previous.is_closed():
            await previous.close()
        html = (ROOT / 'web/index.html').read_text('utf-8')
        import re
        player = re.search(r'<section class="player".*?</section>', html, re.S).group().replace(' hidden', '')
        await page.evaluate((ROOT / 'overlay.js').read_text('utf-8'))
        await page.evaluate('data => window.readerInstallPlayer(data)', {
            'id': article['id'], 'article': article, 'html': player, 'region': region,
            'css': (ROOT / 'web/style.css').read_text('utf-8')})
        return article

    async def watch(self, page):
        last_url = page.url
        while not page.is_closed():
            await asyncio.sleep(.5)
            try:
                url = normalize_url(page.url)
                ready = await page.evaluate('!!document.getElementById("reader-player-host")')
                if url == last_url and ready:
                    continue
                self.commands.append({'action': 'stop'})
                await page.wait_for_load_state('domcontentloaded')
                await asyncio.sleep(1.8)
                if normalize_url(page.url) != url:
                    continue
                article = await self.install(page, url)
                last_url = url
                self.commands.append({'action': 'select', 'article': article})
            except Exception:
                # Navigation may destroy the execution context. Retry once settled.
                await asyncio.sleep(1)

    async def load(self, url):
        async with self.load_lock:
            page = await self.context.new_page()
            target = self.document_base + '/documents/' + url[8:] if url.startswith('local://') else url
            await page.goto(target, wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(1800)
            article = await self.install(page, url)
            task = asyncio.create_task(self.watch(page))
            self.watchers.add(task)
            task.add_done_callback(self.watchers.discard)
            return article

    def synthesize(self, text, lang):
        """Generate mono PCM WAV using the selected Silero speaker."""
        import numpy as np
        import torch

        if lang not in self.models.selected:
            raise ValueError(f'Неподдерживаемый язык: {lang}')

        name = self.models.selected[lang]
        model = asyncio.run(self.models.get_model(lang))
        sample_rate = 48000 #self.models.sample_rate(lang)

        with torch.inference_mode():
            result = model.apply_tts(
                text=text,
                speaker=name,
                sample_rate=sample_rate,
            )

        if isinstance(result, torch.Tensor):
            samples = result.detach().cpu().squeeze().numpy()
        else:
            samples = np.asarray(result).squeeze()

        if samples.size == 0:
            samples = np.zeros(int(sample_rate * 0.1), dtype=np.float32)

        # Silero returns floating-point audio in approximately [-1, 1].
        pcm = (
            np.clip(samples, -1.0, 1.0) * 32767
        ).astype('<i2', copy=False)

        audio = io.BytesIO()
        with wave.open(audio, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())

        return audio.getvalue()

    async def audio(self, article, index):
        unit = article['units'][index]
        if unit['kind'] != 'text':
            raise ValueError('Этот блок содержит визуальный материал.')
        key = (unit['lang'], self.models.selected[unit['lang']], unit['text'])
        async with self.speech_lock:
            if key not in self.cache:
                task = asyncio.create_task(asyncio.to_thread(self.synthesize, unit['text'], unit['lang']))
                try:
                    self.cache[key] = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                while len(self.cache) > 8:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            return self.cache[key]


@web.middleware
async def guard(request, handler):
    state = request.app[STATE]
    host = request.host.split(':')[0]
    if host not in ('127.0.0.1', 'localhost'):
        raise web.HTTPForbidden(text='Только локальный доступ')
    if request.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('X-Reader-Token', ''), state.token):
        raise web.HTTPForbidden(text='Недействительная сессия приложения')
    try:
        return await handler(request)
    except KeyError:
        return web.json_response({'error': 'Статья не найдена.'}, status=404)
    except (ValueError, TypeError, IndexError) as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except web.HTTPException:
        raise
    except Exception as exc:
        logging.exception('Reader operation failed')
        return web.json_response({'error': 'Не удалось выполнить действие. ' + str(exc)[:350]}, status=500)


async def index(request):
    text = (ROOT / 'web/index.html').read_text('utf-8').replace('__TOKEN__', request.app[STATE].token)
    return web.Response(text=text, content_type='text/html', headers={
        'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"})


async def articles(request):
    s = request.app[STATE]
    if request.method == 'GET':
        return web.json_response(s.store.list())
    data = await request.json()
    return web.json_response(await s.load(normalize_url(data.get('url', ''))))


async def progress(request):
    s, id = request.app[STATE], request.match_info['id']
    data = await request.json()
    return web.json_response(s.store.progress(id, data['cursor'], data.get('fraction', 0)))


async def audio(request):
    s = request.app[STATE]
    article = s.store.get(request.match_info['id'])
    i = int(request.match_info['index'])
    if i < 0 or i >= len(article['units']):
        raise ValueError('Некорректный номер блока')
    return web.Response(body=await s.audio(article, i), content_type='audio/wav', headers={'Cache-Control': 'no-store'})


async def focus(request):
    s, id = request.app[STATE], request.match_info['id']
    article = s.store.get(id)
    data = await request.json()
    i = int(data.get('index', 0))
    if not 0 <= i < len(article['units']):
        return web.json_response({'ok': False})
    page = s.pages.get(id)
    if page and not page.is_closed():
        try:
            await page.evaluate('i => readerFocus(i, 1000)', article['units'][i]['source'])
        except Exception:
            return web.json_response({'ok': False})
    return web.json_response({'ok': True})


async def open_source(request):
    s = request.app[STATE]
    s.document_base = 'http://' + request.host
    article = s.store.get(request.match_info['id'])
    page = s.pages.get(article['id'])
    if page is None or page.is_closed():
        await s.load(article['url'])
        page = s.pages[article['id']]
    await page.bring_to_front()
    return web.json_response(s.store.get(article['id']))


async def delete(request):
    s, id = request.app[STATE], request.match_info['id']
    s.store.delete(id)
    page = s.pages.pop(id, None)
    if page and not page.is_closed():
        await page.close()
    return web.json_response({'ok': True})


async def status(request):
    s = request.app[STATE]
    info = s.models.describe()
    return web.json_response({'models': {lang: any(item['installed'] for item in voices) for lang, voices in info['catalog'].items()}})


async def upload_document(request):
    state = request.app[STATE]
    reader = await request.multipart()
    part = await reader.next()
    if part is None or part.name != 'file' or not part.filename:
        raise ValueError('Выберите локальный файл.')
    content = bytearray()
    while True:
        chunk = await part.read_chunk()
        if not chunk:
            break
        if len(content) + len(chunk) > MAX_BYTES:
            raise ValueError('Максимальный размер файла — 64 МБ.')
        content.extend(chunk)
    digest = await asyncio.to_thread(import_document, state.data_dir / 'documents', part.filename, bytes(content))
    state.document_base = 'http://' + request.host
    article = await state.load('local://' + digest)
    return web.json_response(article)


async def document_view(request):
    state = request.app[STATE]
    digest = request.match_info['digest']
    source = request.path.endswith('/source')
    path = state.data_dir / 'documents' / (digest + ('.source' if source else '.html'))
    if not path.is_file():
        raise web.HTTPNotFound(text='Локальный файл не найден. Добавьте его заново.')
    headers = {'Cache-Control': 'no-store', 'X-Frame-Options':'DENY'}
    if source:
        headers['Content-Disposition'] = 'attachment'
    else:
        headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    return web.Response(body=path.read_bytes(), content_type='application/octet-stream' if source else 'text/html', headers=headers)


async def voice_models(request):
    s = request.app[STATE]
    if request.method == 'GET':
        return web.json_response(s.models.describe())
    data = await request.json()
    async with s.speech_lock:
        await s.models.select(data['lang'], data['name'])
        s.cache.clear()
    return web.json_response(s.models.describe())


async def playback(request):
    request.app[STATE].playback = await request.json()
    return web.json_response({'ok': True})


async def commands(request):
    s = request.app[STATE]
    pending, s.commands = s.commands, []
    return web.json_response(pending)


async def asset(request):
    return web.FileResponse(ROOT / 'web' / request.match_info['name'])


def make_app(state):
    app = web.Application(middlewares=[guard], client_max_size=MAX_BYTES + 65536)
    app[STATE] = state
    app.router.add_get('/', index)
    app.router.add_get(r'/{name:style\.css|app\.js}', asset)
    app.router.add_get('/api/status', status)
    app.router.add_get('/api/models', voice_models)
    app.router.add_post('/api/models', voice_models)
    app.router.add_get('/api/commands', commands)
    app.router.add_post('/api/playback', playback)
    app.router.add_get('/api/articles', articles)
    app.router.add_post('/api/articles', articles)
    app.router.add_post('/api/import', upload_document)
    app.router.add_get(r'/documents/{digest:[0-9a-f]{64}}', document_view)
    app.router.add_get(r'/documents/{digest:[0-9a-f]{64}}/source', document_view)
    app.router.add_post('/api/articles/{id}/progress', progress)
    app.router.add_post('/api/articles/{id}/focus', focus)
    app.router.add_post('/api/articles/{id}/open', open_source)
    app.router.add_get('/api/articles/{id}/audio/{index}', audio)
    app.router.add_delete('/api/articles/{id}', delete)
    return app


async def main(args):
    from playwright.async_api import async_playwright
    state = Runtime(args.data_dir, args.models)
    runner = web.AppRunner(make_app(state))
    try:
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', args.port).start()
        async with async_playwright() as p:
            state.playwright = p
            state.context = await p.chromium.launch_persistent_context(
                str(args.data_dir / 'browser'), headless=False, no_viewport=True,
                **({'executable_path': args.browser_executable} if args.browser_executable else {}),
                args=['--autoplay-policy=no-user-gesture-required'])
            async def from_page(source, article_id, action, value=None):
                if state.pages.get(article_id) != source['page']:
                    return
                if action == 'region':
                    state.commands.append({'action': 'stop'})
                    region = {k: max(0, float(value[k])) for k in ('left','top','right','bottom')}
                    article = await state.install(source['page'], state.store.get(article_id)['url'], region)
                    state.commands.append({'action': 'select', 'article': article, 'autoplay': False})
                elif action in ('toggle', 'next', 'previous', 'seek', 'speed', 'jump', 'stop'):
                    state.commands.append({'id': article_id, 'action': action, 'value': value})
            async def player_state(source, article_id):
                if state.pages.get(article_id) != source['page']:
                    return {}
                return state.playback if state.playback.get('id') == article_id else {'id': article_id, 'inactive': True}
            await state.context.expose_binding('pageReaderCommand', from_page)
            await state.context.expose_binding('pageReaderState', player_state)
            page = await state.context.new_page()
            await page.goto(f'http://127.0.0.1:{args.port}')
            await page.bring_to_front()
            print(f'Page Reader: http://127.0.0.1:{args.port} · Ctrl+C для выхода', flush=True)
            closed = asyncio.Event()
            state.context.on('close', lambda _: closed.set())
            await closed.wait()
    finally:
        for task in state.watchers:
            task.cancel()
        await asyncio.gather(*state.watchers, return_exceptions=True)
        await runner.cleanup()
        if state.context:
            await state.context.close()
        state.store.close()


if __name__ == '__main__':
    default_data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'page-reader'
    if sys.platform == 'win32':
        default_data = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PageReader'
    elif sys.platform == 'darwin':
        default_data = Path.home() / 'Library/Application Support/PageReader'
    parser = argparse.ArgumentParser(description='Page Reader — локальное озвучивание сайтов')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=default_data)
    parser.add_argument('--models', type=Path, default=ROOT / 'models')
    parser.add_argument('--browser-executable', help='Путь к установленному Chromium/Chrome вместо браузера Playwright')
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'Ошибка запуска: {e}\nУстановите зависимости: python setup.py', file=sys.stderr)
        sys.exit(1)
