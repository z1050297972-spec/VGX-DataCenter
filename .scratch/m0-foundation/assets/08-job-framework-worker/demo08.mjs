import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-demo8-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9338", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9338/json/version")).json(); break; } catch { await sleep(200); } }
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
    wait: async (expr, ms = 8000) => { for (let t = 0; t < ms; t += 200) { if (await ev(expr)) return true; await sleep(200); } throw new Error("timeout: " + expr + " @ " + (await ev("location.href")) + " :: " + (await ev("document.body.innerText.slice(0,300)"))); },
    front: () => send("Page.bringToFront", {}, sessionId),
  };
}
const H = `
window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); if (!el) throw new Error('no input ' + name); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); };
window.__click = (text, scope) => { const root = scope ? [...document.querySelectorAll(scope)].pop() : document; const b = [...root.querySelectorAll('button')].filter(b => (b.getAttribute('aria-label') || b.innerText.replace(/\\s/g,'')) === text && !b.disabled).pop(); if (!b) throw new Error('no button ' + text); b.click(); };`;
const log = (...a) => console.log(...a);
const rows = (p) => p.ev("[...document.querySelectorAll(\x27.ant-table-tbody tr\x27)].map(r => r.innerText.replace(/\\s+/g,\x27 \x27)).filter(t => t && !t.includes(\x27暂无数据\x27))");
const PY = process.env.PY, DEMO = process.env.DEMO, ROOT = process.env.ROOT, PP = process.env.PP;
const workers = [];
const startWorker = (tag) => { const w = spawn(PY, [DEMO, "worker", ROOT], { env: { ...process.env, PYTHONPATH: PP }, stdio: ["ignore", "pipe", "pipe"] }); w.stdout.on("data", (d) => log(`[${tag}]`, String(d).trim())); w.stderr.on("data", (d) => log(`[${tag} err]`, String(d).trim().slice(0, 400))); workers.push(w); log(tag, "pid", w.pid); return w; };
const prog = (p) => p.ev("(document.querySelector('[aria-label=\"作业进度\"]')||{}).innerText || ''");
const body = (p) => p.ev("document.body.innerText");
const st = (p) => p.ev("fetch('/api' + location.pathname).then(r=>r.json()).then(d=>d.state)");
async function waitState(p, want, ms) { const t = Date.now(); for (;;) { const s = await st(p); if (s === want) return; if (Date.now() - t > ms) throw new Error("state " + s + " != " + want); await sleep(400); } }
async function submit(p, steps, interval) {
  await p.go("/jobs/new"); await p.wait("document.body.innerText.includes('提交示例作业') && !!document.querySelector('input')");
  await p.ev(H + `__fill('steps','${steps}'); __fill('interval_ms','${interval}');`); await sleep(300);
  await p.ev(H + "__click('提交作业')");
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)"); const path = await p.ev("location.pathname"); log("提交 →", path); return path;
}
try {
  let w1 = startWorker("W1"); await sleep(3000);
  const admin = await page();
  await admin.go("/login"); await admin.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await admin.wait("location.pathname === '/'"); log("admin 登录");
  await sleep(2500); log("worker 在线时横幅:", (await body(admin)).includes("worker 没在运行"));
  // 1) 30 步看着走完
  const j1 = await submit(admin, 30, 300);
  const seen = new Set(); for (let t = 0; t < 30; t++) { const pr = await prog(admin); seen.add(pr.replace(/\s+/g, " ")); if ((await st(admin)) === "completed") break; await sleep(700); }
  log("作业1 进度采样:", JSON.stringify([...seen])); await waitState(admin, "completed", 20000); await sleep(1500);
  log("作业1 页面:", (await body(admin)).replace(/\s+/g, " ").slice(0, 900)); await admin.shot("demo8-1-completed");
  // 2) 中途取消
  const j2 = await submit(admin, 30, 500);
  await waitState(admin, "running", 15000); await sleep(3000); log("作业2 取消前进度:", await prog(admin));
  await admin.ev(H + "__click('取消作业')"); await sleep(500);
  const confirm = await admin.ev("[...document.querySelectorAll('.ant-modal button, .ant-popconfirm button, .ant-popover button')].map(b=>b.innerText)"); log("取消后弹出的按钮:", JSON.stringify(confirm));
  if (confirm.length) { await admin.ev("[...document.querySelectorAll('.ant-modal button, .ant-popconfirm button, .ant-popover button')].filter(b=>/确定|确认|取消作业|OK/.test(b.innerText.replace(/\\s/g,''))).pop()?.click()"); }
  await waitState(admin, "cancelled", 15000); await sleep(1500); log("作业2 页面:", (await body(admin)).replace(/\s+/g, " ").slice(0, 900)); await admin.shot("demo8-2-cancelled");
  // 3) 中途 kill -9
  const j3 = await submit(admin, 30, 500);
  await waitState(admin, "running", 15000); await sleep(4000); const before = await prog(admin); log("作业3 kill 前进度:", before);
  process.kill(w1.pid, "SIGKILL"); log("kill -9 W1", new Date().toISOString());
  const t0 = Date.now(); for (;;) { if ((await body(admin)).includes("worker 没在运行")) break; if (Date.now() - t0 > 40000) throw new Error("横幅未出现"); await sleep(500); }
  log(`横幅出现，kill 后 ${(Date.now() - t0) / 1000}s`); await admin.shot("demo8-3-offline-banner");
  await admin.go("/accounts"); await sleep(1500); log("账号页也有横幅:", (await body(admin)).includes("worker 没在运行"));
  await admin.go(j3); await sleep(1500);
  const w2 = startWorker("W2");
  await waitState(admin, "interrupted", 30000); await sleep(1500); const t1 = Date.now();
  for (;;) { if (!(await body(admin)).includes("worker 没在运行")) break; if (Date.now() - t1 > 15000) throw new Error("横幅未消失"); await sleep(500); }
  log("作业3 已中断，横幅消失"); await sleep(1500);
  log("作业3 页面:", (await body(admin)).replace(/\s+/g, " ").slice(0, 1500));
  log("作业3 日志:", await admin.ev("(document.querySelector('[aria-label=\"作业日志\"]')||{}).innerText||''"));
  await admin.shot("demo8-4-interrupted");
  // 重新提交
  await admin.ev(H + "__click('重新提交')"); await sleep(800);
  const conf2 = await admin.ev("[...document.querySelectorAll('.ant-modal button, .ant-popconfirm button, .ant-popover button')].map(b=>b.innerText)");
  if (conf2.length) { log("重提弹出:", JSON.stringify(conf2)); await admin.ev("[...document.querySelectorAll('.ant-modal button, .ant-popconfirm button, .ant-popover button')].filter(b=>/确定|确认|重新提交|OK/.test(b.innerText.replace(/\\s/g,''))).pop()?.click()"); }
  await admin.wait(`/^\\/jobs\\/\\d+$/.test(location.pathname) && location.pathname !== '${j3}'`, 10000); await sleep(1500);
  log("重提 →", await admin.ev("location.pathname"), (await body(admin)).replace(/\s+/g, " ").slice(0, 600)); await admin.shot("demo8-5-resubmitted");
  for (const j of [j1, j2, j3]) log("API", j, await admin.ev(`fetch('/api${j}').then(r=>r.json()).then(d=>JSON.stringify({state:d.state,progress:d.progress,result:d.result, summary:d.summary}))`));
  await admin.go("/audit/operations"); await sleep(2000); log("操作日志:", JSON.stringify(await rows(admin)));
  process.kill(w2.pid, "SIGTERM"); await sleep(3000);
} catch (e) { log("DEMO ERROR", e.message); process.exitCode = 1; }
finally { for (const w of workers) { try { process.kill(w.pid, "SIGKILL"); } catch {} } ws.close(); chrome.kill("SIGKILL"); }
