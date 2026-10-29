"""数据集索引替换（领域层，M1-01）；规则先算计划，SQLAlchemy事务只执行已核对计划。

调用方持导航写锁完成末次指纹核对及事务提交，防止核对后平台写入插队。
不在写事务内读取导航或存储根；失败由现有 session_scope 回滚，绝不先清空再分批提交。
"""

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from rdp.jobs.datasets import _index_write, _plan
from rdp.jobs.datasets._index_read import baseline
from rdp.jobs.datasets.fingerprint import DatasetFingerprint
from rdp.jobs.datasets.scan_types import (
    IndexedDataset,
    IndexReplacement,
    NavigationScan,
    ScanPublication,
    StorageScan,
)


def read_index_baseline(
    session: Session, requested_dataset_id: str | None, *, nav_root: Path | None = None
) -> tuple[IndexedDataset, ...]:
    """读取扫描范围内已有索引的身份，供新增、变更和消失判定。

    Args:
        session: 受管只读事务会话，由调用方关闭，不跨线程共享。
        requested_dataset_id: None为全量，否则为非空原编号，不要求索引已存在。
        nav_root: 显式绝对导航根；遇到无编号入口时必须提供，None仅允许全部入口身份已知。

    Returns:
        按编号及入口路径排序的基线，全量还包含dataset_id=None的旧入口；未索引返回空。
        不因查询为空断言导航数据不存在，单数据集范围不混入无关的未知身份入口。
        查询数量受MAX_SCAN_ENTRIES约束，损坏的指纹不转成空指纹。

    Raises:
        InputError: 索引记录/指纹损坏、请求编号非法或行数超过预算。
        ConflictError: 读取锁竞争超过调用方预算。
        ExternalError: 查询或读取I/O失败。
        DefectError: 非受管会话或映射类型错误。

    Side Effects:
        无（只读数据集及入口索引，不加载JSON全文、不访问文件系统）。

    Time Semantics:
        第一段拿到导航锁后调用，使用单个读事务快照，读完关闭再扫文件；不重试。
    """
    return baseline(session, requested_dataset_id, nav_root)


def plan_index_replacement(
    navigation: NavigationScan,
    storage: StorageScan,
    current: tuple[DatasetFingerprint, ...],
    *,
    committed_at: datetime,
) -> IndexReplacement:
    """把末次指纹核对结果变成可整体提交的替换与保留计划。

    Args:
        navigation: 第一段快照，含开始时的索引基线和消失候选。
        storage: 与该快照配对的第二段结果，允许NOT_RUN。
        current: 对navigation.datasets逐项重算的L12指纹，顺序和身份严格对应。
        committed_at: 注入的aware时刻，转UTC；不要求晚于开始以容忍墙钟回拨。

    Returns:
        不可变IndexReplacement；两次verifiable且相等才接受数据集投影和第二段值。
        不相等/不可验证保留旧索引并加DATASET_CHANGED提示，不能用旧指纹覆盖新结果。
        首次见到且没有旧入口的不可读项保留“无法读取”的位置占位、诊断及空字段，
        不发布第二段值，不声称指纹通过；已有可用入口仍保留旧行和新提示。
        全量仅删除基线中两次均确认所有入口消失的编号及未知身份入口；部分扫描不改其他编号或全局发现。
        空全量可清掉已确认消失的旧索引；枚举失败绝不能传一个假空快照执行删除。

    Raises:
        DefectError: 当前指纹遗漏/重复/范围不匹配、storage引用未知入口或时刻不是aware。

    Side Effects:
        无；不修改输入、不读取数据库、不重算哈希，不执行任何替换。

    Time Semantics:
        调用方在末次复核的同一导航写锁保护段计算计划并立即执行；不可缓存后晚些使用。
    """
    return _plan.plan(navigation, storage, current, committed_at)


def replace_index(session: Session, plan: IndexReplacement) -> ScanPublication:
    """在调用方的一个事务中执行已核对的索引替换计划。

    Args:
        session: 已进入BEGIN IMMEDIATE的受管写会话，调用方仍持导航写锁。
        plan: plan_index_replacement的未消费计划，范围及指纹在当前持锁段已经核对。

    Returns:
        ScanPublication的事务内结果；调用方必须等session_scope成功提交后才能对外返回或报完成。
        数据集按唯一规范副本展示；重复规范副本不任取，保留全部入口和发现。
        无dataset_id的损坏入口通过可空关联按位置展示，不捏造dataset_id。

    Raises:
        InputError: 现有索引损坏或计划字段不满足数据库契约。
        ConflictError: 写锁/约束竞争；整个事务必须回滚，不提交部分数据集。
        ExternalError: 插入、删除、刷新或数据库I/O失败，交session_scope整体回滚。
        DefectError: 非受管写会话、计划复用、外键/映射错误。

    Side Effects:
        同事务替换datasets/entries/documents/links/sources/findings并新增scan及各配置根状态。
        根清单来自navigation.registered_roots；未执行检查的根仅在名字、路径和挂载来源一致时
        沿用最近已知观察和原检查时间，
        从未检查的根记online=None、checked_at=None；不生成假检查时间。
        同路径且目标/身份未变的已有大小及时间保留，离线保留上次统计；目标改变则清空对应统计，
        不把旧路径的大小挂到新目标。NOT_RUN保留可复用磁盘观察，不清已有③④组发现。
        跳过者保留其代次和内容，只补本次跳过提示；全量替换全局发现，单数据集保留其他发现。
        最新代次标记同事务切换；仅清理既非最新又不再被任何索引/发现引用的代次及根状态，
        作业历史不删。失败保留整份旧索引，不写导航层或存储根，不自行commit。

    Time Semantics:
        哈希和磁盘探测已在事务外完成；UTC由UTCDateTime统一存取，锁预算沿用受管数据库。
        不在事务内等待存储、重试或响应取消，原子提交后下一检查点响应控制信号。
    """
    return _index_write.apply(session, plan)
