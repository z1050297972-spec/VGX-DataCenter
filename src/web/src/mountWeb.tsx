// 浏览器启动边界：组装主题、QueryClientProvider 与 RouterProvider，不改变业务逻辑。
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ConfigProvider, theme, type ThemeConfig } from "antd";
import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { appQueryClient, router } from "./router";

// 媒体查询是浏览器外部状态；没有 matchMedia 时（例如部分测试环境）使用浅色。
const DARK_QUERY = "(prefers-color-scheme: dark)";

// antd 预计算派生色必须使用字面量种子；以下值与 shell.css 的 --rdp-* 同步
// （结构沿用 ui-style 08；浅色取值为 ui-style 09「暖色有机」，深色仍是 08）。
// 字体、圆角和动效为两种主题共用；CSS 变量继续承担系统偏好与 plain 的即时降级。
// 圆角对应 --rdp-radius-control / -small / -popup；卡片和弹窗的 24px 在组件 token 里单独给。
const STUDIO_THEME_TOKEN = {
  borderRadius: 12,
  borderRadiusSM: 6,
  borderRadiusLG: 16,
  fontFamily:
    '"Inter Tight", "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif',
  fontFamilyCode: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  motionEaseOut: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseInOut: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseOutBack: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseInBack: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseInQuint: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseOutQuint: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseOutCirc: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionEaseInOutCirc: "cubic-bezier(0.22, 1, 0.36, 1)",
  motionDurationFast: "0.22s",
  motionDurationMid: "0.22s",
  motionDurationSlow: "0.22s",
};
const LIGHT_THEME_TOKEN = {
  ...STUDIO_THEME_TOKEN,
  // 强调色是深橙；珊瑚红只用于停靠菜单和背景色块，不进 antd 种子（和危险红分不开）。
  colorPrimary: "#a64b08",
  colorPrimaryHover: "#8f3f05",
  colorPrimaryActive: "#783403",
  colorPrimaryBg: "#ffe9d6",
  colorPrimaryBgHover: "#ffdcc0",
  colorPrimaryBorder: "#f3c39c",
  colorPrimaryBorderHover: "#e9a56f",
  colorPrimaryText: "#a64b08",
  colorPrimaryTextHover: "#8f3f05",
  colorPrimaryTextActive: "#783403",
  colorLink: "#a64b08",
  colorLinkHover: "#8f3f05",
  colorLinkActive: "#783403",
  colorBgContainer: "#ffffff",
  colorBgElevated: "#ffffff",
  colorBgLayout: "#fffaf4",
  colorText: "#33272a",
  colorTextHeading: "#33272a",
  colorTextSecondary: "#6b5b57",
  colorBorder: "#ebc5ac",
  colorBorderSecondary: "#f3dccb",
  colorSplit: "#f3dccb",
};
// 深色保持 ui-style 08 的取值，工单 09 只换浅色。
const DARK_THEME_TOKEN = {
  ...STUDIO_THEME_TOKEN,
  // 仅文本强调色固定；复选框、开关及禁用态由 darkAlgorithm 推导。
  colorPrimary: "#5b74f0",
  colorPrimaryText: "#93a6ff",
  colorPrimaryTextHover: "#b3c0ff",
  colorPrimaryTextActive: "#7389f5",
  colorLink: "#93a6ff",
  colorLinkHover: "#b3c0ff",
  colorLinkActive: "#7389f5",
  colorBgContainer: "#131314",
  colorBgElevated: "#1a1a1c",
  colorBgLayout: "#0b0b0c",
  colorText: "#ededec",
  colorTextHeading: "#ededec",
  colorTextSecondary: "#98989d",
  colorBorder: "#3a3a3d",
  colorBorderSecondary: "#262628",
  colorSplit: "#262628",
};

// 组件 token 可直接消费 CSS 变量，保留主题切换和降级；不改全局 colorTextLightSolid。
const STUDIO_COMPONENTS: ThemeConfig["components"] = {
  Button: {
    colorPrimary: "var(--rdp-button-bg)",
    colorPrimaryHover: "var(--rdp-button-hover)",
    colorPrimaryActive: "var(--rdp-button-active)",
    primaryColor: "var(--rdp-button-text)",
    defaultBorderColor: "var(--rdp-border-strong)",
    defaultHoverBorderColor: "var(--rdp-accent-hover)",
    defaultHoverColor: "var(--rdp-accent-hover)",
    defaultActiveBorderColor: "var(--rdp-accent-active)",
    defaultActiveColor: "var(--rdp-accent-active)",
    fontWeight: 500,
    defaultShadow: "none",
    primaryShadow: "none",
    dangerShadow: "none",
  },
  // 卡片和弹窗用 --rdp-radius-card 的 24px；全局 borderRadiusLG 留给下拉、气泡等弹层。
  Card: { headerFontSize: 12, headerFontSizeSM: 12, borderRadiusLG: 24 },
  Modal: { borderRadiusLG: 24 },
  // 状态徽章仅去掉填充，Success/Error/Warning 的文字和边框 token 保持不变。
  Tag: {
    defaultBg: "transparent",
    colorSuccessBg: "transparent",
    colorErrorBg: "transparent",
    colorWarningBg: "transparent",
    colorInfoBg: "transparent",
    fontFamily: "var(--rdp-mono)",
    fontSizeSM: 11,
  },
  Breadcrumb: {
    itemColor: "var(--rdp-muted)",
    lastItemColor: "var(--rdp-muted)",
    linkColor: "var(--rdp-muted)",
    linkHoverColor: "var(--rdp-accent-hover)",
    separatorColor: "var(--rdp-muted)",
  },
  Table: {
    headerBg: "transparent",
    headerColor: "var(--rdp-muted)",
    headerSplitColor: "transparent",
    rowHoverBg: "var(--rdp-hover)",
    // 工单 08 统一三种密度的上下内边距为 13px；不改变列宽或滚动逻辑。
    cellPaddingBlock: 13,
    cellPaddingBlockMD: 13,
    cellPaddingBlockSM: 13,
  },
  // 选中项：表面色滑块加强调色文字；未选项用次要色，在次级表面上仍有 5.66:1。
  Segmented: {
    trackBg: "var(--rdp-subtle)",
    itemColor: "var(--rdp-muted)",
    itemHoverColor: "var(--rdp-text)",
    itemSelectedBg: "var(--rdp-elevated)",
    itemSelectedColor: "var(--rdp-accent)",
  },
  // 墨条用强调色；选中页签仍是正文色加粗，不只靠颜色区分。
  Tabs: {
    inkBarColor: "var(--rdp-accent)",
    itemSelectedColor: "var(--rdp-text)",
    itemHoverColor: "var(--rdp-text)",
  },
  Tree: {
    nodeSelectedBg: "var(--rdp-accent-soft)",
    nodeSelectedColor: "var(--rdp-accent-on-soft)",
  },
  Progress: { remainingColor: "var(--rdp-subtle)" },
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
        // 保留既有变量作用域和系统主题订阅，只替换视觉 token。
        cssVar: { key: "css-var-root" },
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: dark ? DARK_THEME_TOKEN : LIGHT_THEME_TOKEN,
        components: STUDIO_COMPONENTS,
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
