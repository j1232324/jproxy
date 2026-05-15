"""
OpenAI ↔ ModelScope 请求/响应格式转换。

ModelScope 的 API 本身就是 OpenAI 兼容的格式，
所以转换逻辑很薄，但这一层有两个重要职责：

1. 替换 model 字段为实际选择的 ModelScope 模型名
2. 作为适配层，未来 ModelScope 格式变化时只需改这里
"""

from typing import Any


def translate_request(openai_request: dict, target_model: str) -> dict:
    """将 OpenAI 格式的请求转为 ModelScope 格式。

    Args:
        openai_request: 原始请求 dict (model 字段会被覆盖)
        target_model:   proxy 选中的 ModelScope 模型名

    Returns:
        修改后的请求 dict
    """
    request = openai_request.copy()
    request["model"] = target_model
    return request


def translate_response(modelscope_response: dict) -> dict:
    """将 ModelScope 响应转为 OpenAI 兼容格式。

    目前是透传，因为格式已经兼容。
    后续可以在这里做:
    - 隐藏实际使用的模型名
    - 统一 usage 字段格式
    - 错误信息标准化
    """
    return modelscope_response


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
