"""08真实worker子进程的测试入口；显式临时目录，绝不发现默认home配置。"""

import sys
from pathlib import Path

from job_process_support import worker_main

if __name__ == "__main__":
    worker_main(Path(sys.argv[1]), sys.argv[2])
