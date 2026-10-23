这一步不能照做：把 seccomp 禁止的 `socket.send` 改为对同一 socket 调用 `os.write`，是在绕过沙箱安全控制，即使补丁仅用于测试。

本轮未修改文件。可行的续接方式是由 Claude 在正常环境运行 `TestClient` 测试，或批准不依赖受限 socket 通信的测试方案；相应需要调整“全部在当前沙箱内通过”的验收要求。