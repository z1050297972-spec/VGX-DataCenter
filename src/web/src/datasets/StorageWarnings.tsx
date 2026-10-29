// 数据集离线提示（11 Q4/Q5）：只使用已发布索引的状态，未知状态不推断为离线。
import type { ReactElement } from "react";
import { Alert } from "antd";
import type { DatasetPanel } from "../api/datasets";

const REASONS = {
  not_mounted: "未挂载",
  source_mismatch: "挂载源不符",
  timeout: "访问超时",
} as const;
interface Props {
  /** 最近扫描的存储根快照，保留实际检查时间。 */ roots: DatasetPanel["storage_roots"];
}
/**
 * 在浏览页和一致性面板上方提示离线根。
 * @param props - 索引存储根，不现场探测路径。
 * @returns 离线根的警告与原检查时间；在线或未检查不报离线。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 显示扫描时刻，UTC 仅显示时转换为浏览器本地时间。
 */
export function StorageWarnings(props: Props): ReactElement {
  return (
    <>
      {props.roots
        .filter((root) => root.online === false)
        .map((root) => (
          <Alert
            key={root.name}
            type="warning"
            showIcon
            title={`存储根 ${root.name} 离线：${root.reason ? REASONS[root.reason] : "原因未知"}；其下磁盘检查已跳过`}
            description={`检查时间：${root.checked_at ? new Date(root.checked_at).toLocaleString() : "未知"}`}
          />
        ))}
    </>
  );
}
