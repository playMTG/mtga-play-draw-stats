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

function params() {
  const p = new URLSearchParams();
  p.set("exclude_bot", $("f-bot").classList.contains("on"));
  const f = $("f-family").value, e = $("f-event").value, d = $("f-deck").value;
  if (f) p.set("family", f);
  if (e) p.set("event", e);
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
  const scope = String(params());
  const o = await api("/api/overview");
  if (scope !== String(params())) return;
  const rates = o.play_draw_rates;
  $("k-play-rate").textContent = rates.play_rate == null ? "无样本" : `${rates.play_rate}%`;
  $("k-draw-rate").textContent = rates.draw_rate == null ? "无样本" : `${rates.draw_rate}%`;
  $("k-play-rate-note").textContent = `先手 ${rates.play} 场 · 后手 ${rates.draw} 场 · 未知 ${rates.unknown} 场`;
  $("k-draw-rate-note").textContent = "全史 · 当前筛选 · 比例仅含先后手已知的有结果对局";
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

async function loadMulligans() {
  const m = await api("/api/mulligans");
  const dist = m.kept_on_dist
    .map((d) => `调度 ${d.kept_on} 次后留牌：${d.count} 局`)
    .join(" · ");
  const by = m.by_mulligan
    .map((r) => `<span class="tag ${r.key === "mulligan" ? "abn" : "loss"}">${r.key === "mulligan" ? "调度过" : r.key === "clean" ? "已知未调度" : "调度未知"} ${r.wr ?? "–"}%（${r.n}）</span>`)
    .join(" ");
  $("mull-box").innerHTML = `
    <div style="margin-bottom:8px">${by || "无数据"}</div>
    <div class="ci">调度留牌分布：${dist || "无"}</div>`;
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
  const j = await api("/api/commanders");
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

function matchRow(r) {
  const ownCommander = r.my_cards?.length || r.my_cmdrs?.length
    ? cardsMarkup(r.my_cards, r.my_cmdrs) : "未记录";
  return `<tr>
    <td>${fmtTime(r.start_time)}</td><td>${eventMarkup(r.event_id, r.event_label)}</td>
    <td class="clip" title="${esc(r.my_deck_tag || "套牌未记录")}">${esc(r.my_deck_tag || "套牌未记录")}</td>
    <td>${ownCommander}</td>
    <td>${r.play_draw === "play" ? "先手" : r.play_draw === "draw" ? "后手" : "未知"}</td>
    <td>${r.my_result === "win" ? "胜" : r.my_result === "loss" ? "负" : "待确认"}</td>
    <td>${esc(r.opponent_name || "–")}</td><td>${cardsMarkup(r.opp_cards, r.opp_cmdrs)}</td>
    <td>${matchDetails(r)}</td>
  </tr>`;
}

function eventMarkup(raw, label) {
  const name = label || raw || "赛事未记录";
  return `<span title="${esc(raw || '赛事未记录')}">${esc(name)}</span>`;
}

async function loadMatches() {
  const m = await api("/api/matches", { limit: matchLimit, offset: matchOffset, ...(matchDay ? {day:matchDay} : {}) });
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
    `<tr><td colspan="9"><strong>${mode === "event" ? eventMarkup(rows[0].event_id, rows[0].event_label) : mode === "commander" ? cardsMarkup(rows[0].opp_cards, rows[0].opp_cmdrs) : esc(key)}</strong> · 当前显示 ${rows.length} 场</td></tr>`
    + rows.map(matchRow).join("")).join("");
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
    for (const id of ["daily-summary", "daily-events", "daily-quality", "daily-asof", "daily-pd-streaks"]) $(id).textContent = "";
  }
  dailyScope = scope;
  const extra = $("daily-date").value ? {day:$("daily-date").value} : {};
  let r;
  try { r = await api("/api/daily", extra); }
  catch (error) {
    if (request === dailyRequest && scope === `${params()}|${$("daily-date").value}`) {
      $("daily-plain").textContent = "战报读取失败，请重试。";
      $("daily-evidence").hidden = true;
      $("daily-latest").hidden = true;
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
      + rows.map(x => `<p>${fmtTime(x.start_time)} · ${esc(x.my_deck_tag || "套牌未记录")} · ${eventMarkup(x.event_id, x.event_label)} · ${{play:"先手",draw:"后手"}[x.play_draw] || "先后手未记录"} · ${{win:"胜",loss:"负"}[x.my_result] || "结果待确认"}${x.commander_names.length ? ` · ${cardsMarkup(x.commander_cards, x.commander_names)}` : ""}</p>`).join("");
  }).join("");
  $("daily-asof").textContent = r.is_today ? "截至目前的已记录对局" : "历史日战报";
  $("daily-plain").textContent = r.plain;
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
    + (r.opponent_types?.total ? `<p>非主将赛事对手类型资料：${r.opponent_types.known}/${r.opponent_types.total} 场。${Object.entries(r.opponent_types.rows).map(([k,v]) => `${esc(k)} ${v} 场`).join("、") || "尚无已标注类型，不推测对手构筑。"}</p>` : "")
    + (r.comparison ? `<h3>与此前战绩比较</h3><p>${esc(r.comparison.baseline_window)} · 可比 ${r.comparison.covered}/${r.comparison.total_decided} 场</p>`
       + r.comparison.groups.map(g => `<p><strong>${eventMarkup(g.event, g.label)} · ${esc(g.mode)}</strong>${g.deck ? ` · ${esc(g.deck)}` : ""}<br>当天 ${g.current.wr ?? "–"}%（${g.current.n} 场），此前 ${g.baseline.wr ?? "–"}%（${g.baseline.n} 场）。${g.usable ? `相差 ${g.delta_pp > 0 ? "+" : ""}${g.delta_pp} 个百分点。` : ""}${esc(g.reason)}${g.small_sample ? "；当天小样本，仅描述。" : "。"}</p>`).join("") + `<p class="ci">${esc(r.comparison.note)}</p>` : "");
  $("daily-quality").textContent = `资料覆盖：调度 ${s.mulligan_known}/${s.n} · 套牌 ${s.deck_known}/${s.n} · 主将赛制对手主将 ${s.commander_known}/${s.commander_eligible}。${r.unknown_date ? `另有 ${r.unknown_date} 场日期未知，未分配到具体日期。` : ""}`;
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
  const f = await api("/api/filters");
  fillSelect("f-family", f.families || []);
  fillSelect("f-event", f.events);
  $("event-name-list").innerHTML = f.events.map(e => `<p>${esc(e.label)}<br><code>${esc(e.value)}</code></p>`).join("") || "当前范围无赛事";
  fillSelect("f-deck", f.decks);
}

