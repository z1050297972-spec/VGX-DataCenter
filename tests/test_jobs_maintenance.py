"""09 契约测试清单；数据库/文件均使用临时目录，未实现的行为逐项跳过。"""

import pytest


def test_two_rules() -> None:
    """验收7：生产每天03:00只登记purge_errors和purge_audit_logs；后者联合清两种日志，不注册M1统计或备份。"""
    pytest.skip("09 契约待实现")


def test_errors_boundary() -> None:
    """验收7：报错保留期取配置，严格早于UTC截止才删；恰好边界、较新、未来记录都留。"""
    pytest.skip("09 契约待实现")


def test_audit_boundary() -> None:
    """验收7：操作/登录日志用当前共同保留期，分别断言严格早于才删、边界及未来均留。"""
    pytest.skip("09 契约待实现")


def test_audit_atomic() -> None:
    """验收7：第二张日志表删除失败时第一张也回滚，作业失败而非成功零计数。"""
    pytest.skip("09 契约待实现")


def test_zero_counts() -> None:
    """契约：无匹配记录仍完成，摘要零条；正常结果只由calculate_outcome计算，不写假失败。"""
    pytest.skip("09 契约待实现")


def test_summary_counts() -> None:
    """契约：报错删除数写入摘要，日志清除的两类独立计数在摘要可辨别，总条目为两数之和，日志结尾一致。"""
    pytest.skip("09 契约待实现")


def test_retention_runtime() -> None:
    """契约：提交以后修改日志保留设置，执行时用最新值；报错保留期来自worker配置而非作业参数。"""
    pytest.skip("09 契约待实现")


def test_restart_idempotent() -> None:
    """契约：两个清除类型均restart，删除提交后崩溃可重跑，摘要只记本次实际删除数，不伪造旧数。"""
    pytest.skip("09 契约待实现")


def test_cancel_checkpoint() -> None:
    """契约：取消在清除事务前后响应，提交后的删除不恢复，不在两表原子清除中间中断。"""
    pytest.skip("09 契约待实现")


def test_bad_clock() -> None:
    """契约：注入坏时钟在清除前DefectError，不错归AuditInputError或删除数据。"""
    pytest.skip("09 契约待实现")


def test_no_recursive_audit() -> None:
    """契约：清除执行不递归写清除操作日志，系统提交动作仍有操作日志，两个恢复重跑不重复提交审计。"""
    pytest.skip("09 契约待实现")
