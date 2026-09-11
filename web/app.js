/* MTGA 先后手统计面板。所有数字来自 /api/*，前端不重算统计。 */
"use strict";

const $ = (sel) => sel.includes(" ") ? document.querySelector(sel) : document.getElementById(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const localDay = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
let matchDay = "", matchLimit = 200, matchOffset = 0;
const fmtTime = (ms) =>
  ms ? new Date(ms).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–";
const fmtDur = (s) => {
  if (s == null) return "–";
  const m = Math.round(s / 60);
  return m >= 1 ? `${m}分` : `${Math.round(s)}秒`;
};

let pdChart = null, trendChart = null, eventChart = null, rankChart = null;
let rankTrack = "constructed";
/** 筛选版本号：任何筛选变化递增；渲染前必须仍是当前版本（R11.4/H4）。 */
let uiVersion = 0;
function bumpUiVersion() { uiVersion += 1; return uiVersion; }
function isStale(v) { return v !== uiVersion; }

function params() {
  const p = new URLSearchParams();
  p.set("exclude_bot", $("f-bot").classList.contains("on"));
  const f = $("f-family").value, e = $("f-event").value, m = $("f-mode").value, d = $("f-deck").value;
  if (f) p.set("family", f);
  if (e) p.set("event", e);
  if (m) p.set("mode", m);
  if (d) p.set("deck", d);
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
  const filtering = !!(params().toString());
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

function barChart(canvasId, labels, values, los, his, color) {
  const ctx = $(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: color,
        borderRadius: 4,
        errorBar: { lo: los, hi: his },
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } },
      },
    },
  });
}

/* Chart.js 误差线（无官方插件，用自定义 plugin 画 CI） */
const ciPlugin = {
  id: "ci",
  afterDatasetsDraw(chart) {
    const ds = chart.data.datasets[0];
    if (!ds.errorBar) return;
    const { ctx } = chart;
    const meta = chart.getDatasetMeta(0);
    const y = chart.scales.y;
    ctx.save();
    ctx.strokeStyle = "#6b7280";
    ctx.lineWidth = 1.5;
    meta.data.forEach((bar, i) => {
      const lo = y.getPixelForValue(ds.errorBar.lo[i]);
      const hi = y.getPixelForValue(ds.errorBar.hi[i]);
      const x = bar.x;
      ctx.beginPath();
      ctx.moveTo(x, hi); ctx.lineTo(x, lo);
      ctx.moveTo(x - 6, hi); ctx.lineTo(x + 6, hi);
      ctx.moveTo(x - 6, lo); ctx.lineTo(x + 6, lo);
      ctx.stroke();
    });
    ctx.restore();
  },
};
Chart.register(ciPlugin);

function trendChartDraw(rows) {
  if (trendChart) trendChart.destroy();
  trendChart = new Chart($("c-trend"), {
    type: "line",
    data: {
      labels: rows.map((r) => r.key),
      datasets: [
        {
          label: "周胜率 %",
          data: rows.map((r) => r.wr),
          borderColor: "#0969da",
          backgroundColor: "rgba(9,105,218,.12)",
          fill: true,
          tension: 0.3,
        },
        {
          label: "周场次",
          data: rows.map((r) => r.n),
          borderColor: "#d1a054",
          yAxisID: "y1",
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } },
        y1: { position: "right", grid: { drawOnChartArea: false } },
      },
    },
  });
}

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
  if (o.hidden) {
    $("k-total-ci").textContent +=
      ` · 另有 ${o.hidden} 场未计入（Bot 局，见下方对局列表）`;
  }
  bigCard("k-play", "k-play-ci", o.on_play);
  bigCard("k-draw", "k-draw-ci", o.on_draw);

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

  // 先后手对比图
  const hasP = o.on_play.n > 0, hasD = o.on_draw.n > 0;
  if (pdChart) pdChart.destroy();
  pdChart = barChart(
    "c-pd",
    ["先手", "后手"],
    [hasP ? o.on_play.wr : 0, hasD ? o.on_draw.wr : 0],
    [hasP ? o.on_play.lo : 0, hasD ? o.on_draw.lo : 0],
    [hasP ? o.on_play.hi : 0, hasD ? o.on_draw.hi : 0],
    ["#c94a3d", "#1a7f5a"]
  );

  // 周趋势
  trendChartDraw(o.trend_weekly.slice(-12));

  // 按赛事横向条形图
  if (eventChart) eventChart.destroy();
  const ev = o.by_event.slice(0, 8);
  eventChart = new Chart($("c-event"), {
    type: "bar",
    data: {
      labels: ev.map((r) => r.label || r.key),
      datasets: [{ data: ev.map((r) => r.wr), backgroundColor: "#5a7db8", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: items => items.length ? ev[items[0].dataIndex].key : ""
      } } },
      scales: { x: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } },
    },
  });
}

