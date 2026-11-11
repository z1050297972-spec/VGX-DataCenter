"""M5-09 远程脚本构造；用标准库引用、摘要和 base64，不引入 SSH/SFTP 依赖。

远程命令始终 bash -s；只上传查询缺失的内容。厂商路径仅作只读输入，写入固定用户目录。
"""

import base64
import hashlib
import io
import json
import shlex
import tarfile
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from rdp.collection.profile_models import RobotProfile
from rdp.infra import viz_relay
from rdp.infra.diagnostics import DefectError
from rdp.jobs.robot_connection._ros_scripts import copy_discovery_xml


def bundle(source: Path, config: dict[str, JsonValue]) -> tuple[str, bytes]:
    """给程序和配置算稳定包编号；只打包直接子目录中的 Python 文件。"""
    contents = {f"viz_relay/{p.name}": p.read_bytes() for p in sorted(source.glob("*.py"))}
    if "viz_relay/__main__.py" not in contents or "viz_relay/__init__.py" not in contents:
        raise FileNotFoundError("缺少转发包入口")
    contents["config.json"] = json.dumps(config, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data in contents.items():
            digest.update(name.encode() + b"\0" + data + b"\0")
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o600
            archive.addfile(entry, io.BytesIO(data))
    return digest.hexdigest()[:16], output.getvalue()


def query(package_id: str) -> str:
    """只读查询 wheel、site SDK 和包目录是否齐全，stdout 只含三个布尔结果。"""
    return (
        _variables(package_id)
        + r"""
# Python 版本是安装前提，不能借安装修改系统 Python。
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || { echo 'RDP_CONTROL_ERROR python_version'; exit 1; }
w=0; s=0; p=0
if [[ -f "$wheel" ]] && printf '%s  %s\n' "$digest" "$wheel" | sha256sum -c - >/dev/null 2>&1; then w=1; fi
if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/site" python3 -c "import importlib.metadata as m; assert m.version('foxglove-sdk') == '$sdk_version'" >/dev/null 2>&1; then s=1; fi
if [[ -d "$package" ]]; then p=1; fi
printf 'RDP_QUERY %s %s %s\n' "$w" "$s" "$p"
"""
    )


def install(
    package_id: str,
    archive: bytes,
    wheel: bytes | None,
    *,
    needs_package: bool,
    profile: RobotProfile,
) -> str:
    """补齐缺失内容后生成 XML 副本、带 ROS 环境运行自检，不启动服务器。"""
    script = _common() + _variables(package_id)
    if wheel is not None:
        script += '\nmkdir -p "$root/wheels"\n' + _upload('"$wheel.part"', wheel)
        script += r"""
# 上传后再次核对摘要，失败的临时包不能成为已安装文件。
if ! printf '%s  %s\n' "$digest" "$wheel.part" | sha256sum -c - >/dev/null 2>&1; then
    rm -f -- "$wheel.part"
    echo 'RDP_CONTROL_ERROR checksum'; exit 1
fi
mv -f -- "$wheel.part" "$wheel"
"""
    script += r"""
# 固定 wheel 只有包和元数据，标准库解压即可安装；禁写字节码，查询不产生额外文件。
export PYTHONDONTWRITEBYTECODE=1
if ! PYTHONPATH="$root/site" python3 -c "import importlib.metadata as m; assert m.version('foxglove-sdk') == '$sdk_version'" >/dev/null 2>&1; then
    # 先清理中断残留；完整解压并核对布局后才替换 site，避免半成品被下次查询复用。
    rm -rf -- "$root/site.part"
    python3 -m zipfile -e "$wheel" "$root/site.part" >"$root/log/install.log" 2>&1 || { echo 'RDP_CONTROL_ERROR install_failed'; exit 1; }
    if ! python3 - "$root/site.part" "$sdk_version" >>"$root/log/install.log" 2>&1 <<'RDP_SITE'
import sys
from pathlib import Path
site, version = sys.argv[1:]
# 固定版本不含脚本或 .data；布局变化必须停止，不能把未知安装内容直接发布。
assert {p.name for p in Path(site).iterdir()} == {'foxglove', f'foxglove_sdk-{version}.dist-info'}
RDP_SITE
    then echo 'RDP_CONTROL_ERROR install_failed'; exit 1; fi
    rm -rf -- "$root/site"
    mv -- "$root/site.part" "$root/site"
fi
"""
    if needs_package:
        script += '\nmkdir -p "$root/relay"\n' + _upload('"$root/relay/package.tar.gz"', archive)
        script += r"""
# 完整解包后才发布包目录；被打断的目录不会在下次查询中伪装成已安装。
mkdir -p "$package.part"
tar -xzf "$root/relay/package.tar.gz" -C "$package.part"
mv -- "$package.part" "$package"
rm -f -- "$root/relay/package.tar.gz"
"""
    join = profile.ros.join
    if join is None:
        raise DefectError()
    script += "\nxml_source=" + shlex.quote(join.fastdds_profiles_file)
    script += "\ndiscovery=" + shlex.quote(join.discovery_address) + "\n"
    script += r"""
# 厂商 XML 只读；解析后要求至少一个 address 且替换完全，避免悄悄加入错误的图。
"""
    script += 'xml_destination="$root/fastdds_local.xml"\n'
    script += "if ! " + copy_discovery_xml().lstrip()
    script += r"""
then echo 'RDP_CONTROL_ERROR xml_format'; exit 1; fi
"""
    script += "\nlaunch=" + shlex.quote(_launch(profile, mode="self-test")) + "\n"
    script += r"""
cd -- "$package"
# 自检和运行使用同一份干净 ROS 环境；原始自检输出只留在机器人专用日志目录。
if ! env -i HOME="$HOME" USER="$USER" LANG=C.UTF-8 PATH=/usr/bin:/bin \
    bash -c "$launch" -- "$config" >"$root/log/self-test.log" 2>&1; then
    report_error "$root/log/self-test.log" self_test_failed; exit 1
fi
grep -Fx 'RDP_VIZ_SELFTEST ok' "$root/log/self-test.log" >/dev/null || { echo 'RDP_CONTROL_ERROR self_test_failed'; exit 1; }
echo 'RDP_CONTROL installed'
"""
    return script


def start(package_id: str, profile: RobotProfile, port: int) -> str:
    """生成有锁、有限等待和失败清理的启动脚本。"""
    return (
        _common()
        + _variables(package_id)
        + "\nport="
        + shlex.quote(str(port))
        + "\nlaunch="
        + shlex.quote(_launch(profile, mode="service"))
        + "\n"
        + _resource("_preview_start.sh")
    )


def probe(package_id: str, profile: RobotProfile) -> str:
    """生成无锁探测脚本，使用启动包的配置及相同 ROS 环境。

    Args:
        package_id: bundle 生成的 16 位十六进制包编号。
        profile: 本次启动所用的已校验型号事实，必须含 ros.join。

    Returns:
        供 bash -s 执行的脚本；stdout 只保留探测或错误协议行。

    Raises:
        DefectError: profile 缺少 ros.join，平台调用前提不成立。

    Side Effects:
        构造时无；执行时覆盖 ~/rdp_viz/log/probe.log 并临时订阅 ROS，
        不拿启停锁、不改 pidfile、不操作已运行的预览进程。

    Time Semantics:
        调用方用 PROBE_TIMEOUT_S 限制 SSH 总时长；与服务并行运行，不等待启停锁。
    """
    return (
        _variables(package_id)
        + "\nlaunch="
        + shlex.quote(_launch(profile, mode="probe"))
        + r"""
cd -- "$package"
# 探测与服务共用环境但不共用输出；保留全部协议行供平台拒绝重复结果。
env -i HOME="$HOME" USER="$USER" LANG=C.UTF-8 PATH=/usr/bin:/bin \
    bash -c "$launch" -- "$config" 2>"$root/log/probe.log" | \
    grep -E '^RDP_VIZ_(PROBE|ERROR) '
"""
    )


def stop() -> str:
    """停止仅按专用 pidfile 和命令行确认的进程组。"""
    return _common() + _resource("_preview_stop.sh")


def _launch(profile: RobotProfile, *, mode: Literal["service", "self-test", "probe"]) -> str:
    """先建立专用 ROS 输出路径再 source，最后 exec 保持 setsid 组长身份。"""
    join = profile.ros.join
    if join is None:
        raise DefectError()
    return "\n".join(
        (
            'export ROS_HOME="$HOME/rdp_viz/ros_home" ROS_LOG_DIR="$HOME/rdp_viz/log/ros"',
            "export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1",
            "source " + shlex.quote(join.setup_script) + " || exit 1",
            "# ROS setup 可能重设 PYTHONPATH，必须在 source 之后加入 SDK 并保留 ROS 路径。",
            'export PYTHONPATH="$HOME/rdp_viz/site${PYTHONPATH:+:$PYTHONPATH}"',
            'export FASTRTPS_DEFAULT_PROFILES_FILE="$HOME/rdp_viz/fastdds_local.xml"',
            "export ROS_LOCALHOST_ONLY=" + shlex.quote(str(int(join.localhost_only))),
            "unset ROS_DOMAIN_ID"
            if profile.ros.domain_id is None
            else "export ROS_DOMAIN_ID=" + shlex.quote(str(profile.ros.domain_id)),
            "exec python3 -m viz_relay "
            + ("" if mode == "service" else f"--{mode} ")
            + '--config "$1"',
        )
    )


def _upload(destination: str, data: bytes) -> str:
    """二进制以 base64 放入固定边界的 here-document，不经 shell 解释。"""
    return (
        "base64 -d > "
        + destination
        + " <<'RDP_PAYLOAD'\n"
        + base64.encodebytes(data).decode("ascii")
        + "RDP_PAYLOAD\n"
    )


def _variables(package_id: str) -> str:
    """静态目录结构只拼接经引用的包编号和锁定文件名。"""
    return "\n".join(
        (
            "set -e -o pipefail",
            'root="$HOME/rdp_viz"',
            "package_id=" + shlex.quote(package_id),
            "wheel_name=" + shlex.quote(viz_relay.WHEEL_FILENAME),
            "digest=" + shlex.quote(viz_relay.WHEEL_SHA256),
            "sdk_version=" + shlex.quote(viz_relay.SDK_VERSION),
            'wheel="$root/wheels/$wheel_name"',
            'package="$root/relay/$package_id"',
            'config="$package/config.json"',
            "",
        )
    )


def _resource(name: str) -> str:
    """读取随平台发布的静态 bash 片段，不接受请求路径。"""
    return Path(__file__).with_name(name).read_text(encoding="utf-8")


def _common() -> str:
    """共用锁和进程身份逻辑，避免启停两份判断漂移。"""
    return _resource("_preview_common.sh")
