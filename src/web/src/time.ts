// 平台统一的时间显示（M1-05）：替换各页面零散的 toLocaleString()。
// 为什么不直接用 toLocaleString：它的格式和时区标注随浏览器语言变化，无法保证中文、也不标时区。

/** 无法解析的时间的固定显示；不展示 Invalid Date，也不让页面因坏数据崩溃。 */
export const INVALID_TIME_TEXT = "时间无效";

/**
 * 把 UTC 时间字符串显示为“年-月-日 时:分:秒 时区”，24 小时制。
 * @param value - 接口返回的 ISO 8601 时间（含时区偏移）。
 * @param timeZone - IANA 时区名；省略则用浏览器本地时区。仅测试需要显式传入。
 * @returns 如 `2026-10-29 12:00:00 UTC`、`2026-10-30 04:30:05 GMT+8`；非法输入返回 INVALID_TIME_TEXT。
 * @throws 无；非法时间和非法时区名都按“时间无效”处理。
 * @sideEffects 无。
 * @timeSemantics 只做显示换算，不改变时刻；时区名取自浏览器的 zh-CN 短名。
 */
export function formatDateTime(value: string, timeZone?: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return INVALID_TIME_TEXT;
  try {
    const parts = new Intl.DateTimeFormat("zh-CN", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      // hourCycle h23 保证午夜是 00 而不是 24。
      hourCycle: "h23",
      timeZoneName: "short",
    }).formatToParts(date);
    const part = (type: Intl.DateTimeFormatPartTypes): string =>
      parts.find((item) => item.type === type)?.value ?? "";
    return (
      `${part("year")}-${part("month")}-${part("day")} ` +
      `${part("hour")}:${part("minute")}:${part("second")} ${part("timeZoneName")}`
    );
  } catch {
    return INVALID_TIME_TEXT;
  }
}

/**
 * 把表单里手填的宽松时间补成带偏移的 ISO 8601，交给路由严格校验。
 * @param value - 用户输入；可只写日期、用空格代替 T、省略秒或时区。
 * @returns 省略的时分秒补 0、省略的时区补浏览器本地偏移；不认识的格式原样返回，由 search 校验拒绝。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 无时区的输入按浏览器本地墙钟解释，偏移取该时刻本身（跨夏令时也正确）。
 */
export function withLocalOffset(value: string): string {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(\.\d{1,6})?)?)?(Z|[+-]\d{2}:\d{2})?$/.exec(
      value.trim(),
    );
  if (!match) return value;
  const [, y = "", mo = "", d = "", h = "00", mi = "00", sec = "00", frac = "", zone] = match;
  const local = `${y}-${mo}-${d}T${h}:${mi}:${sec}`;
  return local + frac + (zone ?? localOffset(local));
}

// 按该墙钟时刻本身取浏览器偏移；无时区 ISO 文本在 JS 中按本地时间解析。
function localOffset(local: string): string {
  const minutes = -new Date(local).getTimezoneOffset();
  const abs = Math.abs(minutes);
  const pad = (n: number): string => String(n).padStart(2, "0");
  return (minutes < 0 ? "-" : "+") + pad(Math.floor(abs / 60)) + ":" + pad(abs % 60);
}
