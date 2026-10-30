// M1-08 创建表单组件；负责受控输入与交互，不读文件、不自行生成计划。
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
 * @param _props - 受控值、候选、pending 及变更/预览回调。
 * @returns 建链表单；缺 meta/info.json 时可从登记格式中选择 fallback_format，版本由服务端给 null。
 * @throws 无；非法输入显示表单反馈，服务端最终校验仍经统一诊断。
 * @sideEffects 只触发 onChange/onPreview/onDatasetPage，不直接请求接口或改 URL。
 * @timeSemantics 同步渲染；pending 禁用提交，修改字段使预览失效而不复用旧结果。
 */
export function CreateLinkForm(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _props: CreateLinkFormProps,
): ReactElement {
  throw new Error("NotImplementedError");
}

/** 新增数据集受控表单。 */
export interface CreateDatasetFormProps {
  /** 数据集名、来源、第一链接和所选格式位置。 */
  value: DatasetPreviewInput;
  /** 数据来源和格式唯一登记候选。 */
  options: CreationOptions;
  /** 请求在途时 true，禁止重复提交。 */
  pending: boolean;
  /** 任一参数改变都清空旧预览；名称保持原样，不自动修剪重命名。 */
  onChange: (value: DatasetPreviewInput) => void;
  /** 点击预览后上交参数，来源必须由用户选择。 */
  onPreview: (value: DatasetPreviewInput) => void;
}

/**
 * 填写新数据集名称、必填来源和第一条链接。
 * @param _props - 服务端字段类型的受控值、候选与预览回调。
 * @returns 新数据集表单；零到多个格式选择，编号由预览提供，页面不能指定。
 * @throws 无；必填/名称错误显示可修正反馈，服务端拒绝由父页面展示诊断。
 * @sideEffects 只发出字段变更和预览事件；不创建入口或来源文件。
 * @timeSemantics pending 禁用按钮；不缓存未提交表单到浏览器存储。
 */
export function CreateDatasetForm(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _props: CreateDatasetFormProps,
): ReactElement {
  throw new Error("NotImplementedError");
}

/** 两种表单共用的按格式入口选择。 */
export interface FormatEntryPickerProps {
  /** 格式登记项及已有版本候选；版本层规则来自 has_versions。 */
  options: CreationOptions["formats"];
  /** 去重的零到多个位置；允许为版本格式输入安全的新版本目录。 */
  value: FormatSelection[];
  /** 请求在途时禁用，避免确认旧预览期间修改参数。 */
  disabled: boolean;
  /** 任一选择变化后上交完整数组。 */
  onChange: (value: FormatSelection[]) => void;
}

/**
 * 选择要加入本条链接的按格式入口。
 * @param _props - 登记选项、去重受控选择及禁用状态。
 * @returns 格式/版本多选组件；archives 显示登记目录名，版本层按登记表要求填写。
 * @throws 无；非法或重复位置留在表单反馈，不悄悄去重后提交。
 * @sideEffects 只触发 onChange，不查磁盘或调用写接口。
 * @timeSemantics 同步交互，无轮询、缓存或时间推断。
 */
export function FormatEntryPicker(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _props: FormatEntryPickerProps,
): ReactElement {
  throw new Error("NotImplementedError");
}
