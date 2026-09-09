"""Nonoverlapping, stratified personal comparisons. Never infer matchmaking intent."""
from collections import defaultdict


def match_mode(event, game_count=0):
    event = event or ''
    if game_count > 1 or event.startswith(('Traditional', 'TradDraft_', 'Trad_')):
        return 'BO3'
    if event in ('Ladder', 'Play', 'Play_Brawl_Historic') or event.startswith(('QuickDraft_', 'PremierDraft_', 'PickTwoDraft_')):
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
