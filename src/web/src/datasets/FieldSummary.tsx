import "./fieldSummary.css";
// M1.5-10 导航层人工信息的查看和就地编辑投影；原文件事实继续由索引参考显示，不从Markdown猜型号。
import type { ReactElement } from "react";
import { Typography } from "antd";
import { useDatasetFilterOptions } from "./queries";
import { classificationScenes, classificationTasks } from "./classificationLabels";
import { INFORMATION_FIELD_ROWS } from "./informationFieldPlacement";
import { InlineField } from "./InlineField";
import type { FieldEditingState } from "./fieldEditingState";
import type { DatasetDetail } from "../api/datasets";

interface Props {
  /** 编辑时仅在此显示标题及缺失第3、5、6、8项的结构化字段后备入口。 */ editing?: FieldEditingState;
  /** 唯一规范副本信息文件，null或不可用时不显示人工值。 */ document: DatasetDetail["canonical_information"];
}
/**
 * 展示保存的导航标题、机器人型号、FPS、数据来源、场景和任务。
 * @param props - 详情本次读取的规范副本，不使用格式副本替代。
 * @returns 结构化人工信息；分类缺字段显示未标注，其余缺字段显示未填写，坏JSON保留由原文查看器诊断。
 * @throws 无；未知扩展字段不导致详情崩溃。
 * @sideEffects 读取分类候选；编辑时只更新共享草稿，不直接写入。
 * @timeSemantics 反映详情读取时刻；写入终态沿用既有缓存失效后重新读取。
 */
export function DatasetFieldSummary(props: Props): ReactElement {
  const vocabulary = useDatasetFilterOptions().data;
  const editing = props.editing;
  const page = editing?.information.data;
  if (editing)
    return (
      <div className="field-summary">
        {page?.fields
          .filter((field) => {
            if (field.path.length !== 1 || field.path[0] === "subtask_notes") return false;
            const rowLabel = INFORMATION_FIELD_ROWS[String(field.path[0])];
            if (rowLabel)
              return !page.fields.some(
                (item) => item.path[0] === "fields" && item.label === rowLabel,
              );
            return field.path[0] === "title";
          })
          .map((field) => (
            <InlineField key={String(field.path[0])} state={editing} data={page} field={field} />
          ))}
      </div>
    );
  if (!props.document?.usable || props.document.content === null) return <></>;
  const data = parse(props.document.content);
  if (!data) return <></>;
  return (
    <section aria-label="导航层结构化信息" className="field-summary">
      <Typography.Title level={5}>导航层人工信息</Typography.Title>
      <dl>
        <dt>标题</dt>
        <dd>{text(data.title)}</dd>
        <dt>机器人型号</dt>
        <dd>{text(data.robot_model)}</dd>
        <dt>FPS</dt>
        <dd>{fpsText(data.fps)}</dd>
        <dt>数据来源</dt>
        <dd>{text(data.data_origin, "未知")}</dd>
        <dt>场景</dt>
        <dd>{classificationScenes(data.scene, vocabulary?.scene_vocabulary)}</dd>
        <dt>任务</dt>
        <dd>{classificationTasks(data.tasks, vocabulary?.task_vocabulary)}</dd>
      </dl>
    </section>
  );
}

function parse(content: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(content);
    return isRecord(value) ? value : null;
  } catch {
    return null;
  }
}
function text(value: unknown, empty = "未填写"): string {
  return typeof value === "string" && value.trim() ? value.trim() : empty;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// 顶层 FPS 必须是正整数，缺失和坏值不能冒充可用筛选值。
function fpsText(value: unknown): string {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? String(value)
    : "未标注";
}
