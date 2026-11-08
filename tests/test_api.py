import asyncio
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch
from aiohttp.test_utils import TestClient, TestServer
from app import Runtime, make_app
from core import prepare_units


class Page:
    def __init__(self):
        self.closed = False
        self.visited = None
        self.url = "https://example.org/article"
    async def goto(self, url, **kwargs): self.visited = url; self.url = url
    async def wait_for_timeout(self, ms): pass
    async def evaluate(self, code, *args):
        if code == 'readerScan()' or code == 'region => readerScan(region)':
            return [{'index':0,'kind':'text','text':'Это тестовая статья. '*40}]
    async def title(self): return 'Тестовая статья'
    async def close(self): self.closed = True
    def is_closed(self): return self.closed
    async def bring_to_front(self): pass


class Context:
    def __init__(self): self.pages = []
    async def new_page(self):
        page = Page()
        self.pages.append(page)
        return page


def wav_fixture(text, lang):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
        wav.writeframes(b'\0\0' * 2205)
    return output.getvalue()


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Runtime(Path(self.tmp.name), Path(self.tmp.name) / 'models')
        self.state.context = Context()
        self.client = TestClient(TestServer(make_app(self.state)))
        await self.client.start_server()
        self.headers = {'X-Reader-Token':self.state.token}

    async def asyncTearDown(self):
        for task in self.state.watchers: task.cancel()
        await asyncio.gather(*self.state.watchers, return_exceptions=True)
        await self.client.close()
        self.state.store.close()
        self.tmp.cleanup()

    async def test_ui_and_unauthorized_origin(self):
        response = await self.client.get('/')
        self.assertEqual(response.status, 200)
        self.assertIn(self.state.token, await response.text())
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        response = await self.client.get('/api/articles')
        self.assertEqual(response.status, 403)
        response = await self.client.get('/api/articles', headers={**self.headers,'Host':'evil.example'})
        self.assertEqual(response.status, 403)

    async def test_add_new_tab_resume_and_delete(self):
        response = await self.client.post('/api/articles', json={'url':'https://example.org/article'}, headers=self.headers)
        self.assertEqual(response.status, 200)
        article = await response.json()
        self.assertEqual(len(self.state.context.pages), 1)
        self.assertEqual(self.state.context.pages[0].visited, article['url'])
        id = article['id']
        response = await self.client.post(f'/api/articles/{id}/progress', json={'cursor':1,'fraction':.42}, headers=self.headers)
        self.assertEqual(response.status, 200)
        response = await self.client.get('/api/articles', headers=self.headers)
        saved = (await response.json())[0]
        self.assertEqual((saved['cursor'], saved['fraction']), (1,.42))
        response = await self.client.post('/api/articles', json={'url':article['url']}, headers=self.headers)
        self.assertEqual((await response.json())['fraction'], .42)
        self.assertEqual(len(self.state.context.pages), 2)
        self.assertTrue(self.state.context.pages[0].closed)
        response = await self.client.delete(f'/api/articles/{id}', headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertTrue(self.state.context.pages[1].closed)
        self.assertEqual(self.state.store.list(), [])

    async def test_audio_contract_cache_and_invalid_index(self):
        article = self.state.store.put('https://example.org/', 'test', prepare_units([{'kind':'text','index':0,'text':'Привет'}]))
        self.state.synthesize = Mock(side_effect=wav_fixture)
        url = f"/api/articles/{article['id']}/audio/0"
        for _ in range(2):
            response = await self.client.get(url, headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, 'audio/wav')
            with wave.open(io.BytesIO(await response.read())) as wav:
                self.assertEqual(wav.getnframes(), 2205)
        self.state.synthesize.assert_called_once_with('Привет', 'ru')
        response = await self.client.get(url[:-1] + '-1', headers=self.headers)
        self.assertEqual(response.status, 400)

    async def test_empty_synthesis_still_writes_valid_wav(self):
        import types
        voice = Mock()
        voice.synthesize.return_value = iter(())
        self.state.voices[self.state.models.selected['ru']] = voice
        module = types.SimpleNamespace(PiperVoice=Mock(), SynthesisConfig=Mock())
        with patch.dict('sys.modules', {'piper': module}):
            result = self.state.synthesize(';', 'ru')
        with wave.open(io.BytesIO(result)) as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertGreater(wav.getnframes(), 0)

    async def test_import_and_reopen_local_file(self):
        from aiohttp import FormData
        form = FormData()
        form.add_field('file', b'Local document text.', filename='book.txt', content_type='text/plain')
        response = await self.client.post('/api/import', data=form, headers=self.headers)
        self.assertEqual(response.status, 200)
        article = await response.json()
        self.assertTrue(article['url'].startswith('local://'))
        digest = article['url'][8:]
        response = await self.client.get('/documents/' + digest)
        self.assertIn('Local document text.', await response.text())
        response = await self.client.get('/documents/' + digest + '/source')
        self.assertEqual(await response.read(), b'Local document text.')
        self.state.store.progress(article['id'], 1, .3)
        await self.state.pages[article['id']].close()
        response = await self.client.post('/api/articles/' + article['id'] + '/open', json={}, headers=self.headers)
        self.assertEqual(response.status, 200)
        saved = await response.json()
        self.assertEqual((saved['cursor'], saved['fraction']), (1, .3))

    async def test_invalid_inputs(self):
        response = await self.client.post('/api/articles', json={'url':'file:///etc/passwd'}, headers=self.headers)
        self.assertEqual(response.status, 400)
        response = await self.client.post('/api/articles/missing/progress', json={'cursor':0}, headers=self.headers)
        self.assertEqual(response.status, 404)


if __name__ == '__main__': unittest.main()
