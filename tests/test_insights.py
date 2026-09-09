from datetime import datetime, timedelta
import base64
import json

import pytest

from app.config import Config
from app.events import MatchRecord, GameRecord, SessionBuilder
from app import store, stats
from app.insights import daily_report
from app.deckstrings import decode
from app.watcher import LogWatcher
from tools.enrich_untapped import enrich, card_mapping
import fixtures as fx


@pytest.fixture
def db(tmp_path):
    c=store.connect(tmp_path/'test.db')
    yield c
    c.close()


def add(c, mid, day, event='Play_Brawl_Historic', deck='test', pd='play', result='win'):
    ts=int(datetime.combine(day,datetime.min.time()).timestamp()*1000)
    c.execute('INSERT INTO matches(match_id,start_time,event_id,my_deck_tag,play_draw,my_result,my_seat) VALUES(?,?,?,?,?,?,1)',
              (mid,ts,event,deck,pd,result))


def test_partial_replay_keeps_children(db,tmp_path):
    cfg=Config({},tmp_path)
    full=MatchRecord(match_id='m',my_seat=1,games=[GameRecord(1,play_draw='draw',result='loss')],
        commanders=[{'seat':2,'grp_id':'42','partner_idx':0}],
        mulligans=[{'game_no':1,'seat':1,'kept_on':2}])
    store.upsert_match(db,full,cfg)
    store.upsert_match(db,MatchRecord(match_id='m',games=[GameRecord(1)]),cfg)
    store.upsert_match(db,full,cfg)
    assert db.execute('SELECT COUNT(*) FROM commanders').fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM mulligans').fetchone()[0]==1
    assert db.execute('SELECT play_draw FROM games').fetchone()[0]=='draw'


@pytest.mark.parametrize('replacement',['new\n','new record much longer\n'])
def test_rotation_equal_or_larger(tmp_path,replacement):
    p=tmp_path/'log';p.write_bytes(b'old\n');w=LogWatcher(p)
    list(w.poll());p.write_bytes(replacement.encode())
    assert [r.text for r in w.poll()]==[replacement]


def test_partial_utf8_line_waits(tmp_path):
    p=tmp_path/'log';raw='中文\n'.encode();p.write_bytes(raw[:2]);w=LogWatcher(p)
    assert list(w.poll())==[]
    with p.open('ab') as f:f.write(raw[2:])
    assert [r.text for r in w.poll()]==['中文\n']


def test_daily_all_formats_and_unknowns(db):
    day=datetime.now().date()
    add(db,'a',day);add(db,'b',day,'PremierDraft_TEST',pd=None,result='loss')
    add(db,'c',day-timedelta(days=1));add(db,'d',day,result=None)
    r=daily_report(db,day.isoformat())
    assert r['summary']['n']==3 and len(r['events'])==2
    assert r['summary']['win_rate']['n']==2
    assert r['summary']['unknown_pd']==1
    assert r['summary']['unknown_result']==1
    assert r['summary']['mulligan_known']==0
    assert daily_report(db,day.isoformat(),family='轮抽')['summary']['n']==1
    assert stats.match_list(db,day=day.isoformat())['total']==3


def test_no_baseline_no_inference_and_filters(db):
    day=datetime.now().date()
    for i in range(30):
        add(db,str(i),day,pd='draw')
        db.execute('INSERT INTO commanders(match_id,seat,grp_id) VALUES(?,2,42)',(str(i),))
    add(db,'draft',day,'PremierDraft_TEST',deck='draft')
    r=stats.targeting_index(db,window_days=7,family='轮抽')
    assert r['dimensions']['play_draw']['n']==1
    r=stats.targeting_index(db,window_days=7,event='Play_Brawl_Historic',deck='test')
    assert r['dimensions']['play_draw']['n']==30
    assert r['dimensions']['matchup']['score'] is None
    assert r['dimensions']['mulligan']['score'] is None
    assert r['composite'] is None


def test_known_zero_mulligan_separate_from_unknown(db):
    day=datetime.now().date();add(db,'a',day);add(db,'b',day)
    db.execute('INSERT INTO mulligans(match_id,seat,game_no,kept_on) VALUES(?,1,1,0)',('a',))
    buckets={r['key']:r['n'] for r in stats.mulligan_stats(db)['by_mulligan']}
    assert buckets=={'clean':1,'unknown':1}
    rows=stats.match_list(db)['rows']
    assert {r['match_id']:r['my_mulls'] for r in rows}=={'a':0,'b':None}


