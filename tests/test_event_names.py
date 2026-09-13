import json
from datetime import datetime

import pytest

from app import event_names, stats, store
from app.insights import daily_report


@pytest.mark.parametrize('raw, expected', [
    ('Traditional_Historic_Play', '传统史迹自由对战'),
    ('TradDraft_NEO_20220101', '传统轮抽 · 神河：霓朝纪 · 2022-01-01'),
    ('MWM_HistoricPauper_20220101', '周中 · 史迹纯普 · 2022-01-01'),
    ('PremierDraft_UNSEEN_Special_20220101', '优选轮抽 · UNSEEN · Special · 2022-01-01'),
    ('FutureUnknown_Event', 'FutureUnknown_Event'),
    (None, '赛事未记录'), ('', '赛事未记录'), ('(unknown)', '赛事未记录'),
])
def test_names_and_conservative_fallback(raw, expected):
    assert event_names.friendly_event(raw) == expected


@pytest.mark.parametrize('raw, expected', [
    # 2026-09-13 核验后补入的系列名，来源见 DESIGN.md「R3 赛事中文化」。
    ('PickTwoDraft_HOB_20260811', '选两张轮抽 · 霍比特人 · 2026-08-11'),
    ('MWM_SOS_Sealed_20260616', '周中 · 斯翠海文的秘密 · 现开 · 2026-06-16'),
    ('MWM_TMT_BotDraft_20260407', '周中 · 忍者神龟 · 机器人轮抽 · 2026-04-07'),
    ('PremierDraft_TLA_20251118', '优选轮抽 · 降世神通：最后的气宗 · 2025-11-18'),
    ('PremierDraft_FIN_20250610', '优选轮抽 · 最终幻想 · 2025-06-10'),
    ('MWM_HBG_BotDraft_20220712', '周中 · 炼金新篇：博德之门 · 机器人轮抽 · 2022-07-12'),
    # 系列代码后面直接跟 Constructed 时，走的是「XX构筑」那条分支。
    ('MWM_FINConstructed_20250617', '周中 · 最终幻想构筑 · 2025-06-17'),
])
def test_verified_set_names(raw, expected):
    assert event_names.friendly_event(raw) == expected


@pytest.mark.parametrize('raw', [
    # 官方中文站对这些系列只给英文名（见 DESIGN.md 核验来源），按既定口径保留代码，
    # 不自行音译。这条守着「不要把没核验过的名字塞进 SETS」。
    'QuickDraft_ECL_20260129',
    'PremierDraft_EOE_20250729',
    'MWM_FDN_4P_BotDraft_20250826',
])
def test_unverified_sets_keep_their_codes(raw):
    label = event_names.friendly_event(raw)
    code = raw.split('_')[1]
    assert code in label, f'{raw} 的系列代码被换掉了：{label}'


def test_local_correction_reload_and_bad_file(tmp_path, monkeypatch):
    path = tmp_path / 'names.json'
    monkeypatch.setattr(event_names, 'OVERRIDES_PATH', path)
    path.write_text(json.dumps({'Ladder': '自定义标准排位', 'bad': 42}), encoding='utf-8')
    assert event_names.friendly_event('Ladder') == '自定义标准排位'
    assert event_names.friendly_event('bad') == 'bad'
    path.write_text('[]', encoding='utf-8')
    assert event_names.friendly_event('Ladder') == '标准排位'
    path.write_text('{broken', encoding='utf-8')
    assert event_names.friendly_event('Ladder') == '标准排位'
    path.unlink()
    assert event_names.friendly_event('Ladder') == '标准排位'


def test_same_translation_keeps_event_identity_everywhere(tmp_path, monkeypatch):
    path = tmp_path / 'names.json'
    monkeypatch.setattr(event_names, 'OVERRIDES_PATH', path)
    path.write_text(json.dumps({'Ladder': '同一译名', 'Play': '同一译名'}), encoding='utf-8')
    conn = store.connect(tmp_path / 'test.db')
    try:
        day = datetime(2022, 1, 1)
        for i, ev in enumerate(('Ladder', 'Play')):
            conn.execute('INSERT INTO matches(match_id,event_id,start_time,play_draw,my_result) VALUES(?,?,?,?,?)',
                         (str(i), ev, int(day.timestamp()*1000)+i*1000, 'play', 'win'))
        before = [tuple(r) for r in conn.execute('SELECT * FROM matches ORDER BY match_id')]
        overview = stats.overview(conn)
        assert len(overview['by_event']) == 2
        assert {r['label'] for r in overview['by_event']} == {'同一译名'}
        assert {r['key'] for r in overview['by_event']} == {'Ladder', 'Play'}
        assert {r['value'] for r in stats.filter_options(conn)['events']} == {'Ladder', 'Play'}
        matches = stats.match_list(conn, event='Play')
        assert matches['total'] == 1
        assert matches['rows'][0]['event_label'] == '同一译名'
        report = daily_report(conn, '2022-01-01', event='Ladder')
        assert report['events'][0]['label'] == '同一译名'
        assert report['highlight_records'][0]['event_label'] == '同一译名'
        assert report['comparison']['groups'][0]['event'] == 'Ladder'
        assert before == [tuple(r) for r in conn.execute('SELECT * FROM matches ORDER BY match_id')]
    finally:
        conn.close()
