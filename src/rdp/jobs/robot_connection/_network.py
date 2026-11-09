"""网络层子进程：标准库完成 DNS 和 TCP；父进程为二者合计强制三秒期限。

getaddrinfo 没有可取消超时，不能放进回收不了的线程；独立进程使 DNS 阻塞也可回收。
不输出系统异常或请求载荷，只以退出码向父进程报告是否接通。
"""

import socket
import sys


def _main() -> int:
    """只尝试指定地址和端口，不扫描、不发送应用层数据。"""
    try:
        with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=float(sys.argv[3])):
            return 0
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(_main())
