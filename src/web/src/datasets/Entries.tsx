// 数据集链接状态展示（M1.5-06）；只呈现登记指向与历史检查状态，不探测磁盘。
import type { ReactElement } from "react";
import { Table, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import { formatDateTime } from "../time";

const LINK_LABELS: Record<DatasetDetail["links"][number]["status"], string> = {
  unchecked: "未检查",
  available: "正常",
  missing: "链接缺失",
  broken: "断链",
  offline: "存储根离线",
  mismatch: "指向不一致",
  unregistered: "存储根未登记",
};
interface LinksProps {
  /** 所选入口的索引链接，顺序保持服务端 ordinal。 */ links: DatasetDetail["links"];
}
/**
 * 显示链接位置、扫描状态和检查时间。
 * @param props - 所选入口的链接快照。
 * @returns 有界分页表格，离线使用专属标签，不等同于断链。
 * @throws 无。
 * @sideEffects 无；所有路径只作文本展示。
 * @timeSemantics checked_at 是历史扫描时间，不以当前时间代替。
 */
export function DatasetLinks(props: LinksProps): ReactElement {
  return (
    <section aria-label="链接状态">
      <Typography.Title level={4}>链接状态</Typography.Title>
      <Table
        size="small"
        rowKey="ordinal"
        scroll={{ x: "max-content" }}
        dataSource={props.links}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "登记指向", dataIndex: "source_path" },
          {
            title: "存储根",
            dataIndex: "storage_root_name",
            render: (value: string | null) => value ?? "未登记",
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (value: DatasetDetail["links"][number]["status"]) => LINK_LABELS[value],
          },
          {
            title: "检查时间",
            dataIndex: "checked_at",
            render: (value: string | null) => (value ? formatDateTime(value) : "未检查"),
          },
        ]}
      />
    </section>
  );
}
