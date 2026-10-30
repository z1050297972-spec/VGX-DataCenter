// 页面统一的时间显示：服务端 UTC 时刻只在显示时转浏览器本地。

/**
 * 把服务端 UTC 时刻格式化为浏览器本地的日期时间文本。
 * @param value - 带时区的 ISO 8601 文本，如 "2026-10-29T12:00:00Z"。
 * @returns 浏览器本地化的日期时间；无法解析时原样返回，不抛错。
 * @throws 无。
 * @sideEffects 无，纯函数（读浏览器区域设置）。
 * @timeSemantics 不读当前时间；同一输入在同一区域设置下输出固定。
 */
export function formatDateTime(value: string): string {
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? value : moment.toLocaleString();
}
