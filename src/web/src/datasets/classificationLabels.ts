// 分类名称是服务端词表的纯投影；不复制编码表，不从 Markdown 推测分类（M1.5-03）。
import type { components } from "../api/schema";

type Term = components["schemas"]["VocabularyTerm"];
/** 筛选协议的空标注专用值，区别于词表编码 unknown；不能写成数据集标注。 */
export const UNLABELED_FILTER = "unlabeled";

/**
 * 将场景或单个任务的编码投影为中文名。
 * @param value - 导航层顶层原值；非文本与空串表示未标注。
 * @param terms - 服务端词表；未加载或编码不在词表时保留原值。
 * @returns 中文名称、原编码或“未标注”，不会从其他字段猜值。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 名称属于传入词表快照，无时钟与缓存。
 */
export function classificationName(value: unknown, terms: readonly Term[] | undefined): string {
  if (typeof value !== "string" || !value) return "未标注";
  return terms?.find((term) => term.code === value)?.name ?? value;
}

/**
 * 将场景或任务数组按保存顺序显示为中文名称。
 * @param value - 顶层 scene 或 tasks 数组原值，只投影非空文本项，与扫描读取口径一致。
 * @param terms - 服务端对应分类词表；没有对应项时保留原编码。
 * @returns 顿号连接的去重分类名称；无有效分类时返回“未标注”。
 * @throws 无。
 * @sideEffects 无，不改原数组。
 * @timeSemantics 只依赖传入原值和词表快照。
 */
export function classificationTasks(value: unknown, terms: readonly Term[] | undefined): string {
  if (!Array.isArray(value)) return "未标注";
  const values: unknown[] = value;
  const codes = values.filter(
    (item): item is string => typeof item === "string" && item.length > 0,
  );
  return [...new Set(codes)].map((code) => classificationName(code, terms)).join("、") || "未标注";
}

/**
 * 显示多个场景，并兼容尚未保存为数组的旧导航原文。
 * @param value - 顶层 scene 原值，允许旧字符串或新数组；缺失表示未标注。
 * @param terms - 服务端场景词表，没有中文名时保留原值。
 * @returns 按保存顺序以顿号连接的名称，空场景显示“未标注”。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 只读取传入的原文和词表快照。
 */
export function classificationScenes(value: unknown, terms: readonly Term[] | undefined): string {
  return classificationTasks(typeof value === "string" ? [value.trim()] : value, terms);
}
