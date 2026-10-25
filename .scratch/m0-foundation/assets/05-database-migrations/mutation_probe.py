"""变异抽查（工单 05）：对首次即通过的测试各做一处能区分正确实现的变异，期望对应测试转红。

在探针工作目录（检出快照）里运行：python mutation_probe.py <探针目录>。每个变异改完立即还原。
前端变异用 vitest，后端用 pytest；变异点必须在源文件里唯一出现，否则记"跳过"。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
C = "src/rdp/infra/db/connection.py"
G = "src/rdp/infra/db/migration.py"
R = "src/rdp/infra/db/records.py"
E = "src/rdp/api/errors.py"
TC = "tests/test_db_connection.py::"
TM = "tests/test_db_migration.py::"
TR = "tests/test_db_records.py::"
TA = "tests/test_api_database.py::"
M = [
    ("等锁上限改成 0（另一个进程写着就立刻失败）", C,
     'cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")', 'cursor.execute("PRAGMA busy_timeout=0")',
     [TC + "test_process_success", TC + "test_process_timeout"]),
    ("约束冲突不归冲突", C,
     "if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CONSTRAINT):",
     "if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):",
     [TC + "test_session_constraint"]),
    ("库损坏归成外部失败", C,
     "elif code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):\n        kind = InputError",
     "elif code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):\n        kind = ExternalError",
     [TC + "test_session_corrupt", TR + "test_write_corrupt", TR + "test_find_corrupt", TR + "test_clear_corrupt"]),
    ("异常退出时提交而不是回滚", C,
     "            session.rollback()\n        except Exception:",
     "            session.commit()\n        except Exception:",
     [TC + "test_session_rollback", TR + "test_clear_commit"]),
    ("只读会话不设 query_only", C,
     'connection.exec_driver_sql("PRAGMA query_only=ON")', 'connection.exec_driver_sql("PRAGMA query_only=OFF")',
     [TA + "test_read_exception"]),
    ("版本检查只拦没迁移过的库（落后、未知都放行）", G,
     "    current, _ = _read_revision(database)\n    if current != head:",
     "    current, _ = _read_revision(database)\n    if current is None:",
     [TM + "test_version_behind", TM + "test_version_unknown", TA + "test_configure_version"]),
    ("备份不复制任何内容", G,
     "            source.backup(\n", "            (lambda *_a, **_k: None)(\n",
     [TM + "test_backup_contents", TM + "test_backup_before"]),
    ("旧备份清理不认文件名，凡 .sqlite3 都算", G,
     "if entry.is_file(follow_symlinks=False) and re.fullmatch(pattern, entry.name):",
     'if entry.name.endswith(".sqlite3"):',
     [TM + "test_backup_foreign"]),
    ("备份文件名去掉随机后缀（同一时刻两次备份互相覆盖）", G,
     "-{uuid4().hex}.sqlite3", '-{"0" * 12 + "4" + "0" * 3 + "8" + "0" * 15}.sqlite3',
     [TM + "test_backup_filename"]),
    ("新建 backups/ 用 0755", G,
     "            directory.mkdir(mode=STATE_DIRECTORY_MODE)\n            directory.chmod(STATE_DIRECTORY_MODE)\n        if not directory.is_dir() or directory.stat().st_mode & 0o7777 != STATE_DIRECTORY_MODE:",
     "            directory.mkdir(mode=0o755)\n            directory.chmod(0o755)\n        if not directory.is_dir():",
     [TM + "test_backup_permissions"]),
    ("清除边界含等于（恰好等于保留天数的也删）", R,
     "ErrorReportRow.occurred_at < cutoff", "ErrorReportRow.occurred_at <= cutoff",
     [TR + "test_clear_boundary", TR + "test_clear_utc"]),
    ("保留天数不拒绝 bool", R,
     "if type(retention_days) is not int or not", "if not isinstance(retention_days, int) or not",
     [TR + "test_clear_days"]),
    ("同一请求重复报告不去重", E,
     '    if getattr(request.state, "rdp_error_reported", False):\n        return',
     "    if False:\n        return",
     [TA + "test_report_reentry"]),
    ("四类里非缺陷的也写进报错表", E,
     "    if problem.category is not DiagnosticCategory.DEFECT:\n        _report_error(request, error, problem)\n        return",
     "    if False:\n        _report_error(request, error, problem)\n        return",
     [TA + "test_report_nondefect"]),
    ("写表失败不再记那条 ERROR", E,
     '        logger.error(\n            "完整报错持久化失败",', '        logger.debug(\n            "完整报错持久化失败",',
     [TA + "test_report_failure"]),
    ("报告不截断", E,
     "        if len(piece) > remaining:\n            return (",
     "        if False:\n            return (",
     [TA + "test_report_bound", TR + "test_report_bound"]),
    ("查不到时返回 400 而不是 404", "src/rdp/api/error_details.py",
     "        raise ErrorReportNotFoundError(\n", "        raise InputError(\n",
     [TA + "test_details_not_found"]),
    ("报错保留天数默认改成 31", "src/rdp/infra/config.py",
     "class ErrorRetentionConfig(BaseModel):", "class ErrorRetentionConfig(BaseModel):  # 变异",
     []),  # 占位，下面单独处理默认值
]
# 默认值所在行与 LogConfig 相同，用带上下文的唯一片段替换。
M[-1] = ("报错保留天数默认改成 31", "src/rdp/infra/config.py",
         '    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)\n    retention_days: int = Field(default=30, ge=1, le=MAX_RETENTION_DAYS)\n\n\nclass PlatformConfig',
         '    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)\n    retention_days: int = Field(default=31, ge=1, le=MAX_RETENTION_DAYS)\n\n\nclass PlatformConfig',
         ["tests/test_db_config.py::test_default"])
W = "src/web/src/api/errorDetails.ts"
FRONT = [
    ("详情查询失败时自动重试一次", W, "          retry: false,", "          retry: 1,",
     "src/api/errorDetails.test.ts", "详情查询 retry=false"),
    ("详情结果长期缓存", W, "          gcTime: 0,", "          gcTime: 600000,",
     "src/api/errorDetails.test.ts", "不同客户端/编号查询隔离"),
]

ok = bad = 0


def mutate(name: str, f: str, old: str, new: str, run: list[str], cwd: Path) -> None:
    """改一处、跑指定测试、立刻还原；测试转红记"抓到"。"""
    global ok, bad
    p = ROOT / f
    src = p.read_text()
    if src.count(old) != 1:
        print(f"[跳过] {name}：没找到唯一的变异点（{src.count(old)} 处）")
        bad += 1
        return
    p.write_text(src.replace(old, new))
    try:
        r = subprocess.run(run, cwd=cwd, capture_output=True, text=True, timeout=600)
    finally:
        p.write_text(src)
    lines = (r.stdout + r.stderr).strip().splitlines()
    tail = next((x for x in reversed(lines) if x.strip()), "")[:160]
    if r.returncode != 0:
        ok += 1
        print(f"[抓到] {name}：{tail}")
    else:
        bad += 1
        print(f"[漏网] {name}：{tail}")


for name, f, old, new, tests in M:
    mutate(name, f, old, new, [str(ROOT / ".venv/bin/pytest"), "-q", "-p", "no:cacheprovider", *tests], ROOT)
for name, f, old, new, file, title in FRONT:
    mutate(name, f, old, new, ["node_modules/.bin/vitest", "run", file, "-t", title], ROOT / "src/web")
print(f"合计：抓到 {ok}，漏网或跳过 {bad}")
