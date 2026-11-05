// 规范副本的14项信息（11 Q12）；只投影已定义的 fields 结构，不解析 Markdown 中的业务值，第4项显示平台统计快照。
import { useMemo, type ReactElement } from "react";
import { Alert, Table, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import { DatasetFieldSummary } from "./FieldSummary";
import { MarkdownValue } from "./Markdown";
import { exactBytes, formatBytes } from "./formatBytes";
import { formatDateTime } from "../time";

// 原始 JSON 是文本接口，这个局部投影用于渲染，不另定义 HTTP 响应模型。
interface Field {
  number: number;
  name: string;
  value_markdown: string;
}
interface Props {
  /** 按任务入口统计字节和UTC统计时刻；未统计为null。 */ size: DatasetDetail["dataset_size"];
  /** 按任务入口规范副本；null 不可用，不能用格式副本替代。 */ document: DatasetDetail["canonical_information"];
}
/**
 * 按原顺序显示规范副本中的14项说明，第4项使用平台统计值。
 * @param props - 服务端明确标识的规范信息文件，保留它自己的入口身份。
 * @returns 编号、名称和 Markdown 内容；副本缺失或结构非法时明确提示。
 * @throws 无；坏 JSON 不导致详情页崩溃。
 * @sideEffects 无；不从说明中提取数值、不更新快照、不发请求。
 * @timeSemantics 第4项属于最近一次统计作业，时间按浏览器本地时区显示；其他项保留原文。
 */
export function DatasetInformation(props: Props): ReactElement {
  const fields = useMemo(() => readFields(props.document), [props.document]);
  return (
    <section aria-label="14 项数据集信息">
      <DatasetFieldSummary document={props.document} />
      <Typography.Title level={4} className="browser-information-title">
        14 项数据集信息
      </Typography.Title>
      {fields ? (
        <>
          <Typography.Paragraph>
            来自按任务入口规范副本；数据大小由平台自动计算
          </Typography.Paragraph>
          <Table
            scroll={{ x: "max-content" }}
            size="small"
            rowKey="number"
            pagination={false}
            dataSource={fields}
            columns={[
              { title: "编号", dataIndex: "number" },
              { title: "名称", dataIndex: "name" },
              {
                title: "内容",
                dataIndex: "value_markdown",
                render: (value: string, field: Field) =>
                  field.number === 4 && field.name === "数据大小" ? (
                    <Typography.Text title={exactBytes(props.size.size_bytes)}>
                      {props.size.size_bytes === null
                        ? "未统计"
                        : formatBytes(props.size.size_bytes)}
                      {props.size.size_checked_at &&
                        ` · 统计时间：${formatDateTime(props.size.size_checked_at)}`}
                    </Typography.Text>
                  ) : (
                    <MarkdownValue text={value} />
                  ),
              },
            ]}
          />
        </>
      ) : (
        <Alert type="warning" title="规范副本不可用，无法展示14项数据集信息" />
      )}
    </section>
  );
}

// 不跳过坏字段伪装成完整14项；原始文件仍能在下方 JSON 查看器打开。
function readFields(document: Props["document"]): Field[] | null {
  if (!document?.usable || document.content === null) return null;
  try {
    const value: unknown = JSON.parse(document.content);
    if (!isRecord(value) || !Array.isArray(value.fields)) return null;
    const fields: unknown[] = value.fields;
    return fields.every(isField) ? fields : null;
  } catch {
    return null;
  }
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isField(value: unknown): value is Field {
  return (
    isRecord(value) &&
    typeof value.number === "number" &&
    Number.isSafeInteger(value.number) &&
    typeof value.name === "string" &&
    typeof value.value_markdown === "string"
  );
}
