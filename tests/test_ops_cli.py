"""第 11 张 cli 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import io
import logging
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from ops_support import runtime_inputs

from rdp import cli as entry
from rdp.ops.cli import Command, Console, parse_command, run_cli, run_maintenance


def _console() -> Console:
    """用内存流和固定非真实密码代替终端。"""
    return Console(io.StringIO(), io.StringIO(), lambda _: "test-password-value")


def test_help_without_environment() -> None:
    """验证契约：验收1：顶层和 web/worker/migrate/create-admin/reset-password/status 的 --help 返回0，不读配置、不建目录。"""
    for command in (
        [],
        ["web"],
        ["worker"],
        ["migrate"],
        ["create-admin"],
        ["reset-password"],
        ["status"],
    ):
        console = _console()
        with pytest.raises(SystemExit) as caught:
            parse_command([*command, "--help"], console=console)
        assert caught.value.code == 0
        assert "usage:" in cast(io.StringIO, console.stdout).getvalue()
        assert cast(io.StringIO, console.stderr).getvalue() == ""


def test_invalid_arguments() -> None:
    """验证契约：验收1：缺命令、缺账号参数、未知选项、缩写和 status 互斥选项冲突返回2，不执行动作。"""
    for args in (
        [],
        ["unknown"],
        ["create-admin"],
        ["reset-password"],
        ["web", "--no-st"],
        ["web", "--password", "hidden"],
        ["status"],
        ["status", "--active-jobs", "--worker-stopped"],
    ):
        console = _console()
        with pytest.raises(SystemExit) as caught:
            parse_command(args, console=console)
        assert caught.value.code == 2
        assert cast(io.StringIO, console.stderr).getvalue()
    assert parse_command(["worker", "--no-stderr"], console=_console()) == Command("worker", True)
    assert (
        parse_command(["create-admin", "admin", "管理员"], console=_console()).display_name
        == "管理员"
    )


def test_main_argument_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：main(None) 使用 sys.argv，显式空序列不回退；生产依赖在调用时创建，导入无副作用。"""
    dispatch = Mock(return_value=7)
    monkeypatch.setattr(entry, "run_cli", dispatch, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["rdp", "--version"])
    assert entry.main(None) == 7
    assert dispatch.call_args.args[0] == ["--version"]
    assert dispatch.call_args.kwargs["inputs"].home == tmp_path
    assert entry.main([]) == 7
    assert dispatch.call_args.args[0] == []
    assert list(tmp_path.iterdir()) == []


def test_console_entry_registration() -> None:
    """验证契约：pyproject 的 rdp 入口与 python -m rdp 共用 main；进程包装用 sys.exit 保留非零退出码。"""
    import ast
    import tomllib

    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["rdp"] == "rdp.cli:main"
    source = ast.parse((root / "src/rdp/__main__.py").read_text())
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
        for node in ast.walk(source)
    )


def test_version_output(tmp_path: Path) -> None:
    """验证契约：M2：--version 输出包版本与七位提交号加换行，不初始化数据库或日志，不调用 git。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    console = _console()
    forbidden = Mock(side_effect=AssertionError("不能启动服务"))
    assert (
        run_cli(["--version"], inputs=inputs, console=console, web=forbidden, signals=forbidden)
        == 0
    )
    assert cast(io.StringIO, console.stdout).getvalue() == "0.1.0 (aaaaaaa)\n"
    assert not (inputs.home / "state").exists()


def test_service_version_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：验收1：旧版、领先版、未知版、无版本和缺失数据库均拒绝 web/worker，提示 rdp migrate，不调用运行器。"""
    import sqlite3

    for index, revision in enumerate(
        (None, "0005_job_scheduling", "9999_future", "unknown", "empty")
    ):
        inputs = runtime_inputs(tmp_path / str(index), migrated=revision is not None)
        if revision is not None:
            database = inputs.home / "state/platform.sqlite3"
            from rdp.infra.config import load_config
            from rdp.infra.state import state_paths

            database = state_paths(
                load_config(environ=inputs.environ, home=inputs.home).config, ()
            ).database
            with sqlite3.connect(database) as connection:
                if revision == "empty":
                    connection.execute("DROP TABLE alembic_version")
                else:
                    connection.execute("UPDATE alembic_version SET version_num=?", (revision,))
        for name in ("web", "worker"):
            forbidden = Mock(side_effect=AssertionError("版本不符不能启动"))
            assert (
                run_cli([name], inputs=inputs, console=_console(), web=forbidden, signals=forbidden)
                == 1
            )
            forbidden.assert_not_called()
            assert "rdp migrate" in capsys.readouterr().err


