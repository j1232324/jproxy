#!/usr/bin/env python3
"""
jproxy — 通用 API 代理，自动切换上游模型

核心功能:
  1. 提供一个固定的 API 地址和 Key，用户零感知
  2. 自动按优先级选择有可用配额的模型
  3. 遇到 429 配额耗尽自动降级到下一个优先级的模型
  4. 每日配额自动重置，持久化到磁盘
  5. 定期提醒用户更新模型列表

使用方式:
  python3 proxy.py                    # 启动服务
  python3 proxy.py --review-models    # 交互式更新模型列表
  python3 proxy.py --show-usage       # 查看当前配额使用情况
  python3 proxy.py --port 8080        # 指定端口启动
"""

import argparse
import json
import os
import sys
from datetime import date
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import yaml

from model_manager import ModelManager
from translator import translate_request, translate_response

# ─── 常量 ─────────────────────────────────────────────────

# 默认配置文件路径：相对于脚本所在目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(_SCRIPT_DIR, "config.yaml")

# ─── 配置加载 ─────────────────────────────────────────────


def load_config(path: str) -> dict:
    """加载 YAML 配置文件。文件不存在则创建默认配置后退出。"""
    abs_path = os.path.abspath(path)

    if not os.path.exists(abs_path):
        print(f"[!] 配置文件不存在: {abs_path}")
        print(f"    正在创建默认配置文件 ...")
        _create_default_config(abs_path)
        print(f"    ✓ 已创建: {abs_path}")
        print(f"    [!] 请编辑该文件，填入你的 上游 API Key 和模型列表后重新启动。")
        sys.exit(1)

    with open(abs_path, "r") as f:
        config = yaml.safe_load(f)

    # 校验必填项
    token = config.get("upstream", {}).get("api_key", "")
    if not token:
        print("[!] upstream.api_key 未设置！")
        print("    请到上游服务商网站获取你的 API Key")
        print("    然后编辑 config.yaml 填入。")
        sys.exit(1)

    models = config.get("models", [])
    if not models:
        print("[!] 未配置任何模型！")
        print("    请至少添加一个模型到 config.yaml 的 models 列表中。")
        print("    示例:")
        print("      models:")
        print('        - name: "Qwen/Qwen2.5-72B-Instruct"')
        print("          priority: 1")
        print("          daily_limit: 2000")
        print()
        print("    运行 python3 proxy.py --review-models 交互式添加")
        sys.exit(1)

    return config


def _create_default_config(path: str):
    """生成默认配置文件。"""
    default = {
        "proxy": {
            "host": "0.0.0.0",
            "port": 8000,
            "api_key": "sk-your-proxy-key",
        },
        "upstream": {
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
        },
        "models": [],
        "settings": {
            "max_retries": 3,
            "model_review_interval_days": 30,
        },
    }
    with open(path, "w") as f:
        yaml.dump(default, f, default_flow_style=False, allow_unicode=True)


# ─── 交互式模型列表编辑 ────────────────────────────────


