// 验收 5 浏览器部分：照第 6–10 张演示的写法，用无头 Chrome 走一遍全过程并截图。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m110-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9344", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9344/json/version")).json(); break; } catch { await sleep(200); } }
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
try {
  const p = await page();
  await p.go("/login"); await p.wait("document.querySelectorAll('input').length >= 2", 15000);
  await p.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await p.wait("location.pathname !== '/login'", 15000); log("登录成功");
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/libero_10")); await p.wait("!!document.querySelector('[aria-label=\"数据来源标注\"]')", 20000); await sleep(1000);
  await p.shot("m110-1-detail");
  await p.ev("(() => { const s = document.querySelector('[aria-label=\"选择数据来源\"]'); const el = s.closest('.ant-select') || s; el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return true; })()"); await sleep(800);
  await p.ev("(() => { const o = [...document.querySelectorAll('.ant-select-item-option')].find(x => x.innerText.includes('仿真生成')); if (!o) throw new Error('no option 仿真生成: ' + [...document.querySelectorAll('.ant-select-item-option')].map(x=>x.innerText).join('|')); o.click(); return true; })()"); await sleep(500);
  await p.ev(H + "__click('预览数据来源')");
  await p.wait("!!document.querySelector('[aria-label=\"数据来源预览差异\"]')", 60000); await sleep(800);
  log("预览差异：", (await p.ev("document.querySelector('[aria-label=\"数据来源预览差异\"]').innerText")).replace(/\s+/g, " ").slice(0, 300));
  log("横向溢出：", await p.ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })"));
  await p.shot("m110-2-preview");
  await p.ev(H + "__click('确认修改数据来源')");
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)", 20000); const job = await p.ev("location.pathname"); log("写入作业页：", job);
  await waitState(p, "completed", 60000); log("写入作业 completed"); await sleep(1500); await p.shot("m110-3-job");
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/libero_10")); await sleep(3000);
  log("详情里来源：", (await p.ev("document.querySelector('[aria-label=\"数据来源标注\"]').innerText")).replace(/\s+/g, " ").slice(0, 200));
  await p.go("/datasets?data_origin=simulation"); await sleep(3000);
  log("按仿真生成筛选：", await p.ev("[...document.querySelectorAll('[aria-label^=\"打开 \"]')].map(b => b.getAttribute('aria-label')).join(',')"));
  await p.shot("m110-4-filter");
  log("DRILL PASS");
} catch (e) { log("DRILL FAIL:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
