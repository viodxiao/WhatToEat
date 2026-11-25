"""阶段二：菜谱本体与实例的质量检查。

检查分两层：
1. 概念层：上位规则表与标签表的一致性（失效规则、双向规则、与同义表冲突）。
2. 实例层：抽取出的原料项是否是真名称、切配形态是否归一、用量是否可信、
   必需/可选是否与原文一致。

每条问题都带「位置 + 类型 + 依据（原文片段）+ 修正建议」，
依据片段取自菜谱 Markdown 的原料段落，可人工回溯。
判定函数 is_noise_name / strip_modifier 与抽取代码共用同一份，
保证「检查器认为有问题」和「修正后确实消失」是同一套标准。

用法：
    python -m scripts.quality_check check --tag before   # 修前扫描
    python -m scripts.quality_check check --tag after    # 修后复查
    python -m scripts.quality_check eval                 # 构造错误样例的对照评测
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

from .recipe_data import (
    ALIASES,
    canonical,
    is_noise_name,
    load_catalog,
    strip_modifier,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "stage2"

# 切配形态：拿到整料用刀即可处理，应归一（与同义词表「土豆片→土豆」一致）。
CUT = re.compile(r"(丝|段|片|块|丁|条)$")
# 加工品形态：需绞、磨、泡发等额外工序或本身是独立商品，按规则文件
# [匹配约定] 第 6 条独立匹配，不归一。
PROCESS = re.compile(r"(末|粒|馅|泥|蓉|沫|碎|粉|浆)$")
# 形似加工品但实为独立商品，人工核对后保留原名。
KEEP_SHAPE = {"吉利丁片", "明胶片", "吉利丁粉", "椰蓉"}

# 可选标记：后面紧跟「但/，/）」等才是「可省略」；「可选牛腩肉」是二选一，不是可省。
OPTIONAL_MARK = re.compile(r"可选(?=[但，,）)\]、；;\s]|$)|可省略|可不放|非必需")


def source_file(recipe_id: str) -> str:
    category, _, name = recipe_id.partition("/")
    return f"recipe/{category}/{name}.md"


def _clean_fragment(fragment: str) -> str:
    fragment = re.sub(r"[（(][^（）()]*[）)]", "", fragment)
    return re.sub(r"^[\s\-*+]+", "", fragment).strip(" ：:、，,")


def locate(recipe, name: str):
    """优先定位到「清洗后正好等于该名称」的那一段，避免 葱 命中 红葱油 这类子串误配。"""
    for line in recipe.materials_text:
        for fragment in re.split(r"[、，,；;]", line):
            if canonical(_clean_fragment(fragment)) == name:
                return line, fragment
    for line in recipe.materials_text:
        for fragment in re.split(r"[、，,；;]", line):
            if name and name in fragment:
                return line, fragment
    return "", ""


def issue(kind, level, recipe_id, group_index, name, evidence_line, suggestion, detail=""):
    return {
        "type": kind,
        "level": level,
        "recipe": recipe_id,
        "source_file": source_file(recipe_id),
        "group_index": group_index,
        "name": name,
        "evidence": evidence_line,
        "suggestion": suggestion,
        "detail": detail,
    }


def check_instances(recipes, rules, vocabulary):
    csv_labels = {canonical(tag) for recipe in recipes.values() for tag in recipe.tags}
    issues = []

    for recipe in recipes.values():
        seen_required = {}
        for gi, group in enumerate(recipe.requirements):
            for option in group.options:
                name = option.name
                line, fragment = locate(recipe, name)

                if is_noise_name(name, vocabulary):
                    issues.append(issue(
                        "E1 误抽", "错误", recipe.id, gi, name, line,
                        "从原料项中移除；若原文确有该原料，按人工核对的规范名重新录入",
                        "名称是句子/提示语/类目名，不是可购买的原料",
                    ))
                elif (CUT.search(name) and not PROCESS.search(name)
                      and name not in KEEP_SHAPE and name[:-1] in (vocabulary | csv_labels)):
                    issues.append(issue(
                        "E3 形态未归一", "建议", recipe.id, gi, name, line,
                        f"归一为「{name[:-1]}」（该词已在词表中）",
                        "名称是规范词 + 切配形态后缀，未走同义词表",
                    ))

                if not group.optional and name in seen_required:
                    issues.append(issue(
                        "E4 必需项重复", "建议", recipe.id, gi, name, line,
                        "合并为一条要求，避免同一原料被计两次",
                        f"同一菜谱已在第 {seen_required[name]} 组要求该原料",
                    ))
                elif not group.optional:
                    seen_required[name] = gi

                if option.grams is not None and (option.grams <= 0 or option.grams > 5000):
                    issues.append(issue(
                        "E5 用量异常", "错误", recipe.id, gi, name, line,
                        "回原文核对克数，疑似小数点或单位错误",
                        f"抽取到 {option.grams} 克",
                    ))

                if line and not group.optional and OPTIONAL_MARK.search(fragment):
                    issues.append(issue(
                        "E6 可选误判", "错误", recipe.id, gi, name, line,
                        "把该要求标为可选（optional=True）",
                        f"原文片段「{fragment}」标注可选，抽取结果却是必需项",
                    ))

    for left, rights in rules.items():
        if left not in csv_labels:
            issues.append(issue(
                "R1 规则失效", "错误", "(概念层)", None, left,
                "recipe/原料标签单向匹配规则.txt [单向规则]",
                "删除该规则，或把左项补进 CSV 标签表",
                "规则左项不在任何菜谱标签中，永远不会被触发",
            ))
        for right in rights:
            if left in rules.get(right, set()):
                issues.append(issue(
                    "R2 规则双向", "错误", "(概念层)", None, f"{left} <-> {right}",
                    "recipe/原料标签单向匹配规则.txt [单向规则]",
                    "保留语义正确的一条，删除另一条",
                    "上位关系是单向覆盖，出现双向会导致互相满足",
                ))
            if ALIASES.get(left) == right:
                issues.append(issue(
                    "R3 同义与上位混用", "错误", "(概念层)", None, f"{left} -> {right}",
                    "recipe/原料标签单向匹配规则.txt [单向规则]",
                    "改由同义词表表达，从规则表删除",
                    "两者是同一实体的不同叫法，不是上位关系",
                ))

    return issues, csv_labels


def summarize(issues, recipes):
    by_type = Counter(item["type"] for item in issues)
    dishes = [r for r in recipes.values() if r.category != "配料"]
    options = [o for r in dishes for g in r.requirements for o in g.options]
    info = {
        "菜品数": len(dishes),
        "原料项数": len(options),
        "无克数原料项": sum(1 for o in options if o.grams is None),
        "无热量菜品": sum(1 for r in dishes if not r.energy),
    }
    return by_type, info


def write_report(tag, issues, by_type, info, path):
    lines = [
        f"# 阶段二问题清单（{tag}）",
        "",
        "## 规模与信息不足统计",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
    ]
    for key, value in info.items():
        lines.append(f"| {key} | {value} |")
    lines += ["", "## 问题类型分布", "", "| 类型 | 条数 |", "|---|---|"]
    for kind, count in sorted(by_type.items()):
        lines.append(f"| {kind} | {count} |")
    lines.append(f"| **合计** | **{len(issues)}** |")

    lines += ["", f"## 明细（每类最多 15 条，全量见 issues_{tag}.json）", ""]
    for kind in sorted(by_type):
        rows = [item for item in issues if item["type"] == kind]
        lines += [f"### {kind}（{len(rows)} 条）", "",
                  "| # | 位置 | 对象 | 依据（原文） | 建议 |", "|---|---|---|---|---|"]
        for index, item in enumerate(rows[:15], 1):
            where = (item["recipe"] if item["group_index"] is None
                     else f"{item['recipe']} · 第{int(item['group_index']) + 1}组")
            evidence = item["evidence"][:40].replace("|", "/")
            lines.append(f"| {index} | {where} | {item['name']} | {evidence} | {item['suggestion']} |")
        if len(rows) > 15:
            lines.append(f"| … | 其余 {len(rows) - 15} 条 | | | |")
        lines.append("")

    lines += ["## 未列为问题的「信息不足」", "",
              "- 原文未给出克数的原料项不计为错误：按本体约束 C7，留空表示信息不足，不可推断为 0。",
              "- 无热量文本的菜品同理，仅作可用性提示，不作为缺陷修正。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_check(tag):
    recipes, rules, vocabulary = load_catalog()
    issues, _ = check_instances(recipes, rules, vocabulary)
    by_type, info = summarize(issues, recipes)
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"issues_{tag}.json").write_text(
        json.dumps({"tag": tag, "summary": dict(by_type), "scale": info, "issues": issues},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(tag, issues, by_type, info, OUT_DIR / f"问题清单_{tag}.md")
    print(f"[{tag}] 共 {len(issues)} 条问题：{dict(by_type)}")
    print(f"       规模：{info}")
    return issues


# --------------------------------------------------------------------------
# 构造错误样例，对照两种检查方法
# --------------------------------------------------------------------------

def build_synthetic(recipes, rules, vocabulary, size=50, seed=20261125):
    """取真实且干净的名称注入已知错误；同时保留等量正确样例用于测误报。"""
    rng = random.Random(seed)
    dishes = [r for r in recipes.values() if r.category != "配料"]
    clean = []
    for recipe in dishes:
        for gi, group in enumerate(recipe.requirements):
            for option in group.options:
                name = option.name
                if not is_noise_name(name, vocabulary) and strip_modifier(name) == name:
                    clean.append((recipe, gi, name))
    rng.shuffle(clean)
    clean = clean[: size * 2]

    injected = []
    for index, (recipe, gi, name) in enumerate(clean[:size]):
        mode = index % 4
        if mode == 0:
            broken, kind = name + "即可", "E1 误抽"
        elif mode == 1:
            broken, kind = "未过期的" + name, "E1 误抽"
        elif mode == 2:
            broken, kind = name + "丝", "E3 形态未归一"
        else:
            broken, kind = "喜欢的" + name, "E1 误抽"
        injected.append({"recipe": recipe.id, "group": gi, "text": broken,
                         "truth": "错误", "injected": kind})

    controls = [{"recipe": recipe.id, "group": gi, "text": name,
                 "truth": "正确", "injected": None}
                for recipe, gi, name in clean[size: size * 2]]
    return injected + controls


def method_length(sample, vocabulary, csv_labels=frozenset()):
    """基线方法：只看长度，超过 10 字即判为抽取错误（等同修正前的过滤条件）。"""
    return [len(item["text"]) > 10 for item in sample]


def method_rules(sample, vocabulary, csv_labels=frozenset()):
    """本组方法：噪声模式 + 修饰语剥离 + 切配形态与词表一致性。"""
    known = vocabulary | csv_labels
    labels = []
    for item in sample:
        name = item["text"]
        hit = is_noise_name(name, vocabulary) or strip_modifier(name) != name
        if not hit and CUT.search(name) and not PROCESS.search(name) and name not in KEEP_SHAPE:
            hit = name[:-1] in known
        labels.append(bool(hit))
    return labels


def score(sample, predicted):
    tp = sum(1 for item, pred in zip(sample, predicted) if item["truth"] == "错误" and pred)
    fp = sum(1 for item, pred in zip(sample, predicted) if item["truth"] == "正确" and pred)
    fn = sum(1 for item, pred in zip(sample, predicted) if item["truth"] == "错误" and not pred)
    tn = sum(1 for item, pred in zip(sample, predicted) if item["truth"] == "正确" and not pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def run_eval():
    recipes, rules, vocabulary = load_catalog()
    sample = build_synthetic(recipes, rules, vocabulary)
    csv_labels = {canonical(tag) for recipe in recipes.values() for tag in recipe.tags}
    base = score(sample, method_length(sample, vocabulary, csv_labels))
    ours = score(sample, method_rules(sample, vocabulary, csv_labels))
    OUT_DIR.mkdir(exist_ok=True)
    result = {"sample_size": len(sample),
              "errors": sum(1 for item in sample if item["truth"] == "错误"),
              "controls": sum(1 for item in sample if item["truth"] == "正确"),
              "method_length": base, "method_rules": ours}
    (OUT_DIR / "eval_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = ["菜谱,组,名称,人工判定,注入错误,长度法,本组方法"]
    rows += [f"{item['recipe']},{item['group']},{item['text']},{item['truth']},"
             f"{item['injected'] or ''},{p1},{p2}"
             for item, p1, p2 in zip(sample, method_length(sample, vocabulary, csv_labels),
                                     method_rules(sample, vocabulary, csv_labels))]
    (OUT_DIR / "eval_samples.csv").write_text("\n".join(rows), encoding="utf-8-sig")
    print("样例", len(sample), "错误", result["errors"], "正确", result["controls"])
    print("长度基线 ", base)
    print("本组方法 ", ours)
    return result


def main():
    parser = argparse.ArgumentParser(description="菜谱本体与实例质量检查")
    parser.add_argument("command", choices=["check", "eval"])
    parser.add_argument("--tag", default="before")
    args = parser.parse_args()
    if args.command == "check":
        run_check(args.tag)
    else:
        run_eval()


if __name__ == "__main__":
    main()
