"""定时提交去重记录（领域层，09）；调用方拥有事务，不绕过 JobService 提交作业。"""

from datetime import date

from sqlalchemy.orm import Session

from rdp.jobs.scheduling_types import ScheduleSubmission


def latest_submission(session: Session, schedule_name: str) -> ScheduleSubmission | None:
    """读取一个登记名最近成功提交的记录。

    Args:
        session: 受管只读或写 Session，不跨线程复用。
        schedule_name: 已验证的稳定名字，1-64 码点。

    Returns:
        按 job_id DESC 的最近一条，不按可回拨的 submitted_at 排序；从未提交为 None。

    Raises:
        InputError: 数据库或存量日期损坏。
        ConflictError: 读取锁冲突。
        ExternalError: 查询 I/O 失败。
        DefectError: 名字、Session 或映射非法。

    Side Effects:
        无；只读一行，不查询作业日志或执行结果。

    Time Semantics:
        返回保存的 UTC 提交时刻和本地日期，不读取当前时钟、不补跑。
    """
    raise NotImplementedError


def submission_dates(
    session: Session, schedule_name: str, start: date, end: date
) -> frozenset[date]:
    """读取一个有界日期窗口中的已提交日期，支持墙钟回拨后的精确去重展示。

    Args:
        session: 受管只读 Session。
        schedule_name: 稳定登记名字。
        start: 含下界的本地日期。
        end: 不含上界的本地日期，晚于 start，跨度至多 SCHEDULE_LOOKAHEAD_DAYS。

    Returns:
        无序不可变日期集合，最多窗口天数项；没有提交为一个空集合。

    Raises:
        InputError: 数据库或日期行损坏。
        ConflictError: 读取锁竞争。
        ExternalError: 数据库 I/O 失败。
        DefectError: 非日期输入、窗口非法或 Session 非受管只读。

    Side Effects:
        无；只读 (schedule_name, local_date) 索引，不加载窗口外的历史记录。

    Time Semantics:
        日期不按 UTC 转换；候选范围由注入时钟的本地日期计算，不用系统当天日期。
    """
    raise NotImplementedError


def insert_submission(session: Session, submission: ScheduleSubmission) -> None:
    """在新作业和审计的同一事务登记日期唯一性。

    Args:
        session: 已获 BEGIN IMMEDIATE 的受管写 Session；对应作业尚未提交。
        submission: 作业编号与当次提交一致的 UTC 时刻和本地日期。

    Returns:
        无；flush 成功不代表外层事务已提交。

    Raises:
        ConflictError: (schedule_name,local_date) 已存在或 job_id 重复；调用方整体回滚新作业及日志。
        InputError: 数据库损坏。
        ExternalError: 插入/flush 失败。
        DefectError: 非法字段、UTC 时刻、缺少对应作业或非受管写 Session。

    Side Effects:
        只追加一行，不修改历史提交；唯一约束保证重启、回拨或并发调用不能重复提交同一天。

    Time Semantics:
        时刻完全使用 submission.submitted_at，不二次取钟；不在事务内等待定时点或重试。
    """
    raise NotImplementedError
