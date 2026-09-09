"""Explicit public-name download. Writes only display catalog, never match data."""
import argparse
import json
import sqlite3
import time
from urllib.parse import urlencode

from app.config import load_config
from app.cards_sync import _curl_json


def translated(card, english):
    if card.get('name') != english or card.get('lang') not in ('zhs', 'zht'):
        return None
    faces = card.get('card_faces') or []
    if faces:
        names = [f.get('printed_name') or f.get('name') or '' for f in faces]
        translated_faces = sum(bool(f.get('printed_name')) for f in faces)
    else:
        names = [card.get('printed_name') or '']
        translated_faces = int(bool(card.get('printed_name')))
    if not names or not translated_faces or not all(isinstance(n, str) and n.strip() for n in names):
        return None
    return ' // '.join(names)


def fetch_name(gid):
    card = _curl_json(f'https://api.scryfall.com/cards/arena/{gid}') or {}
    english, oracle = card.get('name'), card.get('oracle_id')
    if not english or not oracle:
        return None
    for lang in ('zhs', 'zht'):
        time.sleep(.15)
        query = urlencode({'q': f'oracleid:{oracle} lang:{lang}', 'unique': 'prints'})
        result = _curl_json('https://api.scryfall.com/cards/search?' + query) or {}
        for printing in result.get('data', []):
            if printing.get('oracle_id') != oracle:
                continue
            zh = translated(printing, english)
            if zh:
                return {'name_en': english, 'name_zh': zh,
                        'source': 'Scryfall 中文印刷资料（' + ('简体' if lang == 'zhs' else '繁体') + '）',
                        'source_url': printing.get('scryfall_uri'), 'language': lang}
    return {'name_en': english, 'name_zh': '', 'source': '暂无中文印刷译名'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=60)
    args = parser.parse_args()
    cfg = load_config()
    path = cfg.root / 'data/card_names.catalog.json'
    catalog = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    with sqlite3.connect(cfg.db_path.as_uri() + '?mode=ro', uri=True) as conn:
        gids = [str(r[0]) for r in conn.execute('SELECT grp_id FROM commanders GROUP BY grp_id ORDER BY COUNT(*) DESC')]
    todo = [g for g in gids if g.isdigit() and g not in catalog][:args.limit]
    for i, gid in enumerate(todo):
        value = fetch_name(gid)
        if value:
            catalog[gid] = value
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(path)
        print(f'{i+1}/{len(todo)}: {gid}: ' + ('translated' if value and value['name_zh'] else 'fallback'), flush=True)
        time.sleep(.15)


if __name__ == '__main__':
    main()
