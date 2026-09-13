const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');

// ---------- 假 DOM ----------
const elements = new Map();
const make = () => ({value: '', textContent: '', innerHTML: '', hidden: false,
  dataset: {}, classList: {_on: new Set(), toggle(c, on) {on ? this._on.add(c) : this._on.delete(c);},
  contains(c) {return this._on.has(c);}}});
const $ = id => {if (!elements.has(id)) elements.set(id, make()); return elements.get(id);};

// 每日战报 section：applyFormatFocus 在排位焦点下要把段位卡插到它后面。
// 给足 nextSibling / parentNode，让那条分支真的被执行到（否则等于没测）。
const moves = [];
const daily = Object.assign(make(), {
  nextSibling: {}, parentNode: {insertBefore: (node, ref) => moves.push([node, ref])},
});
const body = make();
const document = {
  body,
  getElementById: id => (id === 'commander-card' || id === 'rank-card'
    || id === 'opponent-types-card') ? $(id) : null,
  querySelector: () => daily,
};

const context = vm.createContext({
  $, document, esc: String, fmtTime: value => `time:${value}`,
  encodeURIComponent, decodeURIComponent, JSON,
  uiVersion: 1, isStale: () => false,
  // 故意注入一个「非空」的 params：旧实现用 params().toString() 判「有没有筛选」，
  // 而 params() 永远带 exclude_bot → 恒为真、整块赛制自适应变死代码（2026-09-13 修）。
  // 注入了它，将来谁改回去都会在这条测试上红，而不是悄悄变成死代码。
  params: () => new URLSearchParams('exclude_bot=true'),
});

// 三段切片：按钮/payload 构造、首页入口 loader、赛制收尾。哨兵必须都能找到，
// 否则 indexOf 返回 -1 会让 slice 把整份源码喂给 vm，在加载阶段静默崩掉。
const slices = [
  ['function deckOpenButton', 'function matchRow'],
  ['/* ---------- 首页入口：最近在打的套牌（V3 收尾） ---------- */', 'function mulliganView'],
  ['function applyFormatFocus', 'function bigCard'],
];
for (const [START, END] of slices) {
  const start = source.indexOf(START), end = source.indexOf(END);
  assert.ok(start > 0, `切片起点未找到：${START}`);
  assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
  vm.runInContext(source.slice(start, end), context);
}

// ---------- 1. 赛制自适应真的生效（守卫死代码 bug） ----------
const brawlFocus = {
  primary: '争锋', label: '争锋', share: 70.5, window_days: 30,
  show_commanders: true, show_rank: false, show_opponent_types: false,
};
context.applyFormatFocus(brawlFocus);
assert.equal($('format-focus-note').hidden, false, '没手动筛选时提示条必须显示');
assert.match($('format-focus-note').textContent, /近 30 天主赛制：争锋/);
assert.equal(body.dataset.formatFocus, '争锋', 'body 上要标出当前主赛制');
assert.equal($('commander-card').hidden, false, '争锋焦点要保留主将卡');
assert.equal($('rank-card').hidden, true, '争锋焦点要收掉段位曲线');
assert.equal($('opponent-types-card').hidden, true, '争锋焦点要收掉对手类型卡');

// 排位焦点：段位曲线上移、主将卡收起
$('f-family').value = ''; $('f-event').value = ''; $('f-mode').value = ''; $('f-deck').value = '';
context.applyFormatFocus({
  primary: '排位天梯', label: '排位天梯', share: 40, window_days: 30,
  show_commanders: false, show_rank: true, show_opponent_types: true,
});
assert.equal($('commander-card').hidden, true);
assert.equal($('rank-card').hidden, false);
assert.equal($('opponent-types-card').hidden, false);
assert.equal(moves.length, 1, '排位焦点要把段位曲线上移到每日战报之后');
assert.equal(moves[0][0], $('rank-card'));

// 手动筛选后以筛选为准：整块都不动
$('f-family').value = '轮抽';
context.applyFormatFocus(brawlFocus);
assert.equal($('format-focus-note').hidden, true, '手动筛选后不该再显示主赛制提示条');
assert.equal(body.dataset.formatFocus, '', '手动筛选后不该再标主赛制');
assert.equal($('commander-card').hidden, true, '手动筛选后不强行收放（保留上一次状态）');
$('f-family').value = '';

// 资料不足时不收放
context.applyFormatFocus({primary: 'unknown', label: '资料不足', window_days: 30});
assert.equal($('format-focus-note').hidden, true);
assert.equal(body.dataset.formatFocus, '');

