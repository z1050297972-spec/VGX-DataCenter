"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

import pytest

pytestmark = pytest.mark.skip(reason="M1-08：契约审核后逐函数 TDD 实现")


def test_link_plan_updates_manifest() -> None:
    """验证契约：L3：追加 links，未被覆盖才加一个 source；entry_path 推导且 source_id 首次分配后不重算。"""
    raise NotImplementedError


def test_source_coverage_uses_path_boundary() -> None:
    """验证契约：L3：已有数据块覆盖目标时不重复追加，路径 /a/b 不覆盖 /a/bc，source_id 碰撞拒绝。"""
    raise NotImplementedError


def test_dataset_roots_notice_and_diff() -> None:
    """验证契约：L1：不在 dataset_roots 内才追加，报告和 creation 差异明确列出目标及提示。"""
    raise NotImplementedError


def test_existing_different_target_rejected() -> None:
    """验证契约：L2 场景一：已有同名不同目标拒绝，诊断提示改走改指向。"""
    raise NotImplementedError


def test_same_target_without_registration_rejected() -> None:
    """验证契约：L2：只有同目标但未在 links[] 登记时仍拒绝，不把不一致当 noop。"""
    raise NotImplementedError


def test_registered_same_target_is_noop() -> None:
    """验证契约：L2：同目标且已登记返回空步骤，即使勾新格式也不写，不强迫补选格式或读取元信息，执行结果为 noop。"""
    raise NotImplementedError


def test_link_selection_and_all_replicas() -> None:
    """验证契约：L4/L8：链接只先改规范副本；勾选入口加链接，全部已有副本按自己的 links 重生成。"""
    raise NotImplementedError


def test_zero_and_multiple_format_entries() -> None:
    """验证契约：L4：零和多个勾选都可用，新入口父目录先创建；archives 使用原登记目录名。"""
    raise NotImplementedError


def test_egopro_and_alpha_replica_regression() -> None:
    """验证契约：L8/L9：EgoProDemo 对拍正确，alpha 不可达三块只留规范副本且预览列出遗漏。"""
    raise NotImplementedError


def test_create_dataset_full_plan() -> None:
    """验证契约：L5：一个计划建目录、第一链接、规范三 JSON 和来源文件，格式副本只有三 JSON。"""
    raise NotImplementedError


def test_information_and_subtask_skeletons() -> None:
    """验证契约：L5：信息 14 项按手册固定编号/名称、正文全空；子任务 tasks=[] 且 task_count=0，不补信息 schema_version。"""
    raise NotImplementedError


def test_provenance_actor_and_unknown_lineage() -> None:
    """验证契约：L5 与 ADR 0008：来源必填、真实提交人印记、UTC 时刻、采集任务 null、血缘空；未知也保留人工印记。"""
    raise NotImplementedError


def test_allocate_36_from_max_35() -> None:
    """验证契约：L6：临时导航已有 01-35 时预计 dataset-36；至少两位，移除目录最大编号参与计算且不可复用。"""
    raise NotImplementedError


def test_allocation_unreadable_id_rejected() -> None:
    """验证契约：L6：入口读不出编号或已移除命名不合约时拒绝，不猜最大编号。"""
    raise NotImplementedError


def test_preview_captures_complete_state() -> None:
    """验证契约：L12：记录规范及所有格式入口的 JSON 含来源哈希、条目清单、readlink；新建记录目的不存在和最大编号。"""
    raise NotImplementedError


def test_builder_reads_consistent_preimages() -> None:
    """验证契约：契约：构造中 JSON/链接变化不得把旧正文和新指纹拼成计划，返回冲突或不可验证。"""
    raise NotImplementedError


def test_json_unknown_keys_and_derived_fields() -> None:
    """验证契约：L10/L11：保留未知键和顺序，2 空格、中文、末尾换行，推导 version 显式 null，不补信息 schema_version。"""
    raise NotImplementedError


def test_report_matches_exact_plan() -> None:
    """验证契约：规范 2.2/2.4：creation 路径与步骤逐一对应，计数不重算，检查范围及已知例外清楚展示，预览不写导航。"""
    raise NotImplementedError
