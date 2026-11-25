"""阶段三：自然语言 → 结构化参数 → 现有 /api/search。

本模块只做两件事，刻意保持「薄」：

1. 把本体（概念层 + 受控词表）渲染成提示词里的**取值空间**，让模型在闭集内选择；
2. 把模型返回的参数**按本体校验和归一**（别名 → 规范名、种类对齐、约束检查），
   再交给 `Planner.search`。

检索本身一行没改：仍是规则 + `broader` 扩展。本体在这里的第三个作用是
`Planner.search` 内部的 `expand()`，它决定「有葱」能否覆盖「要小葱」。
"""

from __future__ import annotations

import re
import json
import hashlib
from copy import deepcopy
from collections import Counter
from pathlib import Path

from .llm_client import extract_json
from .recipe_data import canonical, strip_modifier

PROMPT_DIR = Path(__file__).resolve().parent.parent / "stage3" / "prompts"
KINDS = ("ingredient", "seasoning", "tool")

# 词表净化：把「看起来不像可购买资源」的名称挡在提示词与校验之外。
# 阶段二修掉 56 条明显误抽后复查为 0，但数量短语、半截句子仍有残留
# （一个容量在 / 不加水融化会很慢 / 2cm 两段葱段），这些会直接污染提示词。
BAD_CHARS = re.compile(r"[0-9\s、，,。；;：:（）()\"'“”/]")
SENTENCE_WORDS = re.compile(r"的|在|会|很|太|尽量|需要|若|请|把|并且|因为|所以|但是|然后|或者|即可|可以|不要|不能|够|挺")
NUMERAL_PREFIX = re.compile(r"^[一二两三四五六七八九十几半][个片段把根块勺碗袋张只条粒颗瓣杯撮]")


def looks_like_resource(name: str) -> bool:
    """判断一个名称是否像「可以买到的原料/厨具」，用于过滤抽取残留。"""
    return not (BAD_CHARS.search(name) or SENTENCE_WORDS.search(name)
                or NUMERAL_PREFIX.match(name) or not name or len(name) > 10)
FIELDS = {"ingredient": "ingredients", "seasoning": "seasonings", "tool": "tools"}
DEFAULTS = {
    "mode": "search", "ingredients": [], "seasonings": [], "tools": [],
    "difficulties": [1, 2, 3, 4, 5], "categories": None, "preparation_ids": [],
    "name_query": "", "unsupported_dimensions": [], "notes": "",
}


# ---------------------------------------------------------------- 本体 → 提示词

def ontology_view(planner) -> dict:
    """把本体投影成提示词可用的闭集。这是本体进入模型调用的唯一通道。

    提示词里的词表做了**净化**：只保留 CSV 标签、出现 ≥2 次、或出现在上位规则两端的名称，
    并剔掉含数字/空格/顿号的抽取噪声。原因见 `stage3/README.md` §7.5——
    阶段二遗留的 1042 个未归一名称里混着「一个容量在」「不加水融化会很慢」这类句子，
    原样塞进提示词等于教模型说胡话。

    校验用的 `accepted` 仍是**全量**名称集合：提示词只给常用规范名，
    但模型若输出一个罕见但真实存在的原料（青蟹、鳝丝），不应被判为错误。
    """
    counts = Counter()
    kind_of_name = {}
    for recipe in planner.recipes.values():
        groups = [*recipe.requirements, *(g for variant in recipe.variants for g in variant)]
        for group in groups:
            for option in group.options:
                counts[option.name] += 1
                kind_of_name[option.name] = option.kind
    tagged = {canonical(tag) for recipe in planner.recipes.values() for tag in recipe.tags}
    rule_terms = set(planner.rules) | {name for values in planner.rules.values() for name in values}

    prompt_names = {kind: set() for kind in KINDS}
    accepted = {kind: set() for kind in KINDS}
    for name, kind in kind_of_name.items():
        if not looks_like_resource(name):
            continue
        accepted[kind].add(name)
        if name in tagged or counts[name] >= 2 or name in rule_terms:
            prompt_names[kind].add(name)
    for kind in KINDS:
        accepted[kind] |= {entry["name"] for entry in planner.facets[kind]
                           if looks_like_resource(entry["name"])}

    ontology_path = PROMPT_DIR.parent.parent / "ontology" / "ontology.json"
    ontology_bytes = ontology_path.read_bytes()
    schema = json.loads(ontology_bytes)
    return {
        "schema": {key: schema[key] for key in ("classes", "object_properties", "constraints")},
        "ontology_version": schema["meta"]["version"],
        "ontology_sha256": hashlib.sha256(ontology_bytes).hexdigest(),
        "categories": sorted({recipe.category for recipe in planner.dishes}),
        "difficulties": [1, 2, 3, 4, 5],
        "ingredient": sorted(prompt_names["ingredient"]),
        "seasoning": sorted(prompt_names["seasoning"]),
        "tool": sorted(prompt_names["tool"]),
        "accepted": {kind: sorted(accepted[kind]) for kind in KINDS},
        "preparation": [{"id": recipe_id, "name": name}
                        for name, recipe_id in sorted(planner.preparations.items())],
    }


