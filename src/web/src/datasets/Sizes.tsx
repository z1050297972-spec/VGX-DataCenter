// 大小共享部件（11 Q10、M1-04）；只显示按格式统计值，离线仍保留原统计时间。
import type { ReactElement, ReactNode } from "react";
import { Flex, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import { exactBytes, formatBytes } from "./formatBytes";
import { formatDateTime } from "../time";
interface Props {
  /** 按任务入口的数据集大小快照，单位字节。 */ size: DatasetDetail["dataset_size"];
  /** 与大小相关的操作入口。 */ actions: ReactNode;
}
/**
 * 展示按格式统计值、口径和统计时间。
 * @param props - 接口提供的大小快照；null明确表示未知或未统计。
 * @returns 按任务入口口径的大小分节，不叠加格式副本。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 统计时间属于最后一次统计作业，转换为浏览器本地时间显示。
 */
export function DatasetSizeSummary(props: Props): ReactElement {
  const size = props.size;
  return (
    <section>
      <Flex
        justify="space-between"
        align="center"
        gap="middle"
        wrap
        className="browser-size-heading"
      >
        <Typography.Title level={5}>数据集大小（按任务入口）</Typography.Title>
        <Flex gap="small" wrap className="browser-size-actions">
          {props.actions}
        </Flex>
      </Flex>
      <Typography.Paragraph title={exactBytes(size.size_bytes)}>
        统计大小：{size.size_bytes === null ? "未统计" : formatBytes(size.size_bytes)}
        {" · LeRobot 只计 parquet、mp4 和 meta；其他格式计全部大小"}
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        <ul aria-label="大小统计说明">
          <li>
            每天一次：本地时间凌晨 03:00 统计全部数据集。如果那时平台没在运行（例如关机或 worker
            没启动），下次启动时补统计一次，当天只补这一次。
          </li>
          <li>写导航层之后：只重新统计这次写入涉及的数据集（例如编辑字段之后）。</li>
          <li>手动：点“统计大小”立即统计。</li>
        </ul>
      </Typography.Paragraph>
      <Typography.Paragraph>
        统计时间：
        {size.size_checked_at ? formatDateTime(size.size_checked_at) : "未统计"}
      </Typography.Paragraph>
    </section>
  );
}
