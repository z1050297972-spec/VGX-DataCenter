"""测试路径静态审计；用标准库AST折叠常量，不执行被审计程序、不访问数据位置。"""

import ast
import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import cast

_COMPONENT = "mnt"
# 路径分量边界兼容代码字符串和Markdown标点，避免把mnt2、mnt_copy当成真实挂载段。
_SEGMENT = re.compile(rf"(?<![A-Za-z0-9_.-]){_COMPONENT}(?![A-Za-z0-9_.-])")

# 白名单键是相对文件、函数范围和完整语句；任何新I/O表达式都会改变完整语句而失去豁免。
# 白名单声明自身只允许ast.literal_eval可读的纯数据，这是防止自描述递归的明确元例外。
_PYTHON_ALLOWLIST: dict[tuple[str, str, str], str] = {
    (
        "nav_manifest.py",
        "_replace_paths",
        "if '/' + 'mnt/' in value:\n    raise ValueError('样本含真实数据挂载前缀')",
    ): "拒绝样本里的真实前缀，仅作字符串检查。",
    (
        "nav_manifest.py",
        "_validate_input_directories",
        "if len(target.parts) < 3 or target.parts[1] in {'mnt', 'home', 'root'}:\n    raise ValueError('输出必须是测试私有临时目录')",
    ): "拒绝真实数据目录的输入保护，只比较路径分量。",
    (
        "nav_manifest.py",
        "_validate_sources",
        "if not origin or origin[0] != 'mnt' or len(origin) < 3:\n    raise ValueError('来源路径分量不完整')",
    ): "核对采集来源分量，只读清单文字，不访问来源。",
    (
        "nav_path_audit.py",
        "<module>",
        "_COMPONENT = 'mnt'",
    ): "审计器自身用于识别禁用路径分量的常量，不用于I/O。",
    (
        "test_fake_nav.py",
        "test_invalid_sample_before_writes",
        "data['notes'] = [{'unknown': '{unknown}/x', 'realpath': '/' + 'mnt/dataset1/x', 'budget': 'x' * (2 * 1024 * 1024), 'json': 'unused'}[fault]]",
    ): "给文件读取边界注入非法路径文本，验证写入前拒绝，不访问注入路径。",
    (
        "test_fake_nav.py",
        "test_mount_path_allowlist_is_exact",
        "assert python_mount_references(assertion + '    Path(\"/mnt\").read_text()\\n', filename='test_storage_config.py')",
    ): "白名单正反例是JSON或源码文本，只有审计函数读取，不执行其中的文件操作。",
    (
        "test_fake_nav.py",
        "test_mount_path_allowlist_is_exact",
        'assertion = \'def test_defaults():\\n    assert DEFAULT_NAV_ROOT.parts == ("/", "mnt", "datasets")\\n\'',
    ): "白名单正反例是JSON或源码文本，只有审计函数读取，不执行其中的文件操作。",
    (
        "test_fake_nav.py",
        "test_mount_path_allowlist_is_exact",
        "for value in ('/mnt', '/fake/mnt/x', 'mnt'):\n    assert fixture_mount_references({'path': value}, filename='manifest.json')",
    ): "白名单正反例是JSON或源码文本，只有审计函数读取，不执行其中的文件操作。",
    (
        "test_fake_nav.py",
        "test_mount_path_allowlist_is_exact",
        "provenance = {'samples': [{'source_path_parts': ['mnt', 'datasets']}]}",
    ): "白名单正反例是JSON或源码文本，只有审计函数读取，不执行其中的文件操作。",
    (
        "test_fake_nav.py",
        "test_mount_path_audit_detects_literal_and_computed_paths",
        'programs = (\'Path("/mnt")\', \'Path("/" + "mnt")\', \'Path("/") / "mnt"\', \'Path("/", "mnt", "data")\', \'os.path.join("/", "mnt")\', \'Path("/" + "mn" + "t")\', \'Path(f"/{\\\'mnt\\\'}")\', \'Path("/data/mnt/a")\')',
    ): "静态审计回归样例是待解析源码文本，从不执行。",
    (
        "test_fake_nav.py",
        "test_placeholder_expansion",
        "assert '/' + 'mnt/' not in content",
    ): "断言临时JSON没有真实路径残留。",
    (
        "test_fake_nav.py",
        "test_provenance",
        "assert item.source_path_parts[0] == 'mnt'",
    ): "核对来源路径分量和采集记录，仅用于追溯。",
    (
        "test_fake_nav.py",
        "test_provenance",
        "assert known.source_path_parts == ('mnt', 'datasets', '按任务', 'EgoProStandard', '原始路径.json')",
    ): "核对来源路径分量和采集记录，仅用于追溯。",
    (
        "test_mountinfo_sample.py",
        "<module>",
        "_FILESYSTEM_ROOT_CASES = [('/', '/'), ('/subdirectory', '/subdirectory'), ('mnt:[4026532978]', 'mnt:[4026532978]'), ('/with\\\\040space', '/with space'), ('-', '-'), ('/.', '/.')]",
    ): "第4列的格式回归输入，nsfs标识是非路径文本，从不用于文件访问。",
    (
        "test_mountinfo_sample.py",
        "test_real_mountinfo_sample_preserves_nsfs_and_online_disks",
        "assert {record.mount_point.name: record.filesystem_root for record in records if record.filesystem == 'nsfs'} == {'docker.mnt': 'mnt:[4026532978]', 'prompting-client.mnt': 'mnt:[4026532980]', 'snapd-desktop-integration.mnt': 'mnt:[4026532981]', 'firmware-updater.mnt': 'mnt:[4026532775]'}",
    ): "独立核对采集的nsfs命名空间标识，只比较文本，不构造真实路径。",
    (
        "test_storage_config.py",
        "test_defaults",
        "assert DEFAULT_NAV_ROOT.parts == ('/', 'mnt', 'datasets')",
    ): "独立断言获批默认导航位置的分量，不读取该位置。",
}


