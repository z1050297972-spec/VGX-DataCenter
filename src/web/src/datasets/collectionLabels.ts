// M3-03 状态标签；只负责显示，不承担接口校验。
import type { CollectionStatus } from "../api/collection";
/** 工单规定的状态标签，编辑和只读详情共用。 */
export const COLLECTION_STATUS_LABELS: Record<CollectionStatus, string> = {
  planned: "计划中",
  collecting: "采集中",
  done: "已完成",
};
