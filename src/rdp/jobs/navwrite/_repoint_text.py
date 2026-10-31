"""L17/L18 的内存字符串替换与同源报告；不做文件或存储 I/O。

这是导航文档特有的边界规则；使用标准库 re，不引入 Markdown 解析依赖。
"""

import re
from collections import Counter
from collections.abc import Callable

from rdp.jobs.datasets.types import JsonValue
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.models import ListedChange
from rdp.jobs.navwrite.policy import PREVIEW_LISTED_CHANGE_LIMIT, REPOINT_LISTED_CHANGE_LIMIT

# 正文结束字符直接来自 L17；普通字符串只认斜杠或串尾。
_PROSE_END = r"[\s`\"')\]>，。；：）」]"
# 片段两边各保留 40 个字符，避免一处替换带出整篇 Markdown。
_CONTEXT_CHARS = 40


class Replacements:
    """一次预览内的替换累积器；不跨请求共享状态。"""

    def __init__(self, old: str, new: str, checkpoint: Callable[[], None]) -> None:
        """保存显式前缀、检查点和有界逐处样例。"""
        self.old = old
        self.new = new
        self.checkpoint = checkpoint
        self.path_pattern = re.compile(re.escape(old) + r"(?=/|$)")
        self.prose_pattern = re.compile(re.escape(old) + r"(?=/|$|" + _PROSE_END + ")")
        self.counts: Counter[tuple[str, str]] = Counter()
        self.listed: list[ListedChange] = []
        self.listed_total = 0
        self.complete: list[ListedChange] = []
        self.paths: dict[str, str] = {}

    def transform(
        self, value: JsonValue, file: str, path: str = "", *, record: bool = True
    ) -> JsonValue:
        """遍历所有字符串值但跳过 original_path 子树，保持键顺序和未知值。"""
        self.checkpoint()
        if isinstance(value, dict):
            return {
                key: item
                if key == "original_path"
                else self.transform(item, file, f"{path}.{key}" if path else key, record=record)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self.transform(item, file, f"{path}[{index}]", record=record)
                for index, item in enumerate(value)
            ]
        if not isinstance(value, str):
            return value
        return self._string(value, file, path, record=record)

    def _string(self, value: str, file: str, path: str, *, record: bool) -> str:
        """同一份匹配同时驱动替换、数量、路径检查与逐处报告。"""
        group = re.sub(r"\[\d+\]", "[]", path)
        # notes 在真实文档里是字符串数组；下标不能让正文边界和逐处报告失效。
        prose = any(
            field.endswith("markdown") or field == "notes"
            for field in group.replace("[]", "").split(".")
        )
        matcher = self.prose_pattern if prose else self.path_pattern
        updated, count = matcher.subn(lambda _match: self.new, value)
        if count and record:
            self.counts[file, group] += count
            for match in matcher.finditer(value):
                old = self._path(value, match, prose=prose)
                self.paths[old] = self.new + old[len(self.old) :]
                if prose:
                    self._list(value, match, file, path)
        return updated

    def _path(self, value: str, match: re.Match[str], *, prose: bool) -> str:
        """定位被替换的完整路径；带引号或尖括号的 Markdown 路径可包含空格。"""
        end = len(value)
        if prose:
            opening = value[match.start() - 1 : match.start()] if match.start() else ""
            closing = {"`": "`", "<": ">", "'": "'", '"': '"'}.get(opening)
            if closing is not None:
                found = value.find(closing, match.end())
                end = found if found >= 0 else len(value)
            else:
                tail = re.search(_PROSE_END, value[match.end() :])
                if tail is not None:
                    end = match.end() + tail.start()
        return value[match.start() : end]

    def _list(self, value: str, match: re.Match[str], file: str, path: str) -> None:
        """完整差异有明确预算；通用样例字段保持500条，超过完整预算则拒绝预览。"""
        self.listed_total += 1
        if self.listed_total > REPOINT_LISTED_CHANGE_LIMIT:
            raise nav_input_error(
                "NAV_REPOINT_REPORT",
                "完整正文差异超过预览预算，请缩小替换前缀范围",
                objects=(("limit", str(REPOINT_LISTED_CHANGE_LIMIT)),),
            )
        start = max(0, match.start() - _CONTEXT_CHARS)
        end = min(len(value), match.end() + _CONTEXT_CHARS)
        item = ListedChange(
            file=file,
            json_path=path,
            before=value[start:end],
            after=value[start : match.start()] + self.new + value[match.end() : end],
        )
        self.complete.append(item)
        if len(self.listed) < PREVIEW_LISTED_CHANGE_LIMIT:
            self.listed.append(item)