def review_models_interactive(config_path: str):
    """交互式审查/更新模型列表。"""
    abs_path = os.path.abspath(config_path)
    if not os.path.exists(abs_path):
        print(f"[!] 配置文件不存在: {abs_path}")
        print("    请先创建配置文件。")
        return

    with open(abs_path, "r") as f:
        config = yaml.safe_load(f)

    models = config.get("models", [])

    print("\n" + "=" * 60)
    print("  📋 模型列表审查 / Model List Review")
    print("=" * 60)

    # 显示当前列表
    if models:
        print("\n当前模型 / Current models:")
        print(f"  {'优先级':>8}  {'每日限额':>10}  {'模型名称'}")
        print(f"  {'───────':>8}  {'──────────':>10}  {'────────'}")
        for m in sorted(models, key=lambda x: x.get("priority", 999)):
            print(f"  {m.get('priority', '-'):>8}  {m.get('daily_limit', 2000):>10}  {m['name']}")
    else:
        print("\n  (模型列表为空)")

    # ── 添加模型 ──
    print("\n--- 添加模型 (输入模型名称:优先级:每日限额，每行一个，空行结束) ---")
    print("  示例: Qwen/Qwen2.5-72B-Instruct:1:2000")
    while True:
        line = input("  > ").strip()
        if not line:
            break
        parts = line.split(":")
        if len(parts) == 3:
            name = parts[0].strip()
            try:
                priority = int(parts[1].strip())
                daily_limit = int(parts[2].strip())
            except ValueError:
                print("    ✗ 优先级和每日限额必须是数字")
                continue

            # 去重: 同模型名则更新
            found = False
            for m in models:
                if m["name"] == name:
                    m["priority"] = priority
                    m["daily_limit"] = daily_limit
                    found = True
                    print(f"    ✓ 已更新: {name}")
                    break
            if not found:
                models.append({
                    "name": name,
                    "priority": priority,
                    "daily_limit": daily_limit,
                })
                print(f"    ✓ 已添加: {name}")
        else:
            print("    ✗ 格式错误，请使用 name:priority:daily_limit 格式")

    # ── 删除模型 ──
    if models:
        print("\n--- 删除模型 (输入要删除的模型名，每行一个，空行结束) ---")
        while True:
            line = input("  > ").strip()
            if not line:
                break
            before = len(models)
            models = [m for m in models if m["name"] != line]
            if len(models) < before:
                print(f"    ✓ 已删除: {line}")
            else:
                print(f"    ✗ 未找到: {line}")

    # 保存
    config["models"] = models
    with open(abs_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"\n✓ 配置已保存到 {abs_path}")
    print(f"  共 {len(models)} 个模型")

    # 更新审查标记
    mgr = ModelManager(config)
    mgr.mark_reviewed()
    print("  ✓ 已标记为已审查")


# ─── FastAPI 应用 ─────────────────────────────────────────


def create_app(config: dict) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(title="jproxy", version="1.0.0")
    manager = ModelManager(config)
    upstream_cfg = config["upstream"]
    proxy_cfg = config["proxy"]
    settings = config["settings"]

    # ── 认证中间件 ──
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # 以下路径不需要认证
        public_paths = {"/health", "/", "/docs", "/openapi.json"}
        if request.url.path in public_paths:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {proxy_cfg['api_key']}"

        if auth != expected:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "无效的 API Key。请使用 Authorization: Bearer <你的代理 Key>",
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                    }
                },
                headers={"Content-Type": "application/json"},
            )

        return await call_next(request)

    # ── 路由 ──

    @app.get("/health")
    async def health():
        """健康检查。"""
        return {"status": "ok", "timestamp": date.today().isoformat()}

    @app.get("/v1/models")
    async def list_models():
        """返回已配置的模型列表及其配额使用情况。"""
        summary = manager.get_usage_summary()
        data = []
        for s in summary:
            data.append({
                "id": s["name"],
                "object": "model",
                "created": 0,
                "owned_by": "upstream",
                "available": s["available"],
                "daily_usage": {
                    "used": s["used_today"],
                    "limit": s["daily_limit"] or "unknown",
                },
            })
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat_completions(raw_request: Request):
        """核心代理端点：接收 OpenAI 格式的请求，自动选择模型转发。"""
        try:
            body = await raw_request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "无效的 JSON 请求体", "code": "invalid_json"}},
            )

        stream = body.get("stream", False)
        max_retries = settings.get("max_retries", 3)

        # 重试循环：遇到 429 自动切换到下一个优先级的模型
        for attempt in range(max_retries + 1):
            model_name = manager.select_model()
            if model_name is None:
                return _all_exhausted_response(manager)

            # 转换请求格式 (其实就是替换 model 字段)
            ms_request = translate_request(body, model_name)

            headers = {
                "Authorization": f"Bearer {upstream_cfg['api_key']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            if stream:
                # 流式响应 — 交给独立的处理函数
                return await _handle_streaming(
                    ms_request, headers, model_name,
                    upstream_cfg["base_url"], manager,
                )
            else:
                # 非流式响应
                result = await _handle_non_streaming(
                    ms_request, headers, model_name,
                    upstream_cfg["base_url"], manager,
                )
                if result is not None:
                    return result
                # result 为 None 表示遇到了 429，继续下一个模型

        # 所有模型都尝试过了
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": "所有可用模型均已尝试完毕，仍无法完成请求。",
                    "type": "rate_limit_error",
                    "code": "retries_exhausted",
                }
            },
            headers={"Retry-After": "3600"},
        )

    return app


