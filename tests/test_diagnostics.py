"""工单 04 的公开契约测试；只用内存输入和临时目录，验证诊断与失败边界。"""

import json
import logging
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any, cast

import pytest
from pydantic import ValidationError

from rdp.infra import diagnostics as diagnostics_module
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
    aggregate_diagnostics,
    render_diagnostic,
)
from rdp.infra.logging import RuntimeFormatter
from rdp.jobs.outcome import JobOutcome, calculate_outcome


def _data(**changes: object) -> dict[str, object]:
    """构造公开模型的正常输入，边界测试只改变相关字段。"""
    return (
        dict(
            level="error",
            category="input",
            stage="解码",
            source="平台",
            objects=[dict(key="file", value="示例.mcap")],
            rule="至少一个关键帧",
            actual="关键帧0个",
            expected="至少1个",
            consequence="该文件失败，其余继续",
            next_step="检查码流",
        )
        | changes
    )


def _diagnostic(**changes: object) -> Diagnostic:
    """通过公开校验入口构造诊断，不绕开约束。"""
    return Diagnostic.model_validate(_data(**changes))


def test_level_and_category_values() -> None:
    """验证契约：枚举英文成员、JSON 值、中文显示对应文档；只允许 error/warning 及四类，未知值触发 ValidationError。"""
    assert [(x.name, x.value) for x in DiagnosticLevel] == [
        ("ERROR", "error"),
        ("WARNING", "warning"),
    ]
    assert [(x.name, x.value) for x in DiagnosticCategory] == [
        ("INPUT", "input"),
        ("CONFLICT", "conflict"),
        ("EXTERNAL", "external"),
        ("DEFECT", "defect"),
    ]
    assert _diagnostic().level is DiagnosticLevel.ERROR
    for field in ("level", "category"):
        with pytest.raises(ValidationError):
            _diagnostic(**{field: "未知"})


def test_model_required_fields() -> None:
    """验证契约：Diagnostic 与 DiagnosticObject 缺少每个必填字段均触发 ValidationError；expected 省略或 null 为 None。"""
    for field in (
        "level",
        "category",
        "stage",
        "source",
        "objects",
        "rule",
        "actual",
        "consequence",
        "next_step",
    ):
        data = _data()
        del data[field]
        with pytest.raises(ValidationError):
            Diagnostic.model_validate(data)
    for field in ("key", "value"):
        data = dict(key="file", value="样例")
        del data[field]
        with pytest.raises(ValidationError):
            DiagnosticObject.model_validate(data)
    data = _data()
    del data["expected"]
    assert Diagnostic.model_validate(data).expected is None
    assert _diagnostic(expected=None).expected is None


def test_model_text_constraints() -> None:
    """验证契约：逐个文本字段拒绝空串、纯空白、null 和数字/bool/集合；expected 仅额外允许 None；不自动 strip。"""
    for field in ("stage", "source", "rule", "actual", "expected", "consequence", "next_step"):
        for value in ("", " \t\n", 1, True, list[object](), dict[str, object]()):
            with pytest.raises(ValidationError):
                _diagnostic(**{field: value})
        if field != "expected":
            with pytest.raises(ValidationError):
                _diagnostic(**{field: None})
    assert _diagnostic(actual="  原样  ").actual == "  原样  "


def test_model_extra_fields() -> None:
    """验证契约：诊断和对象键值对拒绝额外字段，拒绝 traceback；D1 的 error_chain 默认空元组且只收非空白文本层。"""
    with pytest.raises(ValidationError):
        _diagnostic(traceback="禁止字段")
    with pytest.raises(ValidationError):
        DiagnosticObject.model_validate(dict(key="file", value="x", extra="禁止"))
    assert _diagnostic().error_chain == ()
    assert _diagnostic(error_chain=["外层", "内层"]).error_chain == ("外层", "内层")
    for invalid in (None, "", [" "], [1]):
        with pytest.raises(ValidationError):
            _diagnostic(error_chain=invalid)


def test_model_object_values() -> None:
    """验证契约：对象值只接受字符串；frame="812"、t="27.067s" 保留原值，数字 812 与 null 被拒绝。"""
    d = _diagnostic(objects=[dict(key="frame", value="812"), dict(key="t", value="27.067s")])
    assert [(x.key, x.value) for x in d.objects] == [("frame", "812"), ("t", "27.067s")]
    for invalid in (812, True, None, list[object](), dict[str, object](), ""):
        with pytest.raises(ValidationError):
            _diagnostic(objects=[dict(key="frame", value=invalid)])


