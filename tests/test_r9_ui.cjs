const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');
const context = vm.createContext({
  esc: value => String(value ?? ''),
  Object, Array, Math, Number,
});

vm.runInContext(
  source.slice(source.indexOf('function mulliganView'), source.indexOf('async function loadMulligans')),
  context,
);
vm.runInContext(
  source.slice(source.indexOf('function dailyQualityView'), source.indexOf('let dailyRequest')),
  context,
);
vm.runInContext(
  source.slice(source.indexOf('function targetingSummaryItems'), source.indexOf('async function loadTargeting')),
  context,
);

const mulligan = context.mulliganView({
  by_mulligan: [
    {key:'clean', n:60, wr:55},
    {key:'mulligan', n:20, wr:40},
    {key:'unknown', n:20, wr:null},
  ],
  kept_on_dist: [{kept_on:0,count:65},{kept_on:1,count:25},{kept_on:2,count:5}],
});
assert.match(mulligan.summary, /80\/100 场（80\.0%）/);
assert.match(mulligan.summary, /调度过 20 场/);
assert.doesNotMatch(mulligan.summary, /未知 20/);
assert.doesNotMatch(mulligan.summary, /调度 2 次/);
assert.match(mulligan.detail, /未知 20 场/);
assert.match(mulligan.detail, /逐局留牌分布共 95 局/);
assert.match(mulligan.detail, /BO3/);
assert.match(mulligan.detail, /客户端日志/);

const quality = context.dailyQualityView({
  n:5, mulligan_known:4, deck_known:3, commander_eligible:3, commander_known:2,
}, {unknown_date:1});
assert.match(quality.summary, /2 场套牌未记录/);
assert.match(quality.summary, /1 场争锋主将未记录/);
assert.match(quality.summary, /1 场日期未知/);
assert.match(quality.detail, /当前日期有效分母：5 场/);
assert.match(quality.detail, /调度 4\/5 场/);
assert.match(quality.detail, /争锋对手主将 2\/3 场/);
const completeQuality = context.dailyQualityView({
  n:5, mulligan_known:5, deck_known:5, commander_eligible:0, commander_known:0,
}, {unknown_date:0});
assert.equal(completeQuality.summary, '资料覆盖说明');
assert.doesNotMatch(completeQuality.summary, /未记录|未知/);

const targeting = {
  summary:{play:13, draw:17, max_loss_streak:4, commander_eligible:0},
  dimensions:{
    play_draw:{enough:true,p:0.46},
    mulligan:{enough:true,p:0.03},
    matchup:{enough:false,p:null},
    streak:{enough:true,p:0.01},
  },
  comparison:{covered:24,total_decided:30,adjusted_delta_pp:-6.5},
  nemeses:[{name:'阿耶尼',n:5,wr:20}],
};
const items = context.targetingSummaryItems(targeting);
assert.equal(items.length, 2);
assert.match(items[0].text, /有效分母 30 场/);
assert.match(items[0].text, /先手率 43\.3%/);
assert.match(items[1].text, /可比 24\/30 场/);
assert.doesNotMatch(items.map(item => item.text).join(' '), /p=|调度|匹配偏斜/);
assert.match(context.targetingSummaryMarkup(targeting), /summary-item/);

console.log('R9 compact summaries and folded-detail denominator checks passed');
