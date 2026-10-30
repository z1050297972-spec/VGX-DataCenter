// 创建表单中的单条链接输入；只编辑生成的类型，不复制服务端格式目录映射。
import type { ReactElement } from "react";
import { Input } from "antd";
import type { CreationOptions, LinkPreviewInput } from "../api/datasetCreation";

/** 链接字段的受控属性。 */
export interface LinkFieldsProps {
  /** 生成模型的单条链接，不包含操作者或存储配置。 */
  value: LinkPreviewInput["link"];
  /** 服务端格式登记。 */
  options: CreationOptions;
  /** 请求或恢复失败时禁用。 */
  disabled: boolean;
  /** 字段变化时交回整条链接。 */
  onChange: (value: LinkPreviewInput["link"]) => void;
}
/**
 * 编辑链接名、绝对目标及缺元信息时的格式。
 * @param props - 受控字段及登记选项。
 * @returns 无文件系统访问的输入区域。
 * @throws 无。
 * @sideEffects 只触发 onChange。
 * @timeSemantics 同步输入，请求在父表单提交时发生。
 */
export function LinkFields(props: LinkFieldsProps): ReactElement {
  return (
    <fieldset disabled={props.disabled} className="creation-fields">
      <label>
        链接名
        <Input
          aria-label="链接名"
          required
          value={props.value.name}
          onChange={(event) => {
            props.onChange({ ...props.value, name: event.target.value });
          }}
        />
      </label>
      <label>
        目标路径
        <Input
          aria-label="目标路径"
          required
          pattern="/.*"
          value={props.value.target_path}
          onChange={(event) => {
            props.onChange({ ...props.value, target_path: event.target.value });
          }}
        />
      </label>
      <label>
        无元信息时的格式
        <select
          aria-label="无元信息时的格式"
          value={props.value.fallback_format ?? ""}
          onChange={(event) => {
            props.onChange({ ...props.value, fallback_format: event.target.value || null });
          }}
        >
          <option value="">有 meta/info.json 时使用文件内容</option>
          {props.options.formats.map((item) => (
            <option key={item.format} value={item.format}>
              {item.directory}
            </option>
          ))}
        </select>
      </label>
      <p className="creation-note">
        没有 meta/info.json 时请选格式；存在元信息时以文件为准。链接不会修改目标数据。
      </p>
    </fieldset>
  );
}
