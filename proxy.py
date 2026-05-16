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


def _make_auth_middleware(api_key: str):
    """创建认证中间件的工厂。返回的中间件在 ASGI 层工作，不依赖 Starlette BaseHTTPMiddleware。"""
    public_paths = {"/health", "/", "/docs", "/openapi.json"}

    class AuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path = scope.get("path", "")
            if path in public_paths:
                await self.app(scope, receive, send)
                return

            # 解析 headers 中的 Authorization
            raw_headers = scope.get("headers", [])
            auth_value = ""
            for k, v in raw_headers:
                if k.lower() == b"authorization":
                    auth_value = v.decode("utf-8", errors="replace")
                    break

            expected = f"Bearer {api_key}"
            if auth_value != expected:
                body = json.dumps({
                    "error": {
                        "message": "无效的 API Key。请使用 Authorization: Bearer <你的代理 Key>",
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                    }
                },
                ensure_ascii=False).encode("utf-8")
                headers_out = [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ]
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": headers_out,
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
                return

            await self.app(scope, receive, send)

    return AuthMiddleware


def create_app(config: dict) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(title="jproxy", version="1.0.0")
    manager = ModelManager(config)
    upstream_cfg = config["upstream"]
    proxy_cfg = config["proxy"]
    settings = config["settings"]

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

            print(f"  ▶ 使用模型: {model_name}")
            ms_request = translate_request(body, model_name)

            headers = {
                "Authorization": f"Bearer {upstream_cfg['api_key']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            if stream:
                return await _handle_streaming(
                    ms_request, headers, model_name,
                    upstream_cfg["base_url"], manager,
                )
            else:
                result = await _handle_non_streaming(
                    ms_request, headers, model_name,
                    upstream_cfg["base_url"], manager,
                )
                if result is not None:
                    return result

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

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(raw_request: Request):
        try:
            body = await raw_request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"error": {"message":"invalid json"}})

        # 粗略估算：从请求中数 token
        total = 0
        for msg in body.get("messages", []):
            c = msg.get("content", "")
            if isinstance(c, str):
                total += len(c) // 2 + 10
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict):
                        total += len(b.get("text", "")) // 2 + 10
        return JSONResponse(content={"input_tokens": max(total, 1)})

    # ── Anthropic Messages 端点 ──
    @app.post("/v1/messages")
    async def messages(raw_request: Request):
        try:
            body = await raw_request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"error": {"message":"invalid json"}})

        stream = body.get("stream", False)
        max_retries = settings.get("max_retries", 3)

        for attempt in range(max_retries + 1):
            model_name = manager.select_model()
            if model_name is None:
                return _all_exhausted_response(manager)

            print(f"  ▶ 使用模型: {model_name}")
            ms_request = _anthropic_to_openai(body, model_name)
            headers = {
                "Authorization": f"Bearer {upstream_cfg['api_key']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            if stream:
                # 流式：调上游拿 OpenAI SSE，转成 Anthropic SSE
                if upstream_cfg["base_url"].endswith("/v1"):
                    url = f"{upstream_cfg['base_url']}/chat/completions"
                else:
                    url = f"{upstream_cfg['base_url']}/v1/chat/completions"

                # 构建 Anthropic SSE 响应头
                anthropic_headers = {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }

                async def anthropic_stream():
                    nonlocal model_name
                    max_retries = settings.get("max_retries", 3)

                    for _ in range(max_retries + 1):
                        current = manager.select_model()
                        print(f"  ▶ 使用模型: {current}")
                        if current is None:
                            yield f"event: error\ndata: {json.dumps({'type':'error','error':{'type':'rate_limit_error','message':'all models exhausted'}})}\n\n"
                            return

                        msg_id = f"msg_{os.urandom(8).hex()}"
                        content_text = ""
                        stop_reason = None
                        text_block_started = False
                        tool_blocks_started = {}

                        start_msg = {
                            "id": msg_id, "type": "message", "role": "assistant",
                            "content": [], "model": current,
                            "stop_reason": None, "stop_sequence": None, "usage": None,
                        }
                        yield f"event: message_start\ndata: {json.dumps({'type':'message_start','message':start_msg})}\n\n"

                        oai_body = _anthropic_to_openai(body, current)
                        hdrs = {
                            "Authorization": f"Bearer {upstream_cfg['api_key']}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        }

                        async with httpx.AsyncClient(timeout=120.0) as cli:
                            try:
                                async with cli.stream("POST", url, json=oai_body, headers=hdrs) as resp:
                                    if resp.status_code == 429:
                                        manager.handle_429(current)
                                        yield f"event: error\ndata: {json.dumps({'type':'error','error':{'type':'rate_limit_error'}})}\n\n"
                                        continue
                                    if resp.status_code != 200:
                                        yield f"event: error\ndata: {json.dumps({'type':'error','error':{'type':'upstream_error'}})}\n\n"
                                        return

                                    manager.record_usage(current)
                                    async for line in resp.aiter_lines():
                                        if not line.startswith("data: "):
                                            continue
                                        payload = line[6:].strip()
                                        if payload == "[DONE]":
                                            continue
                                        try:
                                            chunk = json.loads(payload)
                                        except json.JSONDecodeError:
                                            continue

                                        choices = chunk.get("choices", [])
                                        if not choices:
                                            continue
                                        delta = choices[0].get("delta", {})
                                        frag = delta.get("content", "")
                                        if frag:
                                            if not text_block_started:
                                                text_block_started = True
                                                yield "event: content_block_start\ndata: " + json.dumps({"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}) + "\n\n"
                                            content_text += frag
                                            yield "event: content_block_delta\ndata: " + json.dumps({"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":frag}}) + "\n\n"

                                        tool_calls = delta.get("tool_calls")
                                        if tool_calls:
                                            for tc in tool_calls:
                                                fn = tc.get("function", {})
                                                idx = tc.get("index", 0) + 1
                                                if idx not in tool_blocks_started:
                                                    tool_blocks_started[idx] = True
                                                    yield "event: content_block_start\ndata: " + json.dumps({"type":"content_block_start","index":idx,"content_block":{"type":"tool_use","id":tc.get("id",""),"name":fn.get("name",""),"input":{}}}) + "\n\n"
                                                if fn.get("arguments"):
                                                    yield "event: content_block_delta\ndata: " + json.dumps({"type":"content_block_delta","index":idx,"delta":{"type":"input_json_delta","partial_json":fn["arguments"]}}) + "\n\n"
                                            continue

                                        fr = choices[0].get("finish_reason")
                                        if fr:
                                            stop_reason = fr

                            except httpx.RequestError as e:
                                yield f"event: error\ndata: {json.dumps({'type':'error','error':{'message':str(e)}})}\n\n"
                                return

                        if text_block_started:
                            yield "event: content_block_stop\ndata: " + json.dumps({"type":"content_block_stop","index":0}) + "\n\n"
                        for idx in sorted(tool_blocks_started):
                            yield "event: content_block_stop\ndata: " + json.dumps({"type":"content_block_stop","index":idx}) + "\n\n"

                        sr_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
                        sr = sr_map.get(stop_reason, stop_reason)
                        yield f"event: message_delta\ndata: {json.dumps({'type':'message_delta','delta':{'stop_reason':sr,'stop_sequence':None},'usage':{'input_tokens':0,'output_tokens':0}})}\n\n"
                        yield f"event: message_stop\ndata: {json.dumps({'type':'message_stop'})}\n\n"
                        return  # 成功结束

                    yield f"event: error\ndata: {json.dumps({'type':'error','error':{'type':'rate_limit_error','message':'retries exhausted'}})}\n\n"

                return StreamingResponse(anthropic_stream(), media_type="text/event-stream", headers=anthropic_headers)

            # 直接调上游，不走 _handle_non_streaming（避免 JSONResponse 序列化再反序列化）
            if upstream_cfg["base_url"].endswith("/v1"):
                url = f"{upstream_cfg['base_url']}/chat/completions"
            else:
                url = f"{upstream_cfg['base_url']}/v1/chat/completions"

            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    resp = await client.post(url, json=ms_request, headers=headers)
                    if resp.status_code == 429:
                        manager.handle_429(model_name)
                        continue
                    if resp.status_code != 200:
                        return JSONResponse(status_code=resp.status_code, content={"error": _extract_error(resp)})
                    manager.record_usage(model_name)
                    oai_data = resp.json()
                    anthro = _openai_to_anthropic(oai_data, ms_request, model_name)
                    return JSONResponse(content=anthro)
                except httpx.TimeoutException:
                    return JSONResponse(status_code=504, content={"error":{"message":"timeout"}})
                except httpx.RequestError as e:
                    return JSONResponse(status_code=502, content={"error":{"message":str(e)}})

        return JSONResponse(status_code=429, content={"error": {"message":"all models exhausted"}})

    # ── 用纯 ASGI 中间件包裹 app──
    AuthMiddleware = _make_auth_middleware(proxy_cfg["api_key"])
    app = AuthMiddleware(app)
    return app


# ─── Anthropic / OpenAI 格式互转 ─────────────────────────


def _anthropic_to_openai(anthropic_body: dict, model_name: str) -> dict:
    """将 Anthropic Messages 请求转为 OpenAI Chat Completions 请求。"""
    openai_messages = []
    for msg in anthropic_body.get("messages", []):
        role = msg["role"]
        content = msg.get("content", "")

        if isinstance(content, list):
            # content block 数组 — 可能有 tool_use, tool_result
            has_tool_blocks = any(b.get("type") in ("tool_use", "tool_result") for b in content)

            if has_tool_blocks:
                # 拆成 OpenAI 格式：tool_use → assistant + tool_calls, tool_result → tool role
                texts = []
                tool_calls = []
                for block in content:
                    bt = block.get("type")
                    if bt == "text":
                        texts.append(block["text"])
                    elif bt == "tool_use":
                        tc = {
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                        tool_calls.append(tc)
                    elif bt == "tool_result":
                        tool_result_content = block.get("content", "")
                        if isinstance(tool_result_content, list):
                            tool_result_content = "\n".join(
                                b.get("text", "") for b in tool_result_content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        openai_messages.append({
                            "role": "tool",
                            "content": tool_result_content,
                            "tool_call_id": block.get("tool_use_id", ""),
                        })
                    elif bt == "image":
                        texts.append("[image]")

                if tool_calls:
                    assistant_msg = {"role": "assistant", "content": "\n".join(texts) if texts else None}
                    assistant_msg["tool_calls"] = tool_calls
                    openai_messages.append(assistant_msg)
                elif texts:
                    openai_messages.append({"role": role, "content": "\n".join(texts)})
                else:
                    openai_messages.append({"role": role, "content": ""})
            else:
                texts = []
                for block in content:
                    if block.get("type") == "text":
                        texts.append(block["text"])
                    elif block.get("type") == "image":
                        texts.append("[image]")
                openai_messages.append({"role": role, "content": "\n".join(texts)})
        else:
            openai_messages.append({"role": role, "content": content})

    # system 提示在 Anthropic 中是顶层字段
    system = anthropic_body.get("system")
    if system:
        if isinstance(system, list):
            system = "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
        openai_messages.insert(0, {"role": "system", "content": system})

    # tools: Anthropic tools → OpenAI functions
    tools = anthropic_body.get("tools")
    oai_tools = None
    if tools:
        oai_tools = []
        for t in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            })

    oai = {
        "model": model_name,
        "messages": openai_messages,
        "max_tokens": anthropic_body.get("max_tokens", 4096),
        "stream": anthropic_body.get("stream", False),
    }

    if oai_tools:
        oai["tools"] = oai_tools

    # 可选参数
    if "temperature" in anthropic_body:
        oai["temperature"] = anthropic_body["temperature"]
    if "top_p" in anthropic_body:
        oai["top_p"] = anthropic_body["top_p"]
    if "stop_sequences" in anthropic_body:
        oai["stop"] = anthropic_body["stop_sequences"]

    return oai


def _openai_to_anthropic(oai_body: dict, request_body: dict, model_name: str) -> dict:
    """将 OpenAI Chat Completions 响应转为 Anthropic Messages 格式。"""
    choices = oai_body.get("choices", [])
    if not choices:
        return {
            "id": f"msg_{os.urandom(8).hex()}",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model_name,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    choice = choices[0]
    msg = choice.get("message", choice.get("delta", {}))
    content_text = msg.get("content", "") or ""
    finish_reason = choice.get("finish_reason")

    # 映射 finish_reason
    stop_reason_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "content_filter",
    }
    stop_reason = stop_reason_map.get(finish_reason, finish_reason)

    # usage
    usage = oai_body.get("usage", {})

    content_blocks = []
    if content_text:
        content_blocks.append({"type": "text", "text": content_text})

    # tool_calls → tool_use
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": tc.get("function", {}).get("name", ""),
                "input": json.loads(tc.get("function", {}).get("arguments", "{}")),
            })

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    return {
        "id": f"msg_{os.urandom(8).hex()}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model_name,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


async def _wrap_anthropic_stream(streaming_response, request_body, model_name):
    """将 OpenAI SSE 流包装成 Anthropic SSE 流。"""
    # 简化实现：直接透传内部错误，streaming 非流式回退
    return streaming_response


# ─── 请求处理函数 ────────────────────────────────────────


async def _handle_non_streaming(
    request_body: dict,
    headers: dict,
    model_name: str,
    base_url: str,
    manager: ModelManager,
) -> Optional[JSONResponse]:
    """处理非流式请求。遇到 429 返回 None 让上层重试。"""
    # base_url 可能已包含 /v1 路径，避免重复
    if base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(url, json=request_body, headers=headers)

            # 配额耗尽 — 标记后返回 None 触发重试
            if response.status_code == 429:
                manager.handle_429(model_name)
                print(f"  [↻] {model_name} 配额耗尽，尝试下一个模型...")
                return None

            # 其他错误 — 直接返回
            if response.status_code != 200:
                error_body = _extract_error(response)
                # 透传上游状态码，日志里能看到实际错误
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
    # base_url 可能已包含 /v1 路径，避免重复
    if base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"
    max_retries = manager.settings.get("max_retries", 3)

    async def generate():
        for attempt in range(max_retries + 1):
            # 每次重试重新选择模型（因为前面的可能已被标记耗尽）
            current_model = manager.select_model()
            print(f"  ▶ 使用模型: {current_model}")
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
                            manager.handle_429(current_model)
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
