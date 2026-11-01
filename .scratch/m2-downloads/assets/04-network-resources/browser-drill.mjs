// 第 04 张浏览器演练：登录后打开网络与资源页，等镜像检查和资源快照出来，截图并输出页面文字。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m204-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9347", `--user-data-dir=${profile}`, "--window-size=1280,1000", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9347/json/version")).json(); break; } catch { await sleep(200); } }
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
const wait = async (expr, ms = 15000) => { for (let t = 0; t < ms; t += 250) { if (await ev(expr)) return; await sleep(250); } throw new Error("timeout: " + expr); };
const H = `window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); return true; }; window.__label = (l) => { const b = [...document.querySelectorAll('[aria-label="' + l + '"]')].filter(x => !x.disabled).pop(); if (!b) throw new Error('no ' + l); b.click(); return true; };`;
try {
  await go("/login"); await wait("document.querySelectorAll('input').length >= 2");
  await ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __label('登录')");
  await wait("location.pathname !== '/login'");
  const link = await ev("[...document.querySelectorAll('a')].find(a => a.innerText.includes('网络'))?.getAttribute('href') ?? ''");
  console.log("导航链接：", link);
  await go(link || "/monitoring"); await sleep(20000);
  console.log("页面：", (await ev("document.body.innerText.replace(/\\s+/g,' ')")).slice(0, 1500));
  console.log("溢出：", await ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })"));
  await shot("m204-1-monitoring");
} catch (e) { console.log("演练失败：", e.message); process.exitCode = 1; }
finally { chrome.kill(); }
