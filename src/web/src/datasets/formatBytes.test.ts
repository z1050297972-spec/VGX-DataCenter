// 字节换算共用函数的契约：1024 进制、1 到 2 位小数、未知值不显示成 0。
import { describe, it, expect } from "vitest";
import { exactBytes, formatBytes } from "./formatBytes";

describe("formatBytes", () => {
  // 契约：0 字节是真实的零，显示 0 B。
  it("0 显示为 0 B", () => {
    expect(formatBytes(0)).toBe("0 B");
  });
  // 契约：不足 1024 的值保持整数字节，1024 起进位到 KiB。
  it("1023 仍是 B，1024 进位为 1.0 KiB", () => {
    expect(formatBytes(1023)).toBe("1023 B");
    expect(formatBytes(1024)).toBe("1.0 KiB");
    expect(formatBytes(1536)).toBe("1.5 KiB");
  });
  // 契约：逐级进位，每级边界都按 1024 换算。
  it("各级边界按 1024 进位", () => {
    // 舍入后到 1024 时直接进位，不显示 1024.0 KiB。
    expect(formatBytes(1024 ** 2 - 1)).toBe("1.0 MiB");
    expect(formatBytes(1024 ** 2 - 100)).toBe("1023.9 KiB");
    expect(formatBytes(1024 ** 2)).toBe("1.0 MiB");
    expect(formatBytes(1024 ** 3)).toBe("1.0 GiB");
    expect(formatBytes(1024 ** 4)).toBe("1.0 TiB");
  });
  // 契约：最多两位小数，末尾多余的零去掉但至少留一位。
  it("保留 1 到 2 位小数", () => {
    expect(formatBytes(2048)).toBe("2.0 KiB");
    expect(formatBytes(1024 + 10)).toBe("1.01 KiB");
    expect(formatBytes(14 * 1024 ** 2)).toBe("14.0 MiB");
  });
  // 契约：TiB 量级；超过 TiB 也停在 TiB，不引入更大单位。
  it("TiB 量级换算", () => {
    expect(formatBytes(35_769_634_510_578)).toBe("32.53 TiB");
    expect(formatBytes(2048 * 1024 ** 4)).toBe("2048.0 TiB");
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
