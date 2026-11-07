// M1-04 可分享浏览状态；接口字段类型来自生成契约，布局 B/C 复用本模块。
import { UNLABELED_FILTER } from "./classificationLabels";
import type { DatasetQuery } from "../api/datasets";

export type DatasetSearch = Pick<
  DatasetQuery,
  "data_origin" | "robot_model" | "offset" | "fps" | "entry_path" | "scene" | "tasks"
> & {
  /** URL 错误仅作页面提示，不传 API。 */ invalidDatasetSearch?: true;
  /** 顶栏一致性面板是否打开。 */ panel?: boolean;
  /** 当前详情入口，不用于筛选。 */ selected?: string;
  /** 仅决定树页签。 */ tree_view?: "task" | "format" | "scene";
};

/**
 * 从真实 Router 的 search 输入取得浏览条件。
 * @param input - Router 已解码的参数，不能假定值全是字符串。
 * @returns 类型化筛选；无效 FPS 或偏移返回 invalidDatasetSearch，不回显原始输入。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 同步纯转换，无时间参数。
 */
export function validateDatasetSearch(input: Record<string, unknown>): DatasetSearch {
  try {
    return {
      panel: input.panel === true ? true : undefined,
      selected: optionalText(input.selected),
      tree_view:
        input.tree_view === "scene" ? "scene" : input.tree_view === "task" ? "task" : "format",
      entry_path: optionalText(input.entry_path),
      fps: input.fps === "unknown" ? "unknown" : optionalInteger(input.fps),
      robot_model: optionalText(input.robot_model),
      data_origin: optionalOrigin(input.data_origin),
      scene: optionalText(input.scene),
      tasks: optionalTasks(input.tasks),
      offset: optionalInteger(input.offset),
    };
  } catch {
    return { invalidDatasetSearch: true };
  }
}

// Router 的非字符串值不能被悄悄丢掉，否则坏筛选会显示全量数据。
function optionalText(value: unknown): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !value.trim()) throw new Error("筛选参数不合法");
  return value;
}

// FPS 和分页偏移均为非负整数；数值范围的最终判断仍由后端负责。
function optionalInteger(value: unknown): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new Error("筛选参数不合法");
  return value;
}

// 来源只接受已合并契约的六个稳定键；错误值不能默认为未知。
function optionalOrigin(value: unknown): DatasetQuery["data_origin"] {
  if (value === undefined) return undefined;
  if (
    value === "real" ||
    value === "umi" ||
    value === "ego" ||
    value === "simulation" ||
    value === "open_source" ||
    value === "unknown"
  )
    return value;
  throw new Error("筛选参数不合法");
}

// Router 把数组按 JSON 编解码；错误形状或“未标注+具体任务”不能默默丢掉筛选。
function optionalTasks(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new Error("筛选参数不合法");
  const values: unknown[] = value;
  if (!values.every((item): item is string => typeof item === "string" && item.length > 0))
    throw new Error("筛选参数不合法");
  if (values.includes(UNLABELED_FILTER) && new Set(values).size > 1)
    throw new Error("筛选参数不合法");
  return [...new Set(values)];
}
