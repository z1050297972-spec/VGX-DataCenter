"""L12指纹契约；只操作临时导航，所有哈希期待值独立计算。"""

import pytest


def test_stable() -> None:
    """验收2：未改动时两个视图全部入口的指纹相等，不受枚举顺序或mtime改变影响。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_json_bytes_change() -> None:
    """验收2：修改任何一份JSON原字节（包括仅空白）都会改变数据集指纹。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_member_add_remove() -> None:
    """验收2：新增或删除一个直接目录项均改变指纹，隐藏项也包含在清单中。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_readlink_change() -> None:
    """验收2：改变一条实际链接的readlink字面目标改变指纹，断链和相对目标也不跟随。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_provenance_presence_hash() -> None:
    """L12：来源.json缺失、出现、内容改变、删除均被区分，内容不需要能够解析。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_all_format_entries() -> None:
    """L12：增加第二个格式入口、删除或改名已有入口、改JSON身份后仍通过旧路径并集检出变化。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_additional_json() -> None:
    """L12：四个约定文件以外的额外.json也计算原字节摘要，文件不存在与空文件可区分。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_roundtrip_immutable() -> None:
    """L12：model_dump_json/model_validate_json往返相等，嵌套字段及元组不可变，编码版本未知拒绝。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unverifiable() -> None:
    """L12：不可读文件、非普通JSON文件或读中变更标记verifiable=False，两个同样失败的值不能授权替换。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_no_storage_read() -> None:
    """L12：指纹只观察导航；目标、目录层软链接或JSON软链接不能导致访问假存储根。"""
    pytest.skip("M1-01：该契约尚未实现")
