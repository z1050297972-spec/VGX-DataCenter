#!/usr/bin/env bash
# M5 演练：沿用平台的钥匙和 known_hosts（与第 02 张的 ssh 参数一致），连 R1 Lite（登记 robot_id=1）。
K=$HOME/.local/share/rdp/ssh
exec ssh -F /dev/null -i "$K/id_ed25519" -o BatchMode=yes -o ConnectTimeout=5 \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$K/known_hosts" -o GlobalKnownHostsFile=/dev/null \
  -o IdentitiesOnly=yes -o IdentityAgent=none -o PreferredAuthentications=publickey \
  -p 22 -l nvidia -- 192.168.0.229 "$@"
