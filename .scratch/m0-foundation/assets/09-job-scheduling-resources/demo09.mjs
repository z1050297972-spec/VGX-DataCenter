import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-demo9-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9339", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9339/json/version")).json(); break; } catch { await sleep(200); } }
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
const body = (p) => p.ev("document.body.innerText");
const jobApi = (p, id) => p.ev(`fetch('/api/jobs/${id}').then(r=>r.json())`);
async function waitJob(p, id, pred, ms, what) { const t = Date.now(); for (;;) { const j = await jobApi(p, id); if (pred(j)) return j; if (Date.now() - t > ms) throw new Error(`job ${id} ${what}: ${JSON.stringify(j).slice(0, 300)}`); await sleep(400); } }
async function submitForm(p, fill, button) {
  await p.go("/jobs/resources"); await p.wait("document.body.innerText.includes('示例：占用 GPU')");
  await p.ev(H + fill); await sleep(300); await p.ev(H + `__click('${button}')`);
  await p.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)"); const id = Number((await p.ev("location.pathname")).split("/").pop()); log("提交", button, "→", id); return id;
}
const sched = async (p) => { await p.go("/scheduling"); await p.wait("document.body.innerText.includes('GPU 名额')"); await sleep(800); return (await body(p)).replace(/\s+/g, " "); };
try {
  startWorker("W1"); await sleep(5000);
  const admin = await page();
  await admin.go("/login"); await admin.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await admin.wait("location.pathname === '/'"); log("admin 登录");
  log("启动后调度页:", (await sched(admin)).slice(0, 900)); await admin.shot("demo9-0-scheduling-idle");
  // 验收 9 前半：三个占卡作业，两张卡各占一个，第三个等卡
  const g = [];
  for (let i = 0; i < 3; i++) g.push(await submitForm(admin, "__fill('hold_s','40')", "提交占卡作业"));
  const r1 = await waitJob(admin, g[0], (j) => j.state === "running" && j.gpu_index !== null, 15000, "running");
  const r2 = await waitJob(admin, g[1], (j) => j.state === "running" && j.gpu_index !== null, 15000, "running");
  const q3 = await waitJob(admin, g[2], (j) => j.state === "queued" && j.wait_reason === "gpu", 15000, "wait gpu");
  log("占卡:", g[0], "GPU", r1.gpu_index, "|", g[1], "GPU", r2.gpu_index, "|", g[2], q3.state, q3.wait_reason);
  log("两卡占满时调度页:", (await sched(admin)).slice(0, 900)); await admin.shot("demo9-1-two-cards-busy");
  await admin.go(`/jobs/${g[2]}`); await sleep(1500); log("第三个作业页:", (await body(admin)).replace(/\s+/g, " ").slice(0, 500)); await admin.shot("demo9-2-third-waits-gpu");
  await admin.go("/jobs"); await sleep(1500); log("作业列表:", (await rows(admin)).slice(0, 5)); await admin.shot("demo9-3-list-wait");
  await admin.go(`/jobs/${g[0]}`); await sleep(1500);
  log("作业1 日志:", await admin.ev("(document.querySelector('[aria-label=\"作业日志\"]')||{}).innerText||''"));
  // 第一个结束后第三个领到它让出的卡
  const r3 = await waitJob(admin, g[2], (j) => j.state === "running" && j.gpu_index !== null, 70000, "third running");
  log("第三个领卡:", r3.gpu_index, "（作业1 用的是", r1.gpu_index, "）");
  // 验收 9 后半：两个写锁作业，一个持锁暂停，另一个等锁
  const n1 = await submitForm(admin, "__fill('expected_value',''); __fill('pause_s','10')", "提交写锁作业");
  await waitJob(admin, n1, (j) => j.holds_navigation_lock === true, 15000, "holds lock");
  const n2 = await submitForm(admin, "__fill('expected_value',''); __fill('pause_s','0')", "提交写锁作业");
  const w2 = await waitJob(admin, n2, (j) => j.wait_reason === "navigation_lock", 10000, "wait lock");
  log("写锁:", n1, "持锁 |", n2, w2.state, w2.wait_reason);
  log("持锁时调度页:", (await sched(admin)).slice(0, 900)); await admin.shot("demo9-4-lock-held");
  await admin.go(`/jobs/${n2}`); await sleep(1200); log("等锁作业页:", (await body(admin)).replace(/\s+/g, " ").slice(0, 500)); await admin.shot("demo9-5-waiting-lock");
  const f1 = await waitJob(admin, n1, (j) => j.state === "completed", 30000, "n1 done");
  const f2 = await waitJob(admin, n2, (j) => j.state === "completed", 30000, "n2 done");
  log("写锁结果:", n1, f1.state, f1.outcome, "|", n2, f2.state, f2.outcome);
  log("示例文件:", await admin.ev("fetch('/api/scheduling').then(r=>r.json()).then(d=>d.navigation_job_id)"));
  await admin.go(`/jobs/${n2}`); await sleep(1500); log("作业", n2, "页面:", (await body(admin)).replace(/\s+/g, " ").slice(0, 900)); await admin.shot("demo9-6-lock-conflict");
  // 按提示带上作业 n1 的值重新提交，应成功
  const n3 = await submitForm(admin, `__fill('expected_value','${n1}'); __fill('pause_s','0')`, "提交写锁作业");
  const f3 = await waitJob(admin, n3, (j) => j.state === "completed", 30000, "n3 done"); log("带正确期望值:", n3, f3.state, f3.outcome);
  await waitJob(admin, g[2], (j) => j.state === "completed", 60000, "third done");
  log("结束后调度页:", (await sched(admin)).slice(0, 900)); await admin.shot("demo9-7-idle-after");
} catch (e) { log("DEMO FAILED:", e.message); process.exitCode = 1; }
finally { for (const w of workers) { try { w.kill("SIGTERM"); } catch {} } await sleep(4000); for (const w of workers) { try { w.kill("SIGKILL"); } catch {} } chrome.kill("SIGKILL"); ws.close(); }
