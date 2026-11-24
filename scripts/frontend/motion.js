const hero = document.querySelector("#hero");
const heroContent = hero.querySelector(".hero-content");
const floating = document.querySelector("#float-layer");
const drawLayer = document.querySelector("#draw-layer");
const connections = document.querySelector("#connections");
const threads = document.querySelector("#threads");
const flash = document.querySelector("#flash");
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

function titlePoint() {
  const box = hero.getBoundingClientRect();
  const title = document.querySelector("#headline").getBoundingClientRect();
  return {
    x: title.left + title.width / 2 - box.left,
    y: title.top + title.height / 2 - box.top,
    width: box.width,
    height: box.height,
  };
}

export function floatIngredients(labels) {
  const kinds = ["ingredient", "ingredient", "ingredient", "dish", "dish", "seasoning"]
    .filter(kind => labels[kind].length);
  if (!kinds.length) return;

  function spawn(kind, initial = false) {
    if (document.hidden || reduced.matches) return;
    const choices = labels[kind];
    if (!choices.length) return;
    const node = document.createElement("span");
    const { x, y, width, height } = titlePoint();
    const angle = Math.random() * 2 * Math.PI;
    const duration = 5000 + Math.random() * 3200;
    const edge = .73 + Math.random() * .3;
    node.className = "floating";
    node.dataset.kind = kind;
    node.textContent = choices[Math.floor(Math.random() * choices.length)];
    node.style.left = `${x}px`;
    node.style.top = `${y}px`;
    node.style.setProperty("--duration", `${duration}ms`);
    node.style.setProperty("--x", `${Math.cos(angle) * width * .57 * edge}px`);
    node.style.setProperty("--y", `${Math.sin(angle) * height * .76 * edge}px`);
    node.style.setProperty("--rotate", `${Math.random() * 24 - 12}deg`);
    if (initial) node.style.animationDelay = `-${duration * (.4 + Math.random() * .2)}ms`;
    node.addEventListener("animationend", () => node.remove(), { once: true });
    floating.append(node);
  }

  for (const kind of [...kinds, "ingredient", "ingredient", "dish"]) spawn(kind, true);
  function tick() {
    spawn(kinds[Math.floor(Math.random() * kinds.length)]);
    setTimeout(tick, 270 + Math.random() * 275);
  }
  tick();
}