# ─── 请求处理函数 ────────────────────────────────────────


async def _handle_non_streaming(
    request_body: dict,
    headers: dict,
    model_name: str,
    base_url: str,
    manager: ModelManager,
) -> Optional[JSONResponse]:
    """处理非流式请求。遇到 429 返回 None 让上层重试。"""
    url = f"{base_url}/v1/chat/completions"

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(url, json=request_body, headers=headers)

            # 配额耗尽 — 标记后返回 None 触发重试
            if response.status_code == 429:
                manager.mark_exhausted(model_name)
                print(f"  [↻] {model_name} 配额耗尽，尝试下一个模型...")
                return None

            # 其他错误 — 直接返回
            if response.status_code != 200:
                error_body = _extract_error(response)
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": error_body},
                )

            # 成功
            manager.record_usage(model_name)
            result = translate_response(response.json())
            return JSONResponse(content=result)

        except httpx.TimeoutException:
            return JSONResponse(
                status_code=504,
                content={"error": {"message": "上游API超时", "code": "timeout"}},
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": f"连接上游失败: {str(e)}",
                        "code": "connection_error",
                    }
                },
            )


async def _handle_streaming(
    request_body: dict,
    headers: dict,
    model_name: str,
    base_url: str,
    manager: ModelManager,
) -> StreamingResponse:
    """处理流式请求。

    流式场景的特殊考虑:
    - 在 generate() 内部做重试，只要还没 yield 任何数据，
      客户端就收不到响应头，可以安全切换模型
    - 但一旦开始流数据，如果半路 429 就无法优雅降级了
      (实际上 429 在建立连接时就会返回，不会半路出现)
    """
    url = f"{base_url}/v1/chat/completions"
    max_retries = manager.settings.get("max_retries", 3)

    async def generate():
        for attempt in range(max_retries + 1):
            # 每次重试重新选择模型（因为前面的可能已被标记耗尽）
            current_model = manager.select_model()
            if current_model is None:
                yield _sse_error("所有模型配额已耗尽")
                yield "data: [DONE]\n\n"
                return

            # 更新请求中的 model 字段
            body = translate_request(request_body, current_model)

            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST", url, json=body, headers=headers
                    ) as response:
                        # 配额耗尽 — 标记后重试
                        if response.status_code == 429:
                            manager.mark_exhausted(current_model)
                            print(f"  [↻] {current_model} 配额耗尽，尝试下一个...")
                            continue

                        # 其他 HTTP 错误
                        if response.status_code != 200:
                            error_text = await response.aread()
                            yield _sse_error(
                                f"上游返回HTTP {response.status_code}"
                            )
                            yield "data: [DONE]\n\n"
                            return

                        # 成功建立流式连接
                        manager.record_usage(current_model)
                        async for chunk in response.aiter_bytes():
                            yield chunk
                        return  # 流结束

                except httpx.RequestError as e:
                    yield _sse_error(f"连接错误: {str(e)}")
                    yield "data: [DONE]\n\n"
                    return

        # 所有重试耗尽
        yield _sse_error("所有模型重试均已耗尽")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── 辅助函数 ─────────────────────────────────────────────


