const form = document.querySelector('#nl-form');
const output = document.querySelector('#nl-output');

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
    status('done', '');
    const hint = document.createElement('p');
    hint.className = 'nl-hint';
    hint.textContent = parsed.assumptions.join('；');
    output.append(hint);
    for (const [label, items] of [['符合条件的候选', result.ready], ['仍缺食材的候选', result.related]]) {
      const title = document.createElement('p');
      title.className = 'nl-group-title';
      title.textContent = `${label}：${items.length} 道（最多展示 10 道）`;
      output.append(title);
      for (const item of items.slice(0, 10)) {
        const row = document.createElement('p');
        row.className = 'nl-item';
        row.textContent = item.name + (item.missing.length ? `，还缺：${item.missing.join('、')}` : '');
        output.append(row);
      }
    }
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = '查看搜索条件';
    const pre = document.createElement('pre'); pre.textContent = JSON.stringify(parsed.search_payload, null, 2);
    details.append(summary, pre); output.append(details);
  } catch (error) { status('error', error.message); }
  finally { button.disabled = false; }
});
