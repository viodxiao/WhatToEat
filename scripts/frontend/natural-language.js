const form = document.querySelector('#nl-form');
const output = document.querySelector('#nl-output');

// 共享渲染器用动态导入：即使 app.js 加载失败，submit 处理器也已经挂上，
// preventDefault 一定生效，不会退化成浏览器默认提交导致整页刷新。
let shared = null;
const limits = {ready: 6, related: 6, tools: 6};
let last = null;

async function renderer() {
  if (shared) return shared;
  try {
    shared = await import('./app.js');
    return shared;
  } catch {
    throw new Error('界面组件加载失败（可能是浏览器缓存了旧脚本），请按 Ctrl+F5 强制刷新后重试');
  }
}

function status(state, text) {
  output.dataset.state = state;
  output.replaceChildren();
  if (text) output.textContent = text;
}

async function post(url, body) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求参数无效');
  return data;
}

async function draw(ui) {
  const {element, renderRecipeList} = ui;
  const {parsed, result} = last;
  // 佐料/厨具在请求体里表示「用户没有」，交给卡片把对应备选项划掉
  const payload = parsed.search_payload ?? {};
  const excluded = {
    seasoning: new Set(payload.seasonings ?? []),
    tool: new Set(payload.tools ?? []),
  };
  output.dataset.state = 'done';
  output.replaceChildren();
  output.append(element('p', 'nl-hint', parsed.assumptions.join('；')));
  for (const [key, label] of [['ready', '符合条件的候选'], ['related', '缺食材或佐料的候选'],
                              ['tools', '缺少厨具的候选']]) {
    const items = result[key] ?? [];
    if (!items.length) continue;
    const group = element('section', `result-group ${key}`);
    group.append(element('h3', '', `${label} · ${items.length}`));
    renderRecipeList(group, items, limits[key], async () => {
      limits[key] += 12;
      await draw(await renderer());
    }, excluded);
    output.append(group);
  }
  if (!result.ready.length && !result.related.length && !(result.tools ?? []).length) {
    output.append(element('p', 'results-empty', '没有符合当前条件的菜谱。'));
  }
  const details = element('details', 'nl-conditions');
  details.append(element('summary', '', '查看搜索条件'),
                 element('pre', '', JSON.stringify(parsed.search_payload, null, 2)));
  output.append(details);
}

form?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  status('busy', '正在理解需求…');
  try {
    const ui = await renderer();
    const parsed = await post('/api/parse', {text: form.elements.text.value, use_ontology: form.elements.ontology.checked});
    if (parsed.status !== 'ready') {
      status('notice', '需要补充或调整需求：' + parsed.reasons.join('；'));
      return;
    }
    const result = await post('/api/search', parsed.search_payload);
    limits.ready = 6;
    limits.related = 6;
    limits.tools = 6;
    last = {parsed, result};
    await draw(ui);
  } catch (error) { status('error', error.message); }
  finally { button.disabled = false; }
});
