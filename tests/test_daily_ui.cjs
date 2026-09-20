const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const elements = new Map();
const $ = id => {if(!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',hidden:false});return elements.get(id);};
let scope='old'; const pending=[]; const calls=[];
// matchRange 是战报与对局明细共用的时间范围状态，定义在 app.js 开头（不在切片内），
// 需显式注入；syncRangeBtns 同理，用空实现顶替。
const context = vm.createContext({$,params:()=>scope,
  api:(path,extra)=>new Promise(resolve=>{calls.push({path,extra});pending.push(resolve);}),
  esc:String,fmtTime:String,Set,matchRange:'2026-01-02',syncRangeBtns:()=>{}});
// 切片哨兵必须命中：indexOf 返回 -1 会让 slice 把整段错位内容喂给 vm（dailyQualityView
// 被删掉时就这样崩过一次）。起点用 dailyRequest 那行的声明，终点是后面第一个无关函数。
// 起点只要含 loadDaily：顶部那三行「今日…」（todaySideLine/renderTodayLines）2026-09-20
// 已挪到统计卡那边，由 tests/test_top_stats_ui.cjs 守着，不再在这个切片里。
const START = 'let dailyRequest = 0, dailyScope = "", dailyLatest = null;';
const END = 'function fillSelect';
const start = source.indexOf(START);
const end = source.indexOf(END);
assert.ok(start > 0, `切片起点未找到：${START}`);
assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
vm.runInContext(source.slice(start, end), context);

const response = text => ({date:'2026-01-02',range:null,plain:text,is_today:false,latest_date:null,
  highlights:[],highlight_records:[],
  play_draw:{day:{play_rate:null,draw_rate:null,
    play_wr:{wins:3,n:5,wr:60}, draw_wr:{wins:2,n:4,wr:50}},
    day_streaks:{longest_play:0,longest_draw:0},
    history_streaks:{current_side:'play',current_n:1,last_time:1789131805076,
      longest_play:16,longest_draw:11,reason:null}},
  history_summary:{headline:'标准排位 BO1 高 12 个百分点',note:'此前 30 天只是查找窗口',
    items:[{text:'标准排位 · BO1：当天 1 场，1 胜 0 负；可比范围胜率较高。',small_sample:true,delta_pp:12}]},
  summary:{n:1,wins:1,losses:0,play:1,draw:0,unknown_pd:0,win_rate:{wr:100,n:1},
    play_rate:{wr:100,n:1},max_loss_streak:0,duration_sec:0,top_commanders:[],
    mulligan_known:0,deck_known:0,commander_known:0,commander_eligible:0}});

(async()=>{
 const old=context.loadDaily(); scope='new'; const current=context.loadDaily();
 pending[1](response('new result')); await current;
 pending[0](response('stale result')); await old;
 assert.equal($('daily-plain').textContent,'new result');
 const changed=context.loadDaily(); scope='another';pending[2](response('wrong scope'));await changed;
 assert.equal($('daily-plain').textContent,'new result');
 // 单日走 day=，不是 range=（对象来自 vm 里，原型不同，deepStrictEqual 会误判，用字符串比）
 assert.equal(JSON.stringify(calls.at(-1).extra),'{"day":"2026-01-02"}',
   '单日应请求 day=，实际：'+JSON.stringify(calls.at(-1).extra));
 // 分赛事历史变化只留 headline 一句结论（逐赛事明细与比较口径整块删掉了）
 assert.equal($('daily-history-section').hidden,false);
 assert.match($('daily-history-lead').innerHTML,/高 12 个百分点/);
 // 连续纪录只留「当前连续」一条。原先还有「当天最长」「历史最长」和一句统计口径，
 // 加上逐赛事罗列、常遇主将、BO 模式拆分、对手类型覆盖率——用户口径：全都没必要。
 assert.match($('daily-pd-streaks').textContent,/当前连续先手 1 场/);
 assert.doesNotMatch($('daily-pd-streaks').textContent,/当天最长|历史最长|统计口径/);
 // 顶部那三行「今日…」现在归 loadOverview 管（renderTodayLines），战报这里不该再碰它们
 $('k-total-today').textContent='哨兵';
 const blank = response('这一天在当前筛选下没有已记录对局。');
 blank.summary = {...blank.summary, n:0, wins:0, losses:0, play:0, draw:0,
   win_rate:{wr:null,n:0}, play_rate:{wr:null,n:0}, top_commanders:[]};
 blank.history_summary={headline:'',note:'',items:[]};
 context.matchRange='2026-01-02';
 const blankRun=context.loadDaily(); pending[pending.length-1](blank); await blankRun;
 assert.equal($('k-total-today').textContent,'哨兵','战报不再负责顶部「今日…」行，不该改写它');
 assert.equal($('daily-history-section').hidden,true,'空日没有基线时不该显示历史变化区');
 assert.match($('daily-pd-streaks').textContent,/当前连续先手 1 场/,'空日仍应保留跨日连续纪录');
 // 回到有对局的日期
 const back=response('有对局');
 const backRun=context.loadDaily(); pending[pending.length-1](back); await backRun;
 assert.equal($('daily-plain').textContent,'有对局');
 assert.equal($('daily-history-section').hidden,false);
 assert.equal($('daily-asof').textContent,'历史日战报');
 // 2026-09-20 新增「本周」：请求带 range=week，**不能**把范围末的那天回写成选中日
 context.matchRange='week';
 $('d-date').value='2026-01-02';
 const week=response('本周 7 天有对局，共 77 场 · 47 胜 30 负 · 胜率 61.0%。');
 week.range='week'; week.date='2026-01-08'; week.is_today=true;
 week.summary={...week.summary,n:77,wins:47,losses:30};
 const weekRun=context.loadDaily(); pending[pending.length-1](week); await weekRun;
 assert.equal(JSON.stringify(calls.at(-1).extra),'{"range":"week"}','本周应请求 range=week');
 assert.equal(context.matchRange,'week','范围报告不能把状态改成范围末的那一天');
 assert.equal($('d-date').value,'2026-01-02','范围报告不该回写日期控件');
 assert.equal($('daily-asof').textContent,'本周至今的已记录对局');
 assert.match($('daily-plain').textContent,/本周 7 天有对局/);
 // R13：选「全部日期」时战报是单日口径、没有意义——藏起战报区且不再发请求
 const sent=calls.length;
 context.matchRange='';
 await context.loadDaily();
 assert.equal($('daily-block').hidden,true,'全部日期应藏起战报区');
 assert.equal($('daily-all-note').hidden,false,'全部日期应显示替代说明');
 assert.equal(calls.length,sent,'全部日期下不应再请求 /api/daily');
 console.log('Daily UI: 竞态丢弃、作用域、当前连续一条、单日/本周参数、全部日期 检查通过');
})();
