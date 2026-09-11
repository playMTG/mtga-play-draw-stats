"""Card display metadata, keyed strictly by Arena grpId, never translated text."""
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_FACE_SPLIT = re.compile(r"\s+/{2,3}\s+")


_ALCH_PREFIX = re.compile(r"^A-\s*", re.IGNORECASE)


def strip_alchemy_prefix(name: str) -> str:
    """炼金重平衡 A- 前缀对展示无信息量（身份仍用完整英文/ grpId）。"""
    if not name or not isinstance(name, str):
        return name
    return _ALCH_PREFIX.sub("", name, count=1).strip() or name


def front_face(name: str) -> str:
    """双面/转化卡显示只用正面名称；再去掉炼金 A- 前缀。"""
    if not name or not isinstance(name, str):
        return name
    face = _FACE_SPLIT.split(name, 1)[0].strip() or name
    return strip_alchemy_prefix(face)


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
        src = row.get('source')
        if zh:
            source = cached.get('source') or '已有缓存（来源未记录）'
        elif english and src == 'client':
            # 客户端库只提供英文名，没有中文译名
            source = '本机客户端卡名库（无中文译名）'
        elif english and src == 'scryfall':
            source = 'Scryfall（尚未取到中文译名）'
        elif english:
            # 有英文名但 source 为空：早期版本导入时还没有 source 列，
            # 无法回溯真实来源，如实标注「未记录」而不是猜一个（R12.1）
            source = '英文名（来源未记录）'
        else:
            # 完全没名字：展示的就是 grpId，不能再声称是「英文回退」（R12.1）
            source = '缺卡名（客户端库与译名库均未命中）'
        local = self.local.get(gid)
        if isinstance(local, dict) and isinstance(local.get('name_zh'), str) and local['name_zh'].strip():
            zh = local['name_zh'].strip()
            source = '用户本地译名' + ('：' + local['source'] if isinstance(local.get('source'), str) else '')
        name_full = (zh if self.lang == 'zh' else english) or english or zh or f'grpId:{gid}'
        name = front_face(name_full) if name_full and not name_full.startswith('grpId:') else name_full
        return {'key': gid, 'name': name, 'name_full': name_full,
                'name_en': english, 'name_zh': zh,
                'name_source': source or '来源未记录'}
