"""09 契约测试清单；数据库/文件均使用临时目录，未实现的行为逐项跳过。"""

import pytest


def test_authentication() -> None:
    """契约：真实应用GET调度未登录401、强制改密403，普通成员与管理员均可200，鉴权先于查询。"""
    pytest.skip("09 契约待实现")


def test_read_only() -> None:
    """契约：真实API只从数据库及入口catalog读取，不探测nvidia-smi、不读配置文件/worker内存/导航层。"""
    pytest.skip("09 契约待实现")


def test_resource_snapshot() -> None:
    """契约：类型上限和running/cancelling计数正确、终态GPU只作历史不占卡、写锁持有人正确，编号是文本。"""
    pytest.skip("09 契约待实现")


def test_schedule_snapshot() -> None:
    """契约：每日下次UTC时刻、最近作业链接与六态/结果正确，未提交为null，不重算作业结果。"""
    pytest.skip("09 契约待实现")


def test_offline_display() -> None:
    """契约：离线worker返回False并保留最后占用副本，查询故障502不冒充空闲或离线。"""
    pytest.skip("09 契约待实现")


def test_system_response() -> None:
    """契约：系统提交人account_id为JSON null而非字符串None，名字系统、deleted=False。"""
    pytest.skip("09 契约待实现")


def test_job_waiting() -> None:
    """契约：列表/详情包含等待原因和卡号，等待不改变state；终态等待/持锁清空但卡号保留。"""
    pytest.skip("09 契约待实现")


def test_example_payloads() -> None:
    """契约：真实示例提交端点的时长bool/超界/额外字段/路径为安全422，合法参数201且写当前账号审计。"""
    pytest.skip("09 契约待实现")


def test_missing_configuration() -> None:
    """契约：未装配调度服务时新接口502，原接口仍正常；configure_jobs必须显式提供catalog，不在请求内找默认配置。"""
    pytest.skip("09 契约待实现")


def test_inconsistent_display() -> None:
    """契约：数据库双持锁/双卡主是DefectError而非随机选一条，统一错误编号响应。"""
    pytest.skip("09 契约待实现")


def test_system_reserved_account() -> None:
    """契约：显示名系统的正编号账号照常提交/重提并按编号显示；只有空编号是固定系统身份，OPS_ACTOR不能提交。"""
    pytest.skip("09 契约待实现")


def test_excluded_gpus_visible_without_hardware_access() -> None:
    """负责人决定：真实调度GET展示被移出的卡、诊断和核对时刻；未知实例显示unknown，Web不调用核卡或资源池。"""
    pytest.skip("09 契约待实现")
