import csv
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path


RECIPE_DIR = Path(__file__).resolve().parents[1] / "recipe"
KINDS = ("ingredient", "seasoning", "tool")
MATERIAL_HEADINGS = {"必备原料和工具", "原料", "配料", "已知成分", "厨具", "家用厨具", "材料", "工具"}
OPTIONAL = re.compile(r"可选(?:项|配料|材料)?(?=[：:，,；;）)\s]|$)|可省略|可不放|可以不放|非必需|不加也|不放也")
PARENTHESES = re.compile(r"[（(]([^（）()]*)[）)]")
UNIT = r"(?:克|g|毫升|ml|千克|公斤|kg|斤|个|颗|瓣|勺|撮|节|片|根|段|袋|包|盒|块|只|条|杯|滴|小匙|大匙|茶匙|汤匙|枚|把|头|罐|瓶|升|L)"
AMOUNT = re.compile(rf"(?<![\d.])\d+(?:\.\d+)?(?:\s*(?:[-–—~～至/])\s*\d+(?:\.\d+)?)*\s*{UNIT}(?![a-z])", re.I)
MEASURE = re.compile(rf"{AMOUNT.pattern}|\d+(?:\.\d+)?\s*{UNIT}(?![a-z])|适量|少许|若干", re.I)
GRAM_VALUE = r"(?<![\d.\-~～–—至/])([0-9]+(?:\.[0-9]+)?)\s*(?:克|g)(?![a-z]|装|左右|\s*[-–—~～至/])"
GRAMS = re.compile(GRAM_VALUE, re.I)
STEP = re.compile(r"^(?:[-*+]\s+)?\d+[.、．)）]\s*|^[-*+]\s+")

# Identical names and preparation forms present in the source documents.
ALIASES = {
    "土豆片": "土豆", "土豆块": "土豆", "肥牛卷": "肥牛", "纯牛奶": "牛奶",
    "姜": "生姜", "姜片": "生姜", "姜末": "生姜", "姜丝": "生姜",
    "蒜": "大蒜", "蒜子": "大蒜", "蒜头": "大蒜", "蒜瓣": "大蒜", "蒜末": "大蒜",
    "葱段": "葱", "葱花": "葱", "葱末": "葱", "盐巴": "盐", "食盐": "盐",
    "白糖": "白砂糖", "食用猪油": "猪油", "鸡精粉调味料": "鸡精",
    "鲜红椒": "红椒", "清水": "水", "饮用水": "水", "红油豆瓣酱": "豆瓣酱",
    "蒸笼": "蒸屉", "鸡胸脯肉": "鸡胸肉", "去骨鸡腿肉": "鸡腿", "鸡腿肉": "鸡腿",
    "猪肉末": "猪肉馅", "干木耳": "木耳", "湿木耳": "木耳",
    "西红柿": "番茄", "马铃薯": "土豆", "牛腩肉": "牛腩", "香菇片": "香菇",
    "鸡汤料": "调味料（鸡汤专用）", "食用盐": "盐", "泡面": "方便面",
}
SEASONINGS = set("""
盐 糖 白砂糖 红糖 冰糖 黑糖 蜂蜜 味精 鸡精 麻辣鲜 海皇汁 十三香 八角 桂皮 香叶
孜然 小茴香 丁香 草果 草豆蔻 草寇 山奈 陈皮 白芷 香辛料 调味料 料酒 米酒 黄酒
啤酒 老抽 生抽 酱油 蒸鱼豉油 豉油 豆豉 鱼露 蚝油 醋 白醋 陈醋 香醋 米醋
黑胡椒 白胡椒 胡椒 花椒 藤椒 麻椒 咖喱块 咖喱粉 火锅底料 水 清水 泡打粉
小苏打 食用酒精 食用色素 豆瓣酱 蚝油 番茄膏 芝麻 芝麻粉 生姜 大蒜 葱 大葱
小葱 红葱头 沙姜 仔姜 干辣椒 红干椒 干红椒 花雕酒 白葡萄酒 白酒 朗姆酒
冰块 薄荷叶 柠檬汁 芥末 豆瓣 红曲米 花椒粒 开水 温水 热水 凉水 冷水
泡小米辣 泡椒 泡姜 剁椒 橄榄油 黄油
""".split())
TOOL = re.compile(
    r"(锅(?:盖|铲|具)?|烤箱|烤盘|炸锅|微波炉|蒸屉|蒸锅|电饭煲|电饭锅|"
    r"计量秤|温度计|秤|量杯|量勺|计时器|漏勺|滤网|筛网|砧板|菜板|"
    r"刀|碗|盘|模具|锡纸|铝箔|油纸|保鲜膜|保鲜袋|手套|料理机|打蛋器|搅拌机|"
    r"破壁机|榨汁机|搅拌棒|雪克瓶|玻璃杯|容器|擀面杖|筷子|长夹|"
    r"沥油架|烤架|厨房纸|茶壶|烤具|工具|漏斗|刷子|杯|罐|托盘|台)$"
)
AVAILABILITY_STOP = {"水", "开水", "温水", "热水", "冷水", "凉水"}


