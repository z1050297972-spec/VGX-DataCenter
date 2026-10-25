"""工单06前向迁移测试；骨架清单，实施时只用 tmp_path/临时数据库和固定 aware 时钟。"""

import pytest


def test_upgrade_new() -> None:
    """验证契约：激活0002后空库升级到新head，账号、会话两表和原报错表结构与共用MetaData比较无差异。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")


def test_upgrade_existing() -> None:
    """验证契约：0001升级前先生成可读取备份，已有报错数据不变，不创建默认账号。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")


def test_upgrade_noop() -> None:
    """验证契约：再次migrate不改schema或数据、不新增备份。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")


def test_upgrade_failure() -> None:
    """验证契约：DDL中途失败整体回滚，版本仍0001，保留完整升级前备份，无半张表。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")


def test_upgrade_utc_checks() -> None:
    """验证契约：迁移的UTC文本列、索引、约束名、AUTOINCREMENT及会话级联外键与模型一致。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")


def test_upgrade_gate() -> None:
    """验证契约：旧版本启动被闸门拒绝，不能自动迁移。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")


def test_downgrade_refused() -> None:
    """验证契约：任何降级在SQL前给InputError，数据库和版本不变，提示停服务人工恢复备份。"""
    pytest.skip("工单 06 契约骨架，待实现与 TDD")
