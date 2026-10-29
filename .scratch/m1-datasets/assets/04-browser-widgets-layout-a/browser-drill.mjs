// 验收 5 浏览器部分：照第 6–10 张演示的写法，用无头 Chrome 走一遍全过程并截图。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m104-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9342", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9342/json/version")).json(); break; } catch { await sleep(200); } }
const ws = new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pending.set(i, (d) => (d.error ? rej(new Error(method + " " + JSON.stringify(d.error))) : res(d.result))); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
async function page() {
  const { browserContextId } = await send("Target.createBrowserContext");
  const { targetId } = await send("Target.createTarget", { url: "about:blank", browserContextId });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId); await send("Runtime.enable", {}, sessionId);
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }, sessionId); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; };
  return {
    ev,
    go: async (path) => { await send("Page.navigate", { url: BASE + path }, sessionId); await sleep(1500); },
    shot: async (name) => { const { data } = await send("Page.captureScreenshot", { format: "png" }, sessionId); writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, "base64")); },
    wait: async (expr, ms = 10000) => { for (let t = 0; t < ms; t += 200) { if (await ev(expr)) return true; await sleep(200); } throw new Error("timeout: " + expr + " @ " + (await ev("location.href")) + " :: " + (await ev("document.body.innerText.slice(0,300)"))); },
    front: () => send("Page.bringToFront", {}, sessionId),
  };
}
const H = `
window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); if (!el) throw new Error('no input ' + name); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); };
window.__click = (text, scope) => { const root = scope ? [...document.querySelectorAll(scope)].pop() : document; const b = [...root.querySelectorAll('button')].filter(b => (b.getAttribute('aria-label') || b.innerText.replace(/\\s/g,'')) === text && !b.disabled).pop(); if (!b) throw new Error('no button ' + text); b.click(); };`;
const log = (...a) => console.log(...a);
const rows = (p) => p.ev("[...document.querySelectorAll('.ant-table-tbody tr')].map(r => r.innerText.replace(/\\s+/g,' ')).filter(t => t && !t.includes('暂无数据'))");
const body = (p) => p.ev("document.body.innerText");
const st = (p) => p.ev("fetch('/api' + location.pathname).then(r=>r.json()).then(d=>d.state)");
async function waitState(p, want, ms) { const t = Date.now(); for (;;) { const s = await st(p); if (s === want) return; if (Date.now() - t > ms) throw new Error("state " + s + " != " + want); await sleep(400); } }
const api = (p, path) => p.ev(`fetch('/api${path}').then(r=>r.json())`);
try {
  const p = await page();
  await p.go("/login"); await p.wait("document.querySelectorAll('input').length >= 2", 20000); await p.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await p.wait("location.pathname === '/'"); log("登录成功");
  await p.go("/datasets"); await p.wait("!!document.querySelector('[aria-label=\"数据集列表\"]') && !document.body.innerText.includes('正在加载数据集')", 20000); await sleep(1000);
  const total = (await api(p, "/datasets?limit=1")).total; log("接口 total =", total);
  log("页面文字含 35：", (await body(p)).includes("35"));
  await p.shot("m104-1-list");
  const trees = await api(p, "/datasets/trees"); log("树节点（顶层）:", JSON.stringify(trees.nodes.map(n => n.label ?? n.name ?? n.key)).slice(0, 300));
  const filters = await api(p, "/datasets/filters"); log("筛选选项: 型号标签", JSON.stringify(filters.robot_types).slice(0, 300), "| FPS", JSON.stringify(filters.fps).slice(0, 200));
  const rt = filters.robot_types.find(x => (x.value ?? x) !== "unknown"); const rtv = rt.value ?? rt;
  const fp = filters.fps.find(x => (x.value ?? x) !== "unknown"); const fpv = fp.value ?? fp;
  for (const [k, v] of [["robot_type", rtv], ["fps", fpv]]) {
    const n = (await api(p, `/datasets?limit=200&${k}=${encodeURIComponent(v)}`)).total;
    await p.go(`/datasets?${k}=${encodeURIComponent(v)}`); await p.wait("!document.body.innerText.includes('正在加载数据集')", 15000); await sleep(800);
    const rows = await p.ev("document.querySelectorAll('[aria-label=\"数据集列表\"] [aria-label^=\"打开 \"]').length");
    log(`筛选 ${k}=${v}：接口 ${n} 条，页面列出 ${rows} 条，${n === rows ? "一致" : "不一致"}`);
    await p.shot(`m104-2-filter-${k}`);
  }
  await p.go("/datasets"); await p.wait("!document.body.innerText.includes('正在加载数据集')", 15000); await sleep(800);
  await p.ev("[...document.querySelectorAll('[aria-label^=\"打开 \"]')].find(b => b.getAttribute('aria-label').includes('libero_10')).click()");
  await p.wait("!!document.querySelector('[aria-label=\"数据集详情\"]') && !document.body.innerText.includes('正在加载详情')", 15000); await sleep(800);
  log("libero_10 详情打开，URL:", decodeURIComponent(await p.ev("location.search")));
  await p.shot("m104-3-detail-libero10");
  const jumped = await p.ev("(() => { const b = [...document.querySelectorAll('[aria-label^=\"跳转到 \"]')]; if (!b.length) return null; const l = b[0].getAttribute('aria-label'); b[0].click(); return l; })()");
  await sleep(1500); log("跨视图跳转：", jumped, "→ URL", decodeURIComponent(await p.ev("location.search")));
  await p.shot("m104-4-crossview");
  await p.go("/datasets"); await p.wait("!document.body.innerText.includes('正在加载数据集')", 15000); await sleep(800);
  await p.ev("[...document.querySelectorAll('[aria-label^=\"打开 \"]')].find(b => b.getAttribute('aria-label').includes('agibot_world_2026')).click()");
  await p.wait("!document.body.innerText.includes('正在加载详情') && document.body.innerText.includes('打开 子任务.json')", 20000); await sleep(800);
  await p.ev("window.__long = []; new PerformanceObserver(l => { for (const e of l.getEntries()) window.__long.push(Math.round(e.duration)); }).observe({ entryTypes: ['longtask'] }); true");
  const t0 = Date.now(); await p.ev(H + "__click('打开 子任务.json')");
  await p.wait("!document.body.innerText.includes('正在读取子任务') && !document.body.innerText.includes('正在解析 JSON') && !!document.querySelector('[aria-label=\"下一页 JSON\"], [aria-label=\"上一页 JSON\"]')", 60000);
  const lt = await p.ev("window.__long"); log(`14 MB 子任务.json：打开到显示 ${Date.now() - t0} ms；长任务 ${lt.length} 个，最长 ${lt.length ? Math.max(...lt) : 0} ms：${JSON.stringify(lt)}`);
  await p.shot("m104-5-subtasks");
  await p.go("/datasets?panel=true"); await p.wait("!!document.querySelector('[aria-label=\"一致性面板\"]') && !document.body.innerText.includes('正在加载面板')", 20000); await sleep(1000);
  log("一致性面板：", (await p.ev("document.querySelector('[aria-label=\"一致性面板\"]').innerText")).replace(/\s+/g, " ").slice(0, 500));
  await p.shot("m104-6-panel");
  await p.go("/datasets"); await p.wait("!document.body.innerText.includes('正在加载数据集')", 15000); await sleep(800);
  await p.ev("[...document.querySelectorAll('[aria-label^=\"打开 \"]')].find(b => b.getAttribute('aria-label').includes('libero_10')).click()");
  await p.wait("document.body.innerText.includes('重新检查')", 15000); await sleep(500);
  await p.ev("[...document.querySelectorAll('button')].find(b => b.innerText.replace(/\\s/g,'') === '重新检查').click()");
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)", 15000); const job = await p.ev("location.pathname"); log("重新检查 → 作业页", job);
  for (let i = 0; i < 60; i++) { const s = await p.ev(`fetch('/api${job}').then(r=>r.json()).then(d=>d.state)`); if (["completed","failed"].includes(s)) { log("作业状态", s); break; } await sleep(1000); }
  await sleep(1200); await p.shot("m104-7-rescan-job");
  log("DRILL PASS");
} catch (e) { log("DRILL FAIL:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
