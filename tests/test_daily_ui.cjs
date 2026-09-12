const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const elements = new Map();
const $ = id => {if(!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',hidden:false});return elements.get(id);};
let scope='old'; const pending=[];
// matchDay 是战报与对局明细共用的日期状态，定义在 app.js 开头（不在下面两段切片内），
// 需显式注入；syncMatchDayBtns 同理，用空实现顶替。
const context = vm.createContext({$,params:()=>scope,api:()=>new Promise(resolve=>pending.push(resolve)),esc:String,fmtTime:String,fmtDur:String,Set,matchDay:'2026-01-02',syncMatchDayBtns:()=>{}});
vm.runInContext(source.slice(source.indexOf('function eventMarkup'),source.indexOf('async function loadMatches')),context);
vm.runInContext(source.slice(source.indexOf('function dailyQualityView'),source.indexOf('function fillSelect')),context);
const response = text => ({date:'2026-01-02',plain:text,is_today:false,latest_date:null,highlights:[],highlight_records:[],events:[{event:'Ladder',label:'标准排位',n:1,wins:1,losses:0,play:1,draw:0,unknown_pd:0}],modes:[],unknown_date:0,
history_summary:{headline:'标准排位 BO1 高 12 个百分点',note:'此前 30 天只是查找窗口',items:[{text:'标准排位 · BO1：当天 1 场，1 胜 0 负；可比范围胜率较高。',small_sample:true,delta_pp:12}]},
summary:{n:1,wins:1,losses:0,play:1,draw:0,unknown_pd:0,win_rate:{wr:100,n:1},play_rate:{wr:100,n:1},max_loss_streak:0,duration_sec:0,top_commanders:[],mulligan_known:0,deck_known:0,commander_known:0,commander_eligible:0}});
(async()=>{
 const old=context.loadDaily(); scope='new'; const current=context.loadDaily();
 pending[1](response('new result')); await current;
 pending[0](response('stale result')); await old;
 assert.equal($('daily-plain').textContent,'new result');
 const changed=context.loadDaily(); scope='another';pending[2](response('wrong scope'));await changed;
 assert.equal($('daily-plain').textContent,'new result');
 assert.match($('daily-events').innerHTML,/title="Ladder">标准排位/);
 assert.equal($('daily-history-section').hidden,false);
 assert.match($('daily-history-lead').innerHTML,/高 12 个百分点/);
 assert.match($('daily-history-items').innerHTML,/当天 1 场/);
 // R13：选「全部日期」时战报是单日口径、没有意义——藏起战报区且不再发请求
 const sent=pending.length;
 context.matchDay='';
 await context.loadDaily();
 assert.equal($('daily-block').hidden,true,'全部日期应藏起战报区');
 assert.equal($('daily-all-note').hidden,false,'全部日期应显示替代说明');
 assert.equal(pending.length,sent,'全部日期下不应再请求 /api/daily');
 console.log('Daily UI stale-response, scope and event-label checks passed');
})();
