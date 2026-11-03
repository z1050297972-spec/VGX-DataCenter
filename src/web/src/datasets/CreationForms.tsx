import "./creation.css";
// M1-08 创建表单组件；负责受控输入与交互，不读文件、不自行生成计划。
import { Button, Card, Input, Select } from "antd";
import { LinkFields } from "./CreationFields";
import type { ReactElement } from "react";
import type {
  CreationOptions,
  DatasetPreviewInput,
  FormatSelection,
  LinkPreviewInput,
} from "../api/datasetCreation";
import type { DatasetList } from "../api/datasets";

/** 建链表单输入，数据集候选复用已有分页列表。 */
export interface CreateLinkFormProps {
  /** 当前服务端请求字段；格式候选未就绪时不能提交。 */
  value: LinkPreviewInput;
  /** 已登记格式、版本候选及来源，不在前端重复词表。 */
  options: CreationOptions;
  /** 当前数据集候选页，允许翻页/搜索后选择，不能只限于第一页。 */
  datasets: DatasetList;
  /** 预览阶段服务端返回的入口候选，首次预览前为空。 */
  entryOptions?: FormatSelection[];
  /** 预览或提交请求进行中时为 true，禁用重复点击。 */
  pending: boolean;
  /** 输入改变时调用，页面必须清空旧预览确认资格。 */
  onChange: (value: LinkPreviewInput) => void;
  /** 用户点击预览时提交当前参数，不直接执行写入。 */
  onPreview: (value: LinkPreviewInput) => void;
  /** 切换已有数据集候选页；offset 为非负整数条目数，沿用现有列表页上限。 */
  onDatasetPage: (offset: number) => void;
}

/**
 * 填写现有数据集、链接名、绝对目标和按格式入口。
 * @param props - 受控值、候选、pending 及变更/预览回调。
 * @returns 建链表单；缺 meta/info.json 时可从登记格式中选择 fallback_format，版本由服务端给 null。
 * @throws 无；非法输入显示表单反馈，服务端最终校验仍经统一诊断。
 * @sideEffects 只触发 onChange/onPreview/onDatasetPage，不直接请求接口或改 URL。
 * @timeSemantics 同步渲染；pending 禁用提交，修改字段使预览失效而不复用旧结果。
 */
export function CreateLinkForm(props: CreateLinkFormProps): ReactElement {
  return (
    <form
      className="creation-form"
      onSubmit={(event) => {
        event.preventDefault();
        // antd Select不参加浏览器原生required校验，键盘提交也须有数据集。
        if (props.value.dataset_id) props.onPreview(props.value);
      }}
    >
      <Card title="01 基本信息">
        <fieldset disabled={props.pending} className="creation-fields">
          <label>
            数据集
            <Select<string>
              virtual={false}
              aria-label="数据集"
              aria-required="true"
              disabled={props.pending}
              className="creation-select-full"
              placeholder="请选择数据集"
              value={props.value.dataset_id || undefined}
              options={[
                ...(!props.datasets.items.some(
                  (item) => item.dataset_id === props.value.dataset_id,
                ) && props.value.dataset_id
                  ? [{ value: props.value.dataset_id, label: props.value.dataset_id }]
                  : []),
                ...props.datasets.items.flatMap((item) =>
                  item.dataset_id ? [{ value: item.dataset_id, label: item.name }] : [],
                ),
              ]}
              onChange={(value) => {
                props.onChange({ ...props.value, dataset_id: value });
              }}
            />
          </label>
          <div className="creation-actions">
            <Button
              aria-label="上一页数据集"
              disabled={props.datasets.offset === 0}
              onClick={() => {
                props.onDatasetPage(Math.max(0, props.datasets.offset - props.datasets.limit));
              }}
            >
              上一页
            </Button>
            <Button
              aria-label="下一页数据集"
              disabled={props.datasets.offset + props.datasets.limit >= props.datasets.total}
              onClick={() => {
                props.onDatasetPage(props.datasets.offset + props.datasets.limit);
              }}
            >
              下一页
            </Button>
          </div>
        </fieldset>
      </Card>
      <LinkFields
        value={props.value.link}
        options={props.options}
        disabled={props.pending}
        onChange={(link) => {
          props.onChange({ ...props.value, link });
        }}
      />
      {!!props.entryOptions?.length && (
        <FormatEntryPicker
          options={props.options.formats}
          choices={props.entryOptions}
          value={props.value.format_entries}
          disabled={props.pending}
          onChange={(format_entries) => {
            props.onChange({ ...props.value, format_entries });
          }}
        />
      )}
      <Button
        type="primary"
        htmlType="submit"
        aria-label="生成预览"
        disabled={props.pending || !props.value.dataset_id}
        loading={props.pending}
      >
        生成预览
      </Button>
    </form>
  );
}

/** 新增数据集受控表单。 */
export interface CreateDatasetFormProps {
  /** 数据集名、来源、第一链接和所选格式位置。 */
  value: DatasetPreviewInput;
  /** 数据来源和格式唯一登记候选。 */
  options: CreationOptions;
  /** 预览返回的入口候选；未传时使用登记表中的已有版本。 */
  entryOptions?: FormatSelection[];
  /** 请求在途时 true，禁止重复提交。 */
  pending: boolean;
  /** 任一参数改变都清空旧预览；名称保持原样，不自动修剪重命名。 */
  onChange: (value: DatasetPreviewInput) => void;
  /** 点击预览后上交参数，来源必须由用户选择。 */
  onPreview: (value: DatasetPreviewInput) => void;
}

