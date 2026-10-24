"""变异抽查：对首次即通过的测试各做一处能区分正确实现的变异，期望测试转红。"""
import subprocess, sys
from pathlib import Path
M = [
 ("中间件改用客户端带来的编号", "src/rdp/api/__init__.py",
  "        request_id = uuid4().hex\n",
  "        request_id = next((v.decode() for k, v in scope.get('headers', []) if k == b'x-request-id'), uuid4().hex)\n",
  ["tests/test_web_app.py::test_client_request_id_ignored"]),
 ("中间件用 add_middleware 挂在框架错误处理之内", "src/rdp/api/__init__.py",
  "        return RequestIdMiddleware(super().build_middleware_stack())",
  "        return super().build_middleware_stack()",
  ["tests/test_web_app.py::test_request_ids_on_all_response_statuses", "tests/test_web_app.py::test_request_wrapper_outside_error_stack"]),
 ("log_context 退出不恢复", "src/rdp/infra/logging.py",
  "        if request_token is not None:\n            request_id_context.reset(request_token)\n        if job_token is not None:\n            job_id_context.reset(job_token)",
  "        pass",
  ["tests/test_logging.py::test_nested_context", "tests/test_logging.py::test_context_exception_restore", "tests/test_logging.py::test_context_cancel_restore", "tests/test_web_app.py::test_request_context_restored_after_failure"]),
 ("下一零点按固定 86400 秒算", "src/rdp/infra/logging.py",
  "    next_date = moment.date() + timedelta(days=1)\n    return int(datetime.combine(next_date, datetime_time.min, tzinfo=moment.tzinfo).timestamp())",
  "    return int(datetime.combine(moment.date(), datetime_time.min, tzinfo=moment.tzinfo).timestamp()) + 86400",
  ["tests/test_logging.py::test_dst_calendar_midnight"]),
 ("访问日志没关", "src/rdp/infra/logging.py",
  "    access.disabled = True\n    access.propagate = False",
  "    access.disabled = False\n    access.propagate = True",
  ["tests/test_logging.py::test_uvicorn_access_disabled", "tests/test_web_app.py::test_health_has_no_access_log"]),
 ("报错回显所有值", "src/rdp/infra/config.py",
  "            if item in _VISIBLE_FIELDS and isinstance(actual, (str, int, float, bool))",
  "            if True",
  ["tests/test_config.py::test_sensitive_error_values", "tests/test_config.py::test_unknown_fields"]),
 ("已有目录也 chmod", "src/rdp/infra/state.py",
  "    if _directory_stat(path) is not None:\n        return\n",
  "    if _directory_stat(path) is not None:\n        path.chmod(STATE_DIRECTORY_MODE)\n        return\n",
  ["tests/test_state.py::test_existing_layout_checked_without_writes", "tests/test_state.py::test_existing_permissions_unchanged"]),
 ("时钟回拨后用回拨时刻重算边界", "src/rdp/infra/logging.py",
  "        return moment.timestamp() >= self.rolloverAt",
  "        self.rolloverAt = min(self.rolloverAt, _next_midnight(moment))\n        return moment.timestamp() >= self.rolloverAt - 86400 * (moment.timestamp() < self.rolloverAt - 86400)",
  ["tests/test_logging.py::test_clock_rollback"]),
 ("同名归档直接覆盖", "src/rdp/infra/logging.py",
  "            if destination.exists():",
  "            if False:",
  ["tests/test_logging.py::test_archive_collision"]),
 ("请求编号放进进程全局（模仿 ContextVar 接口）", "src/rdp/infra/logging.py",
  'request_id_context: ContextVar[str | None] = ContextVar("rdp_request_id", default=None)',
  """class _GlobalVar:
    def __init__(self): self.v = None
    def get(self): return self.v
    def set(self, v):
        old, self.v = self.v, v
        return old
    def reset(self, old): self.v = old


request_id_context = _GlobalVar()""",
  ["tests/test_web_app.py::test_concurrent_request_ids", "tests/test_logging.py::test_concurrent_context_isolation"]),
]
ok = bad = 0
for name, f, old, new, tests in M:
    p = Path(f); src = p.read_text()
    if src.count(old) != 1:
        print(f"[跳过] {name}：没找到唯一的变异点"); bad += 1; continue
    p.write_text(src.replace(old, new))
    try:
        r = subprocess.run([".venv/bin/pytest", "-q", "-p", "no:cacheprovider", *tests], capture_output=True, text=True, timeout=120)
        tail = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l][-1:]
        killed = r.returncode != 0
        print(f"[{'转红' if killed else '仍绿！'}] {name}：{' '.join(t.split('::')[1] for t in tests)} → {tail}")
        ok += killed; bad += not killed
    finally:
        p.write_text(src)
print(f"合计：转红 {ok}，未转红或跳过 {bad}")
