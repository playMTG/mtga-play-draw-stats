// 争锋主将类型的多标签渲染与打标控件。
//
// 背景：争锋里很多卡组有多种玩法轴（如始霸埃泰力既算 Ramp 也算组合技），
// 类型字段因此从单值字符串变成标签集合。这里锁住渲染层的行为：
// 旧单值数据仍要能显示，多标签要各出一个 chip，空集合回落「未标」。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync('web/app.js', 'utf8');

const START = 'const ARCH_ZH';
const END = 'async function tagOpp';
const start = source.indexOf(START);
const end = source.indexOf(END);
assert.ok(start > 0, `切片起点未找到：${START}`);
assert.ok(end > start, `切片终点未找到或早于起点：${END}`);

const context = vm.createContext({
  esc: value => String(value ?? '').replace(/[&<>"']/g, ''),
});
vm.runInContext(source.slice(start, end), context);

// ---- 标签渲染 ----
// 兼容旧的单值形态
assert.match(context.archTag('Combo'), /组合技/);

// 多标签：两个 chip 都要渲染
const multi = context.archTag(['Combo', 'Ramp']);
assert.match(multi, /组合技/);
assert.match(multi, /Ramp/);
assert.equal(
  (multi.match(/<span class="tag"/g) || []).length,
  2,
  '多标签应渲染出两个 chip',
);

// 空集合与非列表输入
assert.match(context.archTag([]), /未标/);
assert.match(context.archTag(null), /未标/);
assert.match(context.archTag(undefined), /未标/);

// 非法的标签名按原样显示，不应崩
assert.match(context.archTag(['Bogus']), /Bogus/);

// ---- 打标控件 ----
const sel = context.archSelect('grpId:84411', ['Combo', 'Ramp']);
assert.match(sel, /toggleOppTag/);
assert.match(sel, /data-tag="Combo"/);
assert.match(sel, /data-tag="Ramp"/);
assert.match(sel, /打标（2）/, '已选两个标签时下拉标题应显示计数');
assert.match(sel, /清除/);

// 未打标时：标题不带计数，且全部按钮都是未选中态
const empty = context.archSelect('grpId:1', []);
assert.match(empty, /打标</);
assert.ok(!/arch-chip on/.test(empty), '空标签时不应有选中态按钮');

// 单值输入也要能标出选中态（兼容旧数据）
const single = context.archSelect('grpId:1', 'Ramp');
assert.match(single, /class="arch-chip on"[^>]*data-tag="Ramp"/, '单值应渲染为选中态');

// 主将名含单引号时不能把 inline onclick 打断
const quoted = context.archSelect("Harvest's Hand", []);
assert.match(quoted, /Harvest\\'s Hand/, '单引号必须转义，否则 inline 属性会断裂');
assert.ok(!/onclick="[^"]*'Harvest's/.test(quoted), '未转义的单引号会截断 onclick');

console.log('Commander archetype multi-label rendering passed');
