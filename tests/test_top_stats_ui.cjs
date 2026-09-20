const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const elements = new Map();
const $ = id => {if(!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',hidden:false});return elements.get(id);};

// 顶部三张统计卡（今天/本周/本月/总对局）的渲染。切片从 `RANGE_LABEL` 起到
// 「首页入口」那节前一行止：中间就是 rangeLabel／isDayString／todaySideLine／
// renderTodayLines／renderTopCards，自洽、不牵进 fetch 与 DOM。
// 终点**不能**用 `function fillSelect`（那是 test_daily_ui.cjs 的终点）：从这里到
// `fillSelect` 隔着七百多行顶层代码，里面一堆 `$("...").addEventListener(...)`，
// 在假 DOM 上直接崩——2026-09-20 就这么踩过一次，报错还落在无关的 cmdr-sort 上。
// statsRange 是文件开头的状态变量（不在切片内），显式注入；bigCard 与
// applyFormatFocus 是切片外的依赖，用最小实现顶替（它们各有自己的守卫）。
const context = vm.createContext({
  $, esc:String, statsRange:"all",
  bigCard:(id, ci, w) => {
    $(id).textContent = w.n ? `${w.wr}%` : "无样本";
    $(ci).textContent = w.n ? `${w.wins}胜 / ${w.n}场` : "";
  },
  applyFormatFocus:() => {},
});
const START = 'const RANGE_LABEL = {';
const END = '/* ---------- 首页入口：最近在打的套牌（V3 收尾） ---------- */';
const start = source.indexOf(START);
const end = source.indexOf(END);
assert.ok(start > 0, `切片起点未找到：${START}`);
assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
vm.runInContext(source.slice(start, end), context);

// 范围那一块与 today 那一块刻意给不同的数字：前者是「所选范围」，后者恒为今天。
// 这样才照得出「选本周时把本周的数字标成今日」这类错（2026-09-20 改掉的老 bug）。
const response = () => ({
  range: "all",
  total: {n:10837, wins:6169, wr:56.9, lo:56, hi:57.9},
  on_play: {n:5310, wins:3333, wr:62.8, lo:61.5, hi:64.1},
  on_draw: {n:5512, wins:2827, wr:51.3, lo:50, hi:52.6},
  play_draw_rates: {play:5310, draw:5512, unknown:15, play_rate:49.1, draw_rate:50.9},
  today: {
    total: {n:4, wins:3, wr:75, lo:30, hi:95},
    on_play: {n:3, wins:2, wr:66.7, lo:20, hi:94},
    on_draw: {n:1, wins:1, wr:100, lo:20, hi:100},
    play_draw_rates: {play:3, draw:1, unknown:0, play_rate:75, draw_rate:25},
  },
  format_focus: {},
});

const o = response();
context.renderTopCards(o);
assert.equal($('k-total-title').textContent, '全史总胜率', '总对局应叫「全史总胜率」');
assert.equal($('k-total').textContent, '56.9%');
assert.equal($('k-total-ci').textContent, '6169胜 / 10837场');
assert.equal($('k-play-rate').textContent, '49.1%');
assert.equal($('k-play-rate-note').textContent, '先手 5310 场 · 后手 5512 场 · 未知 15 场');
assert.equal($('k-draw-rate-note').textContent, '全史 · 当前筛选 · 比例仅含先后手已知的有结果对局');
assert.equal($('k-play-ci').textContent, '先手胜率 62.8% · 95% CI 61.5–64.1 · 3333胜/5310场');
assert.equal($('pd-dist-scope').textContent, '全史', '分布条要写明自己跟的是哪个范围');
// 「今日…」那三行来自 today 块，不是上面的范围块
assert.equal($('k-total-today').textContent, '今日 3 胜 1 负 · 胜率 75%');
assert.equal($('k-play-today').textContent, '今日先手率 75% · 先手胜率 66.7%（2 胜 / 3 场）');
assert.equal($('k-draw-today').textContent, '今日后手率 25% · 后手胜率 100%（1 胜 / 1 场）');

// 切到「本周」：上面换成本周的数字，下面那行**仍然**是今天的数字
const week = response();
week.range = 'week';
week.total = {n:77, wins:47, wr:61, lo:50, hi:71};
week.on_play = {n:37, wins:25, wr:67.6, lo:52, hi:80};
week.on_draw = {n:36, wins:18, wr:50, lo:35, hi:65};
week.play_draw_rates = {play:37, draw:36, unknown:4, play_rate:50.7, draw_rate:49.3};
context.statsRange = 'week';
context.renderTopCards(week);
assert.equal($('k-total-title').textContent, '本周总胜率');
assert.equal($('k-total').textContent, '61%');
assert.equal($('k-draw-rate-note').textContent, '本周 · 当前筛选 · 比例仅含先后手已知的有结果对局');
assert.equal($('pd-dist-scope').textContent, '本周');
assert.equal($('k-total-today').textContent, '今日 3 胜 1 负 · 胜率 75%',
  '范围切到本周后，「今日…」行必须仍是今天的数字，不能拿本周的顶上');
assert.equal($('k-play-today').textContent, '今日先手率 75% · 先手胜率 66.7%（2 胜 / 3 场）',
  '「今日」行与所选范围无关');

// 范围本来就是「今天」时那三行是纯复读（大数字已经是今天），应留空
context.statsRange = 'today';
const today = response();
today.range = 'today';
today.total = week.total;
today.on_play = week.on_play;
today.on_draw = week.on_draw;
today.play_draw_rates = week.play_draw_rates;
context.renderTopCards(today);
assert.equal($('k-total-title').textContent, '今天总胜率');
assert.equal($('k-total-today').textContent, '', '范围选「今天」时不该再复读一遍今日战绩');
assert.equal($('k-play-today').textContent, '');
assert.equal($('k-draw-today').textContent, '');
// 从「今天」切回「总对局」要能重新长出来（隐藏状态不能残留）
context.statsRange = 'all';
context.renderTopCards(response());
assert.equal($('k-total-today').textContent, '今日 3 胜 1 负 · 胜率 75%');

// 今天还没打牌：今日行留空，但所选范围的数字照常显示
context.statsRange = 'month';
const empty = response();
empty.range = 'month';
empty.today = {total:{n:0, wins:0, wr:null, lo:0, hi:0},
  on_play:{n:0, wins:0, wr:null, lo:0, hi:0}, on_draw:{n:0, wins:0, wr:null, lo:0, hi:0},
  play_draw_rates:{play:0, draw:0, unknown:0, play_rate:null, draw_rate:null}};
context.renderTopCards(empty);
assert.equal($('k-total-title').textContent, '本月总胜率');
assert.equal($('k-total-today').textContent, '', '今天没对局时不该留一行空的「今日…」');
assert.equal($('k-play-today').textContent, '');

// 具体日期（顶部没有这个按钮，但 range 参数能收到）——标题直接写日期，别硬套词。
// 顶层 `const` 是词法绑定、不会挂到 context 上，只能在同一个 context 里再跑一小段
// 求值（等价于页面上另一段 <script>）。
assert.equal(vm.runInContext("rangeLabel('2026-09-14')", context), '2026-09-14');
assert.equal(vm.runInContext("isDayString('2026-09-14')", context), true);
assert.equal(vm.runInContext("isDayString('week')", context), false);

// 顶部范围与下面的战报/明细互不联动：渲染统计卡不该碰战报那几个元素
$('daily-plain').textContent = '战报正文';
$('m-count').textContent = '共 7 场';
context.statsRange = 'week';
context.renderTopCards(week);
assert.equal($('daily-plain').textContent, '战报正文', '统计卡的范围切换不该动战报');
assert.equal($('m-count').textContent, '共 7 场', '统计卡的范围切换不该动明细');
console.log('Top stats UI: 范围切换、今日行恒为今天、空样本与互不联动 检查通过');
