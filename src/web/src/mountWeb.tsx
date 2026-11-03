// 浏览器启动边界：组装主题、QueryClientProvider 与 RouterProvider，不改变业务逻辑。
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ConfigProvider, theme } from "antd";
import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { appQueryClient, router } from "./router";

// 媒体查询是浏览器外部状态；没有 matchMedia 时（例如部分测试环境）使用浅色。
const DARK_QUERY = "(prefers-color-scheme: dark)";

// antd 会在 JS 中预计算派生色，不能用 CSS 变量作为种子；与 shell.css 的 --rdp-* 保持一致，改一处要同步改另一处。
const DARK_THEME_TOKEN = {
  colorPrimary: "#1668dc",
  colorBgContainer: "#1c1c1e",
  colorBgElevated: "#242426",
  colorBgLayout: "#000000",
  borderRadius: 10,
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
  fontFamilyCode: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
};

function subscribeToColorScheme(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);
  return () => {
    media.removeEventListener("change", onChange);
  };
}

function isDarkScheme(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

function AppTheme() {
  const dark = useSyncExternalStore(subscribeToColorScheme, isDarkScheme, () => false);
  return (
    <ConfigProvider
      theme={{
        // 恢复原有变量作用域；浅色不传种子，保留组件预计算 token 的原始值。
        cssVar: { key: "css-var-root" },
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: dark ? DARK_THEME_TOKEN : {},
      }}
    >
      <QueryClientProvider client={appQueryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ConfigProvider>
  );
}

/**
 * 将应用挂载到页面容器。
 *
 * @param container - index.html 中的 root 元素，无单位；null 表示入口 HTML 不完整。
 * @returns 无。
 * @throws Error container 为 null 时同步报错，不尝试挂载。
 * @sideEffects 创建 React 根并绑定当前应用独立的 QueryClient，在容器内渲染路由；页面先确认身份，再发起业务请求。
 * @timeSemantics 每次页面加载只调用一次；健康缓存和超时遵循 useHealth，身份与写请求遵循账号页面契约。
 */
export function mountWeb(container: HTMLElement | null): void {
  if (container === null) {
    throw new Error("缺少页面挂载容器 root");
  }
  createRoot(container).render(<AppTheme />);
}
