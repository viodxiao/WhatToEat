import { element, renderRecipeList } from './app.js';

const form = document.querySelector('#nl-form');
const output = document.querySelector('#nl-output');

// 结果直接复用主列表那套卡片渲染：菜单、详情、缺料提示都不再各写一份
let last = null;
const limits = {ready: 6, related: 6};

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

function draw() {
  const {parsed, result} = last;
  output.dataset.state = 'done';
  output.replaceChildren();
  output.append(element('p', 'nl-hint', parsed.assumptions.join('；')));
  for (const [key, label] of [['ready', '符合条件的候选'], ['related', '仍缺食材的候选']]) {
    const items = result[key];
    if (!items.length) continue;
    const group = element('section', `result-group ${key}`);
    group.append(element('h3', '', `${label} · ${items.length}`));
    renderRecipeList(group, items, limits[key], () => {
      limits[key] += 12;
      draw();
    });
    output.append(group);
  }
  if (!result.ready.length && !result.related.length) {
    output.append(element('p', 'results-empty', '没有符合当前条件的菜谱。'));
  }
  const details = element('details', 'nl-conditions');
  details.append(element('summary', '', '查看搜索条件'),
                 element('pre', '', JSON.stringify(parsed.search_payload, null, 2)));
  output.append(details);
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  status('busy', '正在理解需求…');
  try {
    const parsed = await post('/api/parse', {text: form.elements.text.value, use_ontology: form.elements.ontology.checked});
    if (parsed.status !== 'ready') {
      status('notice', '需要补充或调整需求：' + parsed.reasons.join('；'));
      return;
    }
    const result = await post('/api/search', parsed.search_payload);
    limits.ready = 6;
    limits.related = 6;
    last = {parsed, result};
    draw();
  } catch (error) { status('error', error.message); }
  finally { button.disabled = false; }
});
