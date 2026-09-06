# -*- coding: utf-8 -*-
"""全史分析：回填赛制分类（format_class）+ 生成全史先后手分析报告。

数据源：
- data/untapped/raw_b*.json：原始批次（含 super_format/event_name，用于判定 Brawl）
- SQLite matches 表：已导入的全史对局（source='untapped' + 'log'）

赛制分类规则（写入 matches.format_class）：
- brawl       = super_format==2 或 event 名含 brawl（raw 回填）或 event_id 含 Brawl
- limited     = event_id 含 Draft/Sealed/PremierDraft/QuickDraft
- constructed = 其余

报告输出：data/analysis_full_history.md（gitignored，个人数据不入库）
用法：python -m tools.analyze_history
"""
from __future__ import annotations

import glob
import io
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import load_config  # noqa: E402
from app import stats  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "untapped"

LIMITED_HINTS = ("draft", "sealed")


def tag_format_class(conn: sqlite3.Connection) -> dict:
    """从 raw 批次回填 Brawl 标记（按 match_start 匹配），再按 event 兜底。"""
    brawl_ts = set()
    for p in glob.glob(str(D / "raw_b*.json")):
        try:
            arr = json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for m in arr:
            if not isinstance(m, dict) or not m.get("match_start"):
                continue
            if m.get("super_format") == 2 or "brawl" in (m.get("event_name") or "").lower():
                brawl_ts.add(int(m["match_start"]))
    cur = conn.execute(
        "SELECT match_id, start_time, event_id FROM matches WHERE source='untapped'"
    )
    rows = cur.fetchall()
    n_brawl = n_limited = 0
    for r in rows:
        ts = r["start_time"]
        ev = (r["event_id"] or "")
        ev_l = ev.lower()
        if ts in brawl_ts or "brawl" in ev_l:
            fc = "brawl"
            n_brawl += 1
        elif any(h in ev_l for h in LIMITED_HINTS):
            fc = "limited"
            n_limited += 1
        else:
            fc = "constructed"
        conn.execute("UPDATE matches SET format_class=? WHERE match_id=?",
                     (fc, r["match_id"]))
    conn.commit()
    return {"untapped_rows": len(rows), "brawl": n_brawl, "limited": n_limited}


def wr_row(w: int, n: int) -> dict:
    return stats.wr(w, n)


def _md_wr(x: dict) -> str:
    return f"{x['wr']}%" if x["n"] else "–"


def _md_n(x: dict) -> str:
    return f"{x['wins']}/{x['n']}" if x["n"] else "–"


