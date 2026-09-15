from app.daily_copy import TEMPLATES, pick
from app.daily_highlights import highlights


def row(i, pd='play', result='win', commander=None, event='Play_Brawl_Historic'):
    return dict(match_id=str(i),start_time=i,event_id=event,my_deck_tag='example',
                play_draw=pd,my_result=result,commanders=[commander] if commander else [],
                commander_names=[commander] if commander else [], duration_sec=0)


def test_marathon_day_beats_ordinary_streak():
    """27 场：只有场次够格，三连先手与五五开胜率都不算亮点。"""
    rows = []
    for i in range(27):
        # 14 胜 13 负 ≈ 51.9%，先后手交错，中间夹一段 3 先手
        pd = 'draw' if i in (5, 6, 7) else ('play' if i % 2 else 'draw')
        result = 'win' if i % 2 == 0 else 'loss'
        rows.append(row(i, pd=pd, result=result))
    facts = highlights(rows)
    kinds = [f['kind'] for f in facts]
    assert 'volume' in kinds
    text = ' '.join(f['text'] for f in facts)
    assert '27' in text
    assert '3 连' not in text and '三连' not in text


def test_volume_never_leads_when_a_real_signal_exists():
    """场次是背景板，不能排在真亮点前面（2026-09-14 用户反馈）。

    以前场次排第一，于是打得越多评语越单调——22 局的日子若没有离谱级连续，
    其余信号全被丢掉，最后只剩一句「今天打了很久」。
    """
    rows = [row(i, pd='draw', result='win') for i in range(20)]
    facts = highlights(rows)
    assert facts, '20 场全胜全后手必须有话可说'
    assert facts[0]['kind'] != 'volume', [f['kind'] for f in facts]
    # 两个真亮点足够占满名额时，场次可以被挤掉——它不该抢真事实的位置
    assert {'hot_wr', 'play_draw_streak'} <= {f['kind'] for f in facts}


def test_long_day_with_only_scattered_repeat_still_gets_two_lines():
    """用户原场景：22 场、没有离谱级连续，但一天里遇到同一个人 3 次。

    旧实现按占比（3/22 = 13.7% < 45%）把这个信号丢掉，于是整天只剩
    「22 场打满」一条。现在重复主将按**绝对次数**保留，评语变成两条，
    且真事实在前、场次在后。
    """
    rows = []
    for i in range(22):
        cmd = '阿耶尼' if i in (3, 9, 16) else f'对手{i}'
        pd = 'play' if i % 3 else 'draw'
        result = 'win' if i % 2 else 'loss'   # 11 胜 11 负，够不到高胜率
        rows.append(row(i, pd=pd, result=result, commander=cmd))
    facts = highlights(rows)
    kinds = [f['kind'] for f in facts]
    assert len(facts) == 2, kinds
    assert kinds[0] == 'repeat_commander', kinds
    assert kinds[1] == 'volume', kinds
    assert '阿耶尼' in facts[0]['text']
    assert '22' in facts[1]['text']


def test_empty_and_single_unknown_keeps_fallback():
    assert highlights([]) == []
    facts = highlights([row(1, pd=None, result=None)])
    assert len(facts) == 1
    assert facts[0]['kind'] == 'single'
    # 主句来自话术库或战绩兜底，都可回查 match_ids
    assert facts[0]['match_ids'] == ['1']


def test_no_strong_signal_returns_empty():
    """有对局但没有值得一提的信号时返回空列表。

    7 场 4 胜 3 负、先后手交错：够不到高胜率（4/7≈57%，要 ≥70%）、够不到场次门槛
    （<10）、没有先后手偏斜、没有连续段、没有重复主将。旧版在这里会补一句
    「这一天已记录 7 场，4 胜 3 负」——那是下方统计卡已经逐项列过的数字（用户反馈）。
    """
    rows = [row(i, pd='play' if i % 2 == 0 else 'draw',
                result='win' if i % 2 == 0 else 'loss') for i in range(7)]
    assert highlights(rows) == []


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
    """零散遇到三次（中间夹着别人）：保持原来的轻说法，不升级。"""
    rows = [row(0, pd='play', result='win', commander='A'),
            row(1, pd='draw', result='loss', commander='B'),
            row(2, pd='play', result='win', commander='A'),
            row(3, pd='draw', result='loss', commander='B'),
            row(4, pd='play', result='win', commander='A')]
    facts = highlights(rows)
    rep = next(f for f in facts if f['kind'] == 'repeat_commander')
    assert 'A' in rep['text']
    assert rep['n'] == 3
    assert 'streak' not in rep
    assert any(w in rep['text'] for w in ('缘分', '又', '老朋友', '孽缘', '怎么又是'))


