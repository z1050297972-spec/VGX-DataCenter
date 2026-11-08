// M3-03 采集信息详情与就地编辑入口；名称使用响应投影，不从导航 JSON 猜登记名称。
import type { ReactElement } from "react";
import { Link } from "@tanstack/react-router";
import { Descriptions, Space, Typography } from "antd";
import type { CollectionDetail } from "../api/collection";
import type { DatasetDetail } from "../api/datasets";
import type { FieldEditingState } from "./fieldEditingState";
import { COLLECTION_STATUS_LABELS } from "./collectionLabels";
import { InlineField } from "./InlineField";

interface Props {
  /** 当前详情响应；缺省或 null 表示没有采集信息。 */ collection: DatasetDetail["collection"];
  /** 可选的现有字段编辑会话。 */ editing?: FieldEditingState;
}
/**
 * 显示或就地编辑数据集的采集信息。
 * @param props - 详情投影与共享编辑会话。
 * @returns 状态、方式、用途与机器人链接；空值显示无采集信息。
 * @throws 无。
 * @sideEffects 编辑复用 InlineField 草稿，机器人链接进入登记页。
 * @timeSemantics 展示本次详情快照，编辑以编辑页哈希为准。
 */
export function CollectionInformation(props: Props): ReactElement {
  const { collection, editing } = props;
  const page = editing?.information.data;
  const field = page?.fields.find(
    (item) => item.path.length === 1 && item.path[0] === "collection",
  );
  return (
    <section aria-label="采集信息" className="browser-detail-section">
      <Typography.Title level={4}>采集信息</Typography.Title>
      {editing ? (
        page && field ? (
          <InlineField state={editing} data={page} field={field} />
        ) : (
          <p>正在读取采集信息编辑项…</p>
        )
      ) : collection ? (
        <CollectionReadOnly collection={collection} />
      ) : (
        <p>无（不是平台采集的数据集）</p>
      )}
    </section>
  );
}
// 停用和编号缺失都是可见状态，不能把旧引用显示成未填写。
function referenceName(id: number, name: string | null, status: string): string {
  return `${name ?? `未知编号 ${String(id)}`}${status === "retired" ? "（停用）" : ""}`;
}

// 只读投影与编辑页加载状态分开，避免混用两次读取的值。
function CollectionReadOnly({ collection }: { collection: CollectionDetail }): ReactElement {
  return (
    <Descriptions
      column={1}
      items={[
        { key: "status", label: "状态", children: COLLECTION_STATUS_LABELS[collection.status] },
        {
          key: "method",
          label: "采集方式",
          children: collection.method
            ? `${referenceName(collection.method.id, collection.method.name, collection.method.status)}${collection.method.data_origin ? `（${collection.method.data_origin}）` : ""}`
            : "未填写",
        },
        {
          key: "purpose",
          label: "用途",
          children: collection.purpose
            ? referenceName(
                collection.purpose.id,
                collection.purpose.name,
                collection.purpose.status,
              )
            : "未填写",
        },
        {
          key: "robots",
          label: "机器人",
          children: collection.robots.length ? (
            <Space wrap>
              {collection.robots.map((robot) => (
                <Link key={robot.robot_id} to="/robots">
                  {referenceName(robot.robot_id, robot.name, robot.status)}
                </Link>
              ))}
            </Space>
          ) : (
            "未填写"
          ),
        },
      ]}
    />
  );
}
