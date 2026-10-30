"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

import pytest

pytestmark = pytest.mark.skip(reason="M1-08：契约审核后逐函数 TDD 实现")


def test_changed_json_conflicts_without_write() -> None:
    """验证契约：验收 4/L12：临时导航预览后改变 JSON，在第 07 张流水线写锁下冲突，逐字节证明一行未写。"""
    raise NotImplementedError


def test_changed_link_and_names_conflict() -> None:
    """验证契约：L12：修改链接目标、删除入口或新增条目分别触发冲突，列出实际/期望及重新预览建议。"""
    raise NotImplementedError


def test_new_dataset_number_and_destination_conflict() -> None:
    """验证契约：L6/L12：最大编号变化或目的目录出现时整个写入冲突，不偷偷重分配编号。"""
    raise NotImplementedError


def test_shared_journal_rollback_recovery() -> None:
    """验证契约：L13/L14：两种新计划均走已有日志先行/逆序回滚/重启恢复；故障不留下不明半成品且不改存储目标。"""
    raise NotImplementedError


def test_apply_reindex_sizing_and_change_record() -> None:
    """验证契约：L15/L16 与验收 1：成功后同作业更新索引、提交统计，记录操作摘要与永久变更记录，来源可查询。"""
    raise NotImplementedError


def test_copy_drill_link_and_dataset_panel() -> None:
    """验证契约：验收 1 的自动替代：临时导航样本完成建链、场景一、预计 dataset-36 和格式副本，再扫描不新增需要处理；不读真实部署或挂载数据。"""
    raise NotImplementedError
