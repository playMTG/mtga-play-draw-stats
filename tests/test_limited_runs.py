# -*- coding: utf-8 -*-
"""限制赛单轮（run）切分与评语。

这组测试守的是**用户口径**（2026-09-20）：
「选两张轮抓 4 胜就是卷了，评语要给出激励；3 胜是差一把卷，可惜了；2 胜可以说回了；
真人轮抓 3 胜回了、7 胜卷了。」

注意造数据要用 `run_of('wlwww')` 这种**显式序列**：真实的一轮里负场是夹在胜场中间的
（一轮打满 7 胜就结束了，所以「7 胜 2 负」的两负必须在第 7 胜之前）。写死「先赢后输」
会造出不可能的一轮，测试就测不到真实情形。
"""
from app.daily_highlights import highlights
from app.daily_copy import TEMPLATES
from app.limited_runs import BANDS, band, best_run, spec_for, split_runs

QUICK = 'QuickDraft_MOM_20230428'
PREMIER = 'PremierDraft_DMU_20220901'
PICKTWO = 'PickTwoDraft_HOB_20260811'


def row(i, event=QUICK, result='win', deck='d1'):
    return dict(match_id=str(i), start_time=i * 1000, event_id=event, my_deck_id=deck,
                my_deck_tag='轮抽套牌', play_draw='play', my_result=result,
                commanders=[], commander_names=[], duration_sec=0)


def run_of(pattern, event=QUICK, deck='d1', start=1):
    """按 'wlwww' 造一轮：w=胜、l=负、x=结果未记录。"""
    out = []
    for k, ch in enumerate(pattern):
        result = {'w': 'win', 'l': 'loss', 'x': None}[ch]
        out.append(row(start + k, event=event, result=result, deck=deck))
    return out


def seq(rows):
    return [(r['wins'], r['losses']) for r in rows]


def from_bank(text, bank, **fmt):
    """这句评语是不是从该话术库里挑出来的（比匹配关键词更贴近要守的东西）。"""
    fmt.setdefault('losses', 0)
    fmt.setdefault('cap', 0)
    body = text.rstrip('。')
    return any(t.format(**fmt) == body for t in TEMPLATES[bank])


# ---------- 赛事规格 ----------

def test_specs_match_the_official_reward_tables():
    """上限与回本线按奖励表核验过（来源见 limited_runs 模块注释）。"""
    assert spec_for(PICKTWO).cap_wins == 4
    assert spec_for(PICKTWO).cap_losses == 2
    assert spec_for(PREMIER).cap_wins == 7
    assert spec_for(PREMIER).cap_losses == 3
    # 快速轮抽：7 胜／3 负结束，回本线是**用户口径**的 4 胜
    # （按「宝石 + 1 包 ≈ 200 宝石」折算，4 胜 ≈ 710 其实差一点点，5 胜才过线）
    assert spec_for(QUICK).cap_wins == 7
    assert spec_for(QUICK).cap_losses == 3
    assert spec_for(QUICK).break_even == 4
    assert spec_for('Sealed_DMU_20220901').label == '现开'
    assert spec_for('Trad_Sealed_ONE_20230207').label == '传统现开'
    # 标签从 event_names 派生，带系列与日期的那一截要丢掉
    assert spec_for(PICKTWO).label == '选两张轮抽'


def test_festival_events_have_no_run_model():
    """MWM／十项全能这类活动赛没有固定 run 边界，一律不评。

    本机 `MWM_OmniscienceDraft_20251223` 单个 deck 组里有 132 场、89 胜 43 负
    （能一直打），套上「7 胜 = 卷」会把活动赛误判成天天卷。
    """
    for event in ('MWM_OmniscienceDraft_20251223', 'MWM_Gold_Sealed_20240917',
                  'Decathlon2023_9_OmniDraft_20230113', 'MWM_Cube_BotDraft_20221108',
                  'Brawl_Ladder', 'Ladder', None, ''):
        assert spec_for(event) is None, event


