// 工单06骨架测试清单；实施时仅用注入传输、固定时钟和内存路由。
import { it } from "vitest";

it.skip("验证契约：createAccountClient创建不发请求、相对基址、same-origin，单次传输且不改全局fetch", () => {
  throw new Error("未实现");
});

it.skip("验证契约：任意接口401包括非法body统一通知未登录处理，仍保留安全错误，不循环跳转", () => {
  throw new Error("未实现");
});

it.skip("验证契约：429保留合法problem和1–60秒Retry-After，非法头安全忽略，不自动重试", () => {
  throw new Error("未实现");
});

it.skip("验证契约：所有操作仅用生成类型与正确method/path/body，口令不进URL或持久缓存", () => {
  throw new Error("未实现");
});

it.skip("验证契约：login成功200并读取安全账号；401未知与错口令同文案；403/422/429及网络失败可展示", () => {
  throw new Error("未实现");
});

it.skip("验证契约：logout成功204清缓存，401同样清理；I/O失败不假装登出成功", () => {
  throw new Error("未实现");
});

it.skip("验证契约：fetchCurrentAccount成功200；401跳登录，502保留错误不当作匿名", () => {
  throw new Error("未实现");
});

it.skip("验证契约：changePassword成功刷新身份并轮换cookie；旧口令400保留身份和当前页，第五次429可展示，真实401跳登录，结束清空秘密", () => {
  throw new Error("未实现");
});

it.skip("验证契约：listAccounts空页、100项上界、末页null及64位文本游标无精度损失", () => {
  throw new Error("未实现");
});

it.skip("验证契约：createAccount成功201刷新列表，409冲突保留表单非秘密字段，结束清空口令", () => {
  throw new Error("未实现");
});

it.skip("验证契约：setAccountRole成功刷新身份和列表，最后管理员409经DiagnosticCard显示", () => {
  throw new Error("未实现");
});

it.skip("验证契约：setAccountStatus停用前已确认，成功刷新，403/409不乐观改变列表", () => {
  throw new Error("未实现");
});

it.skip("验证契约：resetAccountPassword成功强制改密，404/422/网络错误可展示，结束不保留秘密引用", () => {
  throw new Error("未实现");
});

it.skip("验证契约：deleteAccount成功204才删列表项，404/409/网络错误保留列表", () => {
  throw new Error("未实现");
});

it.skip("验证契约：每个API超时10秒、AbortSignal透传、卸载取消且忽略迟到结果，不自动重试写请求", () => {
  throw new Error("未实现");
});

it.skip("验证契约：所有账号错误经toFailureView，原异常和服务端HTML不执行或泄漏", () => {
  throw new Error("未实现");
});

it.skip("验证契约：401/403/429的problem正确标题类别被运行时解析接受，错误组合被拒绝", () => {
  throw new Error("未实现");
});

it.skip("验证契约：Argon2容量不足的502显示安全资源繁忙，不当作G2的429，不自动重试或伪造Retry-After", () => {
  throw new Error("未实现");
});

it.skip("验证契约：changePassword的400及409保留安全problem，不调用onUnauthorized；401仍统一退出，429保留Retry-After", () => {
  throw new Error("未实现");
});
