const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');
const esc = value => String(value ?? '');
const context = vm.createContext({
  esc,
  fmtTime: value => `time:${value}`,
  fmtDur: value => value == null ? '未记录' : `${value} 秒`,
  eventMarkup: (raw, label) => label || raw || '赛事未记录',
  cardsMarkup: (cards, fallback = []) => cards?.length
    ? cards.map(card => card.name).join(' / ')
    : fallback.join(' / ') || '–',
  opponentProfileMarkup: (row, cards) => cards?.length ? cards.map(card => card.name).join(' / ') : '–',
});

// 切片哨兵必须命中：indexOf 返回 -1 会让 slice 把整份源码喂给 vm，
// 表现为「document is not defined」而在加载阶段静默崩掉
const START = 'function sourceLabel';
const END = 'function eventMarkup';
const start = source.indexOf(START);
const end = source.indexOf(END);
assert.ok(start > 0, `切片起点未找到：${START}`);
assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
vm.runInContext(source.slice(start, end), context);

const known = {
  match_id: 'known', source: 'untapped', event_id: 'Play_Brawl_Historic',
  event_label: '历史争锋', start_time: 1, duration_sec: 120,
  total_turns: 8, my_mulls: 1, end_reason: 'Concede',
  my_deck_tag: '拿杜', my_deck_id: 'deck-1', my_deck_version: 'version-1',
  my_cards: [{name: '有翼智者，拿杜'}], my_cmdrs: ['Nadu, Winged Wisdom'],
  play_draw: 'draw', my_result: 'win', opponent_name: '对手',
  opp_cards: [{name: '群落之怒，阿耶尼'}], opp_cmdrs: ['Ajani'],
  match_mode: 'BO3',
  games: [
    {game_no: 1, play_draw: 'draw', result: 'loss', reason: 'Game'},
    {game_no: 2, play_draw: 'play', result: 'win', reason: 'Concede'},
  ],
};
const row = context.matchRow(known);
const details = context.matchDetails(known);
assert.match(row, /拿杜/);
assert.match(row, /有翼智者，拿杜/);
assert.match(row, /群落之怒，阿耶尼/);
assert.match(row, /BO3/);
// 逐局信息已从「内联展开」改为「悬停 title」（gameDetails 的 BO3 分支）：
// 摘要行只显示赛制，逐局明细放在 title 里，不再占表格行高
assert.match(row, /title="G1 后手 负 · G2 先手 胜"/);
assert.match(details, /<summary>查看<\/summary>/);
assert.match(details, /用时：.*120 秒/);
assert.match(details, /结束原因.*投降/);
assert.match(details, /数据来源.*Untapped 历史导入/);
assert.match(details, /套牌 ID.*deck-1/);
assert.match(details, /构筑版本.*version-1/);

const unknown = context.matchRow({
  ...known, match_id: 'unknown', my_deck_tag: '名字里写着某主将',
  my_cards: [], my_cmdrs: [],
});
// 套牌名只出现在套牌列；无主将数据时主将列是占位符，不能被套牌名冒充
assert.match(unknown, /名字里写着某主将/);
// 套牌列的 <td> 之后紧跟的主将列必须是占位符
assert.match(unknown, /<td class="clip"[^>]*>.*<\/td>\s*<td>–<\/td>/s);

const noGames = context.gameDetails({...known, match_mode: '未知', games: []});
assert.match(noGames, /未知/);

console.log('Match details identity and folded-diagnostics checks passed');