@dataclass(frozen=True)
class Material:
    name: str
    kind: str
    grams: float | None = None
    quantity: str | None = None
    approximate: bool = False


@dataclass(frozen=True)
class Requirement:
    options: tuple[Material, ...]
    optional: bool = False


@dataclass
class Recipe:
    id: str
    name: str
    source: str
    category: str
    difficulty: int
    tags: tuple[str, ...]
    requirements: list[Requirement]
    materials_text: list[str]
    sections: list[dict]
    description: str
    energy: str
    variants: tuple[tuple[Requirement, ...], ...] = ()


def plain(text):
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("__", "").replace("`", "").strip()


def material_text(text, preparations):
    def preparation_name(match):
        return match[2] if match[2] in preparations else match[1]

    text = re.sub(r"\[([^\]]+)\]\([^\s]*?/配料/([^\n]+?)\.md\)", preparation_name, text)
    return plain(text)


def canonical(name):
    return ALIASES.get(name.strip(), name.strip())


def without_notes(text):
    while (cleaned := PARENTHESES.sub("", text)) != text:
        text = cleaned
    return text


def sections_of(markdown):
    sections = [("", [])]
    for line in markdown.splitlines():
        if match := re.match(r"^##\s+(.+?)\s*:?\s*$", line):
            sections.append((match[1].rstrip(":："), []))
        else:
            sections[-1][1].append(line)
    return sections


def kind_of(name, preparations, tool_section=False):
    if name in preparations:
        return "ingredient"
    if tool_section or TOOL.search(name):
        return "tool"
    if name in SEASONINGS or name.endswith(("油", "酱", "盐", "汁", "糖浆", "高汤", "醋", "椒粉", "调味粉")):
        return "seasoning"
    return "ingredient"


def split_outside(text, separator):
    depth = 0
    result = []
    start = 0
    for index, char in enumerate(text):
        if char in "（(「【":
            depth += 1
        elif char in "）)」】":
            depth = max(0, depth - 1)
        elif depth == 0 and char in separator:
            if char == "," and index > 0 and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit():
                continue
            result.append(text[start:index].strip())
            start = index + 1
    return [part for part in [*result, text[start:].strip()] if part]


def clean_name(text, vocabulary):
    text = AMOUNT.sub("", text)
    text = without_notes(text)
    text = re.sub(r"^(?:约|适量|少许|若干|一些)\s*", "", text.strip())
    text = re.sub(r"[：:=＝].*$", "", text)
    text = re.sub(r"\s*(?:适量|少许|若干|各适量|等|备用|切丝|切段|切块|切片|切丁|切末|去皮)\s*$", "", text)
    text = text.strip(" \t.。；;：:，,-—")
    if text in vocabulary or text in ALIASES:
        return canonical(text)
    if match := re.match(r"^(.+?)\s+(?:约|大约|适量|少许|根据|按需|\d|切|推荐|用于)", text):
        return canonical(match[1])
    if " " in text and not re.search(r"[a-zA-Z]", text):
        text = text.split()[0]
    return canonical(text)


