"""先后手连续记录：只统计筛选后的比赛首局，不跨越未知或顺序不明记录。"""
from collections import Counter


def distribution(rows):
    play = sum(r['play_draw'] == 'play' for r in rows)
    draw = sum(r['play_draw'] == 'draw' for r in rows)
    known = play+draw
    return {'play': play, 'draw': draw, 'unknown': len(rows)-known,
            'play_rate': round(100*play/known, 1) if known else None,
            'draw_rate': round(100*draw/known, 1) if known else None}


def streaks(rows):
    result = {'longest_play': 0, 'longest_draw': 0, 'current_side': None,
              'current_n': 0, 'last_time': None, 'reason': None, 'n': len(rows)}
    if not rows:
        result['reason'] = '无记录'
        return result
    if any(r['start_time'] is None for r in rows):
        result.update(longest_play=None, longest_draw=None, reason='有日期未知的记录，无法确认连续顺序')
        return result
    ordered = sorted(rows, key=lambda r: (r['start_time'], r['match_id']))
    counts = Counter(r['start_time'] for r in ordered)
    side, length = None, 0
    for r in ordered:
        pd = r['play_draw']
        if counts[r['start_time']] > 1 or pd not in ('play','draw'):
            side, length = None, 0
            continue
        length = length+1 if pd == side else 1
        side = pd
        result['longest_'+pd] = max(result['longest_'+pd], length)
    result.update(current_side=side, current_n=length, last_time=ordered[-1]['start_time'])
    if counts[ordered[-1]['start_time']] > 1:
        result['reason'] = '末尾记录时间相同，无法确认先后顺序'
    elif side is None:
        result['reason'] = '末场先后手未知，连续记录已打断'
    result['ambiguous_order'] = any(n>1 for n in counts.values())
    return result
