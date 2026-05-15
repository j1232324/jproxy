#!/usr/bin/env python3
"""
ModelScope Proxy — 启动向导

首次运行时的交互式初始化工具：
  1. 填写你的 ModelScope API Key（免费获取）
  2. 设置代理的 API Key（你的客户端用这个）
  3. 添加想要聚合的模型
  4. 保存配置并启动服务

用法:
  python3 start.py          # 首次初始化 + 启动
  python3 start.py --quick   # 跳过向导，直接启动（如果已配置）
"""

import os
import sys
import json
import subprocess

# ─── 路径 ─────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
PROXY_PATH = os.path.join(SCRIPT_DIR, "proxy.py")

# ─── 推荐模型库 ───────────────────────────────────────────

# 这些是 ModelScope 上常见的免费模型，供用户选择
RECOMMENDED_MODELS = [
    {
        "name": "Qwen/Qwen2.5-72B-Instruct",
        "default_priority": 1,
        "default_limit": 2000,
        "desc": "通义千问 72B — 最强，适合复杂任务",
    },
    {
        "name": "Qwen/Qwen2.5-32B-Instruct",
        "default_priority": 2,
        "default_limit": 2000,
        "desc": "通义千问 32B — 性价比之选",
    },
    {
        "name": "Qwen/Qwen2.5-14B-Instruct",
        "default_priority": 3,
        "default_limit": 2000,
        "desc": "通义千问 14B — 轻量快速",
    },
    {
        "name": "Qwen/Qwen2.5-7B-Instruct",
        "default_priority": 4,
        "default_limit": 2000,
        "desc": "通义千问 7B — 极速响应",
    },
    {
        "name": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "default_priority": 5,
        "default_limit": 2000,
        "desc": "代码专用 32B — 编程任务优选",
    },
    {
        "name": "Qwen/QwQ-32B-Preview",
        "default_priority": 6,
        "default_limit": 2000,
        "desc": "推理模型 32B — 复杂推理任务",
    },
    {
        "name": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "default_priority": 7,
        "default_limit": 2000,
        "desc": "DeepSeek R1 蒸馏版 32B",
    },
    {
        "name": "ZhipuAI/glm-4-9b-chat",
        "default_priority": 8,
        "default_limit": 2000,
        "desc": "智谱 GLM-4 9B",
    },
]

# ─── 工具函数 ─────────────────────────────────────────────


