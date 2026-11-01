// M0 第 13 张浏览器部分：未登录刷新登录页 10 次；管理员登录后在新增数据集页用 antd 下拉框选数据来源；页面上没有原生 select。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m013-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9348", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9348/json/version")).json(); break; } catch { await sleep(200); } }
const ws = new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pending.set(i, (d) => (d.error ? rej(new Error(method + " " + JSON.stringify(d.error))) : res(d.result))); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const { browserContextId } = await send("Target.createBrowserContext");
const { targetId } = await send("Target.createTarget", { url: "about:blank", browserContextId });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, sessionId); await send("Runtime.enable", {}, sessionId);
const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }, sessionId); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; };
const go = async (path) => { await send("Page.navigate", { url: BASE + path }, sessionId); await sleep(1500); };
const shot = async (name) => { const { data } = await send("Page.captureScreenshot", { format: "png" }, sessionId); writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, "base64")); };
const wait = async (expr, ms = 15000) => { for (let t = 0; t < ms; t += 200) { if (await ev(expr)) return true; await sleep(200); } throw new Error("timeout: " + expr + " :: " + (await ev("document.body.innerText.slice(0,300)"))); };
const H = `
window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); if (!el) throw new Error('no input ' + name); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); };
window.__click = (text) => { const b = [...document.querySelectorAll('button')].filter(b => b.innerText.replace(/\\s/g,'') === text && !b.disabled).pop(); if (!b) throw new Error('no button ' + text); b.click(); };`;
let code = 0;
try {
  for (let i = 0; i < 10; i++) { await go("/login"); }
  await wait("document.querySelectorAll('input').length >= 2"); console.log("未登录刷新登录页 10 次完成");
  await ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await wait("location.pathname !== '/login'"); console.log("登录成功");
  await go("/datasets/new"); await wait("!!document.querySelector('[aria-label=\"数据来源\"]')", 20000); await sleep(800);
  console.log("原生 select 数量：", await ev("document.querySelectorAll('select').length"));
  await ev(`(() => { const el = document.querySelector('[aria-label="数据来源"]'); const sel = el.closest('.ant-select') || el; if (!sel) throw new Error(el.outerHTML.slice(0,300)); (sel.querySelector('.ant-select-selector') || sel).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return true; })()`);
  await wait("document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').length > 0");
  const opts = await ev("[...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')].map(o => o.innerText)");
  console.log("数据来源选项：", JSON.stringify(opts));
  await shot("m013-1-select-open");
  await ev("document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').click()"); await sleep(500);
  const shown = await ev(`(document.querySelector('[aria-label="数据来源"]').closest('.ant-select') || document.querySelector('[aria-label="数据来源"]').parentElement).innerText.trim()`);
  console.log("选中后显示：", shown, shown === opts[0] ? "（与第一项一致）" : "（不一致）");
  console.log("生成预览按钮可用：", await ev(`!document.querySelector('[aria-label="生成预览"]').disabled`));
  console.log("溢出：", await ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })"));
  await shot("m013-2-selected");
} catch (e) { console.log("失败：", e.message); code = 1; }
chrome.kill(); process.exit(code);
