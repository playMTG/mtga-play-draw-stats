"""补全已导入对局；默认 dry-run，--apply 备份后补全，不创建新比赛。

输入：raw_b*.json、公开 cards-review.json、loc-en-review.json。
压缩字符串的 titleId 通过卡牌表映射，禁止直接当作 Arena grpId。
"""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from app.config import load_config
from app.deckstrings import decode
from app.deck_versions import fingerprint
from app.events import GameRecord, MatchRecord
from app import store
from app.cards_sync import cards_db_connect


def walk_matches(value):
    if isinstance(value, dict):
        if 'short_id' in value and 'games' in value:
            yield value
        else:
            for child in value.values():
                yield from walk_matches(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_matches(child)


def load_raw(folder):
    out = {}
    for path in sorted(folder.glob('raw_b*.json')):
        for m in walk_matches(json.loads(path.read_text(encoding='utf-8'))):
            out[m['short_id']] = m
    return list(out.values())


def card_mapping(cards, preferred=()):
    by_title = defaultdict(list)
    for c in cards:
        if not c.get('isSecondaryCard') and not c.get('isToken'):
            by_title[c['titleId']].append(c)
    preferred = set(map(str, preferred))
    mapping = {t: min(cs, key=lambda c: (str(c['grpid']) not in preferred, c['grpid']))
               for t,cs in by_title.items()}
    by_id = {c['grpid']:c for c in cards}
    for c in cards:
        if c['titleId'] in mapping or c.get('isToken'):
            continue
        # 双面卡的背面归到明确 linkedFaces 的正面；替代显示版本依据 interchangeableTitleId。
        primary = [by_id[g] for g in c.get('linkedFaces',[]) if g in by_id and not by_id[g].get('isSecondaryCard')]
        target = primary[0]['titleId'] if primary else c.get('interchangeableTitleId')
        if target in mapping:
            mapping[c['titleId']] = mapping[target]
    return mapping


def enrich(conn, raw, mapping, cfg, apply=False):
    report = dict(raw=len(raw), matched=0, skipped=0, commanders=0, mulligans=0,
                  my_commanders=0, opponent_commanders=0,
                  invalid_deckstrings=0, unresolved_titles=0)
    for source in raw:
        seat = source.get('friendly_system_seat_id')
        active = source.get('active_player_id')
        if seat is None:
            report['skipped'] += 1; continue
        on = int(active == seat)
        mid = f"ut_{source['match_start']}_{source.get('friendly_deck_id') or ''}_{on}"
        old = conn.execute("SELECT * FROM matches WHERE match_id=? AND source='untapped'",(mid,)).fetchone()
        if old is None:
            report['skipped'] += 1; continue
        # Exact historical synthetic ID; do not guess using fuzzy time matches.
        report['matched'] += 1
        m = MatchRecord(match_id=mid, source='untapped', my_seat=seat)
        m.my_deck_id = source.get('friendly_deck_id')
        own = source.get('friendly_deckstring')
        own_deck = None
        if own:
            try:
                own_deck = decode(own)
                m.my_deck_version = fingerprint(own_deck)
            except ValueError:
                report['invalid_deckstrings'] += 1
        opponents = source.get('opponents') or []
        if len(opponents) == 1:
            m.opponent_name = opponents[0].get('player_name')
        # Existing data is two-player; synthetic opposing seat is only an internal key.
        opp_seat = 2 if seat == 1 else 1
        seen_own = set()
        seen_opp = set()
        if 'Brawl' in (source.get('event_name') or '') and own_deck:
            for title in own_deck['commanders']:
                card = mapping.get(title)
                if card is None:
                    report['unresolved_titles'] += 1
                    continue
                gid = str(card['grpid'])
                if gid not in seen_own:
                    m.commanders.append({
                        'seat': seat, 'grp_id': gid, 'partner_idx': len(seen_own),
                    })
                    seen_own.add(gid)
        for g in source.get('games') or []:
            no = g.get('game_number')
            if not isinstance(no,int):
                continue
            result = None if g.get('winning_team_id') is None else (
                'win' if g['winning_team_id']==source.get('friendly_team_id') else 'loss')
            pd = None if g.get('active_player_id') is None else ('play' if g['active_player_id']==seat else 'draw')
            m.games.append(GameRecord(game_no=no,result=result,play_draw=pd))
            hands = g.get('player_opening_hands')
            if isinstance(hands,list) and hands:
                m.mulligans.append({'game_no':no,'seat':seat,'kept_on':len(hands)-1})
            if 'Brawl' not in (source.get('event_name') or ''):
                continue
            for encoded in g.get('opponent_revealed_deckstrings') or []:
                try:
                    titles = decode(encoded)['commanders']
                except ValueError:
                    report['invalid_deckstrings'] += 1; continue
                for title in titles:
                    card = mapping.get(title)
                    if card is None:
                        report['unresolved_titles'] += 1; continue
                    gid = str(card['grpid'])
                    if gid not in seen_opp:
                        m.commanders.append({'seat':opp_seat,'grp_id':gid,'partner_idx':len(seen_opp)})
                        seen_opp.add(gid)
        report['commanders'] += bool(m.commanders)
        report['my_commanders'] += bool(seen_own)
        report['opponent_commanders'] += bool(seen_opp)
        report['mulligans'] += bool(m.mulligans)
        if apply:
            store.upsert_match(conn,m,cfg)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    cfg=load_config(); folder=cfg.root/'data'/'untapped'
    conn=sqlite3.connect(f'file:{cfg.db_path.as_posix()}?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    preferred=[r[0] for r in conn.execute('SELECT DISTINCT grp_id FROM commanders')]
    cards=json.loads((folder/'cards-review.json').read_text(encoding='utf-8'))
    mapping=card_mapping(cards,preferred)
    raw=load_raw(folder)
    report=enrich(conn,raw,mapping,cfg)
    print(json.dumps(report))
    if not args.apply:
        conn.close(); return
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=cfg.root/'data'/'backups'/f'before-enrichment-{stamp}.db'
    backup.parent.mkdir(parents=True,exist_ok=True)
    dest=sqlite3.connect(backup);conn.backup(dest);dest.close();conn.close()
    conn=store.connect(cfg.db_path)
    try:
        before=conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0]
        report=enrich(conn,raw,mapping,cfg,apply=True)
        assert conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==before
        conn.commit()
    except Exception:
        conn.rollback();raise
    finally:
        conn.close()
    # 补充公开卡名缓存，保留现有中文翻译。
    names={x['id']:x.get('raw') or x.get('text') for x in json.loads((folder/'loc-en-review.json').read_text(encoding='utf-8'))}
    cc=cards_db_connect(cfg.root/'data'/'mtga_cards.db')
    for c in mapping.values():
        name=names.get(c['titleId'])
        if name:
            cc.execute('INSERT INTO cards(grp_id,name) VALUES(?,?) ON CONFLICT(grp_id) DO NOTHING',
                       (str(c['grpid']),name))
    cc.commit();cc.close()
    print(json.dumps({'applied':report,'backup':str(backup)}))


if __name__=='__main__':
    main()
