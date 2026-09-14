const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');
const context = vm.createContext({
  esc: value => String(value ?? ''),
  Object, Array, Math, Number,
});

// 切片哨兵必须命中：indexOf 返回 -1 会让 slice 把整段错位内容喂给 vm。
// （原先这里还有一段 dailyQualityView，2026-09-14 按用户口径把那个折叠整块删掉了。）
const slices = [
  ['function mulliganView', 'async function loadMulligans'],
  ['function targetingSummaryItems', 'async function loadTargeting'],
];
for (const [START, END] of slices) {
  const start = source.indexOf(START);
  const end = source.indexOf(END);
  assert.ok(start > 0, `切片起点未找到：${START}`);
  assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
  vm.runInContext(source.slice(start, end), context);
}

// 调度卡只留「调度过 vs 没调度」一组对比。原先还带「资料覆盖 N/M 场（x%）」
// 和一大段逐局留牌分布／分母口径（用户反馈：这些数据全都没必要）。
const mulligan = context.mulliganView({
  by_mulligan: [
    {key:'clean', n:60, wr:55},
    {key:'mulligan', n:20, wr:40},
    {key:'unknown', n:20, wr:null},
  ],
  kept_on_dist: [{kept_on:0,count:65},{kept_on:1,count:25},{kept_on:2,count:5}],
});
assert.match(mulligan.summary, /调度过 20 场（胜率 40%）/);
assert.match(mulligan.summary, /未调度 60 场（胜率 55%）/);
assert.doesNotMatch(mulligan.summary, /覆盖|80\/100|逐局留牌|客户端日志|BO3/,
  '资料覆盖与分母口径不该再回到卡片上');
assert.equal(mulligan.detail, undefined, 'detail 字段已随折叠一起删掉');

// 没有任何调度记录时给一句可读的空态，不是空白
assert.match(context.mulliganView({by_mulligan:[{key:'unknown', n:5, wr:null}], kept_on_dist:[]}).summary,
  /没有可用的调度记录/);
assert.match(context.mulliganView({by_mulligan:[], kept_on_dist:[]}).summary,
  /没有可用的调度记录/);
// 胜率未知时不能编数字
assert.match(context.mulliganView({
  by_mulligan:[{key:'clean', n:3, wr:null},{key:'mulligan', n:2, wr:null}], kept_on_dist:[],
}).summary, /胜率待确认/);

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

console.log('R9 摘要：调度一组对比、近期波动两句、无折叠残留 检查通过');