def render_ontology(view: dict) -> str:
    lines = [
        f"【食材】{len(view['ingredient'])} 个常用规范名（不在此列的原料可原样输出，不要改写）：",
        "|".join(view["ingredient"]),
        "",
        f"【佐料】{len(view['seasoning'])} 个：",
        "|".join(view["seasoning"]),
        "",
        f"【厨具】{len(view['tool'])} 个：",
        "|".join(view["tool"]),
        "",
        f"【菜品分类】{len(view['categories'])} 个：",
        "|".join(view["categories"]),
        "",
        f"【难度】{'|'.join(str(level) for level in view['difficulties'])}",
        "",
        f"【半成品】{len(view['preparation'])} 个（填 preparation_ids 时用 id）：",
        "|".join(f"{item['name']}({item['id']})" for item in view["preparation"]),
    ]
    lines += ["", "【概念、关系与约束（来自 ontology/ontology.json）】",
              json.dumps(view["schema"], ensure_ascii=False)]
    return "\n".join(lines)


def parser_prompt(view: dict) -> str:
    template = (PROMPT_DIR / "parser_system.md").read_text(encoding="utf-8")
    return template.replace("{{ONTOLOGY}}", render_ontology(view))


def baseline_prompt(planner=None) -> str:
    """对照组 A：不给任何菜名清单，让模型凭常识直接报菜名。

    早期版本把 672 个菜名塞进提示词，结果这个模型在「汤」「凉拌」这类需要
    枚举大量候选的任务上推理链失控，20 次里有 2 次直接超时或返回空。
    改成自由作答后，落不到目录上的名字正好就是幻觉率，指标更直接。
    """
    return (PROMPT_DIR / "baseline_direct.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 参数解析

def parse_params(text: str) -> dict:
    """把模型输出规整成固定字段，缺字段补默认值。类型错误抛 ValueError。"""
    raw = extract_json(text)
    if not isinstance(raw, dict):
        raise ValueError("顶层不是 JSON 对象")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"未知字段：{sorted(unknown)}")
    params = deepcopy(DEFAULTS)
    params.update(raw)
    for key in ("ingredients", "seasonings", "tools", "preparation_ids", "unsupported_dimensions"):
        value = params[key]
        if not isinstance(value, list) or len(value) > 1000 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 100 for item in value):
            raise ValueError(f"{key} 必须是非空字符串数组，最多 1000 项")
        params[key] = list(dict.fromkeys(item.strip() for item in value))
    levels = params["difficulties"]
    if not isinstance(levels, list) or not levels or len(levels) > 5 or any(
            type(level) is not int or not 1 <= level <= 5 for level in levels):
        raise ValueError("difficulties 必须是 1–5 整数非空数组")
    categories = params["categories"]
    if categories is not None and (not isinstance(categories, list) or any(
            not isinstance(item, str) or not item.strip() for item in categories)):
        raise ValueError("categories 必须是字符串数组或 null")
    if params["mode"] not in ("search", "recommend", "name_search"):
        raise ValueError("非法 mode")
    for key in ("name_query", "notes"):
        if not isinstance(params[key], str):
            raise ValueError(f"{key} 必须是字符串")

    return params


def _known_sets(view: dict) -> dict:
    """校验接受全量名称；提示词只给常用规范名（见 ontology_view 的说明）。"""
    return {kind: set(view["accepted"][kind]) for kind in KINDS}


