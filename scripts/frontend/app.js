import { drawIngredients, floatIngredients, shuffle } from "./motion.js";

const $ = selector => document.querySelector(selector);
const kinds = ["ingredient", "seasoning", "tool"];
const labels = { ingredient: "食材", seasoning: "佐料", tool: "厨具" };
const columns = { ingredient: "ingredients", seasoning: "seasonings", tool: "tools" };
const choices = Object.fromEntries(kinds.map(kind => [kind, new Set()]));
const difficulties = new Set([1, 2, 3, 4, 5]);
const categories = new Set();
const menu = new Map();
const rows = new Map();
const detailCache = new Map();
const stars = number => "★".repeat(number);
const detail = $("#detail");
const random = $("#random");
const refreshButton = $("#refresh-recipes");
const recipeSearch = $("#recipe-search");
const copyButton = $("#copy-missing");
const storageKey = "recipe-planner:kitchen:v1";
let recommendations = [];
let nameMatches = [];
let nameLimit = 14;
let resultData = { ready: [], related: [] };
let resultLimits = { ready: 14, related: 14 };
let openedRecipe;
let searchController;
let recipeSearchTimer;
let shoppingController;
let missingList = "";
let toastTimer;
let ready = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  const use = document.createElementNS(namespace, "use");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function button(text, className, handler, accessibleName) {
  const node = element("button", className, text);
  node.type = "button";
  if (accessibleName) node.setAttribute("aria-label", accessibleName);
  node.addEventListener("click", handler);
  return node;
}

async function json(url, body, signal) {
  const response = await fetch(url, body === undefined ? { signal, cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!response.ok) throw new Error(`请求失败（${response.status}）`);
  return response.json();
}

function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 2800);
}

function hasAvailableIngredients() {
  return choices.ingredient.size > 0 ||
    [...menu.values()].some(recipe => recipe.category === "配料");
}

function pantry() {
  return Object.fromEntries(kinds.map(kind => [columns[kind], [...choices[kind]]]));
}

function saveKitchen() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      ...pantry(),
      difficulties: [...difficulties],
      categories: [...categories],
      menu: [...menu.keys()],
    }));
  } catch {
    // The current session still works when browser storage is unavailable.
  }
}

function restoreKitchen(catalog) {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(storageKey));
  } catch {
    return;
  }
  if (!saved) return;
  for (const kind of kinds) {
    const previous = saved[columns[kind]];
    if (!Array.isArray(previous)) continue;
    const valid = new Set(catalog.facets[kind].filter(entry => !entry.prep_id).map(entry => entry.name));
    for (const name of previous) {
      if (valid.has(name)) choices[kind].add(name);
    }
  }
  if (Array.isArray(saved.difficulties)) {
    const levels = saved.difficulties.filter(level => Number.isInteger(level) && level >= 1 && level <= 5);
    if (!saved.difficulties.length || levels.length) {
      difficulties.clear();
      for (const level of levels) difficulties.add(level);
    }
  }
  if (Array.isArray(saved.categories)) {
    for (const name of catalog.categories) {
      if (saved.categories.includes(name)) categories.add(name);
    }
  }
  if (Array.isArray(saved.menu)) {
    const index = new Map(catalog.recipe_index.map(recipe => [recipe.id, recipe]));
    for (const id of saved.menu) {
      if (index.has(id)) menu.set(id, index.get(id));
    }
  }
}

function renderSelected() {
  const holder = $("#selections");
  holder.replaceChildren();
  for (const kind of kinds) {
    for (const name of choices[kind]) {
      const chip = element("span", `selected-chip${kind === "ingredient" ? "" : " unavailable"}`, name);
      chip.append(button("×", "", () => {
        choices[kind].delete(name);
        updateFilters();
        rows.get(kind).list.querySelector(`button[data-name="${CSS.escape(name)}"]`)?.focus();
      }, `撤销${labels[kind]}${name}`));
      holder.append(chip);
    }
  }
  if (!holder.childElementCount) holder.append(element("p", "", "点击标签：食材选你有的，佐料和厨具选你缺的。"));
  $("#clear").hidden = difficulties.size === 5 && !categories.size && !kinds.some(kind => choices[kind].size);
}

