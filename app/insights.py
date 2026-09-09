"""全赛制本地战报。未知字段不当作零，比较窗口与历史基线不重叠。"""
from collections import Counter
from datetime import datetime, timedelta
import math
import sqlite3

from .event_names import friendly_event
from .card_names import CardNames

from .targeting import binom_cdf, chi2_sf, max_loss_streak, p_to_score


def records(conn, exclude_abnormal=True, exclude_bot=True, event=None, deck=None, family=None):
    from .stats import _filters
    conds, args = _filters(conn, event, deck, family)
    if exclude_abnormal:
        conds.append("is_abnormal=0")
    if exclude_bot:
        conds.append("is_bot=0")
    where = " AND ".join(conds) or "1=1"
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM matches WHERE {where} ORDER BY start_time,match_id", args)]
    # 一次读取子表，避免每场一次 SQL。以 seat 判断我方和对手。
    mulls, cmdrs = {}, {}
    game_counts = dict(conn.execute('SELECT match_id, COUNT(*) FROM games GROUP BY match_id'))
    from .comparisons import match_mode
    for r in conn.execute("SELECT match_id,seat,kept_on FROM mulligans WHERE kept_on IS NOT NULL"):
        mulls.setdefault(r['match_id'], []).append(dict(r))
    names = CardNames(conn)
    for r in conn.execute("SELECT match_id,seat,grp_id FROM commanders"):
        cmdrs.setdefault(r['match_id'], []).append(dict(r))
    for r in rows:
        r['event_label'] = friendly_event(r['event_id'])
        r['match_mode'] = match_mode(r['event_id'], game_counts.get(r['match_id'], 0))
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
        'top_commanders': [{**card_info[k], 'n': n} for k, n in cmdrs.most_common(5)],
        'duration_known': sum(r['duration_sec'] is not None for r in rows),
        'duration_sec': sum(r['duration_sec'] or 0 for r in rows),
        'max_loss_streak': max_loss_streak([r['my_result'] for r in rows]),
    }


def daily_report(conn, day=None, exclude_abnormal=True, exclude_bot=True,
                 event=None, deck=None, family=None):
    from .stats import event_family, friendly_event
    today = datetime.now().date()
    chosen = datetime.strptime(day, '%Y-%m-%d').date() if day else today
    rows = records(conn, exclude_abnormal, exclude_bot, event, deck, family)
    dated = [r for r in rows if r['start_time'] is not None]
    dates = Counter(datetime.fromtimestamp(r['start_time']/1000).date().isoformat() for r in dated)
    selected = [r for r in dated if datetime.fromtimestamp(r['start_time']/1000).date() == chosen]
    summary = aggregate(selected)
    groups = []
    for ev in sorted({r['event_id'] or '' for r in selected}):
        group = [r for r in selected if (r['event_id'] or '') == ev]
        groups.append({'event': ev, 'label': friendly_event(ev), 'family': event_family(ev),
                       **aggregate(group)})
    from .comparisons import compare
    history = [r for r in dated if chosen-timedelta(days=30) <= datetime.fromtimestamp(r['start_time']/1000).date() < chosen]
    comparison = compare(selected, history)
    modes = [{'mode': mode, **aggregate([r for r in selected if r['match_mode']==mode])}
             for mode in ('BO1','BO3','未知') if any(r['match_mode']==mode for r in selected)]
    comparison['baseline_window'] = '所选日期之前 30 个自然日（不含当天）'
    non_command = [r for r in selected if 'Brawl' not in (r['event_id'] or '')]
    tags = Counter(r['opp_archetype_tag'] for r in non_command if r.get('opp_archetype_tag'))
    from .daily_highlights import highlights
    facts = highlights(selected)
    evidence_ids = {mid for fact in facts for mid in fact['match_ids']}
    from .play_draw import distribution, streaks
    # 查看历史日期时不得泄露之后的连续纪录；日期未知不能擅自放到最前面。
    through_day = [r for r in rows if r['start_time'] is None or datetime.fromtimestamp(r['start_time']/1000).date() <= chosen]
    return {'date': chosen.isoformat(), 'is_today': chosen == today,
            'play_draw': {'day': distribution(selected), 'day_streaks': streaks(selected),
                          'history_streaks': streaks(through_day)},
            'summary': summary, 'plain': ' '.join(f['text'] for f in facts) if facts else '这一天在当前筛选下没有已记录对局。', 'events': groups,
            'highlights': facts,
            'highlight_records': [{k: r[k] for k in ('match_id','start_time','event_id','event_label','my_deck_tag','play_draw','my_result','commander_names','commander_cards')} for r in selected if r['match_id'] in evidence_ids],
            'latest_date': max((d for d in dates if d <= today.isoformat()), default=None),
            'comparison': comparison, 'modes': modes,
            'opponent_types': {'known': sum(tags.values()), 'total': len(non_command), 'rows': dict(tags)},
            'dates': [{'date': k, 'n': dates[k]} for k in sorted(dates, reverse=True)],
            'unknown_date': len(rows)-len(dated),
            'scope': {'event': event, 'deck': deck, 'family': family}}


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
              root=None, event=None, deck=None, family=None):
    from .stats import _ti_cfg
    min_n = int(_ti_cfg(cfg)['min_sample'])
    rows = records(conn, exclude_abnormal, exclude_bot, event, deck, family)
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
            'summary': s, 'scope': {'event':event,'deck':deck,'family':family},
            'disclaimer': '本地统计描述波动，不能判定平台意图。多次查看和比较容易偶遇小 p 值；调度与对手分析需要可比历史。'}
