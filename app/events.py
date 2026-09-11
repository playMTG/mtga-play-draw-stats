# -*- coding: utf-8 -*-
"""事件分类器：把日志行流还原成对局结构化记录。

有状态：按文件（=MTGA 会话）建一个 SessionBuilder，逐行 feed。
核心事件（本机 Player.log 实测验证，2026-09）：
  - matchGameRoomStateChangedEvent → Playing/MatchCompleted（对局生命周期、玩家表）
  - finalMatchResult.resultList → MatchScope_Match/Game（胜负、结束原因）
  - GRE gameStateMessage.turnInfo → 逐局先后手与回合数
  - GRE gameStateMessage ZoneType_Command → 主将 grpId（含伙伴双主将）
  - MulliganResp → 调度
  - RankGetCombinedRankInfo → 段位快照

身份识别：构造时传入 my_player_id（config 指定，或回填器按 userId 频次探测）。
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from typing import Any

from .parser import TS_RE, extract_jsons, walk_dicts


@dataclass
class GameRecord:
    game_no: int
    play_draw: str | None = None      # 'play' | 'draw'
    result: str | None = None          # 'win' | 'loss'
    reason: str | None = None


@dataclass
class MatchRecord:
    match_id: str
    source: str = "log"
    event_id: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    my_seat: int | None = None
    opponent_name: str | None = None
    opponent_platform: str | None = None
    play_draw: str | None = None       # 冗余 = 第 1 局先后手
    my_result: str | None = None       # 'win' | 'loss'
    end_reason: str | None = None
    total_turns: int = 0
    games: list[GameRecord] = field(default_factory=list)
    commanders: list[dict] = field(default_factory=list)  # {seat, grp_id, partner_idx}
    mulligans: list[dict] = field(default_factory=list)   # {game_no, seat, kept_on}
    my_deck_tag: str | None = None   # 导入源自带套牌名（日志解析为 None，手动打标优先）
    my_deck_id: str | None = None
    my_deck_version: str | None = None
    my_team: int | None = None
    players: list[dict] = field(default_factory=list)


@dataclass
class RankSnapshot:
    ts_ms: int | None
    constructed_class: str | None
    constructed_level: int | None
    limited_class: str | None
    limited_level: int | None


@dataclass
class SessionResult:
    matches: list[MatchRecord]
    ranks: list[RankSnapshot]
    unparsed_lines: int = 0


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class SessionBuilder:
    """消费一个日志文件（一个 MTGA 会话）的全部行。"""

    _MAX_CLOSED = 30
    _MAX_PENDING_FMR = 20
    _MAX_SEEN_RESULTS = 500

    def __init__(self, source: str = "log", my_player_id: str | None = None):
        self.source = source
        self.my_player_id = str(my_player_id) if my_player_id else None
        self.matches: list[MatchRecord] = []
        self.ranks: list[RankSnapshot] = []
        self.unparsed_lines = 0
        self._cur: MatchRecord | None = None
        self._game_idx: int = 0         # 当前进度中的局号（0-based）
        self._mull_cnt: int = 0         # 当前沿的调度次数（Keep 时落行并清零）
        self._saw_turn_gt1 = False
        self._expect_new_game = False   # 刚写入 MatchScope_Game → 下一 turn1 视为新局
        self._idmap: dict[int, dict] = {}
        self._seen_results: set[str] = set()
        self._last: MatchRecord | None = None   # 最近闭合的对局（迟到结果回填目标）
        self._last_revised: bool = False        # _last 在闭合后又被补了数据
        self._closed_by_id: dict[str, MatchRecord] = {}
        self._pending_fmr: list[tuple[str, dict]] = []
        self._last_ts: int | None = None   # 最近一次看到的时间戳（水位线续读用）
        self.dirty: bool = False        # 自上次 close 以来是否喂入过内容
        # event -> (name, deck id, fingerprint, explicit CommandZone grpIds)
        self._course_decks: dict[str, tuple] = {}

    # ---------- 主入口 ----------

    def feed(self, text: str, ts_ms: int | None = None) -> None:
        """喂入一条逻辑记录（单行或合并后的多行 JSON 块）。"""
        line = text
        self.dirty = True  # 供监听线程判断是否有新内容需要 flush
        jsons = self._parse_jsons(line)
        # Course 信息明确关联赛事；不能把卡组收藏列表中最后一个套牌当作当前套牌。
        for d in walk_dicts(jsons):
            summary = d.get("CourseDeckSummary")
            event = d.get("InternalEventName")
            if not (event and isinstance(summary, dict)):
                continue
            deck = d.get("CourseDeck")
            version = None
            if isinstance(deck, dict) and deck.get("MainDeck"):
                content = {k: sorted(deck.get(k) or [], key=lambda x: json.dumps(x,sort_keys=True))
                           for k in ("MainDeck", "Sideboard", "CommandZone", "Companions")}
                from .deck_versions import local_fingerprint
                version = local_fingerprint(deck) or ('local:' + hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()[:16])
            command_zone = []
            if isinstance(deck, dict):
                for card in deck.get("CommandZone") or []:
                    if not isinstance(card, dict) or card.get("cardId") is None:
                        continue
                    try:
                        quantity = int(card.get("quantity") or 0)
                    except (TypeError, ValueError):
                        continue
                    if quantity > 0:
                        command_zone.append(str(card["cardId"]))
            self._course_decks[str(event)] = (
                summary.get("Name"), summary.get("DeckId"), version,
                list(dict.fromkeys(command_zone)),
            )

        # 时间戳：调用方上下文优先，缺省时从本记录提取
        ts = ts_ms
        if ts is None:
            if m := TS_RE.search(line):
                ts = int(m.group(1))
        if ts is not None:
            self._last_ts = ts
        if self._cur is not None and ts is not None:
            self._cur._last_ts = ts

        # 处理顺序：Playing 先建立目标对局，再处理结果（可能迟到）、再闭合。
        # finalMatchResult 一律按载荷 matchId 路由，不再依赖“当前或上一场”。
        if "MatchGameRoomStateType_Playing" in line:
            self._on_match_start(jsons, ts)
        if "finalMatchResult" in line:
            self._on_final_result(jsons)
        if "MatchGameRoomStateType_MatchCompleted" in line:
            self._on_match_completed(ts)
        if self._cur is not None:
            self._on_gre(jsons)
            if "MulliganResp" in line or "mulliganResp" in line:
                self._on_mulligan(jsons)
        if "constructedClass" in line:
            self._on_rank(jsons, ts)

    def _parse_jsons(self, line: str) -> list:
        raw = extract_jsons(line)
        if not raw and "{" in line:
            self.unparsed_lines += 1  # 有对象起始但无可平衡提取 = 截断/损坏
        out = []
        for s in raw:
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError:
                self.unparsed_lines += 1
        return out

    # ---------- 事件处理 ----------

    def _on_match_start(self, jsons: list, ts_ms: int | None) -> None:
        if self._cur is not None:  # 上一场未闭合（缺 MatchCompleted，如闪退）→ 先落库
            self._close_current()
        cfg = next((d for d in walk_dicts(jsons) if "reservedPlayers" in d), None)
        if cfg is None:
            return
        players = cfg.get("reservedPlayers") or []
        m = MatchRecord(match_id=str(cfg.get("matchId") or "?"), source=self.source)
        m.start_ms = ts_ms
        m.players = [p for p in players if isinstance(p, dict)]
        m.event_id = next(
            (str(d["eventId"]) for d in walk_dicts(cfg) if d.get("eventId")), None
        )
        self._resolve_players(m)
        if m.event_id in self._course_decks:
            (m.my_deck_tag, m.my_deck_id, m.my_deck_version,
             command_zone) = self._course_decks[m.event_id]
            # CommandZone is explicit deck metadata.  It is only attached after
            # the local player's seat is known; a deck name is never used to infer it.
            if m.my_seat is not None and "Brawl" in (m.event_id or ""):
                for index, gid in enumerate(command_zone):
                    m.commanders.append({
                        "seat": m.my_seat, "grp_id": gid, "partner_idx": index,
                    })
        self._cur = m
        self._drain_pending_fmr()

    def _resolve_players(self, m: MatchRecord) -> None:
        mine = None
        if self.my_player_id:
            mine = next(
                (p for p in m.players if str(p.get("userId")) == self.my_player_id), None
            )
        if mine is None:
            return
        m.my_team = _to_int(mine.get("teamId"))
        m.my_seat = _to_int(mine.get("systemSeatId")) or m.my_team  # Brawl BO1 实测 seat==teamId
        for p in m.players:
            if p is mine:
                continue
            if p.get("playerName"):
                m.opponent_name = p.get("playerName")
                m.opponent_platform = p.get("platformId")
                break

    def _remember_closed(self, m: MatchRecord) -> None:
        self._closed_by_id[m.match_id] = m
        while len(self._closed_by_id) > self._MAX_CLOSED:
            oldest = next(iter(self._closed_by_id))
            if oldest == m.match_id:
                break
            del self._closed_by_id[oldest]

    def _find_match_by_id(self, mid: str) -> MatchRecord | None:
        if self._cur is not None and self._cur.match_id == mid:
            return self._cur
        if self._last is not None and self._last.match_id == mid:
            return self._last
        return self._closed_by_id.get(mid)

    def _result_dedup_key(self, rid: str, rl: list) -> str:
        return f"{rid or '?'}:{json.dumps(rl, sort_keys=True, default=str)}"

    def _apply_result_list(self, target: MatchRecord, rl: list) -> None:
        """把 resultList 写入指定对局；逐局结果落在该场自身尚未有结果的局槽上。"""
        my_team = target.my_team
        for entry in rl:
            scope = entry.get("scope")
            wt = _to_int(entry.get("winningTeamId"))
            reason = entry.get("reason")
            if scope == "MatchScope_Match":
                if wt is not None and my_team is not None and target.my_result is None:
                    target.my_result = "win" if wt == my_team else "loss"
                if reason and target.end_reason is None:
                    target.end_reason = str(reason).replace("ResultReason_", "")
            elif scope == "MatchScope_Game":
                g = None
                for existing in target.games:
                    if existing.result is None and existing.reason is None:
                        g = existing
                        break
                if g is None:
                    g = GameRecord(game_no=len(target.games) + 1)
                    target.games.append(g)
                if wt is not None and my_team is not None:
                    g.result = "win" if wt == my_team else "loss"
                g.reason = str(reason).replace("ResultReason_", "") if reason else None
                # 仅影响进行中的对局：一局刚结束，下一 turn1 应开新局
                # （覆盖「第一局在 turn1 投降、从未见到 turn>1」的 BO3 场景）
                if target is self._cur:
                    self._expect_new_game = True

    def _queue_pending_fmr(self, rid: str, fmr: dict) -> None:
        self._pending_fmr = [(i, f) for i, f in self._pending_fmr if i != rid]
        self._pending_fmr.append((rid, fmr))
        if len(self._pending_fmr) > self._MAX_PENDING_FMR:
            self._pending_fmr.pop(0)

    def _drain_pending_fmr(self) -> None:
        if not self._pending_fmr:
            return
        still: list[tuple[str, dict]] = []
        for rid, fmr in self._pending_fmr:
            target = self._find_match_by_id(rid)
            if target is None:
                still.append((rid, fmr))
                continue
            rl = fmr.get("resultList")
            if isinstance(rl, list):
                key = self._result_dedup_key(rid, rl)
                if key not in self._seen_results:
                    self._apply_result_list(target, rl)
                    self._seen_results.add(key)
            if target is self._last:
                self._last_revised = True
        self._pending_fmr = still

    def _on_final_result(self, jsons: list) -> None:
        # 真实日志的 finalMatchResult 带 matchId（2026-09-11 抽样 12/12）。
        # 结果可能晚于 MatchCompleted，甚至晚于下一场 Playing——必须按 ID 路由，
        # 绝不能写入“当前或最近一场”。找不到目标时入有上限的待确认队列。
        for d in walk_dicts(jsons):
            fmr = d.get("finalMatchResult")
            if not isinstance(fmr, dict):
                continue
            rl = fmr.get("resultList")
            if not isinstance(rl, list):
                continue
            rid = str(fmr.get("matchId") or "").strip()
            if rid:
                key = self._result_dedup_key(rid, rl)
                if key in self._seen_results:
                    continue
                if len(self._seen_results) > self._MAX_SEEN_RESULTS:
                    self._seen_results.clear()
                target = self._find_match_by_id(rid)
                if target is None:
                    self._queue_pending_fmr(rid, fmr)
                    continue
                self._apply_result_list(target, rl)
                if target is self._last:
                    self._last_revised = True
                self._seen_results.add(key)
                continue

            # 旧格式（无 matchId）：先解析目标，再用目标 match_id 做去重键，
            # 避免「同一天多场同结论」被误判为重复；只写给尚未有结果的
            # 当前/最近闭合对局，不落到已另有胜负的下一场。
            if self._cur is not None:
                target = self._cur
            elif self._last is not None and self._last.my_result is None:
                target = self._last
                self._last_revised = True
            else:
                target = None
            if target is None:
                continue
            # 进行中的对局允许继续写入 Game 结果（BO3 中途）；
            # 已有整场胜负的闭合对局不再接受无 ID 的重复块。
            key = self._result_dedup_key(target.match_id, rl)
            if key in self._seen_results:
                continue
            if len(self._seen_results) > self._MAX_SEEN_RESULTS:
                self._seen_results.clear()
            if target is not self._cur and target.my_result is not None:
                continue
            self._apply_result_list(target, rl)
            if target is self._last:
                self._last_revised = True
            self._seen_results.add(key)

        self._drain_pending_fmr()

    def _on_match_completed(self, ts_ms: int | None) -> None:
        if self._cur is None:
            return
        self._cur.end_ms = ts_ms
        self._close_current()

    def _on_gre(self, jsons: list) -> None:
        cur = self._cur
        for d in walk_dicts(jsons):
            gsm = d.get("gameStateMessage")
            if not isinstance(gsm, dict):
                q = d.get("queuedGameStateMessage")
                gsm = q if isinstance(q, dict) else {}
            # gameObject 快照（instanceId → 定义，供主将区解析）
            for o in gsm.get("gameObjects") or []:
                if isinstance(o, dict) and "instanceId" in o:
                    self._idmap[o["instanceId"]] = o
            # 逐局先后手 + 回合数
            # turnInfo 实测仅有 turnNumber/activePlayer/phase 等，无局号；
            # 新局信号：① 已见过 turn>1 再回到 turn1；② 刚写入 MatchScope_Game。
            ti = gsm.get("turnInfo")
            if isinstance(ti, dict):
                turn_no = _to_int(ti.get("turnNumber")) or 0
                if turn_no > cur.total_turns:
                    cur.total_turns = turn_no
                if turn_no == 1:
                    if self._saw_turn_gt1 or self._expect_new_game:
                        self._game_idx += 1
                        self._mull_cnt = 0
                        self._saw_turn_gt1 = False
                        self._expect_new_game = False
                    while len(cur.games) < self._game_idx + 1:
                        cur.games.append(GameRecord(game_no=len(cur.games) + 1))
                    g = cur.games[self._game_idx]
                    ap = _to_int(ti.get("activePlayer"))
                    if g.play_draw is None and ap is not None and cur.my_seat is not None:
                        g.play_draw = "play" if ap == cur.my_seat else "draw"
                elif turn_no > 1:
                    self._saw_turn_gt1 = True
            # 主将：ZoneType_Command 区
            zones = gsm.get("zones") or []
            if ("Brawl" in (cur.event_id or "") and
                    any(isinstance(z, dict) and z.get("type") == "ZoneType_Command" for z in zones)):
                self._on_commanders(zones)

    def _on_commanders(self, zones: list) -> None:
        cur = self._cur
        seen = {(c["seat"], c["grp_id"]) for c in cur.commanders}
        per_seat_idx: dict[int, int] = {}  # 伙伴序号按 seat 各自计数
        for z in zones:
            if not (isinstance(z, dict) and z.get("type") == "ZoneType_Command"):
                continue
            # 实测：zone 上无 ownerSeatId，owner 在每个 gameObject 上；
            # 同 zone 的多个实例可能分属两个玩家（各自主将），非伙伴
            for iid in z.get("objectInstanceIds") or []:
                obj = self._idmap.get(iid) or {}
                grp = obj.get("grpId") or obj.get("cardId")
                seat = _to_int(obj.get("ownerSeatId")) or _to_int(z.get("ownerSeatId"))
                if grp is None or seat is None:
                    continue
                key = (seat, str(grp))
                if key in seen:
                    continue
                seen.add(key)
                idx = per_seat_idx.get(seat, 0)
                per_seat_idx[seat] = idx + 1
                cur.commanders.append(
                    {"seat": seat, "grp_id": str(grp), "partner_idx": idx if idx < 2 else 0}
                )

    def _on_mulligan(self, jsons: list) -> None:
        """mulliganResp 真实格式：{"decision": "MulliganOption_Mulligan"|"Keep"}。

        无 seatId、无 keptOn。语义：每次 Mulligan 决策 = 调度一次；
        Keep 决策 = 本局保留在第 N 手（kept_on = 已调度次数，0 = 直接保留）。
        每局必有 Keep，因此 mulligans 表一行 = 一局。seat 缺失由
        upsert 时填 my_seat（该事件只会出现在本地日志 = 我方）。
        合成日志兼容：带 keptOn 字段时直接采用。
        """
        cur = self._cur
        for d in walk_dicts(jsons):
            mr = d.get("mulliganResp") or d.get("MulliganResp")
            if not isinstance(mr, dict):
                continue
            kept = _to_int(mr.get("keptOn") if mr.get("keptOn") is not None
                           else mr.get("requestedMulliganCount"))
            decision = str(mr.get("decision") or "")
            if kept is not None:  # 合成日志 / 未来格式
                cur.mulligans.append(
                    {"game_no": self._game_idx + 1,
                     "seat": _to_int(mr.get("playerSeatId") or mr.get("seatId")),
                     "kept_on": kept}
                )
                continue
            if decision.endswith("_Mulligan"):
                self._mull_cnt += 1
            elif decision.endswith("_AcceptHand") or decision.endswith("_Keep"):
                cur.mulligans.append(
                    {"game_no": self._game_idx + 1, "seat": None,
                     "kept_on": self._mull_cnt}
                )
                self._mull_cnt = 0

    def _on_rank(self, jsons: list, ts_ms: int | None) -> None:
        for d in walk_dicts(jsons):
            if "constructedClass" in d:
                self.ranks.append(
                    RankSnapshot(
                        ts_ms=ts_ms,
                        constructed_class=d.get("constructedClass"),
                        constructed_level=_to_int(d.get("constructedLevel")),
                        limited_class=d.get("limitedClass"),
                        limited_level=_to_int(d.get("limitedLevel")),
                    )
                )
                return

    # ---------- 收尾 ----------

    @property
    def in_progress(self) -> bool:
        """是否有一场对局尚未闭合（水位线只在 False 时落盘，R12.2）。"""
        return self._cur is not None

    @property
    def last_ts(self) -> int | None:
        """最近一次看到的时间戳，供续读时恢复上下文。"""
        return self._last_ts

    def close(self) -> SessionResult:
        if self._cur is not None:
            self._close_current()
        return SessionResult(self.matches, self.ranks, self.unparsed_lines)

    def set_player_id(self, player_id: str | None) -> None:
        """监听中途才探测到身份时补挂；并回填进行中/最近闭合对局的座位。"""
        if not player_id or self.my_player_id:
            return
        self.my_player_id = str(player_id)
        if self._cur is not None:
            self._resolve_players(self._cur)
        if self._last is not None and self._last.my_seat is None:
            self._resolve_players(self._last)
            self._last_revised = True

    def take(self) -> SessionResult:
        """监听线程专用：取走已完成的对局/段位并清空缓冲。

        与 close() 的区别：不关闭进行中的 _cur——若提前闭合，同一场
        对局的后续事件会因 _cur 为 None 被丢弃。未闭合对局由
        MatchCompleted / 下一场开局自然落库。闭合后又被补数据（迟到
        finalMatchResult）的 _last 会在标记时随下轮 take() 重新带上。
        """
        result = SessionResult(list(self.matches), list(self.ranks),
                               self.unparsed_lines)
        self.matches = []
        self.ranks = []
        self.unparsed_lines = 0
        if self._last is not None and self._last_revised:
            result.matches.append(self._last)
            self._last_revised = False
        return result

    def _close_current(self) -> None:
        cur = self._cur
        if cur.start_ms is None:
            cur.start_ms = cur.end_ms
        if not cur.games:
            cur.games.append(GameRecord(game_no=1))
        if cur.play_draw is None and cur.games[0].play_draw:
            cur.play_draw = cur.games[0].play_draw
        self.matches.append(cur)
        self._cur = None
        self._last = cur
        self._last_revised = False
        self._remember_closed(cur)
        self._game_idx = 0
        self._mull_cnt = 0
        self._saw_turn_gt1 = False
        self._expect_new_game = False
        self._idmap = {}
        self._drain_pending_fmr()