function buildFilters(facets, categoryNames) {
  for (const kind of kinds) {
    const caption = element("div", "filter-caption");
    caption.append(element("h3", "", labels[kind]), element("span", "", kind === "ingredient" ? "我手头有" : "只填我缺的"));
    const container = element("div");
    const search = element("label", "filter-input-wrap");
    search.style.display = "block";
    const input = element("input", "filter-input");
    input.type = "search";
    input.placeholder = `搜索${labels[kind]}`;
    input.setAttribute("aria-label", input.placeholder);
    input.addEventListener("input", () => renderRow(kind));
    search.append(icon("search"), input);
    const list = element("div", "filter-tags");
    container.append(search, list);
    const row = element("div", "filter-row");
    row.append(caption, container);
    $("#filters").append(row);
    const entries = facets[kind];
    const defaults = shuffle(entries.filter(entry => entry.in_csv)).slice(0, kind === "tool" ? 8 : 10);
    rows.set(kind, { input, list, entries, defaults });
    renderRow(kind);
  }

  for (let level = 1; level <= 5; level++) {
    const node = button(stars(level), "star-toggle", () => {
      if (!difficulties.delete(level)) difficulties.add(level);
      updateFilters();
    }, `${level} 星`);
    node.dataset.stars = level;
    node.setAttribute("aria-pressed", "true");
    $("#difficulty").append(node);
  }
  for (const name of categoryNames) {
    const node = button(name, "chip", () => {
      if (!categories.delete(name)) categories.add(name);
      updateFilters();
    });
    node.dataset.category = name;
    $("#categories").append(node);
  }
}

function renderRow(kind) {
  const { input, list, entries, defaults } = rows.get(kind);
  const normalized = text => text.normalize("NFKC").toLowerCase();
  const query = normalized(input.value.trim());
  const matching = query ? entries.filter(({ name, terms }) =>
    [name, ...(terms || [])].some(term => normalized(term).includes(query))) : defaults;
  list.replaceChildren();
  if (!matching.length) {
    list.append(element("span", "secondary", "没有匹配的标签"));
    return;
  }
  let limit = 24;
  const appendPage = start => {
    for (const entry of matching.slice(start, limit)) {
      const chip = button(entry.name, ["chip", kind === "ingredient" ? "" : "unavailable", entry.prep_id ? "prep" : ""].join(" "),
        async () => {
          if (entry.prep_id) {
            if (!menu.has(entry.prep_id)) {
              addRecipe({ id: entry.prep_id, name: entry.name, category: "配料" });
            }
            return;
          }
          if (!choices[kind].delete(entry.name)) choices[kind].add(entry.name);
          updateFilters();
        }, entry.name);
      chip.dataset.name = entry.name;
      if (entry.prep_id) {
        chip.dataset.prep = entry.prep_id;
        chip.title = "将自制配料加入菜单";
      }
      chip.setAttribute("aria-pressed", String(entry.prep_id ? menu.has(entry.prep_id) : choices[kind].has(entry.name)));
      list.append(chip);
    }
    if (limit < matching.length) {
      const more = button("更多标签", "subtle", () => {
        more.remove();
        const previous = limit;
        limit += 24;
        appendPage(previous);
      });
      list.append(more);
    }
  };
  appendPage(0);
}

function updateButtons() {
  for (const [kind, { list }] of rows) {
    for (const chip of list.querySelectorAll("[data-name]")) {
      chip.setAttribute("aria-pressed", String(chip.dataset.prep ? menu.has(chip.dataset.prep) : choices[kind].has(chip.dataset.name)));
    }
  }
  for (const toggle of $("#difficulty").children) toggle.setAttribute("aria-pressed", String(difficulties.has(Number(toggle.dataset.stars))));
  for (const toggle of $("#categories").children) toggle.setAttribute("aria-pressed", String(categories.has(toggle.dataset.category)));
}

