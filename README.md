# 今天吃什么，是啊吃什么

本地菜谱选择器。FastAPI 在启动时读取 `recipe` 下的 CSV、Markdown 和单向匹配规则，并为同一页面提供数据接口。前端无需额外构建。

## 本地运行

在 `InternetNewTec` 目录中执行以下命令。已有 `cook` 环境时可跳过创建步骤。

```powershell
conda create -n cook python=3.13 pip -y
conda run -n cook python -s -m pip install -r requirements.txt
conda run -n cook --no-capture-output python -s -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000
```

打开 [菜谱选择器](http://127.0.0.1:8000/) 或 [接口文档](http://127.0.0.1:8000/docs)。在启动服务的终端按 Ctrl+C 可停止。修改菜谱数据后重启服务以重新读取。


## 验证

```powershell
conda run -n cook python -s -m unittest scripts.test_planner -v
```

测试覆盖规则文件中的验收示例、食材与难度筛选、工具任选一项、可选项、配料与克数合并。
