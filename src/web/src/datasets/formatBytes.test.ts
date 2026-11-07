// 字节换算共用函数的契约：1000 进制、两位小数、GB/TB并列、未知值不显示成 0。
import { describe, it, expect } from "vitest";
import { exactBytes, formatBytes } from "./formatBytes";

describe("formatBytes", () => {
  // M1.5-17 验收：页面大小与第4项采用同一组十进制 GB/TB 数值。
  it("统计大小与第4项写法一致", () => {
    expect(formatBytes(119_642_823_842)).toBe("119.64 GB / 0.12 TB");
  });
  // 契约：小于1 GB只显示一个十进制单位，所有数值保留两位小数。
  it("B、KB、MB按1000进位并保留两位小数", () => {
    expect(formatBytes(0)).toBe("0.00 B");
    expect(formatBytes(999)).toBe("999.00 B");
    expect(formatBytes(1000)).toBe("1.00 KB");
    expect(formatBytes(2048)).toBe("2.05 KB");
    expect(formatBytes(1_000_000)).toBe("1.00 MB");
    expect(formatBytes(999_999_999)).toBe("1000.00 MB");
  });
  // 契约：从1 GB起并列显示GB和TB，TB级也保留两个单位。
  it("GB边界与TB量级同时显示GB和TB", () => {
    expect(formatBytes(1_000_000_000)).toBe("1.00 GB / 0.00 TB");
    expect(formatBytes(1_000_000_000_000)).toBe("1000.00 GB / 1.00 TB");
    expect(formatBytes(35_769_634_510_578)).toBe("35769.63 GB / 35.77 TB");
  });
  // 契约：未知（null、undefined、非有限数、负数）显示未知，绝不显示成 0。
  it("未知值不显示成 0", () => {
    expect(formatBytes(null)).toBe("未知");
    expect(formatBytes(undefined)).toBe("未知");
    expect(formatBytes(Number.NaN)).toBe("未知");
    expect(formatBytes(-1)).toBe("未知");
    expect(formatBytes(null)).not.toContain("0");
  });
});

describe("exactBytes", () => {
  // 契约：悬停提示给出带千分位的精确字节数；未知时没有提示。
  it("给出精确字节，未知返回 undefined", () => {
    expect(exactBytes(35_769_634_510_578)).toBe("35,769,634,510,578 B");
    expect(exactBytes(0)).toBe("0 B");
    expect(exactBytes(null)).toBeUndefined();
  });
});