def grams_for(text):
    text = without_notes(text)
    if re.search(r"\d\s*[-~～–—至/]\s*\d", text):
        return None
    value = GRAMS.search(text)
    return float(value[1]) if value else None


def requirement_parts(fragment, vocabulary, preparations, tools):
    optional = bool(OPTIONAL.search(fragment))
    for name in sorted(preparations, key=len, reverse=True):
        if fragment == name or fragment.startswith((name + "（", name + "(", name + " ")):
            return Requirement((Material(name, "ingredient", grams_for(fragment)),), optional)
    notes = [match[1] for match in PARENTHESES.finditer(fragment)]
    primary = without_notes(fragment)
    if primary in preparations:
        return Requirement((Material(primary, "ingredient"),), optional)
    primary = re.sub(r"\s*[—–]+\s*(?:可|也|或).*$", "", primary)
    options = re.split(r"\s*(?:或者|或是|或|／|(?<!\d)/(?!\d))\s*", primary)
    for note in notes:
        if re.search(r"^(?:比如|例如|如|可选择)", note):
            examples = re.sub(r"^(?:比如|例如|如|可选择)\s*", "", note)
            options.extend(re.split(r"[、/／，,]|或", examples))
        elif match := re.match(r"(?:也可(?:用|以用)?|可以用|可用|可换成|可选|或)\s*(.+?)(?:替代|代替|替换|[。，，]|$)", note):
            options.extend(re.split(r"[、/／]|或", match[1]))
    if match := re.search(r"[—–]+\s*可(?:以)?用(.+?)(?:替代|代替|$)", fragment):
        options.append(match[1])

    items = {}
    for option in options:
        name = clean_name(option, vocabulary)
        if not name or name in {"…", "……", "...", "/", "等", "适量"}:
            continue
        if name not in vocabulary and (len(name) > 14 or re.search(r"[。！？]|^(?:注意|请|如果|可以|建议|根据|按照|尽量|步骤|配料|者)", name)):
            continue
        items.setdefault(name, Material(name, kind_of(name, preparations, tools), grams_for(option)))
    return Requirement(tuple(items.values()), optional)


def material_lines(sections, preparations):
    for title, lines in sections:
        if title not in MATERIAL_HEADINGS:
            continue
        tools = title in {"厨具", "家用厨具", "工具"}
        optional = False
        for line in lines:
            stripped = material_text(line, preparations)
            if not stripped or stripped.startswith(">"):
                continue
            label = stripped.strip("# ：:")
            if label in {"原料", "食材", "主料", "配料", "调料", "佐料", "工具", "厨具", "厨房用具", "可选", "可选原料", "可选配料"}:
                tools = label in {"工具", "厨具", "厨房用具"}
                optional = label.startswith("可选")
                continue
            if STEP.match(stripped):
                yield STEP.sub("", stripped), tools, optional
            elif title in {"厨具", "家用厨具", "配料", "原料", "已知成分"} and len(stripped) < 85:
                if not re.search(r"官方未|详细成分|原稿|未公开|^注意|^可以|^建议", stripped):
                    yield stripped, tools, optional


def explicit_amounts(sections, vocabulary):
    amounts = defaultdict(set)
    for title, lines in sections:
        if title != "计算":
            continue
        for line in lines:
            line = plain(line)
            if not STEP.match(line):
                continue
            for piece in split_outside(STEP.sub("", line), "、"):
                name, value = split_amount(piece, vocabulary)
                if name and value:
                    amounts[name].add(value)
    return {name: next(iter(values)) for name, values in amounts.items() if len(values) == 1}


def split_amount(text, vocabulary):
    if match := re.match(r"^(.+?)\s*[:：=＝]\s*(.+)$", text):
        name = clean_name(match[1], vocabulary)
        return name, match[2] if MEASURE.search(match[2]) else None
    if not (measure := MEASURE.search(text)):
        return "", None
    if measure.start() == 0:
        name = clean_name(text[measure.end():], vocabulary)
        return name, measure[0]
    prefix = text[:measure.start()].rstrip()
    # A weight inside a note can describe an equivalent amount, not its ingredient name.
    if prefix.endswith(("（", "(")):
        return "", None
    name = clean_name(prefix, vocabulary)
    quantity = text[len(prefix):].strip()
    return name, quantity


