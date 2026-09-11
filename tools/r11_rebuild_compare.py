# -*- coding: utf-8 -*-
"""R11.2：备份正式库 → 用修复后解析器重建临时库 → 输出差异报告。

严格只读正式库（SQLite backup API），绝不写回 mtga_stats.db。
人工核对 data/reviews/r11-rebuild-*.md 后，再单独决定是否替换。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_config  # noqa: E402
from app import store  # noqa: E402
from app.backfill import backfill, collect_sources, detect_player_id  # noqa: E402


def backup_prod(prod: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"before-r11-rebuild-{stamp}.db"
    src = sqlite3.connect(f"file:{prod}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def rebuild(cfg, rebuild_db: Path) -> dict:
    """写入临时库；使用与正式库相同的 my_player_id（config）。"""
    if rebuild_db.exists():
        rebuild_db.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(rebuild_db) + suffix)
        if p.exists():
            p.unlink()
    rebuild_db.parent.mkdir(parents=True, exist_ok=True)

    files = collect_sources(cfg)
    my_id = cfg.my_player_id or detect_player_id(files)

    # 轻量 Config：只改 db_path
    class _Cfg:
        def __init__(self, base, db_path):
            self._base = base
            self.root = base.root
            self.db_path = db_path
            self.my_player_id = my_id

        def __getitem__(self, k):
            return self._base[k]

        def get(self, k, default=None):
            return self._base.get(k, default)

        @property
        def abnormal_max_duration(self):
            return self._base.abnormal_max_duration

        @property
        def abnormal_max_turns(self):
            return self._base.abnormal_max_turns

        @property
        def player_log(self):
            return self._base.player_log

        @property
        def prev_log(self):
            return self._base.prev_log

        def session_log_dirs(self):
            return self._base.session_log_dirs()

        def expand(self, path):
            return self._base.expand(path)

    rcfg = _Cfg(cfg, rebuild_db)
    report = backfill(rcfg, files)
    report["my_id"] = my_id
    report["rebuild_db"] = str(rebuild_db)
    report["files"] = len(files)
    return report


def _load_matches(db: Path) -> dict[str, dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict[str, dict] = {}
    for r in conn.execute(
        """SELECT match_id, source, event_id, start_time, end_time,
                  my_seat, play_draw, my_result, end_reason, total_turns,
                  opponent_name, my_deck_tag, my_deck_id, is_bot
           FROM matches"""
    ):
        out[r["match_id"]] = dict(r)
    conn.close()
    return out


def _load_games(db: Path) -> dict[str, list[dict]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        """SELECT match_id, game_no, result, reason, play_draw
           FROM games ORDER BY match_id, game_no"""
    ):
        out.setdefault(r["match_id"], []).append(dict(r))
    conn.close()
    return out


def _load_cmdr_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out = {
        r["match_id"]: r["c"]
        for r in conn.execute(
            "SELECT match_id, COUNT(*) c FROM commanders GROUP BY match_id"
        )
    }
    conn.close()
    return out


COMPARE_FIELDS = (
    "my_result", "play_draw", "my_seat", "end_reason",
    "opponent_name", "event_id", "my_deck_tag",
)


def compare(old_db: Path, new_db: Path) -> dict:
    om, nm = _load_matches(old_db), _load_matches(new_db)
    og, ng = _load_games(old_db), _load_games(new_db)
    oc, nc = _load_cmdr_counts(old_db), _load_cmdr_counts(new_db)

    only_old = sorted(set(om) - set(nm))
    only_new = sorted(set(nm) - set(om))
    changed = []
    result_flips = Counter()
    pd_flips = Counter()

    for mid in sorted(set(om) & set(nm)):
        a, b = om[mid], nm[mid]
        diffs = {}
        for f in COMPARE_FIELDS:
            if a.get(f) != b.get(f):
                diffs[f] = {"old": a.get(f), "new": b.get(f)}
        ga, gb = og.get(mid) or [], ng.get(mid) or []
        # 比较逐局 play_draw / result（按 game_no 对齐）
        def gmap(rows):
            return {
                r["game_no"]: (r.get("play_draw"), r.get("result"), r.get("reason"))
                for r in rows
            }
        ma, mb = gmap(ga), gmap(gb)
        if ma != mb:
            diffs["games"] = {"old": ma, "new": mb}
        if oc.get(mid) != nc.get(mid):
            diffs["commanders_n"] = {"old": oc.get(mid, 0), "new": nc.get(mid, 0)}
        if diffs:
            changed.append({"match_id": mid, "diffs": diffs})
            if "my_result" in diffs:
                result_flips[
                    f"{diffs['my_result']['old']}->{diffs['my_result']['new']}"
                ] += 1
            if "play_draw" in diffs:
                pd_flips[
                    f"{diffs['play_draw']['old']}->{diffs['play_draw']['new']}"
                ] += 1

    def summary(db: Path, matches: dict) -> dict:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) n,
                      SUM(my_result='win') wins,
                      SUM(my_result='loss') losses,
                      SUM(my_result IS NULL) null_res,
                      SUM(play_draw='play') plays,
                      SUM(play_draw='draw') draws,
                      SUM(play_draw IS NULL) null_pd,
                      SUM(my_seat IS NULL) null_seat
               FROM matches"""
        ).fetchone()
        games = conn.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]
        conn.close()
        return {
            "matches": row["n"],
            "wins": row["wins"] or 0,
            "losses": row["losses"] or 0,
            "null_result": row["null_res"] or 0,
            "play": row["plays"] or 0,
            "draw": row["draws"] or 0,
            "null_pd": row["null_pd"] or 0,
            "null_seat": row["null_seat"] or 0,
            "games": games,
            "dict_size": len(matches),
        }

    return {
        "old_summary": summary(old_db, om),
        "new_summary": summary(new_db, nm),
        "only_in_old": only_old,
        "only_in_new": only_new,
        "changed_count": len(changed),
        "changed": changed[:500],  # 报告截断，完整列表写 JSON
        "changed_all_count": len(changed),
        "result_flips": dict(result_flips),
        "play_draw_flips": dict(pd_flips),
        "sample_changed_ids": [c["match_id"] for c in changed[:20]],
    }


