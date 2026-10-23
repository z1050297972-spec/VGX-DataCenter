// Web 构建与单元测试配置（工单 02）；不启动后端，不访问平台数据路径。
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // 构建和测试缓存都放入已忽略的依赖目录，检查不能弄脏工作区。
  cacheDir: "node_modules/.vite",
  server: {
    proxy: {
      // M0 spec S3 固定开发后端端口 8600；浏览器请求仍使用相对路径。
      "/api": "http://127.0.0.1:8600",
    },
  },
  test: {
    environment: "jsdom",
    // 沿用 A2 已验证的线程池；0012 已授权本地通信，不需要修改 asyncio 或 socket。
    pool: "threads",
    setupFiles: ["./src/testSetup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    clearMocks: true,
    restoreMocks: true,
  },
});
