"""开发检查工具，用 AST 只读检查 Python 函数契约，不属于平台运行时三层。

ruff 的 pydocstyle、pydoclint 只识别标准文档小节，不能检查 Side Effects: 和
Time Semantics:，所以用标准库 ast 补齐完整性、顺序和非空检查；不执行被检查代码，
不核对契约内容是否符合业务，也不重复实现 ruff 的签名核对。
依据：AGENTS 规则 4、CODING_STANDARDS 3.1，M0 工单 01「仓库骨架和检查链」。
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal


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
    raise NotImplementedError


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
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
