"""全赛制本地战报。未知字段不当作零，比较窗口与历史基线不重叠。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math
import sqlite3

from .event_names import friendly_event
from .card_names import CardNames

from .targeting import binom_cdf, chi2_sf, max_loss_streak, p_to_score


def records(conn, exclude_abnormal=True, exclude_bot=True, event=None, deck=None,
            family=None, mode=None, deck_id=None):
    from .stats import _filters
    conds, args = _filters(conn, event, deck, family, mode, deck_id=deck_id)
    if exclude_abnormal:
        conds.append("is_abnormal=0")
    if exclude_bot:
        conds.append("is_bot=0")
    where = " AND ".join(conds) or "1=1"
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM matches WHERE {where} ORDER BY start_time,match_id", args)]
    # 一次读取子表，避免每场一次 SQL。以 seat 判断我方和对手。
    mulls, cmdrs = {}, {}
    from .comparisons import match_mode
    for r in conn.execute("SELECT match_id,seat,kept_on FROM mulligans WHERE kept_on IS NOT NULL"):
        mulls.setdefault(r['match_id'], []).append(dict(r))
    names = CardNames(conn)
    for r in conn.execute("SELECT match_id,seat,grp_id FROM commanders"):
        cmdrs.setdefault(r['match_id'], []).append(dict(r))
    for r in rows:
        r['event_label'] = friendly_event(r['event_id'])
        r['match_mode'] = r.get('match_mode') or match_mode(r['event_id'], 0)
        mine = [m['kept_on'] for m in mulls.get(r['match_id'], [])
                if m['seat'] is None or m['seat'] == r['my_seat']]
        r['mulligan'] = any(x > 0 for x in mine) if mine else None
        r['commanders'] = sorted({str(c['grp_id']) for c in cmdrs.get(r['match_id'], [])
                                  if r['my_seat'] is not None and c['seat'] is not None
                                  and c['seat'] != r['my_seat']})
        if 'Brawl' not in (r['event_id'] or ''):
            r['commanders'] = []
        r['commander_cards'] = [names.get(g) for g in r['commanders']]
        r['commander_names'] = [c['name'] for c in r['commander_cards']]
    return rows


def aggregate(rows):
    from .stats import wr
    decided = [r for r in rows if r['my_result'] in ('win', 'loss')]
    play = sum(r['play_draw'] == 'play' for r in rows)
    draw = sum(r['play_draw'] == 'draw' for r in rows)
    cmdrs = Counter()
    card_info = {}
    for r in rows:
        cmdrs.update(set(r['commanders']))
        card_info.update({g: {'key':g, 'name':n} for g,n in zip(r['commanders'],r['commander_names'])})
        card_info.update({c['key']:c for c in r.get('commander_cards',[])})
    eligible = [r for r in rows if 'Brawl' in (r['event_id'] or '')]
    return {
        'n': len(rows), 'wins': sum(r['my_result'] == 'win' for r in rows),
        'losses': sum(r['my_result'] == 'loss' for r in rows),
        'unknown_result': len(rows) - len(decided),
        'win_rate': wr(sum(r['my_result'] == 'win' for r in decided), len(decided)),
        'play': play, 'draw': draw, 'unknown_pd': len(rows) - play - draw,
        'play_rate': wr(play, play + draw),
        'mulligan_known': sum(r['mulligan'] is not None for r in rows),
        'mulligan_yes': sum(r['mulligan'] is True for r in rows),
        'deck_known': sum(bool(r['my_deck_tag']) for r in rows),
        'commander_eligible': len(eligible),
        'commander_known': sum(bool(r['commanders']) for r in eligible),
        'distinct_commanders': len(cmdrs),
        'top_commanders': [
            {**card_info[k], 'n': n}
            for k, n in cmdrs.most_common(5)
            if n >= 3  # V0：仅重复遭遇（≥3 场）才进「常遇主将」
        ],
        'duration_known': sum(r['duration_sec'] is not None for r in rows),
        'duration_sec': sum(r['duration_sec'] or 0 for r in rows),
        'max_loss_streak': max_loss_streak([r['my_result'] for r in rows]),
    }


def history_context(dated, chosen):
    """当天**之前**的历史上下文（今日评价 v2 的「个人相关度」要用）。

    用户口径（2026-09-15）：「重新规划一下这个评价体系」。旧版 `highlights(rows)` 只拿
    得到当天的行，所以永远说不出「这是你第 N 场」「这个对手你之前一直输」这类话——
    而这类话恰恰是玩家最想看的。

    只读已经加载好的全量 `dated`（`records()` 本来就返回全量），所以**不需要新增
    持久化状态、也不需要额外查询**。

    返回：
    - `total_before`：当天之前的对局总数（里程碑用）；
    - `opponents`：对手名 -> (之前的胜, 之前的负)（复仇／苦主用）；
    - `commanders`：主将 grpId -> 之前最后一次遇到的毫秒时间戳（久违的主将用）。
    """
    before = [r for r in dated
              if datetime.fromtimestamp(r['start_time'] / 1000).date() < chosen]
    opponents: dict[str, tuple[int, int]] = {}
    commanders: dict[str, int] = {}
    for r in before:
        name = (r.get('opponent_name') or '').strip()
        # 只算真人：与「反复遇到的对手」同口径，教学局 AI 不进历史战绩
        if name and not r.get('is_bot') and 'BotMatch' not in (r.get('event_id') or ''):
            wins, losses = opponents.get(name, (0, 0))
            opponents[name] = (wins + (r['my_result'] == 'win'),
                               losses + (r['my_result'] == 'loss'))
        for gid in (r.get('commanders') or []):
            commanders[gid] = max(commanders.get(gid, 0), r['start_time'])
    return {"total_before": len(before), "opponents": opponents,
            "commanders": commanders}


def daily_report(conn, day=None, exclude_abnormal=True, exclude_bot=True,
                 event=None, deck=None, family=None, mode=None, deck_id=None):
    from .stats import event_family, friendly_event, is_constructed_opponent_event
    today = datetime.now().date()
    chosen = datetime.strptime(day, '%Y-%m-%d').date() if day else today
    rows = records(conn, exclude_abnormal, exclude_bot, event, deck, family, mode, deck_id)
    dated = [r for r in rows if r['start_time'] is not None]
    dates = Counter(datetime.fromtimestamp(r['start_time']/1000).date().isoformat() for r in dated)
    selected = [r for r in dated if datetime.fromtimestamp(r['start_time']/1000).date() == chosen]
    summary = aggregate(selected)
    groups = []
    for ev in sorted({r['event_id'] or '' for r in selected}):
        group = [r for r in selected if (r['event_id'] or '') == ev]
        groups.append({'event': ev, 'label': friendly_event(ev), 'family': event_family(ev),
                       **aggregate(group)})
    from .comparisons import compare, summarize_by_event
    history = [r for r in dated if chosen-timedelta(days=30) <= datetime.fromtimestamp(r['start_time']/1000).date() < chosen]
    comparison = compare(selected, history)
    history_summary = summarize_by_event(comparison)
    modes = [{'mode': mode, **aggregate([r for r in selected if r['match_mode']==mode])}
             for mode in ('BO1','BO3','未知') if any(r['match_mode']==mode for r in selected)]
    comparison['baseline_window'] = '所选日期之前 30 个自然日（不含当天）'
    constructed = [r for r in selected if is_constructed_opponent_event(r['event_id'])]
    tags = Counter(r['opp_archetype_tag'] for r in constructed if r.get('opp_archetype_tag'))
    from .daily_highlights import highlights
    from .limited_runs import split_runs
    # 限制赛单轮结果（「这轮轮抓卷了／差一把／回本」）按**这一轮打完的那天**归日：
    # 昨天开、今天收的一轮算今天打完的，所以切分用全量 `dated` 而不是当天那几行。
    # 只跑一次（1 万行切分是毫秒级），不新增持久化状态——与 `history_context` 同一思路。
    runs_by_day = defaultdict(list)
    for run in split_runs(dated):
        runs_by_day[datetime.fromtimestamp(run['end_time']/1000).date()].append(run)
    # 新鲜度降权（今日评价 v2，见 DESIGN.md）：把最近 7 天的对局重算一遍候选，
    # 统计各 kind 出现过几次，交给选材引擎降权——这是治「天天同一句」的关键。
    # 不需要新增持久化状态，7 天的行本来就在 `dated` 里。
    recent_kinds = Counter()
    for offset in range(1, 8):
        back = chosen - timedelta(days=offset)
        day_rows = [r for r in dated
                    if datetime.fromtimestamp(r['start_time']/1000).date() == back]
        for f in highlights(day_rows, context={'limited_runs': runs_by_day.get(back, [])}):
            recent_kinds[f['kind']] += 1
    facts = highlights(selected, recent_kinds,
                       {**history_context(dated, chosen),
                        'limited_runs': runs_by_day.get(chosen, [])})
    evidence_ids = {mid for fact in facts for mid in fact['match_ids']}
    from .play_draw import distribution, streaks
    # 查看历史日期时不得泄露之后的连续纪录；日期未知不能擅自放到最前面。
    through_day = [r for r in rows if r['start_time'] is None or datetime.fromtimestamp(r['start_time']/1000).date() <= chosen]
    return {'date': chosen.isoformat(), 'is_today': chosen == today,
            'play_draw': {'day': distribution(selected), 'day_streaks': streaks(selected),
                          'history_streaks': streaks(through_day)},
            'summary': summary,
            # 有对局但没有亮点时留空：旧版会补一句「已记录 N 场，X 胜 Y 负」，
            # 而那个数字下方统计卡已逐项列出（用户反馈为无意义复读）。
            'plain': ' '.join(f['text'] for f in facts) if facts
                     else ('这一天在当前筛选下没有已记录对局。' if not selected else ''),
            'events': groups,
            'highlights': facts,
            'highlight_records': [{k: r[k] for k in ('match_id','start_time','event_id','event_label','my_deck_tag','play_draw','my_result','commander_names','commander_cards')} for r in selected if r['match_id'] in evidence_ids],
            'latest_date': max((d for d in dates if d <= today.isoformat()), default=None),
            'comparison': comparison, 'history_summary': history_summary, 'modes': modes,
            'opponent_types': {'known': sum(tags.values()), 'total': len(constructed),
                               'unknown': len(constructed)-sum(tags.values()), 'rows': dict(tags)},
            'dates': [{'date': k, 'n': dates[k]} for k in sorted(dates, reverse=True)],
            'unknown_date': len(rows)-len(dated),
            'scope': {'event': event, 'deck': deck, 'family': family, 'mode': mode}}


def _dimension(label, n, plain, min_n, p=None):
    enough = n >= min_n and p is not None
    score = p_to_score(p) if enough else None
    return {'label': label, 'n': n, 'min_sample': min_n, 'plain': plain,
            'enough': enough, 'p': p, 'score': score,
            'verdict': ('未见明显偏离' if p >= .05 else '偏差值得观察') if enough else None}


def _two_sample(a, n, b, m):
    """两组二分类同质性检验；期望频数不足时不输出近似 p 值。"""
    if not n or not m:
        return None
    pooled = (a+b)/(n+m)
    if min(n*pooled,n*(1-pooled),m*pooled,m*(1-pooled)) < 5:
        return None
    z = (a/n-b/m)/math.sqrt(pooled*(1-pooled)*(1/n+1/m))
    return chi2_sf(z*z,1)


def targeting(conn, cfg=None, window_days=30, exclude_abnormal=True, exclude_bot=True,
              root=None, event=None, deck=None, family=None, mode=None, deck_id=None):
    from .stats import _ti_cfg
    min_n = int(_ti_cfg(cfg)['min_sample'])
    rows = records(conn, exclude_abnormal, exclude_bot, event, deck, family, mode, deck_id)
    now = datetime.now()
    # 包含今天的 N 个本地自然日；未知时间不能偷偷落入最近窗口。
    start = datetime.combine(now.date()-timedelta(days=window_days-1), datetime.min.time()) if window_days else None
    cutoff = int(start.timestamp()*1000) if start else None
    current = [r for r in rows if cutoff is None or (r['start_time'] is not None and r['start_time'] >= cutoff)]
    baseline = [r for r in rows if cutoff is not None and r['start_time'] is not None and r['start_time'] < cutoff]
    s = aggregate(current)
    n = s['play']+s['draw']
    p = min(1.,2*binom_cdf(min(s['play'],s['draw']),n,.5)) if n else None
    dims = {'play_draw': _dimension('先后手分布', n,
        f"先手 {s['play']}/{n} 场，后手 {s['draw']} 场，未知 {s['unknown_pd']} 场。"
        "与各占一半的简单模型作双侧比较；偏离不代表平台针对。", min_n, p)}
    # 同一赛事（保留 BO1/BO3 边界）、明确套牌且版本一致才推断。
    versions = {r.get('my_deck_version') for r in current+baseline}
    comparable = bool(event and deck and len(versions) == 1 and None not in versions)
    known = [r for r in current if r['mulligan'] is not None]
    base = [r for r in baseline if r['mulligan'] is not None]
    mu_p = _two_sample(sum(r['mulligan'] for r in known),len(known),
                       sum(r['mulligan'] for r in base),len(base)) if comparable and len(base)>=min_n else None
    reason = "需要选择同一赛事和套牌，且具备一致的套牌版本及足够的此前基线。"
    dims['mulligan'] = _dimension('调度记录',len(known),
        f"有记录 {len(known)} 场，其中 {s['mulligan_yes']} 场调度；未知 {s['n']-len(known)} 场。"
        + (f"此前可比记录 {len(base)} 场；主动留牌策略也会影响调度。" if mu_p is not None else reason),min_n,mu_p)
    recent_cmd = Counter(tuple(r['commanders']) for r in current if r['commanders'])
    old_cmd = Counter(tuple(r['commanders']) for r in baseline if r['commanders'])
    cn,bn = sum(recent_cmd.values()),sum(old_cmd.values())
    match_p = None
    if comparable and cn>=min_n and bn>=min_n:
        stat = 0.; valid = True
        keys = set(recent_cmd)|set(old_cmd)
        for k in keys:
            total = recent_cmd[k]+old_cmd[k]
            ex,eb = total*cn/(cn+bn),total*bn/(cn+bn)
            if min(ex,eb)<5:
                valid=False;break
            stat += (recent_cmd[k]-ex)**2/ex+(old_cmd[k]-eb)**2/eb
        if valid and len(keys)>1:
            match_p=chi2_sf(stat,len(keys)-1)
    dims['matchup'] = _dimension('对手主将',cn,
        f"当前 {cn} 场含主将资料，此前 {bn} 场。"+
        ("比较主将构成变化，不代表难度或匹配意图。" if match_p is not None else
         "无足够可比基线或类别样本不足；非主将赛制不适用此维度。"),min_n,match_p)
    dims['streak'] = _dimension('连续战绩', s['n'],
        f"当前窗口最长 {s['max_loss_streak']} 连败。混合对局和自身胜率不能证明连败异常，仅作描述。",min_n)
    opponents, opponent_names = {}, {}
    for r in current:
        if r['my_result'] not in ('win','loss'):
            continue
        for gid, name in zip(r['commanders'], r['commander_names']):
            count, wins = opponents.get(gid,(0,0))
            opponents[gid]=(count+1,wins+(r['my_result']=='win'))
            opponent_names[gid] = name
    nemeses = [{'key':gid,'name':opponent_names[gid],'n':count,'wr':round(100*wins/count,1),'archetype':'未分类'}
               for gid,(count,wins) in opponents.items() if count>=3 and wins/count<.4]
    nemeses.sort(key=lambda r:(r['wr'],-r['n']))
    # 不再用任意权重混合不同统计检验；保留接口字段兼容旧客户端。
    from .comparisons import compare
    return {'window_days': window_days, 'dimensions': dims, 'composite': None,
            'comparison': compare(current, baseline, min_n),
            'label': '分项观察', 'min_sample': min_n, 'nemeses': nemeses[:5],
            'summary': s, 'scope': {'event':event,'deck':deck,'family':family,'mode':mode},
            'disclaimer': '本地统计描述波动，不能判定平台意图。多次查看和比较容易偶遇小 p 值；调度与对手分析需要可比历史。'}
