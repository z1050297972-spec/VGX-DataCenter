"""演示（验收第 9 条）：执行线在沙箱外起 Web，分别触发四类报错，截真实页面。

只用临时配置和临时状态目录，不碰真实路径。生产代码里没有演示接口：
- `/api/_diagnostics-demo/*` 由 `tests/diagnostics_demo.py` 的 `mount_diagnostic_demo` 挂上（curl 用）；
- 页面只调 `/api/health`，所以本脚本按环境变量 `DEMO_HEALTH` 把 `/api/health` 换成抛对应一类的路由，
  诊断内容照代表性故障示例（`.scratch/platform-v1/assets/09-observability/代表性故障示例.md`）写。

用法：python demo.py <状态目录> <前端构建目录> <端口>，环境变量 DEMO_HEALTH=input|conflict|external|defect|ok。
"""

import os
import sys
from pathlib import Path

import uvicorn
from diagnostics_demo import mount_diagnostic_demo  # tests/ 下，PYTHONPATH 由调用方给

from rdp.api import create_app
from rdp.infra.diagnostics import ConflictError, Diagnostic, ExternalError, InputError
from rdp.infra.logging import LoggingSettings, configure_logging

state, dist, port = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
(state / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
configure_logging(LoggingSettings("web", state / "logs", stderr=False))


def diag(category: str, **kw: object) -> Diagnostic:
    return Diagnostic.model_validate({"level": "error", "category": category, "source": "平台", **kw})


def fail_input() -> None:
    raise InputError((diag("input", stage="读取数据集", objects=[{"key": "dataset", "value": "r1lite_叠衣服"}, {"key": "file", "value": "原始路径.json"}, {"key": "field", "value": "links[3].target"}], rule="每条链接都要有 target", actual="target 为 null", expected="非空的路径字符串", consequence="这条链接不显示；数据集的其余部分正常", next_step="打开该 JSON，对照导航层里的实际软链接补上 target"),))


def fail_conflict() -> None:
    raise ConflictError((diag("conflict", stage="提交改动", objects=[{"key": "dataset", "value": "r1lite_叠衣服"}], rule="提交时数据集不能已被别的作业改过", actual="预览之后作业 #57 改过该数据集", expected="数据集版本与预览时相同", consequence="本次提交未执行，数据集没有变化", next_step="等作业 #57 结束后重新预览再提交"),))


def fail_external() -> None:
    raise ExternalError((diag("external", stage="解码", source="mcap2lerobot", objects=[{"key": "file", "value": "RB01_20261011103210456.mcap"}, {"key": "topic", "value": "/hdas/camera_head/left_raw/image_raw_color/compressed"}], rule="每一路视频至少要有一个 H.264 关键帧", actual="1806 条消息中关键帧 0 个", expected="至少 1 个关键帧", consequence="该文件失败，不产出 episode；其余文件继续", next_step="用 ffprobe 看该话题码流的帧类型；对照这次采集的 boot.sh 日志", error_chain=["转换 RB01_20261011103210456.mcap 失败", "相机 head_left 解码失败", "无法从 H.264 关键帧读取分辨率：流中没有关键帧"]),))


def fail_defect() -> None:
    raw = {"target": None}
    Path(raw["target"])  # type: ignore[arg-type]  # 故意重现示例二的 TypeError


app = create_app(dist)
mount_diagnostic_demo(app)
mode = os.environ.get("DEMO_HEALTH", "ok")
if mode != "ok":
    endpoint = {"input": fail_input, "conflict": fail_conflict, "external": fail_external, "defect": fail_defect}[mode]
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]
    app.add_api_route("/api/health", endpoint, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())
    app.openapi_schema = None
uvicorn.run(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
