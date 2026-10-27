"""worker与外部进程的内部时钟校验；用注入monotonic计算期限，UTC转换复用基础层。"""

import math

from rdp.infra.diagnostics import DefectError
from rdp.jobs import _storage
from rdp.jobs.types import JobClock


class ClockReader:
    """单个调用/线程的有限且非递减时钟，不跨线程共用上次读数。"""

    def __init__(self, clock: JobClock) -> None:
        """校验UTC时钟并建立本调用的单调读数基线，不读取业务存储。"""
        self.clock = clock
        self.previous: float | None = None
        _storage.moment(clock.now())

    def read(self) -> float:
        """拒绝NaN、bool与回退，不把非法时钟当作业务超时。"""
        value = self.clock.monotonic()
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or (self.previous is not None and value < self.previous)
        ):
            raise DefectError()
        self.previous = value
        return value
