"""Import Chinese card names from a local ParaTranz snapshot.

The generated catalog is keyed by Arena grpId.  Matching uses the English card
name plus set and collector number whenever possible; display text is never used
as a statistical identity.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from app.config import load_config


def _printing(row: dict, filename: str) -> dict | None:
    english = row.get("original")
    chinese = row.get("translation")
    if not isinstance(english, str) or not english.strip():
        return None
    if not isinstance(chinese, str) or not chinese.strip():
        return None
    try:
        stage = int(row.get("stage") or 0)
    except (TypeError, ValueError):
        stage = 0
    key = str(row.get("key") or "")
    position = key.split("|", 1)[0].strip()
    collector = position.split("·", 1)[1].strip() if "·" in position else ""
    set_code = Path(filename).stem.rsplit("-", 1)[-1].lower()
    context = str(row.get("context") or "")
    provider_match = re.search(r"Translated from:\s*([^\n<]+)", context)
    provider = provider_match.group(1).strip() if provider_match else ""
    return {
        "english": english.strip(),
        "chinese": chinese.strip(),
        "stage": stage,
        "set_code": set_code,
        "collector": collector.lower(),
        "provider": provider,
    }


def load_name_index(source: Path, min_stage: int = 5) -> tuple[dict, dict, dict]:
    """Return exact-print, unique-name and import metadata indexes."""
    name_dir = source / "utf8" / "name"
    if not name_dir.is_dir():
        raise ValueError(f"找不到本地牌名目录：{name_dir}")
    exact: dict[tuple[str, str, str], dict] = {}
    candidates: dict[str, list[dict]] = defaultdict(list)
    files = sorted(name_dir.glob("*.json"))
    rows_seen = 0
    trusted = 0
    for path in files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取牌名文件 {path.name}: {exc}") from exc
        if not isinstance(rows, list):
            raise ValueError(f"牌名文件不是数组：{path.name}")
        for row in rows:
            rows_seen += 1
            item = _printing(row, path.name) if isinstance(row, dict) else None
            if not item or item["stage"] < min_stage:
                continue
            trusted += 1
            candidates[item["english"]].append(item)
            key = (item["english"], item["set_code"], item["collector"])
            previous = exact.get(key)
            if previous is None or item["stage"] > previous["stage"]:
                exact[key] = item

    unique: dict[str, dict] = {}
    ambiguous = 0
    for english, options in candidates.items():
        best_stage = max(item["stage"] for item in options)
        best = [item for item in options if item["stage"] == best_stage]
        translations = {item["chinese"] for item in best}
        if len(translations) == 1:
            unique[english] = best[0]
        else:
            ambiguous += 1
    meta = {
        "snapshot": source.name,
        "name_files": len(files),
        "rows_seen": rows_seen,
        "rows_at_or_above_min_stage": trusted,
        "min_stage": min_stage,
        "ambiguous_english_names": ambiguous,
    }
    return exact, unique, meta


def _source(items: list[dict], snapshot: str) -> str:
    stage = min(item["stage"] for item in items)
    providers = sorted({item["provider"] for item in items if item["provider"]})
    if stage >= 9:
        quality = "官方译名"
    elif providers:
        quality = "/".join(providers)
    else:
        quality = "已审核译名"
    return f"本地牌库 {snapshot}（{quality}，stage {stage}）"


def resolve_name(english: str, set_code: str, collector: str,
                 exact: dict, unique: dict, snapshot: str) -> dict | None:
    """Resolve one Arena name; one translated part is enough for multipart cards."""
    if not english:
        return None
    tokens = re.split(r"(\s+/{2,3}\s+)", english)
    parts = [part.strip() for part in tokens[::2]]
    separators = tokens[1::2]
    items: list[dict | None] = []
    for part in parts:
        item = exact.get((part, (set_code or "").lower(), (collector or "").lower()))
        if item is None:
            item = unique.get(part)
        items.append(item)
    translated = [item for item in items if item is not None]
    if not translated:
        return None
    source = _source(translated, snapshot)
    if len(translated) < len(parts):
        source += f"；部分译名（{len(translated)}/{len(parts)}，其余保留英文）"
    return {
        "name_en": english,
        "name_zh": "".join(
            (item["chinese"] if item is not None else part)
            + (separators[index] if index < len(separators) else "")
            for index, (part, item) in enumerate(zip(parts, items))
        ),
        "source": source,
        "language": "zhs",
    }


def build_catalog(source: Path, cards_db: Path, existing: dict | None = None,
                  min_stage: int = 5) -> tuple[dict, dict]:
    exact, unique, meta = load_name_index(source, min_stage=min_stage)
    catalog = dict(existing or {})
    matched = 0
    with sqlite3.connect(cards_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT grp_id,name,set_code,collector_number FROM cards ORDER BY grp_id"
        )
        total = 0
        for row in rows:
            total += 1
            value = resolve_name(
                row["name"] or "", row["set_code"] or "",
                row["collector_number"] or "", exact, unique, meta["snapshot"]
            )
            if value:
                catalog[str(row["grp_id"])] = value
                matched += 1
    meta.update({"cards_seen": total, "cards_matched": matched})
    catalog["_meta"] = meta
    return catalog, meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="时间戳快照目录（其中应有 utf8/name）")
    parser.add_argument("--cards-db", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-stage", type=int, default=5,
                        help="最低译名审核阶段；默认 5，跳过机器候选")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    cards_db = args.cards_db or cfg.root / "data" / "mtga_cards.db"
    output = args.output or cfg.root / "data" / "card_names.catalog.json"
    if not cards_db.is_file():
        parser.error(f"找不到 Arena 卡名库：{cards_db}")
    try:
        existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        existing = existing if isinstance(existing, dict) else {}
        catalog, meta = build_catalog(
            args.source, cards_db, existing=existing, min_stage=args.min_stage
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if args.dry_run:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(output)
    print(f"已写入：{output}")


if __name__ == "__main__":
    main()
