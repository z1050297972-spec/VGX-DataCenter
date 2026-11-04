// M1.5-05 展示入口；与轮询组件分开，避免提交 hook 和查询 hook 相互依赖。
import { createContext, useContext } from "react";
import type { Job } from "../api/jobs";

/** 已提交作业的展示回调；名称由操作入口给出，编号和状态沿用服务端记录。 */
export type ShowJobCard = (job: Job, title: string) => void;
/** 仅保存当前应用会话的展示入口，不写浏览器存储。 */
export const JobCardContext = createContext<ShowJobCard | null>(null);

/**
 * 取得当前登录会话的作业卡片展示入口。
 * @returns 接收已入队 Job 和非空操作名称的回调；同编号只展示一张卡片。
 * @throws Error 未挂载 JobCardsProvider 时表示应用装配缺陷。
 * @sideEffects 调用返回的回调会挂载卡片，读取作业；不导航或取消后台作业。
 * @timeSemantics 卡片只活在当前页面会话，刷新、退出登录或切换账号后清空。
 */
export function useShowJobCard(): ShowJobCard {
  const show = useContext(JobCardContext);
  if (!show) throw new Error("缺少作业卡片 Provider");
  return show;
}
