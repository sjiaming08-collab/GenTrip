"""LLM 调用异常。"""


class LLMError(Exception):
    """LLM 请求或响应异常。"""


class LLMParseError(LLMError):
    """JSON / schema 解析失败。"""
