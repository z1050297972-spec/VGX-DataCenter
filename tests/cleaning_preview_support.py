"""清洗预览的真实 HTTP、执行器与小 MCAP 装配；存储根只在 tmp 下。"""

import io
import os
import time
from collections.abc import Buffer, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock

import pytest
from account_api_support import ApiCase
from accounts_support import EXAMPLE_SECRET, NOW
from cleaning_support import CONFIG, RULES, write_scene
from conversion_support import settings, storage_checker
from httpx import Response
from jobs_api_support import job_api_case
from sqlalchemy import func, select
from tool_registry_support import tool_files

from rdp.infra.config import PlatformConfig, StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.records import CleaningPreviewRow
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.datasets.models import DatasetRow, DatasetScanRow, EntryRow, SourceRow
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobRegistry
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord


@dataclass
class PreviewCase:
    """独立测试的边界依赖；取消由注入时钟在已读进度出现时触发。"""

    api: ApiCase
    root: Path
    registry: JobRegistry
    paths: StatePaths

    @property
    def payload(self) -> dict[str, object]:
        """固定的合法选择，不依赖被测实现计算期望。"""
        return {
            "dataset_id": "dataset-preview",
            "source_ids": ["source-preview"],
            "robot_model": "Galaxea R1 Lite",
        }

    def submit(self, **changes: object) -> Response:
        """经专用路由提交参数，不直接创建作业记录。"""
        return self.api.client.post(
            "/api/jobs/cleaning-preview/mcap2lerobot", json=self.payload | changes
        )

    def login_member(self) -> None:
        """管理员创建普通成员并经登录切换浏览器身份。"""
        response = self.api.client.post(
            "/api/accounts",
            json={
                "login_name": "member",
                "display_name": "成员",
                "role": "member",
                "password": EXAMPLE_SECRET.get_secret_value(),
            },
        )
        assert response.status_code == 201, response.text
        assert self.api.login("member").status_code == 200
        assert (
            self.api.client.post(
                "/api/auth/password",
                json={
                    "current_password": EXAMPLE_SECRET.get_secret_value(),
                    "new_password": "member-new-credential",
                },
            ).status_code
            == 200
        )

    def report_count(self) -> int:
        """只通过库中的公开表核验工单要求的报告有无，不观察私有执行状态。"""
        with session_scope(self.api.engine, read_only=True) as session:
            return session.scalar(select(func.count()).select_from(CleaningPreviewRow)) or 0

    def run(self, identifier: str, *, cancel_during_read: bool = False) -> JobRecord | None:
        """真实领取与执行，不启动轮询线程；注入时钟充当取消时机边界。"""
        signals = ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
        source_identity = (self.root / "sample.mcap").stat().st_ino
        original_fdopen = os.fdopen
        api = self.api

        class CancellingFile(io.FileIO):
            """仅在操作系统文件读取边界触发取消，MCAP 解码仍走真实代码。"""

            def readinto(self, buffer: Buffer) -> int | None:
                count = super().readinto(buffer)
                if count:
                    response = api.client.post(f"/api/jobs/{identifier}/cancel")
                    assert response.status_code == 200, response.text
                    signals.cancelled.set()
                return count

        def fdopen(fd: int, mode: str = "r", buffering: int = -1) -> object:
            if os.fstat(fd).st_ino == source_identity:
                return CancellingFile(fd, "rb")
            return original_fdopen(fd, mode, buffering)

        with session_scope(self.api.engine) as session:
            record = claim_job(session, int(identifier), now=NOW, paths=self.paths, gpu_index=None)
        deps = ExecutorDependencies(
            self.api.engine,
            self.registry,
            self.paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=None,
            storage=None,
        )
        with pytest.MonkeyPatch.context() as patch:
            if cancel_during_read:
                patch.setattr(os, "fdopen", fdopen)
            return execute_job(
                ExecutionWork(record, ExecutionMode.FRESH, None, claim=None), deps, signals
            )


@contextmanager
def preview_case(root: Path, *, offline: bool = False) -> Generator[PreviewCase]:
    """仅把挂载表换成临时根，其他数据库、规则解析、MCAP 读取都运行真实实现。"""
    storage = root / "input"
    storage.mkdir()
    source = storage / "sample.mcap"
    write_scene(source)
    files = tool_files(root / "tool")
    (files.package / "configs/r1lite.toml").write_text(CONFIG)
    (files.package / "cleaning").mkdir(exist_ok=True)
    (files.package / "cleaning/r1lite.toml").write_text(RULES)
    manifest = files.package / "tool.toml"
    text = manifest.read_text()
    if "[cleaning]" not in text:
        text += '\n[cleaning]\n"Galaxea R1 Lite" = "cleaning/r1lite.toml"\n'
    text = text.replace("[models]", '[models]\nother = "configs/r1lite.toml"')
    manifest.write_text(text)
    roots = (StorageRootConfig(name="input", path=storage, nfs_export="server:/input"),)
    checker = storage_checker(roots)
    if offline:
        checker = replace(checker, mounts=replace(checker.mounts, read_mountinfo=lambda: ""))
    web_registry = JobRegistry()
    register_cleaning_jobs(web_registry, settings(files), None)
    with job_api_case(root / "state", registry=web_registry) as api:
        _seed_input(api, source)
        registry = JobRegistry()
        register_cleaning_jobs(
            registry,
            settings(files),
            CleaningDependencies(api.engine, settings(files), roots, checker),
        )
        paths = state_paths(
            PlatformConfig(state_dir=root / "state"),
            tuple(item.display_name for item in registry.definitions()),
        )
        initialize_state(paths)
        assert api.login().status_code == 200
        yield PreviewCase(api, storage, registry, paths)


def _seed_input(api: ApiCase, source: Path) -> None:
    """按工单直接在临时索引登记一个 mcap 规范入口，避免测试依赖导航样本。"""
    with session_scope(api.engine) as session:
        session.add(
            DatasetScanRow(
                scan_id=1,
                job_id=None,
                scope="all",
                requested_dataset_id=None,
                started_at=NOW,
                navigation_finished_at=NOW,
                committed_at=NOW,
                navigation_elapsed_s=0,
                lock_held_s=0,
                storage_stage="not_run",
                is_current=True,
            )
        )
        session.flush()
        session.add(
            DatasetRow(
                dataset_id="dataset-preview",
                name="预览样本",
                canonical_entry_path="按任务/预览样本",
                scan_id=1,
                fingerprint={},
                data_origin="real",
            )
        )
        session.flush()
        session.add(
            EntryRow(
                path="按任务/预览样本",
                dataset_id="dataset-preview",
                scan_id=1,
                view="task",
                name="预览样本",
                dataset_roots=[str(source.parent)],
                provenance_present=False,
                fingerprint={},
            )
        )
        session.flush()
        session.add(
            SourceRow(
                entry_path="按任务/预览样本",
                ordinal=0,
                source_id="source-preview",
                original_path=str(source),
                direct_path=str(source),
                derived_entry_path=str(source),
                format="mcap",
                status="unchecked",
            )
        )
