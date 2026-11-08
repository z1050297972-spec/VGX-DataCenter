// M1.5-09/10 共用字段输入；供新建与详情就地编辑使用，不维护独立编辑器。
import { CollectionInput } from "./CollectionInput";
import { useState, type ReactElement } from "react";
import { Alert, AutoComplete, Input, InputNumber, Select } from "antd";
import type { DatasetFilters } from "../api/datasets";
import type { EditablePage } from "../api/fieldEditing";
import type { FieldChange } from "./fieldEditingState";

type Field = EditablePage["fields"][number];
type Value = FieldChange["value"];
interface InputProps {
  /** 服务端白名单投影中的字段。 */ field: Field;
  /** 当前局部草稿值，未改时为原值。 */ value: Value;
  /** 服务端分类词表；未加载时分类控件不可改。 */ vocabulary?: DatasetFilters;
  /** 提交中或基线过期时禁用。 */ disabled: boolean;
  /** 方式选择后由会话决定是否补齐来源。 */ onOrigin?: (origin: string) => void;
  /** 将新值交给会话，不直接提交。 */ onChange: (value: Value) => void;
}
/**
 * 为编辑器与新建表单提供同一套文本、型号和分类输入。
 * @param props - 字段投影、草稿、词表、禁用状态与回调。
 * @returns 文本框或可选取和输入的分类控件。
 * @throws 无；服务端负责最终校验。
 * @sideEffects 仅触发 onChange，不发送请求。
 * @timeSemantics 同步更新草稿，无轮询。
 */