def normalize(params: dict, view: dict) -> tuple[dict, dict]:
    """按本体校验并归一。返回 (可检索参数, 校验报告)。

    报告里保留每一次改动，用于回答「本体到底起了什么作用」。
    """
    known = _known_sets(view)
    categories = set(view["categories"])
    preparations = {item["id"] for item in view["preparation"]}
    report = {
        "aliases": {},          # 口语名 → 规范名
        "unmapped": {kind: [] for kind in KINDS},   # 词表外名称
        "kind_mismatch": [],    # 放错种类（如把佐料写进 ingredients）
        "dropped": [],          # 被丢弃的非法值
        "violations": [],       # 约束违反
    }
    clean = {key: (list(value) if isinstance(value, list) else value)
             for key, value in params.items()}

    seen = {kind: [] for kind in KINDS}
    for kind in KINDS:
        for raw_name in params[FIELDS[kind]]:
            name = canonical(raw_name)
            if name != raw_name:
                report["aliases"][raw_name] = name
            if name not in known[kind]:
                stripped = canonical(strip_modifier(name))
                if stripped in known[kind] and stripped != name:
                    report["aliases"][name] = stripped
                    name = stripped
            if name in known[kind]:
                if name not in seen[kind]:
                    seen[kind].append(name)
                continue
            other = [k for k in KINDS if k != kind and name in known[k]]
            if other:
                # 本体知道这个词，但种类不对。系统没有「我有佐料」这种表达，
                # 所以只能丢弃并记录，不能强行搬到 seasonings（那表示「没有」）。
                report["kind_mismatch"].append({"name": name, "expected": other[0], "got": kind})
                report["dropped"].append(f"{kind}:{raw_name}")
                continue
            report["unmapped"][kind].append(name)
            report["dropped"].append(f"{kind}:{raw_name}")

    clean["ingredients"], clean["seasonings"], clean["tools"] = (
        seen["ingredient"], seen["seasoning"], seen["tool"])

    levels = sorted({level for level in params["difficulties"] if 1 <= level <= 5})
    if not levels:
        levels = [1, 2, 3, 4, 5]
        report["violations"].append("difficulties 越界或为空，回退为 1-5")
    if levels != sorted(params["difficulties"]):
        report["violations"].append(f"difficulties 由 {params['difficulties']} 修正为 {levels}")
    clean["difficulties"] = levels

    if params["categories"] is not None:
        kept = [name for name in params["categories"] if name in categories]
        for name in params["categories"]:
            if name not in categories:
                report["violations"].append(f"categories 中的「{name}」不在 14 个分类内，已丢弃")
                report["dropped"].append(f"category:{name}")
        clean["categories"] = kept
    else:
        clean["categories"] = None

    clean["preparation_ids"] = [item for item in params["preparation_ids"] if item in preparations]
    for item in params["preparation_ids"]:
        if item not in preparations:
            report["dropped"].append(f"preparation:{item}")

    if set(clean["ingredients"]) & set(clean["seasonings"]):
        overlap = set(clean["ingredients"]) & set(clean["seasonings"])
        report["violations"].append(f"同一名称同时出现在「有」和「没有」：{'、'.join(sorted(overlap))}")
        clean["seasonings"] = [name for name in clean["seasonings"] if name not in overlap]

    for kind in KINDS:
        for name in clean[FIELDS[kind]]:
            if len(name) > 12:
                report["violations"].append(f"{kind} 中的「{name[:12]}…」超长，疑似句子")
    return clean, report


def passthrough(params: dict) -> dict:
    """对照组 B：不做任何归一与校验，模型给什么就查什么。"""
    return {key: (list(value) if isinstance(value, list) else value)
            for key, value in params.items()}


# ---------------------------------------------------------------- 调用检索

def search(planner, params: dict) -> dict:
    """把参数交给现有检索逻辑。mode 决定走哪个入口，与 main.py 的路由一致。"""
    mode = params["mode"]
    if mode == "name_search" and params["name_query"]:
        hits = planner.find_recipes(params["name_query"])
        return {"mode": mode, "items": [{"id": item["id"], "name": item["name"],
                                         "missing": []} for item in hits[:10]]}
    if mode == "recommend":
        items = planner.recommendations(
            params["difficulties"], [], categories=params["categories"],
            seasonings=params["seasonings"], tools=params["tools"])
        return {"mode": mode, "items": [{"id": item["id"], "name": item["name"],
                                         "missing": []} for item in items]}
    result = planner.search(
        [canonical(x) for x in params["ingredients"]],
        [canonical(x) for x in params["seasonings"]],
        [canonical(x) for x in params["tools"]],
        params["difficulties"], params["preparation_ids"], categories=params["categories"])
    ready = [{"id": item["id"], "name": item["name"], "missing": item["missing"]}
             for item in result["ready"]]
    related = [{"id": item["id"], "name": item["name"], "missing": item["missing"]}
               for item in result["related"]]
    return {"mode": mode, "items": ready[:10], "ready_total": len(ready),
            "related_total": len(related),
            "related": related[:5]}


def run(planner, view: dict, text: str, client, *, strict: bool = True) -> dict:
    """一次完整流程：提示词 → 模型 → 解析 → (归一) → 检索。"""
    system = parser_prompt(view)
    reply = client.chat(system, text)
    params = parse_params(reply["text"])
    if strict:
        clean, report = normalize(params, view)
    else:
        clean, report = passthrough(params), {}
    return {
        "system": system, "raw_response": reply["text"], "reply_meta": reply,
        "params_raw": params, "params": clean, "report": report,
        "result": search(planner, clean),
    }
