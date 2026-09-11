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

vm.runInContext(
  source.slice(source.indexOf('function sourceLabel'), source.indexOf('function eventMarkup')),
  context,
);

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
assert.match(row, /<summary>查看<\/summary>/);
assert.match(row, /BO3/);
assert.match(row, /查看 2 局/);
assert.match(row, /第 1 局 · 后手 · 负/);
assert.match(row, /第 2 局 · 先手 · 胜/);
assert.match(details, /结束原因.*投降/);
assert.match(details, /数据来源.*Untapped 历史导入/);
assert.match(details, /套牌 ID.*deck-1/);
assert.match(details, /构筑版本.*version-1/);

const unknown = context.matchRow({
  ...known, match_id: 'unknown', my_deck_tag: '名字里写着某主将',
  my_cards: [], my_cmdrs: [],
});
assert.match(unknown, /名字里写着某主将/);
assert.match(unknown, /<td>未记录<\/td>/);

const noGames = context.gameDetails({...known, match_mode: '未知', games: []});
assert.match(noGames, /未知/);
assert.match(noGames, /逐局未记录/);

console.log('Match details identity and folded-diagnostics checks passed');
