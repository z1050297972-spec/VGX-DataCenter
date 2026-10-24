"""变异抽查（工单 04）：对首次即通过的测试各做一处能区分正确实现的变异，期望对应测试转红。

在探针工作目录（检出快照）里运行：python mutation_probe.py <探针目录>。每个变异改完立即还原。
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(sys.argv[1])
M = [
 ("聚合样例配额改成全局共享（不同组互相挤占）", "src/rdp/infra/diagnostics.py",
  "        if len(samples) < DIAGNOSTIC_SAMPLE_LIMIT:",
  "        if sum(len(g.samples) for g in groups.values()) < DIAGNOSTIC_SAMPLE_LIMIT:",
  ["tests/test_diagnostics.py::test_aggregate_groups_independent"]),
 ("警告也计入错误数", "src/rdp/infra/diagnostics.py",
  "            diagnostic.level is DiagnosticLevel.ERROR\n",
  "            True\n",
  ["tests/test_diagnostics.py::test_aggregate_levels_categories_stages"]),
 ("对象按键名排序输出", "src/rdp/infra/diagnostics.py",
  "            for item in diagnostic.objects\n",
  "            for item in sorted(diagnostic.objects, key=lambda o: o.key)\n",
  ["tests/test_diagnostics.py::test_render_object_order"]),
 ("期望为空也写“；期望：”", "src/rdp/infra/diagnostics.py",
  "    if diagnostic.expected is not None:\n        actual +=",
  "    if True:\n        actual +=",
  ["tests/test_diagnostics.py::test_render_global_and_no_expectation"]),
 ("边界记完日志后重新抛出（uvicorn 会再记一次）", "src/rdp/api/errors.py",
  "            _report_error(request, error, problem)\n            # 已发送前缀",
  "            _report_error(request, error, problem)\n            if True:\n                raise\n            # 已发送前缀",
  ["tests/test_api_errors.py::test_boundary_server_error_rethrow_once", "tests/test_api_errors.py::test_boundary_background_failure_once"]),
 ("响应已开始仍补发 500", "src/rdp/api/errors.py",
  "            if not started:\n                response = JSONResponse(",
  "            if True:\n                response = JSONResponse(",
  ["tests/test_api_errors.py::test_boundary_stream_failure_once"]),
 ("边界吞掉取消等 BaseException", "src/rdp/api/errors.py",
  "        except Exception as error:\n            request = Request(scope, receive=receive)",
  "        except BaseException as error:\n            request = Request(scope, receive=receive)",
  ["tests/test_api_errors.py::test_boundary_cancel_and_exit"]),
 ("日志请求行写实际路径和查询串", "src/rdp/api/errors.py",
  '    path = route.path if isinstance(route, APIRoute) else "未匹配路径"',
  "    path = str(request.url)",
  ["tests/test_api_errors.py::test_handler_request_log_privacy"]),
 ("参数校验诊断回显原值", "src/rdp/api/errors.py",
  '            actual="字段缺失或格式不符合要求（原值不回显）",',
  '            actual="原值：" + repr(item.get("input")),',
  ["tests/test_api_errors.py::test_validation_no_secret_echo"]),
 ("traceback 打印局部变量", "src/rdp/api/errors.py",
  "        error, capture_locals=False,",
  "        error, capture_locals=True,",
  ["tests/test_api_errors.py::test_report_secret_redaction"]),
 ("部分失败有警告时判成带警告成功", "src/rdp/jobs/outcome.py",
  "    if failed_items > 0:\n        return JobOutcome.PARTIALLY_SUCCEEDED",
  "    if failed_items > 0 and warning_count == 0:\n        return JobOutcome.PARTIALLY_SUCCEEDED",
  ["tests/test_job_outcome.py::test_partial_with_warnings"]),
 ("中止且有部分失败时判成部分成功", "src/rdp/jobs/outcome.py",
  "    if aborted:\n        return JobOutcome.FAILED",
  "    if aborted and failed_items == 0:\n        return JobOutcome.FAILED",
  ["tests/test_job_outcome.py::test_aborted_overrides_partial"]),
 ("r1：边界记完日志后重新抛出（示例二走意外异常路径）", "src/rdp/api/errors.py",
  "            _report_error(request, error, problem)\n            # 已发送前缀",
  "            _report_error(request, error, problem)\n            if True:\n                raise\n            # 已发送前缀",
  ["tests/test_api_errors.py::test_representative_platform_defect"]),
 ("r1：缺陷响应的 detail 带异常原文", "src/rdp/api/errors.py",
  '    detail = "平台内部错误，请把错误编号交给维护者。"',
  '    detail = "平台内部错误：" + repr(error)',
  ["tests/test_api_errors.py::test_representative_platform_defect"]),
 ("r1：输入类子类的状态码一律 400", "src/rdp/api/errors.py",
  "        status, category, diagnostics = error.http_status, error.category, error.diagnostics",
  "        status, category, diagnostics = (HTTPStatus.BAD_REQUEST if error.category is DiagnosticCategory.INPUT else error.http_status), error.category, error.diagnostics",
  ["tests/test_api_errors.py::test_handler_mappings_and_media"]),
]
ok = bad = 0
for name, f, old, new, tests in M:
    p = ROOT / f
    src = p.read_text()
    if src.count(old) != 1:
        print(f"[跳过] {name}：没找到唯一的变异点（{src.count(old)} 处）"); bad += 1; continue
    p.write_text(src.replace(old, new))
    try:
        r = subprocess.run([str(ROOT / ".venv/bin/pytest"), "-q", "-p", "no:cacheprovider", *tests], cwd=ROOT, capture_output=True, text=True, timeout=300)
    finally:
        p.write_text(src)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]
    if r.returncode != 0:
        ok += 1; print(f"[抓到] {name}：{tail}")
    else:
        bad += 1; print(f"[漏网] {name}：{tail}")
print(f"合计：抓到 {ok}，漏网或跳过 {bad}")
