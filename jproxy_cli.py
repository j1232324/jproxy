#!/usr/bin/env python3
"""
jproxy — 命令行入口

用法:
  jproxy                  # 有配置则启动，否则进入初始化向导
  jproxy init             # 强制进入初始化向导
  jproxy status           # 查看当前状态和配额
"""
import os
import sys

# 确保在项目目录下能正确导入
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

CWD = os.getcwd()
CONFIG_PATH = os.path.join(CWD, "config.yaml")


def cmd_init():
    """运行初始化向导。"""
    import start as start_mod

    # 让 start 模块在 CWD 读写配置
    start_mod.CONFIG_PATH = CONFIG_PATH
    start_mod.SCRIPT_DIR = CWD

    config = start_mod.load_config()
    start_mod.step_welcome()
    url, key, fetched = start_mod.step_upstream(config)
    proxy_key = start_mod.step_proxy_key(config)
    models = start_mod.step_models(config, fetched)
    start_mod.step_summary(config, url, key, proxy_key, models)


def cmd_status():
    """查看使用状态。"""
    if not os.path.exists(CONFIG_PATH):
        print("  config.yaml 不存在，请先运行 jproxy init")
        return

    from model_manager import ModelManager
    import yaml

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    mgr = ModelManager(config)
    summary = mgr.get_usage_summary()

    print()
    print(f"{'模型名称':50s} {'优先级':>8} {'已用':>6} {'限额':>6} {'状态'}")
    print("-" * 80)
    for s in summary:
        limit_str = str(s['daily_limit']) if s['daily_limit'] else "不限"
        print(f"{s['name']:50s} {s['priority']:>8d} {s['used_today']:>6d} {limit_str:>6} {s['status']}")
    print()
    print(f"今日总调用: {sum(s['used_today'] for s in summary)} 次")


def cmd_run():
    """启动代理服务。"""
    os.chdir(CWD)
    from proxy import create_app
    import uvicorn
    import yaml

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    host = config.get("proxy", {}).get("host", "0.0.0.0")
    port = config.get("proxy", {}).get("port", 8000)
    api_key = config.get("proxy", {}).get("api_key", "sk-your-proxy-key")

    app = create_app(config)

    print(f"🚀 jproxy 已启动")
    print(f"   📡 监听: http://{host}:{port}")
    print(f"   🔑 代理 Key: {api_key}")
    print(f"   📊 已配置 {len(config.get('models', []))} 个模型")
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "init":
            cmd_init()
            return
        elif cmd == "status":
            cmd_status()
            return
        elif cmd in ("-h", "--help"):
            print(__doc__)
            return

    # 有配置直接启动，否则进向导
    if os.path.exists(CONFIG_PATH):
        cmd_run()
    else:
        print("  首次使用，进入初始化向导...\n")
        cmd_init()


if __name__ == "__main__":
    main()
