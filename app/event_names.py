"""Display-only event names. Never use translated labels as statistical keys."""
import json
import re
from functools import lru_cache
from pathlib import Path

OVERRIDES_PATH = Path(__file__).resolve().parent.parent / 'data' / 'event_names.zh.json'

# Project descriptive translations; set names with verified sources are documented.
SETS = {
    'DMU': '多明纳里亚：众志成城', 'MOM': '邪军压境',
    'MID': '依尼翠：黯夜猎踪', 'VOW': '依尼翠：腥红婚誓',
    'NEO': '神河：霓朝纪', 'ELD': '艾卓王权',
    'BLB': '斑隆洛', 'OTJ': '光雷驿镖客',
    'DSK': '暮悲邸：鬼屋惊魂', 'SNC': '新卡佩纳：喧嚣黑街',
    'BRO': '兄弟之战', 'ONE': '非瑞克西亚：万界归一',
    'STX': '斯翠海文', 'LCI': '依夏兰迷窟', 'MKM': '卡洛夫庄园谋杀案',
}
EXACT = {
    'Ladder': '标准排位', 'Traditional_Ladder': '传统标准排位',
    'Play': '标准自由对战', 'Play_Brawl_Historic': '史迹争锋（非排位）',
    'Play_Brawl': '标准争锋（非排位）',
    'AIBotMatch': '机器人练习', 'DualColorPrecons': '双色预组套牌对战',
    'Constructed_BestOf3': '传统构筑赛（BO3）',
    'DirectGameTournamentMode': '直接挑战（比赛模式）',
    'DirectGameTournamentExplorer': '直接挑战（探险）',
}
FORMATS = {'Standard':'标准', 'Historic':'史迹', 'Explorer':'探险',
           'Timeless':'无境', 'Alchemy':'炼金', 'Pioneer':'先驱'}
PREFIXES = {
    'PremierDraft_':'优选轮抽', 'QuickDraft_':'快速轮抽',
    'PickTwoDraft_':'选两张轮抽', 'TradDraft_':'传统轮抽',
    'TraditionalDraft_':'传统轮抽', 'ContenderDraft_':'竞争者轮抽',
    'Trad_Sealed_':'传统现开', 'TraditionalSealed_':'传统现开', 'Sealed_':'现开',
    'MWM_':'每周魔法', 'Festival_':'节庆活动', 'Jump_In_':'Jump In／跳入对战',
    'Brawl_Challenge_':'争锋挑战赛', 'CompCons_Metagame_Challenge_':'构筑环境挑战赛',
    'Constructed_Event_':'标准构筑赛', 'Traditional_Cons_Event_':'传统标准构筑赛',
    'Yargle_Day_':'亚格勒日', 'AlchemyPrecons_':'炼金预组套牌对战',
    'AlchemyRebalanceEvent_':'炼金调整活动', 'AlchemyWelcome_':'炼金入门活动',
    'Constructed_':'构筑活动',
}
TERMS = {
    **FORMATS, 'Brawl':'争锋', 'BrawlBuilder':'争锋构筑', 'Momir':'莫米',
    'OmniscienceDraft':'全知轮抽', 'Omniscience':'全知', 'Artisan':'工匠',
    'Pauper':'纯普', 'HistoricPauper':'史迹纯普', 'StandardPauper':'标准纯普',
    'HistoricArtisan':'史迹工匠', 'ArtisanBrawl':'工匠争锋', 'CascadeBrawl':'倾曳争锋',
    'HistoricBrawl':'史迹争锋', 'HistoricShakeup':'史迹变局',
    'StandardShakeup':'标准变局', 'Singleton':'单卡', 'HistoricSingletonAA':'史迹单卡全卡开放',
    'AllAccess':'全卡开放', 'BotDraft':'机器人轮抽', 'Sealed':'现开',
    'Cube':'万智牌轮抽盒', 'Cascade':'倾曳', 'JumpIn':'Jump In／跳入对战',
    'AlchemyPrecons':'炼金预组套牌', 'ChallengerDecks':'挑战者套牌',
    'FutureAlchemy':'未来炼金', 'PioneerLegal':'先驱合法牌',
    'SlowStart':'缓慢开局', 'SlowStartStandard':'标准缓慢开局',
    'SlowStartAlchemy':'炼金缓慢开局', '3Sets':'三系列构筑',
    'RuleOfLaw':'法治', 'Storydecks':'故事套牌', 'AprilFools':'愚人节',
    'TradDraft':'传统轮抽', 'TradExplorer':'传统探险', 'OmniDraft':'全知轮抽',
}


@lru_cache(maxsize=4)
def _read_overrides(path, stamp):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return {k: v.strip() for k, v in data.items()
                if isinstance(k, str) and isinstance(v, str) and v.strip()}
    except (OSError, ValueError, AttributeError):
        return {}


def local_overrides():
    try:
        stat = OVERRIDES_PATH.stat()
        return _read_overrides(str(OVERRIDES_PATH), (stat.st_mtime_ns, stat.st_size))
    except OSError:
        return {}


def _tail(text):
    parts = []
    for token in text.split('_'):
        token = token.strip()
        if not token:
            continue
        if re.fullmatch(r'\d{8}', token):
            token = f'{token[:4]}-{token[4:6]}-{token[6:]}'
        elif token.endswith('Constructed'):
            code = token[:-11]
            token = f'{SETS.get(code, code)}构筑'
        else:
            token = TERMS.get(token, SETS.get(token, token))
        parts.append(token)
    return ' · '.join(parts)


def friendly_event(event_id):
    if not event_id or event_id == '(unknown)':
        return '赛事未记录'
    custom = local_overrides().get(event_id)
    if custom:
        return custom
    if event_id in EXACT:
        return EXACT[event_id]
    decathlon = re.fullmatch(r'Decathlon(\d{4})_(\d+)_(.+)', event_id)
    if decathlon:
        year, stage, tail = decathlon.groups()
        return f'十项全能 {year} · 第 {stage} 项 · {_tail(tail)}'
    traditional = event_id.startswith('Traditional_')
    core = event_id[len('Traditional_'):] if traditional else event_id
    for fmt, name in FORMATS.items():
        for suffix, mode in (('_Ladder', '排位'), ('_Play', '自由对战')):
            if core == fmt + suffix:
                return ('传统' if traditional else '') + name + mode
        for suffix, mode in (('_Event', '构筑赛'), ('_Challenge', '挑战赛')):
            if core == fmt + suffix or core.startswith(fmt + suffix + '_'):
                tail = _tail(core[len(fmt + suffix):])
                return ('传统' if traditional else '') + name + mode + (' · ' + tail if tail else '')
    for prefix, name in PREFIXES.items():
        if event_id.startswith(prefix):
            tail = _tail(event_id[len(prefix):])
            return name + (' · ' + tail if tail else '')
    return event_id