def test_consecutive_repeat_commander_is_extreme():
    """连续三把都是同一个人：说法要更重，证据只挂连着的这三场。"""
    rows = [row(0, pd='play', result='win', commander='阿耶尼'),
            row(1, pd='draw', result='loss', commander='阿耶尼'),
            row(2, pd='play', result='win', commander='阿耶尼')]
    rep = next(f for f in highlights(rows) if f['kind'] == 'repeat_commander')
    assert rep['streak'] == 3
    assert rep['level'] == 'legendary'
    assert rep['n'] == 3
    assert rep['match_ids'] == ['0', '1', '2']
    assert '阿耶尼' in rep['text'] and '3' in rep['text']
    # 三连不能还落回「零散遇到」那批轻说法
    mild = [t.format(n=3, name='阿耶尼') for t in TEMPLATES['repeat_commander']]
    assert rep['text'].rstrip('。') not in mild


def test_streak_templates_are_separate_from_mild():
    """连击话术必须与「零散遇到」的轻说法分开，不能共用同一批句子。"""
    assert TEMPLATES['repeat_commander_streak']
    assert not set(TEMPLATES['repeat_commander_streak']) & set(TEMPLATES['repeat_commander'])


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


# ---------- 今日评价 v2 选材引擎（2026-09-15） ----------
# 设计见 docs/DESIGN.md「今日评价 v2 规划」。旧版用固定优先级表挑前两条，
# 结果是「天天同一句」+「两句互不相干」。新版按戏剧分选材、按主题去重。


def test_volume_never_leads_when_anything_else_exists():
    """场次永远排最后——它在顶部统计卡里已经有了，评语不该花一格复述它。

    这是**硬规则**，不交给戏剧分：volume 的 level 是 legendary，加成 1.4 倍会
    把「一天里遇到同一个人 3 次」压下去（实测过）。
    """
    rows = []
    for i in range(22):
        cmd = '阿耶尼' if i in (3, 9, 16) else f'对手{i}'
        rows.append(row(i, pd='play' if i % 3 else 'draw',
                        result='win' if i % 2 else 'loss', commander=cmd))
    facts = highlights(rows)
    assert facts[0]['kind'] != 'volume', [f['kind'] for f in facts]
    assert 'repeat_commander' in {f['kind'] for f in facts}


def test_freshness_demotes_but_does_not_erase():
    """新鲜度只降权，不能把事实整条抹掉（2026-09-14 实测踩过）。

    那天「一天里遇到同一个人 3 次」因为在最近 7 天说过而被降权，第一版把惩罚做成
    1/(1+次数)（连续 7 天就是 1/8），结果它掉到阈值以下、评语退化成只剩一句
    「22 场连轴转」——正好退回用户上次抱怨的状态。现在封顶 2.5 倍，
    并且它必须仍然出现在评语里。
    """
    rows = []
    for i in range(22):
        cmd = '阿耶尼' if i in (3, 9, 16) else f'对手{i}'
        rows.append(row(i, pd='play' if i % 3 else 'draw',
                        result='win' if i % 2 else 'loss', commander=cmd))
    fresh = {'repeat_commander': 3, 'volume': 3, 'blitz': 2}
    facts = highlights(rows, fresh)
    kinds = {f['kind'] for f in facts}
    assert 'repeat_commander' in kinds, f'降权不该让真事实消失：{kinds}'
    # 降权确实起了作用：没降权时它当开场
    assert highlights(rows)[0]['kind'] == 'repeat_commander'