export function FieldInput(props: InputProps): ReactElement {
  const { field, value, disabled, onChange } = props;
  if (field.path[0] === "collection")
    return (
      <CollectionInput
        value={collectionValue(value)}
        original={collectionValue(field.value)}
        disabled={disabled}
        onChange={onChange}
        onOrigin={props.onOrigin}
      />
    );
  if (field.path.length === 1 && (field.path[0] === "scene" || field.path[0] === "tasks"))
    return <ClassificationInput {...props} />;
  if (
    field.path.length === 1 &&
    ["robot_model", "fps", "data_origin"].includes(String(field.path[0]))
  )
    return <InformationInput {...props} />;
  return (
    <label className="field-input">
      <span>{field.label}</span>
      {field.multiple ? (
        <Select<string[]>
          mode="tags"
          aria-label={field.label}
          value={list(value)}
          disabled={disabled}
          getPopupContainer={popupContainer}
          onChange={onChange}
          options={list(value).map((value) => ({ value, label: value }))}
        />
      ) : (
        <Input.TextArea
          aria-label={field.label}
          value={text(value)}
          disabled={disabled}
          autoSize={field.path[0] === "subtask_notes" ? { minRows: 6 } : { minRows: 1, maxRows: 8 }}
          placeholder={
            field.path[0] === "subtask_notes" ? "每行一个子任务，例如：抓取杯子" : undefined
          }
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </label>
  );
}
// 来源使用工单的六个中文值；筛选参数的英文编码不能用于字段写入。
const ORIGINS = ["真机采集", "UMI 采集", "ego 采集", "仿真生成", "开源下载", "未知"];
function InformationInput({
  field,
  value,
  disabled,
  onChange,
  vocabulary,
}: InputProps): ReactElement {
  return (
    <label className="field-input">
      <span>{field.label}</span>
      {field.path[0] === "robot_model" ? (
        <AutoComplete
          aria-label={field.label}
          value={text(value)}
          disabled={disabled}
          options={vocabulary?.robot_models
            .filter((item) => item.value !== "unlabeled")
            .map((item) => ({ value: item.value }))}
          showSearch={{
            filterOption: (input, option) =>
              !!option?.value.toLowerCase().includes(input.toLowerCase()),
          }}
          getPopupContainer={popupContainer}
          onChange={(next: string) => {
            onChange(next);
          }}
          onBlur={() => {
            onChange(text(value).trim());
          }}
          placeholder="选择已有型号或输入新型号"
        />
      ) : field.path[0] === "fps" ? (
        <InputNumber
          aria-label={field.label}
          value={typeof value === "number" ? value : null}
          min={1}
          step={1}
          disabled={disabled}
          onChange={(next) => {
            onChange(next ?? "");
          }}
        />
      ) : (
        <Select
          aria-label={field.label}
          value={text(value) || "未知"}
          disabled={disabled}
          virtual={false}
          getPopupContainer={popupContainer}
          options={ORIGINS.map((origin) => ({ value: origin, label: origin }))}
          onChange={(next: string) => {
            onChange(next);
          }}
        />
      )}
    </label>
  );
}
// 同一组设置决定候选来源与交互形态，避免场景与任务的词表配置分散。
const classificationSettings = {
  scene: {
    terms: "scene_vocabulary",
    candidates: "scenes",
    placeholder: "选择或输入场景（可多选，回车确认）",
  },
  tasks: {
    terms: "task_vocabulary",
    candidates: "tasks",
    placeholder: "选择或输入任务（可多选，回车确认）",
  },
} as const;

// 场景和任务均使用 tags；推荐词表和平台已有自定义值共用服务端候选。
function ClassificationInput({
  field,
  value,
  disabled,
  onChange,
  vocabulary,
}: InputProps): ReactElement {
  const [search, setSearch] = useState("");
  const selected = typeof value === "string" ? [value].filter(Boolean) : list(value);
  const settings = classificationSettings[field.path[0] === "tasks" ? "tasks" : "scene"];
  const terms = vocabulary?.[settings.terms];
  const candidates = vocabulary?.[settings.candidates];
  const options = classificationOptions(terms, candidates, selected);
  return (
    <label className="field-input">
      <span>{field.label}</span>
      <Select<string[], { value: string; label: string }>
        mode="tags"
        showSearch={{
          searchValue: search,
          onSearch: setSearch,
          filterOption: (input, option) =>
            !!option &&
            (option.label.includes(input.trim()) || option.value.includes(input.trim())),
        }}
        allowClear
        virtual={false}
        aria-label={field.label}
        placeholder={settings.placeholder}
        value={selected}
        disabled={disabled || !vocabulary}
        loading={!vocabulary}
        getPopupContainer={popupContainer}
        options={options}
        onChange={(next: string[]) => {
          onChange(normalizeClassification(next));
          setSearch("");
        }}
      />
    </label>
  );
}
// 按词表、平台已有值、当前草稿的顺序去重，确保词表中文名优先；筛选哨兵不是分类候选。
function classificationOptions(
  terms: DatasetFilters["scene_vocabulary"] | undefined,
  candidates: DatasetFilters["scenes"] | undefined,
  selected: string[],
) {
  const options = new Map<string, { value: string; label: string }>();
  for (const term of terms ?? []) options.set(term.code, { value: term.code, label: term.name });
  for (const value of [...(candidates?.map((item) => item.value) ?? []), ...selected]) {
    if (value !== "unlabeled" && !options.has(value)) options.set(value, { value, label: value });
  }
  return [...options.values()];
}
// 分类输入统一去首尾空格和去重，其他合法性由服务端契约判断。
function normalizeClassification(next: string[]): string[] {
  return [...new Set(next.map((item) => item.trim()).filter(Boolean))];
}
/**
 * 显示导航型号与原文件型号的参考差异。
 * @param props - 当前信息页与局部改动。
 * @param props.data - editable-fields 返回的规范信息页。
 * @param props.changes - 跨文档草稿，按文档与路径索引。
 * @returns 原文件型号参考及差异提示。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 反映该次编辑页读取时刻，不重新读取原文件。
 */
export function ModelReference({
  data,
  changes,
}: {
  data: EditablePage;
  changes: Record<string, FieldChange>;
}): ReactElement {
  const model =
    changes[JSON.stringify([data.document, ["robot_model"]])]?.value ??
    data.fields.find((field) => field.path[0] === "robot_model")?.value;
  const differs =
    typeof model === "string" &&
    model !== "" &&
    data.original_robot_types.length > 0 &&
    !data.original_robot_types.some(
      (original) => original.trim().toLowerCase() === model.trim().toLowerCase(),
    );
  return (
    <>
      <p>原文件 robot_type（索引参考）：{data.original_robot_types.join("、") || "未知"}</p>
      {differs && <Alert type="info" title="导航型号与原文件型号不同" />}
    </>
  );
}
function popupContainer(trigger: HTMLElement): HTMLElement {
  return trigger.parentElement ?? trigger;
}
function text(value: Value): string {
  return typeof value === "string" ? value : "";
}
function list(value: Value): string[] {
  return Array.isArray(value) ? value : [];
}

// collection 是唯一对象字段；旧文本控件仍只处理原有标量和数组。
function collectionValue(value: Value) {
  return typeof value === "object" && !Array.isArray(value) ? value : null;
}
