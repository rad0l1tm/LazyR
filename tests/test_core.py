import tempfile
import unittest
from pathlib import Path
from core import Store, chunks, language, normalize_url, prepare_units


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'history.db'
        self.store = Store(self.path)
        self.units = prepare_units([{'index': 0, 'kind': 'text', 'text': 'Привет, мир. ' * 100}])
        self.article = self.store.put('https://example.org/', 'Статья', self.units)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_restart_keeps_fraction_and_text(self):
        self.store.progress(self.article['id'], 2, .45)
        self.store.close()
        self.store = Store(self.path)
        saved = self.store.get(self.article['id'])
        self.assertEqual((saved['cursor'], saved['fraction']), (2, .45))
        self.assertEqual(saved['units'], self.units)

    def test_same_link_deduplicates_and_keeps_progress(self):
        self.store.progress(self.article['id'], 1, .25)
        repeated = self.store.put('https://example.org/', 'Новое название', self.units)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual((repeated['cursor'], repeated['fraction']), (1, .25))

    def test_layout_changes_do_not_reset_progress(self):
        self.store.progress(self.article['id'], 2, .45)
        changed = [{**u, 'source': 900, 'areaRatio': .9} for u in self.units]
        article = self.store.put('https://example.org/', 'Статья', changed)
        self.assertEqual((article['cursor'], article['fraction']), (2, .45))
        self.store.close()
        self.store = Store(self.path)
        saved = self.store.get(article['id'])
        self.assertEqual((saved['cursor'], saved['fraction']), (2, .45))

    def test_changed_text_resets_progress(self):
        self.store.progress(self.article['id'], 2, .5)
        article = self.store.put('https://example.org/', 'Обновлено', self.units[:1])
        self.assertEqual((article['cursor'], article['fraction']), (0, 0))

    def test_completed_and_clamped_positions(self):
        a = self.store.progress(self.article['id'], 999, .7)
        self.assertEqual((a['cursor'], a['fraction']), (len(self.units), 0))
        a = self.store.progress(a['id'], -10, -.2)
        self.assertEqual((a['cursor'], a['fraction']), (0, 0))
        with self.assertRaises(ValueError):
            self.store.progress(a['id'], 0, float('nan'))

    def test_delete(self):
        self.store.delete(self.article['id'])
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(KeyError):
            self.store.get(self.article['id'])


class DocumentTests(unittest.TestCase):
    def test_url_validation(self):
        self.assertEqual(normalize_url(' EXAMPLE.org/a#note '), 'https://example.org/a')
        for url in ['javascript://alert', 'file:///etc/passwd', 'https://u:p@example.org', 'https://', 'http://x:invalid']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)

    def test_chunk_cleaning_and_language(self):
        result = chunks(('Пример текста [1, 2]. https://example.org ' * 40))
        self.assertGreater(len(result), 1)
        self.assertTrue(all(len(x) <= 300 for x in result))
        self.assertNotIn('[1, 2]', ' '.join(result))
        self.assertNotIn('https://', ' '.join(result))
        self.assertEqual(language('Русский текст'), 'ru')
        self.assertEqual(language('English text'), 'en')

    def test_punctuation_is_not_sent_to_speech(self):
        units = prepare_units([{'index':0,'kind':'text','text':';'}, {'index':1,'kind':'text','text':'Продолжение'}])
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['text'], 'Продолжение')

    def test_visual_units_and_empty_page(self):
        units = prepare_units([{'index': 0, 'kind':'table', 'text':''}, {'index':1, 'kind':'text', 'text':'Статья'}])
        self.assertEqual(units[0]['seconds'], 3)
        self.assertEqual(units[1]['source'], 1)
        with self.assertRaises(ValueError):
            prepare_units([{'index':0,'kind':'image/visual','text':''}])


if __name__ == '__main__':
    unittest.main()
