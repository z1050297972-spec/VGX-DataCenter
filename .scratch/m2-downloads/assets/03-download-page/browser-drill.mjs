// 第 03 张浏览器演练：无头 Chrome 走下载页、预览诊断、暂存区、token 设置并截图（写法同 M1 第 08 张演练）。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m203-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9346", `--user-data-dir=${profile}`, "--window-size=1280,1000", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9346/json/version")).json(); break; } catch { await sleep(200); } }
const ws = new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pending.set(i, (d) => (d.error ? rej(new Error(method + " " + JSON.stringify(d.error))) : res(d.result))); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, sessionId); await send("Runtime.enable", {}, sessionId);
const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }, sessionId); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; };
const go = async (path) => { await send("Page.navigate", { url: BASE + path }, sessionId); await sleep(1500); };
const shot = async (name) => { const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }, sessionId); writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, "base64")); console.log("截图", name); };
const wait = async (expr, ms = 15000) => { for (let t = 0; t < ms; t += 250) { if (await ev(expr)) return; await sleep(250); } throw new Error("timeout: " + expr + " :: " + (await ev("document.body.innerText.slice(0,400)"))); };
const H = `
window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); if (!el) throw new Error('no input ' + name); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); return true; };
window.__label = (label) => { const b = [...document.querySelectorAll('[aria-label="' + label + '"]')].filter(x => !x.disabled).pop(); if (!b) throw new Error('no ' + label); b.click(); return true; };
window.__button = (text) => { const b = [...document.querySelectorAll('button')].filter(b => b.innerText.replace(/\\s/g,'') === text && !b.disabled).pop(); if (!b) throw new Error('no button ' + text); b.click(); return true; };`;
const body = () => ev("document.body.innerText.replace(/\\s+/g,' ')");
const ovf = () => ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })");
try {
  await go("/login"); await wait("document.querySelectorAll('input').length >= 2");
  await ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __label('登录')");
  await wait("location.pathname !== '/login'"); console.log("登录成功");
  await go("/downloads"); await ev(H + "true"); await wait("!!document.querySelector('[aria-label=\"预览\"]')");
  console.log("导航里有下载：", await ev("document.body.innerText.includes('下载')"));
  await ev("__fill('repo_id','lerobot/pusht')");
  // 目标存储根：只有 dataset1 一个可写根；没自动选上就点开下拉选它。
  const picked = await ev("(() => { const item = [...document.querySelectorAll('.ant-form-item')].find(f => f.innerText.includes('目标存储根')); return item ? item.innerText : ''; })()");
  if (!picked.includes("dataset1")) {
    await ev("(() => { const item = [...document.querySelectorAll('.ant-form-item')].find(f => f.innerText.includes('目标存储根')); (item.querySelector('[role=combobox]') ?? item.querySelector('.ant-select')).dispatchEvent(new MouseEvent('mousedown', {bubbles:true})); return true; })()"); await sleep(600);
    await ev("(() => { const o = [...document.querySelectorAll('.ant-select-item-option')].find(o => o.innerText.includes('dataset1')); if (!o) throw new Error('no option dataset1'); o.click(); return true; })()"); await sleep(400);
  }
  await shot("m203-1-form"); console.log("表单 溢出：", await ovf());
  await ev("__label('高级参数')"); await sleep(800);
  const adv = await body(); console.log("高级参数展开：", ["同时下几个文件", "每服务器连接数", "每文件分段数", "最小分段大小", "重试次数", "重试间隔"].map(k => k + "=" + adv.includes(k)).join(" "));
  await shot("m203-2-advanced");
  await ev("__label('预览')"); console.log("已提交预览");
  await sleep(1000); await wait("!document.body.innerText.includes('正在生成预览')", 90000); await sleep(1500);
  const pv = await body(); console.log("预览结果：", (pv.match(/确认下载.{0,300}/) ?? [""])[0]);
  await shot("m203-3-preview");
  if (await ev("!!document.querySelector('[aria-label=\"刷新暂存列表\"]')")) { await ev("__label('刷新暂存列表')"); await sleep(5000); await shot("m203-4-staging"); console.log("暂存区：", ((await body()).match(/暂存.{0,160}/) ?? [""])[0]); }
  else console.log("下载页上没有暂存区刷新按钮");
  await go("/accounts"); await ev(H + "true"); await wait("document.body.innerText.includes('Hugging Face token')");
  await ev("__fill('token','hf_token_drill_secret')"); await ev("__button('设置token')"); await sleep(2000);
  const tk = await body(); console.log("设置后：", (tk.match(/Hugging Face token.{0,80}/) ?? [""])[0], "| 页面含明文：", tk.includes("hf_token_drill_secret"));
  await shot("m203-5-token");
  await ev("__button('清除token')"); await sleep(1500); const ok2 = await ev("[...document.querySelectorAll('.ant-popconfirm button, .ant-modal button')].find(b => /确定|确认|OK/.test(b.innerText))"); if (ok2 !== undefined) await ev("[...document.querySelectorAll('.ant-popconfirm button, .ant-modal button')].find(b => /确定|确认|OK/.test(b.innerText)).click()"); await sleep(1500);
  console.log("清除后：", ((await body()).match(/Hugging Face token.{0,60}/) ?? [""])[0]);
} catch (e) { console.log("演练失败：", e.message); process.exitCode = 1; }
finally { chrome.kill(); }
