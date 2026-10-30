// 共用一致性面板（11 Q14、M1-04）；直接展示后端合并结果，不把样例数当问题总数。
import type { ReactElement } from "react";
import { Card, Typography } from "antd";
import type { DatasetPanel } from "../api/datasets";
import { DiagnosticEntries } from "../DiagnosticCard";
import { formatDateTime } from "../time";

const GROUP_LABELS = {
  json: "JSON 本身",
  views: "两个视图之间",
  disk: "JSON 和磁盘之间",
  storage: "存储状况",
} as const;
const SEVERITY_LABELS = { action_required: "需要处理", notice: "提示" } as const;

/**
 * 展示四组两级的一致性发现和前若干样例。
 * @param props - data 为最近扫描发布的面板响应。
 * @param props.data - 最近扫描的完整聚合响应。
 * @returns 各组总数、统一五段诊断和扫描时间，空组保留。
 * @throws 无。
 * @sideEffects 无；面板只报告，不修复。
 * @timeSemantics 显示原 indexed_at，UTC 转浏览器本地，不自行取当前时间冒充扫描时间。
 */
export function ConsistencyPanel(props: {
  /** 完整聚合响应，不是样例子集。 */ data: DatasetPanel;
}): ReactElement {
  return (
    <section aria-label="一致性面板">
      <p>
        扫描时间：
        {props.data.indexed_at ? formatDateTime(props.data.indexed_at) : "未扫描"}
      </p>
      {Object.entries(GROUP_LABELS).map(([group, label]) => (
        <section key={group}>
          <Typography.Title level={3}>{label}</Typography.Title>
          {Object.entries(SEVERITY_LABELS).map(([severity, title]) => (
            <Card key={severity} title={title}>
              {props.data.findings
                .filter((item) => item.group === group && item.severity === severity)
                .map((item) => (
                  <section key={`${item.diagnostics.source}:${item.diagnostics.rule}`}>
                    <p>
                      {item.diagnostics.rule} · 共 {item.diagnostics.total} 条（展示{" "}
                      {item.diagnostics.samples.length} 条）
                    </p>
                    <DiagnosticEntries diagnostics={item.diagnostics.samples} />
                  </section>
                ))}
            </Card>
          ))}
        </section>
      ))}
    </section>
  );
}
