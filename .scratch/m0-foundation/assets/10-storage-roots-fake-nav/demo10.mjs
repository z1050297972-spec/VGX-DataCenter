import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-demo10-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9340", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9340/json/version")).json(); break; } catch { await sleep(200); } }
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
const body = (p) => p.ev("document.body.innerText");
const TAG = process.env.TAG || "ok";
try {
  const p = await page();
  await p.go("/login"); await p.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await p.wait("location.pathname === '/'"); log("admin 登录");
  const menu = await p.ev("[...document.querySelectorAll('a')].map(a=>a.innerText.trim()).filter(Boolean)"); log("菜单:", JSON.stringify(menu));
  await p.ev("[...document.querySelectorAll('a')].find(a=>a.innerText.trim()==='存储根').click()");
  await p.wait("location.pathname === '/storage-roots' && document.querySelectorAll('.ant-table-tbody tr').length >= 2", 10000);
  await sleep(800);
  log("表格:", JSON.stringify(await rows(p)));
  log("API:", JSON.stringify(await p.ev("fetch('/api/storage-roots').then(r=>r.json())")));
  await p.shot(`demo10-${TAG}`);
  const before = await p.ev("(document.querySelector('time')||{}).dateTime||''");
  await sleep(1200); await p.ev(H + "__click('重新检查')"); await sleep(1500);
  const after = await p.ev("(document.querySelector('time')||{}).dateTime||''");
  log("重新检查前后检查时间:", before, "→", after);
  // 成员视角：未登录访问被拒
  log("未登录 API 状态:", await p.ev("fetch('/api/storage-roots',{credentials:'omit'}).then(r=>r.status)"));
} catch (e) { log("DEMO FAILED:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
