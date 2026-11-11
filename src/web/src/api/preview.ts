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

/**
 * 提交人工开启或停止预览作业。
 * @param input - 登录客户端、取消信号和机器人永久编号；不传连接信息。
 * @param action - start 开启或 stop 停止。
 * @returns 新作业记录，后续结果由作业查询读取。
 * @throws Error 提交失败、响应缺失或超时，交统一诊断显示。
 * @sideEffects 一次 POST /api/jobs，只有 worker 执行机器人操作。
 * @timeSemantics 提交最多 ACCOUNT_TIMEOUT_MS，不重试、不等待机器人操作完成。
 */
export function submitPreviewJob(
  input: AccountCall<components["schemas"]["RobotResponse"]["robot_id"]>,
  action: "start" | "stop",
): Promise<components["schemas"]["JobResponse"]> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/jobs", {
      body: { type_name: `robot_preview_${action}`, parameters: { robot_id: input.payload } },
      signal,
    });
    if (!response.data) throw new Error("请求失败");
    return response.data;
  });
}