def test_theme_dedup_keeps_two_facts_about_different_things():
    """同一主题的两条不该同时出现，不同主题的必须都能出现。

    最初把「胜率」和「先后手连击」都归进同一个 luck 主题，结果 20 场全胜全后手
    只剩一条；细分后（result / side）两条都在。
    """
    rows = [row(i, pd='draw', result='win') for i in range(20)]
    kinds = {f['kind'] for f in highlights(rows)}
    assert {'hot_wr', 'play_draw_streak'} <= kinds, kinds


def test_arc_comeback_and_collapse():
    """当天走势：先连输后连赢 = 回魂（更重）；先连赢后连输 = 崩盘。"""
    come = ([row(i, pd='play', result='loss') for i in range(3)]
            + [row(i, pd='draw', result='win') for i in range(3, 9)])
    arc = next(f for f in highlights(come) if f['kind'] == 'arc')
    assert arc['level'] == 'legendary' and arc['first'] == 3 and arc['last'] == 6

    fall = ([row(i, pd='play', result='win') for i in range(3)]
            + [row(i, pd='draw', result='loss') for i in range(3, 9)])
    arc2 = next(f for f in highlights(fall) if f['kind'] == 'arc')
    assert arc2['level'] == 'rare' and arc2['first'] == 3 and arc2['last'] == 6

    # 两段都不到 3 场不算「走势」，只是普通波动
    wobble = [row(i, pd='play', result='win' if i % 3 else 'loss') for i in range(9)]
    assert all(f['kind'] != 'arc' for f in highlights(wobble))


def test_blitz_needs_three_quick_games():
    """3 场一分钟内结束才算闪电局；时长为 0（未记录）不算。

    用例刻意让胜负交错——全胜的日子 hot_wr 与先后手连击会占满两格，
    闪电局挤不进去（那样测的就不是闪电局本身了）。
    """
    quick = [dict(row(i, result='win' if i % 2 else 'loss'), duration_sec=30)
             for i in range(6)]
    assert any(f['kind'] == 'blitz' for f in highlights(quick))
    # 两场不够
    assert all(f['kind'] != 'blitz' for f in highlights(quick[:2]))
    # 时长为 0 = 未记录，不能当成「闪电局」
    zero = [dict(row(i, result='win' if i % 2 else 'loss'), duration_sec=0)
            for i in range(6)]
    assert all(f['kind'] != 'blitz' for f in highlights(zero))


def test_assemble_forces_volume_last_even_when_it_scores_higher():
    """直接测 `_assemble`：场次的分**更高**时也必须排最后。

    上面那条端到端用例其实守不住这条规则——本机权重下场次的分本来就不高，
    去掉「强制最后」它照样通过（实测过）。所以这里用手造候选直接钉住规则本身：
    场次的 `level=legendary` 有 1.4 倍加成，分确实高于一个被降权过的闪电局。
    """
    from app.daily_highlights import _assemble, _drama

    volume = {"kind": "volume", "text": "24 场", "n": 24, "denominator": 24,
              "match_ids": [], "level": "legendary"}
    blitz = {"kind": "blitz", "text": "闪电局", "n": 3, "denominator": 24,
             "match_ids": []}
    fresh = {"blitz": 3}   # 最近 7 天说过 3 次 → 降权
    assert _drama(volume, 24, fresh) > _drama(blitz, 24, fresh), "前提不成立"
    assert _assemble([volume, blitz], 24, fresh)[0]["kind"] == "blitz"
    # 只有场次可说的日子，它照样当开场（不是被删掉）
    assert [c["kind"] for c in _assemble([volume], 24, fresh)] == ["volume"]


def test_assemble_forces_volume_last_even_when_it_scores_higher():
    """直接测 `_assemble`：场次的分**更高**时也必须排最后。

    上面那条端到端用例其实守不住这条规则——本机权重下场次的分本来就不高，
    去掉「强制最后」它照样通过（实测过）。所以这里用手造候选直接钉住规则本身：
    场次的 `level=legendary` 有 1.4 倍加成，分确实高于一个被降权过的闪电局。
    """
    from app.daily_highlights import _assemble, _drama

    volume = {"kind": "volume", "text": "24 场", "n": 24, "denominator": 24,
              "match_ids": [], "level": "legendary"}
    blitz = {"kind": "blitz", "text": "闪电局", "n": 3, "denominator": 24,
             "match_ids": []}
    fresh = {"blitz": 3}   # 最近 7 天说过 3 次 → 降权
    assert _drama(volume, 24, fresh) > _drama(blitz, 24, fresh), "前提不成立"
    assert _assemble([volume, blitz], 24, fresh)[0]["kind"] == "blitz"
    # 只有场次可说的日子，它照样当开场（不是被删掉）
    assert [c["kind"] for c in _assemble([volume], 24, fresh)] == ["volume"]


