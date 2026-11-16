"""预览静默回归的进程/时钟边界；真实终端解析、进度累计和成功事务均不替换。"""

import hashlib
import re
import time
from threading import Lock

from agibot_preview_support import AgibotPreviewCase
from jobs_progress_support import MutableClock

from rdp.jobs.types import JobClock


def silent_preview_clock(case: AgibotPreviewCase) -> JobClock:
    """临时假工具等待真实降级诊断；看到终端就绪后推进31秒，实时时限5秒兜底。"""
    release = case.cache / "release-preview"
    program = case.tools.library_root / case.tool_name / "preview"
    source = program.read_text()
    # 在结果写出前暂停，防止短工具先退出，导致终端根本没有机会执行静默检查。
    waiting = f"""import time
sys.stderr.write("预览静默就绪\\n")
sys.stderr.flush()
deadline = time.monotonic() + 5
while not pathlib.Path({str(release)!r}).exists():
    if time.monotonic() >= deadline:
        raise RuntimeError("测试未观察到进度降级")
    time.sleep(0.01)
"""
    source = source.replace(
        'with pathlib.Path(a.result).open("x")', waiting + 'with pathlib.Path(a.result).open("x")'
    )
    program.write_text(source)
    manifest = case.tools.registry_dir / case.tool_name / "tool.toml"
    text = re.sub(r"size = [0-9]+", f"size = {len(source.encode())}", manifest.read_text())
    manifest.write_text(
        re.sub(
            r'(?m)^sha256 = "[0-9a-f]+"',
            f'sha256 = "{hashlib.sha256(source.encode()).hexdigest()}"',
            text,
        )
    )
    clock = MutableClock()
    # 跨过受管终端30秒静默阈值；推进量与测试时钟初始读数无关。
    after_silence = clock.seconds + 31.0
    started = time.monotonic()
    lock = Lock()

    def monotonic() -> float:
        # 日志仅作跨进程握手，断言仍观察真实终态和持久化报告；不依赖线程调度快慢。
        with lock:
            for path in (case.paths.root / "logs").glob("*/*.log"):
                content = path.read_text()
                if "预览静默就绪" in content:
                    clock.seconds = after_silence
                if "连续30秒未解析出进度" in content:
                    release.touch(exist_ok=True)
            # 跳过静默期后仍随真实单调时钟走，受管进程的短轮询等待才能到期。
            return clock.monotonic() + time.monotonic() - started

    return JobClock(clock.now, monotonic)