def test_course_deck_only_associated_by_event():
    b=SessionBuilder(my_player_id=fx.ME)
    b.feed(json.dumps({'InternalEventName':'Play_Brawl_Historic','CourseDeckSummary':
        {'Name':'Example','DeckId':'sample-deck'},'CourseDeck':{
        'MainDeck':[{'cardId':1,'quantity':60}],
        'CommandZone':[{'cardId':99,'quantity':1}]}}))
    for line in fx.bo1_match_lines():b.feed(line)
    m=b.close().matches[0]
    assert m.my_deck_tag=='Example' and m.my_deck_version
    assert any(c['seat']==m.my_seat and c['grp_id']=='99' for c in m.commanders)
    b=SessionBuilder(my_player_id=fx.ME)
    b.feed(json.dumps({'DeckSummaries':[{'Name':'Wrong','DeckId':'other'}]}))
    for line in fx.bo1_match_lines():b.feed(line)
    assert b.close().matches[0].my_deck_tag is None


def encoded(numbers):
    out=bytearray()
    for n in numbers:
        while n>=128:out.append((n&127)|128);n>>=7
        out.append(n)
    return base64.urlsafe_b64encode(out).decode().rstrip('=')


def test_deckstring_metadata_and_invalid():
    # one commander and one companion; they are distinct roles, not creatures inferred from main.
    assert decode(encoded([0,4,2,100,1,20,2,0]))['commanders']==[100]
    assert decode(encoded([0,4,2,100,1,20,2,0]))['companions']==[120]
    for bad in ('?',encoded([0,9,0]),encoded([0,4,1,100]),encoded([0,4,0,99])):
        with pytest.raises(ValueError):decode(bad)


def test_enrichment_only_existing_exact_id_and_idempotent(db,tmp_path):
    cfg=Config({},tmp_path);ts=1000
    db.execute("INSERT INTO matches(match_id,source,start_time,my_result) VALUES('ut_1000_example_1','untapped',1000,'win')")
    raw={'short_id':'example-match','match_start':ts,'friendly_system_seat_id':1,
         'friendly_team_id':1,'active_player_id':1,'friendly_deck_id':'example',
         'friendly_deckstring':encoded([0,4,1,100,1,0]),
         'event_name':'Play_Brawl_Historic','games':[{'game_number':1,
         'player_opening_hands':['first','second'],'opponent_revealed_deckstrings':[encoded([0,4,1,100,1,0])]}]}
    mapping={100:{'grpid':42,'titleId':100}}
    preview=enrich(db,[raw],mapping,cfg)
    assert preview['commanders']==1 and preview['my_commanders']==1
    assert db.execute('SELECT COUNT(*) FROM commanders').fetchone()[0]==0
    enrich(db,[raw],mapping,cfg,True);enrich(db,[raw],mapping,cfg,True)
    assert db.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM commanders').fetchone()[0]==2
    assert {tuple(r) for r in db.execute('SELECT seat,grp_id FROM commanders')}=={(1,'42'),(2,'42')}
    assert db.execute('SELECT kept_on FROM mulligans').fetchone()[0]==1
    raw['match_start']=2000
    assert enrich(db,[raw],mapping,cfg,True)['skipped']==1


def test_card_id_mapping_prefers_known_and_resolves_back():
    cards=[{'grpid':42,'titleId':100},{'grpid':43,'titleId':100},
           {'grpid':44,'titleId':200,'isSecondaryCard':True,'linkedFaces':[42]}]
    m=card_mapping(cards,['43'])
    assert m[100]['grpid']==43 and m[200]['grpid']==43


def test_api_daily_and_tagging(db,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main,'_conn',db)
    client=TestClient(main.app)  # no lifespan, never starts production watcher
    assert client.get('/api/daily?day=bad').status_code==422
    assert client.get('/api/matches?day=bad').status_code==422
    assert client.get('/api/matches?limit=-1').status_code==422
    assert client.get('/api/matches?offset=-1').status_code==422
    assert client.get('/api/daily').status_code==200
    response=client.post('/api/opp_tag_by_name',params={'commander':'grpId:42','tag':'Aggro'})
    assert response.status_code==200 and response.json()['ok']
    assert db.execute('SELECT archetype_user FROM opponent_profiles').fetchone()[0]=='Aggro'
    assert client.get('/api/targeting?family=轮抽').json()['scope']['family']=='轮抽'
    client.close()


