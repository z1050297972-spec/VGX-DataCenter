"""下载计划的契约清单；HTTP 测试使用注入替身，不访问网络。"""

import pytest


def test_mirror_head_redirect_to_official() -> None:
    """首页 308 指向官方站时拒绝，不跟随跳转。"""
    pytest.skip("等待下载计划实现")


def test_mirror_api_redirect_to_official() -> None:
    """API 的 3xx 指向官方站时拒绝，即使首页通过。"""
    pytest.skip("等待下载计划实现")


def test_no_proxy_or_redirect_in_default_transport() -> None:
    """默认传输显式禁用代理和自动重定向，并设置超时。"""
    pytest.skip("等待下载计划实现")


def test_three_page_tree_uses_pinned_commit() -> None:
    """三页 Link next 按顺序获取，所有文件属于同一固定 commit。"""
    pytest.skip("等待下载计划实现")


def test_429_then_success() -> None:
    """429 后按退避重试，成功响应被正常处理。"""
    pytest.skip("等待下载计划实现")


def test_retries_exhausted() -> None:
    """连接、TLS、429 和 5xx 超过预算后返回外部失败诊断。"""
    pytest.skip("等待下载计划实现")


def test_gated_without_token() -> None:
    """受 gated 限制的仓库无 token 时要求用户处理，不列清单。"""
    pytest.skip("等待下载计划实现")


def test_disabled_repository() -> None:
    """已 disabled 的仓库拒绝生成计划并返回诊断。"""
    pytest.skip("等待下载计划实现")


def test_lfs_and_git_files() -> None:
    """清单分别保留普通文件 blob SHA-1 和 LFS 文件的两种校验值。"""
    pytest.skip("等待下载计划实现")


def test_token_never_leaks(caplog: pytest.LogCaptureFixture) -> None:
    """凭据不出现在计划、诊断、异常文本或日志中。"""
    pytest.skip("等待下载计划实现")


def test_include_exclude_fnmatchcase() -> None:
    """包含和排除区分大小写，星号跨斜杠，尾部斜杠补星号且排除优先。"""
    pytest.skip("等待下载计划实现")


def test_video_and_camera_filters() -> None:
    """不选视频和排除指定相机分别只过滤对应视频路径。"""
    pytest.skip("等待下载计划实现")


def test_dataset_preview_from_pinned_info() -> None:
    """从固定 commit 的元数据读取 episode、帧、FPS、版本、类型和相机。"""
    pytest.skip("等待下载计划实现")


def test_model_has_no_dataset_preview() -> None:
    """模型计划不读取数据集元数据且预览为空。"""
    pytest.skip("等待下载计划实现")


def test_bad_repo_id_rejected() -> None:
    """含点段、绝对路径或空段的 repo_id 不得构造暂存路径。"""
    pytest.skip("等待下载计划实现")


def test_staging_path_reuses_commit() -> None:
    """相同类型、仓库与提交复用暂存路径，不同类型隔离。"""
    pytest.skip("等待下载计划实现")


def test_insufficient_capacity_diagnostic() -> None:
    """空间不足诊断包含待下载字节数、可用字节数和目标根。"""
    pytest.skip("等待下载计划实现")


def test_complete_files_reduce_remaining_by_size_only() -> None:
    """仅以大小判断暂存文件完整并扣除，预检不计算哈希。"""
    pytest.skip("等待下载计划实现")


def test_readonly_or_offline_root_rejected() -> None:
    """目标根未登记为可写或不在线时不能生成可执行计划。"""
    pytest.skip("等待下载计划实现")


def test_token_file_missing_and_permission() -> None:
    """凭据文件不存在视为未设置，存在但权限不是 0600 时拒绝。"""
    pytest.skip("等待下载计划实现")


def test_untrusted_pagination_target() -> None:
    """分页地址不能将请求或凭据发送至镜像以外的主机。"""
    pytest.skip("等待下载计划实现")


def test_model_weights_path() -> None:
    """模型权重路径位于可写根的权重目录，安全分段且不进入导航层。"""
    pytest.skip("等待下载计划实现")


def test_untrusted_file_paths_and_symlinks() -> None:
    """恶意或重复清单路径被拒绝，暂存容量检查不跟随软链接逃出根。"""
    pytest.skip("等待下载计划实现")
