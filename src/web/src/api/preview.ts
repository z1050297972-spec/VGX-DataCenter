// 预览的 HTTP 边界复用生成类型和已有超时；端口来自与 relay 共用的受评审静态资源。
import channels from "../../../rdp/collection/preview_channels.json";
import { boundedRequest } from "./_request";
import { ACCOUNT_TIMEOUT_MS, type AccountCall } from "./accounts";
import type { components } from "./schema";

/** 说明档摘要，直接使用 OpenAPI 的事实类型。 */
export type ProfileSummary = components["schemas"]["RobotProfileSummary"];
/** M5-04 固定端口的唯一源在 preview_channels.json，不在浏览器另设默认值。 */
export const PREVIEW_PORT = channels.port;

/**
 * 读取型号与说明档版本，用于预览入口和页头。
 * @param input - 登录客户端、取消信号和空载荷。
 * @returns 全部说明档摘要；没有说明档时 items 为空。
 * @throws Error 请求失败或响应缺失，由统一诊断视图显示。
 * @sideEffects 发送 GET /api/robot-profiles，不连接机器人。
 * @timeSemantics 单次上限 ACCOUNT_TIMEOUT_MS，无重试。
 */
export function listPreviewProfiles(
  input: AccountCall,
): Promise<components["schemas"]["RobotProfileList"]> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const response = await input.client.GET("/api/robot-profiles", { signal });
    if (!response.data) throw new Error("请求失败");
    return response.data;
  });
}