def add_amount(item, quantity, method, use_step_weight):
    if item.kind == "tool":
        return item
    if quantity:
        direct = without_notes(quantity)
        measure = AMOUNT.search(direct)
        grams = grams_for(measure[0]) if measure else None
        if re.search(r"[×*]\s*(?!\s|份数)\S|[÷=]", direct):
            grams = None
        approximate = grams is not None and bool(re.search(r"约|左右", direct))
        if grams is None and (match := re.search(r"[（(]\s*(?:大约|约)\s*(\d+(?:\.\d+)?)\s*(?:g|克)\s*[）)]", quantity, re.I)):
            grams, approximate = float(match[1]), True
        return replace(item, grams=grams, quantity=quantity, approximate=approximate)
    if item.grams is None and use_step_weight:
        return replace(item, grams=step_weight(method, item.name))
    return item


def method_sections(sections):
    result = []
    for title, lines in sections:
        if title not in {"操作", "步骤", "现磨版", "冲调版"}:
            continue
        current = {"title": title, "steps": []}
        in_method = title in {"操作", "步骤"}
        for line in lines:
            line = plain(line)
            if not line or line == "---":
                continue
            if line.startswith("###"):
                heading = line.lstrip("# ").rstrip("：:")
                if title in {"现磨版", "冲调版"}:
                    in_method = heading in {"操作", "步骤"}
                    continue
                if current["steps"]:
                    result.append(current)
                current = {"title": heading, "steps": []}
            elif in_method:
                current["steps"].append(STEP.sub("", line).lstrip("> "))
        if current["steps"]:
            result.append(current)
    return result


def step_weight(sections, name):
    terms = [name, *(alias for alias, target in ALIASES.items() if target == name)]
    names = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    pattern = re.compile(rf"{GRAM_VALUE}\s*(?:的)?(?:{names})(?![汁酱粉泥糊馅])", re.I)
    amounts = set()
    for section in sections:
        for line in section["steps"]:
            for match in pattern.finditer(line):
                before = line[:match.start()].rstrip()
                if re.search(r"\d\s*(?:[-–—~～/至]|到)$|(?:约|大约|剩余|另加)$", before):
                    continue
                amounts.add(float(match[1]))
    return next(iter(amounts)) if len(amounts) == 1 else None


def requires_oven_in_steps(method, sections):
    steps = [step for section in method for step in [section["title"], *section["steps"]]]
    notes = [plain(line) for title, lines in sections if title == "附加内容" for line in lines]
    alternative = (
        r"(?:没有|不用|无需|不需要)烤箱|方法[一二三四].*烤箱|烤箱.{0,20}可用.{0,12}替代|"
        r"烤箱\s*(?:[、/／]|或(?:者)?)\s*(?:明火|微波炉|空气炸锅|平底锅|电饭[煲锅])"
    )
    if any(re.search(alternative, line) for line in steps + notes):
        return False
    return any(re.search(r"烤箱\s*(?:预热|温度|\d+\s*[°℃])|预热[^。；，]{0,24}烤箱", line) for line in steps)


