// 验收 5 浏览器部分：照第 6–10 张演示的写法，用无头 Chrome 走一遍全过程并截图。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-m108-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9345", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9345/json/version")).json(); break; } catch { await sleep(200); } }
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
const setVal = async (p, label, value) => p.ev(`(() => { const el = document.querySelector('[aria-label="${label}"]'); if (!el) throw new Error('no field ${label}'); const input = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') ? el : el.querySelector('input,textarea'); if (!input) throw new Error('no input in ${label}'); const proto = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const clickLabel = async (p, label) => p.ev(`(() => { const b = [...document.querySelectorAll('[aria-label="${label}"]')].filter(x => !x.disabled).pop(); if (!b) throw new Error('no clickable ${label}'); b.click(); return true; })()`);
const ovf = async (p) => p.ev("JSON.stringify({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })");
try {
  const p = await page();
  await p.go("/login"); await p.wait("document.querySelectorAll('input').length >= 2", 15000);
  await p.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await p.wait("location.pathname !== '/login'", 15000); log("登录成功");
  // —— 建链 ——
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/libero_10")); await p.wait("!!document.querySelector('[aria-label=\"建链\"]')", 20000); await sleep(800);
  await clickLabel(p, "建链"); await sleep(1500);
  await setVal(p, "链接名", "演练链接"); await setVal(p, "目标路径", "/mnt/dataset1/libero_v3/libero_goal"); await sleep(500);
  await p.shot("m108-1-link-form"); log("建链表单 溢出：", await ovf(p));
  await clickLabel(p, "生成预览"); await p.wait("!!document.querySelector('[aria-label=\"确认写入\"]') && !document.querySelector('[aria-label=\"确认写入\"]').disabled || document.body.innerText.includes('格式入口')", 60000); await sleep(1500);
  log("建链预览：", (await p.ev("document.body.innerText")).replace(/\s+/g, " ").match(/预览.{0,400}/)?.[0] ?? "");
  const boxes = await p.ev("[...document.querySelectorAll('[aria-label^=\"格式入口 \"]')].map(b => b.getAttribute('aria-label') + ':' + (b.checked ?? b.getAttribute('aria-checked')))");
  log("格式入口候选：", JSON.stringify(boxes));
  await p.shot("m108-2-link-preview"); log("建链预览 溢出：", await ovf(p));
  await p.wait("!!document.querySelector('[aria-label=\"确认写入\"]') && !document.querySelector('[aria-label=\"确认写入\"]').disabled", 30000);
  await clickLabel(p, "确认写入");
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)", 30000); log("建链写入作业：", await p.ev("location.pathname"));
  await waitState(p, "completed", 60000); log("建链作业 completed"); await sleep(1500); await p.shot("m108-3-link-job");
  // —— 新增数据集 ——
  await p.go("/datasets"); await p.wait("!!document.querySelector('[aria-label=\"新增数据集\"]')", 20000); await sleep(800);
  await clickLabel(p, "新增数据集"); await sleep(1500);
  await setVal(p, "数据集名", "M1_08_浏览器演练"); await setVal(p, "链接名", "原始数据"); await setVal(p, "目标路径", "/mnt/dataset1/lerobot"); await sleep(500);
  for (const [label, value] of [["数据来源", "开源下载"], ["无元信息时的格式", "mcap"]]) {
    const r = await p.ev(`(() => { const s = document.querySelector('select[aria-label="${label}"]'); if (!s) return 'no select'; const o = [...s.options].find(x => x.value === '${value}' || x.text.replace(/\\s/g,'') === '${value}'.replace(/\\s/g,'')); if (!o) return 'no option: ' + [...s.options].map(x => x.value + '/' + x.text).join('|'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; set.call(s, o.value); s.dispatchEvent(new Event('change', { bubbles: true })); return 'ok ' + o.value; })()`); log(`选 ${label}：`, r); await sleep(400);
  }
  log("勾选格式入口 mcap：", await p.ev("(() => { const b = document.querySelector('[aria-label=\"格式入口 mcap\"]'); if (!b) return 'none'; if (!b.checked) b.click(); return b.checked; })()")); await sleep(400);
  await p.shot("m108-4-create-form"); log("新增表单 溢出：", await ovf(p));
  await clickLabel(p, "生成预览"); await sleep(2000);
  await p.wait("document.body.innerText.includes('dataset-36') || document.body.innerText.includes('格式入口')", 60000); await sleep(1500);
  log("新增预览：", (await p.ev("document.body.innerText")).replace(/\s+/g, " ").match(/dataset-36.{0,300}/)?.[0] ?? "(no dataset-36 text)");
  await p.shot("m108-5-create-preview"); log("新增预览 溢出：", await ovf(p));
  log("确认写入按钮：", await p.ev("JSON.stringify([...document.querySelectorAll('[aria-label=\"确认写入\"]')].map(b => b.disabled))"));
  await p.wait("[...document.querySelectorAll('[aria-label=\"确认写入\"]')].some(b => !b.disabled)", 30000);
  await clickLabel(p, "确认写入"); await sleep(2500);
  if (await p.ev("!!document.querySelector('[aria-label=\"排队作业确认\"]')")) { log("出现排队作业确认（409）"); await p.shot("m108-5b-queue-409"); await p.ev("[...document.querySelectorAll('[aria-label^=\"确认排队作业 \"]')].forEach(b => { if (!b.checked) b.click(); }); true"); await sleep(400); await clickLabel(p, "确认排队并提交"); }
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)", 30000); log("新增写入作业：", await p.ev("location.pathname"));
  await waitState(p, "completed", 60000); log("新增作业 completed"); await sleep(4000);
  await p.go("/datasets?selected=" + encodeURIComponent("按任务/M1_08_浏览器演练")); await sleep(3500);
  log("新数据集详情：", (await p.ev("document.body.innerText")).replace(/\s+/g, " ").match(/M1_08_浏览器演练.{0,200}/)?.[0] ?? "");
  await p.shot("m108-6-new-dataset");
  log("DRILL PASS");
} catch (e) { log("DRILL FAIL:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
