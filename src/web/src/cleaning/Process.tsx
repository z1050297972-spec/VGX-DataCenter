// 清洗流程只解释报告快照；复用 antd Steps 和已有数字格式化，不重算检查或维护默认阈值。
import type { ReactElement } from "react";
import { Card, Flex, Steps, Typography } from "antd";
import type { CleaningReport } from "../api/cleaning";
import { formatBytes } from "../datasets/formatBytes";
import { formatNumber } from "./formatNumber";

interface Props {
  /** 已生成的报告；文件大小单位为字节或未知，阈值单位遵循各报告字段。 */
  report: CleaningReport;
}

// 与页面问题说明、手册使用同一组中文检查名；未知规则码原样展示，避免隐藏新增检查。
const CHECK_NAMES: Record<string, string> = {
  non_finite: "非有限值",
  entire_static: "整段静止",
  long_static: "长时间静止",
  action_jump: "动作跳变",
  joint_limit: "关节超限",
  camera_frozen: "相机冻结",
  dark_image: "黑屏",
  bright_image: "过曝",
};

/**
 * 按六步解释本次清洗预览及后续选择、转换流程。
 * @param props - 包含文件、基准话题、帧率及规则快照的报告。
 * @returns 默认展开的清洗流程卡片，数值取自报告，未知总大小明确标注。
 * @throws 无。
 * @sideEffects 只渲染说明，不发请求、不修改选择、报告或 URL。
 * @timeSemantics 容差与断点按报告毫秒值显示，质量检查时长按报告秒值显示；不估算耗时。
 */
