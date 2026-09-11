import json
import sqlite3

from app import card_names, stats, store
from app.insights import daily_report, targeting
from tools.import_card_names import build_catalog, resolve_name
from tools.sync_card_names import translated


def test_faces_and_rebalanced_identity():
    card = {'name':'Front // Back', 'lang':'zhs', 'card_faces':[
        {'printed_name':'正面'}, {'printed_name':'背面'}]}
    assert translated(card, 'Front // Back') == '正面 // 背面'
    assert translated(card, 'A-Front // A-Back') is None
    card['card_faces'][1] = {'name':'Back'}
    assert translated(card, 'Front // Back') == '正面 // Back'


def test_catalog_local_and_english(tmp_path):
    (tmp_path/'data').mkdir()
    (tmp_path/'data/card_names.catalog.json').write_text(json.dumps({
        '1': {'name_en':'First', 'name_zh':'第一', 'source':'Scryfall'},
        '2': {'name_en':'A-First', 'name_zh':'', 'source':'无译名'},
        '9': {'name_en':'Front // Back', 'name_zh':'正面 // 背面', 'source':'x'},
        '10': {'name_en':'A-Nadu', 'name_zh':'A-拿杜', 'source':'x'},
    }),encoding='utf-8')
    c=sqlite3.connect(':memory:')
    assert card_names.CardNames(c,root=tmp_path).get('1')['name'] == '第一'
    assert card_names.CardNames(c,lang='en',root=tmp_path).get('1')['name'] == 'First'
    # 炼金 A- 前缀在显示名中去掉；英文身份保留完整
    alchemy = card_names.CardNames(c,root=tmp_path).get('10')
    assert alchemy['name'] == '拿杜'
    assert alchemy['name_en'] == 'A-Nadu'
    dual = card_names.CardNames(c,root=tmp_path).get('9')
    assert dual['name'] == '正面'
    assert dual['name_full'] == '正面 // 背面'
    path=tmp_path/'data/card_names.zh.json'
    path.write_text(json.dumps({'1':{'name_zh':'社区译名','source':'社区出处'}}),encoding='utf-8')
    name=card_names.CardNames(c,root=tmp_path).get('1')
    assert name['name']=='社区译名' and '社区出处' in name['name_source']
    path.write_text('[]',encoding='utf-8')
    assert card_names.CardNames(c,root=tmp_path).get('1')['name']=='第一'
    assert card_names.CardNames(c,root=tmp_path).get('3')['name']=='grpId:3'
    c.close()


def test_same_chinese_name_not_merged(tmp_path, monkeypatch):
    from datetime import datetime
    c=store.connect(tmp_path/'matches.db')
    c.execute("ATTACH DATABASE ':memory:' AS cards_db")
    c.execute('CREATE TABLE cards_db.cards(grp_id TEXT, name TEXT, name_zh TEXT)')
    # Different printings / rebalance IDs stay separate even if labels coincide.
    c.executemany('INSERT INTO cards_db.cards VALUES(?,?,?)', [('1','First','同名'),('2','A-First','同名')])
    day=datetime.now().replace(hour=10,minute=0,second=0,microsecond=0)
    for i in range(6):
        mid=str(i)
        c.execute("INSERT INTO matches(match_id,start_time,event_id,my_seat,my_result,play_draw) VALUES(?,?,'Play_Brawl_Historic',1,'loss','draw')", (mid,int(day.timestamp()*1000)+i*1000))
        c.execute('INSERT INTO commanders(match_id,seat,grp_id) VALUES(?,2,?)',(mid,str(1+i%2)))
    report=daily_report(c,day.date().isoformat())
    assert report['summary']['distinct_commanders']==2
    assert sorted(x['n'] for x in report['summary']['top_commanders'])==[3,3]
    assert len(stats.matchups(c))==2
    assert stats.match_list(c)['rows'][0]['opp_cards'][0]['name_en']=='A-First'
    assert report['highlight_records'][0]['commander_cards'][0]['name_source']=='已有缓存（来源未记录）'
    c.close()


def test_local_snapshot_import_is_print_exact_and_allows_one_face(tmp_path):
    source = tmp_path / 'snapshot-1'
    names = source / 'utf8' / 'name'
    names.mkdir(parents=True)
    rows = [
        {'key':'SET·1 | Front | Name | a', 'original':'Front',
         'translation':'正面', 'stage':9, 'context':'Official Name:'},
        {'key':'SET·1 | Back | Name | b', 'original':'Back',
         'translation':'背面', 'stage':9, 'context':'Official Name:'},
        {'key':'SET·A-2 | A-Card | Name | c', 'original':'A-Card',
         'translation':'A-卡牌', 'stage':5, 'context':'Translated from: MTGZH\n'},
        {'key':'SET·3 | Unsafe | Name | d', 'original':'Unsafe',
         'translation':'机器候选', 'stage':1, 'context':'Translated from: gpt\n'},
    ]
    (names/'2026-01-01-SET.json').write_text(
        json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    db = tmp_path/'cards.db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE cards(grp_id TEXT,name TEXT,set_code TEXT,collector_number TEXT)')
        c.executemany('INSERT INTO cards VALUES(?,?,?,?)', [
            ('1','Front // Back','set','1'), ('2','A-Card','set','A-2'),
            ('3','Unsafe','set','3'), ('4','Front // Missing','set','1'),
            ('5','Front /// Missing','set','1')])
    catalog, meta = build_catalog(source, db, min_stage=5)
    assert catalog['1']['name_zh'] == '正面 // 背面'
    assert catalog['2']['name_zh'] == 'A-卡牌'
    assert '官方译名' in catalog['1']['source']
    assert 'MTGZH' in catalog['2']['source']
    assert '3' not in catalog
    assert catalog['4']['name_zh'] == '正面 // Missing'
    assert '部分译名（1/2' in catalog['4']['source']
    assert catalog['5']['name_zh'] == '正面 /// Missing'
    assert meta['cards_seen'] == 5 and meta['cards_matched'] == 4


def test_local_snapshot_ambiguous_name_needs_exact_printing():
    one = {'english':'Same', 'chinese':'甲', 'stage':9,
           'set_code':'one', 'collector':'1', 'provider':''}
    two = {**one, 'chinese':'乙', 'set_code':'two'}
    exact = {('Same','one','1'): one, ('Same','two','1'): two}
    assert resolve_name('Same','one','1',exact,{},'snapshot')['name_zh'] == '甲'
    assert resolve_name('Same','other','1',exact,{},'snapshot') is None
