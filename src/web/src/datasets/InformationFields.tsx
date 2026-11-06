// M1.5-09 新建信息表单；复用编辑器控件与分类词表，只组装工单约定的请求，不生成导航文件。
import type { ReactElement } from "react";
import { Card } from "antd";
import type { DatasetInformationInput } from "../api/datasetCreation";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { FieldInput } from "./FieldInputs";
import { useDatasetFilterOptions } from "./queries";

// 名称和编号来自导航层手册第3节；第4项没有输入，避免覆盖平台统计值。
const ITEMS = [
  [1, "数据集标识"],
  [2, "地址"],
  [3, "类型与组成"],
  [5, "采集机器人型号"],
  [6, "任务与场景"],
  [7, "数据格式"],
  [8, "FPS"],
  [9, "相机配置"],
  [10, "状态维度"],
  [11, "动作维度"],
  [12, "动作控制方式及单位"],
  [13, "轨迹／帧数"],
  [14, "信息来源与核验日期"],
] as const;
const EMPTY: DatasetInformationInput = { fields: [], robot_model: "", scene: [], tasks: [] };
interface Props {
  /** 未填写时为 undefined 或 null；编号只包含可编辑项。 */
  value?: DatasetInformationInput | null;
  /** 请求在途或写入被挡住时禁用。 */
  disabled: boolean;
  /** 交回整份信息并使旧预览失效；清空后省略 information。 */
  onChange: (value: DatasetInformationInput | undefined) => void;
}
/**
 * 展示可选的14项信息，将型号、场景与任务放在第5、6项内。
 * @param props - 当前初始信息、禁用状态及变更回调。
 * @returns 13个说明文字框、自动计算提示和共用分类控件。
 * @throws 无；词表请求错误通过诊断卡片展示。
 * @sideEffects 读取分类候选；输入变化仅调用 onChange，不提交预览。
 * @timeSemantics 词表沿用数据集查询缓存与取消语义，无轮询；草稿仅留内存。
 */
export function InformationFields(props: Props): ReactElement {
  const vocabulary = useDatasetFilterOptions();
  const value = props.value ?? EMPTY;
  function change(next: DatasetInformationInput): void {
    props.onChange(
      next.fields.length || next.robot_model || next.scene.length || next.tasks.length
        ? next
        : undefined,
    );
  }
  return (
    <Card title="14 项数据集信息（可选）" role="region" aria-label="14 项数据集信息（可选）">
      <div className="creation-fields">
        <p>全部可选，空着的以后可以在编辑器中补充。</p>
        {vocabulary.error && <DiagnosticCard failure={toFailureView(vocabulary.error)} />}
        {ITEMS.map(([number, name]) => {
          const label = `第 ${String(number)} 项：${name}`;
          const classification =
            number === 5
              ? (["robot_model"] as const)
              : number === 6
                ? (["scene", "tasks"] as const)
                : [];
          return (
            <div key={number} role="group" aria-label={label} className="creation-fields">
              {number === 5 && <p>第 4 项：数据大小（自动计算）</p>}
              {classification.map((key) => (
                <FieldInput
                  key={key}
                  field={{
                    path: [key],
                    label: { robot_model: "机器人型号", scene: "场景", tasks: "任务" }[key],
                    value: value[key],
                    multiple: key !== "robot_model",
                  }}
                  value={value[key]}
                  vocabulary={vocabulary.data}
                  disabled={props.disabled}
                  onChange={(next) => {
                    if (key !== "robot_model" && Array.isArray(next))
                      change({ ...value, [key]: next });
                    else if (key === "robot_model" && typeof next === "string")
                      change({ ...value, [key]: next });
                  }}
                />
              ))}
              <FieldInput
                field={{
                  path: ["fields", number, "value_markdown"],
                  label,
                  value: "",
                  multiple: false,
                }}
                value={value.fields.find((field) => field.number === number)?.value_markdown ?? ""}
                disabled={props.disabled}
                onChange={(next) => {
                  if (typeof next !== "string") return;
                  // 空项不发给服务端；先移除旧项再追加，保证编号唯一且不改写说明正文。
                  const fields = value.fields.filter((field) => field.number !== number);
                  if (next !== "") fields.push({ number, value_markdown: next });
                  change({ ...value, fields });
                }}
              />
            </div>
          );
        })}
      </div>
    </Card>
  );
}
