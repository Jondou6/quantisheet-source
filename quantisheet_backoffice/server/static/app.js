// Back Office self-service and punch pages. Punches are queued in this
// phone's storage with the time they were made and sent when online.
"use strict";
const $ = (id) => document.getElementById(id);
const tok = () => sessionStorage.getItem("qsbo") || localStorage.getItem("qsbo_punch");
async function api(method, path, body) {
  const r = await fetch(path, {method, headers: {"Content-Type": "application/json",
    "Authorization": "Bearer " + tok()}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}
function localIso(d) {
  const off = -d.getTimezoneOffset(), s = off >= 0 ? "+" : "-";
  const p = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" +
    p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds()) + s + p(off / 60) + ":" + p(off % 60);
}
async function signin() {
  try {
    const r = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({employee_no: $("no").value, password: $("pw").value})});
    const j = await r.json();
    if (!r.ok) { $("msg").textContent = j.error; return; }
    sessionStorage.setItem("qsbo", j.token);
    localStorage.setItem("qsbo_punch", j.token);
    $("signin").classList.add("hide"); $("main").classList.remove("hide");
    if (j.must_change) $("change").classList.remove("hide");
    load();
  } catch (e) { $("msg").textContent = "Can't reach the server."; }
}
async function load() {
  const stubs = await api("GET", "/api/stubs");
  $("stubs").innerHTML = "";
  for (const s of stubs) {
    const b = document.createElement("button");
    b.textContent = s.pay_date + "  net " + s.net;
    b.onclick = async () => { $("stub").textContent = JSON.stringify(await api("GET", "/api/stubs/" + s.id), null, 1); };
    $("stubs").appendChild(b);
  }
  const p = await api("GET", "/api/pto");
  $("pto").textContent = "Balance: " + p.balance + "  Requests: " + p.requests.length;
  const me = await api("GET", "/api/me");
  $("me").textContent = [me.name, me.address, me.phone, me.email, "SSN " + me.ssn].join(" | ");
}
function queue() { return JSON.parse(localStorage.getItem("qsbo_q") || "[]"); }
function saveQueue(q) { localStorage.setItem("qsbo_q", JSON.stringify(q));
  if ($("queue")) $("queue").textContent = q.length ? q.length + " punch(es) waiting to send" : "All punches sent"; }
async function flush() {
  const q = queue(); if (!q.length || !navigator.onLine) return saveQueue(q);
  try { await api("POST", "/api/punch", {punches: q}); saveQueue([]); }
  catch (e) { saveQueue(q); }
}
function punch(kind) {
  const rec = {id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())), kind,
    time: localIso(new Date()), job: $("job").value, cost_code: $("code").value,
    device: navigator.userAgent.slice(0, 80)};
  const done = () => { const q = queue(); q.push(rec); saveQueue(q); flush(); };
  const withPhoto = () => {
    const f = $("photo").files[0];
    if (!f) return done();
    const rd = new FileReader(); rd.onload = () => { rec.photo = rd.result; done(); }; rd.readAsDataURL(f);
  };
  if (navigator.geolocation) navigator.geolocation.getCurrentPosition((p) => {
    rec.lat = String(p.coords.latitude); rec.lon = String(p.coords.longitude);
    rec.accuracy = String(Math.round(p.coords.accuracy)); withPhoto(); }, withPhoto, {timeout: 15000});
  else withPhoto();
}
async function punchPage() {
  try {
    const jobs = await api("GET", "/api/jobs");
    localStorage.setItem("qsbo_jobs", JSON.stringify(jobs));
  } catch (e) { /* offline: use the saved list */ }
  const jobs = JSON.parse(localStorage.getItem("qsbo_jobs") || "[]");
  for (const j of jobs) { const o = document.createElement("option"); o.value = j.number; o.textContent = j.number + " " + j.name; $("job").appendChild(o); }
  const codes = () => { $("code").innerHTML = ""; const j = jobs.find((x) => x.number === $("job").value);
    for (const c of (j ? j.cost_codes : [])) { const o = document.createElement("option"); o.value = c; o.textContent = c; $("code").appendChild(o); } };
  $("job").onchange = codes; codes();
  $("in").onclick = () => punch("in"); $("out").onclick = () => punch("out");
  window.addEventListener("online", flush); saveQueue(queue()); flush();
}
if (document.body.dataset.page === "punch") punchPage();
else {
  $("go").onclick = signin;
  $("setpw").onclick = async () => { try { await api("POST", "/api/password", {old: $("pw").value, new: $("newpw").value}); $("change").classList.add("hide"); } catch (e) { alert(e.message); } };
  $("preq").onclick = async () => { try { await api("POST", "/api/pto", {date_from: $("pf").value, date_to: $("pt").value, hours_per_day: $("ph").value}); load(); } catch (e) { alert(e.message); } };
  $("msave").onclick = async () => { try { await api("POST", "/api/me", {field: $("mf").value, value: $("mv").value}); alert("Sent to HR"); } catch (e) { alert(e.message); } };
}
