/* MTGA 先后手统计面板。所有数字来自 /api/*，前端不重算统计。 */
"use strict";

const $ = (sel) => sel.includes(" ") ? document.querySelector(sel) : document.getElementById(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function setHTML(id, html) { const el = typeof id === "string" ? $(id) : id; if (el) el.innerHTML = html; }
function setText(id, text) { const el = typeof id === "string" ? $(id) : id; if (el) el.textContent = text; }
function setHidden(id, hidden) { const el = typeof id === "string" ? $(id) : id; if (el) el.hidden = !!hidden; }
const localDay = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
let matchDay = localDay(new Date()), matchLimit = 200, matchOffset = 0;
const fmtTime = (ms) =>
  ms ? new Date(ms).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–";

// 只留仍在渲染的两张图。pdChart／eventChart 随 `396677b`「Drop redundant play/draw
// and per-event charts」一起被删掉了调用点，留着变量只会让人以为还有那两张图。
// 只留段位曲线一张图。周胜率趋势图已按用户口径删掉（「罗列数据全都没必要」）。
let rankChart = null;
let rankTrack = "constructed";
/** 筛选版本号：任何筛选变化递增；渲染前必须仍是当前版本（R11.4/H4）。 */
let uiVersion = 0;
function bumpUiVersion() { uiVersion += 1; return uiVersion; }
function isStale(v) { return v !== uiVersion; }

function params() {
  const p = new URLSearchParams();
  // Bot 局一律排除，不给开关：面板是给自己复盘用的，和 Bot 打的牌没有参考价值，
  // 摆在筛选栏里只会多一个没人会关的按钮（用户口径）。
  p.set("exclude_bot", "true");
  const f = $("f-family").value, e = $("f-event").value, m = $("f-mode").value, d = $("f-deck").value;
  if (f) p.set("family", f);
  if (e) p.set("event", e);
  if (m) p.set("mode", m);
  if (d) p.set("deck", d);
  // 二级联动：选中某个具体身份时再加 deck_id（与 deck 求交，不是替换）
  const di = $("f-deck-id")?.value;
  if (d && di) p.set("deck_id", di);
  return p;
}

async function api(path, extra) {
  const p = new URLSearchParams(extra || {});
  for (const [k, v] of params()) p.set(k, v);
  const r = await fetch(`${path}?${p}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}


function applyFormatFocus(focus) {
  const note = $("format-focus-note");
  if (!note) return;
  // 「手动筛选后以筛选为准」判的是**用户真的挑了筛选条件**，不是 params() 非空。
  // params() 永远带着 exclude_bot，拿它判会让这里恒为真——整块赛制自适应（提示条、
  // body.dataset.formatFocus、三张卡的收放）都会变成死代码。2026-09-13 修。
  const filtering = ["f-family", "f-event", "f-mode", "f-deck"]
    .some(id => $(id)?.value);
  if (!focus || focus.primary === "unknown" || filtering) {
    note.hidden = true;
    document.body.dataset.formatFocus = "";
    return;
  }
  note.hidden = false;
  note.textContent =
    `近 ${focus.window_days} 天主赛制：${focus.label}` +
    (focus.share != null ? `（约 ${focus.share}%）` : "") +
    "。下面区块会按这个赛制收放；手动筛选后以筛选为准。";
  document.body.dataset.formatFocus = focus.primary;
  const cmdr = document.getElementById("commander-card");
  const rank = document.getElementById("rank-card");
  const opp = document.getElementById("opponent-types-card");
  if (cmdr) cmdr.hidden = focus.show_commanders === false;
  if (rank) {
    rank.hidden = focus.show_rank === false;
    if (focus.show_rank) {
      // 排位/限赛焦点：把段位曲线挪到每日战报后面，避免沉在页底
      const daily = document.querySelector("section.card");
      if (daily && rank.previousElementSibling !== daily && daily.nextSibling) {
        daily.parentNode.insertBefore(rank, daily.nextSibling);
      }
    }
  }
  if (opp) opp.hidden = focus.show_opponent_types === false;
}

function bigCard(id, ciId, w) {
  $(id).innerHTML = w.n
    ? `${w.wr}<span class="muted"> %</span>`
    : `<span class="muted">无样本</span>`;
  $(ciId).textContent = w.n
    ? `95% CI ${w.lo}–${w.hi}% · ${w.wins}胜 / ${w.n}场`
    : "";
}

// 先后手／各赛事柱状图与 `barChart` + 误差线插件 `ciPlugin` 一起删掉了调用点
// （`396677b`「Drop redundant play/draw and per-event charts」），定义也一并清掉：
// 留着的唯一效果是让人以为页面上还有那两张图。现在只有下面两条曲线。
async function loadOverview() {
  const v = uiVersion;
  const o = await api("/api/overview");
  if (isStale(v)) return;
  const rates = o.play_draw_rates;
  $("k-play-rate").textContent = rates.play_rate == null ? "无样本" : `${rates.play_rate}%`;
  $("k-draw-rate").textContent = rates.draw_rate == null ? "无样本" : `${rates.draw_rate}%`;
  $("k-play-rate-note").textContent = `先手 ${rates.play} 场 · 后手 ${rates.draw} 场 · 未知 ${rates.unknown} 场`;
  $("k-draw-rate-note").textContent = "全史 · 当前筛选 · 比例仅含先后手已知的有结果对局";
  applyFormatFocus(o.format_focus);
  bigCard("k-total", "k-total-ci", o.total);
  $("k-play-ci").textContent = o.on_play.n
    ? `先手胜率 ${o.on_play.wr}% · 95% CI ${o.on_play.lo}–${o.on_play.hi} · ${o.on_play.wins}胜/${o.on_play.n}场`
    : "";
  $("k-draw-ci").textContent = o.on_draw.n
    ? `后手胜率 ${o.on_draw.wr}% · 95% CI ${o.on_draw.lo}–${o.on_draw.hi} · ${o.on_draw.wins}胜/${o.on_draw.n}场`
    : "";

  // 先后手局数分布条：直白展示先手/后手各多少场、各占比例
  const pn = o.on_play.n || 0, dn = o.on_draw.n || 0, known = pn + dn;
  const dist = $("pd-dist");
  if (known > 0) {
    const pPct = (100 * pn / known).toFixed(1), dPct = (100 * dn / known).toFixed(1);
    dist.innerHTML = `
      <div style="flex:1;display:flex;height:26px;border-radius:6px;overflow:hidden;font-size:12px;font-weight:600">
        <div style="width:${pPct}%;background:#c94a3d;color:#fff;display:flex;align-items:center;justify-content:center;min-width:70px">先手 ${pn}场 · ${pPct}%</div>
        <div style="width:${dPct}%;background:#1a7f5a;color:#fff;display:flex;align-items:center;justify-content:center;min-width:70px">后手 ${dn}场 · ${dPct}%</div>
      </div>`;
    const unknown = (o.total.n || 0) - known;
    $("pd-dist-txt").textContent = unknown > 0 ? `（另 ${unknown} 场先后手未知）` : "";
  } else {
    dist.innerHTML = `<span class="muted">无样本</span>`;
    $("pd-dist-txt").textContent = "";
  }
}

/* ---------- 首页入口：最近在打的套牌（V3 收尾） ---------- */
// 这个区块是**套牌旅程的选择器**：一行一个 deck 身份，点名字就进已有的详情页。
// 所以它刻意不跟随套牌筛选（跟随就只剩一行），但跟随赛事／赛制／模式。
let recentDecksScope = "focus";   // "focus" = 按近 30 天主赛制收窄；"all" = 全部套牌

function recentDecksNote(r) {
  const f = r.focus || {};
  const manual = ["f-family", "f-event", "f-mode"].map(id => $(id)?.value).filter(Boolean);
  const parts = [];
  if (manual.length) {
    parts.push("已按当前筛选收窄，赛制切换以筛选为准。");
  } else if (f.applied) {
    parts.push(`近 ${f.window_days} 天主赛制：${f.label}`
      + (f.share == null ? "" : `（约 ${f.share}%）`) + "，只列这个赛制；点「全部」看所有赛制。");
  } else if (f.primary === "unknown") {
    parts.push("近 30 天资料不足，无法判定主赛制，按全部套牌列出。");
  } else if (recentDecksScope === "all") {
    parts.push("不限赛制，按最近一次对局列出。");
  }
  parts.push(`共 ${r.total} 套牌。`);
  if (r.unlabeled) parts.push(`另有 ${r.unlabeled} 场没记录套牌，点不进去，不计入。`);
  if ($("f-deck").value) parts.push("套牌筛选不影响这个区块——它就是用来挑套牌的。");
  return parts.join(" ");
}

async function loadRecentDecks() {
  const v = uiVersion;
  const r = await api("/api/recent_decks", {
    limit: 8, focus: recentDecksScope === "focus" ? 1 : 0,
  });
  if (isStale(v)) return;
  $("recent-decks-note").textContent = recentDecksNote(r);
  $("recent-decks-rows").innerHTML = r.items.map(it => `
    <div class="summary-item">
      <strong>${deckOpenButton(it.deck, it.deck_id, "", it.label)}</strong>
      <span class="ci">${it.n} 场 · 胜率 ${it.wr ?? "–"}%（${it.wins} 胜）· 先手 ${it.play} · 后手 ${it.draw} · 最近一次 ${fmtTime(it.last_time)}</span>
    </div>`).join("")
    || `<div class="ci">当前范围内没有可点开的套牌记录。</div>`;
}

function setRecentDecksScope(scope) {
  recentDecksScope = scope;
  $("rd-focus").classList.toggle("on", scope === "focus");
  $("rd-all").classList.toggle("on", scope === "all");
  // 返回 promise：按钮回调不用管，但测试要能 await 到「重渲染完成」再断言。
  return loadRecentDecks().catch(() => {});
}

function mulliganView(m) {
  const rows = Object.fromEntries(m.by_mulligan.map(row => [row.key, row]));
  const clean = rows.clean || {n:0,wr:null}, mulligan = rows.mulligan || {n:0,wr:null};
  const unknown = rows.unknown?.n || 0, known = clean.n + mulligan.n, total = known + unknown;
  if (!total) return {summary: "当前筛选没有可用的调度记录。"};
  const rate = row => row.wr == null ? "胜率待确认" : `胜率 ${row.wr}%`;
  if (!known) return {summary: `当前 ${total} 场对局都没有可用的调度记录。`};
  // 只留「调度过 vs 没调度」这一组对比。原先还带「资料覆盖 N/M 场（x%）」和一大段
  // 逐局留牌分布／分母口径（用户反馈：这些数据全都没必要）。
  return {summary: `调度过 ${mulligan.n} 场（${rate(mulligan)}），未调度 ${clean.n} 场（${rate(clean)}）。`};
}

async function loadMulligans() {
  const v = uiVersion;
  const m = await api("/api/mulligans");
  if (isStale(v)) return;
  $("mull-box").innerHTML = `<p>${esc(mulliganView(m).summary)}</p>`;
}

const ARCH_ZH = { Aggro: "快攻", Control: "控制", Combo: "组合技", Ramp: "Ramp", Midrange: "中速", Other: "其他" };
const ARCH_COLOR = { Aggro: "#c94a3d", Control: "#5a7db8", Combo: "#8a63c9", Ramp: "#1a7f5a", Midrange: "#d18f4e", Other: "#6b7280" };

function archTagList(a) {
  // 类型是标签集合（同一主将可有多个玩法轴）；兼容旧的单值字符串
  return Array.isArray(a) ? a.filter(Boolean) : (a ? [a] : []);
}

function archTag(a) {
  const tags = archTagList(a);
  if (!tags.length) return `<span class="tag">未标</span>`;
  return tags
    .map((t) => `<span class="tag" style="background:${ARCH_COLOR[t] || "#eef1f5"};color:#fff">${esc(ARCH_ZH[t] || t)}</span>`)
    .join(" ");
}

function archSelect(key, current) {
  const tags = archTagList(current);
  // 主将名可能含单引号（如 Harvest's Hand），inline onclick 需转义防语法炸
  const safe = key.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  const chips = Object.keys(ARCH_ZH)
    .map((k) => {
      const on = tags.includes(k);
      const style = on ? `background:${ARCH_COLOR[k]};color:#fff` : "";
      return `<button type="button" class="arch-chip${on ? " on" : ""}" data-tag="${k}" style="${style}"`
        + ` onclick="toggleOppTag(this,'${safe}','${k}')">${ARCH_ZH[k]}</button>`;
    })
    .join("");
  const label = tags.length ? `打标（${tags.length}）` : "打标";
  return `<details class="arch-edit"><summary>${label}</summary>`
    + `<div class="arch-chips">${chips}`
    + `<button type="button" class="arch-chip clear" onclick="toggleOppTag(this,'${safe}','')">清除</button>`
    + `</div></details>`;
}

async function toggleOppTag(el, key, tag) {
  const box = el.closest(".arch-chips");
  if (!box) return;
  let next;
  if (tag === "") {
    next = [];
  } else {
    const on = new Set(
      [...box.querySelectorAll(".arch-chip.on")].map((b) => b.dataset.tag).filter(Boolean)
    );
    if (on.has(tag)) on.delete(tag);
    else on.add(tag);
    next = Object.keys(ARCH_ZH).filter((k) => on.has(k));  // 统一按固定顺序存
  }
  await tagOpp(key, next.join(","));
}

function matchArchSelect(row) {
  const current = row.opp_archetype_tag || "";
  const options = ["", ...Object.keys(ARCH_ZH)].map(key => {
    const label = key ? ARCH_ZH[key] : (current ? "清除类型" : "标注类型…");
    return `<option value="${key}" ${key === current ? "selected" : ""}>${label}</option>`;
  }).join("");
  return `<select class="match-arch-select" data-match-id="${esc(row.match_id)}" aria-label="标注这场对手的构筑类型">${options}</select>`;
}

function opponentProfileMarkup(row, cards) {
  if (row.opponent_type_eligible) {
    return `<div>${archTag(row.opp_archetype_tag)}</div>${matchArchSelect(row)}`;
  }
  if ((row.event_id || "").includes("Brawl")) return cardsMarkup(cards || []);
  return `<span class="ci">不适用</span>`;
}

async function tagOpp(key, tag) {
  // key 为主将显示名（可能含引号风险字符，走 POST body 编码）
  const p = new URLSearchParams();
  p.set("commander", key);
  p.set("tag", tag);
  const r = await fetch(`/api/opp_tag_by_name?${p}`, { method: "POST" });
  const j = await r.json();
  if (j.ok) reload(); else alert(j.error || "保存失败，请重试");
}

let cmdrSort = "count";  // count=按场次 / recent=按最近遇到

async function loadCommanders() {
  const v = uiVersion;
  const j = await api("/api/commanders", { sort: cmdrSort });
  if (isStale(v)) return;
  const c = j.rows || [];
  const cov = j.coverage;
  let hint = "";
  if (c.length) {
    const auto = c.filter((r) => archTagList(r.archetype).length).length;
    hint = `共 ${c.length} 位对手主将（${auto} 位已有类型）`;
    // 覆盖率明示：主将 grpId 只在本地日志里存在，云史对局没有该字段，
    // 不注明会被误读成"解析丢数据"（如 1000+ 场争锋只统计到个位数对手）
    if (cov && cov.total) {
      const pct = (100 * cov.with_cmdr / cov.total).toFixed(1);
      hint += ` · 样本覆盖 ${cov.with_cmdr}/${cov.total} 场（${pct}%，当前筛选中主将赛制；含日志与可解码历史）`;
    }
  }
  $("cmdr-hint").textContent = hint || "当前筛选没有可识别主将；非主将赛制不适用";
  const tb = $("#t-cmdr tbody");
  tb.innerHTML = c
    .map(
      (r) => {
        const delta = r.on_play.n && r.on_draw.n ? (r.on_play.wr - r.on_draw.wr) : null;
        return `<tr>
        <td>${cardMarkup(r)}</td>
        <td>${archTag(r.archetype)}</td>
        <td class="num">${r.n}</td>
        <td class="num" style="color:${(r.wr ?? 0) >= 50 ? "var(--win)" : "var(--loss)"}">${r.wr ?? "–"}%</td>
        <td class="num">${r.on_play.n ? `${r.on_play.wr}% (${r.on_play.n})` : "–"}</td>
        <td class="num">${r.on_draw.n ? `${r.on_draw.wr}% (${r.on_draw.n})` : "–"}${delta != null ? ` <span class="ci">Δ${delta > 0 ? "+" : ""}${delta.toFixed(0)}</span>` : ""}</td>
        <td>${archSelect("grpId:" + r.key, r.archetype)}</td>
      </tr>`;
      }
    )
    .join("") || `<tr><td colspan="7" class="ci">暂无主将数据</td></tr>`;
}

function syncCmdrSortBtns() {
  $("cmdr-sort-count")?.classList.toggle("on", cmdrSort === "count");
  $("cmdr-sort-recent")?.classList.toggle("on", cmdrSort === "recent");
}
$("cmdr-sort-count").addEventListener("click", () => { cmdrSort = "count"; syncCmdrSortBtns(); loadCommanders(); });
$("cmdr-sort-recent").addEventListener("click", () => { cmdrSort = "recent"; syncCmdrSortBtns(); loadCommanders(); });
syncCmdrSortBtns();

async function loadOpponentTypes() {
  const v = uiVersion;
  const report = await api("/api/opponent_types");
  if (isStale(v)) return;
  const pct = report.eligible ? (100 * report.known / report.eligible).toFixed(1) : "–";
  $("opponent-types-summary").textContent = report.eligible
    ? `已标注 ${report.known}/${report.eligible} 场（${pct}%） · 未标注 ${report.unknown} 场`
    : "当前筛选没有明确的非主将构筑对局";
  $("opponent-types-rows").innerHTML = report.rows.map(row =>
    `<div class="summary-item"><strong>${esc(report.labels[row.tag] || row.tag)}</strong> · ${row.n} 场 · ${row.wins} 胜 ${row.losses} 负 · 胜率 ${row.win_rate.wr ?? "–"}%</div>`
  ).join("") || `<div class="ci">尚无逐场类型标注。可在下方对局明细或套牌详情中选择类型。</div>`;
  $("opponent-types-note").textContent = report.note;
}

async function tagMatch(matchId, tag, select) {
  if (select) select.disabled = true;
  const p = new URLSearchParams({match_id:matchId, tag});
  const response = await fetch(`/api/opp_tag?${p}`, {method:"POST"});
  const result = await response.json();
  if (!result.ok) {
    if (select) select.disabled = false;
    alert(result.error || "保存失败，请重试");
    return;
  }
  await Promise.all([loadOpponentTypes(), loadMatches(), loadDaily()]);
  if ($("deck-dialog").open) await loadDeckDetail();
}

function cardMarkup(card) {
  if (!card) return "–";
  // 展示层兜底：炼金 A- 前缀对用户无信息量（后端已剥，旧缓存/异常路径再兜一层）
  const raw = String(card.name ?? "");
  const name = raw.replace(/^A-/i, "");
  const hint = [card.name_en, card.name_source, card.key ? `grpId:${card.key}` : ""].filter(Boolean).join(" · ");
  return `<span title="${esc(hint)}">${esc(name)}</span>`;
}
function cardsMarkup(cards, fallback = []) {
  return cards?.length ? cards.map(cardMarkup).join(" / ") : esc(fallback.join(" / ") || "–");
}

function sourceLabel(source) {
  return source === "untapped" ? "Untapped 历史导入" : source === "log" ? "本地日志" : (source || "未记录");
}

function endReasonLabel(reason) {
  return ({Concede:"投降", Game:"正常结束", Timeout:"超时"})[reason] || reason || "未记录";
}

function gameDetails(r) {
  const mode = r.match_mode || "未知";
  const games = r.games || [];
  // BO1 不再展开逐局；BO3 用 title 悬停，不占表格行高
  if (mode === "BO1" || games.length <= 1) {
    return `<span class="ci">${esc(mode)}</span>`;
  }
  const tip = games.map(game => {
    const playDraw = game.play_draw === "play" ? "先手" : game.play_draw === "draw" ? "后手" : "?";
    const result = game.result === "win" ? "胜" : game.result === "loss" ? "负" : "?";
    return `G${game.game_no ?? "?"} ${playDraw} ${result}`;
  }).join(" · ");
  return `<span class="ci" title="${esc(tip)}">${esc(mode)}</span>`;
}

function deckOpenButton(deck, deckId, deckVersion, name) {
  // 套牌旅程的唯一入口按钮。payload 形状只在这里拼一次——明细、首页入口区都走它，
  // 免得两处各拼一份、改了一处忘了另一处（openDeck 只认这三个键）。
  const payload = encodeURIComponent(JSON.stringify({
    deck: deck || "", deck_id: deckId || "", deck_version: deckVersion || "",
  }));
  return `<button class="link-button deck-open" data-deck="${esc(payload)}" title="查看这套牌的独立详情">${esc(name)}</button>`;
}

function deckLink(r, label) {
  // my_deck_label 是后端对限制赛临时牌组给出的可区分名（"轮抓 · 2024-10-05 21:03"）；
  // 客户端只给通用名「轮抽套牌」时，250 次 draft 在明细里根本分不清（V1）。
  const name = label || r.my_deck_label || r.my_deck_tag || "套牌未记录";
  if (!(r.my_deck_tag || r.my_deck_id || r.my_deck_version)) return esc(name);
  return deckOpenButton(r.my_deck_tag, r.my_deck_id, r.my_deck_version, name);
}

function matchRow(r) {
  const brawl = (r.event_id || "").includes("Brawl");
  const ownCommander = brawl
    ? ((r.my_cards?.length || r.my_cmdrs?.length) ? cardsMarkup(r.my_cards, r.my_cmdrs) : "–")
    : `<span class="ci" title="非争锋赛制无主将">–</span>`;
  const oppCell = brawl
    ? opponentProfileMarkup(r, r.opp_cards)
    : (r.opp_archetype_tag ? esc(r.opp_archetype_tag) : `<span class="ci">–</span>`);
  return `<tr>
    <td>${fmtTime(r.start_time)}</td>
    <td>${eventMarkup(r.event_id, r.event_label)} <span class="ci">${gameDetails(r)}</span></td>
    <td class="clip" title="${esc(r.my_deck_label || r.my_deck_tag || "套牌未记录")}">${deckLink(r)}</td>
    <td>${ownCommander}</td>
    <td>${r.play_draw === "play" ? "先手" : r.play_draw === "draw" ? "后手" : "–"}</td>
    <td>${r.my_result === "win" ? "胜" : r.my_result === "loss" ? "负" : "待确认"}</td>
    <td>${esc(r.opponent_name || "–")}</td>
    <td>${oppCell}</td>
    <td title="${esc(`来源 ${sourceLabel(r.source)} · 调度 ${r.my_mulls ?? "?"} · ${endReasonLabel(r.end_reason)} · ${r.match_id || ""}`)}" class="ci">…</td>
  </tr>`;
}

function eventMarkup(raw, label) {
  const name = label || raw || "赛事未记录";
  return `<span title="${esc(raw || '赛事未记录')}">${esc(name)}</span>`;
}

async function loadMatches() {
  const v = uiVersion;
  const m = await api("/api/matches", { limit: matchLimit, offset: matchOffset, ...(matchDay ? {day:matchDay} : {}) });
  if (isStale(v)) return;
  $("m-count").textContent = `共 ${m.total} 场（本页 ${m.rows.length} 场，第 ${Math.floor(matchOffset / matchLimit) + 1} 页）`;
  $("m-more").disabled = matchOffset + m.rows.length >= m.total;
  $("m-prev").disabled = matchOffset === 0;
  const mode = $("m-group").value;
  const grouped = new Map();
  for (const r of m.rows) {
    const key = mode === "event" ? (r.event_id || "未知赛事") : mode === "deck" ? (r.my_deck_tag || "未知套牌")
      : mode === "commander" ? (r.opp_cards?.length ? JSON.stringify(r.opp_cards.map(c=>c.key).sort()) : "无主将资料／不适用")
      : (r.start_time ? localDay(new Date(r.start_time)) : "日期未知");
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(r);
  }
  $("#t-m tbody").innerHTML = [...grouped].map(([key, rows]) =>
    `<tr><td colspan="9"><strong>${mode === "event" ? eventMarkup(rows[0].event_id, rows[0].event_label) : mode === "commander" ? cardsMarkup(rows[0].opp_cards, rows[0].opp_cmdrs) : mode === "deck" ? deckLink(rows[0], key) : esc(key)}</strong> · 当前显示 ${rows.length} 场</td></tr>`
    + rows.map(matchRow).join("")).join("");
}

/* ---------- R6—R8 套牌独立详情 ---------- */
let deckAnchor = null, deckScope = "last20", deckRequest = 0, deckCommander = "", deckObservation = "";

function deckVersionLabel(value, versions) {
  if (!value) return "版本未记录";
  return versions.find(item => item.value === value)?.label || "已知版本";
}

function deckRecordRow(row, versions) {
  return `<tr><td>${fmtTime(row.start_time)}</td><td>${eventMarkup(row.event_id, row.event_label)}</td>
    <td>${gameDetails(row)}</td>
    <td>${esc(row.my_deck_label || row.my_deck_tag || "未命名")}</td>
    <td title="${esc(row.my_deck_version || "构筑版本未记录")}">${esc(deckVersionLabel(row.my_deck_version, versions))}</td>
    <td>${opponentProfileMarkup(row, row.opponent_cards)}</td>
    <td>${row.play_draw === "play" ? "先手" : row.play_draw === "draw" ? "后手" : "未知"}</td>
    <td>${row.my_result === "win" ? "胜" : row.my_result === "loss" ? "负" : "待确认"}</td></tr>`;
}

function deckSummaryMarkup(r) {
  const s = r.summary;
  const pct = value => value == null ? "–" : `${value}%`;
  return `<div class="card"><h2>${esc(r.scope_label)}对局</h2><div class="big">${s.n}</div><div class="ci">当前身份与版本范围</div></div>
    <div class="card"><h2>胜率</h2><div class="big">${s.win_rate.wr ?? "–"}<span class="muted">${s.win_rate.wr == null ? "" : " %"}</span></div><div class="ci">${s.win_rate.wins} 胜 / ${s.win_rate.n} 场有胜负</div></div>
    <div class="card"><h2>先手率</h2><div class="big">${s.play_rate ?? "–"}<span class="muted">${s.play_rate == null ? "" : " %"}</span></div><div class="ci">先手 ${s.play} 场 · 先手胜率 ${pct(s.on_play.wr)}</div></div>
    <div class="card"><h2>后手率</h2><div class="big">${s.draw_rate ?? "–"}<span class="muted">${s.draw_rate == null ? "" : " %"}</span></div><div class="ci">后手 ${s.draw} 场 · 后手胜率 ${pct(s.on_draw.wr)} · 未知 ${s.unknown_play_draw}</div></div>`;
}

function deckVersionNote(r) {
  if (r.selected_version) return "已限定到单一构筑版本；范围与统计均只计算这个版本。";
  if (r.version_count_in_scope > 1) return `该范围记录到 ${r.version_count_in_scope} 个构筑版本，以上是套牌整体。调度或抽牌比较时请再限定单一版本。`;
  if (r.unknown_version) return `有 ${r.unknown_version} 场构筑版本未记录，可在版本下拉框中单独查看。`;
  return r.summary.n ? "这个范围只记录到一个构筑版本。" : "这个范围没有对局。";
}

function deckCommanderCoverage(c) {
  if (!c.eligible) return `当前范围没有争锋对局；其余 ${c.not_applicable} 场不适用对手主将统计。`;
  return `当前范围有 ${c.eligible} 场争锋对局，对手主将已知 ${c.known} 场，未记录 ${c.missing} 场。`
    + (c.not_applicable ? ` 另有 ${c.not_applicable} 场其他赛制，不计入分母。` : "");
}

function deckCommanderRows(c, selectedKey = "") {
  const pct = value => value == null ? "–" : `${value}%`;
  return c.rows.map(row => `<tr>
    <td>${cardMarkup(row)}</td>
    <td class="num">${pct(row.share_known)} <span class="ci">(${row.n}/${c.known})</span></td>
    <td>先 ${row.play} · 后 ${row.draw}${row.unknown_play_draw ? ` · 未知 ${row.unknown_play_draw}` : ""}</td>
    <td>${row.wins} 胜 ${row.losses} 负${row.unknown_result ? ` · 待确认 ${row.unknown_result}` : ""}<br><span class="ci">胜率 ${pct(row.win_rate.wr)}</span></td>
    <td>先手 ${pct(row.on_play.wr)} <span class="ci">(${row.on_play.n})</span><br>后手 ${pct(row.on_draw.wr)} <span class="ci">(${row.on_draw.n})</span></td>
    <td><button class="ti-btn deck-commander-open${row.key === selectedKey ? " on" : ""}" data-commander="${esc(row.key)}">查看 ${row.n} 场</button></td>
  </tr>`).join("");
}

function deckObservationMarkup(observations, selectedKey = "") {
  return observations.items.map(item => `<article class="deck-observation ${esc(item.level)}">
    <h3>${esc(item.headline)}</h3>
    <p>${esc(item.text)}</p>
    <div class="deck-observation-actions">
      <button class="ti-btn deck-observation-open${item.key === selectedKey ? " on" : ""}" data-observation="${esc(item.key)}">查看 ${item.n} 场依据</button>
    </div>
  </article>`).join("");
}


function deckJourneyRender(journey) {
  const sec = $("deck-journey");
  if (!sec) return;
  if (!journey || !journey.days || !journey.days.length) {
    sec.hidden = true;
    return;
  }
  sec.hidden = false;
  const days = journey.days;
  setText("deck-journey-lead",
    `共 ${journey.day_count} 个有记录日` +
    (journey.span_days ? `，跨度约 ${journey.span_days} 天` : "") +
    (journey.unknown_day ? `；另 ${journey.unknown_day} 场日期未知未入轴` : "") +
    "。旅程按当前身份全部记录，不随上方「近 20 场」截断。");
  setHTML("deck-journey-body", days.map(d => {
    const wr = d.win_rate && d.win_rate.wr != null ? `${d.win_rate.wr}%` : "–";
    return `<tr>
      <td><button type="button" class="link-button journey-day" data-day="${esc(d.date)}">${esc(d.date)}</button></td>
      <td class="num">${d.n}</td>
      <td>${d.wins} 胜 ${d.losses} 负 <span class="ci">${wr}</span></td>
      <td>先 ${d.play} · 后 ${d.draw}${d.unknown_play_draw ? ` · 未 ${d.unknown_play_draw}` : ""}</td>
      <td class="clip" title="${esc((d.events||[]).join("、"))}">${esc((d.events||[]).join("、") || "–")}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="5" class="ci">没有可入轴的日期</td></tr>`);
  const marks = journey.version_marks || [];
  setHTML("deck-journey-versions", marks.length
    ? marks.map(m => `<div class="summary-item"><strong>${esc(m.date)}</strong><span>构筑版本变更 → 此后 ${m.n_after} 场（${m.wins} 胜 ${m.losses} 负）</span></div>`).join("")
    : `<p class="ci">尚未记录到构筑版本变更。</p>`);
}


function deckCommanderEnvRender(env) {
  const sec = $("deck-commander-env");
  if (!sec) return;
  if (!env || !env.applicable || !(env.rows || []).length) {
    sec.hidden = true;
    return;
  }
  sec.hidden = false;
  const mine = (env.my_commanders || []).map(c => c.name).join(" / ") || "主将未记录";
  setText("deck-commander-env-lead",
    `我方主将：${mine} · 对手主将已知 ${env.known}/${env.eligible} 场`);
  const pd = env.play_draw || {};
  const rate = pd.play_rate != null ? `先手率 ${pd.play_rate}%` : "";
  setText("deck-commander-env-pd",
    `先后手：先 ${pd.play} · 后 ${pd.draw}${pd.unknown_pd ? ` · 未知 ${pd.unknown_pd}` : ""}${rate ? " · " + rate : ""}`);
  setHTML("deck-commander-env-body", env.rows.map(row => {
    const delta = row.delta_pp == null ? "–"
      : `${row.delta_pp > 0 ? "+" : ""}${row.delta_pp} pp`;
    return `<tr>
      <td>${cardMarkup(row)}</td>
      <td class="num">${row.share_known}% <span class="ci">(${row.n})</span></td>
      <td class="num">${row.baseline_share == null ? "–" : row.baseline_share + "%"}</td>
      <td class="num">${esc(delta)}</td>
      <td>${row.win_rate.wins} 胜 ${row.win_rate.n - row.win_rate.wins} 负</td>
      <td class="num">${row.on_play.n ? row.on_play.wr + "%" : "–"}</td>
      <td class="num">${row.on_draw.n ? row.on_draw.wr + "%" : "–"}</td>
      <td><button type="button" class="ti-btn deck-commander-open" data-commander="${esc(row.key)}">查看 ${row.n} 场</button></td>
    </tr>`;
  }).join("") || `<tr><td colspan="8" class="ci">暂无可列出的对手主将</td></tr>`);
  setText("deck-commander-env-note", env.note || "");
}

async function loadDeckDetail() {
  if (!deckAnchor) return;
  const request = ++deckRequest;
  try {
    // 不整页清空：切换筛选/依据时保留旧内容，避免对话框“闪一下变空”
    const loading = $("deck-loading");
    if (loading) {
      loading.hidden = false;
      loading.textContent = "正在更新…";
    }
    if (!deckAnchor._loadedOnce) {
      setHTML("deck-summary", "");
      setHidden("deck-journey", true);
      setHidden("deck-commander-env", true);
      setHidden("deck-observations", true);
      setHidden("deck-commanders", true);
      setHidden("deck-records", true);
    }
    const p = new URLSearchParams({
      scope: deckScope,
      exclude_bot: "true",
    });
    for (const key of ["deck", "deck_id", "deck_version"]) {
      if (deckAnchor[key]) p.set(key, deckAnchor[key]);
    }
    const modeEl = $("deck-mode");
    if (modeEl && modeEl.value) p.set("mode", modeEl.value);
    const verEl = $("deck-version");
    if (verEl && verEl.value) p.set("version", verEl.value);
    if (deckCommander) p.set("opponent_commander", deckCommander);
    if (deckObservation) p.set("observation", deckObservation);
    const response = await fetch(`/api/deck_detail?${p}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `读取失败（${response.status}）`);
    }
    const r = await response.json();
    if (request !== deckRequest) return;
    if (deckAnchor) deckAnchor._loadedOnce = true;
    setText("deck-title", r.title || "套牌详情");
    const kindLabel = r.deck_kind?.label || "";
    const aliases = r.identity?.aliases || [];
    setText("deck-identity",
      (kindLabel ? `【${kindLabel}】 ` : "") +
      (r.identity?.note || "") +
      (aliases.length > 1 ? ` 历史名称：${aliases.join("、")}。` : ""));
    const currentMode = r.selected_mode || "";
    if (modeEl) {
      modeEl.innerHTML = `<option value="">全部</option>`
        + (r.modes || []).map(item => `<option value="${esc(item.value)}">${esc(item.label)}（${item.n} 场）</option>`).join("");
      modeEl.value = currentMode;
    }
    const currentVersion = r.selected_version || "";
    if (verEl) {
      verEl.innerHTML = `<option value="">全部构筑版本</option>`
        + (r.versions || []).map(item => `<option value="${esc(item.value)}" title="${esc(item.value)}">${esc(item.label)}（${item.n} 场）</option>`).join("")
        + (r.unknown_version ? `<option value="__unknown__">版本未记录（${r.unknown_version} 场）</option>` : "");
      verEl.value = currentVersion;
    }
    setHTML("deck-summary", deckSummaryMarkup(r));
    deckJourneyRender(r.journey);
    deckCommanderEnvRender(r.commander_env);
    setHidden("deck-observations", false);
    const observations = r.observations || {items: [], note: ""};
    setHTML("deck-observation-body", deckObservationMarkup(observations, r.selected_observation?.key || ""));
    setText("deck-observation-note", observations.note || "");
    setText("deck-version-note", deckVersionNote(r));
    const commanders = r.opponent_commanders || {rows: [], known: 0, eligible: 0, not_applicable: 0, multi_commander_matches: 0};
    setHidden("deck-commanders", false);
    setText("deck-commander-coverage", deckCommanderCoverage(commanders));
    setHidden("deck-commander-table", !commanders.rows.length);
    setHTML("deck-commander-body", deckCommanderRows(commanders, r.selected_commander?.key || ""));
    $("deck-commander-note").textContent = commanders.known
      ? `出现占比以主将已知的 ${commanders.known} 场为分母。每位主将在同一场最多计一次；${commanders.multi_commander_matches ? `其中 ${commanders.multi_commander_matches} 场记录了双主将，故各行占比之和可能超过 100%。` : "当前范围没有双主将对局。"}这是对局出现次数，不是不同玩家数。`
      : "没有可识别的对手主将，不按套牌名或其他字段猜测。";
    if (loading) loading.hidden = true;
    setHidden("deck-records", false);
    setText("deck-record-title", r.selected_commander ? `对阵 ${r.selected_commander.name} 的全部记录`
      : r.selected_observation ? `“${r.selected_observation.headline}”的依据` : "范围内对局（核对用）");
    setHidden("deck-record-all", !(r.selected_commander || r.selected_observation));
    setText("deck-record-count", r.records_truncated ? `共 ${r.records_total} 场，显示最近 200 场` : `共 ${r.records_total ?? (r.records || []).length} 场`);
    setHTML("deck-record-body", (r.records || []).map(row => deckRecordRow(row, r.versions)).join("")
      || `<tr><td colspan="8" class="ci">当前范围没有对局</td></tr>`);
  } catch (error) {
    if (request !== deckRequest) return;
    const loading = $("deck-loading");
    if (loading) {
      loading.hidden = false;
      loading.textContent = error?.message || String(error);
    }
  }
}

function jumpToDaily(day) {
  if (!day) return;
  matchDay = day;
  $("d-date").value = day;
  matchOffset = 0;
  syncMatchDayBtns();
  loadDaily();
  loadMatches();
  const el = $("daily-block") || $("d-date");
  if (el && el.scrollIntoView) el.scrollIntoView({behavior:"smooth", block:"start"});
}

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest?.(".journey-day");
  if (!btn) return;
  const day = btn.dataset.day;
  const dialog = $("deck-dialog");
  if (dialog?.open) dialog.close();
  jumpToDaily(day);
});

function openDeck(anchor) {
  try {
    deckAnchor = anchor || {};
    deckAnchor._loadedOnce = false;
    deckScope = "last20";
    deckCommander = "";
    deckObservation = "";
    const modeEl = $("deck-mode");
    const verEl = $("deck-version");
    if (modeEl) modeEl.innerHTML = `<option value="">全部</option>`;
    if (verEl) verEl.innerHTML = `<option value="">全部构筑版本</option>`;
    for (const button of document.querySelectorAll("#deck-scope button")) {
      button.classList.toggle("on", button.dataset.scope === deckScope);
    }
    const dialog = $("deck-dialog");
    if (dialog && !dialog.open) {
      try { dialog.showModal(); }
      catch { /* 已打开时忽略 */ }
    }
    loadDeckDetail().catch(() => {});
  } catch (e) {
    const loading = $("deck-loading");
    if (loading) {
      loading.hidden = false;
      loading.textContent = e?.message || "打开套牌详情失败";
    }
  }
}

let dailyRequest = 0, dailyScope = "", dailyLatest = null;
async function loadDaily() {
  // 「全部日期」下战报无意义（战报是单日口径）：藏起战报区，只留下方明细
  if (!matchDay) {
    dailyScope = "";
    $("daily-block").hidden = true;
    $("daily-all-note").hidden = false;
    $("daily-asof").textContent = "";
    return;
  }
  $("daily-block").hidden = false;
  $("daily-all-note").hidden = true;
  const request = ++dailyRequest;
  const scope = `${params()}|${matchDay}`;
  if (dailyScope !== scope) {
    $("daily-latest").hidden = true;
    $("daily-plain").textContent = "正在读取本地战报…";
    $("daily-plain").className = "";
    for (const id of ["daily-summary", "daily-asof", "daily-pd-streaks", "daily-history-lead"]) $(id).textContent = "";
    $("daily-history-section").hidden = true;
  }
  dailyScope = scope;
  const extra = { day: matchDay };
  let r;
  try { r = await api("/api/daily", extra); }
  catch (error) {
    if (request === dailyRequest && scope === `${params()}|${matchDay}`) {
      $("daily-plain").textContent = "战报读取失败，请重试。";
      $("daily-plain").className = "";
      $("daily-latest").hidden = true;
    }
    return;
  }
  if (request !== dailyRequest || scope !== `${params()}|${matchDay}`) return;
  const s = r.summary;
  matchDay = r.date;
  $("d-date").value = r.date;
  syncMatchDayBtns();
  dailyScope = `${params()}|${r.date}`;
  dailyLatest = r.latest_date;
  $("daily-latest").hidden = s.n > 0 || !dailyLatest;
  $("daily-asof").textContent = r.is_today ? "截至目前的已记录对局" : "历史日战报";
  $("daily-plain").textContent = r.plain || "";
  $("daily-plain").hidden = !r.plain;  // 有对局但无亮点时后端给空串，不留空段落
  const dailyLevel = r.highlights?.[0]?.level;
  $("daily-plain").className = dailyLevel ? `daily-highlight ${dailyLevel}` : "";
  const pd = r.play_draw;
  // 所选日期没有对局时，这三张卡只会显示「–%」「0 胜 0 负 · 0 场有胜负」——零信息，
  // 首屏（默认落在「今天」，而当天常还没打牌）会被这一片「–」占满。直接藏起来，
  // 让「查看最近有记录的一天」成为空日唯一显眼的动作。
  $("daily-summary").hidden = !s.n;
  $("daily-summary").innerHTML = `<div class="card"><h2>当天胜率</h2><div class="big">${s.win_rate.wr ?? "–"}%</div><div class="ci">${s.wins} 胜 ${s.losses} 负 · ${s.win_rate.n} 场有胜负</div></div>
    <div class="card"><h2>当天先手率</h2><div class="big">${pd?.day.play_rate ?? "–"}%</div><div class="ci">先手 ${s.play} 场 · 后手 ${s.draw} 场</div></div>
    <div class="card"><h2>当天后手率</h2><div class="big">${pd?.day.draw_rate ?? "–"}%</div><div class="ci">${s.play_rate.n} 场先后手已知 · 未知 ${s.unknown_pd} 场</div></div>`;
  // 这里原来有三行「当天最长 / 截至所选日期的当前连续 / 历史最长」加一句统计口径，
  // 再加一段「赛事 · N 场 · X 胜 Y 负 · 先手 a / 后手 b / 未知 c」的逐赛事罗列、
  // 常遇主将、BO 模式拆分、对手类型覆盖率（用户反馈：这些数据全都没必要）。
  // 现在只留**当前连续**这一条——它是这个面板存在的理由（先后手），其余在明细里。
  if (pd) {
    const h = pd.history_streaks;
    const current = h.current_side
      ? `当前连续${h.current_side === "play" ? "先手" : "后手"} ${h.current_n} 场`
      : (h.reason || "无连续记录");
    $("daily-pd-streaks").textContent = current;
  }
  const history = r.history_summary;
  const historyItems = history?.items || [];
  const hasBaseline = historyItems.some(i => i.delta_pp != null);
  // 无基线不展示空对比（VISION V0）。只留 headline 那一句结论——
  // 逐赛事的明细与比较口径原本挂在折叠里，现在整块去掉（用户反馈）。
  $("daily-history-section").hidden = !hasBaseline;
  if (hasBaseline) {
    $("daily-history-lead").innerHTML = `<p><strong>${esc(history.headline)}</strong></p>`;
  }
}

function fillSelect(sel, list) {
  const el = $(sel);
  const cur = el.value;
  el.innerHTML = `<option value="">全部</option>`;
  for (const it of list) {
    const op = document.createElement("option");
    op.value = it.value;
    if (sel === "f-event") op.title = it.value;
    op.textContent = `${it.label}（${it.n}）`;
    el.appendChild(op);
  }
  // 当前值仍存在于新列表则保留，否则重置为"全部"
  el.value = list.some((x) => x.value === cur) ? cur : "";
}

async function loadFilters() {
  const v = uiVersion;
  const f = await api("/api/filters");
  if (isStale(v)) return;
  fillSelect("f-family", f.families || []);
  fillSelect("f-event", f.events);
  fillSelect("f-mode", f.modes || []);
  fillSelect("f-deck", f.decks);
  deckIdCounts = new Map((f.decks || []).map(d => [d.value, d.ids || 1]));
  await syncDeckIdentities();
  $("open-filter-deck").disabled = !$("f-deck").value;
}

/* ---------- 二级联动：套牌名字 → 具体身份 ----------
   套牌下拉按「名字」分组，而本机 314 个名字里有 39 个被多个 deck_id 共用：
   限制赛的通用名（「轮抽套牌」188 个 id、「现开赛」48 个…）加上用户自己起的
   重名（「红黑牺牲」2 个 id、「黑白中速」4 个…）。选中这类名字时才出现第二个
   下拉，让用户指定「哪一次 draft / 哪一副同名套牌」，再用 deck_id 收窄全部区块。
   只有这 39 个名字会多一层，其余 275 个完全无感。 */
let deckIdCounts = new Map(), deckIdentities = [];

async function syncDeckIdentities() {
  const wrap = $("f-deck-id-wrap"), sel = $("f-deck-id");
  if (!wrap || !sel) return;
  const tag = $("f-deck").value;
  const keep = sel.value;
  const reset = () => { wrap.hidden = true; sel.innerHTML = `<option value="">全部</option>`; deckIdentities = []; };
  // 名字唯一（或没选名字）时不需要第二级
  if (!tag || (deckIdCounts.get(tag) || 1) < 2) { reset(); return; }
  const v = uiVersion;
  let r;
  try { r = await api("/api/deck_identities", { deck: tag }); }
  catch { reset(); return; }
  if (isStale(v) || $("f-deck").value !== tag) return;
  deckIdentities = r.items || [];
  sel.innerHTML = `<option value="">全部（${r.total}）</option>`
    + deckIdentities.map(it => `<option value="${esc(it.value)}">${esc(it.label)}（${it.n}）</option>`).join("");
  // 换了上游筛选后原选中项可能已不在列表里，那就回到「全部」
  sel.value = deckIdentities.some(it => it.value === keep) ? keep : "";
  wrap.hidden = false;
}

/* ---------- 段位曲线（M4） ---------- */
const RANK_ZH = ["青铜", "白银", "黄金", "铂金", "钻石"];
const scoreLabel = (s) =>
  s >= 21 ? "秘稀" : `${RANK_ZH[Math.floor((s - 1) / 4)] || "?"}${4 - ((s - 1) % 4)}`;

async function loadRankCurve() {
  const v = uiVersion;
  const r = await fetch(`/api/rank_curve?track=${rankTrack}`);
  const j = await r.json();
  if (isStale(v)) return;
  const pts = j.points || [];
  $("rank-hint").textContent = pts.length
    ? `${pts.length} 个段位变化点` : "暂无带时间戳的段位记录";
  if (rankChart) rankChart.destroy();
  rankChart = new Chart($("c-rank"), {
    type: "line",
    data: {
      labels: pts.map((p) => fmtTime(p.ts)),
      datasets: [{
        label: "段位",
        data: pts.map((p) => p.score),
        borderColor: "#8a63c9",
        backgroundColor: "rgba(138,99,201,.10)",
        stepped: "before",
        pointRadius: 3,
        pointHoverRadius: 5,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) => {
              const p = pts[c.dataIndex];
              return p ? (p.class === "Mythic" ? "秘稀" : `${p.class} ${p.level}`) : "";
            },
          },
        },
      },
      scales: {
        y: {
          min: 1, max: 21,
          reverse: false,
          ticks: { stepSize: 4, callback: (v) => scoreLabel(v) },
        },
      },
    },
  });
}

/* ---------- 导出（M4） ---------- */
$("btn-export-m").addEventListener("click", () => {
  window.open(`/api/export?type=matches&${params()}`);
});
// 只在启动任务失败时才出现（见 loadStatus）。POST /api/retry_boot 是幂等的，
// 服务端把「检查 booting + 置位」放进同一把锁，连点也只会起一个回填线程。
$("boot-retry").addEventListener("click", async () => {
  const btn = $("boot-retry");
  btn.disabled = true;
  try {
    const r = await fetch("/api/retry_boot", { method: "POST" }).then(x => x.json());
    if (!r.ok && r.error) alert(r.error);
  } catch {
    alert("重试请求失败，请确认面板服务仍在运行");
  } finally {
    btn.disabled = false;
    await loadStatus();
  }
});
$("btn-export-r").addEventListener("click", () => {
  window.open("/api/export?type=ranks");
});
$("rk-c").addEventListener("click", () => setRankTrack("constructed"));
$("rk-l").addEventListener("click", () => setRankTrack("limited"));

function setRankTrack(t) {
  rankTrack = t;
  $("rk-c").classList.toggle("on", t === "constructed");
  $("rk-l").classList.toggle("on", t === "limited");
  loadRankCurve();
}

async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("watch-dot").className = "dot" + (s.watching ? " ok" : "");
    let text = s.last_error ? `解析待重试：${s.last_error}` : s.watching
      ? `监听中 · 库内 ${s.db.matches} 场`
      : `监听未启用 · 库内 ${s.db.matches} 场`;
    // 启动期的归档／回填失败以前在页面上**完全不可见**：`/api/retry_boot` 与
    // `_state["boot_error"]` 都在，但前端从没引用过（R11.3 的验收标准是
    // 「回填错误可见可重试」，实际只做了后端半边）。失败时补一句并给重试按钮——
    // 正常情况按钮不出现，所以不增加任何日常噪音。
    const failed = !!s.boot_error;
    if (failed) text += ` · 启动任务失败：${s.boot_error}`;
    $("watch-txt").textContent = text;
    $("boot-retry").hidden = !failed;
    renderCardNamesNote(s.card_names);
  } catch {
    $("watch-txt").textContent = "服务不可达";
    $("boot-retry").hidden = true;
  }
}

/** 卡名覆盖提示（R12.1）：没有卡名时给出可执行的离线补齐入口。 */
function renderCardNamesNote(c) {
  const box = $("card-names-note");
  if (!box) return;
  if (!c || !c.total || c.missing === 0) { box.hidden = true; return; }
  box.hidden = false;
  const parts = [`当前 ${c.total} 个对手主将里，${c.missing} 个还没有卡名（页面显示为 grpId）。`];
  if (c.client_db) {
    parts.push("已找到本机 MTGA 客户端的卡牌库，点下面按钮即可离线补齐英文名。");
  } else {
    parts.push("未找到本机 MTGA 客户端的卡牌库（Raw_CardDatabase_*.mtga）；"
      + "可在 config.json 的 log_paths.client_raw_extra 指定目录，"
      + "或打开 card_sync_enabled 后联网补全。");
  }
  if (c.online_sync) parts.push("联网补全已开启。");
  parts.push("中文译名不在客户端库里，需要本地牌名快照或联网同步。");
  $("card-names-detail").textContent = parts.join("");
  $("card-names-title").textContent = c.named === 0 ? "对手主将还没有卡名" : "部分对手主将还没有卡名";
  const btn = $("card-names-seed");
  btn.hidden = !c.client_db;
  $("card-names-hint").hidden = !c.client_db;
}

$("card-names-seed").addEventListener("click", async () => {
  const btn = $("card-names-seed");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在补齐…";
  try {
    const r = await fetch("/api/card_names_seed", {method: "POST"}).then(x => x.json());
    btn.textContent = r.seeded ? `已补齐 ${r.seeded} 张`
      : r.client_db ? "没有可补齐的卡名" : "未找到客户端卡牌库";
    if (r.seeded) await reload();
  } catch {
    btn.textContent = "补齐失败，请重试";
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = original; }, 2500);
});

// 每个区块独立容错：早前用 Promise.all，任一 loader 抛错就整页只剩一条堆栈横幅，
// 而横幅里全是 app.js 内部的行号，看不出是哪个区块坏了（实测撞到过一次）。
// 改成 allSettled + 汇总提示：失败要看得见，但不该拖垮其余内容（R13.4）。
const RELOAD_SECTIONS = [
  ["总览", loadOverview], ["最近在打的套牌", loadRecentDecks], ["调度", loadMulligans],
  ["对手主将", loadCommanders],
  ["对手类型", loadOpponentTypes], ["对局明细", loadMatches], ["运行状态", loadStatus],
  ["段位曲线", loadRankCurve], ["被针对指数", loadTargeting], ["每日战报", loadDaily],
];

async function reload() {
  const results = await Promise.allSettled(
    RELOAD_SECTIONS.map(([, fn]) => Promise.resolve().then(fn)));
  reportLoadFailures(
    RELOAD_SECTIONS.map(([name], i) => [name, results[i]])
      .filter(([, r]) => r.status === "rejected")
      .map(([name, r]) => [name, r.reason]),
  );
}

function reportLoadFailures(failed, fatal = false) {
  const box = $("load-error");
  if (!box) return;
  box.hidden = !failed.length;
  if (!failed.length) {
    $("load-error-body").innerHTML = "";
    return;
  }
  $("load-error-title").textContent = fatal ? "页面未能初始化" : "部分区块加载失败";
  $("load-error-body").innerHTML = failed
    .map(([name, err]) => `<p><strong>${esc(name)}</strong>：${esc((err && err.message) || String(err))}</p>`)
    .join("")
    + (fatal ? "" : `<p class="ci">其余区块已正常加载；刷新页面可重试。</p>`);
}

// ---------- 你被针对了吗（§3.5） ----------
let tiWindow = "30";

function targetingSummaryItems(r) {
  const s = r.summary;
  const known = s.play + s.draw;
  const items = [];
  if (known) {
    const rate = (100 * s.play / known).toFixed(1);
    const pd = r.dimensions.play_draw;
    let detail = `先手 ${s.play} 场、后手 ${s.draw} 场；有效分母 ${known} 场，先手率 ${rate}%。`;
    if (pd.enough && pd.p < 0.05) detail += " 与五五开参考相比偏差值得继续观察。";
    else if (pd.enough) detail += " 当前未见明显偏离五五开参考。";
    else detail += " 样本不足时只记录比例。";
    items.push({title:"先后手窗口", text:detail});
  } else {
    items.push({title:"先后手窗口", text:"当前窗口没有先后手已知的对局。"});
  }
  const comparison = r.comparison;
  if (comparison && comparison.adjusted_delta_pp != null) {
    const sign = comparison.adjusted_delta_pp > 0 ? "+" : "";
    items.push({
      title:"与此前可比战绩",
      text:`可比 ${comparison.covered}/${comparison.total_decided} 场；较按当前构成加权的此前胜率 ${sign}${comparison.adjusted_delta_pp} 个百分点。`,
    });
  } else if (r.nemeses?.length) {
    const item = r.nemeses[0];
    items.push({title:"低胜率对手记录", text:`对 ${item.name} ${item.n} 场，胜率 ${item.wr}%；这是小样本记录。`});
  } else if (s.max_loss_streak >= 3) {
    items.push({title:"连续战绩", text:`当前窗口最长 ${s.max_loss_streak} 连败，只描述记录。`});
  }
  return items.slice(0, 2);
}

function targetingSummaryMarkup(r) {
  return targetingSummaryItems(r).map(item => `<div class="summary-item"><strong>${esc(item.title)}</strong><span>${esc(item.text)}</span></div>`).join("");
}

async function loadTargeting() {
  const v = uiVersion;
  const r = await api("/api/targeting", { window: tiWindow });
  if (isStale(v)) return;
  // 只留一两句摘要。原先这里还有个折叠，里面列四个维度的 p 值／分母、
  // 同范围历史战绩、近期低胜率对手清单和免责声明——整块按用户口径删掉。
  $("ti-summary").innerHTML = targetingSummaryMarkup(r);
}

// 四级级联：赛制大类 → 赛事 → 比赛模式 → 套牌
// 上游变化 → 重建下拉列表 + 刷新数据；套牌变化 → 只刷新数据
async function onFilterChange() {
  matchOffset = 0;
  bumpUiVersion();
  await loadFilters();
  await reload();
}
$("f-family").addEventListener("change", () => {$("f-event").value="";$("f-deck").value="";onFilterChange();});
$("f-event").addEventListener("change", () => {$("f-deck").value="";onFilterChange();});
$("f-mode").addEventListener("change", onFilterChange);
$("f-deck").addEventListener("change", async () => {
  // 换了名字，上一级的身份选择作废
  $("f-deck-id").value = "";
  $("open-filter-deck").disabled = !$("f-deck").value;
  matchOffset=0;bumpUiVersion();
  await syncDeckIdentities();
  await reload();
});
$("f-deck-id").addEventListener("change", () => {
  matchOffset=0;bumpUiVersion();reload();
});

// 被针对指数时间窗切换
for (const [id, w] of [["ti-7", "7"], ["ti-30", "30"], ["ti-all", "all"]]) {
  $(id).addEventListener("click", async () => {
    tiWindow = w;
    for (const x of ["ti-7", "ti-30", "ti-all"]) $(x).classList.remove("on");
    $(id).classList.add("on");
    await loadTargeting();
  });
}

loadFilters().then(reload).catch((e) => {
  // 筛选都取不到时，reload 根本不会开始，所以要说明是整页没起来（R13.4）
  reportLoadFailures([["筛选条件", e]], true);
});
// 日期筛选：战报与对局明细共用同一份状态，改一次两边一起刷新
function refreshDay() {
  loadDaily();
  loadMatches();
}
function setDay(day) {
  matchDay = day || "";
  $("d-date").value = matchDay;
  matchOffset = 0;
  syncMatchDayBtns();
  refreshDay();
}
$("d-date").addEventListener("change", () => setDay($("d-date").value));
$("daily-latest").addEventListener("click", () => { if (dailyLatest) setDay(dailyLatest); });
$("d-today").addEventListener("click", () => setDay(localDay(new Date())));
$("d-yesterday").addEventListener("click", () => {
  const d = new Date(); d.setDate(d.getDate() - 1); setDay(localDay(d));
});
$("d-all").addEventListener("click", () => setDay(""));
function syncMatchDayBtns() {
  const today = localDay(new Date());
  const y = new Date(); y.setDate(y.getDate()-1);
  const yesterday = localDay(y);
  $("d-today")?.classList.toggle("on", matchDay === today);
  $("d-yesterday")?.classList.toggle("on", matchDay === yesterday);
  $("d-all")?.classList.toggle("on", !matchDay);
}
syncMatchDayBtns();
$("m-group").addEventListener("change", loadMatches);
$("rd-focus").addEventListener("click", () => setRecentDecksScope("focus"));
$("rd-all").addEventListener("click", () => setRecentDecksScope("all"));
$("m-more").addEventListener("click", () => {matchOffset+=matchLimit;loadMatches();});
$("m-prev").addEventListener("click", () => {matchOffset=Math.max(0,matchOffset-matchLimit);loadMatches();});
$("open-filter-deck").addEventListener("click", () => {
  if ($("f-deck").value) openDeck({deck:$("f-deck").value, deck_id:$("f-deck-id").value || "", deck_version:""});
});
$("deck-close").addEventListener("click", () => $("deck-dialog").close());
$("deck-mode").addEventListener("change", () => {$("deck-version").value="";deckCommander="";deckObservation="";loadDeckDetail();});
$("deck-version").addEventListener("change", () => {deckCommander="";deckObservation="";loadDeckDetail();});
$("deck-scope").addEventListener("click", event => {
  const button = event.target.closest("button[data-scope]");
  if (!button) return;
  deckScope = button.dataset.scope;
  deckCommander = "";
  deckObservation = "";
  for (const item of document.querySelectorAll("#deck-scope button")) item.classList.toggle("on", item === button);
  loadDeckDetail();
});
$("deck-commander-body").addEventListener("click", event => {
  const button = event.target.closest(".deck-commander-open");
  if (!button) return;
  deckCommander = button.dataset.commander;
  deckObservation = "";
  loadDeckDetail();
});
$("deck-observation-body").addEventListener("click", event => {
  const button = event.target.closest(".deck-observation-open");
  if (!button) return;
  deckObservation = button.dataset.observation;
  deckCommander = "";
  loadDeckDetail();
});
$("deck-record-all").addEventListener("click", () => {deckCommander="";deckObservation="";loadDeckDetail();});
document.addEventListener("click", event => {
  const button = event.target.closest(".deck-open");
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  try { openDeck(JSON.parse(decodeURIComponent(button.dataset.deck))); }
  catch { /* 畸形页面属性不发起查询 */ }
});
document.addEventListener("change", event => {
  const select = event.target.closest(".match-arch-select");
  if (select) tagMatch(select.dataset.matchId, select.value, select);
});
setInterval(() => {loadStatus(); if(!document.hidden) reload().catch(() => {});}, 15000);
