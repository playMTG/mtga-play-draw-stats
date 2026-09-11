const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');
const context = vm.createContext({
  esc: value => String(value ?? '').replace(/[&<>"']/g, ''),
  cardsMarkup: cards => cards?.length ? cards.map(card => card.name).join(' / ') : '–',
});
vm.runInContext(
  source.slice(source.indexOf('const ARCH_ZH'), source.indexOf('async function tagOpp')),
  context,
);

const tagged = context.opponentProfileMarkup({
  match_id:'match-1', event_id:'Ladder', opponent_type_eligible:true,
  opp_archetype_tag:'Ramp',
}, []);
assert.match(tagged, /Ramp/);
assert.match(tagged, /match-arch-select/);
assert.match(tagged, /data-match-id="match-1"/);
assert.match(tagged, /清除类型/);

const untagged = context.opponentProfileMarkup({
  match_id:'match-2', event_id:'Ladder', opponent_type_eligible:true,
}, []);
assert.match(untagged, /未标/);
assert.match(untagged, /标注类型/);

assert.match(context.opponentProfileMarkup({
  match_id:'brawl', event_id:'Play_Brawl_Historic', opponent_type_eligible:false,
}, [{name:'对手主将'}]), /对手主将/);
assert.match(context.opponentProfileMarkup({
  match_id:'draft', event_id:'PremierDraft_TEST', opponent_type_eligible:false,
}, []), /不适用/);

console.log('Constructed opponent type tagging controls and applicability checks passed');
