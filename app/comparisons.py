"""Nonoverlapping, stratified personal comparisons. Never infer matchmaking intent."""
from collections import defaultdict


def match_mode(event, game_count=0):
    event = event or ''
    event_key = event.casefold()
    if (game_count > 1 or event.startswith(('Traditional', 'TradDraft_', 'Trad_'))
            or 'bestof3' in event_key):
        return 'BO3'
    if ('bestof1' in event_key or event in ('Ladder', 'Play', 'Play_Brawl_Historic')
            or event.startswith(('QuickDraft_', 'PremierDraft_', 'PickTwoDraft_'))):
        return 'BO1'
    return '未知'


def comparison_key(row):
    event = row.get('event_id') or ''
    mode = row.get('match_mode', '未知')
    if not event or mode == '未知':
        return None
    # Exact event retains set / rules / entry structure; pools naturally differ.
    if 'Draft' in event or 'Sealed' in event:
        return event, mode, 'limited'
    version = row.get('my_deck_version')
    if not version or not row.get('my_deck_tag'):
        return None
    return event, mode, row['my_deck_tag'], version


def compare(current, history, min_history=20):
    from .stats import wr, friendly_event
    groups, past = defaultdict(list), defaultdict(list)
    for row in current:
        key = comparison_key(row) or ('unknown', row.get('event_id'), row.get('match_mode'), row.get('my_deck_tag'))
        groups[key].append(row)
    for row in history:
        key = comparison_key(row)
        if key is not None:
            past[key].append(row)
    result, covered, expected, wins = [], 0, 0., 0
    for key, rows in groups.items():
        a = [r for r in rows if r['my_result'] in ('win', 'loss')]
        b = [r for r in past.get(key, []) if r['my_result'] in ('win', 'loss')]
        aw, bw = sum(r['my_result']=='win' for r in a), sum(r['my_result']=='win' for r in b)
        usable = key[0] != 'unknown' and len(b) >= min_history and bool(a)
        delta = round(100*(aw/len(a)-bw/len(b)), 1) if usable else None
        if usable:
            covered += len(a); wins += aw; expected += len(a)*bw/len(b)
        row = rows[0]
        result.append({'event': row.get('event_id'), 'label': friendly_event(row.get('event_id') or ''),
                       'mode': row.get('match_mode', '未知'), 'deck': row.get('my_deck_tag'),
                       'version': row.get('my_deck_version'), 'current': wr(aw,len(a)), 'baseline': wr(bw,len(b)),
                       'delta_pp': delta, 'usable': usable,
                       'reason': ('同赛事历史；限赛套牌不同，仅描述战绩' if key and key[-1]=='limited' else '同赛事、同名套牌、同构筑版本') if usable else
                                 ('赛事规则或套牌版本资料不足' if key[0] == 'unknown' else f'此前记录不足 {min_history} 场'),
                       'small_sample': len(a)<20})
    return {'groups': result, 'covered': covered,
            'total_decided': sum(r['my_result'] in ('win','loss') for r in current),
            'adjusted_delta_pp': round(100*(wins-expected)/covered,1) if covered else None,
            'note': '按当前对局构成加权此前胜率；只描述同范围战绩差异，不能证明原因。小样本不作长期结论。'}


def summarize_by_event(comparison):
    """Turn conservative deck/version comparisons into readable event + BO summaries.

    The raw groups remain available for audit.  This view may combine several deck
    versions within one event/mode, but only the subgroups that already passed the
    comparison rules contribute to the historical delta.
    """
    from .stats import wr

    grouped = {}
    for source in comparison.get('groups', []):
        key = (source.get('event') or '', source.get('mode') or '未知')
        target = grouped.setdefault(key, {
            'event': source.get('event') or '',
            'label': source.get('label') or source.get('event') or '赛事未记录',
            'mode': source.get('mode') or '未知',
            'current_n': 0,
            'current_wins': 0,
            'comparable_n': 0,
            'comparable_wins': 0,
            'expected_wins': 0.0,
            'baseline_n': 0,
        })
        current = source.get('current') or {}
        current_n = current.get('n') or 0
        current_wins = current.get('wins') or 0
        target['current_n'] += current_n
        target['current_wins'] += current_wins
        if source.get('usable') and current_n:
            baseline = source.get('baseline') or {}
            baseline_n = baseline.get('n') or 0
            baseline_wins = baseline.get('wins') or 0
            if baseline_n:
                target['comparable_n'] += current_n
                target['comparable_wins'] += current_wins
                target['expected_wins'] += current_n * baseline_wins / baseline_n
                target['baseline_n'] += baseline_n

    items = []
    for target in grouped.values():
        current_n = target['current_n']
        current_wins = target['current_wins']
        current = wr(current_wins, current_n)
        prefix = f"{target['label']} · {target['mode']}：当天 {current_n} 场，{current_wins} 胜 {current_n-current_wins} 负"
        comparable_n = target['comparable_n']
        if comparable_n:
            delta = round(100 * (target['comparable_wins'] - target['expected_wins']) / comparable_n, 1)
            status = 'higher' if delta >= 5 else ('lower' if delta <= -5 else 'similar')
            if status == 'higher':
                change = f"可比范围胜率比此前高 {abs(delta):g} 个百分点"
            elif status == 'lower':
                change = f"可比范围胜率比此前低 {abs(delta):g} 个百分点"
            else:
                change = f"可比范围胜率与此前接近（相差 {delta:+g} 个百分点）"
            coverage = (f"其中 {comparable_n}/{current_n} 场有足够的同范围历史"
                        if comparable_n != current_n else f"{comparable_n} 场均有足够的同范围历史")
            text = f"{prefix}；{coverage}，{change}。"
        else:
            delta = None
            status = 'no_baseline'
            text = f"{prefix}；此前没有足够的同赛事、同模式且口径相同的记录，暂不比较。"
        items.append({
            'event': target['event'], 'label': target['label'], 'mode': target['mode'],
            'current': current, 'comparable_n': comparable_n,
            'total_decided': current_n, 'baseline_n': target['baseline_n'],
            'delta_pp': delta, 'status': status, 'text': text,
            'small_sample': current_n < 20,
        })

    items.sort(key=lambda item: (-item['total_decided'], item['label'], item['mode']))
    comparable = [item for item in items if item['delta_pp'] is not None]
    if comparable:
        focus = sorted(comparable, key=lambda item: (-abs(item['delta_pp']), -item['comparable_n'], item['label']))[0]
        if focus['status'] == 'higher':
            change = f"高 {abs(focus['delta_pp']):g} 个百分点"
        elif focus['status'] == 'lower':
            change = f"低 {abs(focus['delta_pp']):g} 个百分点"
        else:
            change = f"接近此前（相差 {focus['delta_pp']:+g} 个百分点）"
        headline = f"可比范围中，{focus['label']} · {focus['mode']} 的变化最明显：{change}。"
    elif items:
        headline = f"当天有 {len(items)} 个赛事／模式组；暂无足够可比历史，以下保留当天事实。"
    else:
        headline = '当天在当前筛选下没有可比较的赛事记录。'

    return {
        'headline': headline,
        'items': items,
        'comparable_groups': len(comparable),
        'note': ('“此前 30 天”只是查找窗口，不需要使用满 30 天。轮抽、现开按同一赛事与 BO 模式比较；'
                 '构筑还要求同一套牌与同一构筑版本。差值只描述个人记录变化，不说明原因。'),
    }