def _all_exhausted_response(manager: ModelManager) -> JSONResponse:
    """所有模型配额耗尽时的响应。"""
    summary = manager.get_usage_summary()
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "message": "所有模型的每日配额均已耗尽。请明天再试，或添加更多模型。",
                "type": "rate_limit_error",
                "code": "all_models_exhausted",
                "usage": summary,
            }
        },
        headers={"Retry-After": str(24 * 3600)},
    )


def _extract_error(response: httpx.Response) -> dict:
    """从失败的 HTTP 响应中提取错误信息。"""
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return {"message": response.text, "status_code": response.status_code}


def _sse_error(message: str) -> bytes:
    """生成一个 SSE 格式的错误消息。"""
    data = json.dumps({"error": message})
    return f"data: {data}\n\n".encode("utf-8")


# ─── CLI 入口 ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="jproxy — 多模型自动切换代理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 proxy.py                              # 启动服务
  python3 proxy.py --port 8080                  # 指定端口
  python3 proxy.py --review-models              # 交互式编辑模型列表
  python3 proxy.py --show-usage                 # 查看配额使用情况
  python3 proxy.py --config /path/to/config.yaml # 指定配置文件
        """,
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH,
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--review-models", action="store_true",
        help="交互式审查/更新模型列表",
    )
    parser.add_argument(
        "--host", type=str,
        help="覆盖配置文件中的监听地址",
    )
    parser.add_argument(
        "--port", type=int,
        help="覆盖配置文件中的监听端口",
    )
    parser.add_argument(
        "--show-usage", action="store_true",
        help="查看当前配额使用情况并退出",
    )

    args = parser.parse_args()
    config_path = os.path.abspath(args.config)

    # ── 交互式模型列表编辑 ──
    if args.review_models:
        review_models_interactive(config_path)
        return

    # ── 加载配置 ──
    config = load_config(config_path)

    # CLI 覆盖配置
    if args.host:
        config["proxy"]["host"] = args.host
    if args.port:
        config["proxy"]["port"] = args.port

    # ── 查看配额使用 ──
    if args.show_usage:
        mgr = ModelManager(config)
        summary = mgr.get_usage_summary()
        print()
        print(f"{'模型名称':50s} {'优先级':>8} {'已用':>6} {'限额':>6} {'状态'}")
        print("-" * 80)
        for s in summary:
            limit_str = str(s['daily_limit']) if s['daily_limit'] else "不限"
            print(f"{s['name']:50s} {s['priority']:>8d} {s['used_today']:>6d} {limit_str:>6} {s['status']}")
        print()
        total_used = sum(s['used_today'] for s in summary)
        print(f"今日总调用: {total_used} 次")
        return

    # ── 模型审查提醒 ──
    mgr = ModelManager(config)
    if mgr.needs_review():
        interval = config.get("settings", {}).get("model_review_interval_days", 30)
        print()
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│  📋 模型列表审查提醒                                        │")
        print(f"│  上次审查距今已超过 {interval} 天                            │")
        print("│  上游 不断有新模型上线，建议定期更新。                 │")
        print("│                                                             │")
        print("│  运行以下命令审查:                                            │")
        print(f"│    python3 proxy.py --review-models                         │")
        print("└─────────────────────────────────────────────────────────────┘")
        print()

    # ── 启动服务 ──
    app = create_app(config)
    host = config["proxy"]["host"]
    port = config["proxy"]["port"]
    api_key = config["proxy"]["api_key"]

    print(f"🚀 jproxy 已启动")
    print(f"   📡 监听: http://{host}:{port}")
    print(f"   🔑 代理 Key: {api_key}")
    print(f"   📊 已配置 {len(config.get('models', []))} 个模型")
    print()
    print("客户端使用示例:")
    print(f"  curl http://{host}:{port}/v1/chat/completions \\")
    print(f"    -H \"Authorization: Bearer {api_key}\" \\")
    print(f'    -d \'{{"model":"any","messages":[{{"role":"user","content":"你好"}}]}}\'')
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
