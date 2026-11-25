# 阶段一产物：菜谱领域本体（v0.2.0）

本目录把项目代码里**隐含**的结构显式化为可核对的本体文件，作为大作业阶段一（利用 Agent 或大模型辅助构建领域本体）的交付物。

| 文件 | 作用 | 读者 |
|---|---|---|
| `whattoeat.ttl` | OWL 2 / Turtle 形式化版本：类、关系、OWL 公理、受控词表 | 人、推理器 |
| `ontology.json` | 同源同版本的 JSON 结构化表示：类、关系、约束、实例映射、统计、遗留问题 | 程序、阶段二检查脚本 |
| `README.md` | 建模说明、来源依据、规模、局限、修改记录 | 报告与答辩 |

两个本体文件必须同步修改；`ontology.json` 是唯一可被程序直接消费的版本。

---

## 一、建模方式：概念结构与实例事实分开

| 层次 | 内容 | 存放位置 |
|---|---|---|
| **概念结构** | 12 个类、8 条关系、8 条数据属性、8 条约束（C1–C8）、14 个分类与 5 个难度等级 | 本目录两个本体文件 |
| **实例事实** | 723 条菜谱、672 道菜品、51 个配料、5913 条原料要求、6120 个原料项、61 条上位关系、39 条同义归一 | `recipe/` 源文件 + `scripts/recipe_data.py` 抽取结果 |

这样划分的依据是任务要求：“概念结构描述概念、属性、关系及必要约束；具体课程及其学分值属实例与事实”。本项目中 `Dish`、`Preparation`、`RecipeRequirement` 是概念，而“咖喱肥牛的咖喱块是必需项”是事实。

**复用与新增的界线**：菜谱原文（HowToCook、CookLikeHOC 及公开视频）与 61 条上位规则是**复用/整理**的领域资料；12 个类、8 条关系、8 条约束的显式化，以及把变体从硬编码提升为 `MethodVariant` 类，是本次**新增**的建模工作。实例数量（6120 个原料项）不等于新建概念数量。

---

## 二、12 个概念类

| 类 | 中文 | 上位类 | 实例数 | 判定依据 |
|---|---|---|---|---|
| `FoodProduct` | 可制作食物 | — | — | `Recipe` 数据类（同时承载菜品与配料） |
| `Dish` | 菜品 | FoodProduct | 672 | `category != 配料` |
| `Preparation` | 配料（半成品） | FoodProduct **且** Ingredient | 51 | `recipe/配料/*.md` |
| `PantryItem` | 厨房资源 | — | — | `KINDS` 三元组的上位 |
| `Ingredient` | 食材 | PantryItem | — | `kind_of()` 默认分支 |
| `Seasoning` | 佐料 | PantryItem | — | 词表 + 「油/酱/盐/汁/醋」词尾 |
| `Tool` | 厨具 | PantryItem | — | 厨具段落 + 正则 |
| `RecipeRequirement` | 原料要求 | — | 5913 | `Requirement` 数据类 |
| `RequirementOption` | 要求项 | — | 6120 | `Material` 数据类 |
| `MethodVariant` | 做法变体 | — | 2 | `Recipe.variants` |
| `DishCategory` | 菜品分类 | — | 14 | 目录名 / CSV 种类列 |
| `DifficultyLevel` | 难度等级 | — | 5 | CSV 难度列 |

**两处有意为之的建模决定**：

1. `Preparation` 多重归类。半成品既是“做出来的食物”（`FoodProduct`），又是“下一道菜可用的食材”（`Ingredient`）。因此 `FoodProduct` 与 `PantryItem` **不能**声明为互斥，否则配料会自相矛盾。代码里 `kind_of()` 把配料按 `ingredient` 处理，与此一致。
2. `MethodVariant` 独立成类。原实现用 `if name == "原味豆浆"` 硬编码区分现磨版与冲调版；本体把它提升为可复用的类，并要求“有变体时原料要求下沉到变体”，这是概念层对实现层的一次修正（实现尚未跟进，见遗留问题 O3）。

