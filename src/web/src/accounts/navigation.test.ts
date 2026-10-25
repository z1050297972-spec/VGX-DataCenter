// 工单06骨架测试清单；实施时仅用注入传输、固定时钟和内存路由。
import { it } from "vitest";

it.skip("验证契约：safeReturnTo允许单斜杠站内path/query/hash，非法或缺失回退/", () => {
  throw new Error("未实现");
});

it.skip("验证契约：safeReturnTo拒绝外部URL、//、反斜杠、控制符、编码外跳、多重编码、坏编码和超长2048输入", () => {
  throw new Error("未实现");
});

it.skip("验证契约：safeReturnTo拒绝登录/改密循环地址和重复参数数组，登录及改密完成后再次校验", () => {
  throw new Error("未实现");
});

it.skip("验证契约：guardAccountRoute匿名任何页面跳登录并保留安全回跳，未决身份不渲染受保护内容", () => {
  throw new Error("未实现");
});

it.skip("验证契约：guardAccountRoute强制改密优先到改密页，不能访问首页或管理员页；完成后返回安全目标", () => {
  throw new Error("未实现");
});

it.skip("验证契约：guardAccountRoute成员进入管理员页回首页并显示权限提示，管理员允许", () => {
  throw new Error("未实现");
});

it.skip("验证契约：guardAccountRoute的502等错误显示诊断而非跳登录，取消忽略迟到身份", () => {
  throw new Error("未实现");
});

it.skip("验证契约：handleUnauthorized并发401合并为一次replace并清除Query身份、账号、详情及mutation缓存", () => {
  throw new Error("未实现");
});

it.skip("验证契约：handleUnauthorized已在登录页不重定向，保留错口令诊断；切换账号无旧数据残留", () => {
  throw new Error("未实现");
});

it.skip("验证契约：前端以TanStack Router和内存history执行守卫，不直接操作window.location或存储秘密", () => {
  throw new Error("未实现");
});

it.skip("验证契约：身份Query保持staleTime:0和refetchOnWindowFocus:true，无定时轮询；切回窗口重查身份，收到401调用统一handleUnauthorized", () => {
  throw new Error("未实现");
});
