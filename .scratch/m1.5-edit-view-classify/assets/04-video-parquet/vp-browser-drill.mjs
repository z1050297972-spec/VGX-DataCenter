// 验收 5 浏览器部分：照第 6–10 张演示的写法，用无头 Chrome 走一遍全过程并截图。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m154-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9350", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9350/json/version")).json(); break; } catch { await sleep(200); } }
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
const clickLabel = async (p, label) => p.ev(`(() => { const b = [...document.querySelectorAll('[aria-label="${label}"]')].filter(x => !x.disabled).pop(); if (!b) throw new Error('no clickable ${label}: ' + [...document.querySelectorAll('[aria-label]')].map(x=>x.getAttribute('aria-label')).filter(l => /打开|预览|查看/.test(l)).slice(0,20).join('|')); b.click(); return true; })()`);
try {
  const p = await page();
  await p.go("/login"); await p.wait("document.querySelectorAll('input').length >= 2", 15000);
  await p.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await p.wait("location.pathname !== '/login'", 15000); log("登录成功");
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/libero_10")); await p.wait("!!document.querySelector('[aria-label=\"查看原文件\"]')", 20000); await sleep(800);
  // 模拟不支持 AV1 的浏览器：只对 AV1 返回空
  await p.ev("(() => { const o = HTMLMediaElement.prototype.canPlayType; HTMLMediaElement.prototype.canPlayType = function (t) { return /av01|av1/i.test(t) ? '' : o.call(this, t); }; if (window.MediaSource) { const m = MediaSource.isTypeSupported.bind(MediaSource); MediaSource.isTypeSupported = (t) => /av01|av1/i.test(t) ? false : m(t); } return true; })()");
  await clickLabel(p, "查看原文件"); await sleep(1500);
  log("选链接：", await p.ev("(() => { const s = document.querySelector('[aria-label=\"选择原文件链接\"]'); if (!s) return 'none'; if (s.tagName === 'SELECT') { const o = [...s.options].find(x => x.text.includes('原始数据')); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value); s.dispatchEvent(new Event('change', { bubbles: true })); return 'native'; } const sel = s.closest('.ant-select') || s; (sel.querySelector('.ant-select-selector') || sel).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return 'antd-open'; })()")); await sleep(800);
  log("选项：", await p.ev("(() => { const o = [...document.querySelectorAll('.ant-select-item-option')].find(x => x.innerText.includes('原始数据')); if (!o) return 'no option (maybe native/already)'; o.click(); return 'ok'; })()")); await sleep(1500);
  await p.wait("!!document.querySelector('[aria-label=\"打开目录 data\"]')", 20000);
  await clickLabel(p, "打开目录 data"); await sleep(1500);
  const dsub = await p.ev("[...document.querySelectorAll('[aria-label^=\"打开目录 \"]')].map(x => x.getAttribute('aria-label').slice(5))"); await clickLabel(p, "打开目录 " + dsub[0]); await sleep(1500);
  const pq = await p.ev("[...document.querySelectorAll('[aria-label^=\"预览文件 \"]')].map(x => x.getAttribute('aria-label').slice(5)).find(f => f.endsWith('.parquet'))");
  await clickLabel(p, "预览文件 " + pq); await p.wait("!!document.querySelector('[aria-label=\"parquet数据表格\"]')", 30000); await sleep(1500);
  log("parquet：", pq, (await p.ev("document.body.innerText")).replace(/\s+/g, " ").match(/(行数|总行|行组|列)[^。]{0,80}/g)?.slice(0, 3).join(" | "));
  log("parquet 表格行：", await p.ev("document.querySelectorAll('[aria-label=\"parquet数据表格\"] .ant-table-tbody tr').length"));
  log("溢出：", await p.ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })")); await p.shot("m154-1-parquet");
  await clickLabel(p, "原文件上一级"); await sleep(1200); await clickLabel(p, "原文件上一级"); await sleep(1200);
  await clickLabel(p, "打开目录 videos"); await sleep(1500);
  const v1 = await p.ev("[...document.querySelectorAll('[aria-label^=\"打开目录 \"]')].map(x => x.getAttribute('aria-label').slice(5))"); await clickLabel(p, "打开目录 " + v1[0]); await sleep(1500);
  const v2 = await p.ev("[...document.querySelectorAll('[aria-label^=\"打开目录 \"]')].map(x => x.getAttribute('aria-label').slice(5))"); if (v2.length) { await clickLabel(p, "打开目录 " + v2[0]); await sleep(1500); }
  const mp4 = await p.ev("[...document.querySelectorAll('[aria-label^=\"预览文件 \"]')].map(x => x.getAttribute('aria-label').slice(5)).find(f => f.endsWith('.mp4'))");
  await clickLabel(p, "预览文件 " + mp4); await sleep(6000);
  log("视频区域：", (await p.ev("document.body.innerText")).replace(/\s+/g, " ").match(/(转码|原文件|编码|时长)[^。]{0,60}/g)?.slice(0, 4).join(" | "));
  const v = await p.ev("(async () => { const v = document.querySelector('[aria-label=\"原文件视频\"]') || document.querySelector('video'); if (!v) return 'no video'; v.muted = true; try { await v.play(); } catch (e) { return 'play error ' + e.message + ' src=' + v.currentSrc; } await new Promise(r => setTimeout(r, 4000)); return JSON.stringify({ src: v.currentSrc.replace(location.origin, '').slice(0, 160), t: v.currentTime, readyState: v.readyState, error: v.error && v.error.code, w: v.videoWidth, h: v.videoHeight }); })()");
  log("播放：", v); await p.shot("m154-2-video-transcode");
  log("下一段：", await p.ev("(() => { const b = document.querySelector('[aria-label=\"视频下一段\"]'); if (!b) return 'none'; b.click(); return 'clicked'; })()")); await sleep(6000);
  log("下一段后：", await p.ev("(async () => { const v = document.querySelector('video'); if (!v) return 'no video'; v.muted = true; try { await v.play(); } catch (e) {} await new Promise(r => setTimeout(r, 3000)); return JSON.stringify({ src: v.currentSrc.replace(location.origin, '').slice(0, 160), t: v.currentTime, readyState: v.readyState, error: v.error && v.error.code }); })()"));
  log("溢出：", await p.ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })"));
  log("DRILL PASS");
} catch (e) { log("DRILL FAIL:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