---

## 三、8 条关系

| 关系 | 中文 | 定义域 → 值域 | 特性 | 说明 |
|---|---|---|---|---|
| `requires` | 要求 | FoodProduct ∪ MethodVariant → RecipeRequirement | — | 菜谱对原料的要求，方向不可反 |
| `hasOption` | 候选 | RecipeRequirement → RequirementOption | 至少 1 个 | 同一要求下的候选之间是「或」 |
| `refersTo` | 指向资源 | RequirementOption → PantryItem | 恰好 1 个 | 决定该项是食材/佐料/厨具 |
| `broader` | 上位原料 | PantryItem → PantryItem | 传递、非对称、非自反 | **单向覆盖**，61 条 |
| `usesPreparation` | 使用配料 | Dish → Preparation | — | 组成关系的第一段 |
| `hasVariant` | 有做法 | FoodProduct → MethodVariant | — | 互斥做法分支 |
| `belongsToCategory` | 属于分类 | Dish → DishCategory | 恰好 1 个 | 14 类 |
| `hasDifficulty` | 难度为 | FoodProduct → DifficultyLevel | 恰好 1 个 | 1–5 星 |

**组成关系的建模方式**：`Dish --usesPreparation--> Preparation --requires--> RecipeRequirement`。菜品不直接展开配料的原料，而是引用配料实体，由配料自己描述构成，避免同一份半成品在每道菜里重复建模（对应代码 `shopping()` 的合并逻辑）。

**上位关系与同义归一是两件事**：`broader` 是层级覆盖（茉莉绿茶 → 绿茶 → 茶叶），`skos:altLabel` 是同一实体的不同叫法（西红柿 = 番茄）。混用会导致“番茄能满足西红柿、西红柿能满足番茄”的循环，本项目代码中二者分别由 `read_rules()` 与 `ALIASES` 维护，本体保持同样区分。

---

## 四、约束 C1–C8

| 编号 | 约束 | OWL 表达 | 检查方式 |
|---|---|---|---|
| C1 | 菜品至少一条 `requires` 或一个 `hasVariant` | `Dish ⊑ (∃requires) ⊔ (∃hasVariant)` | 实例：`requirements or variants` 非空 |
| C2 | 每个要求至少 1 个候选 | `≥1 hasOption` | `len(group.options) >= 1` |
| C3 | 必需/可选必须显式 | `=1 isOptional.xsd:boolean` | `group.optional in (True, False)` |
| C4 | 同要求多候选为「多选一」 | 无法用 OWL 表达（不区分与/或） | `planner.check()` 的 `any(...)` 语义 |
| C5 | 上位覆盖单向不可逆 | `Transitive + Asymmetric + Irreflexive` | `expand()` 传递闭包 + 拒绝集断言 |
| C6 | 有变体时要求下沉到变体 | C1 并集 + `MethodVariant ⊑ ≥1 requires` | `variants` 非空 ⇒ `requirements == []` |
| C7 | 克数缺失 = 信息不足 | 无数值公理 | `grams is None` 必须能回溯到「适量/少许」原文 |
| C8 | 食材/佐料/厨具互斥；菜品与配料互斥；配料可同时是食材 | `AllDisjointClasses` + `disjointWith` | 同名只归一个 kind；配料可作 ingredient 选中 |

C4 与 C7 是 OWL 表达不了的语义约定，因此在 `ontology.json` 的 `constraints` 里写成可执行检查项，供阶段二直接使用。任务要求“格式合法、逻辑一致与领域语义正确属于不同层面”，C4/C7 正属于语义层，不能靠推理器代替。

---

## 五、规模统计（脚本实测，非估计）