def test_no_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：验收2：web/worker --no-stderr 时启动及运行错误日志只写各自文件，stderr 无日志。"""
    inputs = runtime_inputs(tmp_path)

    def web(runtime: object) -> int:
        from rdp.ops.runtime import ServiceRuntime

        assert isinstance(runtime, ServiceRuntime)
        try:
            logging.getLogger("rdp.test").error("运行故障")
            return 1
        finally:
            runtime.engine.dispose()

    assert (
        run_cli(
            ["web", "--no-stderr"],
            inputs=inputs,
            console=_console(),
            web=web,
            signals=lambda _: nullcontext(),
        )
        == 1
    )
    assert capsys.readouterr().err == ""
    assert "运行故障" in (inputs.home / "state/logs/web.log").read_text()


def test_foreground_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：前台默认同时写 stderr 和本进程文件，--no-stderr 不串改另一个进程的设置。"""
    inputs = runtime_inputs(tmp_path)

    def web(runtime: object) -> int:
        from rdp.ops.runtime import ServiceRuntime

        assert isinstance(runtime, ServiceRuntime)
        runtime.engine.dispose()
        logging.getLogger("rdp.test").info("前台输出")
        return 0

    assert (
        run_cli(
            ["web"], inputs=inputs, console=_console(), web=web, signals=lambda _: nullcontext()
        )
        == 0
    )
    assert "前台输出" in capsys.readouterr().err
    assert "前台输出" in (inputs.home / "state/logs/web.log").read_text()


def test_migrate_dispatch(tmp_path: Path) -> None:
    """验证契约：migrate 只初始化状态并迁移到唯一 head，输出版本/备份摘要，不装配前端、调度或 GPU。"""
    from rdp.infra.config import load_config
    from rdp.infra.db.migration import check_database_version
    from rdp.infra.state import state_paths

    inputs = runtime_inputs(tmp_path, migrated=False)
    console = _console()
    assert run_maintenance(Command("migrate"), inputs=inputs, console=console) == 0
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    check_database_version(paths.database)
    assert "0020_dataset_collection" in cast(io.StringIO, console.stdout).getvalue()


def test_accounts_require_current_database(tmp_path: Path) -> None:
    """验证契约：账号命令拒绝旧库，不自动迁移，不在读取密码前开始写事务；失败关闭引擎。"""
    from rdp.infra.diagnostics import InputError

    inputs = runtime_inputs(tmp_path, migrated=False)
    read = Mock(side_effect=AssertionError("不能读密码"))
    console = Console(io.StringIO(), io.StringIO(), read)
    for command in (
        Command("create-admin", login_name="admin", display_name="管理"),
        Command("reset-password", login_name="admin"),
    ):
        with pytest.raises(InputError):
            run_maintenance(command, inputs=inputs, console=console)
    read.assert_not_called()
    assert not (inputs.home / "state").exists()


def test_create_admin_dispatch(tmp_path: Path) -> None:
    """验证契约：创建首管理员使用登录名、显示名、注入时刻和两次无回显读取；成功只记已有领域的一条操作日志。"""
    from sqlalchemy import select

    from rdp.accounts.models import AccountRow
    from rdp.audit.models import OperationLogRow
    from rdp.infra.config import load_config
    from rdp.infra.db.connection import create_database_engine, session_scope
    from rdp.infra.state import state_paths

    inputs = runtime_inputs(tmp_path)
    read = Mock(return_value="test-password-value")
    assert (
        run_maintenance(
            Command("create-admin", login_name="admin", display_name="管理"),
            inputs=inputs,
            console=Console(io.StringIO(), io.StringIO(), read),
        )
        == 0
    )
    assert read.call_count == 2
    engine = create_database_engine(
        state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ()).database
    )
    try:
        with session_scope(engine, read_only=True) as session:
            assert session.scalars(select(AccountRow)).one().login_name == "admin"
            assert session.scalars(select(OperationLogRow)).one().actor_name == "运维"
    finally:
        engine.dispose()