function updateFilters() {
  saveKitchen();
  renderSelected();
  updateButtons();
  refreshResults();
  if (menu.size) refreshShopping();
}

function recipeDetailsButton(recipe) {
  return button("查看详情", "subtle recipe-details", event => {
    showDetails(recipe.id, event.detail > 0 ? event.currentTarget : null);
  }, `查看${recipe.name}详情`);
}

function recipeCard(recipe, excluded = null) {
  const { missing = [] } = recipe;
  const card = element("article", "recipe-card");
  const top = element("div", "card-top");
  const title = button(recipe.name, "card-title", () => showDetails(recipe.id));
  const added = menu.has(recipe.id);
  const add = button(added ? "✓" : "+", "add-card", () => addRecipe(recipe), `添加${recipe.name}到菜单`);
  add.dataset.recipe = recipe.id;
  add.disabled = added;
  const actions = element("div", "recipe-actions");
  actions.append(recipeDetailsButton(recipe), add);
  top.append(title, actions);
  const meta = element("p", "card-meta");
  meta.append(element("span", "", recipe.category), element("span", "", stars(recipe.difficulty)));
  if (missing.length) meta.append(element("span", "", `缺 ${missing.length} 项食材`));
  const preview = element("div", "card-preview");
  for (const kind of kinds) {
    const line = element("div", "preview-line");
    line.append(element("strong", "", labels[kind]));
    if (!recipe.labels[kind].length) line.append(element("span", "", "—"));
    for (const label of recipe.labels[kind]) {
      // 佐料/厨具在菜谱里常常是「备选」而非「必备」：一组里只要有一项没被标记缺就够用。
      // 这里把用户声明缺的那一项划掉，避免把「砂锅 / 深汤锅」读成「必须有砂锅」。
      const out = kind !== "ingredient" && Boolean(excluded?.[kind]?.has(label));
      const node = element("span", out ? "label-missing" : "", label);
      if (out) node.title = `你标记了没有${labels[kind]}「${label}」`;
      line.append(node);
    }
    preview.append(line);
  }
  if (missing.length) preview.append(element("p", "missing", `还缺 ${missing.join("、")}`));
  card.append(top, meta, preview);
  return card;
}

function renderRecipeList(target, recipes, limit = recipes.length, onMore, excluded = null) {
  const list = element("div", "result-list");
  list.append(...recipes.slice(0, limit).map(recipe => recipeCard(recipe, excluded)));
  target.append(list);
  if (recipes.length > limit) target.append(button("显示更多", "subtle more", onMore));
}

function renderResults() {
  const output = $("#results");
  output.replaceChildren();
  const status = $("#result-count");
  status.textContent = "";
  // 用户声明「缺」的佐料/厨具，用于在卡片里划掉对应备选项（见 recipeCard）
  const excluded = { seasoning: choices.seasoning, tool: choices.tool };
  if (recipeSearch.value.trim()) {
    status.textContent = `${nameMatches.length} 道菜谱`;
    if (!nameMatches.length) {
      output.append(element("p", "results-empty", "没有找到这个菜名，试试更短的关键词。"));
      return;
    }
    renderRecipeList(output, nameMatches, nameLimit, () => {
      nameLimit += 14;
      renderResults();
    }, excluded);
    return;
  }
  if (!difficulties.size) {
    output.append(element("p", "results-empty", "请选择至少一个难度。"));
    return;
  }
  if (!hasAvailableIngredients()) {
    if (choices.seasoning.size || choices.tool.size) {
      output.append(element("p", "recipe-hint secondary", "请至少选择一种你有的食材吧"));
    }
    if (recommendations.length) {
      renderRecipeList(output, recommendations, recommendations.length, undefined, excluded);
    } else {
      output.append(element("p", "results-empty", "没有符合当前条件的菜谱。"));
    }
    return;
  }
  const { ready, related } = resultData;
  status.textContent = `${ready.length} 道可做`;
  if (!ready.length && !related.length) {
    output.append(element("p", "results-empty", "没有符合当前条件的菜谱。"));
    return;
  }
  for (const [key, name] of [["ready", "食材已齐"], ["related", "还缺食材"]]) {
    const recipes = resultData[key];
    if (!recipes.length) continue;
    const group = element("section", `result-group ${key}`);
    group.append(element("h3", "", `${name} · ${recipes.length}`));
    renderRecipeList(group, recipes, resultLimits[key], () => {
      resultLimits[key] += 14;
      renderResults();
    }, excluded);
    output.append(group);
  }
}

