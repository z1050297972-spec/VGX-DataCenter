import "./browser.css";
// 共用筛选栏（16、M1-04）；筛选实际含义由后端决定，页面不从 Markdown 提取值。
import { UNLABELED_FILTER } from "./classificationLabels";
import { type ReactElement } from "react";
import { Col, Row, Select, Typography } from "antd";
import type { DatasetFilters } from "../api/datasets";
import type { DatasetSearch } from "./search";

interface FilterProps {
  /** 导航层全局候选。 */ options: DatasetFilters;
  /** 当前 URL 条件。 */ search: DatasetSearch;
  /** 修改条件时由布局更新 URL。 */ onChange: (search: DatasetSearch) => void;
}
/**
 * 展示导航层信息与采集信息筛选条件和来源说明。
 * @param props - 候选、当前筛选与变化回调。
 * @returns 带中文名称和候选计数的筛选栏。
 * @throws 无。
 * @sideEffects 用户选值调用 onChange 并清除分页偏移。
 * @timeSemantics 候选计数来自索引，浏览器不独立刷新统计。
 */
export function DatasetFilterBar(props: FilterProps): ReactElement {
  return (
    <Row gutter={[16, 16]} className="dataset-filters">
      <Col xs={24} sm={12} className="browser-filter-column">
        <label>
          机器人型号
          <Select
            aria-label="机器人型号"
            allowClear
            virtual={false}
            className="browser-filter-wide"
            value={props.search.robot_model ?? undefined}
            options={props.options.robot_models.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(value: string | undefined) => {
              props.onChange({ ...props.search, robot_model: value, offset: undefined });
            }}
          />
        </label>
      </Col>
      <Col xs={24} sm={12} className="browser-filter-column">
        <label>
          FPS
          <Select
            aria-label="FPS"
            allowClear
            virtual={false}
            className="browser-filter-medium"
            value={props.search.fps == null ? undefined : String(props.search.fps)}
            options={props.options.fps.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(value: string | undefined) => {
              props.onChange({
                ...props.search,
                fps:
                  value === undefined ? undefined : value === "unknown" ? "unknown" : Number(value),
                offset: undefined,
              });
            }}
          />
        </label>
      </Col>
      <Col xs={24} sm={12} className="browser-filter-column">
        <label>
          数据来源
          <Select
            aria-label="数据来源"
            allowClear
            virtual={false}
            className="browser-filter-medium"
            value={props.search.data_origin ?? undefined}
            options={props.options.data_origins.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(value: DatasetSearch["data_origin"]) => {
              props.onChange({ ...props.search, data_origin: value, offset: undefined });
            }}
          />
        </label>
      </Col>
      <ClassificationFilters {...props} />
      {collectionFilters.map(([key, options, label]) => (
        <Col key={key} xs={24} sm={12} className="browser-filter-column">
          <label>
            {label}
            <Select<string>
              aria-label={`筛选${label}`}
              allowClear
              virtual={false}
              className="browser-filter-medium"
              value={props.search[key] ?? undefined}
              options={props.options[options].map((item) => ({
                value: item.value,
                label: `${item.label}（${String(item.count)}）`,
              }))}
              onChange={(value: string | undefined) => {
                props.onChange({ ...props.search, [key]: value, offset: undefined });
              }}
            />
          </label>
        </Col>
      ))}
      <Col span={24}>
        <Typography.Text type="secondary">
          筛选以导航层的数据集信息为准，不读原数据文件。与原文件不一致的地方见一致性面板，正式使用数据集前请核对。
        </Typography.Text>
      </Col>
    </Row>
  );
}

// 两个分类维度共用候选计数，但未标注与具体任务互斥，避免发出不可能满足的交集。
function ClassificationFilters(props: FilterProps): ReactElement {
  return (
    <>
      <Col xs={24} sm={12} className="browser-filter-column">
        <label>
          场景
          <Select<string>
            aria-label="筛选场景"
            allowClear
            virtual={false}
            className="browser-filter-scene"
            value={props.search.scene ?? undefined}
            options={props.options.scenes.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(value: string | undefined) => {
              props.onChange({ ...props.search, scene: value, offset: undefined });
            }}
          />
        </label>
      </Col>
      <Col xs={24} sm={12} className="browser-filter-column">
        <label>
          任务
          <Select<string[]>
            mode="multiple"
            aria-label="筛选任务"
            allowClear
            virtual={false}
            className="browser-filter-tasks"
            value={props.search.tasks ?? []}
            options={props.options.tasks.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(values: string[]) => {
              const last = values.at(-1);
              const tasks =
                last === UNLABELED_FILTER
                  ? [last]
                  : values.filter((value) => value !== UNLABELED_FILTER);
              props.onChange({
                ...props.search,
                tasks: tasks.length ? tasks : undefined,
                offset: undefined,
              });
            }}
          />
        </label>
      </Col>
    </>
  );
}

// A/B/C 使用同一筛选栏，沿用场景的单选及跨维度组合语义。
const collectionFilters = [
  ["collection_status", "collection_statuses", "采集状态"],
  ["collection_method", "collection_methods", "采集方式"],
  ["collection_purpose", "collection_purposes", "用途"],
  ["collection_robot", "collection_robots", "机器人"],
] as const;