def test_reset_password_sessions(tmp_path: Path) -> None:
    """验证契约：验收4：经命令重置后原有全部会话失效，角色和启停状态不变，下次登录必须改密码。"""
    from account_api_support import api_case
    from accounts_support import AUDIT_CONTEXT, EXAMPLE_SECRET, NOW

    from rdp.accounts.errors import AuthenticationError
    from rdp.accounts.types import Credentials

    inputs = runtime_inputs(tmp_path)
    with api_case(inputs.home / "state") as case:
        assert case.login().status_code == 200
        grant = case.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        assert (
            run_maintenance(
                Command("reset-password", login_name="admin"), inputs=inputs, console=_console()
            )
            == 0
        )
        assert case.client.get("/api/auth/me").status_code == 401
        with pytest.raises(AuthenticationError):
            case.service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT)
        response = case.client.post(
            "/api/auth/login", json={"login_name": "admin", "password": "test-password-value"}
        )
        assert response.status_code == 200
        assert response.json()["must_change_password"] is True
        assert response.json()["role"] == "administrator"
        assert response.json()["status"] == "enabled"
        assert case.client.get("/api/version").status_code == 403


def test_reset_password_audit(tmp_path: Path) -> None:
    """验证契约：验收4：重置成功恰好一条操作日志且操作人为“运维”，密码/哈希不得出现在日志或错误中。"""
    from account_api_support import api_case
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import session_scope

    inputs = runtime_inputs(tmp_path)
    with api_case(inputs.home / "state") as case:
        with session_scope(case.engine, read_only=True) as session:
            before = len(session.scalars(select(OperationLogRow)).all())
        console = _console()
        assert (
            run_maintenance(
                Command("reset-password", login_name="admin"), inputs=inputs, console=console
            )
            == 0
        )
        with session_scope(case.engine, read_only=True) as session:
            rows = session.scalars(select(OperationLogRow).order_by(OperationLogRow.log_id)).all()
            assert len(rows) == before + 1
            assert rows[-1].actor_id is None and rows[-1].actor_name == "运维"
            assert "test-password-value" not in str(rows[-1].details)
        assert (
            "test-password-value"
            not in cast(io.StringIO, console.stdout).getvalue()
            + cast(io.StringIO, console.stderr).getvalue()
        )


def test_account_input_failure(tmp_path: Path) -> None:
    """验证契约：两次密码不一致、账号不存在、已有管理员及无回显失败返回非0，不留下部分账号变更。"""
    inputs = runtime_inputs(tmp_path)
    console = Console(
        io.StringIO(),
        io.StringIO(),
        Mock(side_effect=["different-first-value", "different-second-value"]),
    )
    assert (
        run_cli(
            ["create-admin", "admin", "管理员"],
            inputs=inputs,
            console=console,
            web=Mock(),
            signals=lambda _: nullcontext(),
        )
        == 1
    )
    assert (
        run_maintenance(
            Command("create-admin", login_name="admin", display_name="管理员"),
            inputs=inputs,
            console=_console(),
        )
        == 0
    )
    for args in (["create-admin", "another", "管理"], ["reset-password", "missing"]):
        assert (
            run_cli(
                args, inputs=inputs, console=_console(), web=Mock(), signals=lambda _: nullcontext()
            )
            == 1
        )


def test_account_interrupt(tmp_path: Path) -> None:
    """验证契约：输入 EOF/Ctrl-C 返回130，事务尚未开始，不输出密码。"""
    inputs = runtime_inputs(tmp_path)
    for error in (EOFError(), KeyboardInterrupt()):
        console = Console(io.StringIO(), io.StringIO(), Mock(side_effect=error))
        assert (
            run_cli(
                ["create-admin", "admin", "管理"],
                inputs=inputs,
                console=console,
                web=Mock(),
                signals=lambda _: nullcontext(),
            )
            == 130
        )
        assert cast(io.StringIO, console.stdout).getvalue() == ""
    assert (
        run_maintenance(
            Command("create-admin", login_name="admin", display_name="管理"),
            inputs=inputs,
            console=_console(),
        )
        == 0
    )


