// Headless smoke test for the ST user-data controls.
// Verifies country multi-select state/order/lifecycle and App-level control hierarchy.
const fs = require('fs');

const target = process.argv[2] || 'dashboard.html';
const html = fs.readFileSync(target, 'utf8');
let pass = 0;
let fail = 0;

function check(name, condition) {
  if (condition) {
    pass += 1;
    console.log('  PASS', name);
  } else {
    fail += 1;
    console.log('  FAIL', name);
  }
}

function position(source, needle) {
  return source.indexOf(needle);
}

console.log('— 国家/地区多选结构 —');
check('旧国家总开关已删除', !html.includes('stCountryToggle') && !html.includes('stCountryArrow'));
check('旧 countryOpen 状态已删除', !html.includes('countryOpen'));
check('国家选择组具备可访问名称', html.includes('id="stCountryChoices"') && html.includes('aria-label="选择国家或地区"'));
check('国家按钮使用 aria-pressed', html.includes('class="st-country-chip') && html.includes('aria-pressed="'));
check('国家默认零选择', /selectedCountries:\s*\[\]/.test(html));

const countryNames = ['中国香港', '新加坡', '日本', '韩国', '泰国', '马来西亚', '印度', '菲律宾', '越南'];
let previousCountry = -1;
let countryOrderOk = true;
for (const name of countryNames) {
  const current = position(html, `{key:` + ({
    中国香港: '"hk"', 新加坡: '"sg"', 日本: '"jp"', 韩国: '"kr"', 泰国: '"th"',
    马来西亚: '"my"', 印度: '"in"', 菲律宾: '"ph"', 越南: '"vn"',
  })[name] + `, name:"${name}"}`);
  if (current < 0 || current <= previousCountry) countryOrderOk = false;
  previousCountry = current;
}
check('九个国家配置完整且顺序固定', countryOrderOk);
check('多选状态支持添加与取消', html.includes('stState.selectedCountries.push(countryKey)') && html.includes('stState.selectedCountries.splice(idx, 1)'));
check('图表按固定国家配置顺序渲染', html.includes('ST_COUNTRIES.forEach(function(c){') && html.includes('if(stState.selectedCountries.indexOf(c.key) === -1) return;'));
check('取消选择销毁对应 ECharts 实例', html.includes('stDisposeCountryChart(countryKey)') && html.includes('charts[chartId].dispose()'));
check('resize 只重绘已有国家选择', html.includes('if(stState.selectedCountries.length && typeof stRenderCountries'));
check('国家选择不写入 localStorage', !/localStorage[^\n]*(selectedCountries|countrykey)/.test(html));

console.log('— App 控制层级 —');
check('标题说明只保留一份', (html.match(/<h3>OTA App 用户数据对比<\/h3>/g) || []).length === 1);
check('动态视图仅生成一个控制卡', (html.match(/class=\\?"st-app-control\\?"/g) || []).length === 1);
check('动态视图仅生成一个图表卡', (html.match(/class=\\?"st-app-panel\\?"/g) || []).length === 1);
const appControlStart = position(html, "html += '<div class=\"st-app-control\">'");
const appPanelStart = position(html, "html += '<div class=\"st-app-panel\">'");
const appMetricStart = position(html, 'data-appmetric');
check('App 指标切换位于图表卡内', appPanelStart >= 0 && appMetricStart > appPanelStart);
check('App 图表卡同时包含指标与展示模式', appMetricStart > appPanelStart && position(html, 'data-appmode') > appPanelStart);
check('市场与 App 指标状态独立', /metric:\s*"MAU"/.test(html) && /appMetric:\s*"MAU"/.test(html));
check('App 默认回退到 Trip.com', html.includes('stState.appActive = ST_APPS[0].key'));
check('App 维持单选 aria 状态', html.includes('data-appkey=') && html.includes("var act = stState.appActive === a.key"));
check('App 选择栏不再显示冗余标签', !html.includes('st-app-rail-cap') && !html.includes('>选择 App</span>'));
check('App 指标和模式 aria 属性闭合', html.includes("+ '\">' + m + '</button>'") && html.includes("+ '\">' + m[1] + '</button>'"));
check('App 模式继续按 App 记忆', html.includes('stState.appMode[stState.appActive] = nextMode'));

console.log('— 响应式与维护性 —');
check('移动端国家与 App 选择栏横向滚动', html.includes('.st-country-rail,.st-app-rail{flex-wrap:nowrap;overflow-x:auto'));
check('国家图表保持单列', html.includes('#stCountriesGrid{display:grid;grid-template-columns:1fr'));
check('国家与 App 列表集中配置', (html.match(/var ST_COUNTRIES =/g) || []).length === 1 && (html.match(/var ST_APPS =/g) || []).length === 1);
check('stRenderAppCharts 仅定义一次', (html.match(/function stRenderAppCharts\(/g) || []).length === 1);

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
