"""契约检查器的公开边界测试，在临时目录生成源码，以子进程验证诊断及退出码。"""

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent, indent

# 工单要求以当前测试解释器运行脚本，避免落到 PATH 上的另一个 Python。
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_contracts.py"
# 子进程只读取临时样例，10 秒用于发现卡住或意外执行源码的回归。
_TIMEOUT_S = 10
_VALID_DOC = """完成一次操作。

Args:
    无

Returns:
    无

Raises:
    无

Side Effects:
    无

Time Semantics:
    无"""


def _function(name: str = "sample", doc: str = _VALID_DOC, body: str = "return None") -> str:
    """生成受控的样例定义，文档内容来自契约而不是被测解析器。"""
    return f'def {name}():\n    """{doc}"""\n{indent(body, "    ")}\n'


def _write(root: Path, name: str, source: str) -> Path:
    """在临时目录写样例源码，允许创建包目录以验证可见性。"""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _run(root: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    """通过真实命令行边界检查临时样例，并保留退出码和两路输出。"""
    # 解释器、脚本和参数都由测试构造，不经过 shell。
    return subprocess.run(  # noqa: S603  # 理由：只运行固定解释器和受控测试参数。
        [sys.executable, "-B", str(_SCRIPT), *paths],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )


def _run_api(root: Path, code: str) -> subprocess.CompletedProcess[str]:
    """在隔离子进程调用公开 API，观察直接异常和进程参数语义。"""
    prelude = (
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(_SCRIPT.parent)!r})\n"
        "from check_contracts import check_file, main\n"
    )
    # -B 保证导入检查脚本也不会在工作目录留下字节码缓存。
    return subprocess.run(  # noqa: S603  # 理由：只运行固定解释器及本文件定义的测试代码。
        [sys.executable, "-B", "-c", prelude + dedent(code)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )


def test_complete_contract(tmp_path: Path) -> None:
    """验证契约：六项齐全且非空的公开函数退出 0，末行是问题总数: 0。"""
    _write(tmp_path, "sample.py", _function())
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "问题总数: 0\n"
    assert result.stderr == ""


def test_not_applicable_sections(tmp_path: Path) -> None:
    """验证契约：Args、Returns、Raises 等不适用项写无时通过，中文标点不受影响。"""
    _write(
        tmp_path,
        "sample.py",
        _function(
            doc=_VALID_DOC.replace("完成一次操作。", "职责：（无单位），无需时钟；不写文件。")
        ),
    )
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 0
    assert result.stdout == "问题总数: 0\n"
    assert result.stderr == ""


def test_stub_contract(tmp_path: Path) -> None:
    """验证契约：骨架只抛 NotImplementedError，Raises 不写该异常也通过。"""
    _write(tmp_path, "sample.py", _function(body="raise NotImplementedError"))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 0
    assert result.stdout == "问题总数: 0\n"


def test_missing_docstring(tmp_path: Path) -> None:
    """验证契约：公开函数没有 docstring 时退出 1，并报告职责和所有缺失小节。"""
    _write(tmp_path, "sample.py", "def sample():\n    return None\n")
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.startswith("sample.py:1  sample.sample  ")
    for title in ("职责", "Args:", "Returns:", "Raises:", "Side Effects:", "Time Semantics:"):
        assert title in result.stdout
    assert result.stdout.endswith("问题总数: 1\n")


def test_missing_summary(tmp_path: Path) -> None:
    """验证契约：docstring 直接从 Args 开始时报告缺少职责首行。"""
    _write(tmp_path, "sample.py", _function(doc=_VALID_DOC.removeprefix("完成一次操作。\n\n")))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "缺少职责" in result.stdout
    assert "缺少 Args:" not in result.stdout


def test_missing_each_section(tmp_path: Path) -> None:
    """验证契约：分别删除五个小节各失败一次，诊断精确指出被删除的标题。"""
    for title in ("Args:", "Returns:", "Raises:", "Side Effects:", "Time Semantics:"):
        doc = _VALID_DOC.replace(title + "\n    无", "")
        _write(tmp_path, "sample.py", _function(doc=doc))
        result = _run(tmp_path, "sample.py")
        assert result.returncode == 1
        assert f"缺少 {title}" in result.stdout
        assert result.stdout.endswith("问题总数: 1\n")


def test_empty_each_section(tmp_path: Path) -> None:
    """验证契约：分别将五个小节置空或仅留空白，各报告对应小节为空。"""
    for title in ("Args:", "Returns:", "Raises:", "Side Effects:", "Time Semantics:"):
        for content in ("", "    "):
            doc = _VALID_DOC.replace(title + "\n    无", title + "\n" + content)
            _write(tmp_path, "sample.py", _function(doc=doc))
            result = _run(tmp_path, "sample.py")
            assert result.returncode == 1
            assert f"{title} 为空" in result.stdout


def test_section_order(tmp_path: Path) -> None:
    """验证契约：调换 Returns 和 Raises 的顺序时退出 1 并报告顺序错误。"""
    doc = (
        _VALID_DOC.replace("Returns:", "TEMP:")
        .replace("Raises:", "Returns:")
        .replace("TEMP:", "Raises:")
    )
    _write(tmp_path, "sample.py", _function(doc=doc))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "顺序不对" in result.stdout


def test_exact_headings(tmp_path: Path) -> None:
    """验证契约：Side effects: 等大小写不同的标题不替代 Side Effects:。"""
    for wrong in ("Side effects:", "side Effects:", "SIDE EFFECTS:"):
        _write(tmp_path, "sample.py", _function(doc=_VALID_DOC.replace("Side Effects:", wrong)))
        result = _run(tmp_path, "sample.py")
        assert result.returncode == 1
        assert "缺少 Side Effects:" in result.stdout


def test_section_heading_trailing_whitespace(tmp_path: Path) -> None:
    """验证评审修复：标题尾随空格或制表符不造成缺项，也不吞掉下一节。"""
    for title in ("Args:", "Returns:", "Raises:", "Side Effects:", "Time Semantics:"):
        for suffix in (" ", "\t"):
            _write(tmp_path, "sample.py", _function(doc=_VALID_DOC.replace(title, title + suffix)))
            result = _run(tmp_path, "sample.py")
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout == "问题总数: 0\n"


def test_inline_section_content_reports_layout_error(tmp_path: Path) -> None:
    """验证评审修复：小节同行内容报换行问题，不能误报标题缺失或内容为空。"""
    for title in ("Args:", "Returns:", "Raises:", "Side Effects:", "Time Semantics:"):
        for separator in (" ", "\t"):
            doc = _VALID_DOC.replace(title + "\n    无", title + separator + "无")
            _write(tmp_path, "sample.py", _function(doc=doc))
            result = _run(tmp_path, "sample.py")
            assert result.returncode == 1
            assert result.stdout == (
                f"sample.py:1  sample.sample  {title} 标题后要换行再写内容\n问题总数: 1\n"
            )
            assert result.stderr == ""


def test_duplicate_section(tmp_path: Path) -> None:
    """验证契约：重复 Args 小节时报告重复，同一定义仍只计一个问题。"""
    _write(tmp_path, "sample.py", _function(doc=_VALID_DOC + "\n\nArgs:\n    无"))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "重复 Args:" in result.stdout
    assert result.stdout.count("sample.sample") == 1
    assert result.stdout.endswith("问题总数: 1\n")


def test_private_function(tmp_path: Path) -> None:
    """验证契约：私有函数只有一句非空职责即通过，缺失或空白 docstring 时失败。"""
    for doc, expected in (("只做一件事。", 0), ("", 1), ("   ", 1)):
        _write(tmp_path, "sample.py", _function("_hidden", doc))
        result = _run(tmp_path, "sample.py")
        assert result.returncode == expected
        if expected:
            assert "缺少职责" in result.stdout
            assert "缺少 Args:" not in result.stdout


def test_private_module(tmp_path: Path) -> None:
    """验证契约：_private.py 中的公开名字函数按私有函数检查。"""
    _write(tmp_path, "_private.py", _function(doc="只做一件事。"))
    assert _run(tmp_path, "_private.py").returncode == 0
    _write(tmp_path, "_private.py", _function(doc=""))
    result = _run(tmp_path, "_private.py")
    assert result.returncode == 1
    assert "_private.sample" in result.stdout
    assert "缺少 Args:" not in result.stdout


def test_private_package(tmp_path: Path) -> None:
    """验证契约：_private 包下的函数按私有检查，包外临时目录的下划线不影响可见性。"""
    _write(tmp_path, "_private/__init__.py", "")
    _write(tmp_path, "_private/sample.py", _function(doc="职责。"))
    assert _run(tmp_path, "_private/sample.py").returncode == 0
    _write(tmp_path, "_temporary/sample.py", _function(doc="职责。"))
    result = _run(tmp_path, "_temporary/sample.py")
    assert result.returncode == 1
    assert "缺少 Args:" in result.stdout
    assert "_temporary.sample" not in result.stdout


def test_package_init(tmp_path: Path) -> None:
    """验证契约：公开包的 __init__.py 不算私有模块，其中公开函数必须有六项。"""
    _write(tmp_path, "public/__init__.py", _function(doc="职责。"))
    result = _run(tmp_path, "public/__init__.py")
    assert result.returncode == 1
    assert "缺少 Time Semantics:" in result.stdout
    _write(tmp_path, "public/__init__.py", _function())
    assert _run(tmp_path, "public/__init__.py").returncode == 0


def test_public_methods(tmp_path: Path) -> None:
    """验证契约：公开类的公开方法必须有六项，缺 Time Semantics 时失败。"""
    doc = _VALID_DOC.replace("Time Semantics:\n    无", "")
    _write(tmp_path, "sample.py", "class Public:\n" + indent(_function("method", doc), "    "))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "sample.py:2  sample.Public.method  缺少 Time Semantics:" in result.stdout


def test_private_classes(tmp_path: Path) -> None:
    """验证契约：私有类及嵌套在私有类中的类，其方法只需非空职责。"""
    source = "class _Private:\n    class Public:\n" + indent(
        _function("method", "职责。"), "        "
    )
    _write(tmp_path, "sample.py", source)
    assert _run(tmp_path, "sample.py").returncode == 0
    _write(tmp_path, "sample.py", source.replace("职责。", ""))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "缺少职责" in result.stdout
    assert "缺少 Args:" not in result.stdout


def test_initializers(tmp_path: Path) -> None:
    """验证契约：公开类 __init__ 必须有六项，私有类 __init__ 只需职责。"""
    for name, expected in (("Public", 1), ("_Private", 0)):
        source = f"class {name}:\n" + indent(_function("__init__", "创建对象。"), "    ")
        _write(tmp_path, "sample.py", source)
        result = _run(tmp_path, "sample.py")
        assert result.returncode == expected
        if expected:
            assert "sample.Public.__init__" in result.stdout
            assert "缺少 Args:" in result.stdout


def test_property_summary(tmp_path: Path) -> None:
    """验证契约：property 只有一句职责即通过，缺失职责时失败。"""
    for doc, expected in (("数值，单位为米。", 0), ("", 1)):
        source = "class Public:\n    @property\n" + indent(_function("value", doc), "    ")
        _write(tmp_path, "sample.py", source)
        result = _run(tmp_path, "sample.py")
        assert result.returncode == expected
        if expected:
            assert "缺少职责" in result.stdout
            assert "缺少 Args:" not in result.stdout


def test_property_accessors_require_only_summary(tmp_path: Path) -> None:
    """验证评审修复：property 的 getter、setter、deleter 只需非空职责。"""
    for accessor in ("getter", "setter", "deleter"):
        for doc, expected in (("设置或读取属性。", 0), ("", 1)):
            source = "class Public:\n    @property\n" + indent(
                _function("value", "属性值。"), "    "
            )
            method = _function("value", doc)
            if accessor == "setter":
                method = method.replace("def value():", "def value(self, x: int) -> None:")
            source += f"    @value.{accessor}\n" + indent(method, "    ")
            _write(tmp_path, "sample.py", source)
            result = _run(tmp_path, "sample.py")
            assert result.returncode == expected, result.stdout + result.stderr
            if expected:
                assert "缺少职责" in result.stdout
                assert "缺少 Args:" not in result.stdout
                assert result.stdout.endswith("问题总数: 1\n")


def test_cached_property_forms_require_only_summary(tmp_path: Path) -> None:
    """验证评审修复：cached_property 的直接名、限定名及两种导入别名只需职责。"""
    forms = (
        ("from functools import cached_property", "cached_property"),
        ("import functools", "functools.cached_property"),
        ("from functools import cached_property as cached", "cached"),
        ("import functools as ft", "ft.cached_property"),
    )
    for imports, decorator in forms:
        for doc, expected in (("缓存计算结果。", 0), ("", 1)):
            source = f"{imports}\nclass Public:\n    @{decorator}\n" + indent(
                _function("value", doc), "    "
            )
            _write(tmp_path, "sample.py", source)
            result = _run(tmp_path, "sample.py")
            assert result.returncode == expected, result.stdout + result.stderr
            if expected:
                assert "缺少职责" in result.stdout
                assert "缺少 Args:" not in result.stdout


def test_dataclass_attributes(tmp_path: Path) -> None:
    """验证契约：数据类必须有非空 Attributes，缺失或空白失败，空类写无通过。"""
    for doc, expected in (
        ("数据。", 1),
        ("数据。\n\nAttributes:\n    ", 1),
        ("数据。\n\nAttributes:\n    无", 0),
    ):
        source = f'from dataclasses import dataclass\n@dataclass\nclass Record:\n    """{doc}"""\n'
        _write(tmp_path, "sample.py", source)
        result = _run(tmp_path, "sample.py")
        assert result.returncode == expected
        if expected:
            assert "sample.py:3  sample.Record" in result.stdout
            assert "Attributes:" in result.stdout


def test_decorator_forms(tmp_path: Path) -> None:
    """验证契约：property、dataclass、overload 的直接名、限定名和导入别名同样识别。"""
    forms = (
        (
            "from builtins import property\nfrom dataclasses import dataclass\nfrom typing import overload\n",
            "property",
            "dataclass",
            "overload",
        ),
        (
            "import builtins\nimport dataclasses\nimport typing\n",
            "builtins.property",
            "dataclasses.dataclass",
            "typing.overload",
        ),
        (
            "import builtins as b\nimport dataclasses as d\nimport typing as t\n",
            "b.property",
            "d.dataclass",
            "t.overload",
        ),
        (
            "from builtins import property as p\nfrom dataclasses import dataclass as d\nfrom typing import overload as o\n",
            "p",
            "d",
            "o",
        ),
    )
    for imports, prop, data, overload in forms:
        source = imports + f"@{data}(frozen=True)\nclass Record:\n    pass\n"
        source += f"class Public:\n    @{prop}\n" + indent(_function("value", "职责。"), "    ")
        source += f"@{overload}\ndef example(value: int): ...\n" + _function("example")
        _write(tmp_path, "sample.py", source)
        result = _run(tmp_path, "sample.py")
        assert result.returncode == 1
        assert result.stdout.count("sample.Record") == 1
        assert "Attributes:" in result.stdout
        assert "sample.Public.value" not in result.stdout
        assert "sample.example" not in result.stdout
        assert result.stdout.endswith("问题总数: 1\n")


def test_generator_yields(tmp_path: Path) -> None:
    """验证契约：yield 和 yield from 生成器以 Yields 替代 Returns，误写 Returns 失败。"""
    for body in ("yield 1", "yield from (1, 2)"):
        _write(
            tmp_path,
            "sample.py",
            _function(doc=_VALID_DOC.replace("Returns:", "Yields:"), body=body),
        )
        assert _run(tmp_path, "sample.py").returncode == 0
        _write(tmp_path, "sample.py", _function(body=body))
        result = _run(tmp_path, "sample.py")
        assert result.returncode == 1
        assert "缺少 Yields:" in result.stdout


def test_nested_yield(tmp_path: Path) -> None:
    """验证契约：内层函数的 yield 不把外层普通函数误判为生成器。"""
    body = "def nested():\n    yield 1\nreturn nested"
    _write(tmp_path, "sample.py", _function(body=body))
    assert _run(tmp_path, "sample.py").returncode == 0
    _write(
        tmp_path, "sample.py", _function(doc=_VALID_DOC.replace("Returns:", "Yields:"), body=body)
    )
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "缺少 Returns:" in result.stdout


def test_async_functions(tmp_path: Path) -> None:
    """验证契约：async 函数和 async 生成器分别执行六项和 Yields 规则。"""
    for body, title in (("return None", "Returns:"), ("yield 1", "Yields:")):
        source = "async " + _function(doc=_VALID_DOC.replace("Returns:", title), body=body)
        _write(tmp_path, "sample.py", source)
        assert _run(tmp_path, "sample.py").returncode == 0
        _write(tmp_path, "sample.py", source.replace("Time Semantics:\n    无", ""))
        result = _run(tmp_path, "sample.py")
        assert result.returncode == 1
        assert "缺少 Time Semantics:" in result.stdout


def test_overload_skipped(tmp_path: Path) -> None:
    """验证契约：overload 签名没有 docstring 不报错，实际实现缺小节仍失败。"""
    source = "from typing import overload\n@overload\ndef sample(value: int): ...\n" + _function()
    _write(tmp_path, "sample.py", source)
    assert _run(tmp_path, "sample.py").returncode == 0
    _write(tmp_path, "sample.py", source.replace("Time Semantics:\n    无", ""))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert result.stdout.count("sample.sample") == 1
    assert "缺少 Time Semantics:" in result.stdout


def test_nested_definitions_skipped(tmp_path: Path) -> None:
    """验证契约：函数内嵌套定义没有文档不报错，外层函数照常检查。"""
    body = "def nested():\n    pass\nclass Inner:\n    def method(self):\n        pass\nreturn None"
    _write(tmp_path, "sample.py", _function(body=body))
    assert _run(tmp_path, "sample.py").returncode == 0
    _write(tmp_path, "sample.py", _function(doc="职责。", body=body))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert result.stdout.count("sample.sample") == 1
    assert "nested" not in result.stdout
    assert "Inner" not in result.stdout


def test_test_functions_skipped(tmp_path: Path) -> None:
    """验证契约：test_ 开头的测试函数不要求六项文档，普通函数仍检查。"""
    _write(tmp_path, "sample.py", "def test_example():\n    pass\n" + _function())
    assert _run(tmp_path, "sample.py").returncode == 0
    _write(tmp_path, "sample.py", "def test_example():\n    pass\ndef normal():\n    pass\n")
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "sample.normal" in result.stdout
    assert "sample.test_example" not in result.stdout


def test_diagnostic_location(tmp_path: Path) -> None:
    """验证契约：问题行含文件、从 1 开始的定义行号、带包和嵌套类的全名及具体问题。"""
    _write(tmp_path, "public/__init__.py", "")
    source = "class Outer:\n    class Inner:\n        def method(self):\n            pass\n"
    _write(tmp_path, "public/sample.py", source)
    result = _run(tmp_path, "public/sample.py")
    assert result.returncode == 1
    assert result.stdout.startswith(
        "public/sample.py:3  public.sample.Outer.Inner.method  缺少职责"
    )
    assert result.stdout.endswith("问题总数: 1\n")


def test_multiple_issues_one_definition(tmp_path: Path) -> None:
    """验证契约：一个定义同时缺项、空项或乱序只输出一行，总数只增加 1。"""
    doc = "职责。\n\nRaises:\n    无\n\nArgs:\n\nReturns:\n    无"
    _write(tmp_path, "sample.py", _function(doc=doc))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 1
    assert "缺少 Time Semantics:" in result.stdout
    assert "Args: 为空" in result.stdout
    assert "小节顺序不对" in result.stdout
    assert len(result.stdout.splitlines()) == 2
    assert result.stdout.endswith("问题总数: 1\n")


def test_report_order(tmp_path: Path) -> None:
    """验证契约：多个文件按路径排序，同文件按源码行号排序，最后汇总有问题的定义数。"""
    _write(tmp_path, "z.py", "def zeta(): pass\ndef alpha(): pass\n")
    _write(tmp_path, "a.py", "def first(): pass\n")
    result = _run(tmp_path, "z.py", "a.py")
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines[0].startswith("a.py:1  a.first  ")
    assert lines[1].startswith("z.py:1  z.zeta  ")
    assert lines[2].startswith("z.py:2  z.alpha  ")
    assert lines[3] == "问题总数: 3"


def test_empty_file_and_directory(tmp_path: Path) -> None:
    """验证契约：空源码返回空问题列表，空目录检查退出 0 并输出总数 0。"""
    _write(tmp_path, "empty.py", "")
    (tmp_path / "empty").mkdir()
    for name in ("empty.py", "empty"):
        result = _run(tmp_path, name)
        assert result.returncode == 0
        assert result.stdout == "问题总数: 0\n"
    result = _run_api(tmp_path, "assert check_file(Path('empty.py')) == []\n")
    assert result.returncode == 0, result.stderr


def test_read_only_no_execution(tmp_path: Path) -> None:
    """验证契约：源码含顶层写文件或抛异常语句时只解析不执行，源码和目录内容保持不变。"""
    source = "from pathlib import Path\nPath('marker').write_text('不应执行')\nraise RuntimeError('不应执行')\n"
    path = _write(tmp_path, "sample.py", source)
    before = set(tmp_path.rglob("*"))
    result = _run(tmp_path, "sample.py")
    assert result.returncode == 0
    assert result.stdout == "问题总数: 0\n"
    assert set(tmp_path.rglob("*")) == before
    assert path.read_text(encoding="utf-8") == source


def test_default_paths(tmp_path: Path) -> None:
    """验证契约：无参数时只检查当前目录的 src/rdp 和 scripts，其他目录不扫描。"""
    _write(tmp_path, "src/rdp/sample.py", _function())
    _write(tmp_path, "scripts/utility.py", _function("utility"))
    _write(tmp_path, "outside/bad.py", "def broken(:")
    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout == "问题总数: 0\n"
    _write(tmp_path, "scripts/utility.py", "def missing(): pass\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "scripts/utility.py:1" in result.stdout


def test_explicit_paths(tmp_path: Path) -> None:
    """验证契约：显式相对或绝对文件及目录路径均接受，目录递归扫描且忽略非 .py 文件。"""
    _write(tmp_path, "sources/one.py", _function())
    _write(tmp_path, "sources/nested/two.py", _function("second"))
    _write(tmp_path, "sources/ignored.txt", "def invalid(:")
    for paths in (("sources/one.py",), (str(tmp_path / "sources/one.py"),), ("sources",)):
        result = _run(tmp_path, *paths)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "问题总数: 0\n"
    _write(tmp_path, "sources/nested/two.py", "def second(): pass\n")
    result = _run(tmp_path, "sources")
    assert result.returncode == 1
    assert "sources/nested/two.py:1" in result.stdout


def test_overlapping_paths(tmp_path: Path) -> None:
    """验证契约：重复及重叠路径对应的同一绝对文件只报告一次。"""
    path = _write(tmp_path, "sources/sample.py", "def sample(): pass\n")
    result = _run(
        tmp_path, "sources", "sources/sample.py", str(path), "sources/../sources/sample.py"
    )
    assert result.returncode == 1
    assert result.stdout.count("sample.sample") == 1
    assert result.stdout.endswith("问题总数: 1\n")


def test_symlink_boundary(tmp_path: Path) -> None:
    """验证契约：目录内软链接不跟随，显式软链接路径退出 2，不读取链接目标。"""
    outside = _write(tmp_path, "outside/bad.py", "def broken(:")
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/file.py").symlink_to(outside)
    (tmp_path / "sources/directory").symlink_to(outside.parent, target_is_directory=True)
    (tmp_path / "sources/broken.py").symlink_to(tmp_path / "absent.py")
    result = _run(tmp_path, "sources")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "问题总数: 0\n"
    for name in ("sources/file.py", "sources/directory", "sources/broken.py"):
        result = _run(tmp_path, name)
        assert result.returncode == 2
        assert name in result.stderr
        assert "软链接" in result.stderr
        assert result.stdout == ""


def test_help(tmp_path: Path) -> None:
    """验证契约：-h 和 --help 输出帮助到 stdout 并退出 0，没有问题总数。"""
    for option in ("-h", "--help"):
        result = _run(tmp_path, option)
        assert result.returncode == 0
        assert "--help" in result.stdout
        assert "问题总数" not in result.stdout
        assert result.stderr == ""


def test_invalid_option(tmp_path: Path) -> None:
    """验证契约：未知选项退出 2，错误写 stderr，不输出部分报告或总数。"""
    _write(tmp_path, "first.py", "def missing(): pass\n")
    result = _run(tmp_path, "first.py", "--unknown")
    assert result.returncode == 2
    assert "--unknown" in result.stderr
    assert "未知选项" in result.stderr
    assert result.stdout == ""


def test_missing_path(tmp_path: Path) -> None:
    """验证契约：不存在的文件或目录退出 2，stderr 含路径和原因。"""
    for path in ("missing.py", "missing_directory"):
        result = _run(tmp_path, path)
        assert result.returncode == 2
        assert path in result.stderr
        assert result.stdout == ""
        assert "Traceback" not in result.stderr


def test_invalid_file_kind(tmp_path: Path) -> None:
    """验证契约：显式非 .py 文件或非普通文件路径退出 2，不作为源码解析。"""
    _write(tmp_path, "sample.txt", _function())
    result = _run(tmp_path, "sample.txt")
    assert result.returncode == 2
    assert result.stderr == "检查失败: sample.txt: 不是 .py 文件\n"
    assert result.stdout == ""
    # FIFO 是存在但不能当作普通源码读取的输入；超时会暴露误读造成的阻塞。
    os.mkfifo(tmp_path / "pipe.py")
    result = _run(tmp_path, "pipe.py")
    assert result.returncode == 2
    assert result.stderr == "检查失败: pipe.py: 不是普通文件\n"
    assert result.stdout == ""


def test_syntax_error(tmp_path: Path) -> None:
    """验证契约：源码语法错误退出 2，stderr 含路径和原因，stdout 无部分报告。"""
    _write(tmp_path, "bad.py", "def broken(:\n")
    _write(tmp_path, "first.py", "def undocumented(): pass\n")
    result = _run(tmp_path, "first.py", "bad.py")
    assert result.returncode == 2
    assert "bad.py" in result.stderr
    assert "syntax" in result.stderr.lower()
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


def test_source_encoding(tmp_path: Path) -> None:
    """验证契约：UTF-8 及合法编码声明可读取，无效声明或无法解码的源码退出 2。"""
    path = tmp_path / "sample.py"
    for source in (
        _function().encode("utf-8"),
        ("# coding: latin-1\n" + _function(doc=_VALID_DOC.replace("完成一次操作。", "café.")))
        .replace("无", "none")
        .encode("latin-1"),
    ):
        path.write_bytes(source)
        assert _run(tmp_path, "sample.py").returncode == 0
    for source in (b"# coding: unknown-codec\n", b"# coding: utf-8\n# \xff\n", b"# \xff\n"):
        path.write_bytes(source)
        result = _run(tmp_path, "sample.py")
        assert result.returncode == 2
        assert "sample.py" in result.stderr
        assert result.stdout == ""
        assert "Traceback" not in result.stderr


def test_read_failure(tmp_path: Path) -> None:
    """验证契约：文件读取或父包识别的 OSError 穿过 check_file，命令入口转为退出 2。"""
    _write(tmp_path, "sample.py", _function())
    scenarios = (
        "patch('tokenize.open', side_effect=PermissionError('读取被拒绝'))",
        "patch('pathlib.Path.stat', new=fail_parent)",
    )
    for scenario in scenarios:
        code = f"""
    from unittest.mock import patch
    original_stat = Path.stat
    def fail_parent(path, *args, **kwargs):
        if path.name == '__init__.py':
            raise PermissionError('父包读取被拒绝')
        return original_stat(path, *args, **kwargs)
    with {scenario}:
        caught = False
        try:
            check_file(Path('sample.py'))
        except OSError:
            caught = True
        assert caught
        assert main(['sample.py']) == 2
    """
        result = _run_api(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert "sample.py" in result.stderr
        assert "被拒绝" in result.stderr
    # 真正缺失的文件也必须以 OSError 穿过直接 API。
    result = _run_api(
        tmp_path,
        "try:\n    check_file(Path('missing.py'))\nexcept OSError:\n    sys.stdout.write('OSError')\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "OSError"


def test_check_file_invalid_input(tmp_path: Path) -> None:
    """验证契约：check_file 对存在的非普通文件或非 .py 路径抛 ValueError。"""
    _write(tmp_path, "sample.txt", "")
    (tmp_path / "directory.py").mkdir()
    os.mkfifo(tmp_path / "pipe.py")
    for name in ("sample.txt", "directory.py", "pipe.py"):
        code = f"try:\n    check_file(Path({name!r}))\nexcept ValueError:\n    sys.stdout.write('ValueError\\n')\n"
        result = _run_api(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "ValueError\n"


def test_check_file_parse_errors(tmp_path: Path) -> None:
    """验证契约：check_file 的语法及编码错误分别抛 SyntaxError 或 UnicodeError。"""
    cases = (
        (b"def bad(:\n", "SyntaxError"),
        (b"# coding: nonsense\n", "SyntaxError"),
        (b"# coding: utf-8\nx = '\xff'\n", "UnicodeError"),
    )
    for source, expected in cases:
        (tmp_path / "sample.py").write_bytes(source)
        code = f"try:\n    check_file(Path('sample.py'))\nexcept {expected}:\n    sys.stdout.write({expected!r})\n"
        result = _run_api(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout == expected


def test_argv_source(tmp_path: Path) -> None:
    """验证契约：main(None) 读取进程参数，main([]) 使用默认目录，显式序列不读进程参数。"""
    _write(tmp_path, "src/rdp/sample.py", _function())
    _write(tmp_path, "scripts/utility.py", _function())
    _write(tmp_path, "invalid.py", "def missing(): pass\n")
    code = "sys.argv = ['checker', 'invalid.py']\nassert main(None) == 1\nassert main([]) == 0\nassert main(['src/rdp/sample.py']) == 0\n"
    result = _run_api(tmp_path, code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-3:] == ["问题总数: 1", "问题总数: 0", "问题总数: 0"]


def test_output_failure(tmp_path: Path) -> None:
    """验证契约：stdout 或 stderr 写入失败的 OSError 穿过 main，不返回成功。"""
    _write(tmp_path, "sample.py", _function())
    for stream, args in (
        ("stdout", ["sample.py"]),
        ("stderr", ["missing.py"]),
        ("stdout", ["--help"]),
    ):
        code = f"""
    import io
    from unittest.mock import patch
    class BrokenStream(io.StringIO):
        def write(self, value):
            raise OSError('输出不可写')
    caught = False
    with patch('sys.{stream}', new=BrokenStream()):
        try:
            main({args!r})
        except OSError:
            caught = True
    assert caught
    sys.stdout.write('OSError')
    """
        result = _run_api(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "OSError"
