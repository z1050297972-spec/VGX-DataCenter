// 验收 5 浏览器部分：照第 6–10 张演示的写法，用无头 Chrome 走一遍全过程并截图。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m152-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9347", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9347/json/version")).json(); break; } catch { await sleep(200); } }
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
const clickLabel = async (p, label) => p.ev(`(() => { const b = [...document.querySelectorAll('[aria-label="${label}"]')].filter(x => !x.disabled).pop(); if (!b) throw new Error('no clickable ${label}'); b.click(); return true; })()`);
const setVal = async (p, label, value) => p.ev(`(() => { const el = document.querySelector('[aria-label="${label}"]'); if (!el) throw new Error('no field ${label}'); const input = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') ? el : el.querySelector('input,textarea'); const proto = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const ovf = async (p) => p.ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })");
try {
  const p = await page();
  await p.go("/login"); await p.wait("document.querySelectorAll('input').length >= 2", 15000);
  await p.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await p.wait("location.pathname !== '/login'", 15000); log("登录成功");
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/libero_10")); await p.wait("!!document.querySelector('[aria-label=\"编辑导航层字段\"]')", 20000); await sleep(800);
  await clickLabel(p, "编辑导航层字段"); await p.wait("!!document.querySelector('[aria-label=\"机器人型号\"]')", 20000); await sleep(800);
  await setVal(p, "机器人型号", "Franka Panda（浏览器演练）"); await sleep(300);
  await p.shot("m152-1-editor"); log("编辑器 溢出：", await ovf(p));
  await clickLabel(p, "预览字段改动"); await p.wait("!!document.querySelector('[aria-label=\"字段预览差异\"]')", 60000); await sleep(1000);
  log("预览差异：", (await p.ev("document.querySelector('[aria-label=\"字段预览差异\"]').innerText")).replace(/\s+/g, " ").slice(0, 300));
  await p.shot("m152-2-preview"); log("预览 溢出：", await ovf(p));
  await p.wait("[...document.querySelectorAll('[aria-label=\"确认字段写入\"]')].some(b => !b.disabled)", 30000); await clickLabel(p, "确认字段写入");
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)", 30000); log("写入作业：", await p.ev("location.pathname")); await waitState(p, "completed", 60000); log("写入 completed"); await sleep(1500);
  await p.shot("m152-3-job");
  await clickLabel(p, "预览撤回导航改动"); await p.wait("[...document.querySelectorAll('[aria-label=\"确认撤回导航改动\"]')].some(b => !b.disabled)", 60000); await sleep(800);
  await p.shot("m152-4-revert-preview");
  await clickLabel(p, "确认撤回导航改动"); await sleep(1500);
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)", 30000); log("撤回作业：", await p.ev("location.pathname")); await waitState(p, "completed", 60000); log("撤回 completed");
  // 14 MB 子任务分页
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/agibot_world_2026")); await p.wait("!!document.querySelector('[aria-label=\"编辑导航层字段\"]')", 20000); await sleep(800);
  await clickLabel(p, "编辑导航层字段"); await sleep(1000);
  const t0 = Date.now();
  await p.ev("(() => { const s = document.querySelector('[aria-label=\"选择编辑文件\"]'); const sel = s.closest('.ant-select') || s; (sel.querySelector('.ant-select-selector') || sel).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return true; })()"); await sleep(800);
  log("选文件：", await p.ev("(() => { const o = [...document.querySelectorAll('.ant-select-item-option')].find(x => x.innerText.includes('子任务')); if (!o) return 'no option: ' + [...document.querySelectorAll('.ant-select-item-option')].map(x=>x.innerText).join('|'); o.click(); return 'ok'; })()"));
  await p.wait("[...document.querySelectorAll('[aria-label]')].some(x => / · 描述$/.test(x.getAttribute('aria-label')))", 60000);
  log(`14 MB 子任务第一页出现：${Date.now() - t0} ms；本页描述框 ${await p.ev("[...document.querySelectorAll('[aria-label]')].filter(x => / · 描述$/.test(x.getAttribute('aria-label'))).length")} 个`);
  log("子任务编辑 溢出：", await ovf(p)); await p.shot("m152-5-subtasks-page");
  log("DRILL PASS");
} catch (e) { log("DRILL FAIL:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
