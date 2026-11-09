"""M4.5 的平台指纹子进程；只依赖标准库，用平台解释器读取 LeRobot 源码并流式哈希。

与解释器探测共享沙箱和秒级预算，避免损坏环境或源码挂载阻塞工具列表及作业取消。
"""

import hashlib
import json
import sys
from pathlib import Path


def _fingerprint(package: Path, scope: tuple[str, ...]) -> str:
    """工单算法：POSIX 相对路径排序，路径、NUL、内容摘要与换行依次进哈希。"""
    digest = hashlib.sha256()
    paths = sorted(
        (
            path
            for name in scope
            for path in (package / name).rglob("*.py")
            if "__pycache__" not in path.parts
        ),
        key=lambda path: path.relative_to(package).as_posix(),
    )
    for path in paths:
        with path.open("rb") as stream:
            content_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        digest.update(
            path.relative_to(package).as_posix().encode() + b"\0" + content_digest.encode() + b"\n"
        )
    return digest.hexdigest()


if __name__ == "__main__":
    target = Path(sys.argv[1])
    probe = json.loads(target.read_text())
    probe["fingerprint"] = _fingerprint(Path(probe["package"]), tuple(sys.argv[2:]))
    target.write_text(json.dumps(probe))
    sys.stdout.write(json.dumps(probe) + "\n")