/* ---------- 段位曲线（M4） ---------- */
const RANK_ZH = ["青铜", "白银", "黄金", "铂金", "钻石"];
const scoreLabel = (s) =>
  s >= 21 ? "秘稀" : `${RANK_ZH[Math.floor((s - 1) / 4)] || "?"}${4 - ((s - 1) % 4)}`;

async function loadRankCurve() {
  const r = await fetch(`/api/rank_curve?track=${rankTrack}`);
  const j = await r.json();
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
    loadOverview(), loadMulligans(), loadCommanders(), loadMatches(), loadStatus(),
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

async function loadTargeting() {
  const r = await api("/api/targeting", { window: tiWindow });
  const sc = $("ti-score"), lb = $("ti-label");
  if (r.composite == null) {
    sc.textContent = "分项观察";
    sc.style.fontSize = "20px";
    lb.textContent = "以资料覆盖和具体偏差为准";
  } else {
    sc.textContent = r.composite;
    const nEnough = Object.values(r.dimensions).filter((d) => d.enough).length;
    lb.textContent = `${r.label}（${nEnough} 个维度综合，50 分＝正常）`;
    sc.style.color = r.composite >= 85 ? "var(--win)"
      : r.composite >= 70 ? "var(--warn)" : "var(--text)";
  }
  $("ti-dims").innerHTML = Object.entries(r.dimensions).filter(([key]) => key !== "matchup" || r.summary.commander_eligible > 0).map(([,value]) => dimBar(value)).join("")
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

// 三级级联：赛制大类 → 赛事 → 套牌
// 赛制/赛事变化 → 重建下拉列表 + 刷新数据；套牌变化 → 只刷新数据
async function onFilterChange() {
  matchOffset = 0;
  await loadFilters();
  await reload();
}
$("f-family").addEventListener("change", () => {$("f-event").value="";$("f-deck").value="";onFilterChange();});
$("f-event").addEventListener("change", () => {$("f-deck").value="";onFilterChange();});
$("f-deck").addEventListener("change", () => {matchOffset=0;reload();});
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
setInterval(() => {loadStatus(); if(!document.hidden) reload().catch(() => {});}, 15000);
