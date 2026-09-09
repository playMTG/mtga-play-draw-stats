"""当天事实评语：固定优先级，不依赖历史，不评价平台意图或玩家技术。"""
from collections import defaultdict


def highlights(rows):
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (r['start_time'], r['match_id']))
    n = len(rows)
    wins = sum(r['my_result'] == 'win' for r in rows)
    losses = sum(r['my_result'] == 'loss' for r in rows)
    unknown = n-wins-losses
    result = f"这一天已记录 {n} 场，{wins} 胜 {losses} 负"
    if unknown:
        result += f"，{unknown} 场结果待确认"
    candidates = []

    def add(kind, text, evidence, denominator):
        candidates.append({'kind': kind, 'text': text+'。', 'n': len(evidence),
                           'denominator': denominator, 'match_ids': [r['match_id'] for r in evidence]})

    known = [r for r in rows if r['play_draw'] in ('play', 'draw')]
    # 优先级：单场描述 → 全同先后手 → 重复主将 → 第四胜 → 后手胜场 → 普通战绩。
    if n == 1:
        pd = {'play': '先手', 'draw': '后手'}.get(rows[0]['play_draw'], '先后手未记录')
        add('single', result+f"，{pd}", rows, n)
        return candidates
    if len(known) >= 3 and len({r['play_draw'] for r in known}) == 1:
        pd = '先手' if known[0]['play_draw'] == 'play' else '后手'
        text = (f"这一天已记录的 {n} 场全部{pd}" if len(known)==n else
                f"这一天 {n} 场中，{len(known)} 场已知记录均为{pd}，另 {n-len(known)} 场未记录先后手")
        add('same_pd', text, known, n)
    eligible = [r for r in rows if 'Brawl' in (r['event_id'] or '')]
    identified = [r for r in eligible if r['commanders']]
    opponents, names = defaultdict(list), {}
    for r in identified:
        for gid, name in zip(r['commanders'], r['commander_names']):
            if not opponents[gid] or opponents[gid][-1]['match_id'] != r['match_id']:
                opponents[gid].append(r)
            names[gid] = name
    if opponents:
        gid = min(opponents, key=lambda g: (-len(opponents[g]), str(g)))
        group = opponents[gid]
        if len(group) >= 3:
            w = sum(r['my_result']=='win' for r in group)
            l = sum(r['my_result']=='loss' for r in group)
            text = f"{len(identified)} 场主将资料已知的争锋对局中，{len(group)} 场遇到 {names[gid]}，交手 {w} 胜 {l} 负"
            if len(group)-w-l:
                text += f"，{len(group)-w-l} 场结果待确认"
            if len(eligible)>len(identified):
                text += f"；另有 {len(eligible)-len(identified)} 场争锋缺少主将资料"
            add('repeat_commander', text, group, len(identified))
    if wins >= 4:
        count = 0
        for i, r in enumerate(rows):
            count += r['my_result']=='win'
            if count == 4:
                add('four_wins', f"记录中的第 4 胜出现在当天第 {i+1} 场；当前 {wins} 胜 {losses} 负"+
                    (f"，另 {unknown} 场结果待确认" if unknown else ''), rows, n)
                break
    draw = [r for r in rows if r['play_draw']=='draw']
    draw_wins = [r for r in draw if r['my_result']=='win']
    if draw_wins:
        add('draw_wins', f"这一天 {len(draw)} 场已知后手对局中，赢下了 {len(draw_wins)} 场", draw, len(draw))
    add('results', result, rows, n)
    # 主将亮点与当天战绩配对，避免两条都只是局部描述。
    if candidates[0]['kind'] == 'repeat_commander':
        return [candidates[0], candidates[-1]]
    return candidates[:2]
