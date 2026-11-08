"""有界检查子进程（M4-04）；按版本读取产物，仅将检查事实交回worker。"""

import subprocess
import sys
from pathlib import Path
from typing import Literal

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel
from rdp.jobs.conversion import _check_data as data
from rdp.jobs.conversion._check_video import videos
from rdp.jobs.conversion.check_models import CheckLayer, CheckReport

_NAMES = ("结构", "计数", "视频", "内容")


def diagnostic(
    layer: Literal["结构", "计数", "视频", "内容"], actual: str, *, warning: bool = False
) -> Diagnostic:
    """只生成统一诊断，细节与层名一同进入报告和作业结果。"""
    return Diagnostic(
        level=DiagnosticLevel.WARNING if warning else DiagnosticLevel.ERROR,
        category=DiagnosticCategory.INPUT,
        stage=layer,
        source="平台",
        objects=(),
        rule="conversion.check."
        + dict(zip(_NAMES, ("structure", "counts", "video", "content"), strict=True))[layer],
        actual=actual,
        expected="产物结构、计数、视频与内容符合声明的LeRobot版本",
        consequence="等待人工确认" if warning else "产物保留在暂存区，禁止入库",
        next_step="核对检查报告后确认入库" if warning else "修正转换输入或工具后重新转换",
    )


def check(root: Path, expected: str, scratch: Path) -> CheckReport:
    """前置层失败后明确停止，避免用不可信元信息继续解释数据。"""
    layers: list[CheckLayer] = []
    layer = "结构"
    try:
        info, warnings = data.structure(root, expected)
        layers.append(
            CheckLayer(
                name="结构",
                result="有警告" if warnings else "通过",
                diagnostics=tuple(diagnostic(layer, w, warning=True) for w in warnings),
            )
        )
        layer = "计数"
        data.counts(root, info)
        layers.append(CheckLayer(name="计数", result="通过"))
        layer = "视频"
        warnings = videos(root, info, scratch)
        layers.append(
            CheckLayer(
                name="视频",
                result="有警告" if warnings else "通过",
                diagnostics=tuple(diagnostic(layer, w, warning=True) for w in warnings),
            )
        )
        layer = "内容"
        data.content(root, info)
        layers.append(CheckLayer(name="内容", result="通过"))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        layers.append(
            CheckLayer(name=layer, result="不通过", diagnostics=(diagnostic(layer, str(error)),))
        )
    for name in _NAMES[len(layers) :]:
        layers.append(CheckLayer(name=name, result="未检查"))
    warnings = sum(len(layer.diagnostics) for layer in layers if layer.result == "有警告")
    failed = any(layer.result == "不通过" for layer in layers)
    return CheckReport(
        result="不通过" if failed else "有警告" if warnings else "通过",
        warning_count=warnings,
        layers=tuple(layers),
    )


if __name__ == "__main__":
    sys.stdout.write(check(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])).model_dump_json())
