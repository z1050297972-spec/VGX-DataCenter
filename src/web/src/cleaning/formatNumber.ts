// 清洗报告的数字展示边界；只格式化显示文本，不改报告事实、选择或转换参数。

// 负责人指定秒数两位、原始跨度和毫秒三位；其余数值保留六位有效数字，兼顾比例长尾与微小阈值。
// 复用标准 Intl，不自行实现小数舍入；不用分组符，便于逐项核对原始计数和时间戳。
const FORMATTERS = {
  seconds: new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: false,
  }),
  span: new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
    useGrouping: false,
  }),
  milliseconds: new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
    useGrouping: false,
  }),
  number: new Intl.NumberFormat("zh-CN", { maximumSignificantDigits: 6, useGrouping: false }),
};
const UNITS = { seconds: " 秒", span: " 秒", milliseconds: " 毫秒", number: "" };

/**
 * 按报告显示约定格式化数值，附上秒或毫秒单位。
 * @param value - 报告数值；null、undefined 和非有限值显示未知。
 * @param format - seconds 为两位秒数，span 为三位秒数，milliseconds 为三位毫秒，number 为紧凑数值。
 * @returns 数值显示文本；未知不伪造为零。
 * @throws 无。
 * @sideEffects 无；不修改输入或表单请求。
 * @timeSemantics 仅格式化，不转换时间基准或物理单位。
 */
export function formatNumber(
  value: number | null | undefined,
  format: "seconds" | "span" | "milliseconds" | "number" = "number",
): string {
  if (value == null || !Number.isFinite(value)) return "未知";
  return FORMATTERS[format].format(value) + UNITS[format];
}
