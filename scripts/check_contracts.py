"""开发检查工具，用 AST 只读检查 Python 函数契约，不属于平台运行时三层。

ruff 的 pydocstyle、pydoclint 只识别标准文档小节，不能检查 Side Effects: 和
Time Semantics:，所以用标准库 ast 补齐完整性、顺序和非空检查；不执行被检查代码，
不核对契约内容是否符合业务，也不重复实现 ruff 的签名核对。
依据：AGENTS 规则 4、CODING_STANDARDS 3.1，M0 工单 01「仓库骨架和检查链」。
"""

import argparse
import ast
import re
import stat
import sys
import tokenize
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Literal

# AGENTS 规则 4 的顺序是检查依据；生成器只替换返回小节。
_FUNCTION_SECTIONS = ("Args:", "Returns:", "Raises:", "Side Effects:", "Time Semantics:")
# 顶格英文标题都作为边界，拼错的标题不能冒充前一节的内容。
_SECTION_HEADING = re.compile(r"(?P<title>[A-Za-z][A-Za-z ]*:)(?P<inline>.*)")
type _Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
# 只认标准装饰器的静态名字，不把其他库碰巧同名的对象当作豁免。
_DECORATOR_KINDS = {
    "property": "property",
    "builtins.property": "property",
    "cached_property": "property",
    "functools.cached_property": "property",
    "dataclass": "dataclass",
    "dataclasses.dataclass": "dataclass",
    "overload": "overload",
    "typing.overload": "overload",
    "typing_extensions.overload": "overload",
}


def _bind_import(node: ast.AST, aliases: dict[str, str]) -> None:
    """记录当前作用域内的显式导入别名，不导入样例模块。"""
    if isinstance(node, ast.Import):
        for item in node.names:
            aliases[item.asname or item.name.split(".")[0]] = (
                item.name if item.asname else item.name.split(".")[0]
            )
    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
        for item in node.names:
            aliases[item.asname or item.name] = f"{node.module}.{item.name}"


def _decorators(node: _Definition, aliases: dict[str, str]) -> set[str]:
    """把已知装饰器的限定名和导入别名归一成检查规则。"""
    result: set[str] = set()
    for item in node.decorator_list:
        name = _decorator_name(item)
        first, separator, rest = name.partition(".")
        canonical = aliases.get(first, first) + separator + rest
        # 属性的访问器延续 property 的一句职责规则，不按普通公开方法要求六项。
        if isinstance(item, ast.Attribute) and item.attr in {"getter", "setter", "deleter"}:
            result.add("property")
        elif canonical in _DECORATOR_KINDS:
            result.add(_DECORATOR_KINDS[canonical])
    return result


def _definitions(
    nodes: Iterable[ast.AST], prefix: tuple[str, ...], aliases: dict[str, str]
) -> Iterator[tuple[_Definition, tuple[str, ...], set[str]]]:
    """遍历模块和类中的定义，函数体是边界，不进入嵌套定义。"""
    for node in nodes:
        _bind_import(node, aliases)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = (*prefix, node.name)
            yield node, names, _decorators(node, aliases)
            if isinstance(node, ast.ClassDef):
                yield from _definitions(node.body, names, aliases.copy())
        else:
            yield from _definitions(ast.iter_child_nodes(node), prefix, aliases)


def _sections(doc: str) -> list[tuple[str, str]]:
    """按顶格英文标题划分小节，保留出现顺序和重复项。"""
    result: list[tuple[str, str]] = []
    heading: str | None = None
    content: list[str] = []
    for line in doc.splitlines():
        # 尾随排版空白不属于标题文字，保留左侧缩进以区分标题和内容。
        line = line.rstrip()
        if match := _SECTION_HEADING.fullmatch(line):
            if heading is not None:
                result.append((heading, "\n".join(content).strip()))
            # 同行内容也划归本节，使诊断能指出排版错误，而不是误报缺项或空项。
            heading, content = match["title"], [match["inline"]]
        elif heading is not None:
            content.append(line)
    if heading is not None:
        result.append((heading, "\n".join(content).strip()))
    return result


def _doc_problems(doc: str | None, sections: Sequence[str]) -> list[str]:
    """列出职责首行和要求小节的文档问题。"""
    if not doc or not doc.strip():
        return ["缺少职责", *(f"缺少 {section}" for section in sections)]
    first_line = doc.splitlines()[0].strip()
    problems = ["缺少职责"] if _SECTION_HEADING.fullmatch(first_line) else []
    entries = _sections(doc)
    headings = [heading for heading, _ in entries]
    problems.extend(f"缺少 {section}" for section in sections if section not in headings)
    problems.extend(f"重复 {section}" for section in sections if headings.count(section) > 1)
    problems.extend(
        f"{heading} 为空" for heading, content in entries if heading in sections and not content
    )
    problems.extend(_inline_section_problems(doc, sections))
    order = [sections.index(heading) for heading in headings if heading in sections]
    if order != sorted(order):
        problems.append("小节顺序不对")
    return problems


