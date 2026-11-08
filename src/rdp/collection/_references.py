"""采集编号空间映射；扫描提示与编辑校验共用，避免混用三个独立编号空间。"""

from rdp.collection.information import CollectionInformation
from rdp.collection.models import MethodRow, PurposeRow, RegistryRow, RobotRow


def references(
    value: CollectionInformation,
) -> tuple[tuple[str, type[RegistryRow], tuple[int, ...]], ...]:
    """按导航字段顺序列出编号及其对应登记表，不查询或修改数据库。"""
    return (
        ("method_id", MethodRow, () if value.method_id is None else (value.method_id,)),
        ("purpose_id", PurposeRow, () if value.purpose_id is None else (value.purpose_id,)),
        ("robot_ids", RobotRow, value.robot_ids),
    )
