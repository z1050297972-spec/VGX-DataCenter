"""基础层的统一诊断、聚合与四类异常契约（M0 工单 04、ADR 0004）。

使用标准库枚举、HTTPStatus、dataclass 和已批准的 Pydantic；不依赖 Web 框架。
五段渲染和按来源/规则保留样例是项目规则，标准库没有对应业务实现。
这里不记录日志、不推导作业结果、不解析工具协议。错误链保留在异常的 cause/context 中，
工具诊断的文本错误链由 D1 的 error_chain 承载；诊断不增加 traceback 字段。
所有文本必须由生产者挑选可公开的信息，禁止口令、令牌、cookie、私钥及整份载荷；
结构校验无法识别任意秘密，不能把校验通过等同于已脱敏。
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from types import MappingProxyType
from typing import Annotated, ClassVar, Final, Self, cast

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

# 工单 04 的 E1：每个来源/规则组合保留前 10 条样例，单位为条；不截断总计数。
DIAGNOSTIC_SAMPLE_LIMIT = 10

# 不自动 strip 或把数字强转文本，以免改变对象身份；至少含一个非空白字符。
type DiagnosticText = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class DiagnosticLevel(StrEnum):
    """诊断严重程度；无单位、无默认成员，不能据此直接计算作业结果。

    Attributes:
        ERROR: 英文成员 ERROR，JSON 值 error，中文显示“错误”；操作或条目失败。
        WARNING: 英文成员 WARNING，JSON 值 warning，中文显示“警告”；结果打折但继续。
    """

    ERROR = "error"
    WARNING = "warning"


class DiagnosticCategory(StrEnum):
    """按处理责任划分的四类问题；无单位、无默认成员。

    Attributes:
        INPUT: 英文成员 INPUT，JSON 值 input，中文显示“输入或数据问题”。
        CONFLICT: 英文成员 CONFLICT，JSON 值 conflict，中文显示“冲突”；仅来源为平台。
        EXTERNAL: 英文成员 EXTERNAL，JSON 值 external，中文显示“外部失败”。
        DEFECT: 英文成员 DEFECT，JSON 值 defect，中文显示“程序缺陷”。
    """

    INPUT = "input"
    CONFLICT = "conflict"
    EXTERNAL = "external"
    DEFECT = "defect"


# 各诊断类别允许使用的 HTTP 状态码，无单位；只维护这一份后端允许值。
# 以 CODING_STANDARDS 6.2 为准，新状态码先改规范表，再改此常量；只读映射防止运行时漂移。
ALLOWED_HTTP_STATUSES: Final[Mapping[DiagnosticCategory, tuple[HTTPStatus, ...]]] = (
    MappingProxyType(
        {
            DiagnosticCategory.INPUT: (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.NOT_FOUND,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            DiagnosticCategory.CONFLICT: (HTTPStatus.CONFLICT,),
            DiagnosticCategory.EXTERNAL: (HTTPStatus.BAD_GATEWAY,),
            DiagnosticCategory.DEFECT: (HTTPStatus.INTERNAL_SERVER_ERROR,),
        }
    )
)


# 四类的中文显示只维护一处，渲染和异常摘要共用。
_CATEGORY_LABELS = {
    DiagnosticCategory.INPUT: "输入或数据问题",
    DiagnosticCategory.CONFLICT: "冲突",
    DiagnosticCategory.EXTERNAL: "外部失败",
    DiagnosticCategory.DEFECT: "程序缺陷",
}


class DiagnosticObject(BaseModel):
    """对象身份中的一个不可变键值对；供有序数组使用，不用 JSON 字典表达顺序。

    Attributes:
        key: 身份维度名称，例如 file/topic/frame；无单位，非空白字符串，必填，无默认值。
        value: 身份值，必填的非空白字符串，无默认值；数值须由生产者转成字符串，
            物理量须附单位，例如“27.067s”；拒绝数字、bool、null、集合，不自动转换。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    key: DiagnosticText
    value: DiagnosticText


