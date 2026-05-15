#!/usr/bin/env python3
"""
jproxy — 启动向导

首次运行时的交互式初始化工具：
  1. 填写上游 API Key 和地址（自动获取可用模型）
  2. 设置代理的 API Key
  3. 选择要用的模型
  4. 保存配置并启动服务

用法:
  python3 start.py          # 首次初始化 + 启动
  python3 start.py --quick   # 跳过向导，直接启动
  python3 start.py --reset   # 重置配置
"""

import os
import sys
from datetime import date

import yaml


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
PROXY_PATH = os.path.join(SCRIPT_DIR, "proxy.py")

# ─── 默认推荐模型（上游获取失败时的备选） ────────────────

FALLBACK_MODELS = [
    {"name": "Qwen/Qwen2.5-72B-Instruct", "desc": "通义千问 72B"},
    {"name": "Qwen/Qwen2.5-32B-Instruct", "desc": "通义千问 32B"},
    {"name": "Qwen/Qwen2.5-14B-Instruct", "desc": "通义千问 14B"},
    {"name": "Qwen/Qwen2.5-7B-Instruct", "desc": "通义千问 7B"},
    {"name": "Qwen/Qwen2.5-Coder-32B-Instruct", "desc": "代码专用 32B"},
    {"name": "Qwen/QwQ-32B-Preview", "desc": "推理模型 32B"},
    {"name": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", "desc": "DeepSeek R1 蒸馏版"},
    {"name": "ZhipuAI/glm-4-9b-chat", "desc": "智谱 GLM-4 9B"},
]

# ─── 工具函数 ─────────────────────────────────────────────


def color(text: str, code: str) -> str:
    codes = {
        "green": "\033[92m", "cyan": "\033[96m",
        "yellow": "\033[93m", "red": "\033[91m",
        "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m",
    }
    return f"{codes.get(code, '')}{text}{codes['reset']}"


def print_banner():
    banner = f"""
{color('╔══════════════════════════════════════════════════╗', 'cyan')}
{color('║', 'cyan')}       {color('jproxy', 'bold')} — 通用 API 代理，自动切换模型        {color('║', 'cyan')}
{color('║', 'cyan')}       {color('聚合多个模型，避开单个的频率限制', 'dim')}           {color('║', 'cyan')}
{color('╚══════════════════════════════════════════════════╝', 'cyan')}
"""
    print(banner)


def print_step(step: int, total: int, title: str):
    print()
    print(color(f"─── [{step}/{total}] {title} ───", "bold"))


def input_with_default(prompt: str, default: str = "") -> str:
    if default:
        full = f"{prompt} [{color(default, 'dim')}]: "
    else:
        full = f"{prompt}: "
    val = input(full).strip()
    if not val and default:
        return default
    return val


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    print(color(f"  ✓ 配置已保存: {CONFIG_PATH}", "green"))


def is_configured(config: dict) -> bool:
    key = config.get("upstream", {}).get("api_key", "")
    models = config.get("models", [])
    return bool(key and models)


# ─── 获取上游模型列表 ─────────────────────────────────────


def try_fetch_models(base_url: str, api_key: str):
    """尝试从上游 API 获取可用模型列表。

    调用 GET /v1/models，返回模型名列表。
    失败时返回 None。
    """
    import urllib.request
    import json

    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            models = data.get("data", [])
            names = [m["id"] for m in models if isinstance(m, dict) and "id" in m]
            if names:
                return names
    except Exception:
        pass
    return None


# ─── 向导步骤 ─────────────────────────────────────────────


def step_welcome():
    print_banner()
    print("欢迎！这个代理让你在多个模型之间自动切换，")
    print("遇到频率限制时自动降级到下一个可用模型。")
    print()
    print("配置三样东西就可以开始：")
    print("  ① 上游 API 地址和 Key（自动拉取模型列表）")
    print("  ② 代理的密码（你的客户端用）")
    print("  ③ 选择要用的模型")
    print()


def step_upstream(config: dict) -> tuple:
    """步骤 1: 配置上游 API + 自动获取模型列表。"""
    print_step(1, 4, "配置上游 API（自动获取可用模型）")

    current_cfg = config.get("upstream", {})
    default_url = current_cfg.get("base_url", "https://api.openai.com/v1")
    default_key = current_cfg.get("api_key", "")

    if default_key:
        masked = default_key[:8] + "..." + default_key[-4:]
        print(f"  当前 Key: {color(masked, 'dim')}")
        change = input("  是否更换？(y/N): ").strip().lower()
        if change != "y" and change != "yes":
            return default_url, default_key, None

    print()
    url = input_with_default("  上游 API 地址", default_url)

    while True:
        key = input("  上游 API Key: ").strip()
        if key:
            break
        print(color("  ✗ 不能为空", "red"))

    # 尝试自动获取模型列表
    print(f"  {color('⟳ 正在拉取可用模型列表...', 'dim')}", end="")
    fetched = try_fetch_models(url, key)
    if fetched:
        print(color(" ✓", "green"))
        print(f"    获取到 {len(fetched)} 个模型")
    else:
        print(color(" 无法获取（将使用推荐列表）", "yellow"))

    return url, key, fetched


def step_proxy_key(config: dict) -> str:
    """步骤 2: 设置代理的 API Key。"""
    print_step(2, 4, "设置代理密码")

    current = config.get("proxy", {}).get("api_key", "sk-your-proxy-key")
    default_key = "sk-your-proxy-key" if current == "sk-your-proxy-key" else current

    print("  客户端调用代理时需要这个 Key，随便设一个。")
    print()

    key = input_with_default("  代理 API Key", default_key)
    return key


def step_models(config: dict, fetched_models: list) -> list:
    """步骤 3: 选择模型（优先级自动排列）。"""
    print_step(3, 4, "选择模型")

    existing = config.get("models", [])
    if existing:
        print(f"  当前已有 {len(existing)} 个模型:")
        for m in existing:
            print(f"    · {m['name']}  (优先级 {m.get('priority','?')})")
        modify = input("  是否重新配置？(y/N): ").strip().lower()
        if modify != "y":
            return existing

    # 构建候选列表：API 获取的 + 备选推荐
    candidates = []
    seen = set()

    if fetched_models:
        for name in fetched_models:
            if name not in seen:
                candidates.append({"name": name, "desc": ""})
                seen.add(name)

    for m in FALLBACK_MODELS:
        if m["name"] not in seen:
            candidates.append(m)
            seen.add(m["name"])

    models = []
    print()
    print("  按添加顺序自动分配优先级（1, 2, 3...）")
    print(f"  输入序号选择模型，或直接输入 {color('模型名', 'cyan')} 自定义")
    print(f"  {color('直接回车', 'bold')}完成添加")
    print()

    # 显示候选列表（最多 30 个）
    MAX_SHOW = 30
    print(f"  {color('可用模型:', 'bold')}")
    for i, m in enumerate(candidates[:MAX_SHOW], 1):
        rest = ""
        if i == 1 and fetched_models:
            rest = " (来自上游 API)"
        name_display = m["name"]
        if len(name_display) > 60:
            name_display = name_display[:57] + "..."
        print(f"    {i:2d}. {color(name_display, 'cyan')}{color(rest, 'dim')}")
    if len(candidates) > MAX_SHOW:
        print(f"    ... 还有 {len(candidates) - MAX_SHOW} 个（可直接输入模型名添加）")
    print()

    while True:
        inp = input("  > ").strip()

        if not inp:
            if not models:
                print(color("  ✗ 至少需要添加一个模型", "red"))
                continue
            break

        # 序号选择
        if inp.isdigit():
            idx = int(inp) - 1
            if 0 <= idx < len(candidates):
                name = candidates[idx]["name"]
            else:
                print(color(f"  ✗ 序号无效，范围 1-{len(candidates)}", "red"))
                continue
        else:
            # 自定义模型名
            name = inp

        if not name:
            continue
        if any(m["name"] == name for m in models):
            print(color(f"  ✗ {name} 已在列表中", "yellow"))
            continue

        priority = len(models) + 1
        models.append({"name": name, "priority": priority})
        print(color(f"    ✓ #{priority}  {name}", "green"))

    print()
    print(f"  已选择 {len(models)} 个模型:")
    for i, m in enumerate(models, 1):
        print(f"    #{i}  {m['name']}")

    return models


def step_summary(config: dict, upstream_url: str, upstream_key: str, proxy_key: str, models: list):
    """步骤 4: 确认并启动。"""
    print_step(4, 4, "确认配置")

    print()
    print(f"  {color('上游地址:', 'bold')}    {upstream_url}")
    print(f"  {color('代理密码:', 'bold')}     {proxy_key}")
    print(f"  {color('模型数量:', 'bold')}     {len(models)} 个")
    print()

    config["proxy"] = config.get("proxy", {})
    config["proxy"]["host"] = config["proxy"].get("host", "0.0.0.0")
    config["proxy"]["port"] = config["proxy"].get("port", 8000)
    config["proxy"]["api_key"] = proxy_key

    config["upstream"] = {
        "base_url": upstream_url,
        "api_key": upstream_key,
    }

    config["models"] = models
    config["settings"] = config.get("settings", {
        "max_retries": 3,
        "model_review_interval_days": 30,
    })

    save_config(config)

    print()
    start_now = input(color("  是否现在启动？(Y/n): ", "bold")).strip().lower()
    if start_now == "n":
        print()
        print("  随时可以启动:")
        print(f"    {color('python3 proxy.py', 'cyan')}")
        return False
    return True


# ─── 主流程 ───────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="jproxy 启动向导")
    parser.add_argument("--quick", action="store_true", help="跳过向导直接启动")
    parser.add_argument("--reset", action="store_true", help="重置配置")
    args = parser.parse_args()

    config = load_config()

    if args.reset:
        print(color("  正在重置配置...", "yellow"))
        if os.path.exists(CONFIG_PATH):
            bak = CONFIG_PATH + ".bak"
            os.rename(CONFIG_PATH, bak)
            print(f"  旧配置已备份: {bak}")
        config = {}
        for f in [".model_quota_state.json", ".model_review"]:
            p = os.path.join(SCRIPT_DIR, f)
            if os.path.exists(p):
                os.remove(p)

    if args.quick and is_configured(config):
        print(color("  ✓ 配置就绪，启动...", "green"))
        _start_proxy()
        return

    if is_configured(config) and not args.reset:
        print(color("  ✓ 检测到已有配置", "green"))
        reconfig = input("  是否重新配置？(y/N): ").strip().lower()
        if reconfig != "y":
            s = input(color("  是否启动？(Y/n): ", "bold")).strip().lower()
            if s != "n":
                _start_proxy()
            return

    # ── 完整向导 ──
    step_welcome()
    url, key, fetched = step_upstream(config)
    proxy_key = step_proxy_key(config)
    models = step_models(config, fetched)
    should_start = step_summary(config, url, key, proxy_key, models)

    if should_start:
        _start_proxy()


def _start_proxy():
    print()
    print(color("  🚀 启动 jproxy...", "bold"))
    print()
    os.chdir(SCRIPT_DIR)
    os.execvp(sys.executable, [sys.executable, PROXY_PATH])


if __name__ == "__main__":
    main()
