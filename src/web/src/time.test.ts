// 平台统一时间显示（M1-05）：中文年月日、24 小时制并标明时区。
import { describe, it, expect } from "vitest";
import { formatDateTime } from "./time";

describe("formatDateTime", () => {
  // 契约：UTC 输入按指定时区显示为“年-月-日 时:分:秒 时区”，不依赖本机时区。
  it("按指定时区显示并带时区名", () => {
    expect(formatDateTime("2026-10-29T12:00:00Z", "UTC")).toBe("2026-10-29 12:00:00 UTC");
  });
  // 契约：同一时刻在东八区换算日期和小时，时区标注随之变化，不留英文 AM/PM。
  it("东八区换算后跨日并标注 GMT+8", () => {
    expect(formatDateTime("2026-10-29T20:30:05Z", "Asia/Shanghai")).toBe(
      "2026-10-30 04:30:05 GMT+8",
    );
  });
  // 契约：午夜显示 00 点而不是 24 点。
  it("午夜显示 00 点", () => {
    expect(formatDateTime("2026-10-29T00:00:00Z", "UTC")).toBe("2026-10-29 00:00:00 UTC");
  });
  // 契约：无法解析的时间显示“时间无效”，不显示 Invalid Date 也不抛错。
  it("非法时间显示固定提示", () => {
    expect(formatDateTime("not-a-time", "UTC")).toBe("时间无效");
  });
  // 契约：不传时区时使用浏览器本地时区，且结果仍带时区标注。
  it("默认使用本地时区并带时区标注", () => {
    expect(formatDateTime("2026-10-29T12:00:00Z")).toMatch(
      /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+$/,
    );
  });
});