# ---------- 需要历史上下文的类别（里程碑／复仇／苦主） ----------


def test_milestone_fires_only_when_the_day_crosses_a_round_number():
    """里程碑只在当天的对局**跨过**整数关口时出现——天天报就没人当回事了。"""
    rows = [row(i) for i in range(4)]
    hit = highlights(rows, context={"total_before": 98})    # 98 -> 102，跨过 100
    ms = next(f for f in hit if f['kind'] == 'milestone')
    assert ms['level'] == 'legendary' and '100' in ms['text']
    # 没跨关口：103 -> 107 不含任何关口，不该出现
    # （注意 99 -> 103 **是**跨过 100 的，选例子时踩过这个坑）
    assert all(f['kind'] != 'milestone'
               for f in highlights(rows, context={"total_before": 103}))
    # 没有上下文时也不能崩，只是不出里程碑
    assert all(f['kind'] != 'milestone' for f in highlights(rows))


def test_revenge_needs_a_losing_record_and_a_win_today():
    """复仇 = 之前交手明显劣势（负 ≥2 且负 > 胜），今天赢了。"""
    # 必须 ≥2 场：单场走的是 `if n == 1` 的 early-return 分支，测不到这些类别
    def pair(result):
        rs = [row(0, result=result), row(1, result='loss' if result == 'win' else 'win')]
        rs[0]['opponent_name'] = '宿敌'
        rs[1]['opponent_name'] = '路人'
        return rs

    rows = pair('win')
    ctx = {"opponents": {"宿敌": (0, 3)}}
    rep = next(f for f in highlights(rows, context=ctx) if f['kind'] == 'revenge')
    assert '宿敌' in rep['text'] and rep['n'] == 1

    # 今天输给同一个人的话不是复仇（那是苦主）
    assert all(f['kind'] != 'revenge' for f in highlights(pair('loss'), context=ctx))

    # 之前交手占优（胜多于负）不算「旧账」
    ahead = pair('win')
    assert all(f['kind'] != 'revenge'
               for f in highlights(ahead, context={"opponents": {"宿敌": (3, 1)}}))
    # 只输过 1 次也不够
    assert all(f['kind'] != 'revenge'
               for f in highlights(ahead, context={"opponents": {"宿敌": (0, 1)}}))


def test_nemesis_needs_never_beaten():
    """苦主 = 从没赢过的对手（负 ≥3、胜 0），今天又输了。"""
    rows = [row(0, result='loss'), row(1, result='win')]
    rows[0]['opponent_name'] = '克星'
    rows[1]['opponent_name'] = '路人'
    nem = next(f for f in highlights(rows, context={"opponents": {"克星": (0, 4)}})
               if f['kind'] == 'nemesis')
    assert '克星' in nem['text']
    # 赢过 1 次就不算「从没赢过」
    assert all(f['kind'] != 'nemesis'
               for f in highlights(rows, context={"opponents": {"克星": (1, 4)}}))
    # 只输 2 次不够
    assert all(f['kind'] != 'nemesis'
               for f in highlights(rows, context={"opponents": {"克星": (0, 2)}}))


def test_history_context_excludes_ai_opponents():
    """历史战绩只算真人——教学局的 AI 对手不进「复仇／苦主」的分母。

    与「反复遇到的对手」同口径：`is_bot`（按自己套牌名打的标记）与 `AIBotMatch`
    （教学局，Sparky 那类）都要排除。
    """
    from datetime import date
    from app.insights import history_context

    def m(i, name, result, bot=0, event='Play_Brawl_Historic'):
        return dict(match_id=str(i), start_time=i, opponent_name=name,
                    my_result=result, is_bot=bot, event_id=event, commanders=[])

    dated = [m(0, '真人', 'loss'), m(1, '真人', 'loss'),
             m(2, 'Sparky', 'loss', event='AIBotMatch'),
             m(3, 'BotFarm', 'loss', bot=1)]
    ctx = history_context(dated, date(1970, 1, 2))
    assert ctx['total_before'] == 4
    assert ctx['opponents'] == {'真人': (0, 2)}, ctx['opponents']


