from app.play_draw import distribution, streaks


def rows(values, results=None):
    """results 缺省全胜，这样旧用例不必改；要测胜率时显式传。"""
    rs = [dict(match_id=str(i), start_time=i, play_draw=v) for i, v in enumerate(values)]
    for i, r in enumerate(rs):
        r['my_result'] = (results[i] if results else 'win')
    return rs


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
    assert d==dict(play=1,draw=2,unknown=1,play_rate=33.3,draw_rate=66.7,
                   play_wr=dict(wins=1,n=1,wr=100.0),
                   draw_wr=dict(wins=2,n=2,wr=100.0))


def test_distribution_win_rate_by_side():
    """先后手各自的胜率（2026-09-15 用户要求卡片上同时给出）。

    分母只算**有胜负**的对局：未结算的结果不能算成输，也不能把「先后手未知」的
    对局算进任何一侧。先后手未知的那些场次因此不出现在两个分母里。
    """
    d = distribution(rows(['play','play','draw','draw','draw',None],
                          results=['win','loss','win','loss','loss',None]))
    assert d['play_wr']==dict(wins=1,n=2,wr=50.0)
    assert d['draw_wr']==dict(wins=1,n=3,wr=33.3)
    # 只有先后手已知、且结果已结算的对局才进分母
    assert d['play_wr']['n']+d['draw_wr']['n']==5
    # 某一边没有样本时给 None，不编 0%
    empty = distribution(rows(['play','play']))
    assert empty['draw_wr']==dict(wins=0,n=0,wr=None)
    # 结果未结算时不进分母
    pending = distribution(rows(['play','play'], results=[None,'win']))
    assert pending['play_wr']==dict(wins=1,n=1,wr=100.0)


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
