"""python -m rdp 的进程包装（11），复用控制台入口，不另维护参数或退出码规则。"""

import sys

from rdp.cli import main

if __name__ == "__main__":
    sys.exit(main())
