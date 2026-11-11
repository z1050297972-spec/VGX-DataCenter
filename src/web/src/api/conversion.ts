// 转换提交边界（M4.5-04）：只能从清洗报告转换，禁止绕过预览直接提交工具。
import type { AccountCall } from "./accounts";
import type { components, operations } from "./schema";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import { toFailureView } from "./problems";

/** 从报告转换的请求体，字段与可选性均以 OpenAPI 为准。 */
export type CleaningConversionInput = components["schemas"]["ConversionOptions"];
/** 剔除段的稳定身份，直接使用生成的文件及段下标结构。 */
export type ExcludedEpisode = components["schemas"]["EpisodeSelection"];

/** 页面提交上下文；路径参数和请求体分别引用生成类型。 */
export interface CleaningConversionSubmission {
  /** 预览作业的规范十进制编号文本，不经 Number 转换。 */
  jobId: operations["convert_from_cleaning_preview"]["parameters"]["path"]["job_id"];
  /** 当前输出选项和剔除选择。 */
  parameters: CleaningConversionInput;
}

/**
 * 按清洗报告和当前剔除选择提交转换。
 * @param input - 预览作业编号、输出版本、空间百分比和 GiB 偏置、稳定的文件及段下标。
 * @returns 新转换作业；服务端再次核对管理员权限及报告有效性。
 * @throws Error 权限、报告过期、参数、网络或超时失败，以统一诊断呈现。
 * @sideEffects POST /api/cleaning-previews/{job_id}/convert；不在浏览器访问数据路径。
 * @timeSemantics 请求最多 JOB_REQUEST_TIMEOUT_MS 毫秒，不等待转换完成，不自动重试。
 */
export function convertFromCleaningPreview(
  input: AccountCall<CleaningConversionSubmission>,
): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/cleaning-previews/{job_id}/convert", {
      params: { path: { job_id: input.payload.jobId } },
      body: input.payload.parameters,
      signal,
    });
    if (!response.data) throw new Error("请求失败", { cause: toFailureView(null) });
    return response.data;
  });
}
