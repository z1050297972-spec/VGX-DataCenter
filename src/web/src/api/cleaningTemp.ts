// 临时，生成类型就绪后删除。仅补充 M4.5 第 03 张尚未生成的转换与 LeRobot 环境契约。
// 第 02 张的预览路径和报告全部继承 schema.d.ts，不在此覆盖。
import type { components, paths } from "./schema";
import type { Job } from "./jobs";

export interface ExcludedEpisode {
  file_index: number;
  segment_index: number;
}
export interface CleaningConversionInput {
  output_format?: string;
  space_ratio_percent: number;
  space_reserve_gib: number;
  excluded_files: number[];
  excluded_episodes: ExcludedEpisode[];
}
export interface CleaningConversionParameters extends CleaningConversionInput {
  cleaning_preview_job_id: number;
}
export interface CleaningConversionSubmission {
  jobId: string;
  parameters: CleaningConversionInput;
}
export interface LeRobotEnvironment {
  status: "unconfigured" | "available" | "mismatch" | "error";
  expected_version: string;
  actual_version: string | null;
  expected_fingerprint: string;
  actual_fingerprint: string | null;
  message: string | null;
}
/** 工具列表的唯一临时扩展是 LeRobot 环境；摘要含清洗型号，直接沿用生成类型。 */
export type ToolList = components["schemas"]["ToolListResponse"] & {
  lerobot_environment: LeRobotEnvironment;
};

// 手工路径仅为 openapi-fetch 的编译期补充，不另造传输或绕过账号 401 处理。
type JsonResponse<T> = { headers: { [name: string]: unknown }; content: { "application/json": T } };
type PostOperation<P, B> = {
  parameters: { path: P };
  requestBody: { content: { "application/json": B } };
  responses: { 200: JsonResponse<Job>; 201: JsonResponse<Job> };
};
export type CleaningPaths = Omit<paths, "/api/tools" | "/api/jobs/convert/{tool_name}"> & {
  "/api/tools": { get: { responses: { 200: JsonResponse<ToolList> } } };
  "/api/cleaning-previews/{job_id}/convert": {
    post: PostOperation<{ job_id: string }, CleaningConversionInput>;
  };
};
