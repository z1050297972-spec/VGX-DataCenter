// 清洗报告数字格式契约：时间和毫秒按约定精度显示，比例去长尾，未知值不伪造为零。
import { expect, it } from "vitest";
import { formatNumber } from "./formatNumber";

it("统一格式化秒、原始跨度、毫秒、比例及未知值", () => {
  expect(formatNumber(15.033333333333333, "seconds")).toBe("15.03 秒");
  expect(formatNumber(15.000111, "span")).toBe("15.000 秒");
  expect(formatNumber(1.23456789, "milliseconds")).toBe("1.235 毫秒");
  expect(formatNumber(0, "seconds")).toBe("0.00 秒");
  expect(formatNumber(0.1 + 0.2)).toBe("0.3");
  expect(formatNumber(0.00000001)).toBe("0.00000001");
  expect(formatNumber(null, "milliseconds")).toBe("未知");
  expect(formatNumber(Number.NaN)).toBe("未知");
});
