// 工具库 HTTP 边界（M4-01）：只用生成类型和账号客户端，不从浏览器读取程序路径。
import type { AccountCall } from "./accounts";
import type { components } from "./schema";
import { boundedRequest } from "./_request";
import { toFailureView } from "./problems";

/** 工具列表摘要，字段及四种状态均由 OpenAPI 生成。 */
export type ToolSummary = components["schemas"]["ToolSummaryResponse"];
/** 全部工具登记，包含无效清单。 */
export type ToolList = components["schemas"]["ToolListResponse"];
/** 工具配置全文、命令和源码说明。 */
export type ToolDetail = components["schemas"]["ToolDetailResponse"];
/** 工具数量少且程序在本地系统盘；请求最多等待 30 秒，避免页面无限加载。 */
const TOOL_REQUEST_TIMEOUT_MS = 30_000;

/**
 * 读取当前工具列表与指纹状态。
 * @param input - 账号客户端、取消信号和 undefined 载荷。
 * @returns 按名称排序的工具列表，不过滤不可用项。
 * @throws Error 请求失败、超时或取消；交统一诊断视图，401 沿用账号导航。
 * @sideEffects 发出一次同源 GET /api/tools，不读取浏览器存储或工具文件。
 * @timeSemantics 等待至多 TOOL_REQUEST_TIMEOUT_MS 毫秒；无重试，取消后忽略迟到结果。
 */
export function getTools(input: AccountCall): Promise<ToolList> {
  return boundedRequest(input.signal, TOOL_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.GET("/api/tools", { signal });
    if (response.data == null) throw new Error("请求失败", { cause: toFailureView(null) });
    return response.data;
  });
}

/**
 * 读取一个工具的登记详情及完整配置。
 * @param input - 账号客户端和取消信号，payload 是列表返回的工具名。
 * @returns 详情响应，配置全文和指纹均来自平台登记包。
 * @throws Error 工具不存在、请求失败、超时或取消，通过统一诊断展示。
 * @sideEffects 发出一次同源 GET /api/tools/{name}，不执行命令模板。
 * @timeSemantics 最多 TOOL_REQUEST_TIMEOUT_MS 毫秒；关抽屉取消请求，不接收迟到数据。
 */
export function getTool(input: AccountCall<string>): Promise<ToolDetail> {
  return boundedRequest(input.signal, TOOL_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.GET("/api/tools/{name}", {
      params: { path: { name: input.payload } },
      signal,
    });
    if (response.data == null) throw new Error("请求失败", { cause: toFailureView(null) });
    return response.data;
  });
}
