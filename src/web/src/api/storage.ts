// 存储根 HTTP 边界（10）：只用生成类型和账号客户端，不从浏览器探测数据目录。
import type { AccountCall } from "./accounts";
import type { components } from "./schema";

/** 全部登记根的只读状态；数组顺序由后端配置决定。 */
export type StorageRoots = components["schemas"]["StorageRootsResponse"];
/** 单根摘要，原因保持后端枚举，禁止从错误文本猜测。 */
export type StorageRoot = components["schemas"]["StorageRootResponse"];
/** 本地挂载表查询的 HTTP 预算为十秒；与 worker 的可配置访问预算相互独立。 */
export const STORAGE_REQUEST_TIMEOUT_MS = 10_000;

/**
 * 请求一次现场存储根挂载检查。
 * @param _input - 账号客户端、undefined payload 和取消信号；普通成员可调用。
 * @returns GET /api/storage-roots 的完整摘要；配置为空返回空 items，不把缺少响应体视为空配置。
 * @throws Error 传输、超时、取消或服务端失败，使用统一诊断视图；401 由账号客户端处理。
 * @sideEffects 经 openapi-fetch 与 boundedRequest 发一次同源 GET，不访问返回的路径，不记录来源挂载信息。
 * @timeSemantics 最多 STORAGE_REQUEST_TIMEOUT_MS 毫秒；无重试，取消后不接收迟到数据。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 工单10要求保留必填输入且函数体只抛未实现异常；接入请求后移除本行。
export function getStorageRoots(_input: AccountCall): Promise<StorageRoots> {
  throw new Error("NotImplementedError");
}
