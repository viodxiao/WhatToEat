# Windows 运行说明

此包沿用原项目的 Conda `cook` 环境、Python 3.13，以及原 `requirements.txt` 中的全部依赖版本。自动新建环境时指定原文记录的 Python 3.13.18；已有 Python 3.13 的 `cook` 环境直接复用。不是独立 EXE，需要先安装 Miniconda 或 Anaconda。

## 目录结构

把 `WhatToEat_windows.zip` 解压到自己的 `WhatToEat` 目录。压缩包根目录直接是以下内容，与最初上传的压缩包相同，不再套一层 `project` 或 `WhatToEat`：

```text
WhatToEat/
  README.md
  WINDOWS.md
  requirements.txt
  requirements-dev.txt
  install_windows.bat
  start_windows.bat
  verify_windows.bat
  scripts/
    frontend/
    main.py
    ...
  recipe/
  ontology/
  stage2/
  stage3/
  validation/
```

保留原项目目录及食谱中文文件名。源码包不包含 Linux `.venv`、缓存、Git 历史或 IDE 的机器专用配置。不要把 Linux 虚拟环境复制到 Windows。

## 安装与启动

打开 **Anaconda Prompt / Miniconda Prompt**，进入解压目录：

```bat
cd /d "D:\你的目录\WhatToEat"
install_windows.bat
verify_windows.bat
start_windows.bat
```

安装脚本先检查 `cook`，不存在时创建，再安装原运行依赖及用于 API 测试的 httpx。已有环境若不是 Python 3.13，会报错停止，不自动更改 Python。脚本会切换至自身所在目录，支持目录含空格，并启用 UTF-8。

服务启动后访问 http://127.0.0.1:8000/ 。Ctrl+C 停止服务。无需 Node.js、前端编译或 GPU。

也可以继续使用原来的命令：

```bat
conda create -n cook python=3.13.18 pip -y
conda run -n cook python -s -m pip install -r requirements-dev.txt
conda run -n cook --no-capture-output python -s -X utf8 -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000
```

已有 `cook` 时跳过创建命令。`requirements-dev.txt` 引用原 `requirements.txt`，只额外加入测试依赖。`requirements-tested.txt` 是前一次 Linux/Python 3.12 验证的快照，不是本次 Windows 安装入口。

## 自然语言功能配置

手动筛选菜谱不需要模型接口。自然语言功能需要在启动服务的同一个终端中设置以下环境变量，用自己的实际配置替换占位值：

```bat
set "WTE_LLM_BASE_URL=https://your-gateway/v1"
set "WTE_LLM_MODEL=your-model-name"
set "WTE_LLM_API_KEY=your-api-key"
start_windows.bat
```

PowerShell 对应写法为 `$env:WTE_LLM_BASE_URL = "..."`，其他两个变量同理，然后执行 `./start_windows.bat`。密钥不需要写进项目文件。

无模型配置时页面仍能打开，调用自然语言入口会提示配置缺失。`verify_windows.bat` 使用测试替身，不消耗模型调用。

## 验证范围

本次已检查路径使用方式、UTF-8、压缩包的 Windows 文件名兼容性和目录结构；应用测试在 Linux 上通过。当前机器不是 Windows，没有把 Windows 批处理执行或 Windows/Python 3.13 安装标记为已实测。请在目标 Windows 上运行 `verify_windows.bat` 完成最终验收。依赖安装需要包源中提供原锁定版本，Conda 创建需要能访问相应包源。