async function refreshResults(rotate = false) {
  clearTimeout(recipeSearchTimer);
  searchController?.abort();
  if (!ready) return;
  const query = recipeSearch.value.trim();
  const recommend = !query && !hasAvailableIngredients();
  refreshButton.hidden = !recommend || !difficulties.size;
  refreshButton.disabled = true;
  if (!query && !difficulties.size) {
    renderResults();
    return;
  }
  const controller = new AbortController();
  searchController = controller;
  const status = $("#result-count");
  const output = $("#results");
  status.textContent = query ? "正在搜索…" : recommend ? "正在推荐…" : "正在匹配…";
  if (!rotate) output.replaceChildren();
  try {
    const filters = {
      difficulties: [...difficulties],
      categories: categories.size ? [...categories] : null,
    };
    let results;
    if (query) {
      results = await json(`/api/recipes?${new URLSearchParams({ q: query })}`, undefined, controller.signal);
    } else if (recommend) {
      results = await json("/api/recommendations", {
        ...filters,
        seasonings: [...choices.seasoning],
        tools: [...choices.tool],
        previous_ids: rotate ? recommendations.map(recipe => recipe.id) : [],
      }, controller.signal);
    } else {
      results = await json("/api/search", {
        ...pantry(),
        ...filters,
        preparation_ids: [...menu.values()].filter(recipe => recipe.category === "配料").map(recipe => recipe.id),
      }, controller.signal);
    }
    if (controller.signal.aborted) return;
    if (query) {
      nameMatches = results;
      nameLimit = 14;
    } else if (recommend) {
      recommendations = results;
    } else {
      resultData = results;
      resultLimits = { ready: 14, related: 14 };
    }
    renderResults();
  } catch (error) {
    if (!controller.signal.aborted && error.name !== "AbortError") {
      status.textContent = "";
      if (recommend && rotate && output.childElementCount) {
        notify("暂时无法刷新推荐，请重试。");
      } else {
        const message = recommend ? "暂时无法加载推荐，请点击「换一批」重试。" : "菜谱检索暂时不可用，请重试。";
        output.replaceChildren(element("p", "results-empty", message));
      }
    }
  } finally {
    if (!controller.signal.aborted) refreshButton.disabled = false;
  }
}

function emptyPlan(text, glyph) {
  const prompt = element("div", "plan-empty");
  if (glyph) prompt.append(icon(glyph));
  prompt.append(element("p", "", text));
  return prompt;
}

function renderMenu() {
  $("#nav-count").textContent = menu.size;
  $("#plan-count").textContent = `${menu.size} 道`;
  const basket = $("#basket");
  basket.replaceChildren();
  if (!menu.size) basket.append(emptyPlan("菜单里还没有菜谱。", "basket"));
  for (const recipe of menu.values()) {
    const row = element("div", "basket-entry");
    const name = element("span", "basket-label", recipe.name);
    if (recipe.category === "配料") name.append(element("small", "", "配料"));
    const actions = element("div", "recipe-actions");
    actions.append(recipeDetailsButton(recipe),
      button("×", "icon-button", () => removeRecipe(recipe), `移除${recipe.name}`));
    row.append(name, actions);
    basket.append(row);
  }
  for (const add of document.querySelectorAll(".add-card")) {
    add.disabled = menu.has(add.dataset.recipe);
    add.textContent = add.disabled ? "✓" : "+";
  }
  if (detail.open) updateDetailButton();
}

function addRecipe(recipe) {
  if (menu.has(recipe.id)) return;
  menu.set(recipe.id, recipe);
  saveKitchen();
  renderMenu();
  refreshShopping();
  if (recipe.category === "配料") {
    updateButtons();
    refreshResults();
  }
  notify(`已将「${recipe.name}」加入菜单`);
}

