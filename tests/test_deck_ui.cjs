const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');
const context = vm.createContext({
  esc: value => String(value ?? '').replace(/[&<>"']/g, ''),
  fmtTime: value => `time:${value}`,
  eventMarkup: (raw, label) => label || raw || '赛事未记录',
  cardMarkup: card => card.name,
  cardsMarkup: cards => cards?.length ? cards.map(card => card.name).join(' / ') : '–',
  gameDetails: row => `${row.match_mode || '未知'}：${row.games?.length || 0} 局`,
  opponentProfileMarkup: (row, cards) => row.opponent_type_eligible
    ? (row.opp_archetype_tag || '未标') : (cards?.map(card => card.name).join(' / ') || '不适用'),
  encodeURIComponent, decodeURIComponent, JSON,
});
// 切片哨兵：起点 deckLink，终点用后面第一个无关函数。
// 必须断言哨兵都能找到——否则 indexOf 返回 -1 会让 slice 把整份源码喂给 vm，
// 表现为「document is not defined」而在加载阶段静默崩掉（曾因此失效过）。
const START = 'function deckLink';
const END = 'function deckJourneyRender';
const start = source.indexOf(START);
const end = source.indexOf(END);
assert.ok(start > 0, `切片起点未找到：${START}`);
assert.ok(end > start, `切片终点未找到或早于起点：${END}`);
vm.runInContext(source.slice(start, end), context);

const link = context.deckLink({
  my_deck_tag: '拿杜', my_deck_id: 'deck-1', my_deck_version: 'title-v1:abc',
});
assert.match(link, /deck-open/);
assert.match(link, /拿杜/);
const payload = link.match(/data-deck="([^"]+)"/)[1];
assert.deepEqual(JSON.parse(decodeURIComponent(payload)), {
  deck: '拿杜', deck_id: 'deck-1', deck_version: 'title-v1:abc',
});

const report = {
  scope_label: '近 20 场', selected_version: null, version_count_in_scope: 2,
  unknown_version: 0,
  summary: {
    n: 20, win_rate: {wr: 55, wins: 11, n: 20},
    play: 8, draw: 12, unknown_play_draw: 0, play_rate: 40, draw_rate: 60,
    on_play: {wr: 62.5}, on_draw: {wr: 50},
  },
};
assert.match(context.deckSummaryMarkup(report), /近 20 场对局/);
assert.match(context.deckSummaryMarkup(report), /先手率/);
assert.match(context.deckVersionNote(report), /2 个构筑版本/);
report.selected_version = 'title-v1:abc';
assert.match(context.deckVersionNote(report), /单一构筑版本/);

const row = context.deckRecordRow({
  start_time: 1, event_id: 'Play_Brawl_Historic', event_label: '历史争锋',
  my_deck_tag: '拿杜', my_deck_version: 'title-v1:abc', play_draw: 'draw', my_result: 'win',
  opponent_cards: [{key:'100', name:'第一主将'}],
  match_mode: 'BO3', games: [{game_no:1}, {game_no:2}],
}, [{value: 'title-v1:abc', label: '版本 1'}]);
assert.match(row, /历史争锋/);
assert.match(row, /版本 1/);
assert.match(row, /第一主将/);
assert.match(row, /后手/);
assert.match(row, /胜/);
assert.match(row, /BO3：2 局/);

const commanders = {
  eligible: 5, known: 4, missing: 1, not_applicable: 2,
  multi_commander_matches: 1,
  rows: [{
    key:'100', name:'第一主将', share_known:75, n:3,
    play:1, draw:2, unknown_play_draw:0, wins:2, losses:1, unknown_result:0,
    win_rate:{wr:66.7}, on_play:{wr:100,n:1}, on_draw:{wr:50,n:2},
  }],
};
assert.match(context.deckCommanderCoverage(commanders), /5 场争锋对局/);
assert.match(context.deckCommanderCoverage(commanders), /主将已知 4 场/);
const commanderRows = context.deckCommanderRows(commanders, '100');
assert.match(commanderRows, /第一主将/);
assert.match(commanderRows, /75%/);
assert.match(commanderRows, /先 1 · 后 2/);
assert.match(commanderRows, /2 胜 1 负/);
assert.match(commanderRows, /deck-commander-open on/);

const observations = {items:[{
  key:'streak-draw', kind:'play_draw_streak', level:'legendary', n:8,
  headline:'连续 8 把后手：离谱级连庄',
  text:'当前范围内最长连续后手为 8 场，参考概率约 0.39%。',
  probability:{explanation:'扫描整个范围的概率，不是被针对概率。'},
}]};
const observationMarkup = context.deckObservationMarkup(observations, 'streak-draw');
assert.match(observationMarkup, /legendary/);
assert.match(observationMarkup, /连续 8 把后手/);
assert.match(observationMarkup, /0\.39%/);
assert.match(observationMarkup, /查看 8 场依据/);
assert.match(observationMarkup, /deck-observation-open on/);
assert.match(observationMarkup, /不是被针对概率/);

console.log('Deck detail identity links, observations, summaries, versions and rows passed');
