"""OpenAI 兼容 chat/completions 客户端（仅标准库，不新增依赖）。

配置有两处来源，**环境变量优先**，缺失的字段再取本地配置文件：

1. 环境变量

       WTE_LLM_BASE_URL  例如 https://your-gateway/v1
       WTE_LLM_API_KEY   访问令牌
       WTE_LLM_MODEL     模型名，例如 gpt-4o-mini / deepseek-chat
       WTE_LLM_TEMPERATURE  默认 0

2. 项目根目录的 `llm.local.json`（已被 .gitignore 忽略，不会进仓库）

       {"base_url": "...", "api_key": "...", "model": "...",
        "temperature": 0, "timeout": 75, "max_tokens": 4000}

   三个必填项 base_url / api_key / model，可选 temperature / timeout / max_tokens。
   也可以用 `WTE_LLM_CONFIG` 指定别的路径。

配置文件只是省去每次开终端都要 set 的麻烦；凭据仍然不写进被版本管理的文件。
未配置时 `Client.configured` 为 False，评测脚本会拒绝出正式结果，
只允许 `--provider stub` 的连通性冒烟，避免把占位数据当成实验数据。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# 项目根目录（scripts/ 的上一级），用于定位默认配置文件
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE_NAME = "llm.local.json"
CONFIG_PATH_ENV = "WTE_LLM_CONFIG"
# 只有这几个字段允许来自配置文件，避免配置里混入未知键
CONFIG_FIELDS = ("base_url", "api_key", "model", "temperature", "timeout", "max_tokens")


def config_path() -> Path | None:
    """返回实际生效的配置文件路径；没有则返回 None。"""
    explicit = os.environ.get(CONFIG_PATH_ENV, "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_absolute():
            return candidate if candidate.is_file() else None
        # 相对路径先按当前目录找，再按项目根找，避免换个工作目录就失效
        for base in (Path.cwd(), PROJECT_ROOT):
            if (base / candidate).is_file():
                return base / candidate
        return None
    candidate = PROJECT_ROOT / CONFIG_FILE_NAME
    return candidate if candidate.is_file() else None


def read_config(path: Path | None = None) -> dict:
    """读配置文件。文件缺失、JSON 损坏或字段类型不对都返回 {}，不抛异常。"""
    target = path or config_path()
    if target is None:
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in CONFIG_FIELDS if key in raw}


class LLMError(RuntimeError):
    """调用失败，带 HTTP 状态与响应片段，便于写进执行记录。"""


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def extract_json(text: str):
    """从模型回复里取出 JSON：容忍 ```json 围栏、前后解释性文字。"""
    if not text:
        raise LLMError("模型返回为空")
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text, index)
                return value
            except json.JSONDecodeError:
                continue
    raise LLMError(f"无法解析为 JSON：{text[:120]}")


def _as_float(text: str, default: float) -> float:
    """配置里写成字符串或不合法时退回默认值，不让拼错的配置把服务卡死。"""
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


@dataclass
class Client:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.0
    timeout: int = 75
    max_retries: int = 1
    max_tokens: int = 4000
    config_file: str = ""  # 本次配置来自哪个文件，空串表示只用了环境变量/默认值

    @classmethod
    def load(cls, prefix: str = "WTE_LLM") -> "Client":
        """环境变量优先，缺失字段回落到本地配置文件，最后用内置默认值。"""
        file_config = read_config()

        def pick(env_suffix: str, field: str) -> str:
            return (os.environ.get(f"{prefix}_{env_suffix}", "").strip()
                    or str(file_config.get(field, "") or "").strip())

        return cls(
            base_url=pick("BASE_URL", "base_url"),
            api_key=pick("API_KEY", "api_key"),
            model=pick("MODEL", "model"),
            temperature=_as_float(pick("TEMPERATURE", "temperature"), 0.0),
            timeout=int(_as_float(pick("TIMEOUT", "timeout"), 75)),
            max_tokens=int(_as_float(pick("MAX_TOKENS", "max_tokens"), 4000)),
            config_file=str(config_path() or ""),
        )

    @classmethod
    def from_env(cls, prefix: str = "WTE_LLM") -> "Client":
        """旧名保留：行为同 load()，环境变量优先、其次配置文件。"""
        return cls.load(prefix)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def masked(self) -> dict:
        """打印用：密钥只露首尾，避免日志或截图泄露。"""
        key = self.api_key
        shown = f"{key[:6]}…{key[-4:]}" if len(key) > 12 else ("(已设置)" if key else "(未设置)")
        return {
            "base_url": self.base_url or "(未设置)",
            "model": self.model or "(未设置)",
            "api_key": shown,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "config_file": self.config_file or "(未使用，仅环境变量/默认值)",
            "configured": self.configured,
        }

    def describe(self) -> dict:
        """写进执行记录的元信息（不含密钥）。"""
        return {"base_url": self.base_url, "model": self.model, "temperature": self.temperature}

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> dict:
        if not self.configured:
            raise LLMError(f"未配置模型：请设置 WTE_LLM_BASE_URL / WTE_LLM_API_KEY / WTE_LLM_MODEL，"
                           f"或在项目根目录新建 {CONFIG_FILE_NAME} 填写 base_url / api_key / model")
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                _endpoint(self.base_url), data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"},
            )
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                return {
                    "text": text,
                    "usage": data.get("usage", {}),
                    "model": data.get("model", self.model),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                }
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:300]
                # 部分网关不支持 response_format，去掉后重试一次。
                if error.code == 400 and "response_format" in payload:
                    payload.pop("response_format")
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    last = LLMError(f"HTTP 400（已去掉 response_format 重试）：{detail}")
                    continue
                if error.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    last = LLMError(f"HTTP {error.code}：{detail}")
                    continue
                raise LLMError(f"HTTP {error.code}：{detail}") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    last = LLMError(f"网络错误：{error}")
                    continue
                raise LLMError(f"网络错误：{error}") from None
        raise last or LLMError("调用失败")


class StubClient:
    """连通性冒烟用的假客户端：**不产生任何可用于报告的数据**。

    返回空参数，评测脚本据此把结果写成 results_stub.json，
    永远不会覆盖正式结果文件。
    """

    configured = True
    temperature = 0.0
    model = "stub"

    def describe(self) -> dict:
        return {"base_url": "(stub)", "model": "stub", "temperature": 0.0}

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> dict:
        payload = {
            "mode": "search", "ingredients": [], "seasonings": [], "tools": [],
            "difficulties": [1, 2, 3, 4, 5], "categories": None, "preparation_ids": [],
            "name_query": "", "unsupported_dimensions": [], "notes": "STUB",
        }
        return {"text": json.dumps(payload, ensure_ascii=False), "usage": {},
                "model": "stub", "elapsed_ms": 0}


def _main() -> int:
    """自检入口：`python -m scripts.llm_client` 看配置，加 `--ping` 真发一次请求。"""
    import sys

    client = Client.load()
    for key, value in client.masked().items():
        print(f"{key:12}: {value}")
    if "--ping" not in sys.argv:
        print("\n加 --ping 可实际发一次最小请求验证连通性。")
        return 0 if client.configured else 1
    if not client.configured:
        print("\n未配置，无法 ping。")
        return 1
    try:
        reply = client.chat("只回复两个字：你好", "ping", json_mode=False)
    except LLMError as error:
        print(f"\n连通性失败：{error}")
        return 1
    print(f"\n连通正常，{reply['elapsed_ms']} ms，回复：{reply['text'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