def write_report(out_dir: Path, payload: dict, compare_result: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"r11-rebuild-{stamp}.json"
    md_path = out_dir / f"r11-rebuild-{stamp}.md"
    json_path.write_text(
        json.dumps({"rebuild": payload, "compare": compare_result},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    c = compare_result
    os_, ns = c["old_summary"], c["new_summary"]
    lines = [
        "# R11.2 重建对比报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 临时库：`{payload.get('rebuild_db')}`",
        f"- 身份：`{payload.get('my_id')}`",
        f"- 日志文件数：{payload.get('files')}",
        "",
        "## 汇总",
        "",
        "| 指标 | 旧库 | 新库 | 差 |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("matches", "对局数"),
        ("wins", "胜"),
        ("losses", "负"),
        ("null_result", "无胜负"),
        ("play", "先手"),
        ("draw", "后手"),
        ("null_pd", "先后手未知"),
        ("null_seat", "无座位"),
        ("games", "局数"),
    ):
        a, b = os_[key], ns[key]
        lines.append(f"| {label} | {a} | {b} | {b - a:+d} |")
    lines += [
        "",
        "## 覆盖",
        "",
        f"- 仅旧库有：{len(c['only_in_old'])} 场",
        f"- 仅新库有：{len(c['only_in_new'])} 场",
        f"- 字段有差异：{c['changed_count']} 场",
        f"- 胜负变化分布：{c['result_flips'] or '（无）'}",
        f"- 先后手变化分布：{c['play_draw_flips'] or '（无）'}",
        "",
        "## 抽样 match_id（前 20）",
        "",
    ]
    for mid in c["sample_changed_ids"]:
        lines.append(f"- `{mid}`")
    if c["only_in_old"][:10]:
        lines += ["", "## 仅旧库（前 10）", ""]
        lines += [f"- `{m}`" for m in c["only_in_old"][:10]]
    if c["only_in_new"][:10]:
        lines += ["", "## 仅新库（前 10）", ""]
        lines += [f"- `{m}`" for m in c["only_in_new"][:10]]
    lines += [
        "",
        "## 处理约定",
        "",
        "- 本报告**不**自动替换正式库。",
        "- 完整差异见同目录 JSON。",
        "- 人工核对代表性记录后，再执行替换（另开步骤）。",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-rebuild", action="store_true",
                    help="跳过重建，只用已有临时库对比")
    ap.add_argument("--rebuild-db", type=Path, default=None)
    args = ap.parse_args()

    cfg = load_config()
    prod = cfg.db_path
    if not prod.is_file():
        print(f"正式库不存在：{prod}", file=sys.stderr)
        return 1

    backup = backup_prod(prod, cfg.root / "data" / "backups")
    print(f"已备份正式库 → {backup}")

    rebuild_db = args.rebuild_db or (cfg.root / "data" / "r11-rebuild" / "mtga_stats_rebuild.db")
    if args.skip_rebuild:
        if not rebuild_db.is_file():
            print(f"临时库不存在：{rebuild_db}", file=sys.stderr)
            return 1
        rebuild_report = {
            "rebuild_db": str(rebuild_db),
            "my_id": cfg.my_player_id,
            "files": None,
            "stats": store.stats(sqlite3.connect(rebuild_db)),
        }
        print(f"跳过重建，使用 {rebuild_db}")
    else:
        print("开始重建临时库（不写正式库）…")
        rebuild_report = rebuild(cfg, rebuild_db)
        print(f"重建完成：{rebuild_report.get('stats')}")

    cmp = compare(prod, rebuild_db)
    md = write_report(cfg.root / "data" / "reviews", rebuild_report, cmp)
    print(f"\n旧/新对局：{cmp['old_summary']['matches']} / {cmp['new_summary']['matches']}")
    print(f"仅旧 {len(cmp['only_in_old'])} · 仅新 {len(cmp['only_in_new'])} · "
          f"有差异 {cmp['changed_count']}")
    print(f"胜负变化：{cmp['result_flips'] or '无'}")
    print(f"报告：{md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
