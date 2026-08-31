// Headless smoke test for the OTA dashboard news tab (5模块结构, 2026-08-18)
// 模块映射: intl_core_company→coreCompanyList | intl_industry→intlIndustryList |
//          intl_disclosures→intlDisclosureList | dom_industry→domIndustryList |
//          dom_disclosures→domDisclosureList
const fs = require('fs');

const elements = {};
function makeEl(id) {
  return {
    id, innerHTML: '', textContent: '', value: '', style: {}, dataset: {},
    className: '', offsetWidth: 800, offsetHeight: 400,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {},
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
const echartsInstance = () => ({
  setOption() {}, resize() {}, dispose() {}, on() {}, off() {},
  dispatchAction() {}, getOption() { return { series: [] }; }, clear() {},
  convertToPixel() { return [0, 0]; },
});
global.echarts = { init: () => echartsInstance(), connect() {}, use() {}, registerTheme() {} };
global.requestAnimationFrame = (fn) => fn();

const html = fs.readFileSync(process.argv[2] || 'dashboard.html', 'utf8');
const scriptBlocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x => x[1]);
const appScript = scriptBlocks.find(b => b.includes('var RAW ='));
if (!appScript) { console.error('FAIL: no app script block found'); process.exit(1); }

try {
  (0, eval)(appScript);
} catch (e) {
  console.error('FAIL: script eval error:', e.message);
  process.exit(1);
}

try {
  if (loadFn) loadFn();          // init()
  switchTab('latest');            // render news tab
} catch (e) {
  console.error('FAIL: init/switchTab error:', e.stack);
  process.exit(1);
}

let pass = 0, fail = 0;
function check(name, cond) {
  if (cond) { pass++; console.log('  PASS', name); }
  else { fail++; console.log('  FAIL', name); }
}
const h = (id) => (elements[id] ? elements[id].innerHTML : '');
const count = (id) => (h(id).match(/class="[^"]*\bnews-item\b[^"]*"/g) || []).length;
const renderedText = (id, className) => {
  const re = new RegExp('<div class="' + className + '"[^>]*>([\\s\\S]*?)<\\/div>', 'g');
  return [...h(id).matchAll(re)].map(m => m[1].replace(/<[^>]+>/g, '').trim());
};

// ══════════ 5 模块结构验收（2026-08-18 重构） ══════════
console.log('— 国际·披露与文件 (intlDisclosureList) —');
check('intlDisclosureList 有条目', count('intlDisclosureList') > 0);
check('披露模块含Rule 144', h('intlDisclosureList').includes('Rule 144'));
check('三家公司徽章都有颜色(无#666灰)', !h('intlDisclosureList').includes('#666'));
const disclosureSummaries = renderedText('intlDisclosureList', 'news-summary');
const disclosureTitles = renderedText('intlDisclosureList', 'news-title');
check('披露标题与已展示摘要均含中文',
      disclosureTitles.every(t => /[\u4e00-\u9fff]/.test(t)) &&
      disclosureSummaries.every(t => /[\u4e00-\u9fff]/.test(t)));
check('SEC Form 4/Rule 144展示具体交易摘要而非表单占位',
      disclosureSummaries.some(t => /股|美元|经纪商|10b5-1/.test(t)) &&
      !disclosureSummaries.some(t => /向SEC提交(?:董事\/高管交易|证券出售登记)/.test(t)));

console.log('— 国际·核心公司动态 (coreCompanyList) —');
check('coreCompanyList 有条目', count('coreCompanyList') > 0);
check('核心公司含 ticker 徽章(BKNG/EXPE/ABNB)', /BKNG|EXPE|ABNB/.test(h('coreCompanyList')));
check('官方IR投资者大会公告进核心公司动态',
      /Communacopia|TMT大会/.test(h('coreCompanyList')) &&
      /Booking Holdings IR|Expedia Group IR|Airbnb IR/.test(h('coreCompanyList')));
const newsContainers = ['coreCompanyList','intlIndustryList','domIndustryList'];
const renderedTitles = newsContainers.flatMap(id =>
  renderedText(id, 'news-title'));
const renderedSummaries = newsContainers.flatMap(id =>
  renderedText(id, 'news-summary'));
check('所有展示中的新闻标题均含中文',
      renderedTitles.length > 0 && renderedTitles.every(t => /[\u4e00-\u9fff]/.test(t)));
check('所有实际展示的新闻摘要均含中文（允许无摘要）',
      renderedSummaries.length > 0 &&
      renderedSummaries.every(t => /[\u4e00-\u9fff]/.test(t)));
check('不生成“公开信息显示+标题”占位摘要',
      !renderedSummaries.some(t => /^公开信息显示，/.test(t)));

console.log('— 国际·行业新闻 (intlIndustryList) —');
check('intlIndustryList 有条目', count('intlIndustryList') > 0);
check('环球旅讯海外交易进入国际行业',
      h('intlIndustryList').includes('eTravel') && h('intlIndustryList').includes('Spotnana'));
const intlIndustryBadges = [...h('intlIndustryList').matchAll(/<span class="news-tag"[^>]*>([^<]+)<\/span>/g)]
  .map(x => x[1].trim());
check('国际行业中不再显示BKNG/EXPE/ABNB核心公司徽章',
      !intlIndustryBadges.some(x => ['BKNG','EXPE','ABNB'].includes(x)));

console.log('— 国内·行业新闻 (domIndustryList) —');
check('domIndustryList 有条目', count('domIndustryList') > 0);
check('环球旅讯三条海外交易不再进入国内',
      !h('domIndustryList').includes('eTravel') &&
      !h('domIndustryList').includes('VayKLife') &&
      !h('domIndustryList').includes('Spotnana'));

console.log('— 国内·披露与文件 (domDisclosureList) —');
check('domDisclosureList 有条目', count('domDisclosureList') > 0);
check('国内披露含文旅部或交通运输部或披露易',
      h('domDisclosureList').includes('文旅部') ||
      h('domDisclosureList').includes('交通运输部') ||
      h('domDisclosureList').includes('披露易'));

console.log('— 国内无独立核心公司子模块 —');
check('国内行业含东航标签(entity_id=CEAIR 或 中国东航)',
      h('domIndustryList').includes('中国东航') || h('domIndustryList').includes('CEAIR'));
check('无旧缓存脏数据(国际航线/机场徽章)',
      !h('domIndustryList').includes('>国际航线<') && !h('domIndustryList').includes('>机场<') && !h('domIndustryList').includes('>要闻<'));

console.log('— 其他 —');
check('更新时间已填充', /更新于|数据截至/.test((elements['newsUpdateTime'] && elements['newsUpdateTime'].textContent || '')));

console.log('— 筛选管道 —');
check('raw HTML 无"来源未提供足够公开信息"占位残留', !html.includes('来源未提供足够公开信息'));
const selStatuses = [];
var _nd = MKT_DATA.news_data || {};
Object.values(_nd.international || {}).forEach(arr =>
  (Array.isArray(arr) ? arr : []).forEach(i => selStatuses.push(i.selection_status)));
Object.values(_nd.domestic || {}).forEach(arr =>
  (Array.isArray(arr) ? arr : []).forEach(i => selStatuses.push(i.selection_status)));
Object.values(_nd.modules || {}).forEach(arr =>
  (Array.isArray(arr) ? arr : []).forEach(i => selStatuses.push(i.selection_status)));
check('页面数据无 selection_status=rejected 条目',
  selStatuses.length > 0 && selStatuses.every(x => x === undefined || x === 'kept'));

// ══════════ 安全段（改造项⑨）: 恶意HTML / javascript URL / 日期与状态 / 折叠 / 空摘要 ══════════
console.log('— 安全: 单元级 —');
check('escapeHtml 转义 <>&"\'',
  escapeHtml('<img src=x>&"\'') === '&lt;img src=x&gt;&amp;&quot;&#39;');
check('escapeHtml(null/undefined) 不炸', escapeHtml(null) === '' && escapeHtml(undefined) === '');
check('safeExternalUrl 放行 https/http',
  safeExternalUrl('https://skift.com/x') === 'https://skift.com/x'
  && safeExternalUrl('http://www.mot.gov.cn/x') === 'http://www.mot.gov.cn/x');
check('safeExternalUrl 拒绝 javascript:', safeExternalUrl('javascript:alert(1)') === '');
check('safeExternalUrl 拒绝大小写混淆', safeExternalUrl(' JaVaScRiPt:alert(1)') === '');
check('safeExternalUrl 拒绝 data:', safeExternalUrl('data:text/html,<b>x</b>') === '');
check('safeExternalUrl 拒绝空/相对路径', safeExternalUrl('') === '' && safeExternalUrl('/path/x') === '');

console.log('— 安全: 渲染级(恶意fixture注入, 5模块结构) —');
// 用恶意 fixture 覆盖新闻数据（新 modules 结构），重渲染全部列表
MKT_DATA.news_data = {
  last_updated: '2026-08-18 10:00:00',
  update_status: 'partial',
  fetch_status: { sources: { 'Skift': { status: 'success' }, 'Bloomberg Markets': { status: 'failed' } } },
  // 新 5 模块结构（renderNewsTab 优先使用 modules）
  modules: {
    intl_disclosures: [
      { date: '2026-08-15', company: 'BKNG', type: '10-Q', title: '<script>alert("sec")</script>',
        url: 'javascript:alert(1)', source: 'SEC EDGAR',
        summary: 'Booking Holdings 于 2026-08-15 提交 10-Q 季度报告' },
      { date_status: 'unknown', date: '', company: 'ABNB', type: '8-K', title: '无日期披露',
        url: 'https://www.sec.gov/ok', source: 'SEC EDGAR' },
    ],
    intl_core_company: [
      { date: '2026-08-17', title: 'BKNG 收购 AI 初创公司', summary: '产品合作动态',
        url: 'https://ir.bookingholdings.com/x', source: 'Booking Holdings IR',
        entity_id: 'BKNG', is_core_company: true, selection_status: 'kept', selection_score: 78 },
    ],
    intl_industry: [
      { date: '2026-08-17', title: '<img src=x onerror=alert(2)>恶意标题', summary: '<b>加粗注入</b>&"',
        url: 'https://skift.com/ok', source: 'Skift' },
      { date: '2026-08-17', title: 'javascript URL 条目', summary: '基于标题的摘要',
        url: 'javascript:alert(3)', source: 'Skift' },
      { date: '2026-08-16', title: '空摘要条目(非付费墙)', summary: '', url: 'https://skift.com/empty', source: 'Skift' },
      { date: '2026-08-16', title: '被折叠条目(不应渲染)', url: 'https://skift.com/folded',
        folded_into: 'https://skift.com/empty', source: 'Skift' },
      { date: '2026-08-15', title: '付费墙空摘要(不显示占位)', summary: '', paywall: true,
        url: 'https://skift.com/pw', source: 'WSJ' },
      { date_status: 'unknown', date: '', title: '未知日期条目', url: 'https://skift.com/nodate', source: 'Skift' },
    ],
    dom_industry: [],
    dom_disclosures: [],
  },
  // 向后兼容：旧 partition 结构（renderNewsTab 在无 modules 时回退使用）
  international: { sec_filings: [], industry_news: [] },
  domestic: { china_industry: [], regulatory: [], company_news: [] },
};
renderNewsTab();

var secH = h('intlDisclosureList'), intlH = h('intlIndustryList');
check('SEC标题已转义(无原始<script>)', !secH.includes('<script>') && secH.includes('&lt;script&gt;'));
check('SEC无javascript:外链', !/href="[^"]*javascript:/i.test(secH));
check('SEC恶意URL条目降级为无链接标题(仅1个合法<a>)', secH.includes('alert(&quot;sec&quot;)') && (secH.match(/<a /g) || []).length === 1);
check('SEC未知日期显示待确认', secH.includes('待确认'));
check('新闻标题已转义(无原始<img onerror>)', !intlH.includes('<img src=x') && intlH.includes('&lt;img src=x'));
check('新闻摘要已转义(无原始<b>)', !intlH.includes('<b>加粗注入</b>') && intlH.includes('&lt;b&gt;加粗注入&lt;/b&gt;'));
check('新闻无javascript:/data:外链', !/href="[^"]*(javascript:|data:)/i.test(intlH));
check('外链带rel="noopener noreferrer"', (intlH.match(/rel="noopener noreferrer"/g) || []).length >= 2);
check('未知日期显示发布时间待确认', intlH.includes('发布时间待确认'));
check('空摘要不再显示整行占位提示', !intlH.includes('来源未提供足够公开信息'));
check('付费墙空摘要仅显示标题', intlH.includes('付费墙空摘要') && !intlH.includes('付费墙空摘要</div><div class="news-summary'));
check('folded_into条目不渲染', !intlH.includes('被折叠条目'));
check('partial状态行(1个失败)', (elements['newsUpdateTime'].textContent || '').includes('部分来源更新失败（1个）'));

MKT_DATA.news_data.update_status = 'failed';
renderNewsTab();
check('failed状态行提示缓存数据', (elements['newsUpdateTime'].textContent || '').includes('全部来源更新失败')
  && (elements['newsUpdateTime'].textContent || '').includes('以下为缓存数据'));

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
