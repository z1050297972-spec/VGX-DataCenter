"""作业展示的成员脱敏边界（M0-13 D3）；只改响应副本，管理员与磁盘原始日志保持完整。

诊断复用既有Pydantic模型，日志对象使用render_diagnostic已有的JSON字符串语法识别；
标准库正则和JSON足够处理当前文本格式，不引入日志解析依赖。
"""

import json
import re
from dataclasses import replace

from rdp.infra.diagnostics import Diagnostic, DiagnosticGroup
from rdp.jobs.logs import LogTail

# 诊断对象中的命令和stderr必须整字段去掉；路径可能出现在五段自由文本中，统一替换。
_PRIVATE_OBJECT_KEYS = frozenset({"command", "argv", "stderr", "stderr_tail"})
# 路径以Unix根斜杠开始；标点和引号是诊断中的分隔，不属于路径。
_ABSOLUTE_PATH = re.compile(r"""(?<![A-Za-z0-9_.])/[^\s"'<>\[\]{}，。；：！？、（）()=]+""")
_JSON_STRING = r'"(?:\\.|[^"\\])*"'
_OBJECT_PAIR = re.compile(f"({_JSON_STRING})=({_JSON_STRING})")


def _member_text(text: str) -> str:
    """替换自由文本中的绝对路径，保留诊断各段的业务说明。"""
    return "（路径已隐藏）" if text == "/" else _ABSOLUTE_PATH.sub("（路径已隐藏）", text)


def member_diagnostic(value: Diagnostic) -> Diagnostic:
    """删除管理员专属对象，再校验五段诊断的响应副本。"""
    data = value.model_dump()
    data["objects"] = [
        item.model_dump()
        for item in value.objects
        if item.key.lower() not in _PRIVATE_OBJECT_KEYS
        and not item.value.startswith("/")
        and not _ABSOLUTE_PATH.search(item.value)
    ]
    for name in ("stage", "source", "rule", "actual", "expected", "consequence", "next_step"):
        if isinstance(data[name], str):
            data[name] = _member_text(data[name])
    # 错误链是工具原始异常信息，可能重复命令或stderr；五段诊断足够成员定位业务结果。
    data["error_chain"] = ()
    return Diagnostic.model_validate(data)


def member_diagnostic_group(value: DiagnosticGroup) -> DiagnosticGroup:
    """组身份和样例使用同样的脱敏规则，保留完整计数和样例顺序。"""
    return replace(
        value,
        source=_member_text(value.source),
        rule=_member_text(value.rule),
        samples=tuple(member_diagnostic(item) for item in value.samples),
    )


def member_log_tail(tail: LogTail) -> LogTail:
    """保留有界日志状态和五段文本，移除工具stderr输出及命令对象。"""
    return LogTail(
        tail.status, tuple(_member_log_line(line) for line in tail.lines), tail.truncated
    )


def _member_log_line(line: str) -> str:
    """处理render_diagnostic的JSON对象与工具输出前缀，不把转义换行当作新记录。"""
    if re.search(r"\bstderr\s+[^│]*│", line):
        return "（工具stderr仅管理员可见）"
    if "错误链：" in line or "← " in line:
        return "（错误链仅管理员可见）"

    def object_pair(match: re.Match[str]) -> str:
        key, value = json.loads(match[1]), json.loads(match[2])
        if (
            key.lower() in _PRIVATE_OBJECT_KEYS
            or value.startswith("/")
            or _ABSOLUTE_PATH.search(value)
        ):
            return ""
        return match[0]

    text = _OBJECT_PAIR.sub(object_pair, line)
    text = re.sub(r"\b(?:argv|command|stderr_tail)\s*[=:].*", "（工具细节仅管理员可见）", text)
    return _member_text(text)
