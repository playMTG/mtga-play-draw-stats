# -*- coding: utf-8 -*-
"""中文内容兼容性测试：汉化 mod 环境下日志含中文（卡名/玩家名等），解析必须无损。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser import iter_lines, iter_records


def test_chinese_content_survives_parsing(tmp_path):
    """多行 JSON 块含中文（汉化 mod 场景）+ 单行含中文玩家名 → 完整提取不乱码。

    逻辑记录共 3 条：纯时间戳行、合并后的 JSON 块、单行 JSON。
    """
    p = tmp_path / "Player.log"
    block = (
        '[UnityCrossThreadLogger]2026-09-06 15:00:00\n'
        '[UnityCrossThreadLogger]Client ==> {"payload":{\n'
        '  "cardName":" fraud 龙 奥莉薇亚",\n'
        '  "notes":"历史争锋 · 示例玩家的套牌"\n'
        '}}\n'
    )
    single = '[UnityCrossThreadLogger]MatchEvent {"playerName":"玩家小张","seatId":0}\n'
    p.write_text(block + single, encoding="utf-8")

    recs = [t for t, _ in iter_records(p)]
    assert len(recs) == 3
    obj = json.loads(recs[1][recs[1].index("{"):])
    assert obj["payload"]["cardName"] == " fraud 龙 奥莉薇亚"
    assert obj["payload"]["notes"] == "历史争锋 · 示例玩家的套牌"
    obj2 = json.loads(recs[2][recs[2].index("{"):])
    assert obj2["playerName"] == "玩家小张"


def test_chinese_multibyte_offsets_consistent(tmp_path):
    """含中文的字节偏移推进正确（watcher tail 依赖 nbytes）。

    Windows 下 write_text 把 \\n 翻译成 \\r\\n， nbytes 相应 +1。
    """
    from app.parser import iter_lines
    p = tmp_path / "Player.log"
    p.write_text('{"名":"龙"}\n{"a":"b"}\n', encoding="utf-8")
    recs = list(iter_lines(p))
    assert len(recs) == 2
    assert recs[1].line_no == 2
    assert recs[0].nbytes == len('{"名":"龙"}\r\n'.encode("utf-8"))
