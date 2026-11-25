# 审查与修改说明

项目方向可行，且符合课程要求中的食品烹饪领域。已有本体概念结构、规则抽取、质量检查与四组实验，最有价值的改进是让本体真正参与运行、让执行约束不丢失、让对照结论可复核。本次保留原始压缩包及历史模型记录，在解压后的项目中修改。

## 已完成

| 问题 | 修改及产物 |
|---|---|
| 自然语言层只在脚本中存在，页面和 API 未连接 | 页面增加自然语言输入；`POST /api/parse` 调用模型、验证参数，再由浏览器实际 `POST /api/search`；保留手动筛选功能 |
| 本体提示词实际上只由运行时词表产生 | `ontology_view` 读取 `ontology/ontology.json` 的类、关系、约束，并记录版本与 SHA256；词表仍来自食谱抽取 |
| 概念结构与实例事实缺少独立的可重建产物 | `python -m scripts.export_ontology` 导出 `ontology/instances.json`，含 723 实例、725 个源文件清单、文件哈希、原料原文、别名和覆盖规则 |
| 错误类型被静默改成空数组；删除分类后扩大检索范围 | 参数类型、范围和未知字段验证；空分类保留为空集合；接口遇到未映射、冲突或不支持维度时返回 `needs_clarification`，不发起搜索 |
| 十分钟被当成一二星难度 | 两组共同提示词把时间列为不支持维度，不再替代为难度 |
| B/C 独立调用模型，混入生成差异 | 新实验 C 复用 B 的同一原始输出，只增加归一校验；D/B 用同一基础提示词，B 仅追加本体上下文 |
| “完全匹配”漏算标注为空但预测多填的字段 | 修正为五字段逐一整集相等；补充回归测试 |
| 可做性没有检查分类与难度 | 增加两项检查；指标仍仅覆盖已有标注和菜谱抽取规则 |
| 回放缺记录时可能调用模型，且覆盖历史记录 | 缺记录明确失败，离线回放不调模型；重算分数；新结果写入独立目录，保留历史证据 |
| 调用失败从成功率分母消失 | 保留计划任务数、成功记录数、错误数；失败计入任务成功率分母；输出返回非零状态 |
| 缺少调用成本汇总 | 汇总接口报告的 token 与 elapsed_ms；C 复用 B，不重复计算模型成本 |

依赖以 `requirements.txt` 为准，测试额外依赖 `httpx` 由 `requirements-dev.txt` 追加，仅用于 API 集成测试。

## 运行

在本目录执行（Python 3.13 已验证）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
# 通过环境变量设置 WTE_LLM_BASE_URL、WTE_LLM_API_KEY、WTE_LLM_MODEL
.venv/bin/python -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000
```

打开页面后输入“我有番茄和鸡蛋，想做简单一点的”，可勾选是否使用本体。若未配置模型接口，返回 503 和配置提示。凭据只从环境读取。

```bash
.venv/bin/python -m unittest scripts.test_planner scripts.test_nl_query scripts.test_revision -v
python3 -m scripts.export_ontology
python3 -m scripts.quality_check check --tag review
python3 -m scripts.stage3_eval --replay --output-dir stage3/runs/historical-rescore
python3 -m scripts.stage3_eval --provider stub --output-dir stage3/runs/new-smoke
# 正式实验：新输出目录不得已有文件
python3 -m scripts.stage3_eval --output-dir stage3/runs/experiment-01
# 推荐让另一位组员冻结新的独立测试样例，格式参照 scripts.stage3_eval.TASKS
python3 -m scripts.stage3_eval --tasks path/to/frozen_tasks.json --output-dir stage3/runs/heldout-01
```

新实验每个任务调用 A、D、B 三次模型，C 复用 B。四组均保留；A 只是直接生成菜名的参考基线，主要对照为 D/B，校验消融为 B/C。批量评测调用与 `/api/search` 相同的 Python 检索器和规范化逻辑；浏览器演示和集成测试实际走 HTTP API。评测输出记录提示词、原始回答、模型配置、token、参数、结果和分数。

## 已验证结果与适用边界

- 单元与 API 集成测试可用 `python -m unittest scripts.test_planner scripts.test_nl_query scripts.test_revision` 复现；模型由测试替身替代，不是模型效果评测。
- 阶段二规则复查为 0 条，见 `stage2/issues_review.json`；这只表示现有规则没有发现问题，不表示语义正确，也不是本次新做的大模型质量复核。
- 历史 20 任务 × 4 组记录重评分见 `stage3/runs/historical-rescore/results.json`，逐条分数见同目录 `scored_records.json`。D/B/C 五字段完全匹配率分别为 0.30/0.70/0.70；按已有条件核算的已匹配候选可做率为 0.519/0.818/0.818。A 的可做率是已匹配菜名子集上的比例，不能视为全部生成菜名的成功率。
- 这些是旧模型回答的重评分，不是新版提示词或新版守卫逻辑的实测提升。旧记录的来源来自用户提供的归档，本次未独立重跑或验证远端模型。
- 原测试任务及失败分析已参与历史开发，不能将它们重新包装为未见测试集；建议另一位组员冻结新任务并提供人工参考答案。`--tasks` 支持独立文件。
- 参数 F1 仍是成功解析记录上的诊断指标；模型调用失败率单独报告，不能只用 F1 宣称整体成功。五字段完全匹配不覆盖 mode、半成品、unsupported_dimensions，不能当成完整语义正确率。
- D/B 共用含别名、单向覆盖规则的检索器，因此准确命名是“无/有本体提示词”，不能称为完全无领域知识与完整本体的净对照。
- 本次没有可用模型配置，未运行新版本的真实模型实验。stub 仅验证程序运行，不能写进效果结论；集成测试里的模型输出同样由测试替身驱动，不代表模型效果。

## 尚未解决、报告中必须明确的内容

本体概念层是从项目代码与领域资料显式整理的结构；实例导出是确定性规则抽取，并非大模型自动建本体。阶段一可描述为人工/Agent 辅助建模与规则实例化；不要宣称完成了“LLM 自动抽取—人工核验”的新实验。新增证据是文件与原料段落级追溯，不能作为每条关系已被原文蕴含的证明。

现有接口以 ingredients 表示已有/想用食材，以 seasonings/tools 表示缺少资源。它尚不支持独立的“必须包含”“禁止食材”“可购买缺料”语义，默认佐料和厨具齐备。营养、时间、过敏、口味等条件没有可靠建模，当前只能提示无法执行；若模型漏抽这些限制，程序也无法保证发现。不要把结果作为过敏安全或营养达标结论。

真正的下一轮扩展应在标注与来源就绪后，增加独立的可用性/需求断言及来源证据，再扩展检索接口与人工评价；本次没有在缺少标注时强行填补这些领域事实。最终提交还需要小组填写真实成员分工、人工核验记录，并据实际完成范围制作 PPT 与报告。
