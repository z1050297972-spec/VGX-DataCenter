# M5 演练第 1 步：只写 ~/rdp_viz/。wheel 已经由上一条命令传到 ~/rdp_viz/wheels/.incoming。
set -euo pipefail
R=$HOME/rdp_viz
cd "$R"
# 机器人侧再核对一次 sha256（平台已固定），对上才改成正式文件名。
echo "a36b76e1f57f9e2889732922f7af473c8dd4d2da740efc1cbc5e2acaa6ae7d29  wheels/.incoming" | sha256sum -c -
mv wheels/.incoming wheels/foxglove_sdk-0.30.3-cp310-abi3-manylinux_2_28_aarch64.whl
# 机器人没有 ensurepip，不建 venv；wheel 只有 foxglove/ 和 dist-info，解压到 site/ 即为安装（等同 pip --target）。
rm -rf site.tmp && mkdir site.tmp && python3 -m zipfile -e wheels/foxglove_sdk-0.30.3-cp310-abi3-manylinux_2_28_aarch64.whl site.tmp && rm -rf site && mv site.tmp site
ls site
# 程序和配置：已由 tar 解到 relay/de2a162e085b094e/
ls relay/de2a162e085b094e relay/de2a162e085b094e/viz_relay
mkdir -p log/ros ros_home run