/**
 * 填写新数据集名称、必填来源和第一条链接。
 * @param props - 服务端字段类型的受控值、候选与预览回调。
 * @returns 新数据集表单；零到多个格式选择，编号由预览提供，页面不能指定。
 * @throws 无；必填/名称错误显示可修正反馈，服务端拒绝由父页面展示诊断。
 * @sideEffects 只发出字段变更和预览事件；不创建入口或来源文件。
 * @timeSemantics pending 禁用按钮；不缓存未提交表单到浏览器存储。
 */
export function CreateDatasetForm(props: CreateDatasetFormProps): ReactElement {
  return (
    <form
      className="creation-form"
      onSubmit={(event) => {
        event.preventDefault();
        // 保留原生下拉框的必选语义，不能通过键盘提交空来源。
        if (props.value.data_origin) props.onPreview(props.value);
      }}
    >
      <Card title="01 基本信息">
        <fieldset disabled={props.pending} className="creation-fields">
          <label>
            数据集名
            <Input
              aria-label="数据集名"
              required
              value={props.value.dataset_name}
              onChange={(event) => {
                props.onChange({ ...props.value, dataset_name: event.target.value });
              }}
            />
          </label>
          <label>
            数据来源
            <Select<string>
              virtual={false}
              aria-label="数据来源"
              aria-required="true"
              disabled={props.pending}
              className="creation-select-full"
              placeholder="请选择数据来源"
              value={props.value.data_origin || undefined}
              options={props.options.data_origins.map((value) => ({ value, label: value }))}
              onChange={(value) => {
                props.onChange({ ...props.value, data_origin: value });
              }}
            />
          </label>
        </fieldset>
      </Card>
      <LinkFields
        value={props.value.link}
        options={props.options}
        disabled={props.pending}
        onChange={(link) => {
          props.onChange({ ...props.value, link });
        }}
      />
      <FormatEntryPicker
        options={props.options.formats}
        choices={props.entryOptions?.length ? props.entryOptions : undefined}
        value={props.value.format_entries}
        disabled={props.pending}
        onChange={(format_entries) => {
          props.onChange({ ...props.value, format_entries });
        }}
      />
      <Button
        type="primary"
        htmlType="submit"
        aria-label="生成预览"
        disabled={props.pending || !props.value.data_origin}
        loading={props.pending}
      >
        生成预览
      </Button>
    </form>
  );
}

/** 两种表单共用的按格式入口选择。 */
export interface FormatEntryPickerProps {
  /** 格式登记项及已有版本候选；版本层规则来自 has_versions。 */
  options: CreationOptions["formats"];
  /** 成功预览返回的准确候选；未传时使用登记版本候选。 */
  choices?: FormatSelection[];
  /** 去重的零到多个位置；允许为版本格式输入安全的新版本目录。 */
  value: FormatSelection[];
  /** 请求在途时禁用，避免确认旧预览期间修改参数。 */
  disabled: boolean;
  /** 任一选择变化后上交完整数组。 */
  onChange: (value: FormatSelection[]) => void;
}

/**
 * 选择要加入本条链接的按格式入口。
 * @param props - 登记选项、去重受控选择及禁用状态。
 * @returns 格式/版本多选组件；archives 显示登记目录名，版本层按登记表要求填写。
 * @throws 无；非法或重复位置留在表单反馈，不悄悄去重后提交。
 * @sideEffects 只触发 onChange，不查磁盘或调用写接口。
 * @timeSemantics 同步交互，无轮询、缓存或时间推断。
 */
export function FormatEntryPicker(props: FormatEntryPickerProps): ReactElement {
  const choices =
    props.choices ??
    props.options.flatMap<FormatSelection>((item) =>
      item.has_versions
        ? item.versions.map((version) => ({ format: item.format, version }))
        : [{ format: item.format, version: null }],
    );
  return (
    <Card title="03 格式入口">
      <fieldset disabled={props.disabled} className="creation-fields">
        <legend>格式入口</legend>
        {choices.map((item) => {
          const selected = props.value.some(
            (value) =>
              value.format === item.format && (value.version ?? null) === (item.version ?? null),
          );
          const directory =
            props.options.find((value) => value.format === item.format)?.directory ?? item.format;
          const label = directory + (item.version ? "/" + item.version : "");
          return (
            <label className="creation-check" key={label}>
              <input
                type="checkbox"
                aria-label={`格式入口 ${label}`}
                checked={selected}
                onChange={() => {
                  props.onChange(
                    selected
                      ? props.value.filter(
                          (value) =>
                            !(
                              value.format === item.format &&
                              (value.version ?? null) === (item.version ?? null)
                            ),
                        )
                      : [...props.value, item],
                  );
                }}
              />
              {label}
            </label>
          );
        })}
        {!choices.length && <p>当前没有可选格式入口，可先生成预览。</p>}
      </fieldset>
    </Card>
  );
}
