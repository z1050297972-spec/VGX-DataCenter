"""一键部署只读查询契约清单；只用临时配置/数据库和注入的系统元数据。"""

import json
import sqlite3
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from accounts_support import model_row
from ops_support import runtime_inputs

from rdp.infra.config import WebConfig, load_config
from rdp.infra.db.connection import create_database_engine
from rdp.infra.diagnostics import ExternalError, InputError
from rdp.infra.state import state_paths
from rdp.ops.setup_queries import (
    AdministratorPresence,
    accessible_urls,
    administrator_presence,
    mounted_storage_candidates,
    run_setup_query,
    validate_setup_configuration,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试进程HOME始终在本次临时目录，阻断依赖的用户配置发现。"""
    monkeypatch.setenv("HOME", str(tmp_path))


def test_validate_reuses_platform_config(tmp_path: Path) -> None:
    """验证契约：validate_setup_configuration返回原LoadedConfig模型，未知键/范围/存储登记仍由load_config唯一校验，保留来源和home展开。"""
    config = tmp_path / "config.toml"
    config.write_text('state_dir = "~/state"\n[web]\nport = 9123\n')
    result = validate_setup_configuration(config, home=tmp_path)
    assert result == load_config(environ={"RDP_CONFIG": str(config)}, home=tmp_path)
    assert result.source == config and not result.used_defaults
    assert result.config.state_dir == tmp_path / "state"
    config.write_text("unknown = 1")
    with pytest.raises(ValueError, match="unknown"):
        validate_setup_configuration(config, home=tmp_path)
    config.write_text("[web]\nport = 65536")
    with pytest.raises(ValueError, match="web.port"):
        validate_setup_configuration(config, home=tmp_path)


def test_validate_missing_is_not_defaults(tmp_path: Path) -> None:
    """验证契约：显式文件缺失报FileNotFoundError，坏TOML/路径报ValueError、权限故障保留OSError，不拿默认配置冒充成功。"""
    with pytest.raises(FileNotFoundError):
        validate_setup_configuration(tmp_path / "missing", home=tmp_path)
    with pytest.raises(ValueError):
        validate_setup_configuration(Path("relative"), home=tmp_path)
    with pytest.raises(OSError):
        validate_setup_configuration(tmp_path, home=tmp_path)
    broken = tmp_path / "broken"
    broken.write_text("unclosed = [")
    with pytest.raises(ValueError):
        validate_setup_configuration(broken, home=tmp_path)


def test_validate_does_not_initialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：校验不创建状态/导航/日志目录，不连接数据库、不执行命令或访问存储根，配置字节和权限不变。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "config.toml"
    config.write_text('state_dir = "~/state"\nnav_root = "~/nav"\n[jobs]\ngpus = []')
    config.chmod(0o640)
    before = config.read_bytes(), config.stat().st_mode
    validate_setup_configuration(config, home=tmp_path)
    assert list(tmp_path.iterdir()) == [config]
    assert (config.read_bytes(), config.stat().st_mode) == before


def test_admin_missing_absent_present(tmp_path: Path) -> None:
    """验证契约：缺库为database_missing且不建文件；最新空库为absent；启用或停用管理员均present，只有成员仍absent。"""
    missing = tmp_path / "missing.sqlite3"
    assert administrator_presence(missing) == AdministratorPresence.DATABASE_MISSING
    assert not missing.exists()
    inputs = runtime_inputs(tmp_path)
    database = state_paths(
        load_config(environ=inputs.environ, home=inputs.home).config, ()
    ).database
    assert administrator_presence(database) == AdministratorPresence.ABSENT
    engine = create_database_engine(database)
    try:
        from rdp.infra.db.connection import session_scope

        with session_scope(engine) as session:
            session.add(model_row())
        assert administrator_presence(database) == AdministratorPresence.ABSENT
        with session_scope(engine) as session:
            session.add(model_row("admin", "administrator", status="disabled"))
        assert administrator_presence(database) == AdministratorPresence.PRESENT
    finally:
        engine.dispose()


def test_admin_database_errors(tmp_path: Path) -> None:
    """验证契约：空库无版本、旧版、未知版、损坏、软链接/目录及I/O故障拒绝，不能归为absent；连接在失败时关闭。"""
    for name, contents in (("empty", b""), ("corrupt", b"bad database")):
        database = tmp_path / name
        database.write_bytes(contents)
        with pytest.raises(InputError):
            administrator_presence(database)
    with pytest.raises(ExternalError):
        administrator_presence(tmp_path)
    dangling = tmp_path / "link"
    dangling.symlink_to(tmp_path / "missing")
    with pytest.raises(ExternalError):
        administrator_presence(dangling)
    with pytest.raises(InputError):
        administrator_presence(Path("relative"))


def test_admin_read_only_no_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：管理员检查使用只读连接、只取存在性，不select口令/会话、不改journal_mode、不写账号或审计。"""
    inputs = runtime_inputs(tmp_path)
    database = state_paths(
        load_config(environ=inputs.environ, home=inputs.home).config, ()
    ).database
    original = sqlite3.connect
    statements: list[str] = []
    modes: list[str] = []

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        modes.append(str(args[0]))
        connection = original(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    before = database.read_bytes()
    assert administrator_presence(database) == AdministratorPresence.ABSENT
    assert database.read_bytes() == before
    assert all("?mode=ro" in uri for uri in modes)
    sql = " ".join(statements).lower()
    assert "query_only=on" in sql
    assert "select 1 from accounts" in sql and "limit 1" in sql
    assert not any(
        word in sql for word in ("password", "token", "journal_mode", "insert", "update")
    )


def test_admin_snapshot_not_reservation(tmp_path: Path) -> None:
    """验证契约：存在性只代表查询快照，不创建或预留账号；之后既有create_first_admin仍负责并发首号约束。"""
    from accounts_support import EXAMPLE_SECRET, NOW
    from argon2 import PasswordHasher

    from rdp.accounts.security import PasswordCodec
    from rdp.accounts.service import AccountService
    from rdp.accounts.types import Credentials, NewAccount, Role
    from rdp.audit.types import OPS_AUDIT_CONTEXT
    from rdp.infra.diagnostics import ConflictError

    inputs = runtime_inputs(tmp_path)
    database = state_paths(
        load_config(environ=inputs.environ, home=inputs.home).config, ()
    ).database
    assert administrator_presence(database) == AdministratorPresence.ABSENT
    engine = create_database_engine(database)
    try:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        request = NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR)
        service.create_first_admin(request, now=NOW, audit=OPS_AUDIT_CONTEXT)
        assert administrator_presence(database) == AdministratorPresence.PRESENT
        with pytest.raises(ConflictError):
            service.create_first_admin(request, now=NOW, audit=OPS_AUDIT_CONTEXT)
    finally:
        engine.dispose()


def test_mount_metadata_sources() -> None:
    """验证契约：从独立findmnt样本取得ext4 UUID、NFS导出和ro/rw，UUID只规范化，不用路径哈希或猜设备号，丢弃其他挂载选项。"""
    snapshot = {
        "filesystems": [
            {
                "target": "/data/z",
                "source": "/dev/sda",
                "fstype": "ext4",
                "uuid": "123E4567-E89B-42D3-A456-426614174000",
                "options": "ro,relatime",
            },
            {
                "target": "/data/a",
                "source": "nas:/share",
                "fstype": "nfs4",
                "uuid": None,
                "options": "rw,secret=hidden",
            },
        ]
    }
    roots = mounted_storage_candidates(json.dumps(snapshot))
    assert [str(root.path) for root in roots] == ["/data/a", "/data/z"]
    assert roots[0].nfs_export == "nas:/share" and not roots[0].read_only
    assert roots[1].uuid == "123e4567-e89b-42d3-a456-426614174000" and roots[1].read_only
    assert all(root.unavailable_reason is None for root in roots)
    assert "secret" not in repr(roots)


def test_mount_unavailable_reasons() -> None:
    """验证契约：未知文件系统、缺UUID和非法NFS来源保留展示行并给不可选原因，不凭rw授予平台写权限。"""
    rows = [
        {"target": "/data/a", "source": "/dev/a", "fstype": "ext4", "uuid": None, "options": "rw"},
        {
            "target": "/data/b",
            "source": "bad source",
            "fstype": "nfs",
            "uuid": None,
            "options": "ro",
        },
        {"target": "/data/c", "source": "tmpfs", "fstype": "tmpfs", "uuid": None, "options": "rw"},
    ]
    roots = mounted_storage_candidates(json.dumps({"filesystems": rows}))
    assert [root.unavailable_reason for root in roots] == [
        "missing_uuid",
        "invalid_source",
        "unsupported_filesystem",
    ]
    assert all(root.uuid is None and root.nfs_export is None for root in roots)


def test_mount_invalid_snapshot() -> None:
    """验证契约：坏JSON、缺字段、非法类型、重复挂载点、ro/rw冲突、超行数和超字节均失败，错误不回显原始挂载选项。"""
    valid = {
        "target": "/data/a",
        "source": "/dev/a",
        "fstype": "ext4",
        "uuid": None,
        "options": "rw",
    }
    invalid: list[object] = [
        None,
        [],
        {},
        {"filesystems": [valid, valid]},
        {"filesystems": [valid] * 4097},
    ]
    invalid.extend(
        {"filesystems": [valid | change]}
        for change in (
            {"options": "ro,rw,secret=hidden"},
            {"options": "relatime"},
            {"target": "relative"},
            {"target": "/data/../bad"},
            {"fstype": 4},
            {"uuid": 7},
        )
    )
    invalid.append(
        {"filesystems": [{key: value for key, value in valid.items() if key != "source"}]}
    )
    for value in invalid:
        with pytest.raises(ValueError) as caught:
            mounted_storage_candidates(json.dumps(value))
        assert "secret" not in str(caught.value)
    for text in ("{", " " * (2 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            mounted_storage_candidates(text)


def test_mount_no_storage_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：挂载候选解析仅消费传入快照，不stat/resolve/open候选路径，不读设备、不挂载、不写文件。"""

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("纯解析不能访问路径")

    with monkeypatch.context() as patch:
        for method in ("stat", "resolve", "open"):
            patch.setattr(Path, method, forbidden)
        result = mounted_storage_candidates(
            '{"filesystems":[{"target":"/data/offline","source":"nas:/archive","fstype":"nfs","uuid":null,"options":"ro"}]}'
        )
    assert result[0].path == Path("/data/offline")


def test_urls_listen_scope() -> None:
    """验证契约：0.0.0.0只列IPv4、::只列IPv6，回环优先并去重；明确绑定地址不返回其他网卡地址，IPv6括号与scope编码正确。"""
    snapshot = json.dumps(
        [
            {
                "ifname": "eth0",
                "addr_info": [
                    {"family": "inet", "local": "192.0.2.10", "scope": "global"},
                    {"family": "inet", "local": "192.0.2.2", "scope": "global"},
                    {"family": "inet", "local": "192.0.2.2", "scope": "global"},
                    {"family": "inet6", "local": "fe80::2", "scope": "link"},
                    {"family": "inet6", "local": "2001:db8::1", "scope": "global"},
                ],
            }
        ]
    )
    assert accessible_urls(WebConfig(port=9001), snapshot) == (
        "http://127.0.0.1:9001/",
        "http://192.0.2.2:9001/",
        "http://192.0.2.10:9001/",
    )
    assert accessible_urls(WebConfig(host="::", port=9001), snapshot) == (
        "http://[::1]:9001/",
        "http://[2001:db8::1]:9001/",
        "http://[fe80::2%25eth0]:9001/",
    )
    assert accessible_urls(WebConfig(host="127.0.0.1", port=9001), snapshot) == (
        "http://127.0.0.1:9001/",
    )


def test_urls_invalid_snapshot() -> None:
    """验证契约：网卡JSON大小/数量/形状、IP和family不符或非法接口名拒绝，不把失败伪装成没有网卡。"""
    entry = {"family": "inet", "local": "192.0.2.2", "scope": "global"}
    cases: list[object] = [
        None,
        {},
        [{}],
        [{"ifname": "bad/name", "addr_info": []}],
        [{"ifname": "eth0", "addr_info": [entry | {"family": "inet6"}]}],
        [{"ifname": "eth0", "addr_info": [entry] * 4097}],
        [{"ifname": "eth0", "addr_info": [{"local": "bad"}]}],
    ]
    for case in cases:
        with pytest.raises(ValueError):
            accessible_urls(WebConfig(), json.dumps(case))
    with pytest.raises(ValueError):
        accessible_urls(WebConfig(), " " * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        accessible_urls(WebConfig(host="user@host"), "[]")


def test_urls_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：地址生成不解析DNS、不发HTTP或探测路由；明确主机名保持合法URL，返回值不包含未指定或组播地址。"""
    import socket

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("地址列表不得探测网络")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert accessible_urls(WebConfig(host="example.test"), "[]") == ("http://example.test:8600/",)
    snapshot = json.dumps(
        [
            {
                "ifname": "eth0",
                "addr_info": [
                    {"family": "inet", "local": "0.0.0.0", "scope": "global"},  # noqa: S104  # 理由：纯解析样本。
                    {"family": "inet", "local": "224.0.0.1", "scope": "global"},
                ],
            }
        ]
    )
    assert accessible_urls(WebConfig(), snapshot) == ("http://127.0.0.1:8600/",)


def test_query_cli_json_contract(tmp_path: Path) -> None:
    """验证契约：四个只读命令输出各自安全JSON白名单且无半份结果，缺库状态独立于absent，Path/枚举/null编码固定。"""
    config = tmp_path / "config.toml"
    config.write_text('state_dir = "~/state"\nnav_root = "~/nav"\n[jobs]\ngpus = []')
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"filesystems":[]}')
    output, errors = StringIO(), StringIO()
    assert (
        run_setup_query(
            ["validate-config", "--config", str(config)],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 0
    )
    payload = json.loads(output.getvalue())
    assert set(payload) == {"config_file", "state_dir", "nav_root", "web", "gpus", "storage_roots"}
    assert payload["state_dir"] == str(tmp_path / "state")
    cases: list[tuple[list[str], dict[str, Any]]] = [
        (
            ["administrator", "--database", str(tmp_path / "missing")],
            {"status": "database_missing"},
        ),
        (["mounts", "--input", str(snapshot)], {"items": []}),
    ]
    for args, expected in cases:
        output = StringIO()
        assert run_setup_query(args, home=tmp_path, stdout=output, stderr=errors) == 0
        assert json.loads(output.getvalue()) == expected
        assert output.getvalue().count("\n") == 1
    snapshot.write_text("[]")
    output = StringIO()
    assert (
        run_setup_query(
            ["urls", "--config", str(config), "--input", str(snapshot)],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 0
    )
    assert json.loads(output.getvalue()) == {"urls": ["http://127.0.0.1:8600/"]}
    assert not errors.getvalue()


def test_query_cli_exit_codes(tmp_path: Path) -> None:
    """验证契约：顶层/子命令帮助0，参数错误2，校验/查询失败1且stderr有安全说明，stdout不回显配置/环境全文。"""
    for args, expected in [
        (["--help"], 0),
        (["administrator", "--help"], 0),
        ([], 2),
        (["mounts"], 2),
        (["unknown"], 2),
        (["validate-config", "--config", str(tmp_path / "missing")], 1),
    ]:
        output, errors = StringIO(), StringIO()
        assert run_setup_query(args, home=tmp_path, stdout=output, stderr=errors) == expected
        if expected:
            assert errors.getvalue() and not output.getvalue()
        else:
            assert "usage" in output.getvalue()
    config = tmp_path / "config.toml"
    config.write_text('secret = "sensitive-value"')
    output, errors = StringIO(), StringIO()
    assert (
        run_setup_query(
            ["validate-config", "--config", str(config)],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 1
    )
    assert "sensitive-value" not in errors.getvalue() + output.getvalue()


def test_query_cli_bounded_reads(tmp_path: Path) -> None:
    """验证契约：快照文件最多读上限加一字节，超限拒绝；不等stdin、不打开设备作为无限输入，路径错误保留来源。"""
    import os

    snapshot = tmp_path / "large"
    snapshot.write_bytes(b" " * (2 * 1024 * 1024) + b"[]")
    output, errors = StringIO(), StringIO()
    assert (
        run_setup_query(
            ["mounts", "--input", str(snapshot)], home=tmp_path, stdout=output, stderr=errors
        )
        == 1
    )
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    # 子进程超时保证错误实现不会把测试永久卡在FIFO打开上。
    import subprocess
    import sys

    result = subprocess.run(  # noqa: S603  # 理由：固定解释器、临时FIFO和有界子进程。
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; from rdp.ops.setup_queries import run_setup_query; sys.exit(run_setup_query(sys.argv[1:], home=Path.home(), stdout=sys.stdout, stderr=sys.stderr))",
            "mounts",
            "--input",
            str(fifo),
        ],
        env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
        capture_output=True,
        timeout=2,
        check=False,
    )
    assert result.returncode == 1 and result.stderr and not result.stdout


def test_query_cli_no_business_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：只读命令不下载、建目录、迁移、创建/重置账号、启动服务或写操作日志，调用现有业务函数即测试失败。"""
    import subprocess

    import rdp.infra.db.migration
    import rdp.infra.state

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("只读查询调用了写入边界")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(rdp.infra.state, "initialize_state", forbidden)
    monkeypatch.setattr(rdp.infra.db.migration, "migrate", forbidden)
    output, errors = StringIO(), StringIO()
    assert (
        run_setup_query(
            ["administrator", "--database", str(tmp_path / "absent")],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 0
    )
    assert list(tmp_path.iterdir()) == []


def test_query_main_argument_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """验证契约：main(None)使用sys.argv，显式空列表不回退；系统依赖调用时绑定，模块导入无文件或home访问。"""
    import sys

    from rdp.ops.setup_queries import main

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["query", "--help"])
    assert main(None) == 0
    assert "usage" in capsys.readouterr().out
    assert main([]) == 2
    assert capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_validate_rejects_nonregular_file(tmp_path: Path) -> None:
    """验证配置普通文件前置条件；FIFO不会让校验进程等待生产者。"""
    import os
    import subprocess
    import sys

    fifo = tmp_path / "config.pipe"
    os.mkfifo(fifo)
    result = subprocess.run(  # noqa: S603  # 理由：固定查询入口与临时FIFO，有界等待自动回收。
        [sys.executable, "-m", "rdp.ops.setup_queries", "validate-config", "--config", str(fifo)],
        env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    assert result.returncode == 1 and not result.stdout
    assert "OSError" in result.stderr


def test_query_failure_preserves_safe_remediation(tmp_path: Path) -> None:
    """验证失败诊断保留输入路径、平台修复步骤，并隐藏未知配置值。"""
    config = tmp_path / "missing.toml"
    output, errors = StringIO(), StringIO()
    assert (
        run_setup_query(
            ["validate-config", "--config", str(config)],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 1
    )
    assert str(config) in errors.getvalue()
    database = tmp_path / "empty.sqlite3"
    database.touch()
    errors = StringIO()
    assert (
        run_setup_query(
            ["administrator", "--database", str(database)],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 1
    )
    assert "migrate" in errors.getvalue() and str(database) in errors.getvalue()
    config.write_text('unexpected = "do-not-disclose"')
    errors = StringIO()
    assert (
        run_setup_query(
            ["validate-config", "--config", str(config)],
            home=tmp_path,
            stdout=output,
            stderr=errors,
        )
        == 1
    )
    assert "unexpected" in errors.getvalue() and "do-not-disclose" not in errors.getvalue()
    assert output.getvalue() == ""
