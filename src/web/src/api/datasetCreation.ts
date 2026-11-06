// M1-08 创建操作的 HTTP 边界；载荷来自 OpenAPI，复用账号客户端及既有请求超时。
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS } from "./jobs";
import { toFailureView } from "./problems";
import type { AccountCall } from "./accounts";
import type { Job } from "./jobs";
import type { components } from "./schema";
import type { SceneArrays } from "./sceneTypes";

/** 建链预览输入；目标、名称及格式规则由服务器单一定义。 */
export type LinkPreviewInput = components["schemas"]["LinkPreviewParameters"];
/** 新增数据集预览输入，含可选初始信息；后端已生成第09张契约。 */
export type DatasetPreviewInput = SceneArrays<components["schemas"]["DatasetPreviewParameters"]>;
/** 新建数据集信息沿用生成类型，编号范围和去重由后端校验。 */
export type DatasetInformationInput = SceneArrays<components["schemas"]["DatasetInformation"]>;
/** 表单格式登记与来源候选。 */
export type CreationOptions = components["schemas"]["CreationOptions"];
/** 保存的创建预览；不含可执行计划正文。 */
export type CreationPreview = SceneArrays<components["schemas"]["CreationPreviewView"]>;
/** 确认载荷只引用预览和已确认的排队编号。 */
export type ConfirmCreationInput = components["schemas"]["ConfirmCreationRequest"];
/** 确认成功返回的写入作业；未确认的新排队项通过 409 五段诊断返回。 */
export type CreationSubmit = components["schemas"]["JobResponse"];
/** 格式选择同时用于两种表单，不另维护版本层规则。 */
export type FormatSelection = components["schemas"]["FormatEntrySelection"];
/** 同数据集排队提醒。 */
export type QueuedNavigationJob = components["schemas"]["QueuedNavigationJob"];

/** 成功预览的读取参数，编号保持文本精度。 */
export interface CreationPreviewCall extends AccountCall {
  /** 成功预览作业编号，规范十进制文本，最大 2^63-1。 */
  previewJobId: CreationPreview["preview_job_id"];
}

/**
 * 读取创建表单共用的格式与数据来源候选。
 * @param _input - 账号客户端、undefined payload、取消信号，均显式提供。
 * @returns GET /api/datasets/creation-options 的候选，不从浏览器文件系统发现目录。
 * @throws Error 请求、超时、取消、认证或服务端错误经统一 problem 适配。
 * @sideEffects 一次同源 GET；不改 URL 或持久保存候选。
 * @timeSemantics 使用 JOB_REQUEST_TIMEOUT_MS，无重试，无后台轮询。
 */
export function getCreationOptions(_input: AccountCall): Promise<CreationOptions> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.GET("/api/datasets/creation-options", { signal });
    return required(response.data);
  });
}

/**
 * 为现有数据集提交只读建链预览。
 * @param _input - LinkPreviewInput、账号客户端及取消信号；不接受客户端计划。
 * @returns POST /api/datasets/link-previews 的 queued 作业，用既有作业接口轮询。
 * @throws Error 输入拒绝、未登录、超时或服务端失败交 DiagnosticCard。
 * @sideEffects 一次同源 POST，服务端只写预览作业及提交日志。
 * @timeSemantics JOB_REQUEST_TIMEOUT_MS，不重试 POST；取消 HTTP 不等于取消已提交作业。
 */
export function submitLinkPreview(_input: AccountCall<LinkPreviewInput>): Promise<Job> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.POST("/api/datasets/link-previews", {
      body: _input.payload,
      signal,
    });
    return required(response.data);
  });
}

/**
 * 提交新数据集全套入口的只读预览。
 * @param _input - 必填数据集名、来源和第一链接，使用生成的 DatasetPreviewInput。
 * @returns POST /api/datasets/creation-previews 的 queued 预览作业，尚未占用数据集编号。
 * @throws Error 输入、来源或服务端拒绝，以及网络/取消失败，均经统一诊断。
 * @sideEffects 一次 POST，不在浏览器内创建入口或推测下一个编号。
 * @timeSemantics 请求上限 JOB_REQUEST_TIMEOUT_MS，无重试；等待预览走作业轮询节奏。
 */
export function submitDatasetPreview(_input: AccountCall<DatasetPreviewInput>): Promise<Job> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.POST("/api/datasets/creation-previews", {
      body: _input.payload,
      signal,
    });
    return required(response.data);
  });
}

/**
 * 读取已经成功完成的任一种创建预览。
 * @param _input - 账号客户端、文本预览编号、undefined payload 和取消信号。
 * @returns GET /api/datasets/creation-previews/{preview_job_id} 的结构化差异与最新排队提醒。
 * @throws Error 未成功、过期、错类型、损坏及请求失败交统一诊断，不当作空预览。
 * @sideEffects 一次 GET，只读已保存计划投影；不重新计算预览或写导航。
 * @timeSemantics 保留 created_at；使用 JOB_REQUEST_TIMEOUT_MS，确认前再读取，不自动轮询此接口。
 */
export function getCreationPreview(_input: CreationPreviewCall): Promise<CreationPreview> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.GET("/api/datasets/creation-previews/{preview_job_id}", {
      params: { path: { preview_job_id: _input.previewJobId } },
      signal,
    });
    const value = required(response.data);
    // 客户端的可写类型会把固定二元组展开成数组，边界核对长度后恢复协议中的键值对。
    return {
      ...value,
      report: {
        ...value.report,
        notices: value.report.notices.map((notice) => ({
          ...notice,
          objects: notice.objects.map(objectPair),
        })),
      },
    };
  });
}

/**
 * 确认同一份预览，提交写入；新增排队提醒通过 409 返回。
 * @param _input - 生成的确认载荷，只含预览编号和用户已确认的排队编号。
 * @returns POST /api/datasets/creation-writes 的 201 作业记录，按 job_id 跳转作业页。
 * @throws Error 类型/过期/认证/请求失败交统一诊断；队列提醒 409 从 queued_job_id_N 诊断对象取编号，用户确认后带 acknowledged_queue_job_ids 重提；导航冲突需重新预览。
 * @sideEffects 一次 POST；用户重复点击在 Mutation pending 时禁用，不修改已保存预览。
 * @timeSemantics JOB_REQUEST_TIMEOUT_MS，不重试不确定的提交；worker 写锁内复核并异步执行。
 */
export function confirmCreation(
  _input: AccountCall<ConfirmCreationInput>,
): Promise<CreationSubmit> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.POST("/api/datasets/creation-writes", {
      body: _input.payload,
      signal,
    });
    return required(response.data);
  });
}

function required<T>(value: T | undefined): T {
  if (value === undefined || value === null)
    throw new Error("请求失败", { cause: toFailureView(null) });
  return value;
}

function objectPair(value: string[]): [string, string] {
  const key = value[0],
    item = value[1];
  if (value.length !== 2 || key === undefined || item === undefined)
    throw new Error("请求失败", { cause: toFailureView(null) });
  return [key, item];
}