def python_mount_references(
    source: str, *, filename: str = "<sample>"
) -> tuple[tuple[int, str], ...]:
    """返回源码中未获精确白名单允许的路径位置；单独根名、常量拼接和Path组合都检查。"""
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST, scope: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        if isinstance(node, ast.stmt) and _allowed_statement(filename, scope, node):
            return
        value = _constant_path(node)
        if value is not None:
            if _SEGMENT.search(value):
                found.append((getattr(node, "lineno", 0), ast.unparse(node)))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(ast.parse(source), "<module>")
    return tuple(found)


def fixture_mount_references(value: object, *, filename: str) -> tuple[str, ...]:
    """检查JSON全部键值；唯一数据例外是manifest.samples[*].source_path_parts的第零分量。"""
    found: list[str] = []

    def visit(item: object, location: tuple[str | int, ...]) -> None:
        if isinstance(item, str):
            # 采集来源仅用于追溯，NavManifest另行核对其与asset_path一致；其他位置不放行。
            provenance = (
                filename == "manifest.json"
                and len(location) == 4
                and location[0] == "samples"
                and isinstance(location[1], int)
                and location[2:] == ("source_path_parts", 0)
                and item == _COMPONENT
            )
            if _SEGMENT.search(item) and not provenance:
                found.append("/".join(str(part) for part in location))
        elif isinstance(item, dict):
            for key, child in cast(dict[str, object], item).items():
                if _SEGMENT.search(key):
                    found.append("/".join(str(part) for part in (*location, key)))
                visit(child, (*location, key))
        elif isinstance(item, list):
            for index, child in enumerate(cast(list[object], item)):
                visit(child, (*location, index))

    visit(value, ())
    return tuple(found)


def _allowed_statement(filename: str, scope: str, node: ast.stmt) -> bool:
    """只放行有理由的完整语句；白名单声明不能藏可执行调用。"""
    if (
        filename == "nav_path_audit.py"
        and isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_PYTHON_ALLOWLIST"
    ):
        if node.value is None or not isinstance(ast.literal_eval(node.value), dict):
            raise ValueError("审计白名单必须是纯字面量字典")
        return True
    return bool(_PYTHON_ALLOWLIST.get((filename, scope, ast.unparse(node))))


def _constant_path(node: ast.AST) -> str | None:
    """只折叠无副作用的语法，不求值变量、任意调用或被审计的文件操作。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        return (
            node.value.decode("utf-8", errors="surrogateescape")
            if isinstance(node.value, bytes)
            else node.value
        )
    if isinstance(node, ast.FormattedValue):
        return _constant_path(node.value)
    if isinstance(node, ast.JoinedStr):
        return _join_constants(node.values, "")
    if isinstance(node, ast.BinOp):
        left, right = _constant_path(node.left), _constant_path(node.right)
        if left is not None and right is not None:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Div):
                return str(PurePosixPath(left) / right)
    if isinstance(node, ast.Call) and not node.keywords:
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if name in {"Path", "PurePath", "PurePosixPath", "join", "joinpath"}:
            return _join_constants(node.args, "/")
    return None


def _join_constants(nodes: Sequence[ast.AST], separator: str) -> str | None:
    """常量片段全部已知才拼接；未知片段由上层继续逐节点检查。"""
    values = [_constant_path(node) for node in nodes]
    return (
        separator.join(cast(list[str], values))
        if values and all(value is not None for value in values)
        else None
    )
