# 今天吃什么，是啊吃什么

> 已完成一次代码与实验审查：新增自然语言页面入口、真实本体上下文、严格参数验证和修正后的评测。下文及 `stage3/` 原报告的数值属于历史版本，重评分结果见 `stage3/runs/historical-rescore/`。

本地菜谱选择器。FastAPI 在启动时读取 `recipe` 下的 CSV、Markdown 和单向匹配规则，并为同一页面提供数据接口。前端无需额外构建。

## 本地运行

在仓库根目录（本文件所在目录）执行以下命令。已有 Python 3.13 的 `cook` 环境时可跳过创建步骤。

```powershell
conda create -n cook python=3.13 -y
conda run -n cook python -s -m pip install -r requirements.txt
conda run -n cook --no-capture-output python -s -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000
```

运行依赖见 `requirements.txt`（`fastapi`、`uvicorn`、`pydantic`，Python 3.13 已实测）。跑测试另需 `httpx==0.28.1`。

打开 [菜谱选择器](http://127.0.0.1:8000/) 或 [接口文档](http://127.0.0.1:8000/docs)。在启动服务的终端按 Ctrl+C 可停止。修改菜谱数据后重启服务以重新读取。


## 验证

```powershell
conda run -n cook python -s -m unittest scripts.test_planner -v
```

测试覆盖规则文件中的验收示例、食材与难度筛选、工具任选一项、可选项、配料与克数合并。

## 目录结构

| 目录 | 内容 |
|---|---|
| `recipe/` | 领域数据：724 行菜谱索引 CSV、723 篇 Markdown（14 个菜品分类 + 51 个配料）、单向匹配规则 |
| `scripts/` | `recipe_data.py` 抽取、`planner.py` 检索与推荐、`main.py` API、`frontend/` 页面 |
| `ontology/` | **阶段一产物**：领域本体（12 类 / 8 关系 / 8 约束），Turtle + JSON 双版本 |
| `stage2/` | **阶段二产物**：质量检查器输出、问题清单（修前 99 条 → 修后 0 条）、对照实验 |
| `stage3/` | **阶段三产物**：自然语言解析提示词、20 条评测任务、执行记录、对照结果 |

## 课程作业：Agent 与领域本体协同增强

| 阶段 | 入口 | 说明 |
|---|---|---|
| 一 · 本体构建 | [`ontology/README.md`](ontology/README.md) | 建模方式、来源依据、规模统计、修改记录 |
| 二 · 质量检查 | [`stage2/README.md`](stage2/README.md) | 检查设计、修正内容、复查结果、对照实验、典型案例 |
| 二 · 已知问题 | [`stage2/KNOWN_ISSUES.md`](stage2/KNOWN_ISSUES.md) | 仍存问题、方法边界与待复核项（复查 0 条 ≠ 没有问题） |
| 三 · 增强 Agent | [`stage3/README.md`](stage3/README.md) | 自然语言 → 结构化参数 → 现有检索；A/D/B/C 四方案消融对照与结果 |
| 三 · 典型案例 | [`stage3/cases.md`](stage3/cases.md) | 4 个完整案例：成功、失败、边界，含输入/过程/输出/判定依据 |

质量检查可单独运行（只依赖标准库）：

```powershell
python -m scripts.quality_check check --tag after   # 全量扫描，当前应为 0 条
python -m scripts.quality_check eval                # 构造错误样例的对照评测
```

自然语言层（阶段三）需要一个 OpenAI 兼容接口。两种配置方式，**同一字段两处都配时以环境变量为准**。

方式一 · 本地配置文件（推荐，配一次长期有效）：

在项目根目录新建 `llm.local.json`，填三个必填项：

```json
{"base_url": "https://your-gateway/v1", "api_key": "sk-...", "model": "your-model"}
```

该文件已被 `.gitignore` 忽略，不会进仓库。可先自检，密钥只显示首尾：

```powershell
python -m scripts.llm_client
```

方式二 · 环境变量（临时覆盖，适合切换模型或跑 CI）：

```powershell
$env:WTE_LLM_BASE_URL = "https://your-gateway/v1"
$env:WTE_LLM_API_KEY  = "sk-..."
$env:WTE_LLM_MODEL    = "gpt-4o-mini"
```

`base_url`、`api_key`、`model` 必填；`temperature`（默认 0）、`timeout`（默认 75 秒）、`max_tokens`（默认 4000）可选，配置文件中用同名小写键。也可以用 `WTE_LLM_CONFIG` 指向别的配置文件路径。

配好后自检并运行评测：

```powershell
python -m scripts.llm_client --ping                 # 发一次最小请求验证连通性
python -m scripts.stage3_eval --check-gold          # 先验证标注可用，不调模型
python -m scripts.stage3_eval                       # 20 任务 × 4 方案 = 80 次调用
python -m scripts.stage3_eval --replay              # 用已录制记录复算
```

未配置模型时页面仍能正常打开，调用自然语言入口（`POST /api/parse`）会返回 503 并提示缺少哪几项。
