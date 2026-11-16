"""手动工具演练共用临时导航夹具；仅显式运行 drills 时加载，不注册常规测试跳过项。"""

import sys
from pathlib import Path

# 演练复用仓库的临时 DB/导航构造器；机器相关入口全部留在 drills，不让 tests 反向导入。
_TESTS = Path(__file__).parents[2] / "tests"
sys.path.append(str(_TESTS.parent))
sys.path.append(str(_TESTS))
