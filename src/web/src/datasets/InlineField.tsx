// M1.5-10 单个位置的草稿投影；复用第09张输入控件，不再渲染整页重复字段列表。
import type { ReactElement } from "react";
import type { EditablePage } from "../api/fieldEditing";
import type { FieldEditingState } from "./fieldEditingState";
import { INFORMATION_FIELD_ROWS } from "./informationFieldPlacement";
import { FieldInput, ModelReference } from "./FieldInputs";
import { useDatasetFilterOptions } from "./queries";

interface Props {
  /** 当前编辑会话。 */ state: FieldEditingState;
  /** 字段所属页，用于取得准确的文档与哈希。 */ data: EditablePage;
  /** 原始字段投影，路径不因布局变化而改写。 */ field: EditablePage["fields"][number];
}
/**
 * 在原位置编辑一个字段，第3、5、6、8项附带结构化输入。
 * @param props - 会话、所属页和字段投影。
 * @returns 单项输入；型号参考随第5项或独立型号输入展示。
 * @throws 无。
 * @sideEffects 分类查询复用现有缓存；输入只修改会话草稿。
 * @timeSemantics 禁止在提交中或基线过期后编辑。
 */
export function InlineField(props: Props): ReactElement {
  const { state, data, field } = props;
  const vocabulary = useDatasetFilterOptions().data;
  const names =
    field.path[0] === "fields"
      ? Object.keys(INFORMATION_FIELD_ROWS).filter(
          (key) => INFORMATION_FIELD_ROWS[key] === field.label,
        )
      : [];
  return (
    <div className="field-inline">
      {field.path[0] === "robot_model" && <ModelReference data={data} changes={state.changes} />}
      {field.path[0] === "fps" && (
        <p>原文件 fps（索引参考）：{data.original_fps.join("、") || "未知"}</p>
      )}
      {data.fields
        .filter((entry) => entry.path.length === 1 && names.includes(String(entry.path[0])))
        .map((entry) => (
          <InlineField key={String(entry.path[0])} state={state} data={data} field={entry} />
        ))}
      <FieldInput
        field={field}
        value={(state.changes[JSON.stringify([data.document, field.path])] ?? field).value}
        vocabulary={vocabulary}
        disabled={state.busy || state.stale}
        onOrigin={(origin) => {
          const originField = data.fields.find(
            (entry) => entry.path.length === 1 && entry.path[0] === "data_origin",
          );
          if (!originField) return;
          const current = (
            state.changes[JSON.stringify([data.document, originField.path])] ?? originField
          ).value;
          // 只补齐当前草稿的未知来源，不能覆盖用户已填或刚刚手动改过的来源。
          if (current === null || current === "" || current === "未知")
            state.update(data, originField, origin);
        }}
        onChange={(value) => {
          state.update(data, field, value);
        }}
      />
    </div>
  );
}
