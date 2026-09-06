/* MTGA 先后手统计面板。所有数字来自 /api/*，前端不重算统计。 */
"use strict";

const $ = (sel) => sel.includes(" ") ? document.querySelector(sel) : document.getElementById(sel);
const fmtTime = (ms) =>
  ms ? new Date(ms).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–";
const fmtDur = (s) => {
  if (s == null) return "–";
  const m = Math.round(s / 60);
  return m >= 1 ? `${m}分` : `${Math.round(s)}秒`;
};

let pdChart = null, trendChart = null, eventChart = null, rankChart = null;
let rankTrack = "constructed";

function params() {
  const p = new URLSearchParams();
  p.set("exclude_abnormal", $("f-abn").classList.contains("on"));
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
  const o = await api("/api/overview");
  bigCard("k-total", "k-total-ci", o.total);
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
      labels: ev.map((r) => r.key),
      datasets: [{ data: ev.map((r) => r.wr), backgroundColor: "#5a7db8", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } },
    },
  });
}

async function loadMulligans() {
  const m = await api("/api/mulligans");
  const dist = m.kept_on_dist
    .map((d) => `第${d.kept_on}张后留 ${d.count} 次`)
    .join(" · ");
  const by = m.by_mulligan
    .map((r) => `<span class="tag ${r.key === "mulligan" ? "abn" : "loss"}">${r.key === "mulligan" ? "调度过" : "全留起手"} ${r.wr ?? "–"}%（${r.n}）</span>`)
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
  const r = await fetch("/api/opp_tag_by_name", { method: "POST", body: p });
  const j = await r.json();
  if (j.ok) reload();
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
      hint += ` · 样本覆盖 ${cov.with_cmdr}/${cov.total} 场（${pct}%，仅本地日志对局含对手主将，云史无此数据）`;
    }
  }
  $("cmdr-hint").textContent = hint;
  const tb = $("#t-cmdr tbody");
  tb.innerHTML = c
    .map(
      (r) => {
        const delta = r.on_play.n && r.on_draw.n ? (r.on_play.wr - r.on_draw.wr) : null;
        return `<tr>
        <td>${r.name}</td>
        <td>${archTag(r.archetype)}</td>
        <td class="num">${r.n}</td>
        <td class="num" style="color:${(r.wr ?? 0) >= 50 ? "var(--win)" : "var(--loss)"}">${r.wr ?? "–"}%</td>
        <td class="num">${r.on_play.n ? `${r.on_play.wr}% (${r.on_play.n})` : "–"}</td>
        <td class="num">${r.on_draw.n ? `${r.on_draw.wr}% (${r.on_draw.n})` : "–"}${delta != null ? ` <span class="ci">Δ${delta > 0 ? "+" : ""}${delta.toFixed(0)}</span>` : ""}</td>
        <td>${archSelect(r.name, r.archetype)}</td>
      </tr>`;
      }
    )
    .join("") || `<tr><td colspan="7" class="ci">暂无主将数据</td></tr>`;
}

async function loadMatches() {
  const m = await api("/api/matches");
  $("m-count").textContent = `共 ${m.total} 场（显示前 ${m.rows.length}）`;
  const tb = $("#t-m tbody");
  tb.innerHTML = m.rows
    .map((r) => {
      const tags = [];
      if (r.is_abnormal) tags.push(`<span class="tag abn">异常 ${r.abnormal_reason || ""}</span>`);
      if (r.is_bot) tags.push(`<span class="tag">Bot</span>`);
      if (r.source === "untapped") tags.push(`<span class="tag">云史</span>`);
      return `<tr>
        <td>${fmtTime(r.start_time)}</td>
        <td>${r.event_id || "–"}</td>
        <td>${r.play_draw === "play" ? "先手" : r.play_draw === "draw" ? "后手" : "–"}</td>
        <td><span class="tag ${r.my_result === "win" ? "win" : "loss"}">${r.my_result === "win" ? "胜" : r.my_result === "loss" ? "负" : "–"}</span></td>
        <td class="num">${r.total_turns ?? "–"}</td>
        <td class="num">${fmtDur(r.duration_sec)}</td>
        <td class="num">${r.my_mulls || 0}</td>
        <td>${r.opponent_name || "–"}</td>
        <td>${r.opp_cmdrs.map((c) => `<code>${c}</code>`).join(" ") || "–"}</td>
        <td class="ci">${(r.end_reason || "").replace("ResultReason_", "")}</td>
        <td>${tags.join(" ") || ""}</td>
      </tr>`;
    })
    .join("");
}

function fillSelect(sel, list) {
  const el = $(sel);
  const cur = el.value;
  el.innerHTML = `<option value="">全部</option>`;
  for (const it of list) {
    const op = document.createElement("option");
    op.value = it.value;
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
    $("watch-txt").textContent = s.watching
      ? `监听中 · 库内 ${s.db.matches} 场`
      : `监听未启用 · 库内 ${s.db.matches} 场`;
  } catch {
    $("watch-txt").textContent = "服务不可达";
  }
}

async function reload() {
  await Promise.all([
    loadOverview(), loadMulligans(), loadCommanders(), loadMatches(), loadStatus(),
    loadRankCurve(), loadTargeting(),
  ]);
}

// ---------- 你被针对了吗（§3.5） ----------
let tiWindow = "30";

function dimBar(d) {
  if (!d.enough) {
    return `<div class="dim dim-off">
      <span class="dim-name">${d.label}</span>
      <span class="dim-desc">样本 ${d.n} 场，不足 ${d.min_sample ?? ""} 不计分</span>
      <div class="bar-track"></div><span class="dim-score">–</span></div>`;
  }
  const score = d.score ?? 50;
  return `<div class="dim" ${score >= 70 ? "" : 'style="opacity:.85"'}>
    <span class="dim-name">${d.label}</span>
    <span class="dim-desc">${d.obs_desc} · ${d.exp_desc} · p=${d.p}</span>
    <div class="bar-track"><div class="bar-fill" style="width:${score}%"></div></div>
    <span class="dim-score">${Math.round(score)}</span></div>`;
}

async function loadTargeting() {
  const r = await api("/api/targeting", { window: tiWindow });
  const sc = $("ti-score"), lb = $("ti-label");
  if (r.composite == null) {
    sc.textContent = "–";
    lb.textContent = "样本不足，暂不计分";
  } else {
    sc.textContent = r.composite;
    lb.textContent = r.label;
    sc.style.color = r.composite >= 85 ? "var(--win)"
      : r.composite >= 70 ? "var(--warn)" : "var(--text)";
  }
  $("ti-dims").innerHTML = Object.values(r.dimensions).map(dimBar).join("");
  const nem = $("ti-nemeses");
  if (r.nemeses && r.nemeses.length) {
    nem.innerHTML = "克星预警：" + r.nemeses.map(
      (x) => `${x.name}（${x.archetype} ${x.n} 场 ${x.wr}%）`).join("、");
  } else {
    nem.textContent = "";
  }
  $("ti-note").textContent = r.disclaimer;
}

// 三级级联：赛制大类 → 赛事 → 套牌
// 赛制/赛事变化 → 重建下拉列表 + 刷新数据；套牌变化 → 只刷新数据
async function onFilterChange() {
  await loadFilters();
  await reload();
}
$("f-family").addEventListener("change", onFilterChange);
$("f-event").addEventListener("change", onFilterChange);
$("f-deck").addEventListener("change", reload);
$("f-abn").addEventListener("click", async () => {
  $("f-abn").classList.toggle("on");
  await onFilterChange();
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
setInterval(loadStatus, 5000);
