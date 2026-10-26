// 作业 HTTP 契约（08）：沿用账号感知客户端和 defaultFetch，不保存浏览器原生函数为对象方法。
// 全部接口类型从 OpenAPI 生成；所有写请求由浏览器带同源 Origin，失败交统一诊断。
import type { AccountCall } from "./accounts";
import type { components, operations } from "./schema";

/** 永久记录；编号是规范十进制文本，不允许转 Number。 */
export type Job = components["schemas"]["JobResponse"];
/** 状态筛选、游标和 limit，分享/刷新时由类型化 Router search 保留。 */
export type JobSearch = NonNullable<operations["list_jobs"]["parameters"]["query"]>;
/** 有界列表页，末页 next_cursor=null。 */
export type JobList = components["schemas"]["JobListResponse"];
/** 示例参数，间隔单位毫秒，序号从 1 起。 */
export type CountInput = components["schemas"]["CountParameters"];
/** 日志尾部，明确区分 available/not_started/cleared。 */
export type JobLog = components["schemas"]["JobLogResponse"];
/** 最近心跳及服务端在线判定。 */
export type WorkerStatus = components["schemas"]["WorkerStatusResponse"];
/** 单个作业请求，不接受客户端文件路径。 */
export interface JobCall extends AccountCall {
  /** 作业正编号文本，最大 2^63-1。 */
  jobId: Job["job_id"];
}

/** 工单约 1 秒刷新，与后端写入节奏一致；单位毫秒。 */
export const JOB_POLL_INTERVAL_MS = 1000;
/** 请求上限 10 秒，沿用账号页面预算；超时不能证明服务器已回滚。 */
export const JOB_REQUEST_TIMEOUT_MS = 10000;
/** 离页即释放作业缓存，不在账号切换后复用旧身份内容；单位毫秒。 */
export const JOB_GC_TIME_MS = 0;
/** 作业查询立即过期，聚焦后刷新；单位毫秒。 */
export const JOB_STALE_TIME_MS = 0;
/** 后端同名上限，客户端只用于表单和 URL 边界，服务端独立校验。 */
export const JOB_PAGE_LIMIT = 100;
/** v1 opaque 游标上限，单位字符，不在浏览器解码内部载荷。 */
export const JOB_CURSOR_MAX_CHARS = 512;

/**
 * 获取按状态筛选的一页作业。
 * @param _input - 账号感知客户端、生成的 JobSearch 和 AbortSignal；不按提交人限制。
 * @returns GET /api/jobs 的job_id倒序页，UTC 时刻、文本编号，空页合法。
 * @throws Error 网络/超时/取消或服务错误经 toFailureView；401 先统一清缓存和回登录。
 * @sideEffects 一次同源 GET，经 openapi-fetch 和 boundedRequest；不读 cookie、不存储原生 fetch 的 this。
 * @timeSemantics 最多 JOB_REQUEST_TIMEOUT_MS，无自动重试，取消后丢弃迟到结果。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function listJobs(_input: AccountCall<JobSearch>): Promise<JobList> {
  throw new Error("未实现");
}

/**
 * 读取指定作业的永久详情。
 * @param _input - 已认证客户端、文本 jobId、undefined payload 和取消信号。
 * @returns GET /api/jobs/{job_id} 的完整 Job，未知进度总数保持 null。
 * @throws Error 404/422/权限/网络等失败交统一诊断，不伪造不存在的记录。
 * @sideEffects 一次只读请求；字段只使用生成类型，不在客户端计算作业结果。
 * @timeSemantics 上限 10 秒，遵守 AbortSignal，无内部轮询。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function getJob(_input: JobCall): Promise<Job> {
  throw new Error("未实现");
}

/**
 * 提交示例数数作业。
 * @param _input - 客户端、CountInput 和取消信号；整数范围与序号关系遵守服务端模型。
 * @returns POST /api/jobs/example 的新 queued 记录，201 后才显示提交成功。
 * @throws Error 校验/权限/存储/超时等错误交 DiagnosticCard，不回显敏感载荷。
 * @sideEffects 同源写请求带 Origin；成功由调用方刷新列表并导航详情，不重发不确定提交。
 * @timeSemantics 请求最多 10 秒，不等待 worker 上线或作业结束，取消请求不保证服务器回滚。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function submitCountJob(_input: AccountCall<CountInput>): Promise<Job> {
  throw new Error("未实现");
}

/**
 * 请求取消任意作业。
 * @param _input - 客户端、文本 jobId、undefined payload 和取消信号。
 * @returns POST /api/jobs/{job_id}/cancel 的 cancelled 或 cancelling 记录。
 * @throws Error 409 表示已正在取消、终态或真实写冲突，展示诊断并重新读取；worker先领取时正常返回正在取消。其他错误沿用统一问题响应。
 * @sideEffects 一次同源 POST，服务端记录当前取消账号；不在客户端乐观伪造已取消。
 * @timeSemantics 最多 10 秒，无自动重试；cancelling 继续轮询直至终态。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function cancelJob(_input: JobCall): Promise<Job> {
  throw new Error("未实现");
}

/**
 * 从终态记录重新提交一个新作业。
 * @param _input - 客户端、原 jobId、undefined payload 和 AbortSignal，不提交操作者声明。
 * @returns POST /api/jobs/{job_id}/resubmit 的新 Job，含 resubmitted_from。
 * @throws Error 非终态 409、旧参数不兼容 422、其他失败均由 DiagnosticCard 呈现。
 * @sideEffects 一次同源 POST；成功导航到新编号，旧页面记录不改写，不复制旧提交人。
 * @timeSemantics 请求 10 秒上限；不重试，卸载取消并忽略迟到结果。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function resubmitJob(_input: JobCall): Promise<Job> {
  throw new Error("未实现");
}

/**
 * 查询日志的有限尾部。
 * @param _input - 账号客户端、作业编号和取消信号，不能指定磁盘路径。
 * @returns GET /api/jobs/{job_id}/log 的状态及至多 50 行；cleared 显示“作业日志已清除”。
 * @throws Error 读取故障或越界缺陷沿用统一诊断；不把 502 伪装成已清除。
 * @sideEffects 一次只读请求，不下载整份文件；React 文本渲染输出，不执行工具输出 HTML。
 * @timeSemantics 10 秒上限，无请求内等待；终态详情收到最后一次日志结果后停止轮询。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function getJobLog(_input: JobCall): Promise<JobLog> {
  throw new Error("未实现");
}

/**
 * 读取 worker 的服务端在线判定。
 * @param _input - 账号客户端、undefined payload 和取消信号；所有登录账号使用同一路径。
 * @returns GET /api/worker/status 的最近心跳与 online；数据库查询失败不返回假的离线。
 * @throws Error 401/403/网络/服务端错误交统一诊断，401 先清缓存。
 * @sideEffects 一次 GET，不探测进程号、不使用浏览器墙钟重新判定在线。
 * @timeSemantics 请求最多 10 秒；布局约每秒轮询，阈值 15 秒由服务端计算。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function getWorkerStatus(_input: AccountCall): Promise<WorkerStatus> {
  throw new Error("未实现");
}
