"""M1.5-04：用临时生成文件经真实认证HTTP边界验证预览，不访问数据盘。"""

import asyncio
import os
import shutil
import subprocess
from contextlib import suppress
from importlib import import_module
from pathlib import Path
from threading import Event
from typing import Any, cast
from urllib.parse import urlencode

import pytest
from account_api_support import ApiCase
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation
from test_file_viewer_api import setup_viewer

from rdp.api._asgi import ASGIMessage


def test_parquet_schema_paging_and_noatime(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证parquet结构、跨行组分页、嵌套/二进制显示、截断和O_NOATIME描述符读取。"""
    arrow = import_module("pyarrow")
    parquet = import_module("pyarrow.parquet")
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    source = target / "sample.parquet"
    parquet.write_table(
        arrow.table(
            {
                "index": [0, 1, 2, 3, 4],
                "text": ["short", "x" * 1100, "third", "fourth", "last"],
                "nested": [[1, 2], [3], [], [4, 5], [6]],
                "blob": [b"abc"] * 5,
            }
        ),
        source,
        row_group_size=2,
    )
    opened: list[int] = []
    original = os.open
    original_parquet = parquet.ParquetFile
    groups_seen: list[int] = []

    def from_descriptor(stream: Any) -> Any:
        import fcntl
        from types import SimpleNamespace

        assert not isinstance(stream, (str, Path))
        assert fcntl.fcntl(stream.fileno(), fcntl.F_GETFL) & os.O_NOATIME
        file = original_parquet(stream)

        def batches(*, batch_size: int, row_groups: list[int]) -> Any:
            groups_seen.extend(row_groups)
            return file.iter_batches(batch_size=batch_size, row_groups=row_groups)

        return SimpleNamespace(
            metadata=file.metadata, schema_arrow=file.schema_arrow, iter_batches=batches
        )

    def observe(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original(path, flags, *args, **kwargs)
        if os.fstat(descriptor).st_ino == source.stat().st_ino:
            opened.append(flags)
        return descriptor

    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        monkeypatch.setattr(os, "open", observe)
        monkeypatch.setattr(parquet, "ParquetFile", from_descriptor)
        response = case.client.get(
            "/api/datasets/dataset-14/parquet",
            params={"link_name": "原始数据", "path": "sample.parquet", "offset": 1, "limit": 2},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_rows"] == 5 and body["row_groups"] == 3
        assert [column["name"] for column in body["columns"]] == ["index", "text", "nested", "blob"]
        assert body["columns"][0]["type"] == "int64"
        assert [row[0]["text"] for row in body["rows"]] == ["1", "2"]
        assert body["rows"][0][1]["truncated"] is True
        assert len(body["rows"][0][1]["text"]) <= 1024
        assert body["rows"][0][2]["text"] == "[3]"
        assert body["rows"][0][3]["text"] == "<binary: 3 bytes>"
        assert body["has_more"] is True and body["schema_only"] is False
        assert opened and all(flags & os.O_NOATIME for flags in opened)
        assert groups_seen == [0, 1]


def make_video(path: Path) -> None:
    """生成有真实AV1编码的三秒测试视频；工具不可用时明确失败，绝不跳过。"""
    executable = shutil.which("ffmpeg")
    assert executable is not None, "M1.5-04验收需要本机ffmpeg，当前不可用"
    result = subprocess.run(  # noqa: S603 # 理由：固定ffmpeg参数和临时测试路径，不使用shell。
        [
            executable,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=5",
            "-t",
            "3",
            "-c:v",
            "libaom-av1",
            "-cpu-used",
            "8",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, f"ffmpeg生成AV1失败：{result.stderr.decode(errors='replace')}"


def test_video_probe_and_transcode_use_inherited_noatime_fd(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证真实AV1探测与H264分片输出；两工具仅继承O_NOATIME描述符，参数不含原路径。"""
    import fcntl

    source = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve() / "clip.mp4"
    make_video(source)
    original = subprocess.Popen
    commands: list[list[str]] = []

    def observe(command: list[str], *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if "fd:" in command:
            assert str(source) not in command
            descriptors = kwargs["pass_fds"]
            assert len(descriptors) == 1
            assert command[command.index("-fd") + 1] == str(descriptors[0])
            assert fcntl.fcntl(descriptors[0], fcntl.F_GETFL) & os.O_NOATIME
            commands.append(command)
        return cast("subprocess.Popen[bytes]", original(command, *args, **kwargs))

    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        monkeypatch.setattr(subprocess, "Popen", observe)
        params = {"link_name": "原始数据", "path": "clip.mp4"}
        probe = case.client.get("/api/datasets/dataset-14/video-info", params=params)
        assert probe.status_code == 200, probe.text
        assert probe.json()["codec"] == "av1" and probe.json()["duration_s"] == 3.0
        response = case.client.get(
            "/api/datasets/dataset-14/video", params=params | {"start_s": 1, "duration_s": 1}
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("video/mp4")
        assert b"ftyp" in response.content and b"moof" in response.content
        assert any("ffprobe" in command[0] for command in commands)
        assert any("ffmpeg" in command[0] for command in commands)
        output = tmp_path / "result.mp4"
        output.write_bytes(response.content)
        decoded = subprocess.run(  # noqa: S603 # 理由：仅探测测试自己生成的临时输出。
            [
                shutil.which("ffprobe") or "/ffprobe-unavailable",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "csv=p=0",
                str(output),
            ],
            capture_output=True,
            timeout=5,
            check=True,
        )
        assert decoded.stdout.strip() == b"h264"


@pytest.mark.parametrize("after_body", [False, True])
def test_disconnect_before_video_headers_kills_process(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch, after_body: bool
) -> None:
    """验证客户端在首块前或流发送中断开即杀掉ffmpeg，不等总时限，也不泄漏许可。"""
    import sys

    source = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve() / "clip.mp4"
    make_video(source)
    original = subprocess.Popen
    started = Event()
    disconnect_ready = Event() if after_body else started
    processes: list[subprocess.Popen[bytes]] = []

    def slow(command: list[str], *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if "-movflags" in command:
            program = (
                "import os,time; os.write(1, b'x' * 65536); time.sleep(20)"
                if after_body
                else "import time; time.sleep(20)"
            )
            command = [sys.executable, "-c", program]
            process = cast("subprocess.Popen[bytes]", original(command, *args, **kwargs))
            processes.append(process)
            started.set()
            return process
        return cast("subprocess.Popen[bytes]", original(command, *args, **kwargs))

    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        monkeypatch.setattr(subprocess, "Popen", slow)
        cookie = "; ".join(f"{key}={value}" for key, value in case.client.cookies.items())

        asyncio.run(_assert_video_disconnect(case, cookie, disconnect_ready, processes))


async def _assert_video_disconnect(
    case: ApiCase, cookie: str, started: Event, processes: list[subprocess.Popen[bytes]]
) -> None:
    """通过公开ASGI接收事件模拟首块前断开，finally回收真实子进程。"""
    sent_request = False

    async def receive() -> ASGIMessage:
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        if not started.is_set():
            assert await asyncio.to_thread(started.wait, 3), "转码没有启动"
        return {"type": "http.disconnect"}

    async def send(message: ASGIMessage) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            started.set()

    scope: ASGIMessage = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path": "/api/datasets/dataset-14/video",
        "query_string": urlencode({"link_name": "原始数据", "path": "clip.mp4"}).encode(),
        "headers": [(b"cookie", cookie.encode())],
    }
    task = asyncio.create_task(case.app(scope, receive, send))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        deadline = asyncio.get_running_loop().time() + 0.5
        while (
            any(process.poll() is None for process in processes)
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.01)
        assert processes and all(process.poll() is not None for process in processes), (
            "断开后转码进程仍存活"
        )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)


def test_parquet_large_schema_only_and_invalid_input(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证超过2GiB只读结构、空页/200行上限、损坏文件与路径越界；使用稀疏临时文件。"""
    arrow, parquet = import_module("pyarrow"), import_module("pyarrow.parquet")
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    source = target / "large.parquet"
    parquet.write_table(arrow.table({"value": [17, 23]}), source, row_group_size=1)
    content = source.read_bytes()
    footer_size = int.from_bytes(content[-8:-4], "little")
    with source.open("r+b") as stream:
        stream.seek(2 * 1024**3 + 1)
        stream.write(content[-footer_size - 8 :])
    (target / "broken.parquet").write_bytes(b"not parquet")
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        params = {"link_name": "原始数据", "path": "large.parquet"}
        response = case.client.get("/api/datasets/dataset-14/parquet", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_only"] is True and body["rows"] == []
        assert body["total_rows"] == 2 and body["row_groups"] == 2
        assert body["columns"] == [{"name": "value", "type": "int64"}]
        for changes in (
            {"limit": 201},
            {"offset": -1},
            {"path": "../large.parquet"},
            {"path": "broken.parquet"},
        ):
            invalid = case.client.get("/api/datasets/dataset-14/parquet", params=params | changes)
            assert invalid.status_code == 422, invalid.text
        parquet.write_table(arrow.table({"value": [17, 23]}), target / "small.parquet")
        empty = case.client.get(
            "/api/datasets/dataset-14/parquet",
            params=params | {"path": "small.parquet", "offset": 2, "limit": 200},
        )
        assert empty.json()["rows"] == [] and empty.json()["has_more"] is False


def slow_video_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[subprocess.Popen[bytes]], Event]:
    """用真实可杀子进程替换转码工具边界，保留ffprobe与编码器能力检查。"""
    import sys

    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    two_started = Event()

    def slow(command: list[str], *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if "-movflags" in command:
            process = cast(
                "subprocess.Popen[bytes]",
                original([sys.executable, "-c", "import time; time.sleep(20)"], *args, **kwargs),
            )
            processes.append(process)
            if len(processes) == 2:
                two_started.set()
            return process
        return cast("subprocess.Popen[bytes]", original(command, *args, **kwargs))

    monkeypatch.setattr(subprocess, "Popen", slow)
    return processes, two_started


def test_video_concurrency_is_two_and_recovers(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证两路持有进程时第三路429五段诊断；失败回收后新请求可正常播放。"""
    from concurrent.futures import ThreadPoolExecutor

    source = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve() / "clip.mp4"
    make_video(source)
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        params = {"link_name": "原始数据", "path": "clip.mp4"}
        with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
            processes, started = slow_video_boundary(patch)
            futures = [
                pool.submit(case.client.get, "/api/datasets/dataset-14/video", params=params)
                for _ in range(2)
            ]
            try:
                assert started.wait(4), "两路转码未启动"
                busy = case.client.get("/api/datasets/dataset-14/video", params=params)
                assert busy.status_code == 429, busy.text
                diagnostic = busy.json()["diagnostics"][0]
                assert diagnostic["rule"] == "FILE_VIEWER_VIDEO_BUSY"
                assert all(
                    diagnostic[key]
                    for key in ("objects", "actual", "expected", "consequence", "next_step")
                )
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)
                for future in futures:
                    assert future.result(timeout=3).status_code == 502
        assert case.client.get("/api/datasets/dataset-14/video", params=params).status_code == 200


def test_video_timeout_and_bad_parameters(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证真实子进程超时被杀、返回502五段诊断；负起点、非有限秒数及超长片段422。"""
    from rdp.jobs import _file_video

    source = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve() / "clip.mp4"
    make_video(source)
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)
        params = {"link_name": "原始数据", "path": "clip.mp4"}
        with monkeypatch.context() as patch:
            processes, _ = slow_video_boundary(patch)
            patch.setattr(_file_video, "TRANSCODE_TIMEOUT_S", 0.05)
            response = case.client.get("/api/datasets/dataset-14/video", params=params)
            assert response.status_code == 502, response.text
            assert "timeout" in response.json()["diagnostics"][0]["actual"]
            assert processes and all(process.poll() is not None for process in processes)
        for changes in (
            {"start_s": -1},
            {"start_s": "nan"},
            {"duration_s": 301},
            {"duration_s": 0},
            {"path": "../clip.mp4"},
        ):
            response = case.client.get("/api/datasets/dataset-14/video", params=params | changes)
            assert response.status_code == 422, response.text


def test_video_missing_tool_reports_file_identity(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证工具缺失以502五段诊断报告数据集和相对文件身份，不变成500或暴露绝对路径。"""
    target = (fake_nav.nav_root / "按任务/libero_10/原始数据").resolve()
    (target / "clip.mp4").write_bytes(b"fixture")
    original = shutil.which
    with browser_case(tmp_path / "state", fake_nav) as case:
        setup_viewer(case, fake_nav)

        def missing(name: str) -> str | None:
            return None if name in {"ffmpeg", "ffprobe"} else original(name)

        monkeypatch.setattr(shutil, "which", missing)
        for endpoint in ("video-info", "video"):
            response = case.client.get(
                f"/api/datasets/dataset-14/{endpoint}",
                params={"link_name": "原始数据", "path": "clip.mp4"},
            )
            assert response.status_code == 502, response.text
            diagnostic = response.json()["diagnostics"][0]
            objects = {item["key"]: item["value"] for item in diagnostic["objects"]}
            assert objects["dataset_id"] == "dataset-14"
            assert objects["relative_path"] == "clip.mp4"
            assert "缺少" in diagnostic["actual"]
            assert all(diagnostic[key] for key in ("rule", "expected", "consequence", "next_step"))
            assert str(target) not in response.text


def test_parquet_openapi_declares_200_row_limit() -> None:
    """验证公开契约：OpenAPI的parquet页长上限与运行时200行一致，不能继承目录500项上限。"""
    from rdp.api import create_app

    schema = create_app(None, database=None).openapi()
    parameters = schema["paths"]["/api/datasets/{dataset_id}/parquet"]["get"]["parameters"]
    limit = next(item for item in parameters if item["name"] == "limit")
    assert limit["schema"]["maximum"] == 200
    assert limit["schema"]["default"] == 200
