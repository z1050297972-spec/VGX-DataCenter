"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

import pytest

pytestmark = pytest.mark.skip(reason="M1-08：契约审核后逐函数 TDD 实现")


def test_link_target_must_exist() -> None:
    """验证契约：L1：在线本地存储根下目标不存在时拒绝，导航和目标均不变。"""
    raise NotImplementedError


def test_link_target_must_be_absolute() -> None:
    """验证契约：L1：相对目标路径按参数错误拒绝，所有 SetLinkStep 都是绝对目标。"""
    raise NotImplementedError


def test_link_target_must_be_registered() -> None:
    """验证契约：L1：原始目标不属于任何登记根时拒绝。"""
    raise NotImplementedError


def test_link_realpath_must_stay_registered() -> None:
    """验证契约：L1：祖先软链接使 realpath 逃出登记根时拒绝。"""
    raise NotImplementedError


def test_link_target_outside_navigation() -> None:
    """验证契约：L1：目标位于导航根内部时拒绝，即使同样落在登记根下。"""
    raise NotImplementedError


def test_link_target_not_symlink() -> None:
    """验证契约：L1：目标自身是软链接时拒绝，不能链到链接。"""
    raise NotImplementedError


def test_link_destination_stays_in_views() -> None:
    """验证契约：L1：禁止格式、版本或名称穿越，所有目的都在两个视图的入口下。"""
    raise NotImplementedError


def test_link_name_no_slash() -> None:
    """验证契约：L1：链接名含 / 时拒绝，不产生多层路径。"""
    raise NotImplementedError


def test_link_name_no_dot_prefix() -> None:
    """验证契约：L1：链接名以 . 开头时拒绝，包括 . 和 ..。"""
    raise NotImplementedError


def test_link_name_no_reserved_json() -> None:
    """验证契约：L1：四份 JSON 保留名逐个拒绝，不覆盖事实文件。"""
    raise NotImplementedError


def test_names_reject_empty_and_nul() -> None:
    """验证契约：执行线名称规则：空名及 NUL 无法作为目录分量，模型拒绝。"""
    raise NotImplementedError


def test_dataset_name_uses_link_rules() -> None:
    """验证契约：最后 Comment：数据集名共用不含 /、不以 . 开头及保留名规则。"""
    raise NotImplementedError


def test_dataset_name_cannot_collide() -> None:
    """验证契约：最后 Comment：按任务下同名目录、文件、链接或断链均拒绝。"""
    raise NotImplementedError


def test_readonly_local_root_is_allowed() -> None:
    """验证契约：L1 与 ADR 0006：只读本地存储根可作为链接目标，整个操作不改目标。"""
    raise NotImplementedError


def test_root_offline_identity_timeout() -> None:
    """验证契约：ADR 0006：根离线、挂错源、超时分别以外部失败结束，不伪装成路径缺失。"""
    raise NotImplementedError


def test_nas_is_out_of_scope() -> None:
    """验证契约：工单不做项：NAS 目标明确拒绝，不自行批准 1B。"""
    raise NotImplementedError


def test_meta_info_is_authoritative() -> None:
    """验证契约：L3 与最后 Comment：有元信息时用其格式/版本，不被 fallback_format 覆盖；v3.0 映射到格式版本 3.0。"""
    raise NotImplementedError


def test_missing_meta_uses_selected_format() -> None:
    """验证契约：最后 Comment：mcap/tar 无元信息时用登记格式选择，sources[].version 明确 null。"""
    raise NotImplementedError


def test_missing_meta_requires_selection() -> None:
    """验证契约：最后 Comment：缺元信息且未选择格式时拒绝，不猜格式。"""
    raise NotImplementedError


def test_bad_meta_is_not_missing() -> None:
    """验证契约：契约：损坏、越界、超预算或不可读元信息不能静默降级为缺文件。"""
    raise NotImplementedError


def test_format_registry_and_version_layer() -> None:
    """验证契约：ADR 0006：拒绝未登记格式；lerobot 必填版本，mcap/archives 不接收版本。"""
    raise NotImplementedError


def test_format_selection_no_duplicates() -> None:
    """验证契约：契约：重复格式位置拒绝，不能悄悄去重后预览。"""
    raise NotImplementedError


def test_origin_required_and_registered() -> None:
    """验证契约：L5：数据来源必填且来自 DATA_ORIGINS，显式未知可用，英文筛选键不可用。"""
    raise NotImplementedError


def test_budgets_and_control_checkpoints() -> None:
    """验证契约：规范 2.7：作业参数 16 KiB、导航文件及入口预算生效，构造过程中取消/停止及时退出。"""
    raise NotImplementedError
