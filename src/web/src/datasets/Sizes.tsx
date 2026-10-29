// 大小共享部件（11 Q10、M1-04）；统计值与10-12记录并排，离线仍保留原统计时间。
import type { ReactElement } from "react";
import { Card } from "antd";
import type { DatasetDetail } from "../api/datasets";
interface Props {
  /** 按任务入口的数据集大小快照，单位字节。 */ size: DatasetDetail["dataset_size"];
}
/**
 * 分开展示统计值、统计时间和10-12记录值。
 * @param props - 接口提供的大小快照；null明确表示未知或未统计。
 * @returns 按任务入口口径的大小卡片，不叠加格式副本。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 统计时间属于最后一次统计作业，转换为浏览器本地时间显示。
 */
export function DatasetSizeSummary(props: Props): ReactElement {
  const size = props.size;
  return (
    <Card title="数据集大小（按任务入口）">
      <p>
        统计大小：{size.size_bytes === null ? "未统计" : `${size.size_bytes.toLocaleString()} B`}
      </p>
      <p>
        统计时间：
        {size.size_checked_at ? new Date(size.size_checked_at).toLocaleString() : "未统计"}
      </p>
      <p>
        10-12 记录：
        {size.recorded_size_bytes === null
          ? "未知"
          : `${size.recorded_size_bytes.toLocaleString()} B`}
      </p>
    </Card>
  );
}