function removeRecipe(recipe) {
  menu.delete(recipe.id);
  saveKitchen();
  renderMenu();
  refreshShopping();
  if (recipe.category === "配料") {
    updateButtons();
    refreshResults();
  }
}

async function refreshShopping() {
  shoppingController?.abort();
  missingList = "";
  copyButton.disabled = true;
  $("#copy-fallback").hidden = true;
  const output = $("#shopping");
  if (!menu.size) {
    output.replaceChildren(emptyPlan("加入菜谱后汇总用料。"));
    return;
  }
  const controller = new AbortController();
  shoppingController = controller;
  try {
    const items = await json("/api/shopping", {
      ...pantry(), ids: [...menu.keys()], include_missing: true,
    }, controller.signal);
    if (controller.signal.aborted) return;
    const headings = { ingredient: "食材（未标记已有）", seasoning: "缺少的佐料", tool: "缺少的厨具" };
    const missingGroups = kinds.filter(kind => items.missing[kind].length).map(kind => [
      headings[kind],
      ...items.missing[kind].map(item => `- ${[item.name, shoppingQuantity(item)].filter(Boolean).join(" ")}`),
    ].join("\n"));
    missingList = missingGroups.length ? ["缺料清单", ...missingGroups].join("\n\n") : "";
    copyButton.disabled = !missingList;
    output.replaceChildren();
    for (const kind of kinds) {
      if (!items[kind].length) continue;
      const section = element("div", "shopping-group");
      const list = element("div", "shopping-items");
      for (const item of items[kind]) {
        const chip = element("span", "shopping-item", item.name);
        const amount = shoppingQuantity(item);
        if (amount) chip.append(element("small", "", amount));
        list.append(chip);
      }
      section.append(element("h4", "", labels[kind]), list);
      output.append(section);
    }
    if (!output.childElementCount) output.append(emptyPlan("原食谱未列出具体用料。"));
  } catch (error) {
    if (!controller.signal.aborted && error.name !== "AbortError") {
      output.replaceChildren(emptyPlan("用料清单暂时无法加载。"));
    }
  }
}

async function copyMissingList() {
  const text = missingList;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    $("#copy-fallback").hidden = true;
    notify("已复制缺料清单");
  } catch {
    if (text !== missingList) return;
    const field = $("#missing-text");
    field.value = text;
    $("#copy-fallback").hidden = false;
    field.focus();
    field.select();
  }
}

function updateDetailButton() {
  const add = $("#detail-add");
  add.disabled = menu.has(openedRecipe.id);
  add.textContent = add.disabled ? "已加入菜单" : "加入我的菜单";
}

function detailSection(name, texts, ordered = false) {
  const group = element("section", "detail-section");
  group.append(element("h3", "", name));
  if (texts.length) {
    const list = element(ordered ? "ol" : "ul");
    list.append(...texts.map(line => element("li", "", line)));
    group.append(list);
  }
  return group;
}

function materialQuantity(item) {
  if (item.quantity) return item.quantity.replaceAll("*", "×");
  if (item.grams !== null) return `${item.approximate ? "约 " : ""}${item.grams} 克`;
  return "";
}

function shoppingQuantity(item) {
  if (item.grams === null || item.approximate || item.quantity?.includes("份数")) {
    return materialQuantity(item);
  }
  return `${item.grams} 克`;
}

