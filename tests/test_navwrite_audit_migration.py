"""操作日志扩展与 0010 迁移的契约测试清单（M1-07，L15）。

骨架阶段全部跳过。
"""

import pytest


def test_new_operation_codes_are_stable_strings() -> None:
    """L15：七个新操作码的字符串值固定，旧值含义不变。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_audit_values_new_fields_whitelisted() -> None:
    """L15：dataset_ids、dataset_count、file_count、link_count、change_record_id、reverts_job_id 在白名单里，超过 20 个编号被拒绝。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_operation_detail_fields_cover_every_operation() -> None:
    """契约：OPERATION_DETAIL_FIELDS 覆盖每一个 OperationType，撤回多一个 reverts_job_id。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_navigation_write_object_ref_validation() -> None:
    """契约 ObjectRef：navigation_write 的对象编号是规范十进制作业编号，名字为“写导航层 #编号”。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_old_rows_unchanged_by_0010() -> None:
    """迁移 v0010：升级后 operation_logs 全部旧行、索引和发号高水位不变。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_0010_accepts_navigation_write_kind() -> None:
    """迁移 v0010：升级后 object_kind 可写 navigation_write，旧值仍可写，未知值被 CHECK 拒绝。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_0010_creates_marker_table() -> None:
    """迁移 v0010：创建单行表 nav_recovery_failure，约束与冻结 DDL 一致。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_0010_downgrade_refused() -> None:
    """迁移 v0010：降级被拒绝，保留当前结构和数据。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_0010_matches_orm_after_activation() -> None:
    """迁移 v0010：移入 versions 后 compare_metadata 对 ORM 无差异。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_import_boundary_contract_present() -> None:
    """规范 1.4：pyproject 的 import-linter 合约禁止 rdp.api、rdp.ops 直接 import atomic、recovery、pipeline、jobs。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_api_audit_schema_accepts_navigation_write_kind() -> None:
    """契约：操作日志接口的对象种类包含 navigation_write，OpenAPI 与生成类型保持同步。"""
    pytest.skip("M1-07：该契约尚未实现")