// ---------- 2. 首页入口：一行一个可点开的套牌身份 ----------
let apiCalls = [];
const FOCUS_ON = {applied: true, primary: '争锋', label: '争锋', window_days: 30, share: 70.5};
const FOCUS_OFF = {applied: false, primary: null, label: null, window_days: null, share: null};
context.api = async (path, extra) => {
  apiCalls.push({path, extra});
  // focus 口径由**请求参数**决定，和真实后端一致（focus=0 时不该再回 applied:true，
  // 否则提示条会停在「主赛制」那套说辞上）。
  return {
    total: 3, unlabeled: 4, limit: 8,
    focus: extra.focus ? FOCUS_ON : FOCUS_OFF,
    items: [
      {deck: '拿杜史迹争锋生物版', deck_id: 'd1', label: '拿杜史迹争锋生物版',
       n: 285, wins: 166, wr: 58.2, play: 131, draw: 143, last_time: 1789225906382,
       first_time: 1780000000000},
      {deck: '现开赛', deck_id: 'y1', label: '现开赛 · 2026-09-04 19:19 起',
       n: 6, wins: 3, wr: 50, play: 3, draw: 3, last_time: 1788535601916,
       first_time: 1788535000000},
      {deck: 'W3', deck_id: '', label: 'W3',
       n: 2, wins: 1, wr: 50, play: 1, draw: 1, last_time: 1788000000000,
       first_time: 1787000000000},
    ],
  };
};

(async () => {
  await context.loadRecentDecks();
  assert.equal(apiCalls.length, 1);
  assert.equal(apiCalls[0].path, '/api/recent_decks');
  assert.equal(apiCalls[0].extra.focus, 1, '默认按主赛制收窄');
  assert.equal(apiCalls[0].extra.limit, 8);

  const html = $('recent-decks-rows').innerHTML;
  const buttons = [...html.matchAll(/data-deck="([^"]+)"/g)];
  assert.equal(buttons.length, 3, '每行都要是可点开的套牌入口');
  const payloads = buttons.map(m => JSON.parse(decodeURIComponent(m[1])));
  assert.deepEqual(payloads[0], {deck: '拿杜史迹争锋生物版', deck_id: 'd1', deck_version: ''});
  assert.deepEqual(payloads[1], {deck: '现开赛', deck_id: 'y1', deck_version: ''});
  assert.deepEqual(payloads[2], {deck: 'W3', deck_id: '', deck_version: ''});
  assert.match(html, /现开赛 · 2026-09-04 19:19 起/, '用后端的可区分名，不在前端重算');
  assert.match(html, /285 场/);
  assert.match(html, /先手 131 · 后手 143/);
  assert.doesNotMatch(html, /undefined/);

  // 提示条：主赛制口径 + 未记录套牌不占行
  const note = $('recent-decks-note').textContent;
  assert.match(note, /近 30 天主赛制：争锋/);
  assert.match(note, /共 3 套牌/);
  assert.match(note, /另有 4 场没记录套牌/);

  // 切到「全部」：focus=0，提示条换成「不限赛制」
  await context.setRecentDecksScope('all');
  assert.equal(apiCalls[1].extra.focus, 0);
  assert.equal($('rd-all').classList.contains('on'), true);
  assert.equal($('rd-focus').classList.contains('on'), false);
  assert.match($('recent-decks-note').textContent, /不限赛制/);

  // 手动筛选时说明「以筛选为准」，避免用户以为按钮坏了
  $('f-family').value = '轮抽';
  await context.loadRecentDecks();
  assert.match($('recent-decks-note').textContent, /已按当前筛选收窄/);
  $('f-family').value = '';

  // 套牌筛选不影响这个入口（它是选择器），要说清楚
  $('f-deck').value = '拿杜史迹争锋生物版';
  await context.loadRecentDecks();
  assert.match($('recent-decks-note').textContent, /套牌筛选不影响这个区块/);
  $('f-deck').value = '';

  // 空范围：给一句可读的空态，不留空白
  context.api = async () => ({total: 0, unlabeled: 0, limit: 8,
    focus: {applied: false, primary: null}, items: []});
  await context.loadRecentDecks();
  assert.match($('recent-decks-rows').innerHTML, /没有可点开的套牌记录/);

  console.log('Recent-decks UI: 赛制自适应生效、入口按钮 payload、口径提示 检查通过');
})();