def _inline_section_problems(doc: str, sections: Sequence[str]) -> list[str]:
    """为已识别标题的同行内容给出换行提示，不把排版问题误报成缺项。"""
    problems: list[str] = []
    for line in doc.splitlines():
        match = _SECTION_HEADING.fullmatch(line)
        if match and match["title"] in sections and match["inline"].strip():
            problems.append(f"{match['title']} 标题后要换行再写内容")
    return problems


def _module_parts(path: Path) -> tuple[str, ...]:
    """沿连续的传统包目录确定模块路径，目录名不自动等同于包名。"""
    # __init__.py 是所属包自身，不作为私有模块名拼进路径。
    parts = [] if path.stem == "__init__" else [path.stem]
    parent = path.absolute().parent
    while (parent / "__init__.py").is_file():
        parts.insert(0, parent.name)
        if parent == parent.parent:
            break
        parent = parent.parent
    return tuple(parts)


def _decorator_name(node: ast.expr) -> str:
    """提取静态装饰器名称，不求值调用表达式。"""
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


def _has_yield(nodes: Iterable[ast.AST]) -> bool:
    """只判断当前函数是否生成值，嵌套函数、类和 lambda 不影响外层。"""
    for node in nodes:
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if _has_yield(ast.iter_child_nodes(node)):
            return True
    return False


def check_file(path: Path) -> list[str]:
    """只读检查一个 Python 文件，返回其中的契约文档问题。

    Args:
        path: 存在的普通 .py 文件路径；相对路径按当前工作目录解释，无单位。
            模块名由文件名及连续含 __init__.py 的父包目录确定，临时目录名不算包名。

    Returns:
        按源码行号排序的问题行列表；无问题时为空。每个有问题的定义只输出一行，
        格式为「文件:行号  函数全名  问题」，文件使用传入路径的字符串形式，
        行号从 1 开始指向 def、async def 或 class；全名含模块、包及嵌套类名。
        同一定义的缺项、空项、重复小节及顺序错误合并在该行，不包含末尾总数。
        公开函数及公开类的公开方法按职责首行、Args:、Returns:、Raises:、
        Side Effects:、Time Semantics: 检查，标题精确匹配且内容非空；写「无」合格。
        生成器以 Yields: 替代 Returns:，仅按函数自身的 yield 或 yield from 判断。
        函数、所属类或模块路径任一部分以 _ 开头即为私有，只需非空职责；
        __init__.py 不算私有路径，__init__ 按所属类的可见性检查。
        property 只需非空职责；数据类需非空 Attributes:（包括空数据类写「无」）。
        识别 property、dataclass、overload 的直接名字、限定名及导入别名。
        overload 签名、函数体内的嵌套定义及 test_ 开头的测试函数不查；
        overload 的实际实现照常检查。不通过导入或执行代码推断动态装饰器。

    Raises:
        ValueError: path 不是 .py 文件，或存在但不是普通文件。
        OSError: 文件不存在、无权读取，或读取源码、识别父包时发生文件系统错误。
        SyntaxError: 源码无法按当前 Python 语法解析，或声明的源文件编码无效。
        UnicodeError: 源文件无法按声明的编码解码；没有声明时使用 UTF-8。

    Side Effects:
        无（只读指定源码及父包的 __init__.py 是否存在，不导入或执行源码）。

    Time Semantics:
        同步检查读取时的文件内容，不保证并发编辑下的目录快照一致性；无等待或重试。
    """
    if path.suffix != ".py":
        raise ValueError(f"{path}: 不是 .py 文件")
    # 先 stat 再读取，FIFO 等特殊文件不能被当作源码打开而无限阻塞。
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"{path}: 不是普通文件")
    # tokenize.open 按 Python 的编码声明读取，避免自行解析编码规则。
    with tokenize.open(path) as source:
        tree = ast.parse(source.read(), filename=str(path))
    module_parts = _module_parts(path)
    problems: list[str] = []
    for node, names, decorators in _definitions(tree.body, module_parts, {}):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "overload" in decorators or node.name.startswith("test_"):
                continue
            # 构造器沿用类的可见性，模块级同名函数仍按私有函数处理。
            visibility_names = (
                names[:-1]
                if node.name == "__init__" and len(names) > len(module_parts) + 1
                else names
            )
            private = any(part.startswith("_") for part in visibility_names)
            sections = () if private or "property" in decorators else _FUNCTION_SECTIONS
            if sections and _has_yield(node.body):
                sections = tuple(
                    "Yields:" if section == "Returns:" else section for section in sections
                )
            issues = _doc_problems(ast.get_docstring(node), sections)
        else:
            issues = (
                _doc_problems(ast.get_docstring(node), ("Attributes:",))
                if "dataclass" in decorators
                else []
            )
        if issues:
            fullname = ".".join(names)
            problems.append(f"{path}:{node.lineno}  {fullname}  {'；'.join(issues)}")
    return problems