def color(text: str, code: str) -> str:
    """终端颜色包装。"""
    codes = {
        "green": "\033[92m",
        "cyan": "\033[96m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    }
    return f"{codes.get(code, '')}{text}{codes['reset']}"


def print_banner():
    banner = f"""
{color('╔══════════════════════════════════════════════════╗', 'cyan')}
{color('║', 'cyan')}       {color('ModelScope Proxy', 'bold')} — 多模型自动切换代理       {color('║', 'cyan')}
{color('║', 'cyan')}       {color('聚合多个模型免费配额，一键接入', 'dim')}           {color('║', 'cyan')}
{color('╚══════════════════════════════════════════════════╝', 'cyan')}
"""
    print(banner)


def print_step(step: int, total: int, title: str):
    print()
    print(color(f"─── [{step}/{total}] {title} ───", "bold"))


def input_with_default(prompt: str, default: str = "") -> str:
    """带默认值的输入。"""
    if default:
        full = f"{prompt} [{color(default, 'dim')}]: "
    else:
        full = f"{prompt}: "
    val = input(full).strip()
    if not val and default:
        return default
    return val


def load_config() -> dict:
    """加载现有配置（如果存在）。"""
    if os.path.exists(CONFIG_PATH):
        import yaml
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(config: dict):
    """保存配置到 YAML。"""
    import yaml
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    print(color(f"  ✓ 配置已保存: {CONFIG_PATH}", "green"))


def is_configured(config: dict) -> bool:
    """检查配置是否可用（有 ModelScope Key + 有模型）。"""
    key = config.get("modelscope", {}).get("api_token", "")
    models = config.get("models", [])
    return bool(key and models)


# ─── 向导步骤 ─────────────────────────────────────────────


def step_welcome():
    print_banner()
    print("欢迎！这个代理帮你把多个 ModelScope 免费模型的额度聚合在一起。")
    print("你只需要提供两样东西：")
    print("  ① 你的 ModelScope API Key（注册免费获取）")
    print("  ② 你想用哪些模型")
    print("然后你的客户端用一个固定的地址和密码就能调用。")
    print()


def step_modelscope_key(config: dict) -> str:
    """步骤 1: 填写 ModelScope API Key。"""
    print_step(1, 4, "填写你的 ModelScope API Key")

    current = config.get("modelscope", {}).get("api_token", "")
    if current:
        print(f"  当前: {color(current[:12] + '...' + current[-4:], 'dim')}")
        change = input("  是否更换？(y/N): ").strip().lower()
        if change != "y":
            return current

    print()
    print("  ModelScope 提供免费的 AI 模型 API，需要注册后获取密钥。")
    print(f"  获取地址: {color('https://modelscope.cn/my/myAccessKey', 'cyan')}")
    print("  注册完全免费，不需要付费。")
    print()

    while True:
        key = input("  你的 ModelScope API Key: ").strip()
        if key:
            return key
        print(color("  ✗ 不能为空，请重新输入（或按 Ctrl+C 退出）", "red"))


def step_proxy_key(config: dict) -> str:
    """步骤 2: 设置代理的 API Key。"""
    print_step(2, 4, "设置你的代理密码（API Key）")

    current = config.get("proxy", {}).get("api_key", "sk-your-proxy-key")
    default_key = "sk-your-proxy-key" if current == "sk-your-proxy-key" else current

    print("  这个 Key 是给你的客户/客户端用的。")
    print("  他们调用你的代理时，用这个 Key 做身份验证。")
    print("  随便设一个就行，比如 sk-my-代理-123")
    print()

    key = input_with_default("  设置 API Key", default_key)
    return key


def step_models(config: dict) -> list:
    """步骤 3: 添加模型。

    优先级自动递增：第一个添加的为 1，第二个为 2...
    """
    print_step(3, 4, "添加模型（优先级自动排列）")

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
    print("  选择你想用的模型，按添加顺序自动分配优先级（1, 2, 3...）")
    print(f"  {color('直接回车', 'bold')}完成添加")
    print()

    # 显示推荐列表
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

        # 序号 → 推荐模型
        if inp.isdigit():
            idx = int(inp) - 1
            if 0 <= idx < len(RECOMMENDED_MODELS):
                name = RECOMMENDED_MODELS[idx]["name"]
            else:
                print(color(f"  ✗ 序号无效，请输入 1-{len(RECOMMENDED_MODELS)}", "red"))
                continue
        else:
            # 直接输入模型名
            name = inp

        if not name:
            continue

        # 去重
        if any(m["name"] == name for m in models):
            print(color(f"  ✗ {name} 已在列表中", "yellow"))
            continue

        # 优先级自动递增
        priority = len(models) + 1
        daily_limit = 2000

        models.append({"name": name, "priority": priority, "daily_limit": daily_limit})
        print(color(f"    ✓ #{priority}  {name}", "green"))

    print()
    print(f"  已添加 {len(models)} 个模型（按添加顺序 = 优先级顺序）:")
    for i, m in enumerate(models, 1):
        print(f"    #{i}  {m['name']}")
    print(f"  注意: 每个模型的每日限额可能不同（几十~几千），以 ModelScope 实际为准。")
    print(f"  代理会自动根据 429 响应判断是否超额。")

    return models


def step_summary(config: dict, ms_key: str, proxy_key: str, models: list):
    """步骤 4: 确认并启动。"""
    print_step(4, 4, "确认配置")

    # 汇总显示
    print()
    print(f"  {color('ModelScope Key:', 'bold')}  {color(ms_key[:12] + '...' + ms_key[-4:], 'dim')}")
    print(f"  {color('代理密码:', 'bold')}       {proxy_key}")
    print(f"  {color('模型数量:', 'bold')}       {len(models)} 个")
    total_quota = sum(m["daily_limit"] for m in models)
    print(f"  {color('总配额/天:', 'bold')}   {total_quota} 次调用")
    print()

    # 保存配置
    config["proxy"] = config.get("proxy", {})
    config["proxy"]["host"] = config["proxy"].get("host", "0.0.0.0")
    config["proxy"]["port"] = config["proxy"].get("port", 8000)
    config["proxy"]["api_key"] = proxy_key

    config["modelscope"] = config.get("modelscope", {})
    config["modelscope"]["api_token"] = ms_key
    config["modelscope"]["base_url"] = config["modelscope"].get(
        "base_url", "https://api-inference.modelscope.cn"
    )

    config["models"] = models
    config["settings"] = config.get("settings", {})
    config["settings"]["max_retries"] = config["settings"].get("max_retries", 3)
    config["settings"]["model_review_interval_days"] = config["settings"].get(
        "model_review_interval_days", 30
    )

    save_config(config)

    # 写入审查标记
    review_file = os.path.join(SCRIPT_DIR, ".model_review")
    from datetime import date
    with open(review_file, "w") as f:
        f.write(date.today().isoformat())

    # 询问启动
    print()
    start_now = input(color("  是否现在启动代理服务器？(Y/n): ", "bold")).strip().lower()
    if start_now == "n":
        print()
        print("  配置已保存。随时可以启动:")
        print(f"    {color('python3 proxy.py', 'cyan')}")
        print()
        return False
    return True


# ─── 主流程 ───────────────────────────────────────────────


def main():
    # 检查依赖
    try:
        import yaml
    except ImportError:
        print(color("[!] 缺少依赖: pyyaml", "red"))
        print("    运行: pip install -r requirements.txt")
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser(description="ModelScope Proxy 启动向导")
    parser.add_argument(
        "--quick", action="store_true",
        help="跳过向导，直接启动（如果已配置）",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="重置配置，重新运行初始化向导",
    )
    args = parser.parse_args()

    config = load_config()

    # --quick: 如果已配置，直接启动
    if args.quick and is_configured(config):
        print(color("  ✓ 配置已就绪，正在启动...", "green"))
        _start_proxy()
        return

    # --reset: 清除现有配置并重新初始化
    if args.reset:
        print(color("  正在重置配置...", "yellow"))
        # 备份旧配置
        if os.path.exists(CONFIG_PATH):
            bak = CONFIG_PATH + ".bak"
            os.rename(CONFIG_PATH, bak)
            print(f"  旧配置已备份到: {bak}")
        config = {}
        # 清除配额状态
        state_file = os.path.join(SCRIPT_DIR, ".model_quota_state.json")
        if os.path.exists(state_file):
            os.remove(state_file)
        review_file = os.path.join(SCRIPT_DIR, ".model_review")
        if os.path.exists(review_file):
            os.remove(review_file)

    # 如果已有有效配置，问是否重新配置
    if is_configured(config) and not args.reset:
        print(color("  ✓ 检测到已有配置", "green"))
        reconfig = input("  是否重新配置？(y/N): ").strip().lower()
        if reconfig != "y":
            start = input(color("  是否启动代理？(Y/n): ", "bold")).strip().lower()
            if start != "n":
                _start_proxy()
            return

    # 运行向导
    step_welcome()
    ms_key = step_modelscope_key(config)
    proxy_key = step_proxy_key(config)
    models = step_models(config)
    should_start = step_summary(config, ms_key, proxy_key, models)

    if should_start:
        _start_proxy()


def _start_proxy():
    """启动代理服务器（在当前进程中）"""
    print()
    print(color("  🚀 启动 ModelScope Proxy...", "bold"))
    print()

    # 启动 uvicorn，传入 --config 参数
    os.chdir(SCRIPT_DIR)
    os.execvp(sys.executable, [
        sys.executable, PROXY_PATH,
    ])


if __name__ == "__main__":
    main()
