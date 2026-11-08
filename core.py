"""Persistence and document preparation; independent of UI and speech engine."""
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit


def normalize_url(value):
    value = str(value).strip()
    if '://' not in value:
        value = 'https://' + value
    u = urlsplit(value)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise ValueError('Введите ссылку HTTP или HTTPS без логина и пароля.')
    try:
        u.port
    except ValueError:
        raise ValueError('Некорректный порт в ссылке.')
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path or '/', u.query, ''))


def chunks(text, limit=300):
    text = re.sub(r'\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]', '', text)
    text = re.sub(r'https?://\S+', '', text)
    result, part = [], ''
    for word in text.split():
        if part and len(part) + len(word) + 1 > limit:
            result.append(part)
            part = ''
        part = (part + ' ' + word).strip()
    if part:
        result.append(part)
    return result


def language(text):
    return 'ru' if len(re.findall('[А-Яа-яЁё]', text)) > len(re.findall('[A-Za-z]', text)) else 'en'


def prepare_units(units):
    prepared = []
    for unit in units:
        if unit['kind'] == 'text':
            for text in chunks(unit['text']):
                if not any(c.isalnum() for c in text):
                    continue
                prepared.append({'kind': 'text', 'text': text, 'source': unit['index'], 'lang': language(text)})
        else:
            prepared.append({'kind': unit['kind'], 'text': '', 'source': unit['index'], 'seconds': 3, 'areaRatio': max(0, float(unit.get('areaRatio', 0)))})
    if not any(u['kind'] == 'text' for u in prepared):
        raise ValueError('На странице нет доступного текста. Откройте статью, войдите на сайт при необходимости и повторите загрузку.')
    if len(prepared) > 12000:
        raise ValueError('Страница слишком большая: откройте отдельную статью.')
    return prepared


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY, url TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            units TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
            fraction REAL NOT NULL DEFAULT 0, updated TEXT NOT NULL)''')
        if 'region' not in [r[1] for r in self.db.execute('PRAGMA table_info(articles)')]:
            self.db.execute('ALTER TABLE articles ADD COLUMN region TEXT')
        self.db.commit()

    def get(self, id):
        row = self.db.execute('SELECT * FROM articles WHERE id=?', (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        item = dict(row)
        item['units'] = json.loads(item['units'])
        item['region'] = json.loads(item.get('region') or 'null')
        return item

    def list(self):
        ids = self.db.execute('SELECT id FROM articles ORDER BY updated DESC').fetchall()
        return [self.get(r['id']) for r in ids]

    def put(self, url, title, units):
        id = hashlib.sha256(url.encode()).hexdigest()[:24]
        old = self.db.execute('SELECT units,cursor,fraction FROM articles WHERE id=?', (id,)).fetchone()
        serialized = json.dumps(units, ensure_ascii=False)
        # A changed document must never inherit an unrelated numeric cursor.
        same = old and [(u['kind'], u.get('text','')) for u in json.loads(old['units'])] == [(u['kind'], u.get('text','')) for u in units]
        self.db.execute('''INSERT INTO articles(id,url,title,units,updated) VALUES(?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title, units=excluded.units,
            cursor=CASE WHEN ? THEN articles.cursor ELSE 0 END,
            fraction=CASE WHEN ? THEN articles.fraction ELSE 0 END, updated=excluded.updated''',
            (id, url, title, serialized, datetime.now(timezone.utc).isoformat(), bool(same), bool(same)))
        self.db.commit()
        return self.get(id)

    def progress(self, id, cursor, fraction):
        item = self.get(id)
        cursor = max(0, min(len(item['units']), int(cursor)))
        fraction = float(fraction)
        if not math.isfinite(fraction):
            raise ValueError('Некорректная позиция воспроизведения.')
        fraction = max(0, min(.999, fraction)) if cursor < len(item['units']) else 0
        self.db.execute('UPDATE articles SET cursor=?,fraction=?,updated=? WHERE id=?',
                        (cursor, fraction, datetime.now(timezone.utc).isoformat(), id))
        self.db.commit()
        return self.get(id)

    def delete(self, id):
        self.db.execute('DELETE FROM articles WHERE id=?', (id,))
        self.db.commit()

    def close(self):
        self.db.close()
