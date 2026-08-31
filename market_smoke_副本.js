// Headless smoke test for the MARKET tab stock-chart hover interactions:
//  - hovering a quarter flag (lane) shows the earnings card
//  - hovering its direction stud (price-line triangle) shows the SAME card
//  - during flag/stud hover the 3 charts are un-linked (no simultaneous cards)
//  - pointer NEAR a flag (not on the symbol): axis broadcast recipients render NO card
//  - leaving the chart restores the shared connect group
const fs = require('fs');

const elements = {};
function makeEl(id) {
  return {
    id, innerHTML: '', textContent: '', value: '', style: {}, dataset: {},
    className: '', offsetWidth: 800, offsetHeight: 400, clientHeight: 380, clientWidth: 760,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    _h: {},
    addEventListener(ev, fn) { this._h[ev] = fn; },
    removeEventListener() {},
    appendChild() {}, removeChild() {}, setAttribute() {}, getAttribute() { return null; },
    querySelectorAll() { return []; }, querySelector() { return null; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: 600 }; },
    getContext() { return null; },
  };
}
global.document = {
  getElementById(id) { if (!elements[id]) elements[id] = makeEl(id); return elements[id]; },
  querySelectorAll() { return []; },
  querySelector() { return makeEl('__q'); },
  createElement(tag) { return makeEl('created_' + tag); },
  addEventListener() {}, removeEventListener() {},
  body: makeEl('body'),
};
let loadFn = null;
global.window = {
  addEventListener(ev, fn) { if (ev === 'load') loadFn = fn; },
  removeEventListener() {},
  innerWidth: 1280, innerHeight: 900, devicePixelRatio: 1,
  location: { hash: '' },
};
global.navigator = { userAgent: 'node-smoke-test' };
global.requestAnimationFrame = (fn) => fn();

// ── echarts stub: capture options / event handlers / actions / group ──
const chartInstances = [];
function makeChart(el) {
  const inst = {
    group: null, _opt: null, handlers: {}, actions: [],
    setOption(opt) { inst._opt = opt; },
    on(ev, fn) { (inst.handlers[ev] = inst.handlers[ev] || []).push(fn); },
    off(ev) { delete inst.handlers[ev]; },
    dispatchAction(a) { inst.actions.push(a); },
    convertToPixel() { return [10, 10]; },
    resize() {}, dispose() {},
    fire(ev, p) { (inst.handlers[ev] || []).forEach((fn) => fn(p)); },
  };
  chartInstances.push(inst);
  return inst;
}
global.echarts = {
  init: (el) => makeChart(el),
  connect(charts) {                    // mimic real connect: assign + RETURN shared group name
    charts.forEach((c) => { c.group = 'g_test'; });
    return 'g_test';
  },
  use() {}, registerTheme() {},
};
global.window.echarts = global.echarts;

const html = fs.readFileSync(process.argv[2] || 'dashboard.html', 'utf8');
const scriptBlocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((x) => x[1]);
const appScript = scriptBlocks.find((b) => b.includes('var RAW ='));
if (!appScript) { console.error('FAIL: no app script block found'); process.exit(1); }
try { (0, eval)(appScript); } catch (e) { console.error('FAIL: script eval error:', e.message); process.exit(1); }
try { if (loadFn) loadFn(); switchTab('market'); } catch (e) {
  console.error('FAIL: init/switchTab error:', e.stack); process.exit(1);
}

let pass = 0, fail = 0;
function check(name, cond) {
  if (cond) { pass++; console.log('  PASS', name); }
  else { fail++; console.log('  FAIL', name); }
}