def test_comparison_requires_nonoverlapping_same_version(db):
    today = datetime.now().date()
    for old in (False, True):
        for i in range(40):
            mid = f'{old}-{i}'
            add(db, mid, today-timedelta(days=40) if old else today)
            db.execute('UPDATE matches SET my_deck_version=? WHERE match_id=?', ('v1', mid))
            db.execute('INSERT INTO mulligans(match_id,seat,game_no,kept_on) VALUES(?,1,1,?)',
                       (mid, int(i < 20)))
            db.execute('INSERT INTO commanders(match_id,seat,grp_id) VALUES(?,2,?)',
                       (mid, str(42+i%2)))
    dims = stats.targeting_index(db, window_days=7, event='Play_Brawl_Historic', deck='test')['dimensions']
    assert dims['mulligan']['enough'] and dims['mulligan']['p'] == pytest.approx(1)
    assert dims['matchup']['enough'] and dims['matchup']['p'] == pytest.approx(1)
    db.execute("UPDATE matches SET my_deck_version='v2' WHERE match_id='False-0'")
    dims = stats.targeting_index(db, window_days=7, event='Play_Brawl_Historic', deck='test')['dimensions']
    assert not dims['mulligan']['enough'] and not dims['matchup']['enough']


def test_cross_source_fingerprint_and_changes():
    from app.deck_versions import fingerprint, local_fingerprint
    cloud = {'main': [100,100,200], 'side': [300], 'commanders': [200]}
    local = {'MainDeck': [{'cardId':1,'quantity':2}], 'Sideboard':[{'cardId':3,'quantity':1}],
             'CommandZone':[{'cardId':2,'quantity':1}]}
    assert fingerprint(cloud) == local_fingerprint(local,{1:100,2:200,3:300})
    assert local_fingerprint(local,{1:100}) is None
    local['MainDeck'][0]['quantity']=3
    assert fingerprint(cloud) != local_fingerprint(local,{1:100,2:200,3:300})


def test_daily_comparison_excludes_today_future_and_other_deck(db):
    today=datetime.now().date()
    for i in range(25):
        add(db,f'old{i}',today-timedelta(days=1))
    add(db,'current',today,result='loss')
    add(db,'future',today+timedelta(days=1))
    db.execute("UPDATE matches SET my_deck_version='title-v1:test'")
    r=daily_report(db,today.isoformat())
    assert r['comparison']['covered']==1
    assert r['comparison']['groups'][0]['baseline']['n']==25
    assert r['comparison']['adjusted_delta_pp']==-100
    assert r['modes'][0]['mode']=='BO1'
    db.execute("UPDATE matches SET my_deck_version='different' WHERE match_id='current'")
    assert daily_report(db,today.isoformat())['comparison']['covered']==0


def test_modes_do_not_infer_bo1_from_single_game():
    from app.comparisons import match_mode
    assert match_mode('UnknownEvent',1)=='未知'
    assert match_mode('Traditional_Ladder',1)=='BO3'
    assert match_mode('UnknownEvent',2)=='BO3'
    assert match_mode('PremierDraft_TEST',1)=='BO1'


def test_limited_baseline_keeps_set_and_rules_separate():
    from app.comparisons import compare
    row={'event_id':'PremierDraft_TEST','match_mode':'BO1','my_result':'win'}
    history=[dict(row,my_result='loss') for _ in range(20)]
    assert compare([row],history)['covered']==1
    assert compare([dict(row,event_id='PremierDraft_OTHER')],history)['covered']==0
    assert compare([dict(row,match_mode='BO3')],history)['covered']==0


def test_daily_highlight_scope_evidence_and_empty_date(db):
    day=datetime.now().date()
    add(db,'brawl',day,pd='draw')
    add(db,'draft',day,'PremierDraft_TEST',pd='play')
    report=daily_report(db,day.isoformat(),family='轮抽')
    assert report['highlights'][0]['match_ids']==['draft']
    assert [r['match_id'] for r in report['highlight_records']]==['draft']
    assert '先手' in report['plain']
    empty=daily_report(db,(day-timedelta(days=1)).isoformat())
    assert empty['highlights']==[] and empty['highlight_records']==[]
    assert empty['latest_date']==day.isoformat()


def test_daily_streaks_history_cutoff_scope_and_bo3(db):
    day=datetime.now().date()
    add(db,'old',day-timedelta(days=1),pd='draw')
    add(db,'today',day,pd='draw')
    add(db,'future',day+timedelta(days=1),pd='draw')
    add(db,'draft',day,'PremierDraft_TEST',pd='play')
    db.execute("INSERT INTO games(match_id,game_no,play_draw) VALUES('today',1,'draw'),('today',2,'play'),('today',3,'play')")
    r=daily_report(db,day.isoformat(),event='Play_Brawl_Historic')['play_draw']
    assert r['day_streaks']['longest_draw']==1
    assert r['history_streaks']['longest_draw']==2
    assert r['history_streaks']['current_n']==2
    assert r['day']['draw_rate']==100
    assert r['day']['play']==0
    overview=stats.overview(db,event='Play_Brawl_Historic')['play_draw_rates']
    assert overview['draw']==3 and overview['draw_rate']==100
