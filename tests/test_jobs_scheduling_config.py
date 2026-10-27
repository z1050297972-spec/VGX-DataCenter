"""09 契约测试清单；数据库/文件均使用临时目录，未实现的行为逐项跳过。"""

import pytest


def test_defaults() -> None:
    """K1/验收1：无 jobs 配置时 gpus=(0,1)、类型默认并发1，且配置来源仍可追踪。"""
    pytest.skip("09 契约待实现")


def test_empty_gpus() -> None:
    """K1：显式空 GPU 列表合法，表示不用 GPU，不回退默认两张卡。"""
    pytest.skip("09 契约待实现")


def test_gpu_validation() -> None:
    """契约：GPU 拒绝 bool、负数、超上界、字符串、重复及超过64项列表，未知配置项拒绝。"""
    pytest.skip("09 契约待实现")


def test_concurrency_bounds() -> None:
    """验收1：并发接受1和具名最大32，拒绝0、33、bool、浮点及字符串。"""
    pytest.skip("09 契约待实现")


def test_unknown_type() -> None:
    """契约：jobs.concurrency 的未登记键在 Web/worker 启动均拒绝，诊断指出配置键。"""
    pytest.skip("09 契约待实现")


def test_invalid_definition() -> None:
    """契约：JobRegistry 拒绝非法声明上限和非bool requires_gpu，不增加登记项。"""
    pytest.skip("09 契约待实现")


def test_resolve_sorted() -> None:
    """契约：覆盖优先于声明值，结果按类型/卡号排序且不因调用者随后修改配置而改变。"""
    pytest.skip("09 契约待实现")


def test_state_path() -> None:
    """契约：navigation_example 严格位于临时 state root，取路径不创建文件。"""
    pytest.skip("09 契约待实现")


def test_production_types() -> None:
    """契约：生产登记五种类型，两个清除为restart、三个示例为interrupt，只有example_gpu需卡。"""
    pytest.skip("09 契约待实现")


def test_required_dependencies_have_no_defaults() -> None:
    """阻塞3：run_worker/configure_jobs/claim_job与执行依赖/凭据构造缺必填关键字时TypeError；允许无值的字段也须显式None。"""
    pytest.skip("09 契约待实现")
