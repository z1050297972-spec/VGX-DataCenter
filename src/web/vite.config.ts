// Web 构建与单元测试配置（工单 02）；不启动后端，不访问平台数据路径。
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // M1-04：路由动态导入后，React 和 Ant Design 仍被多个页面共同引用。
  // UI 依赖作为整组保留：按大小切开 rc-util 会产生循环块并破坏 KeyCode 初始化顺序。
  // 工单只限制主入口低于 500 kB，较大的 vendor 块保留构建警告，不提高全局阈值。
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "react-runtime",
              test: /node_modules\/(react|react-dom|scheduler)\//,
              priority: 20,
            },
            {
              name: "ui",
              test: /node_modules\/(antd|@ant-design|@rc-component|rc-[^/]+)\//,
            },
          ],
        },
      },
    },
  },
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
