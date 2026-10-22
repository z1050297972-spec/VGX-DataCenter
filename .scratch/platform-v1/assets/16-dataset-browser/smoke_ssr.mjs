// Claude 的冒烟检查（不进原型分支）：用 Vite 的 ssrLoadModule 在 Node 里加载原型模块，
// 用 renderToString 渲染三个变体和各部件的多种状态，抓渲染期异常，并核对派生计算。
// 不监听端口（middlewareMode），不写 src/web/src；只读 public/data。
import fs from 'node:fs'
import path from 'node:path'

const WEB = '/home/shawn/桌面/robot-data-platform.wt/prototype-dataset-browser/src/web'
const { createServer } = await import(path.join(WEB, 'node_modules/vite/dist/node/index.js'))
const server = await createServer({
  root: WEB, configFile: path.join(WEB, 'vite.config.ts'), logLevel: 'error', appType: 'custom',
  server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true, include: [] },
  // 虚拟入口：让 react/antd 和原型模块走同一条外部化加载路径，保证是同一个实例。
  plugins: [{
    name: 'smoke-entry',
    resolveId: id => (id === 'virtual:smoke' ? '\0virtual:smoke' : null),
    load: id => (id === '\0virtual:smoke' ? "export * as React from 'react'; export { renderToString } from 'react-dom/server'; export * as antd from 'antd'; export { default as zhCN } from 'antd/locale/zh_CN';" : null),
  }],
})
const load = p => server.ssrLoadModule(p)
let failures = 0
const ok = (cond, msg) => { if (!cond) { failures++; console.log('  ✗', msg) } else console.log('  ✓', msg) }
try {
  const v = await load('virtual:smoke')
  const React = v.React.createElement ? v.React : v.React.default
  const renderToString = v.renderToString
  const antd = v.antd.App ? v.antd : v.antd.default
  const zhCN = v.zhCN && v.zhCN.locale ? v.zhCN : (v.zhCN && v.zhCN.default) || v.zhCN
  const D = '/src/prototype/dataset-browser'
  const data = await load(`${D}/data.prototype.ts`)
  const { VariantA } = await load(`${D}/VariantA.prototype.tsx`)
  const { VariantB } = await load(`${D}/VariantB.prototype.tsx`)
  const { VariantC } = await load(`${D}/VariantC.prototype.tsx`)
  const W = await load(`${D}/widgets/Details.prototype.tsx`)
  const C = await load(`${D}/widgets/Consistency.prototype.tsx`)
  const J = await load(`${D}/widgets/JsonViewer.prototype.tsx`)
  const Cm = await load(`${D}/widgets/Common.prototype.tsx`)
  const h = React.createElement
  const wrap = el => renderToString(h(antd.ConfigProvider, { locale: zhCN }, h(antd.App, null, el)))
  const readJson = p => JSON.parse(fs.readFileSync(path.join(WEB, 'public/data', p), 'utf-8'))
  const index = readJson('index.json')
  const entry = k => index.entries.find(e => e.key === k)
  const file = (k, f) => readJson(`entries/${k}/${f}`)
  const noop = () => {}
  const base = { index, filters: { ...data.emptyFilters }, setFilters: noop, demo: { offline: false, changed: false }, view: 'format', setView: noop, selected: null, go: noop, close: noop, location: '按格式', setLocation: noop }
  const render = (label, el, expect = []) => {
    try {
      const html = wrap(el)
      // React SSR 会在相邻文本之间插入 <!-- -->，比对前去掉注释和标签
      const text = html.replace(/<!--.*?-->/g, '').replace(/<[^>]+>/g, '')
      const missing = expect.filter(t => !html.includes(t) && !text.includes(t))
      ok(!missing.length, `${label}（${html.length} 字符）${missing.length ? '，缺：' + missing.join(' / ') : ''}`)
      return html
    } catch (e) { failures++; console.log('  ✗', label, '渲染异常：', e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : e); return '' }
  }

  console.log('派生计算')
  const nav = data.navigation(index)
  const fmt = nav.find(n => n.path === '按格式'); const task = nav.find(n => n.path === '按任务')
  ok(task.children.length === 35, `按任务 35 个入口：${task.children.length}`)
  const ler = fmt.children.find(n => n.name === 'lerobot')
  ok(ler && ler.children.map(n => `${n.name}:${n.entries.length}`).join(',') === '2.0:0,2.1:0,3.0:31', `lerobot 版本节点：${ler && ler.children.map(n => `${n.name}:${n.entries.length}`).join(',')}`)
  ok(fmt.children.map(n => `${n.name}:${n.entries.length}`).join(',') === 'lerobot:31,mcap:2,tar、tar.gz（含分卷）:2', `格式目录：${fmt.children.map(n => `${n.name}:${n.entries.length}`).join(',')}`)
  const count = f => index.datasets.filter(d => data.matches(d, { ...data.emptyFilters, ...f })).length
  ok(count({ robots: ['未知'] }) === 10, `型号"未知" 10 个：${count({ robots: ['未知'] })}`)
  ok(count({ fps: ['未知'] }) === 3, `FPS"未知" 3 个：${count({ fps: ['未知'] })}`)
  ok(count({ fps: ['36'] }) === 1 && count({ fps: ['25'] }) === 1, `FPS 36/25 只有 EgoProDemo：${count({ fps: ['36'] })}/${count({ fps: ['25'] })}`)
  ok(count({ name: 'LIBERO' }) === 5, `名称 LIBERO 不分大小写 5 个：${count({ name: 'LIBERO' })}`)
  ok(count({ name: 'dataset-14' }) === 1, `名称匹配 dataset_id：${count({ name: 'dataset-14' })}`)
  ok(count({ robots: ['franka'], fps: ['20'] }) === 5, `franka 且 20fps 5 个：${count({ robots: ['franka'], fps: ['20'] })}`)
  ok(data.formatBytes(631143389) === '631 MB' && data.formatBytes(13216127618578) === '13.2 TB', `formatBytes：${data.formatBytes(631143389)} / ${data.formatBytes(13216127618578)}`)
  const t = data.totalSize(index, task.entries)
  ok(t.count === 35 && !t.recorded, `按任务总大小 ${data.formatBytes(t.bytes)}，35 个，无记录值回退`)
  const nulled = { ...index, entries: index.entries.map(e => e.key === 'task__libero_10' ? { ...e, size: { ...e.size, bytes: null, measured_at: null } } : e) }
  const es = data.entrySize(nulled, nulled.entries.find(e => e.key === 'task__libero_10'))
  ok(es.recorded && es.bytes === 631143389, `没统计过时回退到记录值并标记：${JSON.stringify(es)}`)
  ok(data.issueTotals(index, base.demo).action === 1 && data.issueTotals(index, base.demo).info === 5, `问题计数 1 · 5`)
  ok(data.issueTotals(index, { offline: true, changed: false }).action === 2, `离线时需要处理 +1`)
  const alphaT = entry('task__agibot_world_alpha')
  ok(data.linkStates(index, alphaT.links[0], { offline: true, changed: false }).join() === '存储根离线', `离线时 alpha 链接标"存储根离线"`)
  ok(data.linkStates(index, entry('task__libero_10').links[0], { offline: true, changed: false }).join() === '正常', `离线时 dataset1 上的链接仍"正常"`)
  const fake = { ...alphaT.links[0], target_exists: false, storage_root: '/mnt/dataset1' }
  ok(data.linkStates(index, fake, base.demo).join() === '断链', `断链`)
  ok(data.linkStates(index, { ...fake, storage_root: null, target_exists: true }, base.demo).join() === '不在已登记的存储根下', `不在已登记的存储根下`)
  ok(data.linkStates(index, { ...alphaT.links[0], in_json: false }, base.demo).join() === 'JSON 里没有', `JSON 里没有`)
  ok(data.linkStates(index, { ...alphaT.links[0], json_source_path: '/x' }, base.demo).join() === '指向不同', `指向不同`)
  ok(data.counterpartEntries(index, entry('task__libero_10')).map(e => e.key).join() === 'format__lerobot__3.0__libero_10', `跨视图：task__libero_10 → format__lerobot__3.0__libero_10`)

  console.log('变体 A')
  render('A 按格式，未选中', h(VariantA, base), ['按格式', '按任务', 'lerobot', '3.0', '2.0', 'mcap', '一致性面板', '数据集浏览（原型）'])
  render('A 按任务', h(VariantA, { ...base, view: 'task', location: '按任务' }), ['libero_10', 'agibot_world_alpha'])
  render('A 选中 alpha（详情页，离线+改动）', h(VariantA, { ...base, view: 'task', location: '按任务', selected: alphaT, demo: { offline: true, changed: true } }), ['返回列表', '重新扫描', '跨视图跳转', '正在读取入口文件'])
  render('A 有筛选', h(VariantA, { ...base, filters: { name: 'libero', robots: ['franka'], fps: ['20'] } }), ['libero_10'])
  console.log('变体 B')
  render('B 按格式', h(VariantB, base), ['按格式', 'lerobot', '一致性面板', '需要处理 1 类'])
  render('B 按任务 + 离线', h(VariantB, { ...base, view: 'task', location: '按任务', demo: { offline: true, changed: false } }), ['存储根离线', '需要处理 2 类'])
  render('B 选中 2026（抽屉）', h(VariantB, { ...base, selected: entry('format__archives__agibot_world_2026') }), ['agibot_world_2026'])
  console.log('变体 C')
  render('C 顶层', h(VariantC, { ...base, location: '' }), ['/mnt/datasets', '按任务', '按格式', '索引', '不扫描', '一致性面板（1 · 5）'])
  render('C 进到 lerobot', h(VariantC, { ...base, location: '按格式/lerobot' }), ['2.0', '2.1', '3.0'])
  render('C 进到 lerobot/2.0（空目录）', h(VariantC, { ...base, location: '按格式/lerobot/2.0' }), ['空目录'])
  render('C 选中入口', h(VariantC, { ...base, selected: entry('format__mcap__EgoProStandard') }), ['入口内容', '原始数据__dataset1', '子任务.json', '数据集信息.json', '原始路径.json', '按需加载'])
  render('C 有筛选', h(VariantC, { ...base, location: '', filters: { name: '', robots: ['未知'], fps: [] } }), ['筛选结果 · 10 个'])

  console.log('部件')
  const props = k => ({ ...base, entry: entry(k), selected: entry(k) })
  render('一致性面板', h(C.ConsistencyPanel, base), ['①', '②', '③', '④', '没有发现问题', '需要处理', '提示', '数据块的 direct_path 不存在', 'summary_path 指向的汇总文档不存在', '有没下载完的文件', '第 11 条', '涉及 35 个数据集', '共 70 处'])
  render('一致性面板（离线）', h(C.ConsistencyPanel, { ...base, demo: { offline: true, changed: false } }), ['存储根 /mnt/dataset2 离线：本次扫描跳过了它下面的磁盘检查。', '未检查', '离线'])
  render('详情头（改动提示）', h(W.DetailHeading, { ...props('format__lerobot__3.0__EgoProDemo'), demo: { offline: false, changed: true } }), ['导航层在上次扫描', '重新扫描', '按任务/EgoProDemo'])
  render('大小块（格式入口）', h(W.SizeBlock, props('format__lerobot__3.0__EgoProDemo')), ['统计大小', '10-12 记录', '只含这个格式'])
  render('大小块（2026）', h(W.SizeBlock, props('task__agibot_world_2026')), ['−4.7%'])
  const info = file('task__libero_10', '数据集信息.json')
  render('14 项', h(W.Information, { information: info }), ['<code', 'copy-path', '内容是 2026-10-12 的快照', 'summary_path', 'information_scope'])
  const alphaRaw = file('task__agibot_world_alpha', '原始路径.json')
  const weird = { ...alphaT, links: [alphaT.links[0], { ...alphaT.links[1], target_exists: false, storage_root: '/mnt/dataset1' }, { ...alphaT.links[2], storage_root: null }, { ...alphaT.links[3], in_json: false }], json_links_missing_on_disk: ['原始数据'] }
  const rawWithMissing = { ...alphaRaw, links: [...alphaRaw.links, { name: '原始数据', source_path: '/mnt/dataset2/agibot_world_alpha', entry_path: '按任务/agibot_world_alpha/原始数据', source_type: 'directory' }] }
  render('链接表（各种状态）', h(W.Links, { ...base, entry: weird, original: rawWithMissing }), ['重新检查', '断链', '不在已登记的存储根下', 'JSON 里没有', '磁盘上没有', '检查时间'])
  render('链接表（离线）', h(W.Links, { ...base, entry: alphaT, original: alphaRaw, demo: { offline: true, changed: false } }), ['存储根离线', '未检查'])
  render('数据块表（EgoProStandard 734 条）', h(W.Sources, { original: file('task__EgoProStandard', '原始路径.json'), index }), ['共 734 条数据块', '只核对了路径存在'])
  render('数据块表（alpha）', h(W.Sources, { original: alphaRaw, index }), ['需要关注', '元数据和引用都核对通过', 'entry_type'])
  render('子任务（未加载）', h(W.SubtaskViewer, { entry: entry('task__agibot_world_2026') }), ['子任务.json', '14.1 MB', '加载'])
  const big = file('task__agibot_world_2026', '子任务.json')
  const t0 = Date.now(); const html = render('JSON 查看器（14 MB，只渲染第一层）', h(J.JsonViewer, { value: big, label: '子任务.json' }), ['tasks'])
  ok(Date.now() - t0 < 2000 && html.length < 200000, `首屏渲染 ${Date.now() - t0} ms，${html.length} 字符`)
  render('其他字段（alpha）', h(J.RawFields, { value: alphaRaw, omit: ['links', 'sources'] }), ['excluded_from_navigation', 'navigation_scope', 'task_metadata', 'dataset_roots'])
  render('筛选栏', h(Cm.FilterBar, { index, filters: data.emptyFilters, setFilters: noop }), ['名称', '机器人型号', 'FPS', '清空筛选'])
  render('详情内容（三种模式的加载态）', h('div', null, h(W.DetailContent, { props: props('task__libero_10') }), h(W.DetailContent, { props: props('task__libero_10'), mode: 'tabs' }), h(W.DetailContent, { props: props('task__libero_10'), mode: 'preview', file: '子任务.json' })), ['正在读取'])
} catch (e) {
  failures++
  console.log('脚本异常：', e && e.stack ? e.stack : e)
} finally {
  await server.close()
}
console.log(failures ? `失败 ${failures} 项` : '全部通过')
process.exit(failures ? 1 : 0)
