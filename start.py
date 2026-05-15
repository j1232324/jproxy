#!/usr/bin/env python3
"""
jproxy — 启动向导

首次运行时的交互式初始化工具：
  1. 填写上游 API Key 和地址
  2. 设置代理的 API Key
  3. 选择要聚合的模型
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

# ─── 推荐模型库（示例，用户可自定义） ─────────────────────

RECOMMENDED_MODELS = [
    {
        "name": "Qwen/Qwen2.5-72B-Instruct",
        "default_priority": 1,
        "desc": "通义千问 72B — 最强，适合复杂任务",
    },
    {
        "name": "Qwen/Qwen2.5-32B-Instruct",
        "default_priority": 2,
        "desc": "通义千问 32B — 性价比之选",
    },
    {
        "name": "Qwen/Qwen2.5-14B-Instruct",
        "default_priority": 3,
        "desc": "通义千问 14B — 轻量快速",
    },
    {
        "name": "Qwen/Qwen2.5-7B-Instruct",
        "default_priority": 4,
        "desc": "通义千问 7B — 极速响应",
    },
    {
        "name": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "default_priority": 5,
        "desc": "代码专用 32B",
    },
    {
        "name": "Qwen/QwQ-32B-Preview",
        "default_priority": 6,
        "desc": "推理模型 32B",
    },
    {
        "name": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "default_priority": 7,
        "desc": "DeepSeek R1 蒸馏版 32B",
    },
    {
        "name": "ZhipuAI/glm-4-9b-chat",
        "default_priority": 8,
        "desc": "智谱 GLM-4 9B",
    },
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


# ─── 向导步骤 ─────────────────────────────────────────────


def step_welcome():
    print_banner()
    print("欢迎！这个代理让你在多个模型之间自动切换，")
    print("遇到频率限制时自动降级到下一个可用模型。")
    print()
    print("配置三样东西就可以开始：")
    print("  ① 上游 API 地址和 Key")
    print("  ② 代理的密码（你的客户端用）")
    print("  ③ 要用的模型列表")
    print()


def step_upstream(config: dict) -> tuple:
    """步骤 1: 配置上游 API 地址和 Key。"""
    print_step(1, 4, "配置上游 API")

    current_cfg = config.get("upstream", {})
    default_url = current_cfg.get("base_url", "https://api.openai.com/v1")
    default_key = current_cfg.get("api_key", "")

    if default_key:
        masked = default_key[:8] + "..." + default_key[-4:]
        print(f"  当前 Key: {color(masked, 'dim')}")
        change = input("  是否更换？(y/N): ").strip().lower()
        if change != "y" and change != "yes":
            return default_url, default_key

    print()
    url = input_with_default("  上游 API 地址", default_url)

    while True:
        key = input("  上游 API Key: ").strip()
        if key:
            break
        print(color("  ✗ 不能为空", "red"))

    return url, key


def step_proxy_key(config: dict) -> str:
    """步骤 2: 设置代理的 API Key。"""
    print_step(2, 4, "设置代理密码")

    current = config.get("proxy", {}).get("api_key", "sk-your-proxy-key")
    default_key = "sk-your-proxy-key" if current == "sk-your-proxy-key" else current

    print("  客户端调用代理时需要这个 Key，随便设一个。")
    print()

    key = input_with_default("  代理 API Key", default_key)
    return key


def step_models(config: dict) -> list:
    """步骤 3: 添加模型（优先级自动排列）。"""
    print_step(3, 4, "添加模型")

    existing = config.get("models", [])
    if existing:
        print(f"  当前已有 {len(existing)} 个模型:")
        for m in existing:
            print(f"    · {m['name']}  (优先级 {m.get('priority','?')})")
        modify = input("  是否重新配置？(y/N): ").strip().lower()
        if modify != "y":
            return existing

    models = []
    print()
    print("  按添加顺序自动分配优先级（1, 2, 3...）")
    print(f"  {color('直接回车', 'bold')}完成添加")
    print()

    print(f"  {color('推荐模型（输入序号添加）:', 'bold')}")
    for i, m in enumerate(RECOMMENDED_MODELS, 1):
        print(f"    {i:2d}. {color(m['name'], 'cyan')}")
        print(f"        {m['desc']}")
    print()

    while True:
        inp = input("  > ").strip()
        if not inp:
            if not models:
                print(color("  ✗ 至少需要添加一个模型", "red"))
                continue
            break

        if inp.isdigit():
            idx = int(inp) - 1
            if 0 <= idx < len(RECOMMENDED_MODELS):
                name = RECOMMENDED_MODELS[idx]["name"]
            else:
                print(color(f"  ✗ 序号无效，请输入 1-{len(RECOMMENDED_MODELS)}", "red"))
                continue
        else:
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
    print(f"  已添加 {len(models)} 个模型:")
    for i, m in enumerate(models, 1):
        print(f"    #{i}  {m['name']}")

    return models


def step_summary(config: dict, upstream_url: str, upstream_key: str, proxy_key: str, models: list):
    """步骤 4: 确认并启动。"""
    print_step(4, 4, "确认配置")

    print()
    print(f"  {color('上游地址:', 'bold')}    {upstream_url}")
    print(f"  {color('上游 Key:', 'bold')}    {color(upstream_key[:10] + '...', 'dim')}")
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
        sf = os.path.join(SCRIPT_DIR, ".model_quota_state.json")
        if os.path.exists(sf):
            os.remove(sf)
        rf = os.path.join(SCRIPT_DIR, ".model_review")
        if os.path.exists(rf):
            os.remove(rf)

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

    step_welcome()
    url, key = step_upstream(config)
    proxy_key = step_proxy_key(config)
    models = step_models(config)
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
