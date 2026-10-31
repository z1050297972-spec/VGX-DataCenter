// M1.5-02 分页表单投影；只把编辑值交回会话，不发请求、不解析原文件。
import type { ReactElement } from "react";
import { Alert, Button, Input, Select } from "antd";
import { useDatasetFilterOptions } from "./queries";
import type { DatasetFilters } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import type { EditablePage } from "../api/fieldEditing";
import type { FieldChange, FieldEditingState } from "./fieldEditingState";

type Field = EditablePage["fields"][number];
type Value = FieldChange["value"];
interface InputProps {
  /** 服务端白名单投影中的字段。 */ field: Field;
  /** 当前局部草稿值，未改时为原值。 */ value: Value;
  /** 服务端分类词表；未加载时分类控件不可改。 */ vocabulary?: DatasetFilters;
  /** 提交中或基线过期时禁用。 */ disabled: boolean;
  /** 将新值交给会话，不直接提交。 */ onChange: (value: Value) => void;
}
/**
 * 展示当前页字段、原型号参考和分页控制。
 * @param props - 当前页与会话状态；不会把其他页全文带入DOM。
 * @param props.state - 已授权编辑会话和本次页数据。
 * @param props.data - 服务端规范副本页，不使用格式入口原文替代。
 * @returns 可换行的文本、场景单选、字符串多选和翻页按钮。
 * @throws 无；类型和范围由服务端白名单再校验。
 * @sideEffects 只触发会话回调；翻页发起由会话管理的GET。
 * @timeSemantics 保留跨页草稿，不自行刷新哈希或预览时刻。
 */
export function FieldInputs(props: {
  /** 编辑会话。 */ state: FieldEditingState;
  /** 当前页。 */ data: EditablePage;
}): ReactElement {
  const { state, data } = props;
  const vocabulary = useDatasetFilterOptions();
  return (
    <>
      <p>
        规范副本：{data.entry_path} · 共 {data.total} 条
      </p>
      {state.document === "数据集信息.json" && (
        <ModelReference data={data} changes={state.changes} />
      )}
      {vocabulary.error && <DiagnosticCard failure={toFailureView(vocabulary.error)} />}
      {data.fields.map((field) => (
        <FieldInput
          key={JSON.stringify(field.path)}
          field={field}
          vocabulary={vocabulary.data}
          value={state.changes[JSON.stringify([state.document, field.path])]?.value ?? field.value}
          disabled={state.busy || state.stale}
          onChange={(value) => {
            state.update(field, value);
          }}
        />
      ))}
      {state.document !== "数据集信息.json" && (
        <div className="field-actions">
          <Button
            aria-label="编辑上一页"
            disabled={state.busy || state.offset === 0}
            onClick={() => {
              state.selectOffset(Math.max(0, state.offset - data.limit));
            }}
          >
            上一页
          </Button>
          <Button
            aria-label="编辑下一页"
            disabled={state.busy || state.offset + data.limit >= data.total}
            onClick={() => {
              state.selectOffset(state.offset + data.limit);
            }}
          >
            下一页
          </Button>
        </div>
      )}
    </>
  );
}

function FieldInput(props: InputProps): ReactElement {
  const { field, value, disabled, onChange } = props;
  if (field.path.length === 1 && (field.path[0] === "scene" || field.path[0] === "tasks"))
    return <ClassificationInput {...props} />;
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
          autoSize={{ minRows: 1, maxRows: 8 }}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </label>
  );
}
// 只限制新选择；原有词表外值作为已选项保留，编辑其他字段不会清掉人工历史值。
function ClassificationInput({
  field,
  value,
  disabled,
  onChange,
  vocabulary,
}: InputProps): ReactElement {
  const multiple = field.path[0] === "tasks";
  const selected = multiple ? list(value) : text(value) ? [text(value)] : [];
  const terms = multiple ? vocabulary?.task_vocabulary : vocabulary?.scene_vocabulary;
  const options = classificationOptions(terms, selected);
  return (
    <label className="field-input">
      <span>{field.label}</span>
      <Select<string | string[]>
        mode={multiple ? "multiple" : undefined}
        allowClear
        virtual={false}
        aria-label={field.label}
        placeholder={multiple ? "选择任务（可多选）" : "选择场景"}
        value={multiple ? selected : selected[0]}
        disabled={disabled || !vocabulary}
        loading={!vocabulary}
        getPopupContainer={popupContainer}
        options={options}
        onChange={(next: string | string[] | undefined) => {
          onChange(next ?? (multiple ? [] : ""));
        }}
      />
    </label>
  );
}
// 新值必须来自服务端，已存的未知值仍留在选中项里供显式清空。
function classificationOptions(
  terms: DatasetFilters["scene_vocabulary"] | undefined,
  selected: string[],
) {
  return [
    ...(terms?.map((term) => ({ value: term.code, label: term.name })) ?? []),
    ...selected
      .filter((code) => !terms?.some((term) => term.code === code))
      .map((code) => ({ value: code, label: `${code}（不在词表）`, disabled: true })),
  ];
}
function ModelReference({
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
    !data.original_robot_types.includes(model);
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
  return typeof value === "string" ? [] : value;
}
