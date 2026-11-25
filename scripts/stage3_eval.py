"""阶段三四方案评测。D/B 共享接口与检索器，差别为提示词中的本体上下文；
C 另加归一校验。共享检索器已包含领域规则，因此 D 不是完全无领域知识。
历史回放仅重算指标，不代表新版提示词的实验结果。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from .agent import clarification_reasons
from .llm_client import Client, LLMError, StubClient, extract_json
from .nl_query import (baseline_prompt, normalize, ontology_view, parse_params,
                       passthrough, search)
from .planner import Planner
from .recipe_data import load_catalog

ROOT = Path(__file__).resolve().parent.parent
STAGE3 = ROOT / "stage3"
RECORDS = STAGE3 / "records"
RECORD_ROOT = RECORDS   # 由 main 按 provider 切换，桩数据不会污染正式记录

# ---------------------------------------------------------------- 任务与标注

def task(task_id, split, text, gold, note=""):
    return {"id": task_id, "split": split, "text": text, "gold": gold, "note": note}


ALL = [1, 2, 3, 4, 5]
TASKS = [
    # ---- 开发集：调提示词只用这 10 条 ----
    task("D01", "dev", "我有番茄和鸡蛋，想吃简单点的",
         {"ingredients": ["番茄", "鸡蛋"], "seasonings": [], "tools": [],
          "difficulties": [1, 2], "categories": None}),
    task("D02", "dev", "冰箱里有土豆、胡萝卜和洋葱，家里没有高压锅",
         {"ingredients": ["土豆", "胡萝卜", "洋葱"], "seasonings": [], "tools": ["高压锅"],
          "difficulties": ALL, "categories": None}),
    task("D03", "dev", "想喝汤，家里有排骨和冬瓜",
         {"ingredients": ["排骨", "冬瓜"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["汤"]}),
    task("D04", "dev", "早餐想吃点简单的，有面粉和鸡蛋",
         {"ingredients": ["面粉", "鸡蛋"], "seasonings": [], "tools": [],
          "difficulties": [1, 2], "categories": ["早餐"]}),
    task("D05", "dev", "我有五花肉，但是没有豆瓣酱",
         {"ingredients": ["五花肉"], "seasonings": ["豆瓣酱"], "tools": [],
          "difficulties": ALL, "categories": None}),
    task("D06", "dev", "想吃凉拌菜，有黄瓜和木耳",
         {"ingredients": ["黄瓜", "木耳"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["凉拌"]}),
    task("D07", "dev", "有鸡胸肉和西兰花，想做个简单的炒菜",
         {"ingredients": ["鸡胸肉", "西兰花"], "seasonings": [], "tools": [],
          "difficulties": [1, 2], "categories": ["炒菜"]}),
    task("D08", "dev", "有剩米饭、鸡蛋和火腿肠，想当主食吃",
         {"ingredients": ["米饭", "鸡蛋", "火腿肠"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["主食"]}),
    task("D09", "dev", "家里只有豆腐和白菜，想炖一锅",
         {"ingredients": ["豆腐", "白菜"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["炖菜"]}),
    task("D10", "dev", "想喝点热的，有牛奶和红茶",
         {"ingredients": ["牛奶", "红茶"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["饮品"]}),
    # ---- 测试集：只在正式报告里出现，不用于改提示词 ----
    task("T01", "test", "有虾仁和鸡蛋，但没有料酒",
         {"ingredients": ["虾仁", "鸡蛋"], "seasonings": ["料酒"], "tools": [],
          "difficulties": ALL, "categories": None}),
    task("T02", "test", "想吃烤的，有鸡翅，也有烤箱",
         {"ingredients": ["鸡翅"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["烤类"]},
         note="「有烤箱」是正向条件，tools 应为空而非排除"),
    task("T03", "test", "有牛肉和洋葱，想炖着吃，别太难",
         {"ingredients": ["牛肉", "洋葱"], "seasonings": [], "tools": [],
          "difficulties": [1, 2, 3], "categories": ["炖菜"]}),
    task("T04", "test", "想做个汤，有紫菜、鸡蛋和虾皮",
         {"ingredients": ["紫菜", "鸡蛋", "虾皮"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["汤"]}),
    task("T05", "test", "有面粉和猪肉馅，想包点东西当早餐",
         {"ingredients": ["面粉", "猪肉馅"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["早餐"]}),
    task("T06", "test", "家里没有生抽也没有料酒，只有青菜和面条",
         {"ingredients": ["青菜", "面条"], "seasonings": ["生抽", "料酒"], "tools": [],
          "difficulties": ALL, "categories": None}),
    task("T07", "test", "有山药和排骨，想蒸个菜",
         {"ingredients": ["山药", "排骨"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["蒸菜"]}),
    task("T08", "test", "想吃卤味，有鸡爪",
         {"ingredients": ["鸡爪"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": ["卤菜"]}),
    task("T09", "test", "有茄子和青椒，想吃炒菜，家里没有生抽",
         {"ingredients": ["茄子", "青椒"], "seasonings": ["生抽"], "tools": [],
          "difficulties": ALL, "categories": ["炒菜"]}),
    task("T10", "test", "有酸奶和芒果，想做甜品",
         {"ingredients": ["酸奶", "芒果"], "seasonings": [], "tools": [],
          "difficulties": ALL, "categories": None},
         note="「甜品」不在 14 个分类内，属本体无槽位，应进 unsupported_dimensions"),
]

# 消融阶梯：
#   A 无本体提示词 + 无检索      （纯大模型直判）
#   D 无本体提示词 + 检索        （只把模型当参数抽取器，词表自由）
#   B 本体提示词   + 检索，不校验（本体只约束输出空间）
#   C 本体提示词   + 检索 + 校验（完整流程）
# D→B 是「本体进入提示词」的贡献，B→C 是「调用后归一校验」的贡献。
ARMS = {"A": "直接问模型", "D": "无本体提示词+检索", "B": "本体提示词+不校验", "C": "完整流程"}


# ---------------------------------------------------------------- 打分

FIELDS = ("ingredients", "seasonings", "tools", "categories", "difficulties")
NAME_FIELDS = ("ingredients", "seasonings", "tools")


def _set(value):
    return set(value) if value else set()


def score_params(pred: dict, gold: dict) -> dict:
    """两个口径，避免「难度恒填 1-5」「该填的都留空」把分数刷上去：

    - `tp/fp/fn`：三个名称字段上的元素级统计，空答案直接得 0；
    - `name_hits`：三个名称字段各自整集一致才计 1（分母 3）；
    - `category_hit` / `difficulty_hit`：单字段整集一致；
    - `exact`：5 个字段全部一致。
    """
    counts = {"tp": 0, "fp": 0, "fn": 0, "name_hits": 0, "name_total": 0,
              "category_hit": 0, "difficulty_hit": 0}
    for field in NAME_FIELDS:
        got, want = _set(pred.get(field)), _set(gold.get(field))
        counts["tp"] += len(got & want)
        counts["fp"] += len(got - want)
        counts["fn"] += len(want - got)
        if want:                      # 分母只算「标注里确实有内容」的字段，
            counts["name_total"] += 1  # 否则「一律留空」也能刷到高分
            counts["name_hits"] += int(got == want)
    counts["category_hit"] = int(_set(pred.get("categories")) == _set(gold.get("categories")))
    counts["difficulty_hit"] = int(_set(pred.get("difficulties")) == _set(gold.get("difficulties")))
    counts["exact"] = int(all(_set(pred.get(field)) == _set(gold.get(field)) for field in FIELDS))
    return counts


def match_dish(planner, name: str):
    """把模型给的菜名落到目录上：精确 → 双向包含（容忍语序差异）→ 关键词检索。

    都落不上就记为幻觉。宽容度刻意保留在「包含」这一级：
    「排骨冬瓜汤」能对上「冬瓜排骨汤」，但「番茄鸡蛋面」不会对上「番茄炒蛋」。
    """
    name = name.strip()
    for recipe in planner.dishes:
        if recipe.name == name:
            return recipe.id
    contained = [recipe for recipe in planner.dishes
                 if name and (name in recipe.name or recipe.name in name)]
    if contained:
        return min(contained, key=lambda recipe: abs(len(recipe.name) - len(name))).id
    hits = planner.find_recipes(name)
    return hits[0]["id"] if hits else None


# ---------------------------------------------------------------- 单任务执行

def record_path(arm: str, task_id: str) -> Path:
    return RECORD_ROOT / arm / f"{task_id}.json"


def run_arm(planner, view: dict, item: dict, arm: str, client, *, replay: bool) -> dict:
    path = record_path(arm, item["id"])
    if replay:
        if not path.exists():
            raise ValueError(f"离线回放缺少记录：{arm}/{item['id']}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if arm != "A":
            record["params_score"] = score_params(record["params"], item["gold"])
        return record

    if arm == "A":
        system = baseline_prompt(planner)
        reply = client.chat(system, item["text"])
        names = extract_json(reply["text"]).get("dishes", [])
        names = [str(name).strip() for name in names][:5]
        hits = [(name, match_dish(planner, name)) for name in names]
        record = {
            "task_id": item["id"], "split": item["split"], "arm": arm,
            "system_prompt": system, "user": item["text"],
            "raw_response": reply["text"], "meta": {**client.describe(), **{
                "usage": reply.get("usage", {}), "elapsed_ms": reply.get("elapsed_ms", 0)}},
            "dishes": names,
            "matched": [{"name": name, "id": dish_id} for name, dish_id in hits],
            "result": {"mode": "direct", "items": [
                {"id": dish_id, "name": name} for name, dish_id in hits if dish_id]},
        }
    else:
        system = plain_prompt_cached() if arm == "D" else parser_prompt_cached(planner, view)
        if arm == "C":
            paired = json.loads(record_path("B", item["id"]).read_text(encoding="utf-8"))
            reply = {"text": paired["raw_response"], "usage": {}, "elapsed_ms": 0}
        else:
            reply = client.chat(system, item["text"])
        params = parse_params(reply["text"])
        clean, report = (normalize(params, view) if arm == "C" else (passthrough(params), {}))
        reasons = clarification_reasons(clean, report, planner)
        record = {
            "task_id": item["id"], "split": item["split"], "arm": arm,
            "system_prompt": system, "user": item["text"],
            "raw_response": reply["text"], "meta": {**client.describe(), **{
                "usage": reply.get("usage", {}), "elapsed_ms": reply.get("elapsed_ms", 0)}},
            "status": "needs_clarification" if reasons else "ready", "reasons": reasons,
            "params_raw": params, "params": clean, "report": report,
            "paired_with": "B" if arm == "C" else None,
            "result": {"mode": clean["mode"], "items": []} if reasons else search(planner, clean),
        }
    record["params_score"] = score_params(record["params"], item["gold"]) if arm != "A" else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


_VIEW_CACHE: dict = {}


def parser_prompt_cached(planner, view) -> str:
    if "prompt" not in _VIEW_CACHE:
        from .nl_query import parser_prompt
        _VIEW_CACHE["prompt"] = parser_prompt(view)
    return _VIEW_CACHE["prompt"]


def plain_prompt_cached() -> str:
    """对照组 D：同一份 schema，但不给任何词表与分类枚举。"""
    if "plain" not in _VIEW_CACHE:
        from .nl_query import PROMPT_DIR
        _VIEW_CACHE["plain"] = (PROMPT_DIR / "parser_plain.md").read_text(encoding="utf-8")
    return _VIEW_CACHE["plain"]


# ---------------------------------------------------------------- 可行性核算

def annotate_feasibility(records: dict, planner, tasks: list) -> None:
    """用人工标注的「用户真实条件」回头检查每条推荐到底做不做得出来。

    A 方案只看菜名，不知道每道菜要什么原料，所以「名字有效」不等于「现在能做」。
    这一步不需要再调模型：把已录制的推荐结果放回检索器里核对即可。
    """
    for item in tasks:
        gold = item["gold"]
        selected, covered = planner.pantry(gold["ingredients"], gold.get("preparation_ids", []))
        excluded = {"seasoning": set(gold["seasonings"]), "tool": set(gold["tools"])}
        for record in records.get(item["id"], {}).values():
            ids = [entry["id"] for entry in record["result"]["items"] if entry.get("id")]
            feasible = 0
            for recipe_id in ids:
                recipe = planner.recipes.get(recipe_id)
                if recipe is None:
                    continue
                check = planner.best_method(recipe, selected, covered, excluded)[1]
                feasible += int(not (check.missing or check.supplies or check.blocked)
                                and recipe.difficulty in gold["difficulties"]
                                and (gold["categories"] is None or recipe.category in gold["categories"]))
            record["feasible"] = feasible
            record["items_total"] = len(ids)
            record["feasible_rate"] = round(feasible / max(1, len(ids)), 3)



def resolve_client(records: dict, client) -> dict:
    """replay 时用记录里真实的模型信息，而不是当前环境变量（可能没配）。"""
    for item_records in records.values():
        for record in item_records.values():
            meta = record.get("meta") or {}
            if meta.get("model") and meta["model"] != "stub":
                return {"base_url": meta.get("base_url"), "model": meta["model"],
                        "temperature": meta.get("temperature")}
    return client.describe()


# ---------------------------------------------------------------- 汇总

def summarize(records: dict, tasks: list) -> dict:
    gold = {item["id"]: item["gold"] for item in tasks}
    out = {}
    for arm in ARMS:
        rows = [records[item["id"]][arm] for item in tasks
                if arm in records.get(item["id"], {})]
        bucket = {"tasks": len(tasks), "successful_records": len(rows), "errors": len(tasks) - len(rows), "ready_zero": len(tasks) - len(rows), "nonempty": 0, "ready": 0,
                  "dropped": 0, "aliases": 0, "violations": 0, "unmapped": 0,
                  "tp": 0, "fp": 0, "fn": 0, "exact": 0, "name_hits": 0,
                  "name_total": 0, "category_hits": 0, "difficulty_hits": 0,
                  "feasible": 0, "items_total": 0}
        if arm == "A":
            bucket["valid_names"] = 0
            bucket["total_names"] = 0
            for row in rows:
                bucket["total_names"] += len(row["dishes"])
                bucket["valid_names"] += sum(1 for item in row["matched"] if item["id"])
                bucket["ready_zero"] += int(not row["result"]["items"])
                bucket["nonempty"] += int(bool(row["result"]["items"]))
                bucket["ready"] += len(row["result"]["items"])
                bucket["feasible"] += row.get("feasible", 0)
                bucket["items_total"] += row.get("items_total", 0)
        else:
            for row in rows:
                bucket["feasible"] += row.get("feasible", 0)
                bucket["items_total"] += row.get("items_total", 0)
                score = row["params_score"]
                for key in ("tp", "fp", "fn"):
                    bucket[key] += score[key]
                bucket["exact"] += int(score["exact"])
                bucket["name_hits"] += score["name_hits"]
                bucket["name_total"] += score["name_total"]
                bucket["category_hits"] += score["category_hit"]
                bucket["difficulty_hits"] += score["difficulty_hit"]
                result = row["result"]
                bucket["ready"] += result.get("ready_total", len(result["items"]))
                bucket["ready_zero"] += int(not result["items"])
                bucket["nonempty"] += int(bool(result["items"]) or bool(result.get("related")))
                report = row.get("report") or {}
                bucket["dropped"] += len(report.get("dropped", []))
                bucket["aliases"] += len(report.get("aliases", {}))
                bucket["violations"] += len(report.get("violations", []))
                bucket["unmapped"] += sum(len(v) for v in report.get("unmapped", {}).values())
        total = max(1, bucket["tasks"])
        bucket["feasible_rate"] = round(bucket["feasible"] / max(1, bucket["items_total"]), 3)
        bucket["ready_zero_rate"] = round(bucket["ready_zero"] / total, 3)
        bucket["nonempty_rate"] = round(bucket["nonempty"] / total, 3)
        if arm != "A":
            precision = bucket["tp"] / max(1, bucket["tp"] + bucket["fp"])
            recall = bucket["tp"] / max(1, bucket["tp"] + bucket["fn"])
            bucket["precision"] = round(precision, 3)
            bucket["recall"] = round(recall, 3)
            bucket["f1"] = round(2 * precision * recall / max(1e-9, precision + recall), 3)
            bucket["name_field_acc"] = round(bucket["name_hits"] / max(1, bucket["name_total"]), 3)
            bucket["category_acc"] = round(bucket["category_hits"] / total, 3)
            bucket["difficulty_acc"] = round(bucket["difficulty_hits"] / total, 3)
            bucket["exact_rate"] = round(bucket["exact"] / total, 3)
            bucket["avg_ready"] = round(bucket["ready"] / total, 1)
        else:
            bucket["valid_rate"] = round(bucket["valid_names"] / max(1, bucket["total_names"]), 3)
            bucket["avg_names"] = round(bucket["total_names"] / total, 1)
        bucket["reported_tokens"] = sum(row.get("meta", {}).get("usage", {}).get("total_tokens", 0) for row in rows)
        bucket["elapsed_ms"] = sum(row.get("meta", {}).get("elapsed_ms", 0) for row in rows)
        out[arm] = bucket
    return out


def by_split(records: dict, tasks: list) -> dict:
    out = {}
    for split in ("dev", "test"):
        subset = [item for item in tasks if item["split"] == split]
        out[split] = summarize(records, subset)
    return out


def write_labels_template(tasks: list) -> Path:
    path = STAGE3 / "labels.csv"
    if path.exists():
        return path
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["task_id", "split", "arm", "判定", "理由"])
        for item in tasks:
            for arm in ARMS:
                writer.writerow([item["id"], item["split"], arm, "", ""])
    return path


def read_labels() -> dict:
    path = STAGE3 / "labels.csv"
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            value = (row.get("判定") or "").strip()
            if value in {"1", "0", "对", "错", "通过", "不通过"}:
                out[(row["task_id"], row["arm"])] = 1 if value in {"1", "对", "通过"} else 0
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段三：自然语言 → 参数 → 检索 对照评测")
    parser.add_argument("--provider", choices=("live", "stub"), default="live")
    parser.add_argument("--replay", action="store_true", help="复用已有记录，不再调用模型")
    parser.add_argument("--check-gold", action="store_true", help="只用标注跑一遍检索，验证标注本身")
    parser.add_argument("--tasks", type=Path, help="独立人工标注任务 JSON，字段同 TASKS")
    parser.add_argument("--output-dir", default="stage3/runs/current", help="新运行独立输出目录，不覆盖历史证据")
    parser.add_argument("--only", default="", help="只跑指定任务，逗号分隔，如 D01,T03")
    args = parser.parse_args()

    planner = Planner(*load_catalog())
    view = ontology_view(planner)
    source_tasks = json.loads(args.tasks.read_text(encoding="utf-8")) if args.tasks else TASKS
    tasks = [item for item in source_tasks
             if not args.only or item["id"] in args.only.split(",")]

    if args.check_gold:
        print(f"{'任务':4s} {'ready':>6s} {'related':>8s} {'空?':>4s}  说明")
        for item in tasks:
            gold = dict(item["gold"])
            gold.update({"mode": "search", "preparation_ids": [], "name_query": ""})
            result = search(planner, gold)
            flag = "空" if not result["items"] else ""
            print(f"{item['id']:4s} {result.get('ready_total', 0):6d} "
                  f"{result.get('related_total', 0):8d} {flag:>4s}  {item['note']}")
        return 0

    global RECORD_ROOT
    output_dir = Path(args.output_dir)
    if not args.replay and output_dir.exists() and any(output_dir.iterdir()):
        parser.error("输出目录非空，请为新实验指定独立 --output-dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    RECORD_ROOT = ((STAGE3 / "records_stub" if args.provider == "stub" else RECORDS)
                   if args.replay else output_dir / "records")
    client = StubClient() if args.provider == "stub" else Client.load()
    if not client.configured and not args.replay:
        print("未配置模型：请设置 WTE_LLM_BASE_URL / WTE_LLM_API_KEY / WTE_LLM_MODEL，"
              "或填写项目根目录的 llm.local.json。\n"
              "可用 --provider stub 冒烟，或 --replay 复算已有记录。", file=sys.stderr)
        return 2

    records: dict = defaultdict(dict)
    failures = []
    for item in tasks:
        for arm in ARMS:
            try:
                records[item["id"]][arm] = run_arm(
                    planner, view, item, arm, client, replay=args.replay)
            except (LLMError, ValueError, KeyError, TypeError, OSError) as error:
                failures.append({"task_id": item["id"], "arm": arm, "error": str(error)})
                print(f"[失败] {item['id']} {arm}: {error}", file=sys.stderr)
        done = len(records[item["id"]])
        print(f"{item['id']} 完成 {done}/{len(ARMS)}")

    annotate_feasibility(records, planner, tasks)
    (output_dir / "scored_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"provider": args.provider, "client": resolve_client(records, client),
               "arms": summarize(records, tasks), "by_split": by_split(records, tasks),
               "failures": failures, "tasks": len(tasks),
               "evaluation_version": "2", "historical_replay": args.replay,
               "interpretation": "历史输出重评分；不代表新版模型效果" if args.replay else "新运行"}
    name = "results_stub.json" if args.provider == "stub" else "results.json"
    (output_dir / name).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    print("\n=== 总体 ===")
    for arm, bucket in summary["arms"].items():
        if arm == "A":
            print(f"{arm} {ARMS[arm]}: 菜名有效率 {bucket['valid_rate']:.3f}，"
                  f"平均给出 {bucket['avg_names']:.1f} 个，"
                  f"**其中真能做 {bucket['feasible_rate']:.3f}**")
        else:
            print(f"{arm} {ARMS[arm]}: 名称F1 {bucket['f1']:.3f} (P {bucket['precision']:.3f} "
                  f"R {bucket['recall']:.3f}) | 名称字段全对 {bucket['name_field_acc']:.3f} | "
                  f"分类 {bucket['category_acc']:.3f} 难度 {bucket['difficulty_acc']:.3f} | "
                  f"整体全对 {bucket['exact_rate']:.3f} | 可做≥1 {1 - bucket['ready_zero_rate']:.3f} | "
                  f"非空 {bucket['nonempty_rate']:.3f} | 平均可做 {bucket['avg_ready']:.1f} | "
                  f"归一 {bucket['aliases']} 丢弃 {bucket['dropped']}")
    print("\n=== 测试集 ===")
    for arm, bucket in summary["by_split"]["test"].items():
        if arm == "A":
            print(f"{arm}: 菜名有效率 {bucket['valid_rate']:.3f}")
        else:
            print(f"{arm}: 名称F1 {bucket['f1']:.3f} 名称字段全对 {bucket['name_field_acc']:.3f} "
                  f"可做≥1 {1 - bucket['ready_zero_rate']:.3f} 非空 {bucket['nonempty_rate']:.3f} "
                  f"平均可做 {bucket['avg_ready']:.1f}")

    labels = read_labels()
    path = write_labels_template(tasks)
    if labels:
        print("\n=== 人工判定（labels.csv）===")
        for arm in ARMS:
            values = [value for (task_id, arm_name), value in labels.items() if arm_name == arm]
            if values:
                print(f"{arm}: {sum(values)}/{len(values)} = {sum(values) / len(values):.3f}")
    else:
        print(f"\n人工判定表已生成：{path}（填 1/0 后重跑即可汇总）")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