def build_recipe(row, path, vocabulary, preparations):
    name, source, category, tag_text, difficulty = row
    tags = tuple(dict.fromkeys(tag.strip() for tag in tag_text.split("、") if tag.strip()))
    sections = sections_of(path.read_text(encoding="utf-8-sig"))
    amounts = explicit_amounts(sections, vocabulary)
    method = method_sections(sections)
    requirements = {}
    notes = []
    for line, tools, optional in material_lines(sections, preparations):
        notes.append(line)
        fragments = split_outside(line, "、，,；;")
        for fragment in fragments:
            group = requirement_parts(fragment, vocabulary, preparations, tools)
            inline_name, inline_amount = split_amount(fragment, vocabulary)
            options = tuple(
                add_amount(item, amounts.get(item.name) or (
                    inline_amount if len(group.options) == 1 and inline_name == item.name else None
                ), method, category != "配料")
                for item in group.options if item.name != name or category != "配料"
            )
            if options:
                key = frozenset(item.name for item in options)
                group = Requirement(options, optional or group.optional)
                if key not in requirements or requirements[key].optional and not group.optional:
                    requirements[key] = group
    # Some oven recipes list the appliance only in their operating instructions.
    if "烤箱" in tags and not any("烤箱" in names for names in requirements) and requires_oven_in_steps(method, sections):
        requirements[frozenset({"烤箱"})] = Requirement((Material("烤箱", "tool"),))
        notes.append("烤箱（操作步骤所需）")
    header = [plain(line) for line in sections[0][1] if plain(line) and not line.startswith("#")]
    description = next((line for line in header if not re.match(r"(?:种类|预估|来源|品类)\s*[：:]|^---$", line)), "")
    energy = next((line for line in header if line.startswith("预估卡路里")), "")
    if not energy:
        energy = next((plain(line) for title, lines in sections if "成品热量" in title for line in lines if plain(line)), "")
    variants = ()
    if name == "原味豆浆":
        by_method = []
        for title, lines in sections:
            if title not in {"现磨版", "冲调版"}:
                continue
            nested = sections_of("\n".join(line[1:] if line.startswith("### ") else line for line in lines))
            ingredients = []
            method_steps = [section for section in method if section["title"] == title]
            for line, _, optional in material_lines(nested, preparations):
                notes.append(f"{title} · {line}")
                for fragment in split_outside(line, "、，,"):
                    group = requirement_parts(fragment, vocabulary, preparations, False)
                    items = tuple(Material(item.name, item.kind, step_weight(method_steps, item.name)) for item in group.options)
                    if items:
                        ingredients.append(Requirement(items, optional or group.optional))
            if title == "现磨版":
                ingredients.extend(requirements.values())
            by_method.append(tuple(ingredients))
        variants = tuple(by_method)
        requirements.clear()
    elif name in {"包子", "饭团"}:
        # These Markdown files list ready-made options before their cooking steps.
        listed_options = next((lines for title, lines in sections if title == "品类"), sections[0][1])
        choices = []
        for line in listed_options:
            stripped = plain(line)
            if not STEP.match(stripped) or stripped.startswith("- _"):
                continue
            stripped = STEP.sub("", stripped)
            notes.append(stripped)
            item = clean_name(stripped, vocabulary)
            if item:
                choices.append(Material(item, "ingredient"))
        if choices:
            requirements[frozenset(item.name for item in choices)] = Requirement(tuple(choices))
    return Recipe(f"{category}/{name}", name, source, category, int(difficulty), tags, list(requirements.values()),
                  notes, method, description, energy, variants)


def read_rules(path):
    rules = defaultdict(set)
    active = False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            if active:
                break
            active = line == "[单向规则]"
        elif active and line and not line.startswith("#"):
            specific, general = (part.strip() for part in line.split("->", 1))
            rules[specific].add(general)
    return dict(rules)


def expand(tags, rules):
    covered = set(tags)
    pending = list(covered)
    while pending:
        next_tags = rules.get(pending.pop(), set()) - covered
        covered.update(next_tags)
        pending.extend(next_tags)
    return covered


def load_catalog(directory=RECIPE_DIR):
    with (directory / "食谱名称大全.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))[1:]
    preparations = {path.stem for path in (directory / "配料").glob("*.md")}
    rules = read_rules(directory / "原料标签单向匹配规则.txt")
    vocabulary = {
        label.strip() for row in rows for label in row[3].split("、") if label.strip()
    } | set(rules) | set().union(*rules.values()) | preparations
    recipes = {}
    categories = {row[2] for row in rows}
    files = {(category, path.stem): path for category in categories for path in (directory / category).glob("*.md")}
    for row in rows:
        name, _, category, *_ = row
        path = files.get((category, name)) or files[(category, name.replace("/", "／"))]
        recipe = build_recipe(row, path, vocabulary, preparations)
        recipes[recipe.id] = recipe
    return recipes, rules, vocabulary
