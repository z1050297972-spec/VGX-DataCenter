// 字节数的人读换算，所有显示大小的地方共用（M1-04）。
// 未知值的统一判断：缺失、非有限数、负数都不是字节数。
function isKnown(bytes: number | null | undefined): bytes is number {
  return typeof bytes === "number" && Number.isFinite(bytes) && bytes >= 0;
}
const UNITS = ["B", "KiB", "MiB", "GiB", "TiB"] as const;

/**
 * 把字节数换算成 1024 进制的人读文本。
 * @param bytes - 服务端字节数；null、undefined、非有限数或负数都视为未知。
 * @returns 例如 `32.53 TiB`；不足 1024 为整数 B；未知返回「未知」，不会显示成 0。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 无时间语义。
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (!isKnown(bytes)) return "未知";
  if (bytes < 1024) return `${String(Math.round(bytes))} B`;
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (Number(value.toFixed(2)) >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text = value.toFixed(2).replace(/0$/, "");
  return `${text} ${UNITS[unit] ?? "TiB"}`;
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
