// M1-08 表单流程状态；不复制 HTTP 字段或在浏览器内决定计划步骤。
import type {
  ConfirmCreationInput,
  CreationOptions,
  CreationPreview,
  DatasetPreviewInput,
  LinkPreviewInput,
  QueuedNavigationJob,
} from "../api/datasetCreation";
import type { Job } from "../api/jobs";
import type { RequestFailureView } from "../api/problems";

/** 可分享定位只保存编号，目标路径和未提交表单只在内存中。 */
export interface CreationSearch {
  /** 可选现有数据集永久编号，只用于建链表单预选；不是任意导航路径。 */
  dataset_id?: string;
  /** 可选成功预览编号文本；刷新后读取保存结果，禁止 Number 转换。 */
  preview_job_id?: CreationPreview["preview_job_id"];
  /** Router 输入非法时显示可修正提示，不回显坏输入或发请求。 */
  invalidCreationSearch?: true;
}

/**
 * 校验真实 Router 解码后的创建页面查询参数。
 * @param _input - Router search 原值，数字样式可能已经是 number，不能转为文本蒙混通过。
 * @returns 规范文本编号与预选项；非法值只返回 invalidCreationSearch=true。
 * @throws 无；坏 URL 留在表单提示，不使根路由崩溃。
 * @sideEffects 无；不解析 URLSearchParams、不写浏览器存储。
 * @timeSemantics 同步纯转换，不发请求。
 */
export function validateCreationSearch(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _input: Record<string, unknown>,
): CreationSearch {
  throw new Error("NotImplementedError");
}

/** 页面局部阶段；服务端响应仍使用生成类型。 */
export type CreationStage = "editing" | "previewing" | "reviewing" | "submitting" | "submitted";

/** 两个页面复用的流程结果，不把失败伪装成空预览。 */
export interface CreationFlow {
  /** 当前阶段，editing 可填参数，reviewing 才能确认，pending 阶段禁用重复提交。 */
  stage: CreationStage;
  /** 格式/来源登记候选；尚未取到为 undefined，表单不可提交。 */
  options: CreationOptions | undefined;
  /** 成功并与当前表单参数一致的预览；修改任一参数立刻清空，强制重新预览。 */
  preview: CreationPreview | undefined;
  /** 当前预览作业；终态后停止轮询，不将已有结果复用于新参数。 */
  previewJob: Job | undefined;
  /** 排队提醒，空表示当前快照没有同数据集排队写作业。 */
  queuedJobs: QueuedNavigationJob[];
  /** 当前统一诊断；冲突保留对象、实际、期望、后果与下一步。 */
  failure: RequestFailureView | undefined;
  /** 提交任一种预览，参数类型由当前页面区分。 */
  previewParameters: (parameters: LinkPreviewInput | DatasetPreviewInput) => void;
  /** 确认当前预览；仅传预览编号和用户已确认的排队编号。 */
  confirm: (parameters: ConfirmCreationInput) => void;
  /** 修改表单或冲突后退回编辑阶段，丢弃旧预览确认资格。 */
  edit: () => void;
}

/** hook 的显式输入，不保存目标到可分享 URL。 */
export interface CreationFlowInput {
  /** 当前创建类型，不能拿另一种预览直接确认。 */
  operation: CreationPreview["operation"];
  /** 类型化 Router 提供的预览编号，未预览为 undefined。 */
  previewJobId: CreationPreview["preview_job_id"] | undefined;
  /** 成功后导航到已有 /jobs/$jobId；编号保持文本。 */
  onSubmitted: (job: Job) => void;
  /** 预览成功后写回类型化 search，允许刷新后重读预览。 */
  onPreviewed: (preview: CreationPreview) => void;
}

/**
 * 驱动两种表单从填参数、预览到确认入队的流程。
 * @param _input - 当前操作、文本预览定位及 Router 导航回调。
 * @returns CreationFlow；只允许成功预览进入 reviewing，参数变化后必须重新预览。
 * @throws Error 缺少账号客户端或 QueryClient Provider；请求失败保存在 failure。
 * @sideEffects 用 TanStack Query 和统一客户端读候选、提交预览、轮询 M0 作业、读取保存结果及确认；成功入队后刷新 datasets/jobs 缓存并导航。
 * @timeSemantics 预览作业按 JOB_POLL_INTERVAL_MS 轮询且终态停止，使用 JOB_STALE_TIME_MS/JOB_GC_TIME_MS；离页取消读请求，所有 POST 不重试。
 */
export function useCreationFlow(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _input: CreationFlowInput,
): CreationFlow {
  throw new Error("NotImplementedError");
}