# ---------- 档位 ----------

def test_bands_follow_the_user_definition():
    """用户口径：选二 4 卷／3 差一把／2 回了；真人轮抓 7 卷／3 回了。"""
    picktwo = spec_for(PICKTWO)
    assert [band(picktwo, w) for w in range(5)] == ['bust', 'low', 'even', 'near', 'cap']
    premier = spec_for(PREMIER)
    assert band(premier, 7) == 'cap'
    assert band(premier, 6) == 'near'
    assert band(premier, 3) == 'even'      # 3 胜回了
    assert band(premier, 2) == 'low'
    assert band(premier, 0) == 'bust'
    # 快速轮抽（用户 2026-09-20 定：4 胜就当回了）——4 与 5 都落 `even`
    quick = spec_for(QUICK)
    assert [band(quick, w) for w in range(8)] == [
        'bust', 'low', 'low', 'low', 'even', 'even', 'near', 'cap']
    # 现开回本线是 6 胜，而 6 也是「差一把卷」——按用户口径「差一把」优先
    assert band(spec_for('Sealed_DMU_20220901'), 6) == 'near'
    assert band(spec_for('TradDraft_ONE_20230207'), 3) == 'cap'


def test_every_band_has_a_template_bank():
    """档位与话术库必须一一对应：漏一个库就会静默退回空句。"""
    missing = [b for b in BANDS if f'limited_{b}' not in TEMPLATES]
    assert not missing, missing
    assert 'limited_cap_perfect' in TEMPLATES


# ---------- 切分 ----------

def test_run_ends_at_win_cap_or_loss_cap():
    # 打满 7 胜就结束（负场夹在中间），后面那一局属于下一轮
    runs = split_runs(run_of('wwlwwlwww') + run_of('wlll', start=100))
    assert seq(runs) == [(7, 2), (1, 3)]
    assert runs[0]['band'] == 'cap' and runs[0]['perfect'] is False
    # 负场吃满 3 也结束
    assert seq(split_runs(run_of('lll'))) == [(0, 3)]
    # 选两张轮抓：2 负结束、4 胜封顶
    assert seq(split_runs(run_of('lwwww', event=PICKTWO))) == [(4, 1)]
    assert split_runs(run_of('lwwww', event=PICKTWO))[0]['perfect'] is False


def test_unfinished_run_is_not_reported():
    """半途的一轮（2-1）不进评语——宁可不说，也不能把中途成绩说成一轮结果。"""
    assert split_runs(run_of('wwl')) == []
    assert split_runs(run_of('wwwwww')) == []
    # 结果未知的对局不进 run：不猜
    assert split_runs(run_of('www') + run_of('x', start=100)) == []


def test_same_event_twice_in_a_day_needs_different_decks():
    """同一赛事同一天开两轮：两轮的临时牌组不同，计数必须分开。

    关键情形是**第一轮没打完就开了第二轮**（Arena 允许）：共用计数器会把第一轮
    那 2 场胜场算到第二轮头上，「3 胜 3 负」被写成「5 胜 3 负」——一句假话。
    （两轮都打满时共用计数器看不出问题，所以造数据必须让第一轮半途而废。）
    """
    rows = run_of('ww', deck='d1') + run_of('wwlwll', deck='d2', start=100)
    assert seq(split_runs(rows)) == [(3, 3)]
    # 同一副临时牌组里连着两轮则要看上限：3 负收工后重新开始数
    rows = run_of('wlll', deck='same') + run_of('wwlwll', deck='same', start=100)
    assert seq(split_runs(rows)) == [(1, 3), (3, 3)]


def test_festival_matches_do_not_break_a_standard_run():
    rows = run_of('wwwww', start=1)
    rows.append(row(50, event='MWM_Gold_Sealed_20240917', result='loss'))
    rows += run_of('ww', start=60)
    assert seq(split_runs(rows)) == [(7, 0)]


# ---------- 挑哪一轮 ----------

