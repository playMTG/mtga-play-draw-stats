from app.play_draw import distribution, streaks


def rows(values):
    return [dict(match_id=str(i),start_time=i,play_draw=v) for i,v in enumerate(values)]


def test_streaks_reset_on_unknown_and_switch():
    r=streaks(rows(['play','play',None,'play','draw','draw','draw']))
    assert r['longest_play']==2 and r['longest_draw']==3
    assert (r['current_side'],r['current_n'])==('draw',3)


def test_unknown_tail_is_not_current_streak():
    r=streaks(rows(['draw','draw',None]))
    assert r['longest_draw']==2 and r['current_side'] is None and r['current_n']==0


def test_empty_all_unknown_and_distribution():
    assert streaks([])['reason']=='无记录'
    assert streaks(rows([None,None]))['longest_play']==0
    assert distribution(rows([None]))['play_rate'] is None
    d=distribution(rows(['play','draw','draw',None]))
    assert d==dict(play=1,draw=2,unknown=1,play_rate=33.3,draw_rate=66.7)


def test_order_is_chronological_and_ties_break():
    rs=rows(['draw','draw','draw','draw'])
    rs[2]['start_time']=1
    r=streaks(list(reversed(rs)))
    assert r['longest_draw']==1 and r['current_n']==1
    assert r['ambiguous_order']
    rs[-1]['start_time']=1
    assert streaks(rs)['current_side'] is None


def test_missing_time_does_not_bridge_unknown_position():
    rs=rows(['play','play']);rs[0]['start_time']=None
    r=streaks(rs)
    assert r['longest_play'] is None and r['current_side'] is None
