"""M1.5-01原文件查看器验收；只使用临时数据根和真实ASGI认证接口。"""

from pathlib import Path
from typing import Any

import pytest
from account_api_support import ApiCase
from accounts_support import NOW
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation

from rdp.infra.config import StorageConfig
from rdp.infra.storage import DeviceNumber, MountInspector
from rdp.jobs.file_viewer import FileViewerService


def setup_viewer(case: ApiCase, nav: FakeNavigation, *, table: str | None = None) -> None:
    """给真实应用绑定临时存储挂载表；不查系统挂载状态。"""
    devices = {
        root.uuid: DeviceNumber(8, index + 1) for index, root in enumerate(nav.storage_roots)
    }
    text = (
        table
        if table is not None
        else "\n".join(
            f"{index + 1} 0 8:{index + 1} / {root.path} rw - ext4 /dev/fake rw"
            for index, root in enumerate(nav.storage_roots)
        )
    )
    case.app.state.file_viewer_service = FileViewerService(
        case.engine,
        nav.nav_root,
        MountInspector(nav.storage_roots, lambda: text, devices.get, lambda: NOW),
        StorageConfig(access_timeout_s=1),
    )


def test_lists_registered_link_directory(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：按永久编号和登记链接分页，只列直接子项及字节大小、UTC修改时间。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        response = case.client.get(
            "/api/datasets/dataset-14/files",
            params={"link_name": "原始数据", "path": "meta", "limit": 1},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"][0]["name"] == "info.json"
        assert body["items"][0]["kind"] == "file"
        assert body["items"][0]["size_bytes"] > 0
        assert body["items"][0]["modified_at"].endswith("Z")
        assert body["has_more"] is True


def test_reads_original_bytes(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：JSON原字节、禁止缓存/嗅探；存储打开请求O_NOATIME并在EPERM时只读回退。"""
    target = fake_nav.nav_root / "按任务/libero_10/原始数据"
    expected = (target / "meta/info.json").read_bytes()
    import errno
    import os

    real_target = target.resolve()
    original = os.open
    flags_seen: list[int] = []

    def opened(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        parent = kwargs.get("dir_fd")
        if isinstance(parent, int) and Path(f"/proc/self/fd/{parent}").readlink().is_relative_to(
            real_target
        ):
            flags_seen.append(flags)
            if flags & os.O_NOATIME:
                raise PermissionError(errno.EPERM, "fixture owner mismatch")
        return original(path, flags, *args, **kwargs)

    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        monkeypatch.setattr(os, "open", opened)
        response = case.client.get(
            "/api/datasets/dataset-14/file",
            params={"link_name": "原始数据", "path": "meta/info.json"},
        )
        assert response.status_code == 200, response.text
        assert response.content == expected
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert flags_seen and len(flags_seen) % 2 == 0
        for first, retry in zip(flags_seen[::2], flags_seen[1::2], strict=True):
            assert first & os.O_NOATIME and first ^ retry == os.O_NOATIME
            assert retry & os.O_ACCMODE == os.O_RDONLY
            assert retry & os.O_NOFOLLOW


def test_video_ranges_and_streaming(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：视频支持首段、尾段、开放末尾、截尾、无Range及416，字节和长度精确。"""
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    (target / "clip.mp4").write_bytes(b"0123456789")
    params = {"link_name": "原始数据", "path": "clip.mp4"}
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        for value, expected, content_range in (
            ("bytes=0-2", b"012", "bytes 0-2/10"),
            ("bytes=-3", b"789", "bytes 7-9/10"),
            ("bytes=8-", b"89", "bytes 8-9/10"),
            ("bytes=8-99", b"89", "bytes 8-9/10"),
        ):
            response = case.client.get(
                "/api/datasets/dataset-14/file", params=params, headers={"Range": value}
            )
            assert response.status_code == 206, response.text
            assert response.content == expected
            assert response.headers["content-range"] == content_range
            assert response.headers["content-length"] == str(len(expected))
            assert response.headers["accept-ranges"] == "bytes"
        response = case.client.get("/api/datasets/dataset-14/file", params=params)
        assert response.status_code == 200
        assert response.content == b"0123456789"
        for value in ("bytes=10-", "bytes=5-2", "bytes=-0", "bytes=0-1,3-4", "bytes=nonsense"):
            response = case.client.get(
                "/api/datasets/dataset-14/file", params=params, headers={"Range": value}
            )
            assert response.status_code == 416
            assert response.headers["content-range"] == "bytes */10"


def test_rejects_unsafe_paths_and_offline_storage(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证验收1：两接口拒绝穿越、绝对路径、越界链和非登记链接；离线返回502五段诊断。"""
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    (target / "escape").symlink_to(tmp_path)
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        for endpoint in ("files", "file"):
            for path in ("..", "meta/../../..", str(tmp_path), "escape"):
                response = case.client.get(
                    f"/api/datasets/dataset-14/{endpoint}",
                    params={"link_name": "原始数据", "path": path},
                )
                assert response.status_code == 422, response.text
            response = case.client.get(
                f"/api/datasets/dataset-14/{endpoint}",
                params={"link_name": "not-registered", "path": ""},
            )
            assert response.status_code == 422
        setup_viewer(case, fake_nav, table="")
        response = case.client.get(
            "/api/datasets/dataset-14/files", params={"link_name": "原始数据"}
        )
        assert response.status_code == 502
        diagnostic = response.json()["diagnostics"][0]
        for field in ("rule", "actual", "expected", "consequence", "next_step"):
            assert diagnostic[field]


def test_large_text_is_rejected(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证验收1：文本超过32MiB时拒绝而不读取或返回部分正文。"""
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    with (target / "large.txt").open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        response = case.client.get(
            "/api/datasets/dataset-14/file", params={"link_name": "原始数据", "path": "large.txt"}
        )
        assert response.status_code == 422
        assert "太大，请下载工具查看" in response.text


def test_mount_failure_does_not_exhaust_access_slots(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证故障模型：挂载表读取失败可恢复，连续失败不能泄漏访问槽并永久阻断后续查看。"""
    from dataclasses import replace

    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        service = case.app.state.file_viewer_service
        original = service.mounts.read_mountinfo
        failing = True

        def read_table() -> str:
            if failing:
                raise OSError("fixture mount table unavailable")
            return original()

        service.mounts = replace(service.mounts, read_mountinfo=read_table)
        for _ in range(5):
            response = case.client.get(
                "/api/datasets/dataset-14/files", params={"link_name": "原始数据", "path": "meta"}
            )
            assert response.status_code == 502
        failing = False
        response = case.client.get(
            "/api/datasets/dataset-14/files", params={"link_name": "原始数据", "path": "meta"}
        )
        assert response.status_code == 200, response.text


def test_blocked_file_read_returns_502_without_waiting_for_kernel(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证超时契约：原文件内核读取阻塞时按配置返回502；迟到读取不改变响应，测试释放并回收线程。"""
    import os
    import time
    from threading import Event
    from threading import enumerate as threads

    entered, release = Event(), Event()
    original = os.pread
    before = set(threads())

    def blocked(descriptor: int, count: int, offset: int) -> bytes:
        entered.set()
        assert release.wait(5), "测试未释放阻塞读取"
        return original(descriptor, count, offset)

    monkeypatch.setattr(os, "pread", blocked)
    try:
        with browser_case(tmp_path / "state", fake_nav) as case:
            setup_viewer(case, fake_nav)
            started = time.monotonic()
            response = case.client.get(
                "/api/datasets/dataset-14/file",
                params={"link_name": "原始数据", "path": "meta/info.json"},
            )
            assert entered.is_set()
            assert response.status_code == 502, response.text
            assert time.monotonic() - started < 2.5
            assert "timeout" in response.text
    finally:
        release.set()
        for thread in set(threads()) - before:
            if thread.name == "storage-dataset1":
                thread.join(timeout=2)
                assert not thread.is_alive()


def test_pagination_limit_and_registered_target_drift(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证分页/只读契约：最多500项、末页准确；实际链接与清单不符时拒绝，不暴露替换目标。"""
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    folder = target / "many"
    folder.mkdir()
    for index in range(501):
        (folder / f"item-{index}.txt").write_bytes(b"x")
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        params = {"link_name": "原始数据", "path": "many", "limit": 500}
        first = case.client.get("/api/datasets/dataset-14/files", params=params)
        assert first.status_code == 200
        assert len(first.json()["items"]) == 500 and first.json()["has_more"]
        last = case.client.get("/api/datasets/dataset-14/files", params=params | {"offset": 500})
        assert len(last.json()["items"]) == 1 and not last.json()["has_more"]
        assert not {item["name"] for item in first.json()["items"]} & {
            item["name"] for item in last.json()["items"]
        }
        assert (
            case.client.get(
                "/api/datasets/dataset-14/files", params=params | {"limit": 501}
            ).status_code
            == 422
        )
        link = fake_nav.nav_root / "按任务/libero_10/原始数据"
        link.unlink()
        link.symlink_to(fake_nav.storage_roots[1].path)
        assert (
            case.client.get(
                "/api/datasets/dataset-14/files", params={"link_name": "原始数据"}
            ).status_code
            == 422
        )


def test_unknown_text_extension_still_obeys_size_limit(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证文本上限不依赖主机MIME登记：无MIME的log/jsonl和application/yaml均不能绕过32MiB。"""
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    for name in ("large.log", "large.jsonl", "config.yaml", "README"):
        with (target / name).open("wb") as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        for name in ("large.log", "large.jsonl", "config.yaml", "README"):
            response = case.client.get(
                "/api/datasets/dataset-14/file", params={"link_name": "原始数据", "path": name}
            )
            assert response.status_code == 422, name
            assert "太大，请下载工具查看" in response.text


def test_short_reads_fill_requested_range(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证Range原字节契约：系统短读不等于EOF，仍应填满已声明范围而非误报文件变化。"""
    import os

    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    (target / "short.mp4").write_bytes(b"0123456789")
    original = os.pread

    def short_read(descriptor: int, count: int, offset: int) -> bytes:
        return original(descriptor, min(3, count), offset)

    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        monkeypatch.setattr(os, "pread", short_read)
        response = case.client.get(
            "/api/datasets/dataset-14/file",
            params={"link_name": "原始数据", "path": "short.mp4"},
            headers={"Range": "bytes=1-8"},
        )
        assert response.status_code == 206, response.text
        assert response.content == b"12345678"
        assert response.headers["content-range"] == "bytes 1-8/10"