console.log('— 市场行情 tab: 图表构建 —');
check('三张股价图已初始化', !!(stockCharts.bkng && stockCharts.expe && stockCharts.abnb));
check('connect 已生效并捕获共享组名', stockLinkGroup === 'g_test');
const bkngOpt = stockCharts.bkng && stockCharts.bkng._opt;
check('BKNG 图含旗标/图钉系列(3 series)', bkngOpt && bkngOpt.series.length === 3);
const fmt = bkngOpt && bkngOpt.tooltip.formatter;
check('tooltip formatter 可调用', typeof fmt === 'function');
if (bkngOpt) {
  const bkngSeries = MKT_DATA.stock_prices.BKNG;
  check('BKNG 日线从 2018 年开始', bkngSeries.dates[0] <= '2018-01-05');
  const aug28Index = bkngSeries.dates.indexOf('2026-08-28');
  check('BKNG 已补齐 2026-08-28 收盘价',
        aug28Index >= 0 && bkngSeries.close[aug28Index] === 205.63);
  check('BKNG 日线无非法收盘价', bkngSeries.close.every((v) => Number.isFinite(Number(v)) && Number(v) > 0));
  check('财报旗标轴与完整价格区间对齐', bkngOpt.xAxis[1].min <= '2018-01-05' && bkngOpt.xAxis[1].max === bkngSeries.dates[bkngSeries.dates.length - 1]);
}

console.log('— 财报卡片: 旗标 vs 图钉 —');
const e0 = MKT_DATA.earnings_dates.filter((e) => e.company === 'BKNG')[0];
check('存在 BKNG 财报日数据', !!e0);
if (e0 && fmt) {
  // 悬浮旗标(scatter series2) — 行情线参数故意给一个不匹配日期, 走 studMeta 精确定位
  const outFlag = fmt([
    { seriesType: 'line', seriesIndex: 0, seriesName: 'Booking', marker: '<span></span>', value: ['1900-01-01', 100] },
    { seriesType: 'scatter', seriesIndex: 2, dataIndex: 0, value: [e0.date, 0.5] },
  ]);
  // 悬浮图钉(scatter series1) — 同一 dataIndex
  const outStud = fmt([
    { seriesType: 'line', seriesIndex: 0, seriesName: 'Booking', marker: '<span></span>', value: ['1900-01-01', 100] },
    { seriesType: 'scatter', seriesIndex: 1, dataIndex: 0, value: ['1900-01-01', 100] },
  ]);
  check('旗标悬浮显示财报卡片(季度+财报日)', outFlag.includes(e0.quarter) && outFlag.includes('财报日'));
  check('旗标悬浮头部为财报日本身', outFlag.includes(e0.date));
  check('图钉悬浮显示相同卡片', outStud === outFlag);
  check('无匹配价格点时以首交易日收盘补价格行', /\(\d{4}-\d{2}-\d{2} 收盘\): <b>\$/.test(outFlag));

  // 行情线上的普通悬浮(无 scatter): 正常价格行, 不出卡片(选一个非财报日)
  let normalDate = '2026-06-15';
  while (MKT_DATA.earnings_dates.some((e) => e.company === 'BKNG' && e.date === normalDate)) normalDate = '2026-06-16';
  const outLine = fmt([{ seriesType: 'line', seriesIndex: 0, seriesName: 'Booking', marker: '<span></span>', value: [normalDate, 1234.5] }]);
  check('普通悬浮: 日期+价格行', outLine.includes(normalDate) && outLine.includes('$1234.50'));
  check('普通悬浮(非财报日): 无财报卡片', !outLine.includes('财报日'));
  const outNaN = fmt([{ seriesType: 'line', seriesIndex: 0, seriesName: 'Booking', marker: '<span></span>', value: ['2026-08-28', NaN] }]);
  check('轴指针超出最后价格点时不显示 $NaN', !outNaN.includes('$NaN'));
}

console.log('— 悬浮期间断开三图联动 —');
const bk = stockCharts.bkng, ex = stockCharts.expe, ab = stockCharts.abnb;
bk.actions.length = 0; ex.actions.length = 0; ab.actions.length = 0;
bk.fire('mouseover', { componentType: 'series', seriesIndex: 2, dataIndex: 0 });   // 悬浮旗标
check('悬浮旗标: 三图组名改为独占(断开联动)', bk.group === 'solo_bkng' && ex.group === 'solo_expe' && ab.group === 'solo_abnb');
check('其他两图被隐藏悬浮框(hideTip)', ex.actions.some((a) => a.type === 'hideTip') && ab.actions.some((a) => a.type === 'hideTip'));
check('悬浮图本身不 hideTip', !bk.actions.some((a) => a.type === 'hideTip'));
bk.fire('globalout', {});
check('离开图表: 恢复共享组名(联动回归)', bk.group === 'g_test' && ex.group === 'g_test' && ab.group === 'g_test');

