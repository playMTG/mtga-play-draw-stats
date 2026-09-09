import json
from datetime import datetime

import pytest

from app import event_names, stats, store
from app.insights import daily_report


@pytest.mark.parametrize('raw, expected', [
    ('Traditional_Historic_Play', '传统史迹自由对战'),
    ('TradDraft_NEO_20220101', '传统轮抽 · 神河：霓朝纪 · 2022-01-01'),
    ('MWM_HistoricPauper_20220101', '每周魔法 · 史迹纯普 · 2022-01-01'),
    ('PremierDraft_UNSEEN_Special_20220101', '优选轮抽 · UNSEEN · Special · 2022-01-01'),
    ('FutureUnknown_Event', 'FutureUnknown_Event'),
    (None, '赛事未记录'), ('', '赛事未记录'), ('(unknown)', '赛事未记录'),
])
def test_names_and_conservative_fallback(raw, expected):
    assert event_names.friendly_event(raw) == expected


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
