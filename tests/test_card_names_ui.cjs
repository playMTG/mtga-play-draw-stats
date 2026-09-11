const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const elements = new Map();
const $ = id => {if(!elements.has(id)) elements.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false});return elements.get(id);};
const context = vm.createContext({$, Set});
const start = source.indexOf('function renderCardNamesNote');
const end = source.indexOf('$("card-names-seed").addEventListener');
assert.ok(start > 0 && end > start, 'renderCardNamesNote 应存在且先于按钮绑定');
vm.runInContext(source.slice(start, end), context);

// 没有主将数据：整块隐藏
context.renderCardNamesNote({total:0, named:0, missing:0, client_db:null});
assert.equal($('card-names-note').hidden, true);

// 部分缺名 + 找得到客户端库：提示 + 可点按钮
context.renderCardNamesNote({total:463, named:462, missing:1, client_db:'C:\\x\\Raw', online_sync:false});
assert.equal($('card-names-note').hidden, false);
assert.equal($('card-names-title').textContent, '部分对手主将还没有卡名');
assert.match($('card-names-detail').textContent, /463 个对手主将里，1 个还没有卡名/);
assert.match($('card-names-detail').textContent, /离线补齐/);
assert.equal($('card-names-seed').hidden, false);

// 全部缺名 + 没有客户端库：说明离线路径不可用，按钮隐藏
context.renderCardNamesNote({total:463, named:0, missing:463, client_db:null, online_sync:false});
assert.equal($('card-names-title').textContent, '对手主将还没有卡名');
assert.match($('card-names-detail').textContent, /未找到本机 MTGA 客户端的卡牌库/);
assert.match($('card-names-detail').textContent, /card_raw_extra|client_raw_extra/);
assert.equal($('card-names-seed').hidden, true);

// 缺名但没开联网：不应声称联网补全已开启
assert.ok(!/联网补全已开启/.test($('card-names-detail').textContent));
context.renderCardNamesNote({total:463, named:0, missing:463, client_db:null, online_sync:true});
assert.match($('card-names-detail').textContent, /联网补全已开启/);

console.log('Card-names notice checks passed');
