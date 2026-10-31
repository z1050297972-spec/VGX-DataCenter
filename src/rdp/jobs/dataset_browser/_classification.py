"""分类候选的纯投影（M1.5-03）；词表只在 datasets.vocabulary 维护，不读取文件。"""

from urllib.parse import quote

from rdp.jobs.dataset_browser.schemas import FilterOption, VocabularyTerm
from rdp.jobs.datasets import vocabulary


def options(
    values: tuple[tuple[str, ...], ...], terms: tuple[vocabulary.VocabularyTerm, ...]
) -> tuple[FilterOption, ...]:
    """按数据集去重计数；词表外值保留，未标注最后，零计数词表项仍可选。"""
    counts: dict[str, int] = {}
    for row in values:
        for code in set(row):
            counts[code] = counts.get(code, 0) + 1
    known = {term.code for term in terms}
    return (
        tuple(
            FilterOption(value=term.code, label=term.name, count=counts.get(term.code, 0))
            for term in terms
        )
        + tuple(
            FilterOption(value=code, label=f"{code}（不在词表）", count=counts[code])
            for code in sorted(counts.keys() - known)
        )
        + (
            FilterOption(
                value=vocabulary.UNLABELED,
                label=vocabulary.UNLABELED_NAME,
                count=sum(not row for row in values),
            ),
        )
    )


def terms(values: tuple[vocabulary.VocabularyTerm, ...]) -> tuple[VocabularyTerm, ...]:
    """把领域常量投影成 OpenAPI 响应，不让页面再维护一份编码表。"""
    return tuple(VocabularyTerm(code=term.code, name=term.name) for term in values)


def scene_path(scene: str | None) -> str:
    """虚拟树路径编码词表外斜线，防止原值被误当成多层目录。"""
    code = scene or vocabulary.UNLABELED
    # quote 按 URI 标准保留点；纯点分量在目录前缀契约里有特殊含义，必须显式编码。
    encoded = "%2E" * len(code) if code in {".", ".."} else quote(code, safe="")
    return "按场景/" + encoded
