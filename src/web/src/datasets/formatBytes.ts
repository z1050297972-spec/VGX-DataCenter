// 字节数的人读换算，所有显示大小的地方共用（M1-04）。
// 未知值的统一判断：缺失、非有限数、负数都不是字节数。
function isKnown(bytes: number | null | undefined): bytes is number {
  return typeof bytes === "number" && Number.isFinite(bytes) && bytes >= 0;
}
// M1.5-17：页面与第4项统一使用十进制字节单位，达到1 TB才同时展示GB和TB。
const UNIT_BASE = 1000;
const GB_BYTES = UNIT_BASE ** 3;
const TB_BYTES = UNIT_BASE ** 4;
const UNITS = ["B", "KB", "MB"] as const;

/**
 * 把字节数换算成 1000 进制的人读文本。
 * @param bytes - 服务端字节数；null、undefined、非有限数或负数都视为未知。
 * @returns 两位小数；不足1 GB显示B、KB或MB，1 GB至不足1 TB只显示GB，达到1 TB并列显示GB和TB；未知返回「未知」。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 无时间语义。
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (!isKnown(bytes)) return "未知";
  if (bytes >= TB_BYTES)
    return `${(bytes / GB_BYTES).toFixed(2)} GB / ${(bytes / TB_BYTES).toFixed(2)} TB`;
  if (bytes >= GB_BYTES) return `${(bytes / GB_BYTES).toFixed(2)} GB`;
  let value = bytes;
  let unit = 0;
  while (value >= UNIT_BASE && unit < UNITS.length - 1) {
    value /= UNIT_BASE;
    unit += 1;
  }
  if (Number(value.toFixed(2)) >= UNIT_BASE && unit < UNITS.length - 1) {
    value /= UNIT_BASE;
    unit += 1;
  }
  return `${value.toFixed(2)} ${UNITS[unit] ?? "MB"}`;
}

/**
 * 给悬停提示用的精确字节数。
 * @param bytes - 服务端字节数。
 * @returns 带千分位的 `N B`；未知时返回 undefined，让调用方不挂提示。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 无时间语义。
 */
export function exactBytes(bytes: number | null | undefined): string | undefined {
  if (!isKnown(bytes)) return undefined;
  return `${bytes.toLocaleString("en-US")} B`;
}
