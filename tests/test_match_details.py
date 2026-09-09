import sqlite3

from app import stats, store


def test_match_details_separate_my_and_opponent_commanders(tmp_path):
    conn = store.connect(tmp_path / 'matches.db')
    conn.execute("ATTACH DATABASE ':memory:' AS cards_db")
    conn.execute('CREATE TABLE cards_db.cards(grp_id TEXT,name TEXT,name_zh TEXT)')
    conn.executemany('INSERT INTO cards_db.cards VALUES(?,?,?)', [
        ('10','My Commander','我的主将'), ('20','Opponent Commander','对手主将')])
    conn.execute("""INSERT INTO matches(
        match_id,source,event_id,start_time,my_seat,my_deck_tag,my_deck_id,
        my_deck_version,my_result,play_draw,end_reason,total_turns,duration_sec)
        VALUES('known','log','Play_Brawl_Historic',2,1,'我的套牌','deck-1',
               'version-1','win','play','Concede',8,120)""")
    conn.executemany('INSERT INTO commanders(match_id,seat,grp_id) VALUES(?,?,?)', [
        ('known',1,'10'), ('known',2,'20')])
    conn.execute("""INSERT INTO matches(
        match_id,source,event_id,start_time,my_seat,my_deck_tag,my_result)
        VALUES('unknown','untapped','Play_Brawl_Historic',1,1,
               '名字里写着我的主将','loss')""")
    conn.execute("""INSERT INTO matches(
        match_id,source,event_id,start_time,my_seat,my_deck_tag,my_result)
        VALUES('not-brawl','log','MWM_Momir_20260908',3,1,'莫米','win')""")
    conn.executemany('INSERT INTO commanders(match_id,seat,grp_id) VALUES(?,?,?)', [
        ('not-brawl',1,'10'), ('not-brawl',2,'20')])
    conn.commit()

    rows = {row['match_id']: row for row in stats.match_list(
        conn, exclude_abnormal=False, exclude_bot=False)['rows']}
    assert rows['known']['my_cards'][0]['key'] == '10'
    assert rows['known']['opp_cards'][0]['key'] == '20'
    assert rows['known']['my_cmdrs'] == ['我的主将']
    assert rows['unknown']['my_cards'] == []
    assert rows['unknown']['my_cmdrs'] == []  # deck label is never an identity source
    assert rows['not-brawl']['my_cmdrs'] == []
    assert rows['not-brawl']['opp_cmdrs'] == []  # command-zone objects outside Brawl are not commanders
    assert rows['known']['my_deck_id'] == 'deck-1'

    headers, exported = stats.export_rows(
        conn, 'matches', exclude_abnormal=False, exclude_bot=False)
    my_index = headers.index('我方主将')
    by_id = {row[0]: row for row in exported}
    assert by_id['known'][my_index] == '我的主将'
    assert by_id['unknown'][my_index] == ''
    assert by_id['not-brawl'][my_index] == ''
    assert by_id['not-brawl'][headers.index('对手主将')] == ''
    conn.close()
