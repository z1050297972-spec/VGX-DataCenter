// 调度 HTTP 契约（09）：复用账号感知客户端和生成类型，不从浏览器探测硬件或拼服务器地址。
import type { AccountCall } from "./accounts";
import type { Job } from "./jobs";
import type { components } from "./schema";

/** 只读资源与每日计划快照，全部编号保持十进制文本。 */
export type Scheduling = components["schemas"]["SchedulingResponse"];
/** 占用秒数 0-600，边界由后端模型提供。 */
export type GpuInput = components["schemas"]["GpuExampleParameters"];
/** 预览值和锁内暂停秒数，不允许客户端指定文件路径。 */
export type NavigationInput = components["schemas"]["NavigationExampleParameters"];

/**
 * 读取 worker 保存的调度展示快照。
 * @param _input - 当前账号客户端、undefined payload 和 AbortSignal；没有管理员要求。
 * @returns GET /api/worker/scheduling 的 Scheduling，空闲和从未提交保持 null；不在客户端猜 worker 状态。
 * @throws Error 网络、超时、取消、401/403 和服务端故障由统一 toFailureView 呈现。
 * @sideEffects 经 openapi-fetch 与 boundedRequest 发一次同源 GET；401 统一清理账号缓存，不读 cookie 或默认配置。
 * @timeSemantics 请求上限 JOB_REQUEST_TIMEOUT_MS=10000，无自动重试，卸载/换号取消并忽略迟到响应。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数属于公开契约，函数体按工单要求仅抛未实现错误。
export function getScheduling(_input: AccountCall): Promise<Scheduling> {
  throw new Error("未实现");
}

/**
 * 提交演示 GPU 名额的作业。
 * @param _input - 当前账号客户端、GpuInput 和 AbortSignal，整数秒范围以生成模型为准。
 * @returns POST /api/jobs/example/gpu 的新 queued 作业，成功后可导航到其详情。
 * @throws Error 参数、身份、持久化或传输失败；由 DiagnosticCard 显示，保留输入。
 * @sideEffects 一次同源 POST；不设置 CUDA 环境，不在浏览器挑卡，成功由调用方刷新作业查询。
 * @timeSemantics 请求最多 JOB_REQUEST_TIMEOUT_MS，禁止自动重试不确定的提交；等待时长只在 worker 生效。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数属于公开契约，函数体按工单要求仅抛未实现错误。
export function submitGpuJob(_input: AccountCall<GpuInput>): Promise<Job> {
  throw new Error("未实现");
}

/**
 * 提交带预览期望值的示例写锁作业。
 * @param _input - 当前账号客户端、NavigationInput 和 AbortSignal；不包含身份或路径。
 * @returns POST /api/jobs/example/navigation 的新 queued 作业，不在提交时判断最终冲突。
 * @throws Error 422/权限/数据库/网络等失败交统一诊断，不把提交成功当成写入成功。
 * @sideEffects 单次同源 POST，服务器记录点击账号；不乐观改示例文件状态。
 * @timeSemantics 10 秒请求上限，不重试；pause_s 的零至十秒暂停由后台锁内执行。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数属于公开契约，函数体按工单要求仅抛未实现错误。
export function submitNavigationJob(_input: AccountCall<NavigationInput>): Promise<Job> {
  throw new Error("未实现");
}