export function CleaningProcess(props: Props): ReactElement {
  const { report } = props;
  const { sync, checks } = report.rules;
  // 任一文件无法取得大小时，总量也未知，不能把缺失元数据当成零字节。
  const totalBytes = report.files.some((file) => file.size_bytes === null)
    ? null
    : report.files.reduce((sum, file) => sum + (file.size_bytes ?? 0), 0);
  const size = totalBytes === null ? "总大小未知" : `共 ${formatBytes(totalBytes)}`;
  const severe = checks.severe_checks.map((check) => CHECK_NAMES[check] ?? check).join("、");
  return (
    <Card className="cleaning-section" title="清洗流程" role="region" aria-label="清洗流程">
      <Steps
        orientation="vertical"
        size="small"
        current={-1}
        classNames={{
          itemSection: "cleaning-process-content",
          itemContent: "cleaning-process-content",
        }}
        items={[
          {
            title: "读取文件",
            content: (
              <Flex vertical gap="small">
                <Typography.Text>
                  本次 {report.files.length} 个 MCAP 文件、{size}
                  ，每个文件完整读一遍（只读，不改访问时间）。
                </Typography.Text>
                <Typography.Text type="secondary">
                  MCAP
                  是压缩块，图像和关节消息混在同一块里，要拿到每条消息的时间戳就得整块解压，没法跳过图像，所以耗时主要取决于文件总大小和磁盘读速。
                </Typography.Text>
              </Flex>
            ),
          },
          {
            title: "时间对齐",
            content: (
              <Flex vertical gap="small">
                <Typography.Text>
                  按基准话题对齐，切出的段与工具转换后的 episode 一致。
                </Typography.Text>
                <Typography.Text>
                  基准：以话题 {report.reference_topic} 的每条有效消息为一帧（
                  {formatNumber(report.fps)} 帧/秒）。
                </Typography.Text>
                <Typography.Text>
                  匹配：其他话题按消息头时间戳取最近的一条，一样近时取较早的；缺失的可选话题按配置填充。
                </Typography.Text>
                <Typography.Text>
                  一致性：与 mcap2lerobot 转换使用同一份配置、同一套对齐规则。
                </Typography.Text>
              </Flex>
            ),
          },
          {
            title: "判坏帧、切段",
            content: (
              <Flex vertical gap="small">
                <Typography.Text>每个文件独立判坏帧、切段，丢弃过短的段。</Typography.Text>
                <Typography.Text>
                  坏帧：某话题的时间差超过它的容差（默认{" "}
                  {formatNumber(sync.default_tolerance_ms, "milliseconds")}
                  ，各话题容差见文件展开项）。
                </Typography.Text>
                <Typography.Text>
                  切段：首尾坏帧裁掉，中间坏帧处切开；相邻基准帧间隔超过{" "}
                  {formatNumber(sync.max_frame_gap_ms, "milliseconds")} 也切开。
                </Typography.Text>
                <Typography.Text>丢弃：短于 {sync.min_episode_frames} 帧的段丢弃。</Typography.Text>
              </Flex>
            ),
          },
          {
            title: "文件级检查",
            content: (
              <Flex vertical gap="small">
                <Typography.Text>
                  有致命问题的文件整个剔除，不交给工具，原因见文件表。
                </Typography.Text>
                <Flex vertical gap="small" role="list" aria-label="文件级致命问题">
                  {[
                    "文件读不了或损坏。",
                    "缺少必需话题。",
                    "消息内容无法解析（消息头、编码、数值字段或维度不符）。",
                    "视频不能按工具的要求解码（H.264 含 B 帧或没有关键帧、H.265 等不支持的格式、图像损坏或尺寸异常）。",
                    "基准话题有效时间戳不足。",
                    "规模超过安全上限（消息数、缓存、对齐内存）。",
                  ].map((item) => (
                    <Typography.Text key={item} role="listitem">
                      • {item}
                    </Typography.Text>
                  ))}
                </Flex>
              </Flex>
            ),
          },
          {
            title: "段内质量检查",
            content: (
              <Flex vertical gap="small">
                <Typography.Text>按报告中的检查规则决定默认处理。</Typography.Text>
                <Typography.Text strong>默认剔除（严重）</Typography.Text>
                <Typography.Text>{severe || "本报告未配置默认剔除的严重检查"}</Typography.Text>
                <Typography.Text strong>只提示（默认保留）</Typography.Text>
                <Flex vertical gap="small" role="list" aria-label="提示类质量检查">
                  {[
                    `连续静止至少 ${formatNumber(checks.long_static_s, "seconds")}。`,
                    "动作跳变超过来源阈值。",
                    "关节超出已配置限位。",
                    `相机冻结至少 ${formatNumber(checks.frozen_s, "seconds")}。`,
                    `每 ${formatNumber(checks.sample_interval_s, "seconds")} 抽一帧检查黑屏或过曝（阈值见规则说明）。`,
                  ].map((item) => (
                    <Typography.Text key={item} role="listitem">
                      • {item}
                    </Typography.Text>
                  ))}
                </Flex>
                <Typography.Text>提示类问题由用户决定保留或剔除。</Typography.Text>
                <Typography.Text>H.264 话题的画面不检查。</Typography.Text>
              </Flex>
            ),
          },
          {
            title: "选择与转换",
            content: (
              <Flex vertical gap="small">
                <Typography.Text>
                  在下面的表格里改保留或剔除；episode
                  编号按当前选择连续排列，就是清洗后数据集里的编号。
                </Typography.Text>
                <Typography.Text strong>点「进行转换」后，依次执行：</Typography.Text>
                <Flex vertical gap="small" role="list" aria-label="进行转换后的六个步骤">
                  {[
                    "核对保留文件的大小、修改时间及工具、配置、规则自预览后没变。",
                    "工具只转换保留的文件（GPU）。",
                    "核对产物 episode 数和逐段帧数与报告一致。",
                    "有待剔除的 episode 时用 LeRobot 删除（同时含保留段和剔除段的视频用工具相同的编码器和参数重新编码，只含保留段的原样复制，只含剔除段的不输出），再核对保留产物。",
                    "入库检查。",
                    "通过后入库，血缘记录本次清洗。",
                  ].map((item, index) => (
                    <Typography.Text key={item} role="listitem">
                      {index + 1}. {item}
                    </Typography.Text>
                  ))}
                </Flex>
              </Flex>
            ),
          },
        ]}
      />
    </Card>
  );
}
