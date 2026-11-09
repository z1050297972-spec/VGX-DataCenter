// 临时，生成类型就绪后删除。M4.5-04 接口尚未进入 OpenAPI；报告字段以
// src/rdp/jobs/cleaning/models.py 为准，仅在此补充类型，继续复用现有客户端和诊断。
import type { components, paths } from "./schema";
import type { Job } from "./jobs";

type Diagnostic = components["schemas"]["Diagnostic"];
export interface TimeRange {
  start_s: number;
  end_s: number;
}
export interface IssueDetails {
  count: number;
  first_time_s: number | null;
  ranges: TimeRange[];
  feature: string | null;
  topic: string | null;
}
export interface EpisodeIssue {
  check: string;
  severity: "severe" | "hint";
  message: string;
  details: IssueDetails;
  diagnostic: Diagnostic;
}
export interface TopicAlignment {
  topic: string;
  tolerance_ms: number;
  mean_abs_dt_ms: number | null;
  max_abs_dt_ms: number | null;
  reused_frames: number;
  bad_frames: number;
  missing_optional: boolean;
  image_check: "not_applicable" | "sampled" | "unchecked_h264";
  image_check_note: string | null;
}
export interface EpisodeReport {
  file_index: number;
  segment_index: number;
  start_frame: number;
  end_frame: number;
  frame_count: number;
  duration_s: number;
  stamp_span_s: number;
  start_time_s: number;
  issues: EpisodeIssue[];
  default_action: "keep" | "exclude";
}
export interface FileReport {
  file_index: number;
  source_id: string;
  path: string;
  size_bytes: number | null;
  mtime_ns: number | null;
  fatal_issues: Diagnostic[];
  warnings: Diagnostic[];
  reference_frames: number;
  kept_frames: number;
  bad_frames: number;
  gaps: number;
  short_segments: number;
  short_frames: number;
  topics: TopicAlignment[];
  default_excluded: boolean;
}
export interface CleaningSummary {
  files: number;
  excluded_files: number;
  episodes: number;
  excluded_episodes: number;
  reference_frames: number;
  kept_frames: number;
}
export interface CleaningReport {
  schema_version: 1;
  tool_config_sha256: string;
  rules_sha256: string;
  fps: number;
  reference_topic: string;
  files: FileReport[];
  episodes: EpisodeReport[];
  summary: CleaningSummary;
  warnings: Diagnostic[];
}
export interface CleaningPreview {
  job_id: number;
  dataset_id: string;
  tool_name: string;
  robot_model: string;
  binary_sha256: string;
  config_sha256: string;
  rules_sha256: string;
  created_at: string;
  report: CleaningReport;
}
export interface CleaningPreviewInput {
  dataset_id: string;
  source_ids: string[];
  robot_model: string;
}
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
export interface CleaningPreviewSubmission {
  tool: string;
  parameters: CleaningPreviewInput;
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
export type ToolSummary = components["schemas"]["ToolSummaryResponse"] & {
  cleaning_models: string[];
};
export interface ToolList {
  items: ToolSummary[];
  lerobot_environment: LeRobotEnvironment;
}

// 手工路径仅为 openapi-fetch 的编译期补充，不另造传输或绕过账号 401 处理。
type JsonResponse<T> = { headers: { [name: string]: unknown }; content: { "application/json": T } };
type PostOperation<P, B> = {
  parameters: { path: P };
  requestBody: { content: { "application/json": B } };
  responses: { 200: JsonResponse<Job>; 201: JsonResponse<Job> };
};
export type CleaningPaths = Omit<paths, "/api/tools" | "/api/jobs/convert/{tool_name}"> & {
  "/api/tools": { get: { responses: { 200: JsonResponse<ToolList> } } };
  "/api/jobs/cleaning-preview/{tool_name}": {
    post: PostOperation<{ tool_name: string }, CleaningPreviewInput>;
  };
  "/api/cleaning-previews/{job_id}": {
    get: {
      parameters: { path: { job_id: string } };
      responses: { 200: JsonResponse<CleaningPreview> };
    };
  };
  "/api/cleaning-previews/{job_id}/convert": {
    post: PostOperation<{ job_id: string }, CleaningConversionInput>;
  };
};