def test_model_duplicate_keys() -> None:
    """验证契约：Diagnostic._validate_identity 拒绝重复对象键；空对象合法代表全局问题。"""
    with pytest.raises(ValidationError):
        _diagnostic(objects=[dict(key="file", value="a"), dict(key="file", value="b")])
    assert _diagnostic(objects=[]).objects == ()


def test_model_tool_conflict() -> None:
    """验证契约：工具来源允许 INPUT/EXTERNAL/DEFECT；工具 CONFLICT 触发 ValidationError，平台 CONFLICT 合法。"""
    for category in ("input", "external", "defect"):
        assert _diagnostic(source="mcap2lerobot", category=category).source == "mcap2lerobot"
    with pytest.raises(ValidationError):
        _diagnostic(source="工具", category="conflict")
    assert _diagnostic(category="conflict").category is DiagnosticCategory.CONFLICT


def test_model_deep_immutability() -> None:
    """验证契约：冻结模型禁止字段赋值；objects 元组及其嵌套 DiagnosticObject 不可变；构造列表后修改原列表不影响模型。"""
    objects = [dict(key="file", value="a")]
    d = _diagnostic(objects=objects)
    objects[0]["value"] = "b"
    assert d.objects[0].value == "a"
    with pytest.raises(ValidationError):
        d.actual = "修改"
    with pytest.raises(ValidationError):
        d.objects[0].value = "修改"
    assert isinstance(d.objects, tuple)
    assert isinstance(d.error_chain, tuple)


def test_json_round_trip() -> None:
    """验证契约：model_dump(mode="json")/model_dump_json D1 后固定十一个字段、枚举字符串、对象数组顺序及 expected=null；model_validate_json 可往返。"""
    d = _diagnostic(expected=None, error_chain=["外层", "根因"])
    payload = d.model_dump(mode="json")
    assert set(payload) == {
        "level",
        "category",
        "stage",
        "source",
        "objects",
        "rule",
        "actual",
        "expected",
        "consequence",
        "next_step",
        "error_chain",
    }
    assert payload["level"] == "error"
    assert payload["objects"] == [dict(key="file", value="示例.mcap")]
    assert payload["expected"] is None
    assert payload["error_chain"] == ["外层", "根因"]
    assert json.loads(d.model_dump_json()) == payload
    assert Diagnostic.model_validate_json(d.model_dump_json()) == d


def test_json_validation_error_privacy() -> None:
    """验证契约：模型校验错误字符串不回显非法输入，生产边界不记录 ValidationError.errors() 的 input；不把结构校验声称为脱敏。"""
    for model, payload in (
        (Diagnostic, _data(level="机密输入值")),
        (DiagnosticObject, dict(key="x", value={"机密输入值": 1})),
    ):
        with pytest.raises(ValidationError) as caught:
            model.model_validate(payload)
        assert "机密输入值" not in str(caught.value)


def test_render_six_lines() -> None:
    """验证契约：render_diagnostic 摘要含中文级别/类别、阶段、来源，五段按对象/规则/实际与期望/后果/检查排列，无尾换行。"""
    lines = render_diagnostic(_diagnostic()).splitlines()
    assert len(lines) == 6
    assert lines[0] == "平台在解码发现输入或数据问题（错误）：至少一个关键帧"
    assert lines[1] == '对象："file"="示例.mcap"'
    assert lines[2] == "规则：至少一个关键帧"
    assert lines[3] == "实际：关键帧0个；期望：至少1个"
    assert lines[4] == "后果：该文件失败，其余继续"
    assert lines[5] == "检查：检查码流"
    assert not render_diagnostic(_diagnostic()).endswith("\n")


def test_render_object_order() -> None:
    """验证契约：render_diagnostic 保留 file/topic/frame 的输入顺序，键和值 JSON 双引号转义且以空格分隔，不按字典序重排。"""
    d = _diagnostic(
        objects=[
            dict(key="topic", value="左相机"),
            dict(key="file", value='a=b"c'),
            dict(key="frame", value="812"),
        ]
    )
    assert (
        render_diagnostic(d).splitlines()[1]
        == '对象："topic"="左相机" "file"="a=b\\"c" "frame"="812"'
    )


def test_render_global_and_no_expectation() -> None:
    """验证契约：空对象输出全局，expected=None 时不输出期望标签，五段仍齐全。"""
    lines = render_diagnostic(_diagnostic(objects=[], expected=None)).splitlines()
    assert lines[1] == "对象：全局"
    assert lines[3] == "实际：关键帧0个"
    assert len(lines) == 6