function mulliganView(m) {
  const rows = Object.fromEntries(m.by_mulligan.map(row => [row.key, row]));
  const clean = rows.clean || {n:0,wr:null}, mulligan = rows.mulligan || {n:0,wr:null};
  const unknown = rows.unknown?.n || 0, known = clean.n + mulligan.n, total = known + unknown;
  if (!total) return {summary:"当前筛选没有可用的调度记录。", detail:"没有有胜负结果的对局可统计。"};
  const coverage = `${known}/${total} 场（${(100 * known / total).toFixed(1)}%）`;
  const rate = row => row.wr == null ? "胜率待确认" : `整场胜率 ${row.wr}%`;
  const summary = known
    ? `调度资料覆盖 ${coverage}。调度过 ${mulligan.n} 场，${rate(mulligan)}；已记录且未调度 ${clean.n} 场，${rate(clean)}。`
    : `当前 ${total} 场对局均没有可用的调度记录。`;
  const distTotal = m.kept_on_dist.reduce((sum, row) => sum + row.count, 0);
  const dist = m.kept_on_dist.map(row => `调度 ${row.kept_on} 次后留牌 ${row.count} 局`).join(" · ") || "无逐局记录";
  const detail = `有效分母：${total} 场有胜负结果的对局；调度已知 ${known} 场，未知 ${unknown} 场。`
    + ` 逐局留牌分布共 ${distTotal} 局：${dist}。BO3 的胜率按整场结果统计，逐局留牌分布按游戏局统计；两者分母不能混用。`
    + ` 调度资料来自客户端日志中的我方留牌事件，旧记录或来源缺少事件时保持未知。`;
  return {summary, detail};
}

async function loadMulligans() {
  const v = uiVersion;
  const m = await api("/api/mulligans");
  if (isStale(v)) return;
  const view = mulliganView(m);
  $("mull-box").innerHTML = `<p>${esc(view.summary)}</p>
    <details class="detail-fold"><summary>查看逐次留牌分布、未知量与来源</summary><div class="ci">${esc(view.detail)}</div></details>`;
}

const ARCH_ZH = { Aggro: "快攻", Control: "控制", Combo: "组合技", Ramp: "Ramp", Midrange: "中速", Other: "其他" };
const ARCH_COLOR = { Aggro: "#c94a3d", Control: "#5a7db8", Combo: "#8a63c9", Ramp: "#1a7f5a", Midrange: "#d18f4e", Other: "#6b7280" };

function archTag(a) {
  if (!a) return `<span class="tag">未标</span>`;
  return `<span class="tag" style="background:${ARCH_COLOR[a] || "#eef1f5"};color:#fff">${ARCH_ZH[a] || a}</span>`;
}