def test_status_exit_codes(tmp_path: Path) -> None:
    """验证契约：status --active-jobs空闲0、活跃3；--worker-stopped未持锁0、持锁3；查询错误1，不能当成安全可升级。"""
    import fcntl

    from jobs_storage_support import job_row

    from rdp.infra.config import load_config
    from rdp.infra.db.connection import create_database_engine, session_scope
    from rdp.infra.state import state_paths
    from rdp.jobs.types import JobState

    inputs = runtime_inputs(tmp_path)

    def run(option: str) -> int:
        return run_cli(
            ["status", option],
            inputs=inputs,
            console=_console(),
            web=Mock(),
            signals=lambda _: nullcontext(),
        )

    assert run("--active-jobs") == 0
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            session.add(job_row(JobState.RUNNING))
        assert run("--active-jobs") == 3
    finally:
        engine.dispose()
    assert run("--worker-stopped") == 0
    with paths.worker_lock.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run("--worker-stopped") == 3


def test_status_does_not_initialize(tmp_path: Path) -> None:
    """验证契约：status 和 --version 不建日志或状态目录、不创建空数据库、不调用维护命令。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    for option, code in (("--active-jobs", 1), ("--worker-stopped", 0)):
        assert (
            run_cli(
                ["status", option],
                inputs=inputs,
                console=_console(),
                web=Mock(),
                signals=lambda _: nullcontext(),
            )
            == code
        )
        assert not (inputs.home / "state").exists()


def test_status_port(tmp_path: Path) -> None:
    """验证契约：status --check-port 使用最终配置，空闲0、占用或检查失败非0，不连接数据库或调用 systemctl。"""
    import socket

    inputs = runtime_inputs(tmp_path, migrated=False)
    config = tmp_path / "config.toml"
    original = config.read_text()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        config.write_text(original + f'[web]\nhost="127.0.0.1"\nport={port}\n')
        assert (
            run_cli(
                ["status", "--check-port"],
                inputs=inputs,
                console=_console(),
                web=Mock(),
                signals=lambda _: nullcontext(),
            )
            == 1
        )
    assert (
        run_cli(
            ["status", "--check-port"],
            inputs=inputs,
            console=_console(),
            web=Mock(),
            signals=lambda _: nullcontext(),
        )
        == 0
    )
    assert not (inputs.home / "state").exists()


def test_boundary_error_once(tmp_path: Path) -> None:
    """验证契约：配置/装配/维护失败仅在命令边界报告一次，诊断保留对象、实际、后果和下一步。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    (tmp_path / "config.toml").write_text("unknown=1")
    console = _console()
    assert (
        run_cli(
            ["web"], inputs=inputs, console=console, web=Mock(), signals=lambda _: nullcontext()
        )
        == 1
    )
    assert cast(io.StringIO, console.stderr).getvalue().count("运维命令失败") == 1
    assert "unknown" in cast(io.StringIO, console.stderr).getvalue()
    assert not (inputs.home / "state").exists()


def test_web_adapter(tmp_path: Path) -> None:
    """包入口把同一资源传给Web生命周期，运行器返回后释放引擎。"""
    from rdp.ops.runtime import prepare_service

    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("web", no_stderr=True, inputs=inputs)
    runner = Mock()
    assert entry.run_web(runtime, inputs=inputs, runner=runner) == 0
    assert runner.call_args.args[0].state.database_engine is runtime.engine


def test_command_help_descriptions() -> None:
    """总帮助和各子命令帮助均说明用途，status明确区分正常、阻止维护和检查失败退出码。"""
    descriptions = {
        "web": "启动 Web 服务",
        "worker": "启动后台作业 worker",
        "migrate": "升级数据库到当前版本",
        "create-admin": "创建首个管理员",
        "reset-password": "重置账号密码并撤销旧会话",
        "status": "只读检查作业、worker 锁或监听端口",
    }
    console = _console()
    with pytest.raises(SystemExit) as caught:
        parse_command(["--help"], console=console)
    assert caught.value.code == 0
    overview = cast(io.StringIO, console.stdout).getvalue()
    for command, description in descriptions.items():
        assert command in overview and description in overview
        console = _console()
        with pytest.raises(SystemExit) as caught:
            parse_command([command, "--help"], console=console)
        assert caught.value.code == 0
        assert description in cast(io.StringIO, console.stdout).getvalue()
    status = cast(io.StringIO, console.stdout).getvalue()
    for fragment in (
        "0：无活跃作业",
        "3：有活跃作业",
        "运行中",
        "正在取消",
        "0：锁未被持有",
        "3：锁被占用",
        "0：端口可用",
        "1：占用或检查失败",
        "1：检查失败",
        "2：参数错误",
    ):
        assert fragment in status
