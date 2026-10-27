// 09 契约清单；路由行为通过真实 createAppRouter 与内存 history 验证。
import { it } from "vitest";

it.skip("验收2：queued 显示等待 GPU，卡归还后轮询转运行；等待原因不改作业状态标签", () => {
  throw new Error("未实现");
});

it.skip("验收4：running 显示等待导航层写锁，获得锁后等待原因消失", () => {
  throw new Error("未实现");
});

it.skip("作业详情显示分到的物理 GPU 编号，终态仍显示历史卡号，None 明确未分配", () => {
  throw new Error("未实现");
});

it.skip("空编号系统身份不加已删除标记，有编号且同名系统的账号保留账号标记；重新提交显示当前点击账号", () => {
  throw new Error("未实现");
});

it.skip("真实 router 保留既有 /jobs?state=queued&limit=2 搜索行为，新资源显示不破坏筛选", () => {
  throw new Error("未实现");
});

it.skip("取消/中断无 outcome 时保持原有六种结局和进度，不将等待映射为新终态", () => {
  throw new Error("未实现");
});