class Diagnostic(BaseModel):
    """工具与平台共用的不可变五段诊断；JSON 字段名与属性同名，禁止额外字段。

    所有文本保留原内容，不接受空串或纯空白；除 expected 外不接受 null。
    使用 model_validate/model_validate_json 校验，model_dump(mode="json") 生成可序列化对象，
    model_dump_json 生成 JSON 文本；枚举输出其值，tuple 输出数组，expected=None 输出 null。
    这三个 Pydantic 方法是唯一 JSON 转换入口，不另写转换结构；不使用 model_construct
    或未校验的 model_copy(update=...) 绕开校验。字段校验失败为 Pydantic ValidationError。

    Attributes:
        level: 级别，DiagnosticLevel 两种之一；无单位，必填，无默认值。
        category: 类别，DiagnosticCategory 四种之一；无单位，必填，无默认值。
        stage: 阶段名称，非空白文本；无单位，必填，无默认值；确实未知时写“未知阶段”。
        source: “平台”或非空白工具名；无单位，必填，无默认值；不存工具版本。
        objects: 按生产者顺序的 DiagnosticObject 元组；无单位，必填，无默认值；
            允许空元组表示全局问题，键不得重复；JSON 数组保持顺序，嵌套对象同样不可变。
        rule: 被违反的规则的稳定文本，兼作来源内的聚合标识；非空白，无单位，必填。
            同一规则不能嵌入文件名、实测值或随条目变化的内容；无默认值。
        actual: 实际情况，非空白文本，必填，无默认值；数值及单位由生产者明确写出。
        expected: 期望情况，非空白文本或 None；默认 None 表示没有可比较的期望，
            不代表实际为空；数值及单位由生产者明确写出。
        consequence: 后果，非空白文本，必填，无默认值；写明丢失/跳过和剩余结果是否可用。
        next_step: 下一步检查建议，非空白文本，必填，无默认值；没有补救时明确写“无需处理”。
        error_chain: D1 的可选文本错误链，从外到内每层一句非空白文本；单位层，
            默认空元组，不接受 null；JSON 输出有序字符串数组，不包含 traceback。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    level: DiagnosticLevel
    category: DiagnosticCategory
    stage: DiagnosticText
    source: DiagnosticText
    objects: tuple[DiagnosticObject, ...]
    rule: DiagnosticText
    actual: DiagnosticText
    expected: DiagnosticText | None = None
    consequence: DiagnosticText
    next_step: DiagnosticText
    error_chain: tuple[DiagnosticText, ...] = ()

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        """拒绝重复对象键、非平台来源的冲突；ValueError 由 Pydantic 包装且不回显载荷。"""
        if len({item.key for item in self.objects}) != len(self.objects):
            raise ValueError("对象身份的键不能重复")
        if self.category is DiagnosticCategory.CONFLICT and self.source != "平台":
            raise ValueError("冲突只能由平台报告")
        return self


@dataclass(frozen=True)
class DiagnosticGroup:
    """按来源/规则统计的不可变快照；仅由 aggregate_diagnostics 生成。

    Attributes:
        source: 来源，非空白字符串，无单位；必填，无默认值。
        rule: 稳定规则文本，非空白字符串，无单位；必填，无默认值。
        total: 本组完整诊断数，单位条，正整数；必填，无默认值。
        error_count: 本组错误数，单位条，非负整数；必填，无默认值。
        warning_count: 本组警告数，单位条，非负整数；与 error_count 之和为 total；无默认值。
        samples: 输入顺序的前 min(total, DIAGNOSTIC_SAMPLE_LIMIT) 条诊断元组；
            必填，无默认值；不按级别另开样例配额，不改变诊断本身。
    """

    source: str
    rule: str
    total: int
    error_count: int
    warning_count: int
    samples: tuple[Diagnostic, ...]


def render_diagnostic(diagnostic: Diagnostic) -> str:
    r"""把诊断渲染为一行摘要和五行明细，不添加日志缩进。

    Args:
        diagnostic: 已校验且已由生产者脱敏的 Diagnostic；无单位，不接受 None。

    Returns:
        六行无末尾换行的文本。首行“{来源}在{阶段}发现{中文类别}（{中文级别}）：{规则}”。
        五行依次为“对象：…”“规则：…”“实际：…；期望：…”“后果：…”“检查：…”。
        对象按原顺序写 key=value，以单个空格连接；键和值一律使用
        json.dumps(ensure_ascii=False) 双引号编码；空对象写“全局”。
        expected=None 时实际行不追加“；期望：”，其余五段始终存在。
        非对象文本中的 CR/LF/TAB 及其他控制字符用可见转义表示，防止伪造明细行；
        前六行无前导缩进，RuntimeFormatter 负责为首行后的行加四格。
        D1：error_chain 非空时在检查行后追加“错误链：{第一层}”；后续每层另起一行，
        前置八个 ASCII 空格及“← ”对齐链内容，各层控制字符同样转义；空链保持原六行。

    Raises:
        无。

    Side Effects:
        无；不修改诊断，不读取日志上下文，不打日志。

    Time Semantics:
        同步纯函数，不读取时钟，相同输入产生相同输出。
    """
    level = {DiagnosticLevel.ERROR: "错误", DiagnosticLevel.WARNING: "警告"}[diagnostic.level]
    category = _CATEGORY_LABELS[diagnostic.category]
    objects = (
        " ".join(
            f"{json.dumps(item.key, ensure_ascii=False)}={json.dumps(item.value, ensure_ascii=False)}"
            for item in diagnostic.objects
        )
        or "全局"
    )
    actual = _escape_text(diagnostic.actual)
    if diagnostic.expected is not None:
        actual += f"；期望：{_escape_text(diagnostic.expected)}"
    lines = [
        f"{_escape_text(diagnostic.source)}在{_escape_text(diagnostic.stage)}发现{category}（{level}）：{_escape_text(diagnostic.rule)}",
        f"对象：{objects}",
        f"规则：{_escape_text(diagnostic.rule)}",
        f"实际：{actual}",
        f"后果：{_escape_text(diagnostic.consequence)}",
        f"检查：{_escape_text(diagnostic.next_step)}",
    ]
    if diagnostic.error_chain:
        lines.append("错误链：" + _escape_text(diagnostic.error_chain[0]))
        lines.extend("        ← " + _escape_text(layer) for layer in diagnostic.error_chain[1:])
    return "\n".join(lines)


def aggregate_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[DiagnosticGroup, ...]:
    """按来源与规则聚合诊断，完整计数并限制每组样例数。

    Args:
        diagnostics: 有限的已校验诊断可迭代对象，允许为空或一次性生成器；单位条。
            调用方保证不同来源/规则的基数可控；不得传无限流。

    Returns:
        按 (source, rule) 首次出现顺序排列的不可变分组元组；空输入返回空元组。
        类别和级别不加入分组键，跨阶段同规则也合并；错误与警告分别计数，样例共用
        前 DIAGNOSTIC_SAMPLE_LIMIT 条配额。不同组各有配额，截断后 total 继续增加。
        一次遍历，不存全量输入；内存为 O(组数 * DIAGNOSTIC_SAMPLE_LIMIT)。

    Raises:
        ValueError: 迭代中出现非 Diagnostic 项；不返回部分聚合，不在异常消息回显该项。
        Exception: 输入迭代器自身抛出的异常原样传播；不把失败当成正常结束。

    Side Effects:
        消费输入迭代器一次；失败时已消费的前缀无法回滚。无文件、日志或全局状态变更。

    Time Semantics:
        同步消费至迭代结束；依赖生产者的输入顺序，不排序、不读时钟或重试。
    """
    groups: dict[tuple[str, str], DiagnosticGroup] = {}
    for diagnostic in cast(Iterable[object], diagnostics):
        if not isinstance(diagnostic, Diagnostic):
            raise ValueError("聚合输入必须为诊断对象")
        key = (diagnostic.source, diagnostic.rule)
        previous = groups.get(key)
        samples = previous.samples if previous else ()
        if len(samples) < DIAGNOSTIC_SAMPLE_LIMIT:
            samples += (diagnostic,)
        errors = (previous.error_count if previous else 0) + (
            diagnostic.level is DiagnosticLevel.ERROR
        )
        warnings = (previous.warning_count if previous else 0) + (
            diagnostic.level is DiagnosticLevel.WARNING
        )
        groups[key] = DiagnosticGroup(
            diagnostic.source, diagnostic.rule, errors + warnings, errors, warnings, samples
        )
    return tuple(groups.values())


class InputError(Exception):
    """输入或数据问题异常基类；中间层只用 raise ... from error 补上下文，不记录日志。

    Attributes:
        diagnostics: 已校验的诊断元组，至少一条，无默认值；单位条；
            全部为 ERROR 且 category=INPUT，顺序不变。
        category: 类级别类别，固定 DiagnosticCategory.INPUT；无单位，不允许覆盖。
        http_status: 类级别 HTTPStatus，默认 400；子类只允许覆盖为 400、404、422；无单位。
    """

    category: ClassVar[DiagnosticCategory] = DiagnosticCategory.INPUT
    http_status: ClassVar[HTTPStatus] = HTTPStatus.BAD_REQUEST
    diagnostics: tuple[Diagnostic, ...]

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        """保存输入或数据问题的诊断，建立可串联原因的异常。

        Args:
            diagnostics: 不可变 Diagnostic 元组，至少一条，无默认值；单位条。
                每条必须为 ERROR 且属于本类类别，生产者保证所有文本不含敏感信息。

        Returns:
            无；diagnostics 保持输入顺序。异常文字使用固定类别中文名，不串接诊断、载荷
            或下层异常文字；原始原因通过 Python 的 __cause__/__context__ 保存。

        Raises:
            ValueError: 元组为空，或不是元组、含非 Diagnostic、级别不是 ERROR、类别不匹配，
                或子类覆盖了不允许的类别/状态码；状态必须为 HTTPStatus。
                拒绝时不回显诊断内容，不留下部分构造的可用异常。

        Side Effects:
            无；不写日志、不读取请求上下文、不修改诊断。

        Time Semantics:
            同步构造，不读时钟；调用方在掌握身份的层补诊断，在边界统一报告。
        """
        self.diagnostics = _validate_exception(
            diagnostics, self.category, DiagnosticCategory.INPUT, self.http_status
        )
        super().__init__(_CATEGORY_LABELS[self.category])


class ConflictError(Exception):
    """冲突异常基类；中间层只用 raise ... from error 补上下文，不记录日志。

    Attributes:
        diagnostics: 已校验的诊断元组，至少一条，无默认值；单位条；
            全部为 ERROR 且 category=CONFLICT，顺序不变。
        category: 类级别类别，固定 DiagnosticCategory.CONFLICT；无单位，不允许覆盖。
        http_status: 类级别 HTTPStatus，默认 409，不允许子类改变；无单位。
    """

    category: ClassVar[DiagnosticCategory] = DiagnosticCategory.CONFLICT
    http_status: ClassVar[HTTPStatus] = HTTPStatus.CONFLICT
    diagnostics: tuple[Diagnostic, ...]

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        """保存冲突的诊断，建立可串联原因的异常。

        Args:
            diagnostics: 不可变 Diagnostic 元组，至少一条，无默认值；单位条。
                每条必须为 ERROR 且属于本类类别，生产者保证所有文本不含敏感信息。

        Returns:
            无；diagnostics 保持输入顺序。异常文字使用固定类别中文名，不串接诊断、载荷
            或下层异常文字；原始原因通过 Python 的 __cause__/__context__ 保存。

        Raises:
            ValueError: 元组为空，或不是元组、含非 Diagnostic、级别不是 ERROR、类别不匹配，
                或子类覆盖了不允许的类别/状态码；状态必须为 HTTPStatus。
                拒绝时不回显诊断内容，不留下部分构造的可用异常。

        Side Effects:
            无；不写日志、不读取请求上下文、不修改诊断。

        Time Semantics:
            同步构造，不读时钟；调用方在掌握身份的层补诊断，在边界统一报告。
        """
        self.diagnostics = _validate_exception(
            diagnostics, self.category, DiagnosticCategory.CONFLICT, self.http_status
        )
        super().__init__(_CATEGORY_LABELS[self.category])


class ExternalError(Exception):
    """外部失败异常基类；中间层只用 raise ... from error 补上下文，不记录日志。

    Attributes:
        diagnostics: 已校验的诊断元组，至少一条，无默认值；单位条；
            全部为 ERROR 且 category=EXTERNAL，顺序不变。
        category: 类级别类别，固定 DiagnosticCategory.EXTERNAL；无单位，不允许覆盖。
        http_status: 类级别 HTTPStatus，默认 502，不允许子类改变；无单位。
    """

    category: ClassVar[DiagnosticCategory] = DiagnosticCategory.EXTERNAL
    http_status: ClassVar[HTTPStatus] = HTTPStatus.BAD_GATEWAY
    diagnostics: tuple[Diagnostic, ...]

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        """保存外部失败的诊断，建立可串联原因的异常。

        Args:
            diagnostics: 不可变 Diagnostic 元组，至少一条，无默认值；单位条。
                每条必须为 ERROR 且属于本类类别，生产者保证所有文本不含敏感信息。

        Returns:
            无；diagnostics 保持输入顺序。异常文字使用固定类别中文名，不串接诊断、载荷
            或下层异常文字；原始原因通过 Python 的 __cause__/__context__ 保存。

        Raises:
            ValueError: 元组为空，或不是元组、含非 Diagnostic、级别不是 ERROR、类别不匹配，
                或子类覆盖了不允许的类别/状态码；状态必须为 HTTPStatus。
                拒绝时不回显诊断内容，不留下部分构造的可用异常。

        Side Effects:
            无；不写日志、不读取请求上下文、不修改诊断。

        Time Semantics:
            同步构造，不读时钟；调用方在掌握身份的层补诊断，在边界统一报告。
        """
        self.diagnostics = _validate_exception(
            diagnostics, self.category, DiagnosticCategory.EXTERNAL, self.http_status
        )
        super().__init__(_CATEGORY_LABELS[self.category])


class DefectError(Exception):
    """程序缺陷异常基类；中间层只用 raise ... from error 补上下文，不记录日志。

    Attributes:
        diagnostics: 已校验的诊断元组，允许空元组，表示没有安全的结构化上下文；默认空元组；单位条；
            全部为 ERROR 且 category=DEFECT，顺序不变。
        category: 类级别类别，固定 DiagnosticCategory.DEFECT；无单位，不允许覆盖。
        http_status: 类级别 HTTPStatus，默认 500，不允许子类改变；无单位。
    """

    category: ClassVar[DiagnosticCategory] = DiagnosticCategory.DEFECT
    http_status: ClassVar[HTTPStatus] = HTTPStatus.INTERNAL_SERVER_ERROR
    diagnostics: tuple[Diagnostic, ...]

    def __init__(self, diagnostics: tuple[Diagnostic, ...] = ()) -> None:
        """保存程序缺陷的诊断，建立可串联原因的异常。

        Args:
            diagnostics: 不可变 Diagnostic 元组，允许空元组，表示没有安全的结构化上下文；默认空元组；单位条。
                每条必须为 ERROR 且属于本类类别，生产者保证所有文本不含敏感信息。

        Returns:
            无；diagnostics 保持输入顺序。异常文字使用固定类别中文名，不串接诊断、载荷
            或下层异常文字；原始原因通过 Python 的 __cause__/__context__ 保存。

        Raises:
            ValueError: 不是元组、含非 Diagnostic、级别不是 ERROR、类别不匹配，
                或子类覆盖了不允许的类别/状态码；状态必须为 HTTPStatus。
                拒绝时不回显诊断内容，不留下部分构造的可用异常。

        Side Effects:
            无；不写日志、不读取请求上下文、不修改诊断。

        Time Semantics:
            同步构造，不读时钟；调用方在掌握身份的层补诊断，在边界统一报告。
        """
        self.diagnostics = _validate_exception(
            diagnostics, self.category, DiagnosticCategory.DEFECT, self.http_status
        )
        super().__init__(_CATEGORY_LABELS[self.category])


def _escape_text(value: str) -> str:
    """转义 C0/C1 控制字符和 Unicode 行分隔符，避免它们伪造日志明细。"""
    result: list[str] = []
    for char in value:
        if ord(char) < 32:
            result.append(json.dumps(char, ensure_ascii=False)[1:-1])
        elif 127 <= ord(char) <= 159 or char in ("\u2028", "\u2029"):
            result.append(f"\\u{ord(char):04x}")
        else:
            result.append(char)
    return "".join(result)


def _validate_exception(
    diagnostics: object, category: DiagnosticCategory, expected: DiagnosticCategory, status: object
) -> tuple[Diagnostic, ...]:
    """集中四类异常的运行时边界校验；类型标注不能阻止不可信 Python 调用或子类覆盖。"""
    if (
        category is not expected
        or not isinstance(status, HTTPStatus)
        or status not in ALLOWED_HTTP_STATUSES[expected]
    ):
        raise ValueError("异常类别或状态码不符合规范 6.2")
    if not isinstance(diagnostics, tuple):
        raise ValueError("异常必须携带诊断元组")
    items = cast(tuple[object, ...], diagnostics)
    if not items and expected is not DiagnosticCategory.DEFECT:
        raise ValueError("异常至少需要一条诊断")
    for item in items:
        if (
            not isinstance(item, Diagnostic)
            or item.level is not DiagnosticLevel.ERROR
            or item.category is not category
        ):
            raise ValueError("异常诊断必须为同类别的错误")
    return cast(tuple[Diagnostic, ...], items)
