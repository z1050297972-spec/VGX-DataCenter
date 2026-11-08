"""M1-03验收2至7的契约测试清单；只用临时导航层/数据库，不读真实部署或存储路径。"""

from pathlib import Path

import pytest
from dataset_api_support import ENTRY, FORMAT_ENTRY, browser_case
from datasets_execution_support import dataset_case
from nav_manifest import FakeNavigation


def test_storage_import_boundary(tmp_path: Path) -> None:
    """验收2：真实禁入配置允许reading/fingerprint，直接及经辅助模块的存储访问导入均被工具拒绝。"""
    import os
    import shutil
    import subprocess
    import tomllib

    root = Path(__file__).parents[1]
    config_text = (root / "pyproject.toml").read_text()
    contract = tomllib.loads(config_text)["tool"]["importlinter"]["contracts"][-1]
    assert contract["source_modules"] == [
        "rdp.jobs.dataset_browser.queries",
        "rdp.jobs.dataset_browser.schemas",
    ]
    assert contract["allow_indirect_imports"] is False
    assert "ignore_imports" not in contract
    shutil.copytree(
        root / "src/rdp", tmp_path / "rdp", ignore=shutil.ignore_patterns("__pycache__")
    )
    config = tmp_path / "pyproject.toml"
    config.write_text(config_text)
    queries = tmp_path / "rdp/jobs/dataset_browser/queries.py"
    original = queries.read_text()
    environment = os.environ | {"PYTHONPATH": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}

    def check() -> subprocess.CompletedProcess[str]:
        # 固定已安装检查器和临时源码，不通过shell，也不加载平台配置。
        return subprocess.run(  # noqa: S603  # 理由：只执行固定已安装检查器与临时配置。
            [
                str(root / ".venv/bin/lint-imports"),
                "--config",
                str(config),
                "--no-cache",
                "--no-logo",
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    assert check().returncode == 0
    for forbidden in contract["forbidden_modules"]:
        queries.write_text(original + "\nimport " + forbidden + "\n")
        result = check()
        assert result.returncode != 0
        assert "数据集接口不得依赖存储根访问 BROKEN" in result.stdout
    (queries.parent / "probe.py").write_text("import rdp.infra.storage\n")
    queries.write_text(original + "\nfrom rdp.jobs.dataset_browser import probe\n")
    assert check().returncode != 0


def test_all_endpoints_with_unreadable_storage_roots(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收2：全部数据集接口在假根chmod000且操作系统探针拒绝根访问时仍返回200。"""
    import os

    with browser_case(tmp_path / "state", fake_nav) as case:
        roots = tuple(root.path for root in fake_nav.storage_roots)
        opened = os.open
        modes = {root: root.stat().st_mode for root in roots}
        for root in roots:
            root.chmod(0)

        def guarded(
            file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if isinstance(file, (str, Path)):
                path = Path(file)
                assert not any(path.is_relative_to(root) for root in roots), "Web尝试打开存储根"
            return opened(file, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(os, "open", guarded)
        try:
            for suffix, query in (
                ("", {}),
                ("/trees", {}),
                ("/filters", {}),
                ("/panel", {}),
                ("/layout", {}),
                ("/detail", {"entry_path": ENTRY}),
                ("/subtasks", {"entry_path": ENTRY}),
            ):
                response = case.client.get("/api/datasets" + suffix, params=query)
                assert response.status_code == 200, response.text[:300]
            for method, suffix, payload, status in (
                ("POST", "/dataset-14/rescan", None, 201),
                ("POST", "/sizing", {"dataset_id": None}, 201),
                ("PUT", "/layout", {"layout": "B"}, 200),
            ):
                response = case.client.request(method, "/api/datasets" + suffix, json=payload)
                assert response.status_code == status, response.text
        finally:
            for root, mode in modes.items():
                root.chmod(mode)


def test_navigation_symlink_replacement_cannot_reach_storage(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收2/4：JSON软链接和入口目录换链都不跟随目标；子任务拒绝非普通项，不暴露目标正文。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        secret = tmp_path / "storage-secret.json"
        secret.write_text('{"SECRET_MARKER": true}')
        path = fake_nav.nav_root / ENTRY / "子任务.json"
        path.unlink()
        path.symlink_to(secret)
        response = case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY})
        assert response.status_code == 400
        assert "SECRET_MARKER" not in response.text
        entry = fake_nav.nav_root / ENTRY
        moved = entry.with_name("moved-entry")
        entry.rename(moved)
        entry.symlink_to(moved, target_is_directory=True)
        try:
            response = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
            assert response.status_code == 200, response.text
            assert response.json()["original_paths"]["content"] is None
            assert response.json()["index_stale"] is True
        finally:
            entry.unlink()
            moved.rename(entry)


def test_data_origin_unknown_and_invalid_value(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：M1全部unknown，已知来源为空，非法来源422，候选unknown独立。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        assert (
            case.client.get("/api/datasets", params={"data_origin": "unknown"}).json()["total"] == 5
        )
        assert case.client.get("/api/datasets", params={"data_origin": "real"}).json()["total"] == 0
        assert (
            case.client.get("/api/datasets", params={"data_origin": "invalid"}).status_code == 422
        )
        options = case.client.get("/api/datasets/filters").json()["data_origins"]
        assert options[-1] == {"value": "unknown", "label": "未知", "count": 5}


def test_filters_intersect_and_paginate_stably(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：多维交集、稳定分页、越末尾空页；树筛视图不丢列表跨视图位置。"""
    import json

    path = fake_nav.nav_root / ENTRY / "数据集信息.json"
    information = json.loads(path.read_bytes())
    information.update(robot_model="franka", fps=30)
    path.write_text(json.dumps(information))
    with browser_case(tmp_path / "state", fake_nav) as case:
        filtered = case.client.get(
            "/api/datasets", params={"robot_model": "franka", "fps": 30, "view": "format"}
        ).json()
        assert filtered["total"] == 1
        assert len(filtered["items"][0]["entries"]) == 2
        assert (
            case.client.get("/api/datasets", params={"robot_model": "franka", "fps": 31}).json()[
                "total"
            ]
            == 0
        )
        page1 = case.client.get("/api/datasets", params={"limit": 2}).json()
        page2 = case.client.get("/api/datasets", params={"offset": 2, "limit": 3}).json()
        names = [row["name"] for row in page1["items"] + page2["items"]]
        assert names == [
            "EgoProDemo",
            "EgoProStandard",
            "R1_lite_table_withdrawing_mcap",
            "agibot_world_alpha",
            "libero_10",
        ]
        assert case.client.get("/api/datasets", params={"offset": 100}).json()["items"] == []
        nodes = case.client.get(
            "/api/datasets/trees", params={"robot_model": "franka", "view": "format"}
        ).json()["nodes"]
        assert [row["entry_path"] for row in nodes if row["kind"] == "entry"] == [FORMAT_ENTRY]


def test_invalid_query_returns_five_part_problem(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：分页、跨字段和穿越参数422，五段诊断不回显不可信原值。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        for query in (
            {"offset": -1},
            {"limit": 101},
            {"version": "3.0"},
            {"view": "task", "format": "lerobot"},
            {"entry_path": "../private-value"},
        ):
            response = case.client.get("/api/datasets", params=query)
            assert response.status_code == 422, response.text
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["diagnostics"]
            assert "private-value" not in response.text


def test_tree_counts_and_size_provenance(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收2/3：树按入口聚合，100统计+旧记录及未统计得到小计100、总量null，时间保持原统计时刻。"""
    from accounts_support import NOW
    from sqlalchemy import update

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.datasets.models import EntryRow

    with browser_case(tmp_path / "state", fake_nav) as case:
        with session_scope(case.engine) as session:
            session.execute(update(EntryRow).values(recorded_size_bytes=None))
            session.execute(
                update(EntryRow)
                .where(EntryRow.path == ENTRY)
                .values(size_bytes=100, size_checked_at=NOW, aria2_count=0, incomplete_count=0)
            )
            session.execute(
                update(EntryRow)
                .where(EntryRow.path == "按任务/EgoProDemo")
                .values(recorded_size_bytes=20)
            )
        response = case.client.get("/api/datasets/trees")
        assert response.status_code == 200, response.text
        nodes = {row["path"]: row for row in response.json()["nodes"]}
        root = nodes["按任务"]
        assert (root["dataset_count"], root["entry_count"]) == (5, 5)
        assert root["size"]["known_bytes"] == 100
        assert root["size"]["total_bytes"] is None
        assert root["size"]["measured_entry_count"] == 1
        assert root["size"]["recorded_entry_count"] == 0
        assert root["size"]["unknown_entry_count"] == 4
        assert root["size"]["oldest_size_checked_at"] == "2026-10-25T12:30:10.123456Z"
        assert nodes[FORMAT_ENTRY]["dataset_id"] == "dataset-14"


def test_list_preserves_damaged_and_format_only_entries(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收2/4：损坏入口按位置保留、仅格式入口仍列出且无规范副本，详情不伪造身份。"""
    import shutil

    damaged = "按任务/R1_lite_table_withdrawing_mcap"
    for name in ("原始路径.json", "数据集信息.json", "子任务.json"):
        (fake_nav.nav_root / damaged / name).write_text("{broken")
    shutil.rmtree(fake_nav.nav_root / "按任务/EgoProDemo")
    with browser_case(tmp_path / "state", fake_nav) as case:
        response = case.client.get("/api/datasets")
        assert response.status_code == 200, response.text
        rows = response.json()["items"]
        unknown = next(row for row in rows if row["dataset_id"] is None)
        assert unknown["entries"][0]["entry_path"] == damaged
        format_only = next(row for row in rows if row["name"] == "EgoProDemo")
        assert format_only["canonical_entry_path"] is None
        assert format_only["size"]["display_bytes"] is None
        detail = case.client.get("/api/datasets/detail", params={"entry_path": damaged})
        assert detail.status_code == 200, detail.text
        assert detail.json()["canonical_information"] is None


def test_index_only_reads_never_open_navigation(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收2：移走整个假导航后树/列表/筛选仍返回原索引；面板边界留第二段。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        hidden = fake_nav.nav_root.with_name("hidden-nav")
        fake_nav.nav_root.rename(hidden)
        try:
            assert case.client.get("/api/datasets").json()["total"] == 5
            assert case.client.get("/api/datasets/trees").status_code == 200
            assert case.client.get("/api/datasets/filters").status_code == 200
        finally:
            hidden.rename(fake_nav.nav_root)


def test_panel_grouping_bounded_examples_and_offline_banner(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收2：四组两级按规则合并，108个发现仅10个样例；单数据集保留101总数，顶部离线保留旧时间。"""
    from datetime import timedelta

    from accounts_support import NOW
    from sqlalchemy import delete, select, update

    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import (
        Diagnostic,
        DiagnosticCategory,
        DiagnosticLevel,
        DiagnosticObject,
    )
    from rdp.jobs.datasets.models import DatasetScanRow, FindingRow, ScanRootRow

    with browser_case(tmp_path / "state", fake_nav) as case:
        with session_scope(case.engine) as session:
            scan_id = session.scalar(
                select(DatasetScanRow.scan_id).where(DatasetScanRow.is_current.is_(True))
            )
            assert scan_id is not None
            session.execute(delete(FindingRow))
            for group in ("json", "views", "disk", "storage"):
                for severity in ("action_required", "notice"):
                    for identity, total, prefix in (
                        ("dataset-14", 101, "a"),
                        ("dataset-33", 7, "b"),
                    ):
                        samples = [
                            Diagnostic(
                                level=DiagnosticLevel.ERROR
                                if severity == "action_required"
                                else DiagnosticLevel.WARNING,
                                category=DiagnosticCategory.INPUT,
                                stage="扫描",
                                source="平台",
                                objects=(
                                    DiagnosticObject(key="entry_path", value=f"{prefix}{number}"),
                                ),
                                rule="PANEL_CASE",
                                actual="已有问题",
                                expected="一致",
                                consequence="只报告",
                                next_step="核对后重扫",
                            ).model_dump(mode="json")
                            for number in range(6)
                        ]
                        session.add(
                            FindingRow(
                                owner_key="dataset:" + identity,
                                group=group,
                                severity=severity,
                                rule="PANEL_CASE",
                                scan_id=scan_id,
                                total=total,
                                samples=samples,
                            )
                        )
            session.execute(
                update(ScanRootRow)
                .where(ScanRootRow.name == fake_nav.storage_roots[0].name)
                .values(online=False, reason="not_mounted", checked_at=NOW - timedelta(hours=1))
            )
        response = case.client.get("/api/datasets/panel")
        assert response.status_code == 200, response.text
        data = response.json()
        assert [(row["group"], row["severity"]) for row in data["findings"]] == [
            (group, severity)
            for group in ("json", "views", "disk", "storage")
            for severity in ("action_required", "notice")
        ]
        for row in data["findings"]:
            diagnosis = row["diagnostics"]
            assert diagnosis["total"] == 108
            assert len(diagnosis["samples"]) == 10
            assert diagnosis["samples"][0]["objects"] == [{"key": "entry_path", "value": "a0"}]
            assert diagnosis["error_count"] == (108 if row["severity"] == "action_required" else 0)
        offline = next(
            row for row in data["storage_roots"] if row["name"] == fake_nav.storage_roots[0].name
        )
        assert offline["online"] is False and offline["reason"] == "not_mounted"
        assert offline["checked_at"] == "2026-10-25T11:30:10.123456Z"
        selected = case.client.get("/api/datasets/panel", params={"dataset_id": "dataset-14"})
        assert selected.status_code == 200
        assert all(row["diagnostics"]["total"] == 101 for row in selected.json()["findings"])
        assert selected.json()["storage_roots"] == data["storage_roots"]
        assert (
            case.client.get("/api/datasets/panel", params={"dataset_id": "absent"}).status_code
            == 404
        )


def test_detail_raw_unknown_fields_and_canonical_information(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收4：当前入口原文保留空白和陌生字段，业务信息独立使用规范副本。"""
    from datasets_support import edit_json

    path = fake_nav.nav_root / FORMAT_ENTRY / "数据集信息.json"
    with browser_case(tmp_path / "state", fake_nav) as case:
        edit_json(path, lambda data: data.update({"unknown_field": {"x": [1, None]}}))
        response = case.client.get("/api/datasets/detail", params={"entry_path": FORMAT_ENTRY})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["information"]["content"] == path.read_text()
        assert (
            data["canonical_information"]["content"]
            == (fake_nav.nav_root / ENTRY / "数据集信息.json").read_text()
        )
        assert (
            data["original_paths"]["content"]
            == (fake_nav.nav_root / FORMAT_ENTRY / "原始路径.json").read_text()
        )
        assert data["index_stale"] is True
        assert len(data["entries"]) == 2
        assert data["subtasks_entry_path"] == FORMAT_ENTRY
        assert "subtasks" not in data


def test_detail_fingerprint_detects_changed_json(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：不变指纹为false；仅改JSON空白且还原mtime仍为true，不依赖新旧时间比较。"""
    import os

    with browser_case(tmp_path / "state", fake_nav) as case:
        assert (
            case.client.get("/api/datasets/detail", params={"entry_path": ENTRY}).json()[
                "index_stale"
            ]
            is False
        )
        path = fake_nav.nav_root / ENTRY / "数据集信息.json"
        before = path.stat()
        path.write_bytes(path.read_bytes() + b" \n")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        response = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
        assert response.status_code == 200
        assert response.json()["index_stale"] is True


def test_detail_fingerprint_covers_new_entries_and_unverifiable_state(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收4：L12发现新增格式入口、来源文件及不可读指纹；相同不可验证状态也不判未变。"""
    import shutil

    with browser_case(tmp_path / "state", fake_nav) as case:
        new = fake_nav.nav_root / "按格式/lerobot/2.1/libero_10"
        shutil.copytree(fake_nav.nav_root / FORMAT_ENTRY, new, symlinks=True)
        assert (
            case.client.get("/api/datasets/detail", params={"entry_path": ENTRY}).json()[
                "index_stale"
            ]
            is True
        )
        shutil.rmtree(new)
        provenance = fake_nav.nav_root / ENTRY / "来源.json"
        provenance.write_text("{}")
        assert (
            case.client.get("/api/datasets/detail", params={"entry_path": ENTRY}).json()[
                "index_stale"
            ]
            is True
        )
        provenance.unlink()
        provenance.symlink_to(tmp_path / "absent")
        for _ in range(2):
            assert (
                case.client.get("/api/datasets/detail", params={"entry_path": ENTRY}).json()[
                    "index_stale"
                ]
                is True
            )


def test_detail_partial_file_failure_is_visible(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：坏JSON、未知schema、缺依赖字段原文保留且不可用；缺文件不拿索引副本冒充。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        path = fake_nav.nav_root / ENTRY / "数据集信息.json"
        for content in ("{broken", '{"schema_version": 999, "dataset_id": "dataset-14"}', "{}"):
            path.write_text(content)
            response = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
            assert response.status_code == 200
            document = response.json()["information"]
            assert document["content"] == content
            assert document["usable"] is False
            assert document["diagnostics"]
        path.unlink()
        response = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
        assert response.status_code == 200
        assert response.json()["information"]["content"] is None
        assert response.json()["original_paths"]["usable"] is True
        issue = response.json()["information"]["diagnostics"][0]
        assert {"key": "entry_path", "value": ENTRY} in issue["objects"]
        assert issue["actual"] and issue["consequence"]


def test_source_derived_paths_and_validation_labels(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收4：五个历史状态中文标签、未知与缺省保持区别；推导路径不采用存下来的错误值。"""
    from datasets_support import edit_json

    path = fake_nav.nav_root / ENTRY / "原始路径.json"
    expected = {
        "path_exists_only": "只核对了路径存在",
        "archive_not_opened": "归档没有打开核对",
        "metadata_and_references_pass": "元数据和引用都核对通过",
        "attention_required": "需要关注",
        "download_state_only": "只有下载控制文件",
        "new_status": "未识别",
        None: "未知",
    }
    with browser_case(tmp_path / "state", fake_nav) as case:
        for status, label in expected.items():
            edit_json(
                path,
                lambda data, status=status: data["sources"][0].update(
                    validation_status=status, entry_path="wrong"
                ),
            )
            response = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
            assert response.status_code == 200, response.text
            source = response.json()["sources"][0]
            assert source["validation_status"] == status
            assert source["validation_status_label"] == label
            assert source["derived_entry_path"] != "wrong"


def test_subtasks_not_embedded_and_fourteen_megabytes_exact(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收4：合成14MiB子任务只由独立接口原字节返回，详情不携带正文。"""
    path = fake_nav.nav_root / ENTRY / "子任务.json"
    with browser_case(tmp_path / "state", fake_nav) as case:
        content = b'{"dataset_id":"dataset-14","large":"' + b"x" * (14 * 1024 * 1024) + b'"}'
        path.write_bytes(content)
        detail = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
        assert detail.status_code == 200
        assert "large" not in detail.text
        response = case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY})
        assert response.status_code == 200, response.text[:300]
        assert response.content == content
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.headers["content-length"] == str(len(content))


def test_subtasks_headers_and_changed_during_read(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收4：响应摘要/时间/缓存头对应本次字节；模拟读期间改动必须409且无半份正文。"""
    import hashlib
    import os
    from datetime import datetime, timedelta

    path = fake_nav.nav_root / ENTRY / "子任务.json"
    with browser_case(tmp_path / "state", fake_nav) as case:
        response = case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY})
        assert response.status_code == 200
        assert (
            response.headers["x-document-sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        assert response.headers["x-index-stale"] == "false"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert datetime.fromisoformat(response.headers["x-observed-at"]).utcoffset() == timedelta(0)
        original_read = os.read
        changed = False

        def racing_read(fd: int, length: int) -> bytes:
            nonlocal changed
            data = original_read(fd, length)
            if not changed and b'"dataset_id"' in data:
                changed = True
                path.write_bytes(path.read_bytes() + b" ")
            return data

        monkeypatch.setattr(os, "read", racing_read)
        failed = case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY})
        assert failed.status_code == 409, failed.text
        assert failed.headers["content-type"].startswith("application/problem+json")


def test_subtasks_missing_oversize_and_io_failure(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收4：缺失/非UTF-8/非普通/超32MiB均400，权限I/O失败502；恰好32MiB允许。"""
    import errno
    import os

    path = fake_nav.nav_root / ENTRY / "子任务.json"
    with browser_case(tmp_path / "state", fake_nav) as case:
        original = path.read_bytes()
        path.unlink()
        assert (
            case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY}).status_code
            == 400
        )
        for content in (b"\xff", b" " * (32 * 1024 * 1024 + 1)):
            path.write_bytes(content)
            assert (
                case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY}).status_code
                == 400
            )
        path.write_bytes(b" " * (32 * 1024 * 1024))
        assert (
            case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY}).status_code
            == 200
        )
        path.unlink()
        os.mkfifo(path)
        assert (
            case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY}).status_code
            == 400
        )
        path.unlink()
        path.write_bytes(original)
        real_open = os.open

        def denied(
            file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if file == "子任务.json":
                raise PermissionError(errno.EACCES, "拒绝读取")
            return real_open(file, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(os, "open", denied)
        assert (
            case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY}).status_code
            == 502
        )


def test_unknown_entry_and_dataset_return_404(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：未知入口404，已入索引但文件缺失在详情局部降级、子任务400；提交范围留第二段。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        for endpoint in ("detail", "subtasks"):
            response = case.client.get(
                "/api/datasets/" + endpoint, params={"entry_path": "按任务/absent"}
            )
            assert response.status_code == 404, response.text
        (fake_nav.nav_root / ENTRY / "子任务.json").unlink()
        assert (
            case.client.get("/api/datasets/detail", params={"entry_path": ENTRY}).status_code == 200
        )
        assert (
            case.client.get("/api/datasets/subtasks", params={"entry_path": ENTRY}).status_code
            == 400
        )


def test_rescan_submits_current_actor_and_never_executes(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收5：重新检查只提交单数据集queued作业和审计，提交人来自登录身份，登记执行器不被调用。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        response = case.client.post("/api/datasets/dataset-14/rescan")
        assert response.status_code == 201, response.text
        job = response.json()
        assert job["type_name"] == "dataset_rescan" and job["state"] == "queued"
        assert job["parameters"] == {"dataset_id": "dataset-14"}
        assert job["submitted_by"] == {"account_id": "1", "name": "管理员", "deleted": False}
        assert case.client.get("/api/jobs/" + job["job_id"]).json() == job
        logs = case.client.get("/api/audit/operations", params={"operation": "submit_job"}).json()[
            "items"
        ]
        assert len(logs) == 1 and logs[0]["result"] == "success"
        # Web生产登记没有执行依赖；若误调用正式执行器会失败，且不能得到未启动的排队记录。
        assert job["started_at"] is None
        assert job["progress"] is None and job["summary"] is None
        assert case.client.post("/api/datasets/absent/rescan").status_code == 404


def test_sizing_submits_all_or_one_without_worker_import(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收5：统计使用正式生产登记，null或单编号由当前成员提交，记录保持queued且没有执行进度。"""
    from account_api_support import add_actor
    from pydantic import SecretStr

    with browser_case(tmp_path / "registered", fake_nav) as case:
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        identifiers: list[str] = []
        for dataset_id in (None, "dataset-14"):
            response = case.client.post("/api/datasets/sizing", json={"dataset_id": dataset_id})
            assert response.status_code == 201, response.text
            job = response.json()
            assert job["parameters"] == {"dataset_id": dataset_id}
            assert job["state"] == "queued" and job["type_name"] == "dataset_sizing"
            assert (
                job["submitted_by"]["name"] == "成员" and job["submitted_by"]["account_id"] == "2"
            )
            assert job["started_at"] is None and job["progress"] is None and job["summary"] is None
            assert case.client.get("/api/jobs/" + job["job_id"]).json() == job
            identifiers.append(job["job_id"])
        assert len(set(identifiers)) == 2
        assert (
            case.client.post("/api/datasets/sizing", json={"dataset_id": "absent"}).status_code
            == 404
        )


def test_submission_failure_rolls_back_job_and_audit(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收5：提交日志失败时作业一起回滚，只有失败补记；解除I/O故障后离线worker仍可排队。"""
    import sqlite3
    from typing import Any

    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    with browser_case(tmp_path / "state", fake_nav) as case:
        before = case.client.get("/api/jobs").json()["items"]
        failed = False

        def fail_once(
            _connection: Any,
            _cursor: Any,
            statement: str,
            parameters: Any,
            _context: Any,
            _many: bool,
        ) -> None:
            nonlocal failed
            if not failed and statement.startswith("INSERT INTO operation_logs"):
                failed = True
                error = sqlite3.OperationalError("disk I/O error")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise OperationalError(statement, parameters, error)

        event.listen(case.engine, "before_cursor_execute", fail_once)
        try:
            response = case.client.post("/api/datasets/dataset-14/rescan")
            assert response.status_code == 502, response.text
        finally:
            event.remove(case.engine, "before_cursor_execute", fail_once)
        assert failed
        assert case.client.get("/api/jobs").json()["items"] == before
        logs = case.client.get("/api/audit/operations", params={"operation": "submit_job"}).json()[
            "items"
        ]
        assert [row["result"] for row in logs] == ["failure"]
        assert case.client.get("/api/worker/status").json()["online"] is False
        assert case.client.post("/api/datasets/dataset-14/rescan").status_code == 201


def test_layout_persists_across_sessions_and_isolates_accounts(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收6：甲保存B后新会话仍读B；乙默认A，拒绝指定其他账号，未登录401。"""
    from account_api_support import add_actor
    from pydantic import SecretStr

    with browser_case(tmp_path / "state", fake_nav) as case:
        initial = case.client.get("/api/datasets/layout")
        assert initial.status_code == 200, initial.text
        assert initial.json() == {"layout": "A", "updated_at": None}
        response = case.client.put("/api/datasets/layout", json={"layout": "B"})
        assert response.status_code == 200, response.text
        saved = response.json()
        case.client.cookies.clear()
        assert case.login().status_code == 200
        assert case.client.get("/api/datasets/layout").json() == saved
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        assert case.client.get("/api/datasets/layout").json() == initial.json()
        assert (
            case.client.put(
                "/api/datasets/layout", json={"layout": "C", "account_id": "1"}
            ).status_code
            == 422
        )
        assert case.client.put("/api/datasets/layout", json={"layout": "C"}).status_code == 200
        assert case.login().status_code == 200
        assert case.client.get("/api/datasets/layout").json() == saved
        case.client.cookies.clear()
        assert case.client.get("/api/datasets/layout").status_code == 401


def test_layout_default_idempotence_and_clock_rollback(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收6：GET不制造保存时刻，首次A保存建记录，同值不改时刻，回拨不降低时刻，最后提交生效。"""
    from datetime import timedelta

    with browser_case(tmp_path / "state", fake_nav) as case:
        assert case.client.get("/api/datasets/layout").json() == {"layout": "A", "updated_at": None}
        first = case.client.put("/api/datasets/layout", json={"layout": "A"}).json()
        assert first["updated_at"] is not None
        case.clock.value += timedelta(seconds=2)
        assert case.client.put("/api/datasets/layout", json={"layout": "A"}).json() == first
        later = case.client.put("/api/datasets/layout", json={"layout": "B"}).json()
        assert later["updated_at"] > first["updated_at"]
        case.clock.value -= timedelta(hours=1)
        changed = case.client.put("/api/datasets/layout", json={"layout": "C"}).json()
        assert changed == {"layout": "C", "updated_at": later["updated_at"]}
        assert case.client.get("/api/datasets/layout").json() == changed


def test_layout_without_audit_and_deleted_account(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收6：布局操作不产生审计；全量重扫保留偏好，删除账号级联清除，重建同名账号不继承旧选择。"""
    from account_api_support import add_actor
    from datasets_execution_support import DatasetCase
    from pydantic import SecretStr
    from sqlalchemy import text

    from rdp.infra.config import PlatformConfig
    from rdp.infra.state import state_paths
    from rdp.jobs.datasets.rescan import RescanDependencies

    with browser_case(tmp_path / "state", fake_nav) as case:
        add_actor(case)
        before = case.client.get("/api/audit/operations").json()["items"]
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        member_id = case.client.get("/api/auth/me").json()["account_id"]
        assert case.client.put("/api/datasets/layout", json={"layout": "C"}).status_code == 200
        scanner = DatasetCase(
            case.engine,
            state_paths(PlatformConfig(state_dir=tmp_path / "state"), ("重新扫描数据集",)),
            RescanDependencies(case.engine, fake_nav.nav_root, fake_nav.storage_roots, None),
            number=72,
        )
        scanner.run()
        assert case.client.get("/api/datasets/layout").json()["layout"] == "C"
        assert case.login().status_code == 200
        assert case.client.get("/api/audit/operations").json()["items"] == before
        assert case.client.delete("/api/accounts/" + member_id).status_code == 204
        # 这里验证的是已批准的外键级联契约，业务读写的断言仍经HTTP完成。
        with case.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM dataset_layout_preferences")) == 0
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        assert case.client.get("/api/auth/me").json()["account_id"] != member_id
        assert case.client.get("/api/datasets/layout").json() == {"layout": "A", "updated_at": None}


def test_layout_migration_matches_model_and_preserves_existing_data(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收6：真实0007库升级0008保留账号/索引/作业，新表与ORM一致且约束/降级拒绝有效。"""
    from accounts_support import NOW
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from dataset_api_support import historical_migrations, seed_historical_index
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    from rdp.infra.config import PlatformConfig
    from rdp.infra.db.connection import create_database_engine
    from rdp.infra.db.migration import migrate
    from rdp.infra.db.models import metadata
    from rdp.infra.state import state_paths

    historical = historical_migrations(tmp_path)
    state = tmp_path / "state"
    with monkeypatch.context() as patch:
        patch.setattr("rdp.infra.db.migration.__file__", str(historical.parent / "migration.py"))
        with dataset_case(state, fake_nav) as case:
            seed_historical_index(case.engine, fake_nav, tmp_path / "current", monkeypatch)
    result = migrate(state_paths(PlatformConfig(state_dir=state), ()), now=NOW)
    assert (result.previous_revision, result.current_revision) == (
        "0007_dataset_index",
        "0019_collection_registry",
    )
    assert result.backup is not None and result.backup.is_file()
    from rdp.infra.db.migrations.versions.v0008_dataset_layout import downgrade
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.dataset_browser.preference_models import DatasetLayoutPreferenceRow

    assert DatasetLayoutPreferenceRow.metadata is metadata
    engine = create_database_engine(state / "rdp.sqlite3")
    try:
        with engine.connect() as connection:
            assert "dataset_layout_preferences" in inspect(connection).get_table_names()
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
            assert connection.scalar(text("SELECT count(*) FROM datasets")) == 5
            assert connection.scalar(text("SELECT count(*) FROM accounts")) == 1
            assert connection.scalar(text("SELECT count(*) FROM jobs")) == 1
        for account, layout in ((1, "Z"), (999, "A"), (0, "A")):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO dataset_layout_preferences VALUES (:id, :layout, :at)"),
                    {"id": account, "layout": layout, "at": NOW.isoformat()},
                )
        with pytest.raises(InputError):
            downgrade()
    finally:
        engine.dispose()


def test_layout_invalid_value_and_database_failure(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收6：无效布局422；写入I/O失败502且原值保留；缺表502不能冒充默认，短锁竞争409。"""
    import sqlite3
    from typing import Any

    from sqlalchemy import event, text
    from sqlalchemy.exc import OperationalError

    with browser_case(tmp_path / "state", fake_nav) as case:
        for payload in ({"layout": "Z"}, {"layout": "b"}, {"layout": "A", "extra": 1}):
            assert case.client.put("/api/datasets/layout", json=payload).status_code == 422
        assert case.client.put("/api/datasets/layout", json={"layout": "B"}).status_code == 200

        def fail(
            _connection: Any,
            _cursor: Any,
            statement: str,
            parameters: Any,
            _context: Any,
            _many: bool,
        ) -> None:
            if statement.startswith("UPDATE dataset_layout_preferences"):
                error = sqlite3.OperationalError("disk I/O error")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise OperationalError(statement, parameters, error)

        event.listen(case.engine, "before_cursor_execute", fail)
        try:
            assert case.client.put("/api/datasets/layout", json={"layout": "C"}).status_code == 502
        finally:
            event.remove(case.engine, "before_cursor_execute", fail)
        assert case.client.get("/api/datasets/layout").json()["layout"] == "B"
        with case.engine.begin():
            assert case.client.put("/api/datasets/layout", json={"layout": "C"}).status_code == 409
        with case.engine.begin() as connection:
            connection.execute(text("DROP TABLE dataset_layout_preferences"))
        assert case.client.get("/api/datasets/layout").status_code == 502


def test_security_precedes_body_and_route_validation(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收2/4：第一段查询匿名401，写请求缺Origin先403，成员可读取，坏路径由认证之后拒绝。"""
    from account_api_support import add_actor
    from pydantic import SecretStr

    with browser_case(tmp_path / "state", fake_nav) as case:
        case.client.cookies.clear()
        for suffix in ("", "/trees", "/filters", "/detail", "/subtasks"):
            assert (
                case.client.get(
                    "/api/datasets" + suffix, params={"entry_path": "../bad"}
                ).status_code
                == 401
            )
        case.client.headers.pop("Origin")
        assert case.client.put("/api/datasets/layout", content="{bad").status_code == 403
        case.client.headers["Origin"] = "http://testserver"
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        assert case.client.get("/api/datasets").status_code == 200


def test_identity_revalidated_inside_business_transaction(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收2/4：全局认证后注销会话，全部读写接口的事务重验均返回401，不留下作业或偏好。"""
    from typing import Annotated

    from fastapi import Depends, Request

    from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
    from rdp.api.datasets import DatasetApiContext, get_dataset_context

    with browser_case(tmp_path / "state", fake_nav) as case:

        def revoke(
            request: Request,
            account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
        ) -> DatasetApiContext:
            context = get_dataset_context(request, account)
            assert account.identity is not None
            account.service.logout(account.identity, now=account.now, audit=account.audit)
            return context

        case.app.dependency_overrides[get_dataset_context] = revoke
        for suffix, query in (
            ("", {}),
            ("/trees", {}),
            ("/filters", {}),
            ("/panel", {}),
            ("/layout", {}),
            ("/detail", {"entry_path": ENTRY}),
            ("/subtasks", {"entry_path": ENTRY}),
        ):
            assert case.login().status_code == 200
            response = case.client.get("/api/datasets" + suffix, params=query)
            assert response.status_code == 401, response.text

        for method, path, payload in (
            ("POST", "/dataset-14/rescan", None),
            ("POST", "/sizing", {"dataset_id": None}),
            ("PUT", "/layout", {"layout": "B"}),
        ):
            assert case.login().status_code == 200
            assert (
                case.client.request(method, "/api/datasets" + path, json=payload).status_code == 401
            )


def test_openapi_and_generated_types_are_current() -> None:
    """验收7：离线OpenAPI和生成JSON一致，含创建、字段编辑和查看器的二十二个操作声明cookie，子任务保留文本安全头。"""
    import json

    from rdp.api import create_app

    schema = create_app(None, database=None).openapi()
    generated = Path(__file__).parents[1] / "src/web/src/api/openapi.json"
    assert json.loads(generated.read_text()) == schema
    operations = [
        operation
        for path, methods in schema["paths"].items()
        if path.startswith("/api/datasets")
        for operation in methods.values()
    ]
    # M1-08 五个创建入口、M1-09 改指向预览、M1.5-01 两个只读查看接口和 M1.5-02 编辑页逐项核对认证边界。
    assert len(operations) == 22
    assert all(operation["security"] == [{"SessionCookie": []}] for operation in operations)
    response = schema["paths"]["/api/datasets/subtasks"]["get"]["responses"]["200"]
    assert response["content"]["text/plain"]["schema"]["type"] == "string"
    assert "X-Index-Stale" in response["headers"]
    assert "X-Content-Type-Options" in response["headers"]


def test_layout_audit_contract_removed() -> None:
    """关卡修正：个人布局不出现在操作日志类型或明细白名单，生成接口不能继续承诺该审计。"""
    from rdp.api import create_app

    schemas = create_app(None, database=None).openapi()["components"]["schemas"]
    assert "set_dataset_layout" not in schemas["OperationType"]["enum"]
    assert "dataset_layout" not in schemas["AuditValues"]["properties"]


def test_production_entry_configures_dataset_queries(tmp_path: Path) -> None:
    """第一段检查点：真实Web装配把配置导航根交给查询服务，空索引可通过认证HTTP读取，不监听端口。"""
    from typing import Unpack, cast

    from accounts_support import EXAMPLE_SECRET
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from httpx import Client
    from ops_support import runtime_inputs

    from rdp.accounts.security import PasswordCodec
    from rdp.accounts.service import AccountService
    from rdp.accounts.types import Credentials, NewAccount, Role
    from rdp.api.production import UvicornOptions
    from rdp.audit.types import OPS_AUDIT_CONTEXT
    from rdp.cli import run_web
    from rdp.ops.runtime import prepare_service

    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("web", no_stderr=True, inputs=inputs)
    accounts = AccountService(runtime.engine, PasswordCodec())
    accounts.create_first_admin(
        NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
        now=inputs.clock.now(),
        audit=OPS_AUDIT_CONTEXT,
    )

    def runner(app: FastAPI, **_options: Unpack[UvicornOptions]) -> None:
        with TestClient(
            app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}
        ) as raw_client:
            client = cast(Client, raw_client)
            assert (
                client.post(
                    "/api/auth/login",
                    json={"login_name": "admin", "password": EXAMPLE_SECRET.get_secret_value()},
                ).status_code
                == 200
            )
            response = client.get("/api/datasets/trees")
            assert response.status_code == 200, response.text
            assert [node["entry_count"] for node in response.json()["nodes"]] == [0, 0, 0]

    assert run_web(runtime, inputs=inputs, runner=runner) == 0


def test_detail_projection_read_failure_marks_stale(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收4回归：原文成功后投影读取失败，不能以随后相同L12误报新鲜或静默丢失数据块。"""
    import errno
    import os

    with browser_case(tmp_path / "state", fake_nav) as case:
        real_open = os.open
        reads = 0

        def fail_projection(
            file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal reads
            if (
                file == "原始路径.json"
                and dir_fd is not None
                and Path(f"/proc/self/fd/{dir_fd}").readlink() == fake_nav.nav_root / ENTRY
            ):
                reads += 1
                if reads == 2:
                    raise PermissionError(errno.EACCES, "临时不可读")
            return real_open(file, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(os, "open", fail_projection)
        response = case.client.get("/api/datasets/detail", params={"entry_path": ENTRY})
        assert response.status_code == 200, response.text
        assert response.json()["original_paths"]["usable"] is True
        assert response.json()["index_stale"] is True
        assert response.json()["diagnostics"]


def test_layout_direct_call_rejects_invalid_value(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """领域契约回归：绕过HTTP的非法布局仍是输入拒绝，不能靠SQL CHECK误报冲突。"""
    from typing import cast

    from accounts_support import AUDIT_CONTEXT, EXAMPLE_SECRET

    from rdp.accounts.types import Credentials
    from rdp.jobs.dataset_browser.errors import DatasetQueryError
    from rdp.jobs.dataset_browser.schemas import Layout
    from rdp.jobs.dataset_browser.service import DatasetBrowserService
    from rdp.jobs.service import JobRequest

    with browser_case(tmp_path / "state", fake_nav) as case:
        grant = case.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=case.clock.value, audit=AUDIT_CONTEXT
        )
        service = DatasetBrowserService(
            case.engine,
            fake_nav.nav_root,
            case.app.state.job_service,
        )
        request = JobRequest(grant.identity, case.clock.value, AUDIT_CONTEXT)
        with pytest.raises(DatasetQueryError):
            service.set_layout(request, cast(Layout, "invalid"))
        assert service.get_layout(request).model_dump() == {"layout": "A", "updated_at": None}


def test_sizing_openapi_matches_production_parameters(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """合并对齐：HTTP直接复用正式统计参数模型，省略编号按全量提交，错误类型及额外字段422。"""
    from rdp.api import create_app
    from rdp.jobs.datasets.sizing import SizingParameters

    schema = create_app(None, database=None).openapi()
    request = schema["paths"]["/api/datasets/sizing"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert request == {"$ref": "#/components/schemas/" + SizingParameters.__name__}
    exported = schema["components"]["schemas"][SizingParameters.__name__]
    expected = SizingParameters.model_json_schema()
    # FastAPI省略None默认值；比较输入约束和必填集合，默认行为另用真实HTTP请求验证。
    assert set(exported["properties"]) == set(expected["properties"]) == {"dataset_id"}
    assert (
        exported["properties"]["dataset_id"]["anyOf"]
        == expected["properties"]["dataset_id"]["anyOf"]
    )
    assert exported.get("required", []) == expected.get("required", []) == []
    assert exported["additionalProperties"] is expected["additionalProperties"] is False
    with browser_case(tmp_path / "state", fake_nav) as case:
        response = case.client.post("/api/datasets/sizing", json={})
        assert response.status_code == 201, response.text
        assert response.json()["parameters"] == {"dataset_id": None}
        for payload in (
            {"dataset_id": True},
            {"dataset_id": "../invalid"},
            {"dataset_id": None, "extra": 1},
        ):
            assert case.client.post("/api/datasets/sizing", json=payload).status_code == 422
