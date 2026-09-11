from app.daily_copy import TEMPLATES, pick
from app.daily_highlights import highlights


def row(i, pd='play', result='win', commander=None, event='Play_Brawl_Historic'):
    return dict(match_id=str(i),start_time=i,event_id=event,my_deck_tag='example',
                play_draw=pd,my_result=result,commanders=[commander] if commander else [],
                commander_names=[commander] if commander else [], duration_sec=0)


def test_marathon_day_beats_ordinary_streak():
    """27 场：亮点是场次，不是三连先手或五五开胜率。"""
    rows = []
    for i in range(27):
        # 14 胜 13 负 ≈ 51.9%，先后手交错，中间夹一段 3 先手
        pd = 'draw' if i in (5, 6, 7) else ('play' if i % 2 else 'draw')
        result = 'win' if i % 2 == 0 else 'loss'
        rows.append(row(i, pd=pd, result=result))
    facts = highlights(rows)
    kinds = [f['kind'] for f in facts]
    assert 'volume' in kinds
    assert facts[0]['kind'] == 'volume'
    text = ' '.join(f['text'] for f in facts)
    assert '27' in text
    assert '3 连' not in text and '三连' not in text


def test_marathon_with_legendary_streak_keeps_both():
    rows = [row(i, pd='draw', result='win') for i in range(20)]
    facts = highlights(rows)
    kinds = {f['kind'] for f in facts}
    assert 'volume' in kinds
    # 20 连后手会 legendary，可与耐力局并列
    assert 'play_draw_streak' in kinds or 'hot_wr' in kinds


def test_empty_and_single_unknown_keeps_fallback():
    assert highlights([]) == []
    facts = highlights([row(1, pd=None, result=None)])
    assert len(facts) == 1
    assert facts[0]['kind'] == 'single'
    # 主句来自话术库或战绩兜底，都可回查 match_ids
    assert facts[0]['match_ids'] == ['1']


def test_seven_all_draw_is_legendary_tone():
    facts = highlights([row(i, pd='draw') for i in range(7)])
    streak = next(f for f in facts if f['kind'] == 'play_draw_streak')
    assert streak['level'] == 'legendary'
    assert '7' in streak['text'] or '连' in streak['text']
    # 少用纯感叹词
    assert '卧槽' not in streak['text'] and '哇' not in streak['text']
    assert '太美' not in streak['text']


def test_hot_wr_no_lab_numbers():
    rows = [row(i, pd='play' if i % 2 else 'draw', result='loss' if i == 4 else 'win') for i in range(5)]
    facts = highlights(rows)
    assert facts[0]['kind'] == 'hot_wr'
    assert '4 胜' not in facts[0]['text']
    assert '%' not in facts[0]['text']


def test_repeat_commander_is_banter():
    rows = [row(i, pd='play' if i % 2 else 'draw', commander='A' if i < 3 else 'B') for i in range(5)]
    facts = highlights(rows)
    rep = next(f for f in facts if f['kind'] == 'repeat_commander')
    assert 'A' in rep['text']
    assert any(w in rep['text'] for w in ('缘分', '又', '老朋友', '孽缘', '怎么又是'))


def test_repeat_requires_three():
    rows = [row(i, pd='play' if i % 2 else 'draw', commander='A' if i < 2 else f'C{i}') for i in range(4)]
    assert all(f['kind'] != 'repeat_commander' for f in highlights(rows))


def test_pick_is_stable_per_seed():
    a = pick('hot_wr', ['m1', 'm2'])
    b = pick('hot_wr', ['m1', 'm2'])
    assert a == b and a


def test_templates_have_no_meimei_typo():
    blob = repr(TEMPLATES)
    assert '太美了' not in blob
    assert 'volume_marathon' in TEMPLATES
