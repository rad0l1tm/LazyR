"""Import local documents into an escaped, readable HTML view."""
import hashlib
import io
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
EXTENSIONS = {'.pdf', '.txt', '.md', '.html', '.htm'}

class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if not self.skip and tag in ('p','div','br','li','h1','h2','h3','section','article'):
            self.parts.append('\n\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if not self.skip and tag in ('p','div','li'):
            self.parts.append('\n\n')
    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


def extract(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError('Поддерживаются PDF, TXT, MD и HTML.')
    if not content or len(content) > MAX_BYTES:
        raise ValueError('Выберите непустой файл размером до 64 МБ.')
    if suffix == '.pdf':
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted and not reader.decrypt(''):
                raise ValueError('PDF защищён паролем. Сохраните копию без пароля и добавьте её.')
            if len(reader.pages) > 1500:
                raise ValueError('PDF содержит более 1500 страниц. Разделите его на части.')
            pages = []
            size = 0
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ''
                size += len(text)
                if size > 4_000_000:
                    raise ValueError('Слишком большой текст. Разделите документ на части.')
                pages.append((f'Страница {i+1}', text))
        except ValueError:
            raise
        except Exception as error:
            raise ValueError('Не удалось прочитать PDF: возможно, файл повреждён или зашифрован.') from error
        if not any(any(c.isalnum() for c in text) for _, text in pages):
            raise ValueError('В PDF нет извлекаемого текста. Для сканов сначала нужно распознавание OCR.')
    else:
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                text = content.decode('cp1251')
            except UnicodeDecodeError as error:
                raise ValueError('Не удалось определить кодировку. Сохраните текст в UTF-8.') from error
        if suffix in ('.html', '.htm'):
            parser = TextHTML()
            parser.feed(text)
            text = ''.join(parser.parts)
        if len(text) > 4_000_000:
            raise ValueError('Слишком большой текст. Разделите документ на части.')
        if not any(c.isalnum() for c in text):
            raise ValueError('В файле нет текста для озвучивания.')
        pages = [('', text)]
    return pages


def import_document(directory, filename, content):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(filename.replace('\\', '/')).name[:180] or 'Документ.txt'
    pages = extract(name, content)
    digest = hashlib.sha256(Path(name).suffix.lower().encode() + b'\0' + content).hexdigest()
    sections = []
    for title, text in pages:
        paragraphs = ''.join('<p>'+escape(part.strip())+'</p>' for part in re.split(r'\n\s*\n', text) if part.strip())
        if paragraphs:
            sections.append('<section>' + ('<h2>'+escape(title)+'</h2>' if title else '') + paragraphs + '</section>')
    html = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+escape(name)+'''</title><style>body{margin:0;background:#f5f5f1;color:#26352f;font:18px/1.8 system-ui;padding:35px 20px 190px}header,main{max-width:850px;margin:auto}h1{font-size:26px;overflow-wrap:anywhere}h2{font-size:17px;color:#7c857e;margin-top:35px}p{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #dfe6d8;margin-top:24px}header small{color:#7c857e}a{color:#284e3c}</style></head><body><header><small>ЛОКАЛЬНЫЙ ДОКУМЕНТ · ТЕКСТ ДЛЯ ЧТЕНИЯ</small><h1>'''+escape(name)+'''</h1><a download href="/documents/'''+digest+'''/source">Скачать исходный файл</a></header><main>'''+''.join(sections)+'''</main></body></html>'''
    # All extraction/validation finishes before the existing saved copy is replaced.
    for suffix, data in (('.source', content), ('.html', html.encode('utf-8')), ('.json', json.dumps({'name': name}, ensure_ascii=False).encode('utf-8'))):
        temporary = directory / (digest + suffix + '.tmp')
        temporary.write_bytes(data)
        temporary.replace(directory / (digest + suffix))
    return digest
