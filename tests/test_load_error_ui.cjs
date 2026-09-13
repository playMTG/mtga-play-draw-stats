const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');

const elements = new Map();
const $ = id => {if(!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',hidden:false});return elements.get(id);};

let calls = [];
let failures = new Set();
const stub = name => async () => {
  calls.push(name);
  if (failures.has(name)) throw new Error(`${name} 读取失败`);
};

// 首页九个数据区块 + 「最近在打的套牌」入口，共十个 loader。清单在这里显式列出：
// 往 RELOAD_SECTIONS 里加 loader 而忘了同步这里，calls.length 就对不上，测试会红。
const LOADERS = [
  ['loadOverview', '总览'], ['loadRecentDecks', '最近在打的套牌'], ['loadMulligans', '调度'],
  ['loadCommanders', '对手主将'], ['loadOpponentTypes', '对手类型'], ['loadMatches', '对局明细'],
  ['loadStatus', '运行状态'], ['loadRankCurve', '段位曲线'], ['loadTargeting', '被针对指数'],
  ['loadDaily', '每日战报'],
];

const context = vm.createContext({ $, esc: String });
for (const [fn, label] of LOADERS) context[fn] = stub(label);
// 只取 RELOAD_SECTIONS + reload + reportLoadFailures 这一段；各 loader 用桩注入
vm.runInContext(
  source.slice(source.indexOf('const RELOAD_SECTIONS'), source.indexOf('// ---------- 你被针对了吗')),
  context);

(async () => {
  // 1) 全部成功：不显示错误区
  calls = []; failures = new Set();
  await context.reload();
  assert.equal(calls.length, LOADERS.length, '每个区块都应被调用');
  assert.equal($('load-error').hidden, true, '全部成功时不应显示错误区');
  assert.equal($('load-error-body').innerHTML, '');

  // 2) 单个区块失败：只点名它，其余照常渲染
  //    （旧实现用 Promise.all，一个失败就整页只剩一条 app.js 堆栈横幅）
  calls = []; failures = new Set(['每日战报']);
  await context.reload();
  assert.equal(calls.length, LOADERS.length, '一个区块失败不能阻止其余区块加载');
  assert.equal($('load-error').hidden, false, '有失败时必须显示错误区');
  assert.equal($('load-error-title').textContent, '部分区块加载失败');
  assert.match($('load-error-body').innerHTML, /每日战报/);
  assert.doesNotMatch($('load-error-body').innerHTML, /对手主将/, '未失败的区块不应被点名');
  assert.match($('load-error-body').innerHTML, /其余区块已正常加载/);

  // 3) 致命失败：筛选取不到时 reload 根本没开始，标题要说清是整页没起来
  context.reportLoadFailures([['筛选条件', new Error('boom')]], true);
  assert.equal($('load-error-title').textContent, '页面未能初始化');
  assert.match($('load-error-body').innerHTML, /筛选条件/);
  assert.doesNotMatch($('load-error-body').innerHTML, /其余区块已正常加载/);

  // 4) 再次全部成功：错误区自动收起
  failures = new Set();
  await context.reload();
  assert.equal($('load-error').hidden, true, '恢复后应收起错误区');
  assert.equal($('load-error-body').innerHTML, '');

  console.log('Load-error UI: 区块独立容错、点名失败区块、致命态标题 检查通过');
})();