function archSelect(key, current) {
  const opts = ["", ...Object.keys(ARCH_ZH)]
    .map((k) => `<option value="${k}" ${k === (current || "") ? "selected" : ""}>${k ? ARCH_ZH[k] : "(清除)"}</option>`)
    .join("");
  // 主将名可能含单引号（如 Harvest's Hand），inline onchange 需转义防语法炸
  const safe = key.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  return `<select onchange="tagOpp('${safe}', this.value)">${opts}</select>`;
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

async function loadCommanders() {
  const v = uiVersion;
  const j = await api("/api/commanders");
  if (isStale(v)) return;
  const c = j.rows || [];
  const cov = j.coverage;
  let hint = "";
  if (c.length) {
    const auto = c.filter((r) => r.archetype).length;
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
        <td><details><summary>${cardMarkup(r)}</summary><div class="ci">${esc(r.name_en || "英文未记录")}<br>${esc(r.name_source)} · grpId:${esc(r.key)}</div></details></td>
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
  const hint = [card.name_en, card.name_source, card.key ? `grpId:${card.key}` : ""].filter(Boolean).join(" · ");
  return `<span title="${esc(hint)}">${esc(card.name)}</span>`;
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

function matchDetails(r) {
  const items = [
    ["回合", r.total_turns ?? "未记录"], ["用时", fmtDur(r.duration_sec)],
    ["我方调度", r.my_mulls ?? "未记录"], ["结束原因", endReasonLabel(r.end_reason)],
    ["数据来源", sourceLabel(r.source)], ["对局编号", r.match_id || "未记录"],
  ];
  if (r.my_deck_id) items.push(["套牌 ID", r.my_deck_id]);
  if (r.my_deck_version) items.push(["构筑版本", r.my_deck_version]);
  if (r.is_bot) items.push(["记录标记", "Bot 局"]);
  if (r.is_abnormal || r.abnormal_reason) items.push(["诊断标记", r.abnormal_reason || "异常"]);
  return `<details><summary>查看</summary><div class="match-details ci">${items.map(
    ([label,value]) => `<span><strong>${esc(label)}：</strong>${esc(value)}</span>`
  ).join("")}</div></details>`;
}

function gameDetails(r) {
  const mode = r.match_mode || "未知";
  const games = r.games || [];
  if (!games.length) return `<strong>${esc(mode)}</strong><div class="ci">逐局未记录</div>`;
  const rows = games.map(game => {
    const playDraw = game.play_draw === "play" ? "先手" : game.play_draw === "draw" ? "后手" : "先后手未知";
    const result = game.result === "win" ? "胜" : game.result === "loss" ? "负" : "结果待确认";
    const reason = game.reason ? ` · ${endReasonLabel(game.reason)}` : "";
    const duration = game.duration_sec == null ? "" : ` · ${fmtDur(game.duration_sec)}`;
    return `<div class="game-row">第 ${esc(game.game_no ?? "?")} 局 · ${playDraw} · ${result}${esc(reason)}${duration}</div>`;
  }).join("");
  return `<strong>${esc(mode)}</strong><details><summary>查看 ${games.length} 局</summary><div class="game-list ci">${rows}</div></details>`;
}

function deckLink(r, label) {
  const name = label || r.my_deck_tag || "套牌未记录";
  if (!(r.my_deck_tag || r.my_deck_id || r.my_deck_version)) return esc(name);
  const payload = encodeURIComponent(JSON.stringify({
    deck: r.my_deck_tag || "", deck_id: r.my_deck_id || "",
    deck_version: r.my_deck_version || "",
  }));
  return `<button class="link-button deck-open" data-deck="${esc(payload)}" title="查看这套牌的独立详情">${esc(name)}</button>`;
}

function matchRow(r) {
  const ownCommander = r.my_cards?.length || r.my_cmdrs?.length
    ? cardsMarkup(r.my_cards, r.my_cmdrs) : "未记录";
  return `<tr>
    <td>${fmtTime(r.start_time)}</td><td>${eventMarkup(r.event_id, r.event_label)}</td>
    <td>${gameDetails(r)}</td>
    <td class="clip" title="${esc(r.my_deck_tag || "套牌未记录")}">${deckLink(r)}</td>
    <td>${ownCommander}</td>
    <td>${r.play_draw === "play" ? "先手" : r.play_draw === "draw" ? "后手" : "未知"}</td>
    <td>${r.my_result === "win" ? "胜" : r.my_result === "loss" ? "负" : "待确认"}</td>
    <td>${esc(r.opponent_name || "–")}</td><td>${opponentProfileMarkup(r, r.opp_cards)}</td>
    <td>${matchDetails(r)}</td>
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
  $("m-day-label").textContent = matchDay || "全部日期";
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
    `<tr><td colspan="10"><strong>${mode === "event" ? eventMarkup(rows[0].event_id, rows[0].event_label) : mode === "commander" ? cardsMarkup(rows[0].opp_cards, rows[0].opp_cmdrs) : mode === "deck" ? deckLink(rows[0], key) : esc(key)}</strong> · 当前显示 ${rows.length} 场</td></tr>`
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
    <td>${esc(row.my_deck_tag || "未命名")}</td>
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
    ${item.probability ? `<details><summary>为什么这段连续记录值得突出</summary><p>${esc(item.probability.explanation)}</p></details>` : ""}
  </article>`).join("");
}


function deckJourneyRender(journey) {
  const sec = $("deck-journey");
  if (!journey || !journey.days || !journey.days.length) {
    sec.hidden = true;
    return;
  }
  sec.hidden = false;
  const days = journey.days;
  $("deck-journey-lead").textContent =
    `共 ${journey.day_count} 个有记录日` +
    (journey.span_days ? `，跨度约 ${journey.span_days} 天` : "") +
    (journey.unknown_day ? `；另 ${journey.unknown_day} 场日期未知未入轴` : "") +
    "。旅程按当前身份全部记录，不随上方「近 20 场」截断。";
  $("deck-journey-body").innerHTML = days.map(d => {
    const wr = d.win_rate && d.win_rate.wr != null ? `${d.win_rate.wr}%` : "–";
    return `<tr>
      <td><button type="button" class="link-button journey-day" data-day="${esc(d.date)}">${esc(d.date)}</button></td>
      <td class="num">${d.n}</td>
      <td>${d.wins} 胜 ${d.losses} 负 <span class="ci">${wr}</span></td>
      <td>先 ${d.play} · 后 ${d.draw}${d.unknown_play_draw ? ` · 未 ${d.unknown_play_draw}` : ""}</td>
      <td class="clip" title="${esc((d.events||[]).join("、"))}">${esc((d.events||[]).join("、") || "–")}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="5" class="ci">没有可入轴的日期</td></tr>`;
  const marks = journey.version_marks || [];
  $("deck-journey-versions").innerHTML = marks.length
    ? marks.map(m => `<div class="summary-item"><strong>${esc(m.date)}</strong><span>改为构筑 ${esc(String(m.version).slice(0,12))}… → 此后 ${m.n_after} 场（${m.wins} 胜 ${m.losses} 负）</span></div>`).join("")
    : `<p class="ci">尚未记录到构筑版本变更。</p>`;
}


function deckCommanderEnvRender(env) {
  const sec = $("deck-commander-env");
  if (!env || !env.applicable || !(env.rows || []).length) {
    sec.hidden = true;
    return;
  }
  sec.hidden = false;
  const mine = (env.my_commanders || []).map(c => c.name).join(" / ") || "主将未记录";
  $("deck-commander-env-lead").textContent =
    `我方主将：${mine} · 对手主将已知 ${env.known}/${env.eligible} 场`;
  const pd = env.play_draw || {};
  const rate = pd.play_rate != null ? `先手率 ${pd.play_rate}%` : "";
  $("deck-commander-env-pd").textContent =
    `先后手：先 ${pd.play} · 后 ${pd.draw}${pd.unknown_pd ? ` · 未知 ${pd.unknown_pd}` : ""}${rate ? " · " + rate : ""}`;
  $("deck-commander-env-body").innerHTML = env.rows.map(row => {
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
  }).join("") || `<tr><td colspan="8" class="ci">暂无可列出的对手主将</td></tr>`;
  $("deck-commander-env-note").textContent = env.note || "";
}

async function loadDeckDetail() {
  if (!deckAnchor) return;
  const request = ++deckRequest;
  $("deck-loading").hidden = false;
  $("deck-loading").textContent = "正在读取套牌详情…";
  $("deck-summary").innerHTML = "";
  $("deck-journey").hidden = true;
  $("deck-commander-env").hidden = true;
  $("deck-observations").hidden = true;
  $("deck-commanders").hidden = true;
  $("deck-records").hidden = true;
  const p = new URLSearchParams({scope:deckScope, exclude_bot:String($("f-bot").classList.contains("on"))});
  for (const key of ["deck", "deck_id", "deck_version"]) if (deckAnchor[key]) p.set(key, deckAnchor[key]);
  if ($("deck-mode").value) p.set("mode", $("deck-mode").value);
  if ($("deck-version").value) p.set("version", $("deck-version").value);
  if (deckCommander) p.set("opponent_commander", deckCommander);
  if (deckObservation) p.set("observation", deckObservation);
  try {
    const response = await fetch(`/api/deck_detail?${p}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `读取失败（${response.status}）`);
    }
    const r = await response.json();
    if (request !== deckRequest) return;
    $("deck-title").textContent = r.title;
    const kindLabel = r.deck_kind?.label || "";
    $("deck-identity").textContent =
      (kindLabel ? `【${kindLabel}】 ` : "") +
      r.identity.note +
      (r.identity.aliases.length > 1 ? ` 历史名称：${r.identity.aliases.join("、")}。` : "");
    const currentMode = r.selected_mode || "";
    $("deck-mode").innerHTML = `<option value="">全部</option>`
      + r.modes.map(item => `<option value="${esc(item.value)}">${esc(item.label)}（${item.n} 场）</option>`).join("");
    $("deck-mode").value = currentMode;
    const currentVersion = r.selected_version || "";
    $("deck-version").innerHTML = `<option value="">全部构筑版本</option>`
      + r.versions.map(item => `<option value="${esc(item.value)}" title="${esc(item.value)}">${esc(item.label)}（${item.n} 场）</option>`).join("")
      + (r.unknown_version ? `<option value="__unknown__">版本未记录（${r.unknown_version} 场）</option>` : "");
    $("deck-version").value = currentVersion;
    $("deck-summary").innerHTML = deckSummaryMarkup(r);
    deckJourneyRender(r.journey);
    deckCommanderEnvRender(r.commander_env);
  $("deck-observations").hidden = false;
    $("deck-observation-body").innerHTML = deckObservationMarkup(r.observations, r.selected_observation?.key || "");
    $("deck-observation-note").textContent = r.observations.note;
    $("deck-version-note").textContent = deckVersionNote(r);
    const commanders = r.opponent_commanders;
    $("deck-commanders").hidden = false;
    $("deck-commander-coverage").textContent = deckCommanderCoverage(commanders);
    $("deck-commander-table").hidden = !commanders.rows.length;
    $("deck-commander-body").innerHTML = deckCommanderRows(commanders, r.selected_commander?.key || "");
    $("deck-commander-note").textContent = commanders.known
      ? `出现占比以主将已知的 ${commanders.known} 场为分母。每位主将在同一场最多计一次；${commanders.multi_commander_matches ? `其中 ${commanders.multi_commander_matches} 场记录了双主将，故各行占比之和可能超过 100%。` : "当前范围没有双主将对局。"}这是对局出现次数，不是不同玩家数。`
      : "没有可识别的对手主将，不按套牌名或其他字段猜测。";
    $("deck-loading").hidden = true;
    $("deck-records").hidden = false;
    $("deck-record-title").textContent = r.selected_commander ? `对阵 ${r.selected_commander.name} 的全部记录`
      : r.selected_observation ? `“${r.selected_observation.headline}”的依据` : "范围内对局（核对用）";
    $("deck-record-all").hidden = !(r.selected_commander || r.selected_observation);
    $("deck-record-count").textContent = r.records_truncated ? `共 ${r.records_total} 场，显示最近 200 场` : `共 ${r.records_total} 场`;
    $("deck-record-body").innerHTML = r.records.map(row => deckRecordRow(row, r.versions)).join("")
      || `<tr><td colspan="8" class="ci">当前范围没有对局</td></tr>`;
  } catch (error) {
    if (request !== deckRequest) return;
    $("deck-loading").hidden = false;
    $("deck-loading").textContent = error.message;
  }
}

function jumpToDaily(day) {
  if (!day) return;
  $("daily-date").value = day;
  loadDaily();
  const el = document.getElementById("daily-section") || document.querySelector("#daily-date");
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
  deckAnchor = anchor;
  deckScope = "last20";
  deckCommander = "";
  deckObservation = "";
  $("deck-mode").innerHTML = `<option value="">全部</option>`;
  $("deck-version").innerHTML = `<option value="">全部构筑版本</option>`;
  for (const button of document.querySelectorAll("#deck-scope button")) button.classList.toggle("on", button.dataset.scope === deckScope);
  const dialog = $("deck-dialog");
  if (!dialog.open) dialog.showModal();
  loadDeckDetail();
}

function dailyQualityView(summary, report) {
  if (!summary.n && !report.unknown_date) {
    return {hidden:true, summary:"资料说明", detail:""};
  }
  const issues = [];
  const deckMissing = Math.max(0, summary.n - summary.deck_known);
  const commanderMissing = Math.max(0, summary.commander_eligible - summary.commander_known);
  if (deckMissing) issues.push(`${deckMissing} 场套牌未记录`);
  if (commanderMissing) issues.push(`${commanderMissing} 场争锋主将未记录`);
  if (report.unknown_date) issues.push(`${report.unknown_date} 场日期未知`);
  const parts = [
    `调度 ${summary.mulligan_known}/${summary.n} 场`,
    `套牌 ${summary.deck_known}/${summary.n} 场`,
  ];
  if (summary.commander_eligible) {
    parts.push(`争锋对手主将 ${summary.commander_known}/${summary.commander_eligible} 场`);
  }
  let detail = `当前日期有效分母：${summary.n} 场；${parts.join("；")}。`;
  if (report.unknown_date) detail += ` 另有 ${report.unknown_date} 场日期未知，未分配到具体日期。`;
  detail += " 缺失资料只影响对应维度，不把未知当作零。";
  return {
    hidden:false,
    summary:issues.length ? `资料说明：${issues.join(" · ")}` : "资料覆盖说明",
    detail,
  };
}

let dailyRequest = 0, dailyScope = "", dailyLatest = null;
async function loadDaily() {
  const request = ++dailyRequest;
  const scope = `${params()}|${$("daily-date").value}`;
  if (dailyScope !== scope) {
    $("daily-evidence").hidden = true;
    $("daily-evidence").open = false;
    $("daily-latest").hidden = true;
    $("daily-plain").textContent = "正在读取本地战报…";
    $("daily-plain").className = "";
    for (const id of ["daily-summary", "daily-events", "daily-quality", "daily-asof", "daily-pd-streaks", "daily-history-lead", "daily-history-items", "daily-history-note"]) $(id).textContent = "";
    $("daily-history-section").hidden = true;
    $("daily-history-details").open = false;
    $("daily-quality-details").hidden = true;
    $("daily-quality-details").open = false;
  }
  dailyScope = scope;
  const extra = $("daily-date").value ? {day:$("daily-date").value} : {};
  let r;
  try { r = await api("/api/daily", extra); }
  catch (error) {
    if (request === dailyRequest && scope === `${params()}|${$("daily-date").value}`) {
      $("daily-plain").textContent = "战报读取失败，请重试。";
      $("daily-plain").className = "";
      $("daily-evidence").hidden = true;
      $("daily-latest").hidden = true;
      $("daily-quality-details").hidden = true;
    }
    return;
  }
  if (request !== dailyRequest || scope !== `${params()}|${$("daily-date").value}`) return;
  const s = r.summary;
  $("daily-date").value = r.date;
  dailyScope = `${params()}|${r.date}`;
  dailyLatest = r.latest_date;
  $("daily-latest").hidden = s.n > 0 || !dailyLatest;
  $("daily-evidence").hidden = !(r.highlights || []).length;
  $("daily-evidence-body").innerHTML = (r.highlights || []).map(f => {
    const ids = new Set(f.match_ids);
    const rows = (r.highlight_records || []).filter(x => ids.has(x.match_id));
    return `<p><strong>${esc(f.text)}</strong></p><p class="ci">${esc(r.date)} · 当前筛选 · 相关记录 ${f.n} 场／所述范围 ${f.denominator} 场；先后手为首局口径。</p>`
      + (f.probability ? `<details><summary>展开概率口径</summary><p class="ci">${esc(f.probability.explanation)}</p></details>` : "")
      + rows.map(x => `<p>${fmtTime(x.start_time)} · ${esc(x.my_deck_tag || "套牌未记录")} · ${eventMarkup(x.event_id, x.event_label)} · ${{play:"先手",draw:"后手"}[x.play_draw] || "先后手未记录"} · ${{win:"胜",loss:"负"}[x.my_result] || "结果待确认"}${x.commander_names.length ? ` · ${cardsMarkup(x.commander_cards, x.commander_names)}` : ""}</p>`).join("");
  }).join("");
  $("daily-asof").textContent = r.is_today ? "截至目前的已记录对局" : "历史日战报";
  $("daily-plain").textContent = r.plain;
  const dailyLevel = r.highlights?.[0]?.level;
  $("daily-plain").className = dailyLevel ? `daily-highlight ${dailyLevel}` : "";
  const pd = r.play_draw;
  $("daily-summary").innerHTML = `<div class="card"><h2>当天胜率</h2><div class="big">${s.win_rate.wr ?? "–"}%</div><div class="ci">${s.wins} 胜 ${s.losses} 负 · ${s.win_rate.n} 场有胜负</div></div>
    <div class="card"><h2>当天先手率</h2><div class="big">${pd?.day.play_rate ?? "–"}%</div><div class="ci">先手 ${s.play} 场 · 后手 ${s.draw} 场</div></div>
    <div class="card"><h2>当天后手率</h2><div class="big">${pd?.day.draw_rate ?? "–"}%</div><div class="ci">${s.play_rate.n} 场先后手已知 · 未知 ${s.unknown_pd} 场</div></div>`;
  if (pd) {
    const d = pd.day_streaks, h = pd.history_streaks;
    const current = h.current_side ? `连续${h.current_side === "play" ? "先手" : "后手"} ${h.current_n} 场` : (h.reason || "无记录");
    $("daily-pd-streaks").innerHTML = `<p><strong>当天最长</strong>：连续先手 ${d.longest_play ?? "–"} 场 · 连续后手 ${d.longest_draw ?? "–"} 场</p>
      <p><strong>截至所选日期的当前连续</strong>：${esc(current)}${h.last_time ? ` · 末场 ${fmtTime(h.last_time)}` : ""}</p>
      <p class="ci">截至所选日期的历史最长：先手 ${h.longest_play ?? "–"} 场 · 后手 ${h.longest_draw ?? "–"} 场。当前筛选内、按比赛首局统计；未知先后手或同时间记录打断连续段。${h.reason && h.longest_play == null ? esc(h.reason)+"。" : ""}</p>`;
  }
  $("daily-events").innerHTML = r.events.map(e => `<p><strong>${eventMarkup(e.event, e.label)}</strong> · ${e.n} 场 · ${e.wins} 胜 ${e.losses} 负 · 先手 ${e.play} / 后手 ${e.draw} / 未知 ${e.unknown_pd}</p>`).join("")
    + (s.top_commanders.length ? `<p>常遇主将：${s.top_commanders.map(c => `${cardMarkup(c)} ${c.n} 场`).join("、")}</p>` : "")
    + (r.modes || []).map(m => `<p>${esc(m.mode)}：${m.n} 场 · ${m.wins} 胜 ${m.losses} 负（整场胜负，首局先后手）</p>`).join("")
    + (r.opponent_types?.total ? `<p>构筑对手类型资料：${r.opponent_types.known}/${r.opponent_types.total} 场。${Object.entries(r.opponent_types.rows).map(([k,v]) => `${esc(ARCH_ZH[k] || k)} ${v} 场`).join("、") || "尚无逐场标注，不推测对手构筑。"}</p>` : "");
  const history = r.history_summary;
  const historyItems = history?.items || [];
  const hasBaseline = historyItems.some(i => i.delta_pp != null);
  // 无基线不展示空对比（VISION V0）
  $("daily-history-section").hidden = !hasBaseline;
  if (hasBaseline) {
    $("daily-history-lead").innerHTML = `<p><strong>${esc(history.headline)}</strong></p>`;
    $("daily-history-items").innerHTML = historyItems
      .filter(i => i.delta_pp != null)
      .map(item => `<p>${esc(item.text)}${item.small_sample ? " <span class=\"ci\">当天样本较少，仅描述。</span>" : ""}</p>`).join("");
    $("daily-history-note").textContent = history.note;
  }
  const quality = dailyQualityView(s, r);
  $("daily-quality-details").hidden = quality.hidden;
  $("daily-quality-summary").textContent = quality.summary;
  $("daily-quality").textContent = quality.detail;
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
  $("event-name-list").innerHTML = f.events.map(e => `<p>${esc(e.label)}<br><code>${esc(e.value)}</code></p>`).join("") || "当前范围无赛事";
  fillSelect("f-deck", f.decks);
  $("open-filter-deck").disabled = !$("f-deck").value;
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
    $("watch-txt").textContent = s.last_error ? `解析待重试：${s.last_error}` : s.watching
      ? `监听中 · 库内 ${s.db.matches} 场`
      : `监听未启用 · 库内 ${s.db.matches} 场`;
  } catch {
    $("watch-txt").textContent = "服务不可达";
  }
}

async function reload() {
  await Promise.all([
    loadOverview(), loadMulligans(), loadCommanders(), loadOpponentTypes(), loadMatches(), loadStatus(),
    loadRankCurve(), loadTargeting(), loadDaily(),
  ]);
}

// ---------- 你被针对了吗（§3.5） ----------
let tiWindow = "30";

function dimVerdictColor(v) {
  return v === "高度可疑" ? "var(--win)"
    : v === "偏邪门" ? "#d4501a"
    : v === "有点怪" ? "var(--warn)"
    : "var(--loss)";
}

function dimBar(d) {
  return `<div class="dim"><div class="dim-head"><strong>${esc(d.label)}</strong>
    <span class="tag">${esc(d.verdict || "仅记录／资料不足")}</span>
    ${d.enough ? `<span class="ci">p=${Number(d.p).toPrecision(3)} · ${d.n} 场</span>` : ""}</div>
    <div class="dim-plain">${esc(d.plain)}</div></div>`;
}

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
  $("ti-summary").innerHTML = targetingSummaryMarkup(r);
  const visibleDimensions = Object.entries(r.dimensions).filter(([key]) => key !== "matchup" || r.summary.commander_eligible > 0);
  $("ti-details-summary").textContent = `查看详细分布、资料覆盖与统计口径（${visibleDimensions.length} 项）`;
  $("ti-dims").innerHTML = visibleDimensions.map(([,value]) => dimBar(value)).join("")
    + (r.comparison ? `<p>同范围历史战绩：可比 ${r.comparison.covered}/${r.comparison.total_decided} 场${r.comparison.adjusted_delta_pp == null ? "；暂无足够基线。" : `；较按当前构成加权的此前胜率相差 ${r.comparison.adjusted_delta_pp} 个百分点。`}</p>` : "");
  const nem = $("ti-nemeses");
  if (r.nemeses && r.nemeses.length) {
    nem.textContent = "近期低胜率对手（小样本记录）：" + r.nemeses.map(
      (x) => `${x.name}（${x.archetype} ${x.n} 场 ${x.wr}%）`).join("、");
  } else {
    nem.textContent = "";
  }
  $("ti-note").textContent = r.disclaimer;
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
$("f-deck").addEventListener("change", () => {
  $("open-filter-deck").disabled = !$("f-deck").value;
  matchOffset=0;bumpUiVersion();reload();
});
$("f-bot").addEventListener("click", async () => {
  $("f-bot").classList.toggle("on");
  await onFilterChange();
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
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div class="card" style="border-color:#c94a3d">加载失败：${e.message}<pre style="white-space:pre-wrap;font-size:11px">${e.stack || ""}</pre></div>`
  );
});
$("daily-date").addEventListener("change", loadDaily);
$("daily-latest").addEventListener("click", () => {if(dailyLatest) {$("daily-date").value=dailyLatest;loadDaily();}});
$("daily-today").addEventListener("click", () => {$("daily-date").value=localDay(new Date());loadDaily();});
$("daily-yesterday").addEventListener("click", () => {const d=new Date();d.setDate(d.getDate()-1);$("daily-date").value=localDay(d);loadDaily();});
$("daily-matches").addEventListener("click", () => {matchDay=$("daily-date").value;matchOffset=0;loadMatches();});
$("m-all").addEventListener("click", () => {matchDay="";matchOffset=0;loadMatches();});
$("m-group").addEventListener("change", loadMatches);
$("m-more").addEventListener("click", () => {matchOffset+=matchLimit;loadMatches();});
$("m-prev").addEventListener("click", () => {matchOffset=Math.max(0,matchOffset-matchLimit);loadMatches();});
$("open-filter-deck").addEventListener("click", () => {
  if ($("f-deck").value) openDeck({deck:$("f-deck").value, deck_id:"", deck_version:""});
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
  try { openDeck(JSON.parse(decodeURIComponent(button.dataset.deck))); }
  catch { /* 畸形页面属性不发起查询 */ }
});
document.addEventListener("change", event => {
  const select = event.target.closest(".match-arch-select");
  if (select) tagMatch(select.dataset.matchId, select.value, select);
});
setInterval(() => {loadStatus(); if(!document.hidden) reload().catch(() => {});}, 15000);
