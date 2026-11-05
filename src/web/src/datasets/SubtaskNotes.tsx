// M1.5-10 子任务记事本就地编辑；只投影规范副本和共享草稿，不读取子任务.json。
import { useEffect, useRef, type ReactElement } from "react";
import type { FieldEditingState } from "./fieldEditingState";
import { InlineField } from "./InlineField";
import { Alert, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import "./subtaskNotes.css";

interface Props {
  /** 已打开的详情编辑会话。 */ editing?: FieldEditingState;
  /** 从子任务链接进入时聚焦输入框。 */ focusInput?: boolean;
  /** 打开详情编辑模式。 */ onEdit: () => void;
  /** 本次详情读取的规范信息文件，不用格式副本替代。 */ document: DatasetDetail["canonical_information"];
  /** 数据集有永久编号时提供现有字段编辑入口。 */ editable: boolean;
}

/**
 * 展示规范副本中的子任务纯文本及字段编辑入口。
 * @param props - 规范信息文件和编辑入口是否可用。
 * @returns 保留换行的子任务分节；缺字段或空串显示未填写，规范副本不可用时提示。
 * @throws 无；JSON 解析失败在分节内显示提示。
 * @sideEffects 编辑链接打开详情编辑模式，字段加载后滚动并聚焦子任务输入。
 * @timeSemantics 反映详情读取时刻；保存后沿用现有查询失效与刷新流程。
 */
export function SubtaskNotes(props: Props): ReactElement {
  const notes = readNotes(props.document);
  const section = useRef<HTMLElement>(null);
  const page = props.editing?.information.data;
  const field = page?.fields.find(
    (entry) => entry.path.length === 1 && entry.path[0] === "subtask_notes",
  );
  useEffect(() => {
    if (props.focusInput && field) {
      section.current?.scrollIntoView({ block: "center" });
      section.current?.querySelector("textarea")?.focus();
    }
  }, [props.focusInput, field]);
  return (
    <section aria-label="子任务" id="dataset-subtask-notes" ref={section}>
      <Typography.Title level={4}>子任务</Typography.Title>
      {props.editing ? (
        page && field ? (
          <InlineField state={props.editing} data={page} field={field} />
        ) : (
          <p>正在读取子任务编辑项…</p>
        )
      ) : notes === null ? (
        <Alert type="warning" title="规范副本不可用，无法展示子任务" />
      ) : (
        <Typography.Paragraph className="subtask-notes-content">
          {notes || "未填写"}
        </Typography.Paragraph>
      )}
      {props.editable && !props.editing && (
        <Typography.Link
          href="#dataset-subtask-notes"
          onClick={(event) => {
            event.preventDefault();
            props.onEdit();
          }}
        >
          编辑子任务
        </Typography.Link>
      )}
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
