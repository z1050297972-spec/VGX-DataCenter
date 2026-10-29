"""扫描自动提交测试的可控时钟；UTC和单调秒独立变化，不改全局时区或真实时间。"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jobs_storage_support import NOW
from nav_manifest import FakeNavigation
from ops_support import runtime_inputs

from rdp.jobs.types import JobClock
from rdp.ops.runtime import RuntimeInputs


@dataclass
class TriggerClock:
    """一个触发器私有的测试时钟，不在测试之间共享状态。"""

    wall: datetime = NOW
    elapsed_s: float = 0.0

    def clock(self) -> JobClock:
        """返回公开时钟形状，允许用例精确设置599.999/600秒边界。"""
        return JobClock(lambda: self.wall, lambda: self.elapsed_s)


def worker_inputs(root: Path, navigation: FakeNavigation) -> RuntimeInputs:
    """生产装配的配置文件只指向临时导航，部署目录、挂载表和数据库也由既有夹具隔离。"""
    inputs = runtime_inputs(root)
    config = Path(inputs.environ["RDP_CONFIG"])
    config.write_text(
        config.read_text().replace(
            'nav_root = "~/nav"',
            "nav_root = " + json.dumps(str(navigation.nav_root), ensure_ascii=False),
        )
    )
    return inputs
