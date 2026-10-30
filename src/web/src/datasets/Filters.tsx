// 共用筛选栏（16、M1-04）；筛选实际含义由后端决定，页面不从 Markdown 提取值。
import { useState, type ReactElement } from "react";
import { Button, Select } from "antd";
import type { DatasetFilters } from "../api/datasets";
import type { DatasetSearch } from "./search";

interface FilterProps {
  /** 全局候选及默认筛选方式。 */ options: DatasetFilters;
  /** 当前 URL 条件。 */ search: DatasetSearch;
  /** 修改条件时由布局更新 URL。 */ onChange: (search: DatasetSearch) => void;
}
/**
 * 按型号表的默认方式展示型号或标签候选，更多筛选保留原始标签。
 * @param props - 候选、当前筛选与变化回调。
 * @returns 带中文名称和候选计数的筛选栏。
 * @throws 无。
 * @sideEffects 用户选值调用 onChange 并清除分页偏移。
 * @timeSemantics 候选计数来自索引，浏览器不独立刷新统计。
 */
export function DatasetFilterBar(props: FilterProps): ReactElement {
  const [more, setMore] = useState(false);
  const byModel = props.options.default_robot_filter === "robot_model";
  return (
    <div className="dataset-filters">
      {byModel && (
        <label>
          机器人型号
          <Select
            aria-label="机器人型号"
            allowClear
            virtual={false}
            style={{ minWidth: 180 }}
            value={props.search.robot_model_id ?? undefined}
            options={props.options.robot_model_options.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(value: string | undefined) => {
              props.onChange({ ...props.search, robot_model_id: value, offset: undefined });
            }}
          />
        </label>
      )}
      {(!byModel || more) && (
        <label>
          型号标签
          <Select
            aria-label="型号标签"
            allowClear
            virtual={false}
            style={{ minWidth: 180 }}
            value={props.search.robot_type ?? undefined}
            options={props.options.robot_types.map((item) => ({
              value: item.value,
              label: `${item.label}（${String(item.count)}）`,
            }))}
            onChange={(value: string | undefined) => {
              props.onChange({ ...props.search, robot_type: value, offset: undefined });
            }}
          />
        </label>
      )}
      <label>
        FPS
        <Select
          aria-label="FPS"
          allowClear
          virtual={false}
          style={{ minWidth: 150 }}
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
      <label>
        数据来源
        <Select
          aria-label="数据来源"
          allowClear
          virtual={false}
          style={{ minWidth: 150 }}
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
      {byModel && (
        <Button
          aria-expanded={more}
          onClick={() => {
            setMore(!more);
          }}
        >
          更多筛选
        </Button>
      )}
    </div>
  );
}
