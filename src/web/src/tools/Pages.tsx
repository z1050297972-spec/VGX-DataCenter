// 工具库只读页面（M4-01、M4.5-10）：展示登记事实和 README，不执行工具或修改登记。
import { useState, type ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Breadcrumb,
  Button,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Flex,
  Grid,
  Popover,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ToolDetail, ToolSummary } from "../api/tools";
import { toFailureView } from "../api/problems";
import { DiagnosticCard, DiagnosticEntries } from "../DiagnosticCard";
import { useTool, useTools, useToolReadme } from "./queries";
import type { LeRobotEnvironment } from "../api/tools";
import "./tools.css";

/**
 * 显示工具清单、指纹状态及可打开的登记详情。
 * @returns 工具表格、只读详情与说明抽屉；不可用状态为红色，可展开五段诊断。
 * @throws 无；加载失败交给 DiagnosticCard。
 * @sideEffects 读取工具列表，点击行时请求详情，点击说明时请求 README；重新检查刷新列表，不写登记包或 URL。
 * @timeSemantics 无轮询，打开页面现场检查；离页和关闭抽屉时取消相应请求。
 */
export function ToolsPage(): ReactElement {
  const query = useTools();
  const [selected, setSelected] = useState<string | null>(null);
  const [readmeName, setReadmeName] = useState<string | null>(null);
  const screens = Grid.useBreakpoint();
  return (
    <section className="tools-page">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "数据" }, { title: "工具库" }]} />
        <Flex justify="space-between" align="center" wrap="wrap">
          <Typography.Title level={2} className="app-page-title">
            工具库
          </Typography.Title>
          <Button
            loading={query.isFetching}
            disabled={query.isFetching}
            onClick={() => {
              void query.refetch();
            }}
          >
            重新检查
          </Button>
        </Flex>
      </header>
      {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
      {query.data && <EnvironmentStatus environment={query.data.lerobot_environment} />}
      <Card>
        <Table<ToolSummary>
          rowKey="name"
          pagination={false}
          loading={query.isFetching}
          scroll={{ x: "max-content" }}
          dataSource={query.data?.items}
          locale={{ emptyText: query.data ? "尚未登记工具" : "暂无工具信息" }}
          onRow={(tool) => ({
            onClick: () => {
              setSelected(tool.name);
            },
          })}
          columns={[
            {
              title: "名称",
              render: (_, tool) => (
                <Button
                  type="link"
                  onClick={() => {
                    setSelected(tool.name);
                  }}
                >
                  {tool.name}
                </Button>
              ),
            },
            { title: "版本", render: (_, tool) => displayText(tool.version) },
            { title: "说明", render: (_, tool) => displayText(tool.summary) },
            {
              title: "输入 → 输出",
              render: (_, tool) =>
                `${displayText(tool.input_format)} → ${displayText(tool.output_format)}`,
            },
            { title: "适用型号", render: (_, tool) => tool.robot_models.join("、") || "—" },
            {
              title: "有清洗规则的型号",
              render: (_, tool) => tool.cleaning_models.join("、") || "无",
            },
            { title: "需要 GPU", render: (_, tool) => gpuLabel(tool.needs_gpu) },
            { title: "状态", render: (_, tool) => <ToolStatus tool={tool} /> },
            {
              title: "操作",
              render: (_, tool) => (
                <Space
                  orientation="vertical"
                  size="small"
                  onClick={(event) => {
                    event.stopPropagation();
                  }}
                >
                  <Button
                    autoInsertSpace={false}
                    disabled={!tool.readme_available}
                    onClick={() => {
                      setReadmeName(tool.name);
                    }}
                  >
                    说明
                  </Button>
                  {!tool.readme_available && (
                    <Typography.Text type="secondary">工具目录里没有 README.md</Typography.Text>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Drawer
        title={selected ? `${selected} · 工具详情` : "工具详情"}
        open={selected !== null}
        onClose={() => {
          setSelected(null);
        }}
        size="large"
        destroyOnHidden
      >
        {selected && <ToolDetails key={selected} name={selected} />}
      </Drawer>
      <Drawer
        title={readmeName ? `${readmeName} 说明` : "工具说明"}
        open={readmeName !== null}
        onClose={() => {
          setReadmeName(null);
        }}
        size={screens.sm ? "large" : "100%"}
        destroyOnHidden
      >
        {readmeName && <ToolReadmeContent key={readmeName} name={readmeName} />}
      </Drawer>
    </section>
  );
}

function ToolReadmeContent({ name }: { name: string }): ReactElement {
  const query = useToolReadme(name);
  if (query.error) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (!query.data)
    return (
      <Spin description="正在读取工具说明">
        <div className="tools-loading" />
      </Spin>
    );
  return (
    <Typography className="tools-readme">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <Typography.Title level={1}>{children}</Typography.Title>,
          h2: ({ children }) => <Typography.Title level={2}>{children}</Typography.Title>,
          h3: ({ children }) => <Typography.Title level={3}>{children}</Typography.Title>,
          h4: ({ children }) => <Typography.Title level={4}>{children}</Typography.Title>,
          h5: ({ children }) => <Typography.Title level={5}>{children}</Typography.Title>,
          a: ({ href, children }) => (
            <Typography.Link href={href} target="_blank" rel="noreferrer">
              {children}
            </Typography.Link>
          ),
          table: ({ children }) => (
            <Flex className="tools-readme-table-scroll">
              <table className="tools-readme-table">{children}</table>
            </Flex>
          ),
          pre: ({ children }) => <pre className="tools-readme-code">{children}</pre>,
        }}
      >
        {query.data.content}
      </ReactMarkdown>
    </Typography>
  );
}

function ToolStatus({ tool }: { tool: ToolSummary }): ReactElement {
  return (
    <Space>
      <Tag color={tool.status === "可用" ? "green" : "red"}>{tool.status}</Tag>
      {tool.diagnostics.length > 0 && (
        <Popover
          title="诊断"
          trigger="click"
          content={<DiagnosticEntries diagnostics={tool.diagnostics} />}
        >
          <Button
            type="link"
            size="small"
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            查看诊断
          </Button>
        </Popover>
      )}
    </Space>
  );
}

function gpuLabel(value: boolean | null): string {
  return value === null ? "—" : value ? "是" : "否";
}

function ToolDetails({ name }: { name: string }): ReactElement {
  const query = useTool(name);
  if (query.error) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (!query.data)
    return (
      <Spin description="正在读取工具详情">
        <div className="tools-loading" />
      </Spin>
    );
  const tool = query.data;
  return (
    <Space orientation="vertical" size="large" className="tools-details">
      <ToolFacts tool={tool} />
      <DiagnosticEntries diagnostics={tool.diagnostics} />
      {tool.command && (
        <section>
          <Typography.Title level={4}>命令模板</Typography.Title>
          <Typography.Paragraph type="secondary">
            参数按列表传递，不经过 shell。
          </Typography.Paragraph>
          <Typography.Text>预检</Typography.Text>
          <pre className="tools-code">{JSON.stringify(tool.command.verify, null, 2)}</pre>
          <Typography.Text>转换</Typography.Text>
          <pre className="tools-code">{JSON.stringify(tool.command.convert, null, 2)}</pre>
        </section>
      )}
      {tool.configurations.map((configuration) => (
        <section key={configuration.robot_model}>
          <Divider />
          <Typography.Title level={4}>{configuration.robot_model}</Typography.Title>
          <Descriptions
            column={1}
            items={[
              { key: "file", label: "配置文件", children: configuration.filename },
              {
                key: "sha256",
                label: "配置 SHA-256",
                children: <Typography.Text code>{configuration.sha256}</Typography.Text>,
              },
            ]}
          />
          <pre className="tools-code" aria-label={`${configuration.robot_model} 配置全文`}>
            {configuration.content}
          </pre>
        </section>
      ))}
    </Space>
  );
}

function ToolFacts({ tool }: { tool: ToolDetail }): ReactElement {
  return (
    <Descriptions
      column={1}
      items={[
        { key: "name", label: "名称", children: tool.name },
        { key: "version", label: "版本", children: displayText(tool.version) },
        { key: "summary", label: "说明", children: displayText(tool.summary) },
        {
          key: "formats",
          label: "输入 → 输出",
          children: `${displayText(tool.input_format)} → ${displayText(tool.output_format)}`,
        },
        { key: "versions", label: "输出版本", children: tool.output_versions.join("、") || "—" },
        { key: "models", label: "适用型号", children: tool.robot_models.join("、") || "—" },
        { key: "gpu", label: "需要 GPU", children: gpuLabel(tool.needs_gpu) },
        {
          key: "status",
          label: "状态",
          children: <Tag color={tool.status === "可用" ? "green" : "red"}>{tool.status}</Tag>,
        },
        { key: "path", label: "程序路径", children: displayText(tool.program_path) },
        {
          key: "sha256",
          label: "程序 SHA-256（前 12 位）",
          children: <Typography.Text code>{tool.sha256_prefix ?? "—"}</Typography.Text>,
        },
        { key: "commit", label: "源码提交（仅说明）", children: displayText(tool.source_commit) },
        { key: "note", label: "源码状态说明", children: displayText(tool.source_note) },
      ]}
    />
  );
}

// 清单无效时没有可信字段，统一用占位符表达未知，不把空值显示为实际版本。
function displayText(value: string | null): string {
  return value ?? "—";
}

// LeRobot 状态来自服务端探测，页面不把版本相同当作指纹相同。
function EnvironmentStatus({ environment }: { environment: LeRobotEnvironment }): ReactElement {
  const labels = {
    unconfigured: "未配置",
    available: "可用",
    mismatch: "不符",
    error: "检查失败",
  } as const;
  return (
    <Card title="LeRobot 环境">
      <Descriptions
        items={[
          {
            key: "status",
            label: "状态",
            children: (
              <Tag color={environment.status === "available" ? "green" : "orange"}>
                {labels[environment.status]}
              </Tag>
            ),
          },
          { key: "expected-version", label: "期望版本", children: environment.expected_version },
          {
            key: "actual-version",
            label: "实际版本",
            children: environment.actual_version ?? "未知",
          },
        ]}
      />
      {environment.message && <Typography.Paragraph>{environment.message}</Typography.Paragraph>}
    </Card>
  );
}
