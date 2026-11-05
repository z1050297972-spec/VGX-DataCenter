// M1.5-08 子任务记事本的只读投影；只读规范副本，不读取或解析子任务.json。
import type { ReactElement } from "react";
import { Alert, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import "./subtaskNotes.css";

interface Props {
  /** 本次详情读取的规范信息文件，不用格式副本替代。 */ document: DatasetDetail["canonical_information"];
  /** 数据集有永久编号时提供现有字段编辑入口。 */ editable: boolean;
}

/**
 * 展示规范副本中的子任务纯文本及字段编辑入口。
 * @param props - 规范信息文件和编辑入口是否可用。
 * @returns 保留换行的子任务分节；缺字段或空串显示未填写，规范副本不可用时提示。
 * @throws 无；JSON 解析失败在分节内显示提示。
 * @sideEffects 无；编辑链接只跳到页面已有的字段编辑入口。
 * @timeSemantics 反映详情读取时刻；保存后沿用现有查询失效与刷新流程。
 */
export function SubtaskNotes(props: Props): ReactElement {
  const notes = readNotes(props.document);
  return (
    <section aria-label="子任务">
      <Typography.Title level={4}>子任务</Typography.Title>
      {notes === null ? (
        <Alert type="warning" title="规范副本不可用，无法展示子任务" />
      ) : (
        <Typography.Paragraph className="subtask-notes-content">
          {notes || "未填写"}
        </Typography.Paragraph>
      )}
      {props.editable && <Typography.Link href="#dataset-field-editor">编辑子任务</Typography.Link>}
    </section>
  );
}

// 缺字段是旧文件的合法空值；不可读的规范副本不能伪装成未填写。
function readNotes(document: Props["document"]): string | null {
  if (!document?.usable || document.content === null) return null;
  try {
    const value: unknown = JSON.parse(document.content);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
    const notes: unknown = "subtask_notes" in value ? value.subtask_notes : "";
    return typeof notes === "string" ? notes : null;
  } catch {
    return null;
  }
}
