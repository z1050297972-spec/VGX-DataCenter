"""第 11 张 version_migration 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import pytest


def test_pending_not_active() -> None:
    """验证契约：0006在pending时不成为活动head；迁移激活前不得给现有jobs ORM注册未迁移列。"""
    pytest.skip("第 11 张：等待对应实现")


def test_upgrade_empty_and_history() -> None:
    """验证契约：0005→0006增加可空platform_version，旧行NULL，不把升级版本伪造成旧执行事实。"""
    pytest.skip("第 11 张：等待对应实现")


def test_fresh_latest() -> None:
    """验证契约：空库迁移至0006具有完整账号、日志、作业、调度结构，版本闸门接受最新head。"""
    pytest.skip("第 11 张：等待对应实现")


def test_constraints() -> None:
    """验证契约：版本列允许NULL与1/128码点，拒绝空值和129码点；原jobs约束和索引仍有效。"""
    pytest.skip("第 11 张：等待对应实现")


def test_sequence_preserved() -> None:
    """验证契约：升级/降级保留sqlite_sequence高水位，覆盖已有行及删除全部历史后空表，编号不复用。"""
    pytest.skip("第 11 张：等待对应实现")


def test_downgrade_refuses_data_loss() -> None:
    """验证契约：任意非NULL版本先拒绝降级，数据、schema和revision全不变；全NULL时可恢复0005。"""
    pytest.skip("第 11 张：等待对应实现")


def test_migration_failure_atomic() -> None:
    """验证契约：DDL/I/O故障整次事务回滚且升级前备份保留；不修改历史迁移文件。"""
    pytest.skip("第 11 张：等待对应实现")