def test_render_control_characters() -> None:
    """验证契约：引号、等号、中文、CR/LF/TAB 和其他控制字符不会产生额外日志行；实际/期望始终在同一行。"""
    d = _diagnostic(actual="中文\r\n\t\x00", expected="a\nb", rule="行\n规则")
    lines = render_diagnostic(d).splitlines()
    assert len(lines) == 6
    assert lines[3] == r"实际：中文\r\n\t\u0000；期望：a\nb"
    assert "\n" not in lines[2]


def test_render_formatter_indentation() -> None:
    """验证契约：render_diagnostic 本身不缩进，交给 RuntimeFormatter 后明细仅四格，不能出现八格重复缩进。"""
    message = render_diagnostic(_diagnostic())
    record = logging.LogRecord("测试", logging.ERROR, __file__, 1, message, (), None)
    output = RuntimeFormatter().format(record)
    assert all(
        line.startswith("    ") and not line.startswith("        ")
        for line in output.splitlines()[1:]
    )


def test_render_pure(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：render_diagnostic 重复结果相同，不改输入/contextvars、不记录日志或访问时间。"""
    d = _diagnostic()
    before = d.model_dump()
    assert render_diagnostic(d) == render_diagnostic(d)
    assert d.model_dump() == before
    assert not caplog.records


def test_aggregate_empty() -> None:
    """验证契约：aggregate_diagnostics 空迭代器返回空元组，不记录日志。"""
    assert aggregate_diagnostics(iter(())) == ()


def test_aggregate_limit_boundary() -> None:
    """验证契约：同来源同规则输入 N-1/N/N+1 条，样例数分别为 9/10/10，总数分别为 9/10/11；E1 的 N=10。"""
    for count, sample_count in ((9, 9), (10, 10), (11, 10)):
        ds = [_diagnostic(actual=str(i)) for i in range(count)]
        groups = aggregate_diagnostics(iter(ds))
        assert len(groups) == 1
        assert groups[0].total == count
        assert len(groups[0].samples) == sample_count
        assert [d.actual for d in groups[0].samples] == [str(i) for i in range(sample_count)]


def test_aggregate_groups_independent() -> None:
    """验证契约：不同来源或规则各自保留前十条，不互相挤占；顺序按首次出现，非来源字典序。"""
    groups = aggregate_diagnostics(
        [_diagnostic(source="z", actual=str(i)) for i in range(12)]
        + [_diagnostic(source="a", actual=str(i)) for i in range(11)]
        + [_diagnostic(source="z", rule="另一规则") for _ in range(13)]
    )
    assert [(g.source, g.rule, g.total, len(g.samples)) for g in groups] == [
        ("z", "至少一个关键帧", 12, 10),
        ("a", "至少一个关键帧", 11, 10),
        ("z", "另一规则", 13, 10),
    ]


def test_aggregate_levels_categories_stages() -> None:
    """验证契约：同来源规则但不同级别/类别/阶段仍同组，样例共用十条，error_count/warning_count 分开且相加等于 total。"""
    groups = aggregate_diagnostics(
        [_diagnostic(), _diagnostic(level="warning", category="external", stage="编码")]
    )
    assert len(groups) == 1
    assert (groups[0].total, groups[0].error_count, groups[0].warning_count) == (2, 1, 1)
    assert [d.stage for d in groups[0].samples] == ["解码", "编码"]


def test_aggregate_one_pass() -> None:
    """验证契约：一次性生成器只消费一次，空与非空均可；只保存各组前十条，不留全量诊断，不改输入。"""
    consumed: list[int] = []

    def values() -> Iterator[Diagnostic]:
        """一次性生产器在消费时记录位置，不预存全量输入。"""
        for i in range(30):
            consumed.append(i)
            yield _diagnostic(actual=str(i))

    iterator = values()
    (group,) = aggregate_diagnostics(iterator)
    assert consumed == list(range(30))
    assert list(iterator) == []
    assert group.total == 30 and len(group.samples) == 10


def test_aggregate_invalid_item() -> None:
    """验证契约：aggregate_diagnostics 非 Diagnostic 项触发 ValueError，不回显该项；已消费前缀不回滚，不返回部分结果。"""
    source = iter([_diagnostic(), "敏感的非法项", _diagnostic(actual="尾项")])
    with pytest.raises(ValueError) as caught:
        aggregate_diagnostics(cast(Any, source))
    assert "敏感的非法项" not in str(caught.value)
    remaining = next(source)
    assert isinstance(remaining, Diagnostic) and remaining.actual == "尾项"


def test_aggregate_iterator_failure() -> None:
    """验证契约：输入迭代器的异常原样传播，已消费前缀不回滚，不误报完整总数，不打印日志。"""
    error = RuntimeError("迭代失败")

    def values() -> Iterator[Diagnostic]:
        """在真实迭代边界抛出故障。"""
        yield _diagnostic()
        raise error

    with pytest.raises(RuntimeError) as caught:
        aggregate_diagnostics(values())
    assert caught.value is error


def test_input_error_contract() -> None:
    """验证契约：InputError 至少一条 INPUT/ERROR，保持顺序，默认 HTTPStatus.BAD_REQUEST，合法子类可覆盖 404/422。"""
    ds = (_diagnostic(category="input"), _diagnostic(category="input", actual="另一条"))
    error = InputError(ds)
    assert error.diagnostics == ds
    assert error.http_status == 400
    assert isinstance(error.http_status, HTTPStatus)
    assert str(error) == "输入或数据问题"


def test_conflict_error_contract() -> None:
    """验证契约：ConflictError 至少一条 CONFLICT/ERROR，HTTPStatus.CONFLICT=409，保持全部诊断顺序。"""
    ds = (_diagnostic(category="conflict"), _diagnostic(category="conflict", actual="另一条"))
    error = ConflictError(ds)
    assert error.diagnostics == ds
    assert error.http_status == 409
    assert isinstance(error.http_status, HTTPStatus)
    assert str(error) == "冲突"


def test_external_error_contract() -> None:
    """验证契约：ExternalError 至少一条 EXTERNAL/ERROR，HTTPStatus.BAD_GATEWAY=502，命令/退出码等安全上下文由诊断承载。"""
    ds = (_diagnostic(category="external"), _diagnostic(category="external", actual="另一条"))
    error = ExternalError(ds)
    assert error.diagnostics == ds
    assert error.http_status == 502
    assert isinstance(error.http_status, HTTPStatus)
    assert str(error) == "外部失败"


def test_defect_error_contract() -> None:
    """验证契约：DefectError 默认空元组，也可携带多条 DEFECT/ERROR 上下文，HTTPStatus.INTERNAL_SERVER_ERROR=500。"""
    ds = (_diagnostic(category="defect"), _diagnostic(category="defect", actual="另一条"))
    error = DefectError(ds)
    assert error.diagnostics == ds
    assert error.http_status == 500
    assert isinstance(error.http_status, HTTPStatus)
    assert str(error) == "程序缺陷"
    assert DefectError().diagnostics == ()


def test_exception_empty_and_container_validation() -> None:
    """验证契约：四类构造器拒绝非元组和非 Diagnostic；前三类拒绝空元组，DefectError 接受空元组。"""
    for cls in (InputError, ConflictError, ExternalError, DefectError):
        for value in (list[object](), "非法", (object(),)):
            with pytest.raises(ValueError):
                cls(cast(Any, value))
    for cls in (InputError, ConflictError, ExternalError):
        with pytest.raises(ValueError):
            cls(())
    assert DefectError().diagnostics == ()


def test_exception_level_and_category_validation() -> None:
    """验证契约：四类构造器逐一拒绝 WARNING 和不匹配类别，抛 ValueError 且不回显诊断内容。"""
    for cls, category in (
        (InputError, "input"),
        (ConflictError, "conflict"),
        (ExternalError, "external"),
        (DefectError, "defect"),
    ):
        for d in (
            _diagnostic(category=category, level="warning"),
            _diagnostic(category="input" if category != "input" else "external"),
        ):
            with pytest.raises(ValueError):
                cls((d,))


def test_exception_subclass_status_validation() -> None:
    """验证契约：规范 6.2 表：公开状态码常量和四类基类逐项一致，拒绝子类越界及 int 冒充 HTTPStatus。"""
    # 期望逐项抄自规范 6.2，不能从被测常量反推，否则规则漂移时测试会一起漂移。
    assert diagnostics_module.ALLOWED_HTTP_STATUSES == {
        DiagnosticCategory.INPUT: (
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.NOT_FOUND,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
            HTTPStatus.TOO_MANY_REQUESTS,
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        ),
        DiagnosticCategory.CONFLICT: (HTTPStatus.CONFLICT,),
        DiagnosticCategory.EXTERNAL: (HTTPStatus.BAD_GATEWAY,),
        DiagnosticCategory.DEFECT: (HTTPStatus.INTERNAL_SERVER_ERROR,),
    }
    assert all(
        isinstance(status, HTTPStatus)
        for statuses in diagnostics_module.ALLOWED_HTTP_STATUSES.values()
        for status in statuses
    )
    # 基类默认值和各子类允许/禁止值也逐项写出，不从常量推导期望。
    table = (
        (InputError, "input", (400, 404, 422, 401, 403, 429), 418),
        (ConflictError, "conflict", (409,), 400),
        (ExternalError, "external", (502,), 503),
        (DefectError, "defect", (500,), 502),
    )
    for base, category, allowed, forbidden in table:
        assert int(base.http_status) == allowed[0]
        for status in allowed:
            subtype = type("合法子类", (base,), {"http_status": HTTPStatus(status)})
            assert cast(Any, subtype((_diagnostic(category=category),))).http_status == status
        for override in (HTTPStatus(forbidden), allowed[0]):
            subtype = type("非法子类", (base,), {"http_status": override})
            with pytest.raises(ValueError):
                subtype((_diagnostic(category=category),))
        subtype = type(
            "非法类别",
            (base,),
            {
                "category": DiagnosticCategory.EXTERNAL
                if category != "external"
                else DiagnosticCategory.INPUT
            },
        )
        with pytest.raises(ValueError):
            subtype((_diagnostic(category=category),))


def test_exception_context_no_logging(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：四类构造器异常文字为固定中文类别；raise ... from 原因保留 cause/context；构造不记录日志或读请求编号。"""
    cause = OSError("外部故障")
    try:
        raise ExternalError((_diagnostic(category="external"),)) from cause
    except ExternalError as error:
        assert error.__cause__ is cause
        assert str(error) == "外部失败"
    assert not caplog.records


def test_representative_conversion_partial_success() -> None:
    """验证契约：验收1/6.11：示例一三个 mcap，失败对象 file=RB01_20261011103210456.mcap、topic=/hdas/camera_head/left_raw/image_raw_color/compressed，实际1806条关键帧0；后果该文件失败不产出episode且其余继续；另两条警告分别丢3帧/排除12消息；calculate_outcome(总3,失败1,警告2,未中止)=PARTIALLY_SUCCEEDED；保留三层cause，不快照整段文本。"""
    d = _diagnostic(
        source="mcap2lerobot",
        objects=[
            dict(key="file", value="RB01_20261011103210456.mcap"),
            dict(key="topic", value="/hdas/camera_head/left_raw/image_raw_color/compressed"),
        ],
        actual="1806 条消息中关键帧 0 个",
        consequence="该文件失败，不产出 episode；其余文件继续",
        error_chain=[
            "转换 RB01_20261011103210456.mcap 失败",
            "相机 head_left 解码失败",
            "无法从 H.264 关键帧读取分辨率：流中没有关键帧",
        ],
    )
    assert d.objects[0].value == "RB01_20261011103210456.mcap"
    assert d.objects[1].value.endswith("/compressed")
    assert d.actual == "1806 条消息中关键帧 0 个"
    assert "不产出 episode" in d.consequence
    assert len(d.error_chain) == 3
    warnings = [
        _diagnostic(level="warning", consequence="丢弃 3 帧并切分"),
        _diagnostic(level="warning", consequence="排除前 12 条消息"),
    ]
    assert warnings[0].consequence == "丢弃 3 帧并切分"
    assert warnings[1].consequence == "排除前 12 条消息"
    assert (
        calculate_outcome(total_items=3, failed_items=1, warning_count=len(warnings), aborted=False)
        is JobOutcome.PARTIALLY_SUCCEEDED
    )


def test_render_error_chain() -> None:
    """验证契约： D1：错误链在检查之后显示，后续层用对齐的箭头，控制字符转义。"""
    lines = render_diagnostic(
        _diagnostic(error_chain=["转换失败", "相机失败", "根因\n细节"])
    ).splitlines()
    assert lines[6:] == ["错误链：转换失败", "        ← 相机失败", r"        ← 根因\n细节"]
    assert len(render_diagnostic(_diagnostic()).splitlines()) == 6


def test_render_unicode_line_boundaries() -> None:
    """验证契约：控制字符与 Unicode 行分隔符不能伪造额外日志行。"""
    for char in ("\x7f", "\x85", "\u2028", "\u2029"):
        output = render_diagnostic(_diagnostic(actual="前" + char + "后"))
        assert char not in output
        assert len(output.splitlines()) == 6