| 指标 | 数值 |
|---|---|
| 菜谱 Markdown | 723 篇（14 个菜品分类 + 配料） |
| 菜品 / 配料 | 672 / 51 |
| 难度分布 | 1★74、2★219、3★241、4★114、5★24 |
| 菜品级原料要求 | 5897 组（必需 5689、可选 208） |
| 原料项 | 6097 个，其中 1991 个有克数（覆盖率 32.7%） |
| 上位规则 | 60 条 |
| 同义归一 | 66 条 |
| CSV 标签去重 | 636 个；词表 669 个 |
| 无热量文本的菜 | 68 道 |

> 以上为**阶段二修正后**的数字。修正前为：要求 5913 组（必需 5710 / 可选 203）、
> 原料项 6120、有克数 1990（32.5%）、上位规则 61 条、同义 39 条。
> 变化明细见 `stage2/README.md`。

---

## 六、遗留问题（阶段二、三已处理部分）

| 编号 | 问题 | 状态 |
|---|---|---|
| O1 | 未归一原料名（修正前 1104 个） | 已修正 62 个（修饰语剥离 + 切配形态归一），**剩 1042 个**待下一轮 |
| O2 | 上位规则左项不在 CSV 标签（小元宵） | **已修正**：删除该规则，规则 61→60，复查 0 条 |
| O3 | 变体仍靠 `if name == "原味豆浆"` 硬编码 | 待改造 |
| O4 | 68 道菜无热量，克数覆盖率 32.7% | 按约束 C7 保留为「信息不足」，不补全 |
| O5 | `SEASONINGS` / `TOOL` 集合未并入 `vocabulary`，导致 `白砂糖`、`花雕酒` 等不参与形态归一判定 | 阶段二发现（造成 6 条漏检），待统一词表 |
| O6 | `PantryItem` 只有 `kind`，没有「有 / 没有」的极性；而接口 `ingredients` 是正向、`seasonings`/`tools` 是反向，导致「我有大蒜」无处表达（大蒜属 `Seasoning`） | 阶段三发现，需新增 `AvailabilityAssertion` 才能根治 |
| O7 | 没有口味、菜系、场景、营养等维度，14 个分类只覆盖做法 | 阶段三按 `unsupported_dimensions` 显式标注，不臆造分类 |

完整问题清单、修正记录与对照实验见 `stage2/README.md`；阶段三的用法与边界见 `stage3/README.md`。

---

## 七、修改记录

| 版本 | 日期 | 变更 | 依据 |
|---|---|---|---|
| 0.1.0 | 2026-11-25 | 从 `scripts/recipe_data.py`、`scripts/planner.py` 与 `recipe/` 显式化出 12 类 / 8 关系 / 8 约束；新增 `MethodVariant` 类；把 `ALIASES` 明确为 `skos:altLabel` 而非 `broader`；记录 O1–O4 四个遗留问题 | 代码静态阅读 + 脚本统计（`load_catalog()` 实测） |
| 0.2.0 | 2026-11-25 | 阶段二修正后同步统计：要求组 5913→5897、原料项 6120→6097、上位规则 61→60、同义词 39→66；O2 关闭，新增 O5（词表未统一） | `stage2/issues_before.json` → `issues_after.json` 复查 0 条；14 个单元测试通过 |
| 0.3.0 | 2026-11-25 | 阶段三接入自然语言入口后新增 O6（可用性极性缺失）、O7（口味/菜系无槽位）；本体公理未变，仅扩充遗留问题 | `stage3/README.md` §7；`scripts/test_nl_query.py` 10 个用例 |

---

## 八、如何校验

```powershell
# JSON 结构与内部一致性
python -c "import json;d=json.load(open('ontology/ontology.json',encoding='utf-8'));print(len(d['classes']),len(d['object_properties']),len(d['constraints']))"

# Turtle 语法与公理（需 rdflib，未加入运行依赖）
python -c "from rdflib import Graph;g=Graph();g.parse('ontology/whattoeat.ttl');print(len(g))"
```

## 本次审查新增

`python -m scripts.export_ontology` 可重建 `instances.json`：规则抽取实例与文件级证据，不更改概念公理。自然语言解析器现在直接读取 `ontology.json` 的概念、关系与约束。详情见 [审查说明](../REVIEW.md)。
