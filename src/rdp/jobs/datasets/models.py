"""可重建数据集索引表（领域层，M1-01、ADR 0006），共用基础层 Base/UTCDateTime。

这里只声明表；不 create_all，不触发迁移。所有身份取自导航；损坏入口通过可空外键保留。
来源记录按入口及序号保存，避免跨视图差异或重复 source_id 被唯一约束吞掉。
第02张填写磁盘状态、meta字段及统计大小；NULL/unchecked表示未检查，不能伪装成零或在线。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class DatasetScanRow(Base):
    """一次成功发布的扫描元数据，失败扫描由永久作业记录追溯。

    Attributes:
        scan_id: 正整数索引代次主键，仅索引内部使用，可以随重建删除。
        job_id: 来源作业正编号，运维直接重建为 None；不外键绑定永久作业历史。
        scope: all/dataset，后者要求 requested_dataset_id 非空。
        requested_dataset_id: 单数据集扫描的永久编号；全量为 None。
        started_at: UTC扫描开始时刻。
        navigation_finished_at: UTC第一段结束时刻。
        committed_at: UTC提交观察时刻；时钟回拨允许早于开始，不用日期约束先后。
        navigation_elapsed_s: 第一段总单调耗时，非负秒，含等锁。
        lock_held_s: 第一段实际持锁非负秒，不含第二段或提交复核。
        storage_stage: not_run/completed，not_run 不意味着存储根离线。
        is_current: 最新成功发布批次标记，全库至多一行True。
    """

    __tablename__ = "dataset_scans"
    __table_args__ = (
        CheckConstraint("scan_id > 0 AND (job_id IS NULL OR job_id > 0)", name="ids"),
        CheckConstraint(
            "(scope = 'all' AND requested_dataset_id IS NULL) OR "
            "(scope = 'dataset' AND requested_dataset_id IS NOT NULL AND length(requested_dataset_id) > 0)",
            name="scope",
        ),
        CheckConstraint("navigation_elapsed_s >= 0 AND lock_held_s >= 0", name="duration"),
        CheckConstraint("storage_stage IN ('not_run','completed')", name="storage_stage"),
        CheckConstraint("is_current IN (0,1)", name="current_boolean"),
        Index(
            "ix_dataset_scans_current",
            "is_current",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    scan_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(Text)
    requested_dataset_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    navigation_finished_at: Mapped[datetime] = mapped_column(UTCDateTime())
    committed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    navigation_elapsed_s: Mapped[float] = mapped_column(Float)
    lock_held_s: Mapped[float] = mapped_column(Float)
    storage_stage: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean)


class ScanRootRow(Base):
    """每扫描代次每个已登记存储根的状态，不主动查询挂载表。

    Attributes:
        scan_id: 复合主键，外键 dataset_scans，删除代次时级联。
        name: 配置中的存储根名，非空，复合主键。
        path: 登记的绝对路径文本，不作为数据库读写路径。
        uuid: 登记的本地盘UUID；与nfs_export恰有一项非空，不因同名根换盘沿用旧观察。
        nfs_export: 登记的服务器:导出路径；与uuid互斥，不联网解析服务器名。
        writable: 登记写许可，不表示本扫描会写数据。
        online: 在线True/离线False/从未检查None；沿用旧观察时保留原checked_at。
        reason: 离线为 not_mounted/source_mismatch/timeout；在线或未检查为None。
        checked_at: UTC检查时刻；可沿用旧观察，从未检查为None，不伪造本次检查时间。
    """

    __tablename__ = "dataset_scan_roots"
    __table_args__ = (
        CheckConstraint("length(name) > 0 AND length(path) > 0", name="identity"),
        CheckConstraint("writable IN (0,1)", name="writable"),
        CheckConstraint(
            "(uuid IS NOT NULL AND length(uuid) > 0 AND nfs_export IS NULL) OR "
            "(uuid IS NULL AND nfs_export IS NOT NULL AND length(nfs_export) > 0)",
            name="source",
        ),
        CheckConstraint(
            "(online IS NULL AND reason IS NULL AND checked_at IS NULL) OR "
            "(online IS NOT NULL AND ((online = 1 AND reason IS NULL AND checked_at IS NOT NULL) OR "
            "(online = 0 AND reason IS NOT NULL AND "
            "reason IN ('not_mounted','source_mismatch','timeout') AND checked_at IS NOT NULL)))",
            name="status",
        ),
    )

    scan_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_scans.scan_id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    path: Mapped[str] = mapped_column(Text)
    uuid: Mapped[str | None] = mapped_column(Text)
    nfs_export: Mapped[str | None] = mapped_column(Text)
    writable: Mapped[bool] = mapped_column(Boolean)
    online: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DatasetRow(Base):
    """按永久编号关联视图的数据集索引，不能为坏入口生成新编号。

    Attributes:
        dataset_id: 非空永久编号主键，不复用、不重算。
        name: 规范入口目录名；缺规范副本时取路径最小格式入口名，仅作展示。
        canonical_entry_path: 唯一按任务入口相对路径；缺失或重复时None，不设循环外键。
        scan_id: 最后发布此数据集的代次外键；跳过的数据集保留旧代次。
        fingerprint: DatasetFingerprint 的JSON值；无法完整观察时仍存 verifiable=False。
        data_origin: 六种稳定来源编码；缺失、坏文件或规范入口不唯一时 unknown。
        recorded_size_bytes: 兼容旧库的记录值列；扫描统一写None，不再用于展示。
        size_bytes: 链接目标表观字节数，非负；尚未统计为None。
        size_checked_at: UTC大小统计时刻，与size_bytes同空同非空。
        scene: 规范副本的场景数组；未填写或无唯一规范副本为空数组（M1.5-12）。
            不校验是否在词表，词表外的值保留。
        tasks: 规范副本的任务原值数组，去重保序；未填写为空数组，永不为NULL。
        robot_model: 规范副本的机器人型号去首尾空白后的值；未填写为None。
        fps: 规范信息顶层正整数帧率，单位帧/秒；未填写为None。
    """

    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("length(dataset_id) > 0 AND length(name) > 0", name="identity"),
        CheckConstraint(
            "data_origin IN ('real','umi','ego','simulation','open_source','unknown')",
            name="origin",
        ),
        CheckConstraint(
            "recorded_size_bytes IS NULL OR recorded_size_bytes >= 0", name="recorded_size"
        ),
        CheckConstraint(
            "(size_bytes IS NULL AND size_checked_at IS NULL) OR "
            "(size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL)",
            name="size",
        ),
        CheckConstraint("fps IS NULL OR fps > 0", name="fps"),
        Index("ix_datasets_name", "name", "dataset_id"),
    )

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    canonical_entry_path: Mapped[str | None] = mapped_column(Text)
    scan_id: Mapped[int] = mapped_column(ForeignKey("dataset_scans.scan_id"), index=True)
    fingerprint: Mapped[dict[str, object]] = mapped_column(JSON)
    data_origin: Mapped[str] = mapped_column(Text)
    recorded_size_bytes: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    size_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scene: Mapped[list[str]] = mapped_column("scene_json", JSON, server_default=text("'[]'"))
    # server_default 让 0012 迁移给旧行补空数组；下一次扫描按导航层内容重写。
    tasks: Mapped[list[str]] = mapped_column(JSON, server_default=text("'[]'"))
    robot_model: Mapped[str | None] = mapped_column(Text)
    fps: Mapped[int | None] = mapped_column(Integer)


class EntryRow(Base):
    """每个物理入口一行；坏JSON和重复按任务身份不能让入口消失。

    Attributes:
        path: 导航相对路径主键，非空，入口身份由位置确定。
        dataset_id: 可空数据集外键；三文件全坏时None，列表按该行名称显示损坏入口。
        scan_id: 本入口最后发布代次外键。
        view: task/format。
        format: task时None；format时为登记的稳定格式键。
        version: 非空格式版本或None，task必为None；lerobot入口必须非空。
        name: 目录名，非空。
        dataset_roots: 当前入口声明的绝对路径数组；不以规范副本覆盖以便发现差异。
        provenance_present: 来源.json目录项存在性，不表示内容合法。
        fingerprint: 单入口EntryFingerprint的JSON值。
        recorded_size_bytes: 兼容旧库的记录值列；扫描统一写None，不再用于展示。
        size_bytes: 本入口所有链接目标表观大小之和，非负或None。
        size_checked_at: UTC统计时刻，与size_bytes成对。
        aria2_count: 同次大小遍历发现的.aria2数，非负或None（未统计）。
        incomplete_count: 同次大小遍历发现的.incomplete数，非负或None。
    """

    __tablename__ = "dataset_entries"
    __table_args__ = (
        CheckConstraint("length(path) > 0 AND length(name) > 0", name="identity"),
        CheckConstraint(
            "(view = 'task' AND format IS NULL AND version IS NULL) OR "
            "(view = 'format' AND format IS NOT NULL AND "
            "((format = 'lerobot' AND version IS NOT NULL AND length(version) > 0) OR "
            "(format IN ('mcap','archives') AND version IS NULL)))",
            name="location",
        ),
        CheckConstraint("provenance_present IN (0,1)", name="provenance"),
        CheckConstraint(
            "recorded_size_bytes IS NULL OR recorded_size_bytes >= 0", name="recorded_size"
        ),
        CheckConstraint(
            "(size_bytes IS NULL AND size_checked_at IS NULL AND aria2_count IS NULL AND incomplete_count IS NULL) OR "
            "(size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL AND "
            "aria2_count IS NOT NULL AND aria2_count >= 0 AND incomplete_count IS NOT NULL AND incomplete_count >= 0)",
            name="size",
        ),
        Index("ix_dataset_entries_tree", "view", "format", "version", "name"),
    )

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("dataset_scans.scan_id"), index=True)
    view: Mapped[str] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    dataset_roots: Mapped[list[str]] = mapped_column(JSON)
    provenance_present: Mapped[bool] = mapped_column(Boolean)
    fingerprint: Mapped[dict[str, object]] = mapped_column(JSON)
    recorded_size_bytes: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    size_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    aria2_count: Mapped[int | None] = mapped_column(Integer)
    incomplete_count: Mapped[int | None] = mapped_column(Integer)


class DocumentRow(Base):
    """三份JSON的读取副本；详情实时读取仍以导航文件为准。

    Attributes:
        entry_path: 复合主键、入口外键，删除入口级联。
        name: 复合主键，三份必需JSON文件名之一。
        payload: 完整有效原对象，保留未知字段；不可解析为None，不用空对象替代。
        schema_version: 有效版本1，文件不可用为None。
        sha256: 可读原字节的64位小写摘要；打不开为None，坏JSON仍可有摘要。
    """

    __tablename__ = "dataset_documents"
    __table_args__ = (
        CheckConstraint("name IN ('原始路径.json','数据集信息.json','子任务.json')", name="name"),
        CheckConstraint("schema_version IS NULL OR schema_version = 1", name="schema_version"),
        CheckConstraint(
            "sha256 IS NULL OR (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*')",
            name="sha256",
        ),
    )

    entry_path: Mapped[str] = mapped_column(
        ForeignKey("dataset_entries.path", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))
    schema_version: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(Text)


class LinkRow(Base):
    """入口声明的链接清单；实际链接另由入口指纹完整保留，能检出多出来的链接。

    Attributes:
        entry_path: 复合主键、入口外键，删除入口级联。
        ordinal: 原JSON数组序号，从0开始的复合主键，重复名字不覆盖原记录。
        name: 声明链接名，非空。
        source_path: 声明绝对目标路径，不 resolve。
        source_type: 声明目标类型原文。
        derived_entry_path: 推导的链接导航路径。
        observed_target: 实际readlink原文；链接缺失或读取失败为None，由status/发现区分。
        storage_root_name: 第02张识别的配置根名；未检查或根未登记为None。
        status: unchecked/available/missing/broken/offline/mismatch/unregistered。
        checked_at: UTC磁盘检查时刻；unchecked时None。
        size_bytes: 单链接目标表观字节数，非负或None。
        size_checked_at: UTC统计时刻，与size_bytes成对。
    """

    __tablename__ = "dataset_links"
    __table_args__ = (
        CheckConstraint("ordinal >= 0 AND length(name) > 0", name="identity"),
        CheckConstraint(
            "status IN ('unchecked','available','missing','broken','offline','mismatch','unregistered')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'unchecked' AND checked_at IS NULL) OR (status != 'unchecked' AND checked_at IS NOT NULL)",
            name="checked",
        ),
        CheckConstraint(
            "(size_bytes IS NULL AND size_checked_at IS NULL) OR (size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL)",
            name="size",
        ),
        Index("ix_dataset_links_status", "status", "entry_path"),
    )

    entry_path: Mapped[str] = mapped_column(
        ForeignKey("dataset_entries.path", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    derived_entry_path: Mapped[str] = mapped_column(Text)
    observed_target: Mapped[str | None] = mapped_column(Text)
    storage_root_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    size_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SourceRow(Base):
    """每入口每个数据块的索引和第02张读取的筛选值。

    Attributes:
        entry_path: 复合主键、入口外键，删除入口级联。
        ordinal: 源数组非负序号，复合主键；不唯一限制source_id以保留异常数据。
        source_id: 原始永久数据块编号，非空。
        original_path: 首次登记位置，原样保存且不检查存在性。
        direct_path: 当前位置绝对文本。
        derived_entry_path: 推导导航路径或未覆盖时的绝对direct_path。
        format: 数据块格式原文，可空，不套入口格式覆盖。
        version: 数据块格式版本，缺省或null为空。
        validation_status: 历史核验状态原文，可空。
        storage_root_name: 当前存储根配置名，未检查/未登记为空。
        status: unchecked/available/missing/offline/unregistered。
        checked_at: UTC路径检查时刻；unchecked为空。
        robot_type: meta/info.json型号标签；unknown/null/读不到/非LeRobot归None。
        fps: meta中的有限正数，单位帧/秒；未知为None。
        fps_rounded: 按非负数半入规则四舍五入的整数，未知为None，只用于原文件参考和回填。
        codebase_version: meta中的非空版本原文；未知为None。
        meta_checked_at: UTC meta读取检查时刻；尚未检查为空。
    """

    __tablename__ = "dataset_sources"
    __table_args__ = (
        CheckConstraint("ordinal >= 0 AND length(source_id) > 0", name="identity"),
        CheckConstraint(
            "status IN ('unchecked','available','missing','offline','unregistered')", name="status"
        ),
        CheckConstraint(
            "(status = 'unchecked' AND checked_at IS NULL) OR (status != 'unchecked' AND checked_at IS NOT NULL)",
            name="checked",
        ),
        CheckConstraint(
            "(fps IS NULL AND fps_rounded IS NULL) OR (fps IS NOT NULL AND fps > 0 AND fps < 1e308 AND fps_rounded IS NOT NULL AND fps_rounded >= 0)",
            name="fps",
        ),
        Index("ix_dataset_sources_identity", "source_id", "entry_path"),
        Index("ix_dataset_sources_robot", "robot_type", "entry_path"),
        Index("ix_dataset_sources_fps", "fps_rounded", "entry_path"),
    )

    entry_path: Mapped[str] = mapped_column(
        ForeignKey("dataset_entries.path", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text)
    original_path: Mapped[str] = mapped_column(Text)
    direct_path: Mapped[str] = mapped_column(Text)
    derived_entry_path: Mapped[str] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str | None] = mapped_column(Text)
    storage_root_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    robot_type: Mapped[str | None] = mapped_column(Text)
    fps: Mapped[float | None] = mapped_column(Float)
    fps_rounded: Mapped[int | None] = mapped_column(Integer)
    codebase_version: Mapped[str | None] = mapped_column(Text)
    meta_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class FindingRow(Base):
    """按归属及规则存有界样例；跳过某数据集不抹掉它的旧发现。

    Attributes:
        owner_key: 复合主键，dataset:编号、entry:路径或global，禁止用猜测编号关联坏入口。
        group: 复合主键，json/views/disk/storage。
        severity: 复合主键，action_required/notice。
        rule: 复合主键，非空稳定规则码。
        scan_id: 此组最近更新代次外键。
        total: 完整发现条数，正整数；不等于样例数。
        samples: 前至多DIAGNOSTIC_SAMPLE_LIMIT条统一Diagnostic的JSON数组，至少一条。
    """

    __tablename__ = "dataset_findings"
    __table_args__ = (
        CheckConstraint(
            "length(owner_key) > 0 AND length(rule) > 0 AND total > 0", name="identity_count"
        ),
        CheckConstraint("\"group\" IN ('json','views','disk','storage')", name="group"),
        CheckConstraint("severity IN ('action_required','notice')", name="severity"),
        Index("ix_dataset_findings_panel", "group", "severity", "rule"),
    )

    owner_key: Mapped[str] = mapped_column(Text, primary_key=True)
    group: Mapped[str] = mapped_column(Text, primary_key=True)
    severity: Mapped[str] = mapped_column(Text, primary_key=True)
    rule: Mapped[str] = mapped_column(Text, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("dataset_scans.scan_id"), index=True)
    total: Mapped[int] = mapped_column(Integer)
    samples: Mapped[list[dict[str, object]]] = mapped_column(JSON)
