// 套牌筛选二级联动的前端契约（V1 续做）。
//
// 两级是「名字 → 具体身份」：只有名字被多个 deck_id 共用（filters 里 ids>1）时
// 才显示第二个下拉。这里守住三件事：显隐条件、请求参数、以及 params() 里
// deck_id 与 deck 同时出现（后端按求交处理）。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');

const makeEl = (init = {}) => Object.assign(
  { value: '', innerHTML: '', hidden: false, classList: { contains: () => false } }, init);
const els = {
  'f-bot': makeEl(), 'f-family': makeEl(), 'f-event': makeEl(), 'f-mode': makeEl(),
  'f-deck': makeEl(), 'f-deck-id': makeEl(), 'f-deck-id-wrap': makeEl({ hidden: true }),
};
const $ = (id) => els[id];

let response = { deck: '', items: [], total: 0 };
const calls = [];
const context = vm.createContext({
  $, esc: (v) => String(v ?? ''), URLSearchParams,
  uiVersion: 1, isStale: (v) => v !== 1,
  api: (path, extra) => { calls.push([path, extra]); return Promise.resolve(response); },
  deckIdCounts: new Map(), deckIdentities: [],
  Map, Set,
});
vm.runInContext(
  source.slice(source.indexOf('function params()'), source.indexOf('async function api(')),
  context);
vm.runInContext(
  source.slice(source.indexOf('async function syncDeckIdentities'),
                source.indexOf('/* ---------- 段位曲线')),
  context);

(async () => {
  // --- params()：deck_id 只在两级都选中时才出现 ---
  els['f-deck'].value = '轮抽套牌';
  assert.equal(context.params().get('deck_id'), null, '只选名字时不该带 deck_id');
  els['f-deck-id'].value = 'abc-123';
  assert.equal(context.params().get('deck_id'), 'abc-123', '选中身份时应带 deck_id');
  assert.equal(context.params().get('deck'), '轮抽套牌', 'deck 必须同时保留（后端按求交）');
  els['f-deck'].value = '';
  assert.equal(context.params().get('deck_id'), null, '没选名字时不该带 deck_id');

  // --- 未选名字：第二级不出现，也不该发请求 ---
  calls.length = 0;
  await context.syncDeckIdentities();
  assert.equal(els['f-deck-id-wrap'].hidden, true, '未选名字应藏起第二级');
  assert.equal(calls.length, 0, '未选名字不该请求 /api/deck_identities');

  // --- 名字唯一（ids=1）：不需要第二级 ---
  context.deckIdCounts = new Map([['W3', 1], ['红黑牺牲', 2]]);
  els['f-deck'].value = 'W3';
  calls.length = 0;
  await context.syncDeckIdentities();
  assert.equal(els['f-deck-id-wrap'].hidden, true, '名字唯一时不该显示第二级');
  assert.equal(calls.length, 0, '名字唯一时不该发请求');

  // --- 名字被多个 deck_id 共用：出现第二级并列出各身份 ---
  response = {
    deck: '红黑牺牲', total: 113,
    items: [
      { value: 'id-big', label: '2022-08-13 21:35 起', n: 111 },
      { value: 'id-small', label: '2022-05-04 22:40 起', n: 2 },
    ],
  };
  els['f-deck'].value = '红黑牺牲';
  els['f-deck-id'].value = '';
  calls.length = 0;
  await context.syncDeckIdentities();
  assert.equal(calls.length, 1, '应恰好请求一次身份列表');
  assert.equal(calls[0][0], '/api/deck_identities');
  // 注意：vm 上下文里造的对象过不了 deepStrictEqual（跨 realm 原型不同），逐项比。
  assert.equal(calls[0][1].deck, '红黑牺牲', '应带当前名字请求身份列表');
  assert.equal(els['f-deck-id-wrap'].hidden, false, '重名时应显示第二级');
  assert.match(els['f-deck-id'].innerHTML, /全部（113）/, '第一项应是「全部」并带总场数');
  assert.match(els['f-deck-id'].innerHTML, /2022-08-13 21:35 起（111）/);
  assert.match(els['f-deck-id'].innerHTML, /value="id-big"/, '选项值必须是 deck_id');
  assert.equal(context.deckIdentities.length, 2);

  // --- 已选身份在刷新后仍存在时保留（例如只改了模式） ---
  els['f-deck-id'].value = 'id-small';
  await context.syncDeckIdentities();
  assert.equal(els['f-deck-id'].value, 'id-small', '身份仍存在时应保留选择');

  // --- 原选中身份在新列表里消失时回到「全部」 ---
  els['f-deck-id'].value = 'id-gone';
  await context.syncDeckIdentities();
  assert.equal(els['f-deck-id'].value, '', '身份消失时应回到「全部」');

  // --- 换回唯一名字：第二级收起、选择清空 ---
  els['f-deck'].value = 'W3';
  await context.syncDeckIdentities();
  assert.equal(els['f-deck-id-wrap'].hidden, true, '换回唯一名字应藏起第二级');
  assert.equal(els['f-deck-id'].value, '', '藏起时应清空选择');
  assert.equal(context.deckIdentities.length, 0);

  console.log('Deck cascade UI visibility, request and params checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
