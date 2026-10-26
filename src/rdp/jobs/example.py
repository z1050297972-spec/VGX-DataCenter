"""不接触数据的示例类型（08 验收 6）；每步一个条目，参数可触发四种结果。

参数校验交 Pydantic，等待交 ProgressReporter，不用 sleep；恢复方式在生产登记表固定为标记中断。
"""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rdp.jobs.execution import ExecutionContext
from rdp.jobs.policy import (
    COUNT_MAX_INTERVAL_MS,
    COUNT_MAX_STEPS,
    COUNT_MIN_INTERVAL_MS,
    COUNT_MIN_STEPS,
)

# 逐项严格整数约束必须在Pydantic强制转换前生效，否则bool会先变成1。
CountStep = Annotated[int, Field(strict=True, ge=COUNT_MIN_STEPS, le=COUNT_MAX_STEPS)]


class CountParameters(BaseModel):
    """示例作业参数，序号从 1 开始，所有整数拒绝 bool。

    Attributes:
        model_config: 冻结、禁止多余字段、不回显拒绝值。
        steps: 总步数，COUNT_MIN_STEPS 至 COUNT_MAX_STEPS，必填。
        interval_ms: 每步间隔，COUNT_MIN_INTERVAL_MS 至 COUNT_MAX_INTERVAL_MS 毫秒，必填。
        failed_steps: 失败步序号元组，默认空，去重前先拒绝重复；每项 1 至 steps，至多 COUNT_MAX_STEPS 项。
        warning_steps: 警告步序号元组，默认空，同一失败步也可产生警告；范围/重复规则同上。
        abort_at_step: 在该步处理前整体中止，1 至 steps；默认 None 不整体中止。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    steps: int = Field(strict=True, ge=COUNT_MIN_STEPS, le=COUNT_MAX_STEPS)
    interval_ms: int = Field(strict=True, ge=COUNT_MIN_INTERVAL_MS, le=COUNT_MAX_INTERVAL_MS)
    failed_steps: tuple[CountStep, ...] = Field(default=(), max_length=COUNT_MAX_STEPS)
    warning_steps: tuple[CountStep, ...] = Field(default=(), max_length=COUNT_MAX_STEPS)
    abort_at_step: int | None = Field(
        default=None, strict=True, ge=COUNT_MIN_STEPS, le=COUNT_MAX_STEPS
    )

    @model_validator(mode="after")
    def _validate_steps(self) -> Self:
        """拒绝超出 steps 的序号、重复项、bool/非整数及越界整体中止步，不回显原值。"""
        raise NotImplementedError


def execute_count(context: ExecutionContext) -> None:
    """逐步数数并上报进度、独立警告与失败条目计数。

    Args:
        context: example_count 的执行上下文，parameters 必须为 CountParameters；mode 仅 fresh。

    Returns:
        无；完整走完全部步骤由执行器按计数计算成功、带警告成功、部分成功或全部失败。

    Raises:
        JobCancelledError: 每步前后或等待期间收到取消，不再开始下一步。
        WorkerStoppingError: worker 停止，留下 running 给下一实例标记中断。
        InputError: 到达 abort_at_step 时主动整体中止，诊断含作业编号、步数、实际、后果与重提建议；
            执行器设置 aborted=True，不能仅靠失败条目数伪装整体中止。
        ExternalError: 进度或作业日志发生不可跳过的 I/O 故障。
        DefectError: 参数模型错误、恢复模式错误或上报约束被破坏。

    Side Effects:
        只有一个“数数”阶段，每步真正处理完才累计 done/total_items 并 report；
        failed_steps 只增加失败条目，warning_steps 只增加警告；分别发统一诊断，不直接赋作业结果。
        每步使用 reporter.wait(interval_ms/1000)，取消立即打断；不创建产物或访问数据目录。

    Time Semantics:
        序号从 1 起，整体中止发生在指定步处理前，保留此前完整计数；
        每步间隔使用可取消的单调等待，零间隔仍检查信号，最终进度由执行器强制保存。
    """
    raise NotImplementedError