function openRecipe(recipe) {
  openedRecipe = recipe;
  detailCache.set(recipe.id, recipe);
  const content = $("#detail-content");
  const title = element("h2", "", recipe.name);
  title.id = "detail-title";
  const meta = element("div", "detail-meta");
  meta.append(element("span", "", recipe.category), element("span", "", `难度 ${stars(recipe.difficulty)}`));
  if (recipe.energy) meta.append(element("span", "", recipe.energy));
  content.replaceChildren(title, meta);
  if (recipe.description) content.append(element("p", "detail-description", recipe.description));
  const materialTexts = recipe.requirements.map(group => {
    const options = group.options.map(item => [item.name, materialQuantity(item)].filter(Boolean).join(" "));
    return options.join(" / ") + (group.optional ? "（可选）" : "");
  });
  const hasAmounts = recipe.requirements.some(group => group.options.some(item => materialQuantity(item)));
  const materials = detailSection("所需材料", hasAmounts ? materialTexts : recipe.materials_text);
  if (hasAmounts && recipe.materials_text.length) {
    const source = element("details");
    source.append(element("summary", "secondary", "查看原始材料说明"));
    const list = element("ul");
    list.append(...recipe.materials_text.map(line => element("li", "", line)));
    source.append(list);
    materials.append(source);
  }
  if (!recipe.materials_text.length && !materialTexts.length) materials.append(element("p", "secondary", "原食谱未列出具体用料。"));
  content.append(materials);
  if (!recipe.sections.length) {
    const method = detailSection("做法", []);
    method.append(element("p", "secondary", "原食谱未公布具体步骤。"));
    content.append(method);
  }
  for (const section of recipe.sections) content.append(detailSection(section.title, section.steps, true));
  updateDetailButton();
  if (!detail.open) detail.showModal();
  detail.scrollTop = 0;
}

async function showDetails(id, pointerTrigger) {
  try {
    const recipe = detailCache.get(id) || await json(`/api/recipe?${new URLSearchParams({ id })}`);
    const restoresPointerFocus = pointerTrigger && document.activeElement === pointerTrigger;
    openRecipe(recipe);
    if (restoresPointerFocus) {
      // Closing the dialog can restore focus to a mouse-activated button.
      pointerTrigger.classList.add("pointer-return");
      pointerTrigger.addEventListener("blur", () => pointerTrigger.classList.remove("pointer-return"), { once: true });
    }
  } catch {
    notify("无法加载这份菜谱，请重试。");
  }
}

async function pickRecipe() {
  random.disabled = true;
  random.querySelector("span").textContent = "正在抽取菜谱…";
  try {
    const recipe = await json("/api/random");
    await drawIngredients(recipe, () => openRecipe(recipe));
  } catch {
    if (!detail.open) notify("暂时无法随机抽取菜谱，请重试。");
  } finally {
    random.disabled = false;
    random.querySelector("span").textContent = "选择困难？我来替你选择！";
  }
}

$("#clear").addEventListener("click", () => {
  for (const kind of kinds) choices[kind].clear();
  categories.clear();
  for (let level = 1; level <= 5; level++) difficulties.add(level);
  updateFilters();
});
$(".dialog-close").addEventListener("click", () => detail.close());
detail.addEventListener("click", event => { if (event.target === detail) detail.close(); });
$("#detail-add").addEventListener("click", () => addRecipe(openedRecipe));
random.addEventListener("click", pickRecipe);
refreshButton.addEventListener("click", () => refreshResults(true));
copyButton.addEventListener("click", copyMissingList);
recipeSearch.addEventListener("input", () => {
  clearTimeout(recipeSearchTimer);
  if (!recipeSearch.value.trim()) {
    refreshResults();
    return;
  }
  searchController?.abort();
  refreshButton.hidden = true;
  $("#result-count").textContent = "正在搜索…";
  recipeSearchTimer = setTimeout(refreshResults, 160);
});

async function initialize() {
  renderSelected();
  renderMenu();
  refreshShopping();
  try {
    const catalog = await json("/api/catalog");
    restoreKitchen(catalog);
    buildFilters(catalog.facets, catalog.categories);
    floatIngredients(catalog.floating);
    ready = true;
    random.disabled = false;
    recipeSearch.disabled = false;
    renderSelected();
    updateButtons();
    renderMenu();
    if (menu.size) refreshShopping();
    refreshResults();
  } catch {
    $("#filters").replaceChildren(element("p", "results-empty", "无法载入食材标签，请刷新页面重试。"));
  }
}

initialize();

// 供自然语言面板复用同一套卡片渲染，避免两处各写一份列表样式
export { element, renderRecipeList };
