"""预览结果文件 `nav-previews/<预览作业编号>.json.gz` 的读写（领域层，M1-07）。

预览是只读的 worker 作业（M1-07 工单）：它访问存储根，所以不能在 Web 里算；
结果是一整份计划，大到不适合放进作业记录，所以存成状态目录里的文件，作业记录里只有编号。
页面用预览作业编号来取；写入作业的参数里也只带这个编号，执行时从这里读出同一份计划，不重新计算。
写入走 worker，读取 Web 和 worker 两侧都可以。
"""

import gzip
import logging
import os
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_external_error, nav_input_error
from rdp.jobs.navwrite.models import NavPreview
from rdp.jobs.navwrite.policy import PREVIEW_FORMAT_VERSION, PREVIEW_RETENTION_DAYS

logger = logging.getLogger(__name__)
_RULE = "NAV_PREVIEW"


def preview_path(paths: StatePaths, preview_job_id: int) -> Path:
    """计算预览文件的路径，只计算、不创建。

    Args:
        paths: 已初始化的状态布局。
        preview_job_id: 预览作业编号，≥ 1。

    Returns:
        `<状态目录>/nav-previews/<preview_job_id>.json.gz` 的绝对路径。

    Raises:
        InputError: preview_job_id 不是 ≥ 1 的整数。

    Side Effects:
        无。

    Time Semantics:
        无；纯路径计算。
    """
    if type(preview_job_id) is not int or preview_job_id < 1:
        problem = nav_input_error(_RULE, "预览作业编号必须是不小于 1 的整数")
        raise problem
    return paths.nav_previews / f"{preview_job_id}.json.gz"


def write_preview(paths: StatePaths, preview: NavPreview) -> Path:
    """把预览结果原子地写成压缩文件。

    Args:
        paths: 已初始化的状态布局。
        preview: 要保存的预览，plan.state 必须可验证。

    Returns:
        写好的文件路径。

    Raises:
        ConflictError: 该编号的预览已存在（预览作业重跑时由 RESTART 路径先删旧文件，不覆盖别人的）。
        ExternalError: 写入、fsync 或 rename 失败；不留半截文件。

    Side Effects:
        写同目录临时文件 → fsync → os.replace → fsync 目录。只写 nav-previews。

    Time Semantics:
        同步；预览作业收尾时调用一次。新建预览之后顺手删除 mtime 早于 preview.created_at 七天（PREVIEW_RETENTION_DAYS）的旧预览文件，
        删不掉的只记警告、不影响本次写入。
    """
    if any(not fingerprint.verifiable for fingerprint in preview.plan.state.datasets):
        problem = nav_input_error(_RULE, "计划里有不可验证的指纹，不能保存预览")
        raise problem
    target = preview_path(paths, preview.preview_job_id)
    if target.exists():
        problem = nav_conflict_error(
            _RULE,
            "该编号的预览已经存在",
            objects=(("preview_job_id", str(preview.preview_job_id)),),
        )
        raise problem
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        paths.nav_previews.mkdir(exist_ok=True)
        content = gzip.compress(preview.model_dump_json().encode("utf-8"), mtime=0)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            view = memoryview(content)
            while view:
                view = view[os.write(descriptor, view) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        temporary.replace(target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        problem = nav_external_error(
            _RULE,
            "写预览文件失败，没有留下半截文件",
            objects=(("preview_job_id", str(preview.preview_job_id)),),
        )
        raise problem from error
    _remove_expired(paths, preview.created_at.timestamp(), target)
    return target


def read_preview(paths: StatePaths, preview_job_id: int) -> NavPreview:
    """读取一份预览结果。

    Args:
        paths: 已初始化的状态布局。
        preview_job_id: 预览作业编号，≥ 1。

    Returns:
        NavPreview。

    Raises:
        InputError: 文件不存在（预览作业未成功或编号不对）、解压或解析失败、format_version 不认识。
        ExternalError: 读取时 I/O 失败。

    Side Effects:
        无（只读状态目录）。

    Time Semantics:
        同步；写入作业在拿写锁之前读取，页面轮询到预览作业结束后读取。文件超过七天可能已被清理，读到不存在时按输入错误处理。
    """
    path = preview_path(paths, preview_job_id)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        problem = nav_input_error(
            _RULE,
            "预览文件不存在：预览作业未成功、编号不对或已过保留期",
            objects=(("preview_job_id", str(preview_job_id)),),
        )
        raise problem from error
    except OSError as error:
        problem = nav_external_error(
            _RULE, "读取预览文件失败", objects=(("preview_job_id", str(preview_job_id)),)
        )
        raise problem from error
    try:
        return NavPreview.model_validate_json(gzip.decompress(raw))
    except (OSError, EOFError, ValueError, ValidationError) as error:
        problem = nav_input_error(
            _RULE,
            "预览文件损坏或版本不认识",
            expected=f"format_version={PREVIEW_FORMAT_VERSION}",
            objects=(("preview_job_id", str(preview_job_id)),),
        )
        raise problem from error


def _remove_expired(paths: StatePaths, now_timestamp: float, keep: Path) -> None:
    """删掉超过保留期的旧预览；每个文件的删除失败都只记警告，不影响本次写入。"""
    cutoff = now_timestamp - timedelta(days=PREVIEW_RETENTION_DAYS).total_seconds()
    try:
        names = [entry.name for entry in paths.nav_previews.iterdir()]
    except OSError:
        logger.warning("无法枚举预览目录，跳过过期预览的清理", exc_info=True)
        return
    for name in names:
        candidate = paths.nav_previews / name
        if candidate == keep or not name.endswith(".json.gz"):
            continue
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink()
        except OSError:
            logger.warning("清理过期预览失败 name=%s", name, exc_info=True)
