"""
OpenAI 格式请求/响应转发层。

上游 API 完全兼容 OpenAI 格式，所以转换逻辑很薄。
这一层保留是为了：
1. 替换 model 字段为实际选中的模型名
2. 后续如有格式差异只需改这里
"""

from typing import Any


def translate_request(openai_request: dict, target_model: str) -> dict:
    """替换 model 字段为实际选中的模型名。

    Args:
        openai_request: 原始请求
        target_model:   选中的模型名

    Returns:
        修改后的请求
    """
    request = openai_request.copy()
    request["model"] = target_model
    return request


def translate_response(response: dict) -> dict:
    """透传上游响应（格式已兼容）。"""
    return response


def make_error_response(
    message: str,
    code: str = "internal_error",
    status_code: int = 500,
) -> dict:
    """生成 OpenAI 风格的错误响应。"""
    return {
        "error": {
            "message": message,
            "type": "api_error",
            "code": code,
            "status_code": status_code,
        }
    }
