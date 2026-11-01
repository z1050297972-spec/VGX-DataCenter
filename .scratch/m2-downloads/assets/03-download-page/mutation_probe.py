"""m2-03 变异抽查：只抽关键行为。每个变异改一处，跑本票后端测试，必须失败；改完立即还原。"""
import subprocess, sys
from pathlib import Path
WT = Path(sys.argv[1])
TOK = WT / "src/rdp/api/download_tokens.py"
SVC = WT / "src/rdp/jobs/service.py"
CLN = WT / "src/rdp/jobs/_download_cleanup.py"
MUTANTS = [
    (TOK, "token 接口要管理员", "Admin = Annotated[AccountRequestContext, Depends(get_admin_context)]", "from rdp.api.account_auth import get_account_context as _g\nAdmin = Annotated[AccountRequestContext, Depends(_g)]"),
    (TOK, "token 文件 0600", "os.fchmod(stream.fileno(), 0o600)", "os.fchmod(stream.fileno(), 0o644)"),
    (TOK, "设置 token 写操作日志", "def _audit_change(\n    session: Session, context: AccountRequestContext, account: AccountRow, operation: OperationType\n) -> None:\n", "def _audit_change(\n    session: Session, context: AccountRequestContext, account: AccountRow, operation: OperationType\n) -> None:\n    return\n"),
    (SVC, "删暂存要管理员", "actor = authorize_admin_job_actor(session, request.identity, now=request.now)\n                    _download_cleanup.check_busy", "pass\n                    _download_cleanup.check_busy"),
    (SVC, "删暂存被占用 409", "_download_cleanup.check_busy(session, checked)\n                attempted", "pass\n                attempted"),
    (CLN, "占用判断按仓库", 'fields = ("storage_root", "repo_type", "repo_id")', 'fields = ("storage_root", "repo_type", "repo_id", "never")'),
]
for path, name, old, new in MUTANTS:
    orig = path.read_text(); n = orig.count(old)
    if n != 1: print(f"跳过（匹配 {n} 处）：{name}"); continue
    path.write_text(orig.replace(old, new))
    try:
        r = subprocess.run([str(WT / ".venv/bin/pytest"), "-q", "-x", "-p", "no:cacheprovider", "tests/test_download_page_api.py"], cwd=WT, capture_output=True, text=True, timeout=600)
        print(("被抓住" if r.returncode != 0 else "漏网") + f"：{name}")
    finally:
        path.write_text(orig)
