"""Card display metadata, keyed strictly by Arena grpId, never translated text."""
import json
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=8)
def _json(path, stamp):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def read_names(path):
    try:
        stat = path.stat()
        return _json(str(path), (stat.st_mtime_ns, stat.st_size))
    except OSError:
        return {}


class CardNames:
    def __init__(self, conn, lang=None, root=None):
        self.root = Path(root or ROOT)
        if lang is None:
            from .config import load_config
            lang = load_config(self.root).get('card_name_lang', 'zh')
        self.lang = lang
        self.local = read_names(self.root / 'data/card_names.zh.json')
        self.catalog = read_names(self.root / 'data/card_names.catalog.json')
        try:
            self.cards = {str(r['grp_id']): dict(r) for r in conn.execute('SELECT * FROM cards_db.cards')}
        except sqlite3.OperationalError:
            self.cards = {}

    def get(self, gid):
        gid = str(gid)
        row = self.cards.get(gid, {})
        cached = self.catalog.get(gid, {})
        if not isinstance(cached, dict):
            cached = {}
        english = row.get('name') or cached.get('name_en') or ''
        # A catalog entry belongs to one exact English identity; stale/conflicting entries cannot rename it.
        if english and cached.get('name_en') != english:
            cached = {}
        zh = cached.get('name_zh') or row.get('name_zh') or ''
        source = cached.get('source') if cached.get('name_zh') else ('已有缓存（来源未记录）' if zh else '英文回退')
        local = self.local.get(gid)
        if isinstance(local, dict) and isinstance(local.get('name_zh'), str) and local['name_zh'].strip():
            zh = local['name_zh'].strip()
            source = '用户本地译名' + ('：' + local['source'] if isinstance(local.get('source'), str) else '')
        name = (zh if self.lang == 'zh' else english) or english or zh or f'grpId:{gid}'
        return {'key': gid, 'name': name, 'name_en': english, 'name_zh': zh,
                'name_source': source or '来源未记录'}
