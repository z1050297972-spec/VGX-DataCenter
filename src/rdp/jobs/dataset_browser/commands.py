"""数据集作业提交（领域层，M1-03），复用M0 JobService，不执行类型函数或访问存储根。"""

from sqlalchemy import Engine

from rdp.accounts.service import authorize_job_actor
from rdp.infra.db.connection import session_scope
from rdp.jobs.dataset_browser import _scope
from rdp.jobs.datasets.catalog import RESCAN_TYPE
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobRecord

# 第02张拥有登记键，合并时对齐；本模块只向M0队列提交。
DATASET_SIZING_JOB_TYPE = "dataset_sizing"


class DatasetCommands:
    """当前账号的单数据集检查和统计提交，和查询模块的导入边界分离。"""

    def __init__(self, engine: Engine, jobs: JobService) -> None:
        """保存提交依赖。

        Args:
            engine: 受管SQLite引擎，与jobs使用同一对象。
            jobs: M0提交服务，由入口提供，不在此登记执行函数。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            仅保存依赖，不打开数据库或调用作业。

        Time Semantics:
            启动期同步构造，无等待或时钟读取。
        """
        self.engine = engine
        self.jobs = jobs

    def submit_rescan(self, request: JobRequest, dataset_id: str) -> JobRecord:
        """为当前账号提交一个单数据集重新扫描作业。

        Args:
            request: M0 JobRequest，提交人和审计来源不可由客户端覆盖。
            dataset_id: 已入索引的永久编号，遵循RescanParameters范围，不能传None触发全量。

        Returns:
            JobService.submit已提交的queued记录；type_name使用catalog.RESCAN_TYPE，
            参数只有dataset_id，即使worker离线也返回排队记录。

        Raises:
            DatasetNotFoundError: 提交前编号不在索引。
            DatasetQueryError: 编号不满足已合并扫描参数约束。
            JobInputError: 登记表缺少扫描类型或登记模型拒绝参数。
            AuthenticationError: JobService写事务重验时身份失效。
            PasswordChangeRequiredError: 提交时账号须改密。
            InputError: 索引或作业记录损坏。
            ConflictError: 作业提交/操作日志写锁竞争或编号耗尽。
            ExternalError: 作业和审计事务失败。
            DefectError: 服务装配或注入时刻非法。

        Side Effects:
            只委托M0提交作业与操作日志，同事务写入；不调用扫描执行器、不写索引或导航。
            范围预查后导航变化由worker处理，不把本次预查当执行许可；失败不留半条作业。

        Time Semantics:
            复用请求唯一UTC时刻；普通写锁5秒、失败补记100毫秒，不在HTTP等待作业完成。
        """
        dataset_id = _scope.identifier(dataset_id)
        self._check_scope(request, dataset_id)
        return self.jobs.submit(request, RESCAN_TYPE, {"dataset_id": dataset_id})

    def submit_sizing(self, request: JobRequest, dataset_id: str | None) -> JobRecord:
        """向已有队列提交手动统计大小，执行类型由第02张登记。

        Args:
            request: 当前会话及审计来源，使用当前账号而非系统身份。
            dataset_id: 已索引编号；None表示全量，拒绝附带存储根、IO优先级或路径。

        Returns:
            DATASET_SIZING_JOB_TYPE的新queued记录，parameters只有dataset_id；
            响应使用M0作业类型，大小结果由后续worker发布，提交时不假造新大小。

        Raises:
            DatasetNotFoundError: 非空编号未入索引。
            DatasetQueryError: 编号文本非法。
            JobInputError: 统计类型未登记或参数校验拒绝，不自行注册一个替代类型。
            AuthenticationError: 提交写事务中身份失效。
            PasswordChangeRequiredError: 账号须先改密。
            InputError: 数据库中的范围/作业数据损坏。
            ConflictError: 提交事务竞争或编号耗尽。
            ExternalError: 作业/操作日志持久化失败。
            DefectError: 统计提交装配、时钟或返回记录违反契约。

        Side Effects:
            M0同事务新增作业和提交日志，不import第02张模块、不遍历根、不在Web执行作业。

        Time Semantics:
            锁与补记预算沿用JobService.submit，不等待上次统计结束、不自动重试POST。
        """
        self._check_scope(request, dataset_id)
        return self.jobs.submit(request, DATASET_SIZING_JOB_TYPE, {"dataset_id": dataset_id})

    def _check_scope(self, request: JobRequest, dataset_id: str | None) -> None:
        """提交前只读检查身份和编号，实际执行资格与导航变化仍由worker处理。"""
        with session_scope(self.engine, read_only=True) as session:
            authorize_job_actor(session, request.identity, now=request.now)
            _scope.require_dataset(session, dataset_id)