// 图钉悬浮同样断开
bk.fire('mouseover', { componentType: 'series', seriesIndex: 1, dataIndex: 0 });   // 悬浮图钉
check('悬浮图钉: 同样断开联动', bk.group === 'solo_bkng' && ex.group !== 'g_test');
bk.fire('mouseout', { seriesIndex: 1 });
check('移出图钉: 恢复联动', bk.group === 'g_test');

// 事件卡片本身的联动(setEventEmphasis)不受影响
check('事件卡片 hover 联动函数仍可用', typeof setEventEmphasis === 'function');

console.log('— 旗标周围: 轴广播接收方不出卡(用户bug场景) —');
// 场景: 指针进入 BKNG 容器但落在旗标"周围"(未压中符号) — 无 series mouseover,
// 断链不触发、三图仍共享组; 此时 connect 把轴位置广播给其余图, 接收方命中自己的
// 旗标点也只显示价格行, 不出财报卡(否则出现截图里 EXPE/ABNB 两卡同屏)
const bkEl = elements['c_stock_bkng'];
check('容器已挂 mouseenter/mouseleave 跟踪', !!(bkEl._h.mouseenter && bkEl._h.mouseleave));
if (bkEl._h.mouseenter) bkEl._h.mouseenter();
check('指针进入BKNG容器: stockHoverKey=bkng', stockHoverKey === 'bkng');
check('未压中符号: 三图仍共享组(轴广播活跃)', bk.group === 'g_test' && ex.group === 'g_test' && ab.group === 'g_test');
const expeFmt = stockCharts.expe && stockCharts.expe._opt.tooltip.formatter;
const ex0 = MKT_DATA.earnings_dates.filter((e) => e.company === 'EXPE')[0];
if (expeFmt && ex0) {
  const outBc = expeFmt([
    { seriesType: 'line', seriesIndex: 0, seriesName: 'Expedia', marker: '<span></span>', value: ['1900-01-01', 100] },
    { seriesType: 'scatter', seriesIndex: 2, dataIndex: 0, value: [ex0.date, 0.5] },
  ]);
  check('接收方命中自己旗标: 不出财报卡', !outBc.includes('财报日') && !outBc.includes('不及预期') && !outBc.includes('超预期'));
  check('接收方降级仍有内容(价格行/日期)', outBc.length > 10);
  const outLocal = fmt([
    { seriesType: 'line', seriesIndex: 0, seriesName: 'Booking', marker: '<span></span>', value: ['1900-01-01', 100] },
    { seriesType: 'scatter', seriesIndex: 2, dataIndex: 0, value: [e0.date, 0.5] },
  ]);
  check('指针所在图自身照常出卡(本图不受抑制)', outLocal.includes(e0.quarter) && outLocal.includes('财报日'));
}
if (bkEl._h.mouseleave) bkEl._h.mouseleave();
check('指针离开容器: 跟踪清空', stockHoverKey === null);
if (expeFmt && ex0) {
  const outBc2 = expeFmt([
    { seriesType: 'line', seriesIndex: 0, seriesName: 'Expedia', marker: '<span></span>', value: ['1900-01-01', 100] },
    { seriesType: 'scatter', seriesIndex: 2, dataIndex: 0, value: [ex0.date, 0.5] },
  ]);
  check('无指针跟踪时默认本图语义(卡恢复, 兼容旧行为)', outBc2.includes(ex0.quarter) && outBc2.includes('财报日'));
}
bk.fire('mouseover', { componentType: 'series', seriesIndex: 2, dataIndex: 0 });
check('旗标mouseover兜底设置指针所在图', stockHoverKey === 'bkng');
bk.fire('globalout', {});

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
