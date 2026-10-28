// 第 11 张版本链路契约；全部使用注入传输、内存 router 与假时钟，不访问真实服务。
import { it } from "vitest";

// 验证契约：登录后的各业务路由底部显示服务端版本，与命令输出完全一致。
it.skip("所有已登录业务页面显示相同平台版本", () => {
  throw new Error("NotImplementedError");
});

// 验证契约：提交号缺失的服务端文字原样显示“未知”，不在浏览器发现 git。
it.skip("原样显示未知提交号", () => {
  throw new Error("NotImplementedError");
});

// 验证契约：加载和失败分别显示状态，不把 HTTP 失败伪装成未知版本，不影响业务页面。
it.skip("区分加载失败和合法未知版本", () => {
  throw new Error("NotImplementedError");
});

// 验证契约：登录与强制改密路由不请求受保护版本接口。
it.skip("未完成登录或改密时不请求版本", () => {
  throw new Error("NotImplementedError");
});

// 验证契约：60000 毫秒边界后聚焦刷新，同客户端复用缓存，不同客户端完全隔离。
it.skip("缓存过期聚焦刷新且不同应用隔离", () => {
  throw new Error("NotImplementedError");
});

// 验证契约：5 秒超时、卸载取消与取消前无请求；请求结束清定时器，不重试。
it.skip("版本请求超时取消与计时器清理", () => {
  throw new Error("NotImplementedError");
});

// 验证契约：空版本、过长版本、控制字符、错误 JSON 和非 2xx 不能作为正常版本展示。
it.skip("拒绝不合法版本载荷并沿用统一错误边界", () => {
  throw new Error("NotImplementedError");
});