export function shuffle(items) {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

function svgNode(name, className, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  if (className) node.setAttribute("class", className);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function orbitPoints(width, height, count) {
  const cx = width / 2;
  const cy = height / 2;
  const rx = Math.min(width * .38, width / 2 - 48, 480);
  const ry = height / 2 - 28;
  const capacity = width < 560 ? 12 : 21;
  const rings = Math.ceil(count / capacity);
  const offset = Math.random() * Math.PI * 2;
  const positions = [];
  for (let ring = 0; ring < rings; ring++) {
    const inRing = Math.ceil((count - positions.length) / (rings - ring));
    const scale = 1 - ring * .55 / rings;
    const ellipse = svgNode("ellipse", null, { cx, cy, rx: rx * scale, ry: ry * scale, visibility: "hidden" });
    connections.append(ellipse);
    // Evenly space labels by distance along the ellipse, including across its start.
    const length = ellipse.getTotalLength();
    for (let index = 0; index < inRing; index++) {
      const fraction = ((index + ring * .4) / inRing + offset / (2 * Math.PI)) % 1;
      positions.push(ellipse.getPointAtLength(length * fraction));
    }
    ellipse.remove();
  }
  // Vary the direction and order while favoring shorter links through the labels.
  const ordered = [positions.splice(Math.floor(Math.random() * positions.length), 1)[0]];
  while (positions.length) {
    const previous = ordered.at(-1);
    positions.sort((a, b) => Math.hypot(a.x - previous.x, a.y - previous.y) -
      Math.hypot(b.x - previous.x, b.y - previous.y));
    const choice = Math.floor(Math.random() ** 1.85 * Math.min(3, positions.length));
    ordered.push(positions.splice(choice, 1)[0]);
  }
  return ordered;
}

function centerOf(node, frame) {
  const box = node.getBoundingClientRect();
  return { x: box.left - frame.left + box.width / 2, y: box.top - frame.top + box.height / 2 };
}

function positionThread(link, frame) {
  const a = centerOf(link.from, frame);
  const b = centerOf(link.to, frame);
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  link.path.setAttribute("d", `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2 - dy * .12} ${(a.y + b.y) / 2 + dx * .12} ${b.x} ${b.y}`);
}

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const translate = (dx, dy) => `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;

function appearanceTimes(count) {
  // Alternate short bursts and longer pauses while capping the overall stagger.
  const gaps = Array.from({ length: count - 1 }, () => Math.random() < .55
    ? 55 + Math.random() * 75
    : 215 + Math.random() * 155);
  const total = gaps.reduce((sum, gap) => sum + gap, 0);
  const scale = total > 2050 ? 2050 / total : 1;
  let delay = 35 + Math.random() * 55;
  return [delay, ...gaps.map(gap => delay += gap * scale)];
}

export async function drawIngredients(recipe, revealRecipe) {
  const labels = shuffle(Object.entries(recipe.labels).flatMap(([kind, names]) => names.map(name => ({ kind, name }))));
  if (reduced.matches || !labels.length) {
    revealRecipe();
    return;
  }
  const { x, y, width, height } = titlePoint();
  const { left, top } = connections.getBoundingClientRect();
  const frame = { left, top };
  const links = [];
  let previous;
  let tracking;
  let titleFade;

  function followLabels() {
    for (const link of links) positionThread(link, frame);
    tracking = requestAnimationFrame(followLabels);
  }

  hero.classList.add("drawing");
  drawLayer.dataset.dense = String(width < 560 && labels.length > 10 || labels.length > 21);
  try {
    const positions = orbitPoints(width, height, labels.length);
    const delays = appearanceTimes(labels.length);
    const nodes = labels.map(({ kind, name }, index) => {
      const node = document.createElement("span");
      node.className = "draw-tag";
      node.dataset.kind = kind;
      node.textContent = name;
      node.style.left = `${x}px`;
      node.style.top = `${y}px`;
      drawLayer.append(node);
      const target = positions[index];
      const offset = node.offsetWidth / 2 + 6;
      const stop = translate(Math.min(width - offset, Math.max(offset, target.x)) - x, target.y - y);
      const pinned = node.animate([
        { opacity: 0, transform: "translate(-50%, -50%) scale(.55)" },
        { opacity: 1, transform: stop },
      ], { duration: 460, delay: delays[index], fill: "both", easing: "cubic-bezier(.18,.6,.25,1)" }).finished.then(() => {
        node.classList.add("pinned");
        if (previous) {
          const path = svgNode("path", "draw-thread", { pathLength: 1 });
          const link = { from: previous, to: node, path };
          threads.append(path);
          links.push(link);
          positionThread(link, frame);
          path.animate([{ strokeDasharray: "1", strokeDashoffset: "1" }, { strokeDasharray: "1", strokeDashoffset: "0" }],
            { duration: 290, easing: "ease-out", fill: "both" });
        }
        previous = node;
      });
      return { node, stop, pinned };
    });
    await Promise.all(nodes.map(({ pinned }) => pinned));
    await pause(260);
    followLabels();
    const gatherDuration = 1610;
    const gatherTiming = { duration: gatherDuration, fill: "forwards", easing: "cubic-bezier(.5,.05,.8,.62)" };
    titleFade = heroContent.animate([{ opacity: 1 }, { opacity: 0 }], gatherTiming);
    const converging = nodes.map(({ node, stop }) => node.animate([
      { transform: stop, opacity: 1 },
      { transform: translate(width / 2 - x, height / 2 - y) + " scale(.28)", opacity: .14 },
    ], gatherTiming).finished);
    threads.animate([{ opacity: 1, offset: .35 }, { opacity: 0 }], { duration: gatherDuration, fill: "both" });
    const whiteLight = flash.animate([{ opacity: 0 }, { opacity: .88, offset: .6 }, { opacity: 0 }],
      { delay: gatherDuration - 300, duration: 415 });
    await Promise.all([...converging, whiteLight.finished]);
  } finally {
    cancelAnimationFrame(tracking);
    try {
      revealRecipe();
    } finally {
      if (titleFade) {
        const opacity = getComputedStyle(heroContent).opacity;
        titleFade.cancel();
        heroContent.animate([{ opacity }, { opacity: 1 }], { duration: 1500, easing: "ease-out" });
      }
      threads.getAnimations().forEach(animation => animation.cancel());
      threads.replaceChildren();
      drawLayer.replaceChildren();
      hero.classList.remove("drawing");
    }
  }
}
