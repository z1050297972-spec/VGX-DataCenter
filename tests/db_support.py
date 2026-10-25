"""数据库测试的标准库资源边界；只处理显式传入的 tmp_path 路径，不解析 home。"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def sqlite_connection(
    path: Path | str, **options: Any
) -> Generator[sqlite3.Connection, None, None]:
    """事务结束后总是关闭 sqlite3 连接；Connection 的原生 with 只提交、不关闭。"""
    connection = sqlite3.connect(path, **options)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def reap_processes(processes: list[Any]) -> None:
    """测试即使断言失败也先终止存活子进程，再有界回收，避免 pytest 挂住。"""
    for process in processes:
        if process.is_alive():
            process.terminate()
        process.join(2)
        if process.is_alive():
            process.kill()
            process.join(2)
        assert not process.is_alive()
