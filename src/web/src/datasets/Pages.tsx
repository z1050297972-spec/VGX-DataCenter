// 数据集页面（M1-04、M1-05）：装配共用状态与部件，在布局 A、B、C 之间切换；不承担索引计算或导航层写入。
import type { ReactElement } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { Affix, Alert, Breadcrumb, Button, Card, Flex, Segmented, Typography } from "antd";
import { DATASET_PAGE_SIZE } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { StorageWarnings } from "./StorageWarnings";
import { useDatasetBrowser, useDatasetLayout } from "./queries";
import { BrowserFilters } from "./browserState";
import { LayoutA } from "./LayoutA";
import { LayoutB } from "./LayoutB";
import { LayoutC } from "./LayoutC";
import type { DatasetLayout } from "../api/datasets";
import { CreateDatasetEntry } from "./CreationEntries";
import "./browser.css";

const route = getRouteApi("/datasets");

/**
 * 显示登录账号的数据集浏览页：筛选、布局切换，以及布局 A、B 或 C。
 * @returns 账号上次选的布局（读不到时为 A）；非法 URL 显示可修正提示，不发数据请求。
 * @throws 无；HTTP 错误通过 DiagnosticCard 展示。
 * @sideEffects 经共用查询读取索引及所选入口；筛选、选中入口、视图、面板写入 URL；切换布局向 /api/datasets/layout 保存。
 * @timeSemantics 索引读取不轮询；离页取消请求，大小沿用服务端统计时刻；切换布局不重新请求索引。
 */
export function DatasetsPage(): ReactElement {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  if (search.invalidDatasetSearch)
    return (
      <section>
        <Typography.Title level={2}>数据集浏览</Typography.Title>
        <CreateDatasetEntry />
        <Alert type="error" title="数据集筛选参数不合法" />
        <Button
          onClick={() => {
            void navigate({ search: {}, replace: true });
          }}
        >
          重置筛选
        </Button>
      </section>
    );
  return <BrowserContent />;
}

// 列表、树、面板各自保留错误，单个请求失败不能遮住其他可用内容。
// 查询放在这一层，切换布局只换排布，不重新请求，也不丢 URL 里的筛选和选中项。
function BrowserContent(): ReactElement {
  const search = route.useSearch();
  const layout = useDatasetLayout();
  const query = useDatasetBrowser({
    robot_type: search.robot_type,
    robot_model_id: search.robot_model_id,
    data_origin: search.data_origin,
    scene: search.scene,
    tasks: search.tasks,
    fps: search.fps,
    offset: search.offset,
    entry_path: search.entry_path,
    limit: DATASET_PAGE_SIZE,
  });
  return (
    <section>
      <Flex justify="space-between" align="center" gap="middle" wrap className="browser-header">
        <div>
          <Breadcrumb items={[{ title: "数据集" }, { title: "浏览" }]} />
          <Typography.Title level={2} className="browser-page-title">
            数据集浏览
          </Typography.Title>
        </div>
        <Flex align="center" gap="middle" wrap>
          {!layout.pending && (
            <Segmented<DatasetLayout>
              aria-label="布局切换"
              name="dataset-layout"
              value={layout.layout}
              onChange={layout.choose}
              options={[
                { value: "A", label: "布局 A" },
                { value: "B", label: "布局 B" },
                { value: "C", label: "布局 C" },
              ]}
            />
          )}
          <CreateDatasetEntry />
        </Flex>
      </Flex>
      {query.panel.data && <StorageWarnings roots={query.panel.data.storage_roots} />}
      {layout.loadError && (
        <>
          <Alert
            type="warning"
            title="布局偏好未能读取"
            description="已使用布局 A，可手动选择其他布局。"
          />
          <DiagnosticCard failure={toFailureView(layout.loadError)} />
        </>
      )}
      {layout.saveError && (
        <>
          <Alert
            type="warning"
            title="布局偏好未能保存"
            description="本次会话仍使用所选布局，下次登录可能恢复为之前保存的布局。"
          />
          <DiagnosticCard failure={toFailureView(layout.saveError)} />
        </>
      )}
      {layout.pending ? (
        <p role="status">正在读取布局偏好</p>
      ) : (
        <>
          <Affix offsetTop={72}>
            <Card className="browser-filter-card">
              <BrowserFilters query={query} />
            </Card>
          </Affix>
          {layout.layout === "B" ? (
            <LayoutB query={query} />
          ) : layout.layout === "C" ? (
            <LayoutC query={query} />
          ) : (
            <LayoutA query={query} />
          )}
        </>
      )}
    </section>
  );
}
