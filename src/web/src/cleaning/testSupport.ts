// 清洗页面测试事实：三个文件、三个段，编号和汇总均手算，不读取真实数据。
import type { ToolList } from "../api/tools";
import type { CleaningPreview, EpisodeReport } from "../api/cleaning";
import type { components } from "../api/schema";

export const fatal: components["schemas"]["Diagnostic"] = {
  level: "error",
  category: "input",
  stage: "清洗预览",
  source: "平台",
  objects: [{ key: "file", value: "broken.mcap" }],
  rule: "cleaning.topic_missing",
  actual: "缺少基准话题",
  expected: "存在基准话题",
  consequence: "文件固定剔除",
  next_step: "检查录制配置后重新预览",
  error_chain: [],
};
const episode: EpisodeReport = {
  file_index: 1,
  segment_index: 0,
  start_frame: 0,
  end_frame: 100,
  frame_count: 100,
  duration_s: 10,
  stamp_span_s: 9.9,
  start_time_s: 1000,
  issues: [],
  fatal_issues: [],
  default_action: "keep",
};
export const preview: CleaningPreview = {
  job_id: "42",
  dataset_id: "dataset-14",
  tool_name: "mcap2lerobot",
  robot_model: "R1",
  binary_sha256: "binary",
  config_sha256: "config",
  rules_sha256: "rules",
  created_at: "2026-11-09T12:00:00Z",
  report: {
    schema_version: 1,
    source_format: "mcap",
    tool_config_sha256: "config",
    rules_sha256: "rules",
    fps: 10,
    reference_topic: "/camera",
    // 特意不同于常见默认值，确保页面展示快照而非自己补阈值。
    rules: {
      sync: {
        default_tolerance_ms: 17,
        max_frame_gap: 2.7,
        max_frame_gap_ms: 270,
        min_episode_frames: 73,
      },
      checks: {
        static_feature: "observation.state",
        long_static_s: 4.5,
        jump_feature: "action",
        frozen_s: 2.25,
        sample_interval_s: 0.75,
        dark_below: 12,
        bright_above: 238,
        severe_checks: ["non_finite", "entire_static"],
        sources: [
          { topic: "/state", static_threshold: 0.002, jump_threshold: 0.7, limits: [[-1.2, 1.3]] },
          { topic: "/gripper", static_threshold: 0.2, jump_threshold: null, limits: null },
          { topic: "/unchecked", static_threshold: null, jump_threshold: null, limits: null },
        ],
      },
    },
    warnings: [],
    summary: {
      files: 3,
      excluded_files: 1,
      episodes: 3,
      excluded_episodes: 1,
      reference_frames: 300,
      kept_frames: 300,
    },
    files: ["broken.mcap", "first.mcap", "last.mcap"].map((path, file_index) => ({
      file_index,
      source_id: "recording-a",
      path,
      // 大小刻意不同，流程卡片必须累计本报告所有文件，包括固定剔除的文件。
      size_bytes: (file_index + 1) * 21_801_234_567,
      mtime_ns: 1000,
      fatal_issues: file_index === 0 ? [fatal] : [],
      warnings: [],
      reference_frames: file_index === 0 ? 0 : file_index === 1 ? 200 : 100,
      kept_frames: file_index === 0 ? 0 : file_index === 1 ? 200 : 100,
      bad_frames: 0,
      gaps: 0,
      short_segments: 0,
      short_frames: 0,
      topics: [
        {
          topic: "/camera",
          tolerance_ms: 12,
          mean_abs_dt_ms: 0,
          max_abs_dt_ms: 0,
          reused_frames: 0,
          bad_frames: 0,
          missing_optional: false,
          image_check: "unchecked_h264",
          image_check_note: "H.264 画面未检查",
        },
      ],
      default_excluded: file_index === 0,
    })),
    episodes: [
      episode,
      {
        ...episode,
        segment_index: 1,
        start_frame: 100,
        end_frame: 200,
        default_action: "exclude",
        issues: [
          {
            check: "non_finite",
            severity: "severe",
            message: "出现非有限值",
            details: {
              count: 2,
              first_time_s: 1,
              ranges: [{ start_s: 1, end_s: 2 }],
              feature: "observation.state",
              topic: "/state",
            },
            diagnostic: fatal,
          },
        ],
      },
      { ...episode, file_index: 2 },
    ],
  },
};
export const cleaningTools: ToolList = {
  items: [
    {
      name: "mcap2lerobot",
      version: "1",
      summary: "转换工具",
      input_format: "mcap",
      output_format: "lerobot",
      output_versions: ["v3.0", "v2.1"],
      robot_models: ["R1", "未登记规则"],
      cleaning_models: ["R1"],
      needs_gpu: true,
      preview_by_tool: false,
      default_space_ratio_percent: 25,
      source_tree_sha256: null,
      status: "可用",
      diagnostics: [],
      program_path: "/tmp/tool",
      sha256_prefix: "binary",
      readme_available: false,
    },
  ],
  lerobot_environment: {
    status: "available",
    expected_version: "0.6.2",
    actual_version: "0.6.2",
    expected_fingerprint: "expected",
    actual_fingerprint: "expected",
    message: null,
  },
};

