"""直接验证基础层编号契约与搬移前的正则值，不依赖数据库或日志。"""

import pytest

from rdp.infra.ids import ERROR_ID_PATTERN, error_source_kind, is_request_id

# 请求编号的四种合法 variant 与格式边界；期望值手写，不用被测规则生成。
REQUEST_ID_CASES = (
    ("123456789abc4def8abc123456789abc", True),
    ("123456789abc4def9abc123456789abc", True),
    ("123456789abc4defaabc123456789abc", True),
    ("123456789abc4defbabc123456789abc", True),
    ("123456789ABC4DEF8ABC123456789ABC", False),
    ("123456789abc3def8abc123456789abc", False),
    ("123456789abc5def8abc123456789abc", False),
    ("123456789abc4def7abc123456789abc", False),
    ("123456789abc4defcabc123456789abc", False),
    ("123456789abc4def8abc123456789ab", False),
    ("123456789abc4def8abc123456789abcd", False),
    ("g23456789abc4def8abc123456789abc", False),
    ("12345678-9abc-4def-8abc-123456789abc", False),
    ("", False),
    (" ", False),
    (" 123456789abc4def8abc123456789abc", False),
    ("123456789abc4def8abc123456789abc ", False),
    ("123456789abc4def8abc123456789abc\n", False),
)


@pytest.mark.parametrize(
    ("identifier", "expected"),
    (*REQUEST_ID_CASES, (None, False), (1, False), (b"123456789abc4def8abc123456789abc", False)),
)
def test_is_request_id(identifier: object, expected: bool) -> None:
    """验证契约：只接受小写 uuid4 hex；拒绝错误版本、variant、长度、格式、非字符串及 None。"""
    assert is_request_id(identifier) is expected


@pytest.mark.parametrize(
    ("identifier", "expected"),
    (
        *((value, "request" if valid else None) for value, valid in REQUEST_ID_CASES),
        ("1", "job"),
        ("9223372036854775807", "job"),
        ("9223372036854775808", None),
        ("01", None),
        ("0", None),
        ("-1", None),
        (" 1", None),
        ("1 ", None),
        ("1\n", None),
        ("1\t", None),
    ),
)
def test_error_source_kind(identifier: str, expected: str | None) -> None:
    """验证契约：合法请求返回 request，规范作业号 1 至整数上限返回 job，其余返回 None。"""
    assert error_source_kind(identifier) == expected


def test_error_id_pattern_unchanged() -> None:
    """验证搬移约束：错误编号模式与改动前的字面值逐字相同，包含锚点和分组。"""
    assert ERROR_ID_PATTERN == r"^([0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}|[1-9][0-9]{0,18})$"
