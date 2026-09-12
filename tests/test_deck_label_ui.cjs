const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');

// 只取 deckLink 一段：matchRow 依赖太多渲染函数，这里只守「显示名取哪个字段」。
const context = vm.createContext({ esc: String });
vm.runInContext(
  source.slice(source.indexOf('function deckLink'), source.indexOf('function matchRow')),
  context);

// 1) 有 my_deck_label 时用它。这是本项的核心：客户端对限制赛牌组只给通用名
//    「轮抽套牌」，250 次 draft 在明细里点哪个都一样。
const draft = {
  my_deck_tag: '轮抽套牌', my_deck_id: 'd1', my_deck_version: 'v1',
  my_deck_label: '轮抓 · 2026-06-10 12:16',
};
const draftHtml = context.deckLink(draft);
assert.match(draftHtml, />轮抓 · 2026-06-10 12:16<\/button>/, '按钮文字应是派生名');
assert.doesNotMatch(draftHtml, />轮抽套牌</, '不应再把通用名当按钮文字');
// 点击后仍带着 deck_id，才能打开那一次 draft 的详情
assert.match(draftHtml, /deck-open/, '仍应是可点击的套牌入口');

// 2) 没有 label 时回落到原始套牌名（争锋/构筑与既有契约不受影响）
const brawl = { my_deck_tag: '阿耶尼史迹争锋', my_deck_id: 'b1', my_deck_version: 'v1' };
assert.match(context.deckLink(brawl), />阿耶尼史迹争锋<\/button>/);

// 3) 显式传入的 label 优先级最高（保留原有参数语义）
assert.match(context.deckLink(draft, '手工指定'), />手工指定<\/button>/);

// 4) 完全没有套牌身份时不出按钮，只出文字
const html = context.deckLink({ my_deck_tag: '', my_deck_id: '', my_deck_version: '' });
assert.equal(html, '套牌未记录');
assert.doesNotMatch(html, /button/);

console.log('Deck label UI: my_deck_label 优先、tag 回退、无身份不出按钮 检查通过');
