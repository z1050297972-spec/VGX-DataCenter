// M1.5 第 05 张浏览器部分：改数据来源后留在数据集页，作业卡片运行中/成功两种状态，点 × 关闭。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m155-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9350", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9350/json/version")).json(); break; } catch { await sleep(200); } }
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
const sel = (l) => `[aria-label="${l}"]`;
try {
  await go("/login"); await wait("document.querySelectorAll('input').length >= 2");
  await ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await wait("location.pathname !== '/login'");
  await go("/datasets?selected=" + encodeURIComponent("按任务/libero_10")); await wait(`!!document.querySelector('${sel("选择数据来源")}')`, 20000); await sleep(800);
  console.log("当前：", await ev(`document.querySelector('${sel("当前数据来源")}')?.innerText`));
  await ev(`(() => { const el = document.querySelector('${sel("选择数据来源")}'); const s = el.closest('.ant-select') || el; s.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return true; })()`);
  await wait("[...document.querySelectorAll('.ant-select-item-option')].some(o => o.innerText.trim() === '开源下载')");
  await ev("[...document.querySelectorAll('.ant-select-item-option')].find(o => o.innerText.trim() === '开源下载').click()"); await sleep(400);
  await ev(`document.querySelector('${sel("预览数据来源")}').click()`);
  await wait(`[...document.querySelectorAll('${sel("确认修改数据来源")}')].some(b => !b.disabled)`, 60000); await sleep(500);
  const before = await ev("location.pathname + location.search");
  await ev(`[...document.querySelectorAll('${sel("确认修改数据来源")}')].find(b => !b.disabled).click()`);
  await wait(`!!document.querySelector('${sel("已提交作业")} .jobs-card')`, 15000); await sleep(300);
  console.log("确认前后地址：", before, "→", await ev("location.pathname + location.search"));
  console.log("卡片（刚提交）：", (await ev(`document.querySelector('${sel("已提交作业")}').innerText.replace(/\\s+/g,' ')`)));
  await shot("m155-1-card-running");
  await wait(`/成功|已完成|完成/.test(document.querySelector('${sel("已提交作业")}').innerText)`, 60000); await sleep(1500);
  console.log("卡片（结束）：", (await ev(`document.querySelector('${sel("已提交作业")}').innerText.replace(/\\s+/g,' ')`)));
  console.log("页面当前来源：", await ev(`document.querySelector('${sel("当前数据来源")}')?.innerText`));
  console.log("溢出：", await ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })"));
  await shot("m155-2-card-done");
  await ev(`document.querySelector('[aria-label^="关闭作业卡片"]').click()`); await sleep(600);
  console.log("关闭后卡片数：", await ev("document.querySelectorAll('.jobs-card').length"));
  await shot("m155-3-closed");
} catch (e) { console.log("失败：", e.message); code = 1; }
chrome.kill(); process.exit(code);
