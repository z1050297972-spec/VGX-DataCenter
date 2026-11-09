"""RobotProfile 读取边界（领域层，ADR 0007、M5-01）。

标准库 tomllib 解析本地部署文件，Pydantic 校验事实；不读取工具库、不连接机器人。
文件按名称排序，一处失败即拒绝整批快照，避免启动后只看到部分型号。
"""

import tomllib
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from rdp.collection.profile_models import RobotProfile
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)


def load_robot_profiles(profiles_dir: Path) -> tuple[RobotProfile, ...]:
    """读取部署目录里的全部 RobotProfile 并校验跨文件身份唯一性。

    Args:
        profiles_dir: 本地可信部署中的 profiles 目录，调用方提供绝对路径；不接受请求路径。

    Returns:
        按文件名排序的说明档元组，空目录返回空元组；任何坏文件都不返回部分结果。

    Raises:
        InputError: TOML、字段或唯一性不合格，或文件软链接越界；诊断含文件、键路径和规则。
        ExternalError: 部署目录或文件不可读；诊断保留路径，不回显文件内容。

    Side Effects:
        无（只读 profiles_dir 直属的 .toml 普通文件，不读取字段中声明的话题或路径）。

    Time Semantics:
        同步本地读取，无轮询或重试；启动期间部署文件须保持稳定，返回快照后不自动刷新。
    """
    path = profiles_dir
    try:
        root = profiles_dir.resolve()
        profiles: list[RobotProfile] = []
        models: set[str] = set()
        identifiers: set[str] = set()
        for path in sorted(profiles_dir.iterdir()):
            if path.suffix != ".toml":
                continue
            if not path.resolve().is_relative_to(root) or not path.is_file():
                raise InputError(
                    (
                        _diagnostic(
                            path, "$", "path", "不是目录内的普通文件", "profiles 目录内的 TOML 文件"
                        ),
                    )
                )
            profile = _read_profile(path)
            for key, value, seen in (
                ("model", profile.model, models),
                ("profile", profile.profile, identifiers),
            ):
                if value in seen:
                    raise InputError(
                        (
                            _diagnostic(
                                path,
                                key,
                                "unique",
                                "与其他文件重复",
                                "每个型号和说明档标识只出现一次",
                            ),
                        )
                    )
                seen.add(value)
            profiles.append(profile)
        return tuple(profiles)
    except OSError as error:
        raise ExternalError(
            (_diagnostic(path, "$", "read", type(error).__name__, "可读取的本地部署文件"),)
        ) from error


def find_profile_by_model(profiles: Sequence[RobotProfile], model: str) -> RobotProfile | None:
    """从已加载快照中按机器人型号寻找说明档。

    Args:
        profiles: load_robot_profiles 返回的唯一型号快照，可为空。
        model: 机器人登记或数据集 robot_model 的原始字符串，精确匹配，不推断别名。

    Returns:
        对应说明档；型号没有说明档时返回 None，不影响该型号的登记和数据集浏览。

    Raises:
        无。

    Side Effects:
        无；只读传入快照，不查询数据库、文件或机器人。

    Time Semantics:
        使用调用方提供的事实版本，不读取时钟或刷新快照。
    """
    return next((profile for profile in profiles if profile.model == model), None)


def _read_profile(path: Path) -> RobotProfile:
    """把 TOML 和模型错误转成五段诊断，不把原始字段值或完整载荷写入日志。"""
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, UnicodeError) as error:
        raise InputError(
            (_diagnostic(path, "$", "toml", type(error).__name__, "有效的 UTF-8 TOML"),)
        ) from error
    try:
        return RobotProfile.model_validate(data)
    except ValidationError as error:
        diagnostics = tuple(
            _diagnostic(
                path,
                ".".join(str(part) for part in detail["loc"]) or "$",
                detail["type"],
                detail["msg"],
                "符合 RobotProfile 字段类型、必填项和一致性约束；未知事实省略对应键",
            )
            for detail in error.errors(
                include_input=False, include_url=False, include_context=False
            )
        )
        raise InputError(diagnostics) from error


def _diagnostic(
    path: Path,
    key: str,
    rule: str,
    actual: str,
    expected: str,
) -> Diagnostic:
    """只记录文件身份及安全的校验摘要，不回显可能误写在配置中的凭据。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL if rule == "read" else DiagnosticCategory.INPUT,
        stage="读取 RobotProfile",
        source="平台",
        objects=(
            DiagnosticObject(key="file", value=str(path)),
            DiagnosticObject(key="key", value=key),
        ),
        rule=f"robot_profile.{rule}",
        actual=actual,
        expected=expected,
        consequence="拒绝加载全部 RobotProfile，平台不能启动",
        next_step="按 ADR 0007 修正该文件，评审后重新启动平台",
    )