# ---------- 需要历史上下文的类别（里程碑／复仇／苦主） ----------


def test_milestone_fires_only_when_the_day_crosses_a_round_number():
    """里程碑只在当天的对局**跨过**整数关口时出现——天天报就没人当回事了。"""
    rows = [row(i) for i in range(4)]
    hit = highlights(rows, context={"total_before": 98})    # 98 -> 102，跨过 100
    ms = next(f for f in hit if f['kind'] == 'milestone')
    assert ms['level'] == 'legendary' and '100' in ms['text']
    # 没跨关口：103 -> 107 不含任何关口，不该出现
    # （注意 99 -> 103 **是**跨过 100 的，选例子时踩过这个坑）
    assert all(f['kind'] != 'milestone'
               for f in highlights(rows, context={"total_before": 103}))
    # 没有上下文时也不能崩，只是不出里程碑
    assert all(f['kind'] != 'milestone' for f in highlights(rows))


def test_revenge_needs_a_losing_record_and_a_win_today():
    """复仇 = 之前交手明显劣势（负 ≥2 且负 > 胜），今天赢了。"""
    # 必须 ≥2 场：单场走的是 `if n == 1` 的 early-return 分支，测不到这些类别
    def pair(result):
        rs = [row(0, result=result), row(1, result='loss' if result == 'win' else 'win')]
        rs[0]['opponent_name'] = '宿敌'
        rs[1]['opponent_name'] = '路人'
        return rs

    rows = pair('win')
    ctx = {"opponents": {"宿敌": (0, 3)}}
    rep = next(f for f in highlights(rows, context=ctx) if f['kind'] == 'revenge')
    assert '宿敌' in rep['text'] and rep['n'] == 1

    # 今天输给同一个人的话不是复仇（那是苦主）
    assert all(f['kind'] != 'revenge' for f in highlights(pair('loss'), context=ctx))

    # 之前交手占优（胜多于负）不算「旧账」
    ahead = pair('win')
    assert all(f['kind'] != 'revenge'
               for f in highlights(ahead, context={"opponents": {"宿敌": (3, 1)}}))
    # 只输过 1 次也不够
    assert all(f['kind'] != 'revenge'
               for f in highlights(ahead, context={"opponents": {"宿敌": (0, 1)}}))


def test_nemesis_needs_never_beaten():
    """苦主 = 从没赢过的对手（负 ≥3、胜 0），今天又输了。"""
    rows = [row(0, result='loss'), row(1, result='win')]
    rows[0]['opponent_name'] = '克星'
    rows[1]['opponent_name'] = '路人'
    nem = next(f for f in highlights(rows, context={"opponents": {"克星": (0, 4)}})
               if f['kind'] == 'nemesis')
    assert '克星' in nem['text']
    # 赢过 1 次就不算「从没赢过」
    assert all(f['kind'] != 'nemesis'
               for f in highlights(rows, context={"opponents": {"克星": (1, 4)}}))
    # 只输 2 次不够
    assert all(f['kind'] != 'nemesis'
               for f in highlights(rows, context={"opponents": {"克星": (0, 2)}}))


def test_history_context_excludes_ai_opponents():
    """历史战绩只算真人——教学局的 AI 对手不进「复仇／苦主」的分母。

    与「反复遇到的对手」同口径：`is_bot`（按自己套牌名打的标记）与 `AIBotMatch`
    （教学局，Sparky 那类）都要排除。
    """
    from datetime import date
    from app.insights import history_context

    def m(i, name, result, bot=0, event='Play_Brawl_Historic'):
        return dict(match_id=str(i), start_time=i, opponent_name=name,
                    my_result=result, is_bot=bot, event_id=event, commanders=[])

    dated = [m(0, '真人', 'loss'), m(1, '真人', 'loss'),
             m(2, 'Sparky', 'loss', event='AIBotMatch'),
             m(3, 'BotFarm', 'loss', bot=1)]
    ctx = history_context(dated, date(1970, 1, 2))
    assert ctx['total_before'] == 4
    assert ctx['opponents'] == {'真人': (0, 2)}, ctx['opponents']


