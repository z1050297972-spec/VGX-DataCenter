"""加入 ROS 图的共用 XML 副本脚本（作业内部，M5-09/11）。

用标准库 ElementTree 校验、re 原样替换地址；不重写命名空间，不修改厂商输入。
调用方负责引用源路径、目标路径和发现地址，以及限定目标目录和清理生命周期。
"""


def copy_discovery_xml() -> str:
    """生成使用 xml_source、xml_destination、discovery 三个 shell 变量的复制命令。"""
    return r"""
PYTHONDONTWRITEBYTECODE=1 python3 - "$xml_source" "$xml_destination" "$discovery" <<'RDP_XML'
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
source, destination, address = sys.argv[1:]
original = Path(source).read_text(encoding='utf-8')
# 不用 ElementTree 重写整份 XML：它会改命名空间前缀，厂商解析器未必接受。
updated, count = re.subn(r'(<address>)[^<]*(</address>)', lambda m: m[1] + address + m[2], original)
nodes = [node for node in ET.fromstring(updated).iter() if node.tag.split('}')[-1] == 'address']
if count == 0 or count != len(nodes) or any(node.text != address for node in nodes):
    sys.exit(1)
Path(destination).write_text(updated, encoding='utf-8')
RDP_XML
"""