// M4.6：工具与报告均为内存事实，目录文本只用于显示，不访问文件系统。
export const agibotTools: ToolList = {
  ...cleaningTools,
  items: cleaningTools.items.map((tool) => ({
    ...tool,
    name: "agibot2lerobot",
    input_format: "agibot_native",
    robot_models: ["AgiBot G1 灵巧手", "AgiBot G1"],
    cleaning_models: ["AgiBot G1 灵巧手", "AgiBot G1"],
    preview_by_tool: true,
    default_space_ratio_percent: 137,
    needs_gpu: false,
  })),
};

export const agibotPreview: CleaningPreview = {
  ...preview,
  tool_name: "agibot2lerobot",
  robot_model: "AgiBot G1",
  report: {
    ...preview.report,
    source_format: "agibot_native",
    reference_topic: null,
    rules: {
      sync: null,
      checks: {
        ...preview.report.rules.checks,
        frozen_s: null,
        sample_interval_s: null,
        dark_below: null,
        bright_above: null,
      },
    },
    summary: {
      files: 3,
      excluded_files: 1,
      episodes: 2,
      excluded_episodes: 1,
      reference_frames: 200,
      kept_frames: 200,
    },
    files: preview.report.files.map((file) => ({
      ...file,
      episode_id: String(101 + file.file_index),
      path: `/tmp/agibot/observations/327/${String(101 + file.file_index)}`,
      reference_frames: 100,
      kept_frames: 100,
      topics: [],
      fatal_issues: file.file_index === 0 ? [{ ...fatal, actual: "缺少深度图" }] : [],
      // 体检结果在文件层，严重数值问题在段层；页面必须将两者合并为整集选择。
      default_excluded: file.file_index === 0,
    })),
    episodes: [
      {
        ...episode,
        default_action: "exclude",
        issues: preview.report.episodes.flatMap((item) => item.issues),
      },
      { ...episode, file_index: 2 },
    ],
  },
};

// G2 平台报告沿用真实适配形状：归档一级、非连续源集号、致命集和可调整数值问题分开。
export const g2Tools: ToolList = {
  ...agibotTools,
  items: agibotTools.items.slice(0, 1).map((tool) => ({
    ...tool,
    name: "agibot2lerobot-g2",
    default_space_ratio_percent: 130,
    input_format: "archives",
    robot_models: ["AgiBot G2（g2a）"],
    cleaning_models: ["AgiBot G2（g2a）"],
  })),
};
export const g2Preview: CleaningPreview = {
  ...preview,
  tool_name: "agibot2lerobot-g2",
  robot_model: "AgiBot G2（g2a）",
  report: {
    ...preview.report,
    source_format: "agibot_lerobot21",
    reference_topic: null,
    rules: agibotPreview.report.rules,
    files: preview.report.files.map((file) => ({
      ...file,
      path: `/tmp/task_42/${String(file.file_index)}.tar.gz`,
      episode_id: null,
      topics: [],
    })),
    episodes: preview.report.episodes.map((episode, index) => ({
      ...episode,
      segment_index: index === 1 ? 7 : 0,
      stamp_span_s: null,
      start_time_s: null,
      fatal_issues: index === 0 ? [{ ...fatal, actual: "缺视频或视频为空" }] : [],
      issues: [],
      default_action: index === 0 ? "exclude" : "keep",
    })),
  },
};
