// 只用于测试的独立响应样本；字段来自生成类型，时间与路径为人工给定。
import type { StorageRoots } from "../api/storage";

export const storageRoots: StorageRoots = {
  items: [
    {
      name: "disk",
      path: "/fake/disk",
      writable: false,
      online: true,
      reason: null,
      checked_at: "2026-10-27T12:00:00Z",
    },
  ],
};
