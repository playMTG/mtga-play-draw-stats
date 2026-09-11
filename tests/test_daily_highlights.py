from app.daily_highlights import highlights


def row(i, pd='play', result='win', commander=None, event='Play_Brawl_Historic'):
    return dict(match_id=str(i),start_time=i,event_id=event,my_deck_tag='example',
                play_draw=pd,my_result=result,commanders=[commander] if commander else [],
                commander_names=[commander] if commander else [])


def test_empty_and_single():
    assert highlights([])==[]
    facts=highlights([row(1,pd=None,result=None)])
    assert len(facts)==1 and '结果待确认' in facts[0]['text']
    assert '先后手未记录' in facts[0]['text']
    assert facts[0]['match_ids']==['1']


def test_seven_all_play_or_draw():
    for pd, word in [('play','先手'),('draw','后手')]:
        facts=highlights([row(i,pd=pd) for i in range(7)])
        assert facts[0]['kind']=='play_draw_streak'
        assert f'7 场全部{word}' in facts[0]['text']
        assert f'连续 7 把{word}' in facts[0]['text']
        assert facts[0]['level']=='legendary'
        assert facts[0]['probability']['scan_percent']==0.78
        assert facts[0]['n']==facts[0]['denominator']==7
        assert len(facts)<=2


def test_unknown_never_becomes_all_play():
    facts=highlights([row(i,pd='play' if i<4 else None) for i in range(7)])
    assert '4 场已知记录连成连续 4 把先手' in facts[0]['text']
    assert '另 3 场先后手未记录' in facts[0]['text']
    assert '7 场全部先手' not in facts[0]['text']
    assert facts[0]['n']==4 and facts[0]['denominator']==7


def test_three_draws_are_evaluated_even_when_not_all_matches_are_draws():
    rows=[row(0,pd='play'),row(1,pd='draw'),row(2,pd='draw'),row(3,pd='draw'),row(4,pd='play')]
    fact=highlights(rows)[0]
    assert fact['kind']=='play_draw_streak'
    assert '连续 3 把后手' in fact['text']
    assert fact['match_ids']==['1','2','3']
    assert fact['probability']['scan_percent']==25.0


def test_repeated_commander_with_record():
    rows=[row(i,pd='play' if i%2 else 'draw',result='loss' if i==4 else 'win',
              commander='A' if i<3 else 'B') for i in range(5)]
    facts=highlights(rows)
    assert facts[0]['kind']=='repeat_commander'
    assert '3 场遇到 A' in facts[0]['text'] and '3 胜 0 负' in facts[0]['text']
    assert '4 胜 1 负' in facts[1]['text']
    assert facts[0]['match_ids']==['0','1','2']


def test_mixed_formats_and_same_name_do_not_inflate():
    rows=[row(i,pd='draw' if i%2 else 'play',commander='A') for i in range(3)]
    rows += [row(3,pd='draw',commander='A',event='PremierDraft_TEST'),row(4,commander=None)]
    fact=highlights(rows)[0]
    assert fact['kind']=='repeat_commander'
    assert fact['n']==3 and fact['denominator']==3
    assert '另有 1 场争锋' in fact['text']


def test_fourth_win_is_recorded_order_not_reward_claim():
    rows=[row(i,pd='play' if i%2 else 'draw',result='loss' if i==0 else 'win') for i in range(5)]
    facts=highlights(list(reversed(rows)))
    assert facts[0]['kind']=='four_wins'
    assert '第 5 场' in facts[0]['text']
    assert '任务' not in facts[0]['text']
    assert facts[0]['match_ids']==['0','1','2','3','4']


def test_no_highlight_still_has_summary():
    facts=highlights([row(i,pd=None,result='loss') for i in range(4)])
    assert facts[0]['kind']=='results'
    assert '0 胜 4 负' in facts[0]['text']


def test_fourth_win_evidence_includes_later_results():
    rows=[row(i,pd='play' if i%2 else 'draw',result='loss' if i==5 else 'win') for i in range(6)]
    fact=highlights(rows)[0]
    assert fact['kind']=='four_wins'
    assert '5 胜 1 负' in fact['text']
    assert fact['match_ids']==[str(i) for i in range(6)]