def _source_files(path: Path) -> Iterator[Path]:
    """递归枚举目录中的 Python 文件，显式文件由文件检查入口验证。"""
    if path.is_symlink():
        raise ValueError(f"{path}: 不接受显式软链接路径")
    if path.is_dir():
        for child in path.iterdir():
            # 在任何目录或文件判定之前排除软链接，断链也不能访问其目标。
            if child.is_symlink():
                continue
            if child.is_dir() or child.suffix == ".py":
                yield from _source_files(child)
    else:
        yield path


def _unique_files(arguments: Sequence[str]) -> list[Path]:
    """按绝对路径去重，再按报告中的文件路径排序，重复参数不重复计数。"""
    files: dict[Path, Path] = {}
    for name in arguments:
        for path in _source_files(Path(name)):
            files.setdefault(path.resolve(), path)
    return sorted(files.values(), key=str)


class _Arguments(argparse.Namespace):
    """保存 argparse 解析结果的静态类型，避免把动态属性传播到检查逻辑。"""

    def __init__(self) -> None:
        """设置无路径及未请求帮助的初始状态。"""
        super().__init__()
        self.paths: list[str] = []
        self.help: bool = False


def _parse_arguments(argv: Sequence[str] | None) -> tuple[list[str], str | None]:
    """用标准库解析参数，把帮助作为文本返回，不在解析阶段写输出流。"""
    parser = argparse.ArgumentParser(
        description="只读检查 Python 函数契约",
        add_help=False,
        exit_on_error=False,
        allow_abbrev=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="显示帮助")
    parser.add_argument("paths", nargs="*", help="Python 文件或目录，默认 src/rdp 和 scripts")
    options = _Arguments()
    _, unknown = parser.parse_known_args(argv, namespace=options)
    if unknown:
        raise ValueError(f"未知选项: {' '.join(unknown)}")
    return options.paths or ["src/rdp", "scripts"], parser.format_help() if options.help else None


def _collect_problems(arguments: Sequence[str]) -> list[str]:
    """先收齐所有结果，任一源码失败时补充路径并丢弃尚未输出的报告。"""
    problems: list[str] = []
    for path in _unique_files(arguments):
        try:
            problems.extend(check_file(path))
        except (OSError, SyntaxError, ValueError) as error:
            message = str(error)
            # 文件校验产生的 ValueError 已含路径，只给缺少上下文的底层错误补路径。
            if not message.startswith(f"{path}:"):
                message = f"{path}: {message}"
            raise ValueError(message) from error
    return problems


def main(argv: Sequence[str] | None = None) -> Literal[0, 1, 2]:
    """检查命令行指定的源码路径，输出问题及总数并返回退出码。

    Args:
        argv: 不含程序名的命令行参数序列，无单位；None 表示读取 sys.argv[1:]。
            接受零个或多个 .py 文件或目录路径，相对路径按当前工作目录解释；
            无路径时检查 src/rdp 和 scripts。目录递归收集 .py 文件，忽略其他扩展名，
            不跟随目录内软链接；显式软链接路径也拒绝，避免越过指定的源码边界。
            重叠路径按绝对路径去重；支持 -h/--help，未知选项属于参数错误。

    Returns:
        0：没有问题（空目录也算）或请求帮助；1：存在契约问题；
        2：参数或路径无效、源码无法读取、解码或解析。
        正常检查按文件路径字典序、文件内行号输出 check_file 的问题行到 stdout，
        最后一行固定为「问题总数: N」，N 是有问题的定义数，最小为 0。
        任一文件检查失败时只向 stderr 输出含路径及原因的错误，不输出部分报告或总数；
        帮助输出到 stdout，不输出问题总数。空参数序列与未指定路径的行为一致。

    Raises:
        OSError: stdout 或 stderr 写入失败；不把无法交付检查结果伪装成成功。

    Side Effects:
        只读检查路径及源码，写 stdout/stderr；不修改源码或创建缓存，不执行被检查代码。

    Time Semantics:
        同步检查当前文件内容，先完成全部检查再输出报告；无轮询或重试。
    """
    try:
        arguments, help_text = _parse_arguments(argv)
        problems = [] if help_text else _collect_problems(arguments)
    except (OSError, SyntaxError, ValueError, argparse.ArgumentError) as error:
        sys.stderr.write(f"检查失败: {error}\n")
        return 2
    if help_text:
        sys.stdout.write(help_text)
        return 0
    sys.stdout.write("\n".join([*problems, f"问题总数: {len(problems)}"]) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