def test_rare_commander_needs_a_long_absence_and_a_prior_meeting():
    """久违的主将 = **见过**、但隔了很久没再遇到。

    实测（全历史 882 天）≥180 天会触发 45 天 = 5%，稀有度合适。
    关键区分：**从没见过的**是「首次相遇」不是「久违」——`context["commanders"]`
    里没有该 grpId 时必须不出这条，否则新系列一上市就会天天报。
    """
    DAY = 86_400_000

    def rows_at(day_index, cmdr):
        rs = [row(0, result='win'), row(1, result='loss')]
        for i, r in enumerate(rs):
            r['start_time'] = day_index * DAY + i
            r['commanders'] = [cmdr]
            r['commander_names'] = ['测试主将']
        return rs

    # 200 天没见 -> 触发，且达到 legendary 的门槛是 365 天，所以这里是 rare
    facts = highlights(rows_at(200, 'g1'), context={"commanders": {"g1": 0}})
    rc = next(f for f in facts if f['kind'] == 'rare_commander')
    assert rc['level'] == 'rare' and rc['days'] == 200 and '测试主将' in rc['text']

    # 400 天没见 -> legendary
    rc2 = next(f for f in highlights(rows_at(400, 'g1'), context={"commanders": {"g1": 0}})
               if f['kind'] == 'rare_commander')
    assert rc2['level'] == 'legendary' and rc2['days'] == 400

    # 179 天不够
    assert all(f['kind'] != 'rare_commander'
               for f in highlights(rows_at(179, 'g1'), context={"commanders": {"g1": 0}}))
    # 从没见过 -> 不是「久违」（首见是另一回事，本项刻意不报）
    assert all(f['kind'] != 'rare_commander'
               for f in highlights(rows_at(999, 'g-new'), context={"commanders": {"g1": 0}}))
    # 没有上下文时不能崩，只是不出这条
    assert all(f['kind'] != 'rare_commander' for f in highlights(rows_at(999, 'g1')))


def test_rare_commander_needs_a_long_absence_and_a_prior_meeting():
    """久违的主将 = **见过**、但隔了很久没再遇到。

    实测（全历史 882 天）≥180 天会触发 45 天 = 5%，稀有度合适。
    关键区分：**从没见过的**是「首次相遇」不是「久违」——`context["commanders"]`
    里没有该 grpId 时必须不出这条，否则新系列一上市就会天天报。
    """
    DAY = 86_400_000

    def rows_at(day_index, cmdr):
        rs = [row(0, result='win'), row(1, result='loss')]
        for i, r in enumerate(rs):
            r['start_time'] = day_index * DAY + i
            r['commanders'] = [cmdr]
            r['commander_names'] = ['测试主将']
        return rs

    # 200 天没见 -> 触发，且达到 legendary 的门槛是 365 天，所以这里是 rare
    facts = highlights(rows_at(200, 'g1'), context={"commanders": {"g1": 0}})
    rc = next(f for f in facts if f['kind'] == 'rare_commander')
    assert rc['level'] == 'rare' and rc['days'] == 200 and '测试主将' in rc['text']

    # 400 天没见 -> legendary
    rc2 = next(f for f in highlights(rows_at(400, 'g1'), context={"commanders": {"g1": 0}})
               if f['kind'] == 'rare_commander')
    assert rc2['level'] == 'legendary' and rc2['days'] == 400

    # 179 天不够
    assert all(f['kind'] != 'rare_commander'
               for f in highlights(rows_at(179, 'g1'), context={"commanders": {"g1": 0}}))
    # 从没见过 -> 不是「久违」（首见是另一回事，本项刻意不报）
    assert all(f['kind'] != 'rare_commander'
               for f in highlights(rows_at(999, 'g-new'), context={"commanders": {"g1": 0}}))
    # 没有上下文时不能崩，只是不出这条
    assert all(f['kind'] != 'rare_commander' for f in highlights(rows_at(999, 'g1')))
