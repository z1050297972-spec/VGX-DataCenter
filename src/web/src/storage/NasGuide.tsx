// 存储根页面的静态接入说明：复用 antd 折叠展示，不执行命令或修改平台配置。
import type { ReactElement } from "react";
import { Collapse, Typography } from "antd";
import "./storage.css";

/**
 * 展示默认收起的 NAS 接入流程，供成员与管理员查阅。
 * @returns 包含 NAS 共享、工作站挂载和平台登记步骤的折叠面板。
 * @throws 无。
 * @sideEffects 无；展开只改变本地展示状态。
 * @timeSemantics 静态说明，以 2026-11-11 的接入操作为例，不请求或轮询。
 */
export function NasGuide(): ReactElement {
  return (
    <Collapse
      className="storage-nas-guide"
      items={[
        {
          key: "nas-guide",
          label: "NAS 接入流程",
          children: (
            <>
              <Typography.Paragraph>
                平台只认挂到工作站上的 ext4 盘或 NFS 共享；NAS 厂商的客户端（如“绿联云”）和 SMB
                共享不算。NAS 自身的文件系统（如 btrfs）不影响。下面以 2026-11-11 接入的平台区
                nas_platform 为例。
              </Typography.Paragraph>
              <Typography.Title level={4}>
                第 1 步　NAS 端：开 NFS 共享（在 NAS 管理页面操作）
              </Typography.Title>
              <ul>
                <li>
                  新建平台专用的共享文件夹（本例 rdp-dataset，导出路径 /volume1/rdp-dataset）。
                </li>
                <li>开启 NFS 服务。</li>
                <li>
                  给该共享文件夹加 NFS 权限：客户端填工作站所在网段（本例
                  192.168.0.0/24），读写，squash 选“映射所有用户为 admin”，否则平台用户写不进去。
                </li>
              </ul>
              <Typography.Title level={4}>
                第 2 步　工作站：挂载（需要 sudo，在终端里做）
              </Typography.Title>
              <pre className="storage-nas-code">{`sudo apt install nfs-common
showmount -e 192.168.0.247
sudo mkdir -p /mnt/nas_platform`}</pre>
              <Typography.Paragraph>在 /etc/fstab 末尾加一行（先备份）：</Typography.Paragraph>
              <pre className="storage-nas-code">
                {
                  "192.168.0.247:/volume1/rdp-dataset  /mnt/nas_platform  nfs  rw,vers=3,noatime,hard,_netdev,nofail  0  0"
                }
              </pre>
              <pre className="storage-nas-code">{`sudo systemctl daemon-reload
sudo mount /mnt/nas_platform
findmnt -no SOURCE,FSTYPE,OPTIONS /mnt/nas_platform`}</pre>
              <Typography.Paragraph>选项说明：</Typography.Paragraph>
              <ul>
                <li>vers=3：用 NFSv3。这台 NAS 用 nfs4 挂会报 “No such file or directory”。</li>
                <li>hard：网络断了就等恢复，不让写入悄悄出错。</li>
                <li>_netdev：等网络起来再挂。</li>
                <li>nofail：NAS 不在线时不卡开机。</li>
                <li>noatime：读文件时不更新访问时间。</li>
              </ul>
              <Typography.Paragraph>
                注意：不要加 x-systemd.automount（会多一层
                autofs，平台判为叠加挂载）；挂载点不能放在别的存储根或 /mnt/datasets 里面。
              </Typography.Paragraph>
              <Typography.Title level={4}>第 3 步　平台：登记存储根</Typography.Title>
              <Typography.Paragraph>
                存储根不能在网页上登记。在 ~/.config/rdp/config.toml 加一段（先备份）：
              </Typography.Paragraph>
              <pre className="storage-nas-code">{`[[storage_roots]]
name = "nas_platform"
path = "/mnt/nas_platform"
nfs_export = "192.168.0.247:/volume1/rdp-dataset"
writable = true`}</pre>
              <ul>
                <li>
                  nfs_export 要和 findmnt
                  显示的来源逐字一致，末尾不带斜杠；平台靠它确认挂的是登记的那个共享，NAS
                  没挂上时不会把数据写进本地空目录。
                </li>
                <li>writable = true 表示允许平台写入（平台区）；只读数据不写这一项。</li>
                <li>改完重启：</li>
              </ul>
              <pre className="storage-nas-code">systemctl --user restart rdp-web rdp-worker</pre>
              <Typography.Paragraph>
                然后回到本页点“重新检查”，应显示在线、可写。
              </Typography.Paragraph>
              <Typography.Title level={4}>以后要改时</Typography.Title>
              <ul>
                <li>
                  NAS 换了地址：/etc/fstab 那一行和 nfs_export
                  都改成新地址，重新挂载并重启两个服务。建议在路由器里给 NAS 绑定固定地址。
                </li>
                <li>再加一个共享文件夹：重复三步，换一个挂载点和名字。</li>
              </ul>
            </>
          ),
        },
      ]}
    />
  );
}