def test_best_run_prefers_the_better_band():
    """回归：`rank` 第一版返回 `BANDS.index`，`max` 于是挑中「没回本」那一轮。

    实测表现是「当天有一轮 7-2 卷了，评语却写 3 胜没够本」。
    """
    rows = run_of('wwlwlll', deck='d1') + run_of('wwlwwlwww', deck='d2', start=100)
    runs = split_runs(rows)
    assert seq(runs) == [(3, 3), (7, 2)]
    best = best_run(runs)
    assert (best['wins'], best['band']) == (7, 'cap')
    # 档位相同时取胜场多的
    rows = run_of('wwlwlll', deck='d1') + run_of('wwlwwlwl', deck='d2', start=100)
    assert seq(split_runs(rows)) == [(3, 3), (5, 3)]
    assert best_run(split_runs(rows))['wins'] == 5


# ---------- 接进今日评语 ----------

def test_limited_run_becomes_a_highlight_with_the_right_wins():
    """评语里的胜场必须与它引用的那一轮一致（用户最容易被写错的地方）。"""
    rows = run_of('lwwww', event=PICKTWO)      # 4 胜 1 负 = 卷了
    facts = highlights(rows)
    limited = [f for f in facts if f['kind'] == 'limited_run']
    assert len(limited) == 1, facts
    fact = limited[0]
    assert fact['band'] == 'cap'
    assert fact['level'] == 'legendary'
    assert from_bank(fact['text'], 'limited_cap', event='选两张轮抽', wins=4)
    assert fact['match_ids'] == [r['match_id'] for r in rows]


def test_near_band_reads_as_a_pity_loss():
    rows = run_of('wwlwl', event=PICKTWO)      # 3 胜 2 负 = 差一把卷
    fact = [f for f in highlights(rows) if f['kind'] == 'limited_run'][0]
    assert fact['band'] == 'near'
    assert from_bank(fact['text'], 'limited_near', event='选两张轮抽', wins=3)


def test_even_band_says_it_broke_even():
    rows = run_of('wwll', event=PICKTWO)       # 2 胜 2 负 = 回了
    fact = [f for f in highlights(rows) if f['kind'] == 'limited_run'][0]
    assert fact['band'] == 'even'
    assert from_bank(fact['text'], 'limited_even', event='选两张轮抽', wins=2)


def test_limited_fact_coexists_with_the_win_rate_fact():
    """限制赛单轮自成一个主题：它和「今天手热」不是同一件事，可以同时出现。"""
    rows = run_of('lwwww', event=PICKTWO)
    rows += [row(200 + i, event='Brawl_Ladder') for i in range(2)]
    facts = highlights(rows)
    kinds = [f['kind'] for f in facts]
    assert kinds[0] == 'limited_run', kinds
    assert len(facts) == 2 and kinds[1] != 'limited_run', kinds


def test_context_runs_win_over_day_only_slicing():
    """跨天的一轮：昨天开、今天收。

    当天那几行只看到 1 场，切不出完整一轮；`context['limited_runs']` 里
    （由 `insights.daily_report` 用全量记录切好）才有正确的那一轮。
    """
    day_rows = [row(1, event=PREMIER, deck='d9'), row(2, event=PREMIER, deck='d9')]
    # 只看当天：2 胜 0 负，切不出完整的一轮
    assert [f for f in highlights(day_rows) if f['kind'] == 'limited_run'] == []
    # 带上跨天的那一轮：7 胜 2 负 = 卷了
    run = split_runs(run_of('wwlwwlwww', event=PREMIER, deck='d9'))[0]
    facts = highlights(day_rows, context={'limited_runs': [run]})
    limited = [f for f in facts if f['kind'] == 'limited_run']
    assert len(limited) == 1
    assert '7' in limited[0]['text']


def test_festival_day_gets_no_limited_fact():
    rows = [row(i, event='MWM_OmniscienceDraft_20251223') for i in range(1, 12)]
    assert [f for f in highlights(rows) if f['kind'] == 'limited_run'] == []
