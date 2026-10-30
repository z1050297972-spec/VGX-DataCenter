// 链接与数据块的共享展示（M1-04）；原始路径、推导路径及历史检查状态严格区分，不探测磁盘。
import type { ReactElement } from "react";
import { Table, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";

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
            title: "观察到的指向",
            dataIndex: "observed_target",
            render: (value: string | null) => value ?? "未检查",
          },
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
            render: (value: string | null) => (value ? new Date(value).toLocaleString() : "未检查"),
          },
        ]}
      />
    </section>
  );
}

interface SourcesProps {
  /** 当前原始路径文件的数据块投影，不是索引重建的原文。 */ sources: DatasetDetail["sources"];
}
/**
 * 按页显示数据块身份、格式及历史核验结果。
 * @param props - 详情接口的数据块，中文标签由后端按手册提供。
 * @returns 首次路径、当前路径和推导入口分开的表格，未知核验原值仍显示。
 * @throws 无。
 * @sideEffects 无；不会打开或检查任何路径。
 * @timeSemantics validation_status 是写导航层时的历史核验结果，不能当作本次扫描结论。
 */
export function DatasetSources(props: SourcesProps): ReactElement {
  return (
    <section aria-label="数据块">
      <Typography.Title level={4}>数据块</Typography.Title>
      <p>核验状态为写入导航层时的历史记录。</p>
      <Table
        size="small"
        rowKey="ordinal"
        dataSource={props.sources}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        scroll={{ x: "max-content" }}
        columns={[
          { title: "数据块编号", dataIndex: "source_id" },
          { title: "首次登记路径", dataIndex: "original_path" },
          { title: "当前路径", dataIndex: "direct_path" },
          { title: "推导入口", dataIndex: "derived_entry_path" },
          { title: "格式", dataIndex: "format", render: (value: string | null) => value ?? "未知" },
          {
            title: "格式版本",
            dataIndex: "version",
            render: (value: string | null) => value ?? "无",
          },
          {
            title: "核验状态",
            key: "validation",
            render: (_, source) => (
              <>
                <span>{source.validation_status_label}</span>
                {source.validation_status && <code>{source.validation_status}</code>}
              </>
            ),
          },
        ]}
      />
    </section>
  );
}
