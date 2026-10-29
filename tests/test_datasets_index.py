"""索引原子替换和迁移契约；数据库仅使用tmp_path，活动迁移链另有M0回归约束。"""

import pytest


def test_atomic_rollback() -> None:
    """索引契约：替换中途注入数据库失败后旧八表行及当前代次完整保留，不出现部分新索引。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_atomic_visibility() -> None:
    """索引契约：并发只读连接只能看到发布前或发布后的完整索引，不能看到先删后建中间态。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_full_removal() -> None:
    """索引契约：全量仅删除基线中两次确认消失的数据集及无编号入口；空导航可清旧索引，枚举失败保留旧索引。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_single_scope() -> None:
    """索引契约：部分扫描不改其他数据集及全局发现，不清其他存储根最近已知状态。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_broken_entry_identity() -> None:
    """读取及索引契约：未知dataset_id入口以位置保存可见，不生成假编号；身份冲突和重复source_id完整保留。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unverifiable_placeholder() -> None:
    """索引契约：首次不可读入口只新增无法读取占位；不可验证状态不能覆盖已存在的可用投影或发布第二段值。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_preserve_sizes() -> None:
    """第02张交接：NOT_RUN/离线保持同目标上次统计值及时间，目标改变清空旧统计，不将None转换为零。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_storage_metadata_fields() -> None:
    """第02张交接：robot_type/fps/codebase_version、链接状态及检查时间、根离线原因、aria2/incomplete计数均可存取，未知值可区分。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_utc_roundtrip() -> None:
    """索引时间契约：全部检查及统计时刻往返为aware UTC，墙钟回拨不导致错误先后约束或丢弃结果。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_schema_constraints() -> None:
    """表结构契约：八表主外键、索引、空值及CHECK有效，重复入口主键/非法状态/负大小/不配对统计时间拒绝。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_migration_upgrade() -> None:
    """迁移契约：0006升级0007原子创建八表，保留全部M0数据和序列，失败回滚，DDL与声明逐项一致。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_migration_downgrade() -> None:
    """迁移契约：downgrade在任何DDL前抛InputError，保留当前索引与永久历史。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_obsolete_scan_cleanup() -> None:
    """索引契约：只清非最新且无索引或发现引用的扫描代次，跳过数据集仍能读到其旧根状态和检查时间。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_projection_fingerprint_race() -> None:
    """第一段读取JSON后、计算指纹前发生手工修改时标为不可验证，不能用新指纹发布旧投影。"""
    pytest.skip("M1-01：该契约尚未实现")