def build_report(conn: sqlite3.Connection) -> str:
    lines = []
    ap = lines.append
    base = "my_result IS NOT NULL AND is_abnormal=0 AND is_bot=0"
    ap("# 全史分析报告（Untapped 10,918 场 + 日志 79 场合并库）")
    ap("")
    ap(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　|　"
       f"口径：排除异常局（时长≤150s）、一场=1 样本、95% Wilson 置信区间")
    ap("")

    # 1. 全史总览
    r = conn.execute(
        f"SELECT SUM(my_result='win') w, COUNT(*) n FROM matches WHERE {base}"
    ).fetchone()
    total = wr_row(r["w"] or 0, r["n"])
    ap("## 1. 全史总览")
    ap("")
    ap(f"**总战绩 {_md_n(total)}，胜率 {_md_wr(total)}**（95% CI {total['lo']}–{total['hi']}%）")
    ap("")

    # 先后手 × 赛制矩阵
    ap("## 2. 先后手 × 赛制")
    ap("")
    ap("| 赛制 | 先手战绩 | 先手胜率 | 后手战绩 | 后手胜率 | 差值 |")
    ap("|---|---|---|---|---|---|")
    fc_names = {"brawl": "Brawl", "constructed": "构组（Standard/Explorer 等）",
                "limited": "轮抽/现开", None: "未分类"}
    for fc in ("brawl", "constructed", "limited"):
        row = conn.execute(
            f"""SELECT play_draw,
                       SUM(my_result='win') w, COUNT(*) n
                FROM matches WHERE {base} AND format_class IS ?
                GROUP BY play_draw""", (fc,)).fetchall()
        play = next((x for x in row if x["play_draw"] == "play"), None)
        draw = next((x for x in row if x["play_draw"] == "draw"), None)
        p = wr_row(play["w"] or 0, play["n"]) if play else wr_row(0, 0)
        d = wr_row(draw["w"] or 0, draw["n"]) if draw else wr_row(0, 0)
        delta = (p["wr"] - d["wr"]) if (p["n"] and d["n"]) else None
        ap(f"| {fc_names[fc]} | {_md_n(p)} | {_md_wr(p)} | {_md_n(d)} | {_md_wr(d)} "
           f"| {f'{delta:+.1f}' if delta is not None else '–'} |")
    # 全部合计
    row = conn.execute(
        f"""SELECT play_draw, SUM(my_result='win') w, COUNT(*) n
            FROM matches WHERE {base} AND play_draw IS NOT NULL
            GROUP BY play_draw""").fetchall()
    play = next((x for x in row if x["play_draw"] == "play"), None)
    draw = next((x for x in row if x["play_draw"] == "draw"), None)
    p = wr_row(play["w"] or 0, play["n"]) if play else wr_row(0, 0)
    d = wr_row(draw["w"] or 0, draw["n"]) if draw else wr_row(0, 0)
    delta = (p["wr"] - d["wr"]) if (p["n"] and d["n"]) else None
    ap(f"| **合计** | {_md_n(p)} | **{_md_wr(p)}** | {_md_n(d)} | **{_md_wr(d)}** "
       f"| {f'{delta:+.1f}' if delta is not None else '–'} |")
    ap("")

    # 3. Brawl 年度趋势
    ap("## 3. Brawl 先后手年度趋势")
    ap("")
    ap("| 年份 | 先手胜率 | 后手胜率 | 差值 | 场次 |")
    ap("|---|---|---|---|---|")
    rows = conn.execute(
        f"""SELECT strftime('%Y', start_time/1000, 'unixepoch', 'localtime') y,
                   play_draw, SUM(my_result='win') w, COUNT(*) n
            FROM matches WHERE {base} AND format_class='brawl'
            GROUP BY y, play_draw ORDER BY y""").fetchall()
    years = defaultdict(dict)
    for x in rows:
        years[x["y"]][x["play_draw"]] = x
    for y in sorted(years):
        p = years[y].get("play"); d = years[y].get("draw")
        pw = wr_row(p["w"] or 0, p["n"]) if p else wr_row(0, 0)
        dw = wr_row(d["w"] or 0, d["n"]) if d else wr_row(0, 0)
        n_total = (p["n"] if p else 0) + (d["n"] if d else 0)
        delta = (pw["wr"] - dw["wr"]) if (pw["n"] and dw["n"]) else None
        ap(f"| {y} | {_md_wr(pw)} | {_md_wr(dw)} "
           f"| {f'{delta:+.1f}' if delta is not None else '–'} | {n_total} |")
    ap("")

    # 4. Brawl 套牌榜（先手/后手差异最大的视角）
    ap("## 4. Brawl 套牌榜 Top 15（按场次）")
    ap("")
    ap("| 套牌 | 场次 | 总胜率 | 先手胜率 | 后手胜率 | 差值 |")
    ap("|---|---|---|---|---|---|")
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(my_deck_tag,''),'(未标注)') deck,
                   SUM(my_result='win') w, COUNT(*) n,
                   SUM(CASE WHEN play_draw='play' THEN 1 ELSE 0 END) pn,
                   SUM(CASE WHEN play_draw='play' AND my_result='win' THEN 1 ELSE 0 END) pw,
                   SUM(CASE WHEN play_draw='draw' THEN 1 ELSE 0 END) dn,
                   SUM(CASE WHEN play_draw='draw' AND my_result='win' THEN 1 ELSE 0 END) dw
            FROM matches WHERE {base} AND format_class='brawl'
            GROUP BY deck ORDER BY n DESC LIMIT 15""").fetchall()
    for r in rows:
        t = wr_row(r["w"] or 0, r["n"])
        p = wr_row(r["pw"] or 0, r["pn"])
        d = wr_row(r["dw"] or 0, r["dn"])
        delta = (p["wr"] - d["wr"]) if (p["n"] and d["n"]) else None
        ap(f"| {r['deck']} | {r['n']} | {_md_wr(t)} | {_md_wr(p)} | {_md_wr(d)} "
           f"| {f'{delta:+.1f}' if delta is not None else '–'} |")
    ap("")

    # 5. 异常局概览
    r = conn.execute(
        "SELECT COUNT(*) n FROM matches WHERE is_abnormal=1").fetchone()
    ap("## 5. 数据质量")
    ap("")
    r2 = conn.execute("SELECT COUNT(*) n FROM matches").fetchone()
    ap(f"- 异常局（时长≤150s）{r['n']} / {r2['n']} 场（{100*r['n']/max(r2['n'],1):.1f}%），统计时已排除")
    rb = conn.execute("SELECT COUNT(*) n FROM matches WHERE is_bot=1").fetchone()
    ap(f"- Bot 刷分局 {rb['n']} 场（套牌名匹配 config bot_deck_patterns），统计时已排除")
    by_src = conn.execute(
        "SELECT source, COUNT(*) c FROM matches GROUP BY source").fetchall()
    src_txt = ", ".join(f"{x['source']} {x['c']} 场" for x in by_src)
    ap(f"- 来源分布：{src_txt}")
    ap("- BO3 场次在 matches 层只计 1 样本（先手/后手按第 1 局计）")
    ap("")
    ap("---")
    ap("*本报告由 tools/analyze_history.py 生成；口径与面板一致（app/stats.py）。*")
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    tag = tag_format_class(conn)
    print(f"赛制回填：{tag}")
    report = build_report(conn)
    out = ROOT / "data" / "analysis_full_history.md"
    out.write_text(report, encoding="utf-8")
    print(f"报告已写入 {out}")
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
