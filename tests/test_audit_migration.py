"""0003隔离和将来激活的契约清单（07）；所有迁移样例仅在tmp_path，不触碰真实平台数据库。"""

import pytest


def test_pending_isolation() -> None:
    """迁移隔离：__abstract__不污染Base.metadata，pending/0003不进入Alembic图，当前head仍0002。"""
    pytest.skip("07 契约清单尚未实现")


def test_upgrade_schema() -> None:
    """验收1：激活0003后三表及索引CHECK与模型一致，两种日志无账号外键且主键AUTOINCREMENT。"""
    pytest.skip("07 契约清单尚未实现")


def test_upgrade_preserves() -> None:
    """验收1/7：升级前备份可读，原账号会话报错不变，不补历史日志或设置行。"""
    pytest.skip("07 契约清单尚未实现")


def test_upgrade_rollback() -> None:
    """规范7.1：第三表DDL失败全回滚到0002，无半张表，升级前备份仍在。"""
    pytest.skip("07 契约清单尚未实现")


def test_downgrade_rejected() -> None:
    """验收1：降级在执行SQL前抛InputError，不删除日志。"""
    pytest.skip("07 契约清单尚未实现")


@pytest.mark.parametrize(
    "case",
    [
        "operation_category",
        "missing_login_identity",
        "deletion_result",
        "retention_range",
        "singleton",
    ],
)
def test_database_constraints(case: str) -> None:
    """验收1/4/5：直接SQL也受结果类别、身份组合、设置单行和7-365边界约束。"""
    pytest.skip(f"07 契约清单尚未实现：{case}")
