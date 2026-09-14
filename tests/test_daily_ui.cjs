const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const elements = new Map();
const $ = id => {if(!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',hidden:false});return elements.get(id);};
let scope='old'; const pending=[];
// matchDay 是战报与对局明细共用的日期状态，定义在 app.js 开头（不在切片内），需显式注入；
// syncMatchDayBtns 同理，用空实现顶替。
const context = vm.createContext({$,params:()=>scope,api:()=>new Promise(resolve=>pending.push(resolve)),esc:String,fmtTime:String,Set,matchDay:'2026-01-02',syncMatchDayBtns:()=>{}});
// 切片哨兵必须命中：indexOf 返回 -1 会让 slice 把整段错位内容喂给 vm（dailyQualityView
// 被删掉时就这样崩过一次）。起点用 dailyRequest 那行的声明，终点是后面第一个无关函数。
const START = 'let dailyRequest = 0, dailyScope = "", dailyLatest = null;';
const END = 'function fillSelect';
const start = source.indexOf(START);
const end = source.indexOf(END);
assert.ok(start > 0, `切片起点未找到：${START}`);
assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
vm.runInContext(source.slice(start, end), context);

const response = text => ({date:'2026-01-02',plain:text,is_today:false,latest_date:null,
  highlights:[],highlight_records:[],
  play_draw:{day:{play_rate:null,draw_rate:null},
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
 // 分赛事历史变化只留 headline 一句结论（逐赛事明细与比较口径整块删掉了）
 assert.equal($('daily-history-section').hidden,false);
 assert.match($('daily-history-lead').innerHTML,/高 12 个百分点/);
 // 连续纪录只留「当前连续」一条。原先还有「当天最长」「历史最长」和一句统计口径，
 // 加上逐赛事罗列、常遇主将、BO 模式拆分、对手类型覆盖率——用户口径：全都没必要。
 assert.match($('daily-pd-streaks').textContent,/当前连续先手 1 场/);
 assert.doesNotMatch($('daily-pd-streaks').textContent,/当天最长|历史最长|统计口径/);
 // 空日（默认落在「今天」，当天常还没打牌）：三张只会显示「–%」「0 场」的统计卡是零信息，
 // 应藏起来；跨日累计的「当前连续」保留。
 const blank = response('这一天在当前筛选下没有已记录对局。');
 blank.summary = {...blank.summary, n:0, wins:0, losses:0, play:0, draw:0,
   win_rate:{wr:null,n:0}, play_rate:{wr:null,n:0}, top_commanders:[]};
 blank.history_summary={headline:'',note:'',items:[]};
 context.matchDay='2026-01-02';
 const blankRun=context.loadDaily(); pending[pending.length-1](blank); await blankRun;
 assert.equal($('daily-summary').hidden,true,'空日应藏起三张「–%」统计卡');
 assert.equal($('daily-history-section').hidden,true,'空日没有基线时不该显示历史变化区');
 assert.match($('daily-pd-streaks').textContent,/当前连续先手 1 场/,'空日仍应保留跨日连续纪录');
 // 回到有对局的日期，统计卡必须重新出现（隐藏状态不能残留）
 const back=response('有对局');
 const backRun=context.loadDaily(); pending[pending.length-1](back); await backRun;
 assert.equal($('daily-summary').hidden,false,'有对局的日期统计卡应重新出现');
 assert.equal($('daily-history-section').hidden,false);
 // R13：选「全部日期」时战报是单日口径、没有意义——藏起战报区且不再发请求
 const sent=pending.length;
 context.matchDay='';
 await context.loadDaily();
 assert.equal($('daily-block').hidden,true,'全部日期应藏起战报区');
 assert.equal($('daily-all-note').hidden,false,'全部日期应显示替代说明');
 assert.equal(pending.length,sent,'全部日期下不应再请求 /api/daily');
 console.log('Daily UI: 竞态丢弃、作用域、当前连续一条、空日与全部日期 检查通过');
})();
