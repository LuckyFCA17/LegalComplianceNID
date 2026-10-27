"use strict";

const CATS = ["K3", "Lingkungan", "Ketenagakerjaan", "Lainnya"];
const OBL = {
  terpenuhi: { label: "Terpenuhi", color: "var(--good)", icon: "✓" },
  proses: { label: "Dalam proses", color: "var(--warning)", icon: "↻" },
  belum: { label: "Belum", color: "var(--critical)", icon: "✕" },
  tidak_berlaku: { label: "Tidak berlaku", color: "var(--na)", icon: "–" },
};
const REL = {
  relevan: { label: "Relevan", color: "var(--good)" },
  pending: { label: "Belum dinilai", color: "var(--pending)" },
  tidak_relevan: { label: "Tidak relevan", color: "var(--na)" },
};

const state = { cats: loadCats(), tab: "dashboard", regs: [], selected: new Set(), me: null };
const canEdit = () => state.me && state.me.role !== "viewer";
const isAdmin = () => state.me && state.me.role === "admin";

/* Disable editing controls for viewers (the server enforces the same rules). */
function lock(root) {
  if (canEdit()) return;
  root.querySelectorAll("input:not([type=search]), select, textarea, button:not(.close)").forEach((el) => {
    if (!el.closest(".toolbar")) el.disabled = true;
  });
}

function loadCats() {
  try {
    const v = JSON.parse(localStorage.getItem("lcn.cats"));
    if (Array.isArray(v) && v.length) return v.filter((c) => CATS.includes(c));
  } catch (_) { /* storage unavailable */ }
  return ["K3", "Lingkungan", "Ketenagakerjaan"];
}
function saveCats() {
  try { localStorage.setItem("lcn.cats", JSON.stringify(state.cats)); } catch (_) { /* ignore */ }
}

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const catParam = () => "category=" + encodeURIComponent(state.cats.join(","));

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.body && !(opts.body instanceof FormData)) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("Sesi berakhir, silakan login kembali");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3500);
}

/* ---------------------------------------------------------------- tooltip */
const tip = $("#tooltip");
document.addEventListener("mouseover", (e) => {
  const el = e.target.closest("[data-tip]");
  if (!el) { tip.hidden = true; return; }
  tip.innerHTML = el.dataset.tip;
  tip.hidden = false;
});
document.addEventListener("mousemove", (e) => {
  if (tip.hidden) return;
  const x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px";
  tip.style.top = e.clientY + 14 + "px";
});

/* ---------------------------------------------------------------- category chips */
function renderChips() {
  $("#cat-chips").innerHTML = CATS.map((c) =>
    `<button class="chip" aria-pressed="${state.cats.includes(c)}" data-cat="${c}">${c}</button>`).join("");
}
$("#cat-chips").addEventListener("click", (e) => {
  const c = e.target.dataset.cat;
  if (!c) return;
  const on = state.cats.includes(c);
  if (on && state.cats.length === 1) return toast("Minimal satu kategori harus dipilih");
  state.cats = on ? state.cats.filter((x) => x !== c) : CATS.filter((x) => x === c || state.cats.includes(x));
  saveCats();
  renderChips();
  refresh();
});

/* ---------------------------------------------------------------- tabs */
document.querySelector(".tabs").addEventListener("click", (e) => {
  const t = e.target.dataset.tab;
  if (!t) return;
  state.tab = t;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + t));
  $(".catbar").hidden = t === "pengguna";
  refresh();
});

function refresh() {
  ({ dashboard: loadDashboard, regulasi: loadRegs, pemenuhan: loadObligations, sumber: loadSources,
     pengguna: loadUsers })[state.tab]();
}

/* ---------------------------------------------------------------- dashboard */
function stackedBar(parts, total) {
  if (!total) return `<div class="track"></div>`;
  return `<div class="track">${parts.filter((p) => p.n > 0).map((p) =>
    `<span class="seg" style="width:${(100 * p.n) / total}%;background:${p.color}"
      data-tip="<b>${esc(p.label)}</b><br>${p.n} dari ${total} (${Math.round((100 * p.n) / total)}%)"></span>`).join("")}</div>`;
}

async function loadDashboard() {
  const d = await api("/api/dashboard?" + catParam());
  const s = d.summary;
  const pct = s.compliance_pct;
  $("#stat-tiles").innerHTML = [
    tile("Tingkat pemenuhan", pct == null ? "—" : pct + "%",
      `${s.obligations.terpenuhi} dari ${s.obligation_total - s.obligations.tidak_berlaku} kewajiban berlaku`,
      pct == null ? null : pct),
    tile("Regulasi relevan", s.relevan, `dari ${s.regulations} regulasi terhimpun`),
    tile("Belum dinilai", s.pending, "menunggu penilaian relevansi"),
    tile("Kewajiban dalam proses", s.obligations.proses, `${s.obligations.belum} belum dimulai`),
    tile("Lewat tenggat", s.overdue, "kewajiban belum terpenuhi"),
  ].join("");

  $("#status-legend").innerHTML = Object.values(OBL).map((o) =>
    `<span><span class="sw" style="background:${o.color}"></span>${o.icon} ${o.label}</span>`).join("");
  $("#cat-chart").innerHTML = d.per_category.map((c) => {
    const parts = Object.entries(OBL).map(([k, o]) => ({ n: c.obligations[k], label: o.label, color: o.color }));
    return `<div class="hbar-row">
      <div class="name">${c.category}<small>${c.relevan} regulasi relevan</small></div>
      ${c.obligation_total ? stackedBar(parts, c.obligation_total) : `<div class="empty-track">Belum ada kewajiban</div>`}
      <div class="pct">${c.compliance_pct == null ? "—" : c.compliance_pct + "%"}</div></div>`;
  }).join("");
  $("#cat-table").innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Kategori</th>${
    Object.values(OBL).map((o) => `<th>${o.label}</th>`).join("")}<th>% Pemenuhan</th></tr></thead><tbody>${
    d.per_category.map((c) => `<tr><td>${c.category}</td>${Object.keys(OBL).map((k) =>
      `<td class="num">${c.obligations[k]}</td>`).join("")}<td class="num">${c.compliance_pct ?? "—"}</td></tr>`).join("")
  }</tbody></table></div>`;

  $("#relevance-chart").innerHTML = `<div class="legend">${Object.values(REL).map((r) =>
    `<span><span class="sw" style="background:${r.color}"></span>${r.label}</span>`).join("")}</div>` +
    d.per_category.map((c) => `<div class="hbar-row"><div class="name">${c.category}<small>${c.regulations} regulasi</small></div>
      ${stackedBar(Object.entries(REL).map(([k, r]) => ({ n: c[k], label: r.label, color: r.color })), c.regulations)}
      <div class="pct" title="Persentase regulasi yang sudah dinilai">${c.regulations ? Math.round((100 * (c.relevan + c.tidak_relevan)) / c.regulations) + "%" : "—"}</div></div>`).join("");

  $("#source-status").innerHTML = d.sources.map((src) => `<li><b>${esc(src.name)}</b>${src.enabled ? "" : " <span class='meta'>(nonaktif)</span>"}
    <div class="meta">${src.last_sync ? fmtDate(src.last_sync) + " — " + esc(src.last_status) : "Belum pernah disinkronkan"}</div></li>`).join("");

  listInto("#overdue", d.overdue, (o) => `<a data-reg="${o.regulation_id}">${esc(o.description)}</a>
    <div class="meta">${esc(o.citation)} · tenggat ${esc(o.due_date)}${o.pic ? " · " + esc(o.pic) : ""}</div>`, "Tidak ada kewajiban yang terlambat.");
  listInto("#review", d.review_needed, (r) => `<a data-reg="${r.id}">${esc(r.citation)}</a>
    <span class="badge ${r.status_berlaku}">${r.status_berlaku}</span><div class="meta">${esc(r.judul)}</div>`, "Tidak ada.");
  listInto("#no-obl", d.without_obligations, (r) => `<a data-reg="${r.id}">${esc(r.citation)}</a>
    <div class="meta">${esc(r.judul)}</div>`, "Semua regulasi relevan sudah memiliki kewajiban.");
}

function tile(label, value, hint, meter) {
  return `<div class="tile"><div class="label">${label}</div><div class="value">${value}</div>
    <div class="hint">${hint}</div>${meter == null ? "" : `<div class="meter"><span style="width:${meter}%"></span></div>`}</div>`;
}
function listInto(sel, items, fn, empty) {
  $(sel).innerHTML = items.length ? items.map((i) => `<li>${fn(i)}</li>`).join("") : `<li class="muted">${empty}</li>`;
}
function fmtDate(iso) {
  try { return new Date(iso).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" }); } catch (_) { return iso; }
}
$("#toggle-table").addEventListener("click", (e) => {
  const t = $("#cat-table");
  t.hidden = !t.hidden;
  e.target.textContent = t.hidden ? "Tampilkan tabel" : "Sembunyikan tabel";
});
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-reg]");
  if (a) openDrawer(+a.dataset.reg);
});

/* ---------------------------------------------------------------- regulations */
const REG_FILTERS = { q: "#reg-q", relevance: "#reg-relevance", compliance: "#reg-compliance",
  status: "#reg-status", sort: "#reg-sort" };
const COMPLIANCE = {
  terpenuhi: { label: "Terpenuhi", icon: "✓", cls: "good" },
  proses: { label: "Dalam proses", icon: "↻", cls: "warn" },
  belum: { label: "Belum dimulai", icon: "✕", cls: "crit" },
  tanpa_kewajiban: { label: "Belum ada kewajiban", icon: "–", cls: "na" },
  tidak_berlaku: { label: "Tidak berlaku", icon: "–", cls: "na" },
};
// Restore the last filters (per viewer, best effort).
try {
  const saved = JSON.parse(localStorage.getItem("lcn.regFilters") || "{}");
  Object.entries(REG_FILTERS).forEach(([k, sel]) => { if (saved[k] != null) $(sel).value = saved[k]; });
} catch (_) { /* storage unavailable */ }

let regTimer;
function scheduleRegs() { clearTimeout(regTimer); regTimer = setTimeout(loadRegs, 200); }
// Some mobile browsers only fire "change" (not "input") on <select>, so listen to both.
Object.values(REG_FILTERS).forEach((sel) => ["input", "change"].forEach((ev) => $(sel).addEventListener(ev, scheduleRegs)));
$("#reg-reset").addEventListener("click", () => {
  Object.values(REG_FILTERS).forEach((sel) => { $(sel).value = ""; });
  loadRegs();
});

function relCtl(r) {
  return `<span class="seg-ctl" data-id="${r.id}">${Object.entries({ relevan: "Relevan", tidak_relevan: "Tidak", pending: "?" })
    .map(([k, l]) => `<button class="${k}" data-rel="${k}" aria-pressed="${r.relevance === k}" title="${REL[k].label}">${l}</button>`).join("")}</span>`;
}
function complianceCell(r) {
  const c = COMPLIANCE[r.compliance_status];
  return `${progress(r.obl_done, r.obl_total, r.obl_na)}
    ${c ? `<span class="cstatus ${c.cls}">${c.icon} ${c.label}</span>` : ""}
    ${r.obl_overdue ? `<span class="cstatus crit">⚠ ${r.obl_overdue} lewat tenggat</span>` : ""}`;
}
function progress(done, total, na) {
  const appl = (total || 0) - (na || 0);
  if (!total) return `<span class="muted">—</span>`;
  const pct = appl ? Math.round((100 * (done || 0)) / appl) : 0;
  return `<div class="mini"><div class="meter"><span style="width:${pct}%"></span></div><span class="num">${done || 0}/${appl}</span></div>`;
}

let regSeq = 0;
async function loadRegs() {
  const filters = Object.fromEntries(Object.entries(REG_FILTERS).map(([k, sel]) => [k, $(sel).value]));
  try { localStorage.setItem("lcn.regFilters", JSON.stringify(filters)); } catch (_) { /* ignore */ }
  $("#reg-reset").hidden = !Object.values(filters).some(Boolean);
  const seq = ++regSeq;
  const regs = await api("/api/regulations?" + new URLSearchParams({ category: state.cats.join(","), ...filters }));
  if (seq !== regSeq) return;  // a newer filter request was sent meanwhile; ignore this stale answer
  state.regs = regs;
  state.selected.clear();
  $("#reg-table tbody").innerHTML = state.regs.map((r) => `<tr class="clickable" data-row="${r.id}">
      <td><input type="checkbox" data-sel="${r.id}" aria-label="Pilih"></td>
      <td><div class="cit">${esc(r.citation)}${r.pdf_url ? ` <a class="pdf-chip" href="${esc(r.pdf_url)}" target="_blank" rel="noopener" title="Buka PDF">PDF</a>`
        : r.url ? ` <a class="pdf-chip ghost" href="${esc(r.url)}" target="_blank" rel="noopener" title="Halaman peraturan">↗</a>` : ""}</div>
        <div class="judul">${esc(r.judul)}</div></td>
      <td><select data-cat-of="${r.id}">${CATS.map((c) => `<option ${c === r.category ? "selected" : ""}>${c}</option>`).join("")}</select></td>
      <td><span class="badge ${r.status_berlaku}">${r.status_berlaku}</span></td>
      <td>${relCtl(r)}</td>
      <td>${r.relevance === "relevan" ? complianceCell(r) : ""}</td></tr>`).join("") ||
    `<tr><td colspan="6" class="muted">Tidak ada regulasi untuk filter ini.</td></tr>`;
  $("#reg-count").textContent = `${state.regs.length} regulasi` +
    (filters.compliance ? " relevan (filter pemenuhan hanya berlaku untuk regulasi relevan)" : "");
  lock($("#reg-table"));
  $("#reg-all").checked = false;
  updateBulk();
}

$("#reg-table").addEventListener("click", async (e) => {
  const rel = e.target.closest("[data-rel]");
  if (rel) {
    e.stopPropagation();
    const id = +rel.parentElement.dataset.id;
    await api(`/api/regulations/${id}`, { method: "PATCH", body: { relevance: rel.dataset.rel } });
    toast(rel.dataset.rel === "relevan" ? "Ditandai relevan — kewajiban usulan ditambahkan bila tersedia" : "Relevansi diperbarui");
    return loadRegs();
  }
  if (e.target.closest("input,select,a,button")) return;
  const row = e.target.closest("[data-row]");
  if (row) openDrawer(+row.dataset.row);
});
$("#reg-table").addEventListener("change", async (e) => {
  if (e.target.dataset.sel) {
    e.target.checked ? state.selected.add(+e.target.dataset.sel) : state.selected.delete(+e.target.dataset.sel);
    return updateBulk();
  }
  if (e.target.dataset.catOf) {
    await api(`/api/regulations/${e.target.dataset.catOf}`, { method: "PATCH", body: { category: e.target.value } });
    toast("Kategori diperbarui");
  }
});
$("#reg-all").addEventListener("change", (e) => {
  document.querySelectorAll("[data-sel]").forEach((c) => {
    c.checked = e.target.checked;
    e.target.checked ? state.selected.add(+c.dataset.sel) : state.selected.delete(+c.dataset.sel);
  });
  updateBulk();
});
function updateBulk() {
  $("#bulkbar").hidden = state.selected.size === 0;
  $("#bulk-count").textContent = `${state.selected.size} dipilih`;
}
$("#bulkbar").addEventListener("click", async (e) => {
  const v = e.target.dataset.bulk;
  if (!v) return;
  await api("/api/regulations/bulk", { method: "POST", body: { ids: [...state.selected], relevance: v } });
  toast(`${state.selected.size} regulasi diperbarui`);
  loadRegs();
});

const dlg = $("#dlg-add");
$("#form-add [name=category]").innerHTML = CATS.map((c) => `<option>${c}</option>`).join("");
$("#btn-add-reg").addEventListener("click", () => dlg.showModal());
dlg.addEventListener("close", async () => {
  if (dlg.returnValue !== "ok") return;
  const body = Object.fromEntries(new FormData($("#form-add")));
  try {
    const r = await api("/api/regulations", { method: "POST", body });
    toast(r.result === "inserted" ? "Regulasi ditambahkan" : "Regulasi sudah ada — data diperbarui");
    $("#form-add").reset();
    loadRegs();
  } catch (err) { toast(err.message); }
});
$("#import-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const r = await api("/api/import", { method: "POST", body: fd });
    toast(`Impor: ${r.fetched} baris, ${r.inserted} baru, ${r.updated} diperbarui`);
    loadRegs();
  } catch (err) { toast(err.message); }
  e.target.value = "";
});

/* ---------------------------------------------------------------- drawer */
async function openDrawer(id) {
  const r = await api(`/api/regulations/${id}`);
  const body = $("#drawer-body");
  body.innerHTML = `<h2>${esc(r.citation)}</h2><p>${esc(r.judul)}</p>
    <dl class="kv">
      <dt>Status berlaku</dt><dd><select id="d-status">${["Berlaku", "Diubah", "Dicabut"].map((s) =>
        `<option ${s === r.status_berlaku ? "selected" : ""}>${s}</option>`).join("")}</select></dd>
      <dt>Kategori</dt><dd>${esc(r.category)}${r.category_locked ? " <span class='muted'>(manual)</span>" : ""}</dd>
      <dt>Relevansi</dt><dd>${relCtl(r)}</dd>
      <dt>Catatan</dt><dd><textarea id="d-note" rows="2" style="width:100%" placeholder="Alasan relevan / tidak relevan">${esc(r.relevance_note)}</textarea></dd>
      <dt>Sumber data</dt><dd>${esc(r.source_name || "-")}</dd>
    </dl>
    <div class="doclinks">
      <h3>Dokumen peraturan</h3>
      <div class="doc-actions">
        ${r.url ? `<a class="button secondary" href="${esc(r.url)}" target="_blank" rel="noopener">↗ Halaman peraturan</a>`
          : `<span class="muted">Belum tertaut ke halaman peraturan.</span>`}
        ${r.pdf_url ? `<a class="button" href="${esc(r.pdf_url)}" target="_blank" rel="noopener">📄 Buka PDF</a>` : ""}
        <a class="link" href="${esc(r.search_url)}" target="_blank" rel="noopener">Cari di JDIH BPK</a>
      </div>
      <div class="editor-only">
        <button id="d-fetch" class="secondary">${r.url ? "Perbarui detail &amp; PDF dari JDIH" : "Cari halaman &amp; PDF di JDIH"}</button>
        <details class="manual-links"><summary>Isi tautan manual</summary>
          <label>Tautan halaman peraturan <input id="d-url" type="url" value="${esc(r.url)}" placeholder="https://peraturan.bpk.go.id/Details/..."></label>
          <label>Tautan PDF <input id="d-pdf" type="url" value="${esc(r.pdf_url)}" placeholder="https://.../file.pdf"></label>
        </details>
      </div>
    </div>
    <div class="card-head"><h2>Aktivitas pemenuhan (${r.obligations.length})</h2><button id="d-add-obl" class="secondary">+ Kewajiban</button></div>
    <div id="d-obls">${r.obligations.map(oblForm).join("") || `<p class="muted">Belum ada kewajiban. ${
      r.relevance !== "relevan" ? "Tandai regulasi sebagai relevan untuk mulai melacak pemenuhan." : ""}</p>`}</div>`;
  $("#drawer").hidden = false;
  body.dataset.id = id;
  lock(body);
}
function oblForm(o) {
  return `<div class="obl" data-obl="${o.id}">
    <div class="row"><label>Pasal <input name="pasal" value="${esc(o.pasal)}"></label>
      <label>Status <select name="status">${Object.entries(OBL).map(([k, v]) =>
        `<option value="${k}" ${k === o.status ? "selected" : ""}>${v.icon} ${v.label}</option>`).join("")}</select></label></div>
    <label>Kewajiban / aktivitas pemenuhan <textarea name="description" rows="2">${esc(o.description)}</textarea></label>
    <div class="row"><label>PIC <input name="pic" value="${esc(o.pic)}"></label>
      <label>Tenggat <input name="due_date" type="date" value="${esc(o.due_date)}"></label></div>
    <label>Bukti pemenuhan (dokumen / tautan) <input name="evidence" value="${esc(o.evidence)}"></label>
    <label>Catatan <input name="notes" value="${esc(o.notes)}"></label>
    <div class="foot"><button class="danger" data-del="${o.id}">Hapus</button><span class="muted saved"></span></div></div>`;
}
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeDrawer(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(); });
function closeDrawer() { $("#drawer").hidden = true; refresh(); }

$("#drawer-body").addEventListener("click", async (e) => {
  const id = +$("#drawer-body").dataset.id;
  const rel = e.target.closest("[data-rel]");
  if (rel) {
    await api(`/api/regulations/${id}`, { method: "PATCH", body: { relevance: rel.dataset.rel, relevance_note: $("#d-note").value } });
    return openDrawer(id);
  }
  if (e.target.id === "d-fetch") {
    e.target.disabled = true;
    e.target.textContent = "Menghubungi JDIH…";
    try {
      const r = await api(`/api/regulations/${id}/detail`, { method: "POST" });
      toast(r.message);
    } catch (err) { toast(err.message); }
    return openDrawer(id);
  }
  if (e.target.id === "d-add-obl") {
    await api(`/api/regulations/${id}/obligations`, { method: "POST", body: { description: "Kewajiban baru" } });
    return openDrawer(id);
  }
  if (e.target.dataset.del && confirm("Hapus kewajiban ini?")) {
    await api(`/api/obligations/${e.target.dataset.del}`, { method: "DELETE" });
    openDrawer(id);
  }
});
$("#drawer-body").addEventListener("change", async (e) => {
  const id = +$("#drawer-body").dataset.id;
  try {
    if (e.target.id === "d-status") {
      await api(`/api/regulations/${id}`, { method: "PATCH", body: { status_berlaku: e.target.value } });
      return toast("Status berlaku diperbarui");
    }
    if (e.target.id === "d-url" || e.target.id === "d-pdf") {
      await api(`/api/regulations/${id}`, { method: "PATCH", body: { [e.target.id === "d-url" ? "url" : "pdf_url"]: e.target.value } });
      toast("Tautan disimpan");
      return openDrawer(id);
    }
    if (e.target.id === "d-note") {
      await api(`/api/regulations/${id}`, { method: "PATCH", body: { relevance_note: e.target.value } });
      return toast("Catatan disimpan");
    }
    const box = e.target.closest("[data-obl]");
    if (box && e.target.name) {
      await api(`/api/obligations/${box.dataset.obl}`, { method: "PATCH", body: { [e.target.name]: e.target.value } });
      $(".saved", box).textContent = "Tersimpan";
    }
  } catch (err) { toast(err.message); }
});

/* ---------------------------------------------------------------- obligations */
["input", "change"].forEach((ev) => $("#obl-status").addEventListener(ev, loadObligations));
let oblSeq = 0;
async function loadObligations() {
  $("#export-link").href = "/api/export.csv?" + catParam();
  const p = new URLSearchParams({ category: state.cats.join(","), status: $("#obl-status").value });
  const seq = ++oblSeq;
  const rows = await api("/api/obligations?" + p);
  if (seq !== oblSeq) return;
  $("#obl-table tbody").innerHTML = rows.map((o) => `<tr data-obl="${o.id}">
      <td><a data-reg="${o.regulation_id}" class="cit" style="cursor:pointer">${esc(o.citation)}</a><div class="judul">${esc(o.category)}${o.pasal ? " · " + esc(o.pasal) : ""}</div></td>
      <td>${esc(o.description)}</td>
      <td><input type="text" name="pic" value="${esc(o.pic)}" placeholder="PIC"></td>
      <td><input type="date" name="due_date" value="${esc(o.due_date)}"></td>
      <td><select name="status">${Object.entries(OBL).map(([k, v]) =>
        `<option value="${k}" ${k === o.status ? "selected" : ""}>${v.icon} ${v.label}</option>`).join("")}</select></td>
      <td><input type="text" name="evidence" value="${esc(o.evidence)}" placeholder="Bukti"></td></tr>`).join("") ||
    `<tr><td colspan="6" class="muted">Belum ada kewajiban. Tandai regulasi sebagai relevan di tab Regulasi.</td></tr>`;
  $("#obl-count").textContent = `${rows.length} kewajiban dari regulasi relevan`;
  lock($("#obl-table"));
}
$("#obl-table").addEventListener("change", async (e) => {
  const tr = e.target.closest("[data-obl]");
  if (!tr || !e.target.name) return;
  try {
    await api(`/api/obligations/${tr.dataset.obl}`, { method: "PATCH", body: { [e.target.name]: e.target.value } });
    toast("Tersimpan");
  } catch (err) { toast(err.message); }
});

/* ---------------------------------------------------------------- sources */
async function loadSources() {
  const [sources, log] = await Promise.all([api("/api/sources"), api("/api/sync/log")]);
  $("#sources").innerHTML = sources.filter((s) => !["manual", "import"].includes(s.kind)).map((s) => `
    <div class="card source" data-src="${s.id}">
      <div class="head"><h2>${esc(s.name)}</h2>
        <label style="margin:0"><input type="checkbox" name="enabled" ${s.enabled ? "checked" : ""}> Aktif</label></div>
      ${s.kind === "seed" ? `<p class="muted">Katalog awal regulasi kunci K3, lingkungan &amp; ketenagakerjaan beserta usulan kewajiban. Verifikasi status melalui JDIH.</p>` : `
      <label>URL dasar <input type="text" name="base_url" value="${esc(s.base_url)}"></label>
      <label>Konfigurasi (JSON) <textarea name="config" rows="3">${esc(JSON.stringify(s.config, null, 1))}</textarea></label>`}
      <div class="status">${s.last_sync ? fmtDate(s.last_sync) + " — " + esc(s.last_status) : "Belum pernah disinkronkan"}</div>
      <div class="actions">${s.kind === "seed" ? "" : `<button class="secondary" data-save="${s.id}">Simpan</button>`}
        ${s.kind === "seed" || s.kind === "jdihn" ? "" : `<button class="secondary" data-test="${s.id}">Tes koneksi</button>`}
        <button data-sync="${s.id}">Sinkronkan</button></div>
      <div class="test-result" hidden></div>
    </div>`).join("");
  if (!isAdmin()) {
    // Only admins may change source settings; editors may still run a sync.
    $("#sources").querySelectorAll("input, textarea, [data-save]").forEach((el) => (el.disabled = true));
  }
  if (!canEdit()) $("#sources").querySelectorAll("[data-sync], [data-test]").forEach((el) => (el.disabled = true));
  $("#sync-log tbody").innerHTML = log.map((l) => `<tr><td>${fmtDate(l.started_at)}</td><td>${esc(l.source_name)}</td>
    <td>${l.status === "ok" ? "✓ OK" : "✕ Gagal"}</td><td>${esc(l.message)}</td></tr>`).join("") ||
    `<tr><td colspan="4" class="muted">Belum ada riwayat.</td></tr>`;
}
async function doSync(btn, body) {
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "Menyinkronkan…";
  try {
    const res = await api("/api/sync", { method: "POST", body: { ...body, categories: state.cats } });
    toast(res.map((r) => `${r.source}: ${r.status === "ok" ? r.message : "gagal"}`).join(" · "));
  } catch (err) { toast(err.message); }
  btn.disabled = false;
  btn.textContent = old;
  loadSources();
}
$("#btn-sync-all").addEventListener("click", (e) => doSync(e.target, {}));
function renderTest(t) {
  const line = (ok, text) => `<li class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✕"} ${text}</li>`;
  let html = `<p class="muted">GET <a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.url)}</a></p><ul class="checks">`;
  if (t.error) {
    html += line(false, esc(t.error));
  } else {
    html += line(true, `Situs merespons (HTTP ${t.http_status}, ${Math.round(t.bytes / 1024)} KB, ${t.links} tautan)`);
    html += line(t.matching_links > 0, `${t.matching_links} tautan ke halaman peraturan`);
    html += line(t.found > 0, `${t.found} peraturan dikenali`);
    if (t.detail) {
      html += t.detail.error ? line(false, "Halaman peraturan: " + esc(t.detail.error))
        : line(!!t.detail.pdf_url, t.detail.pdf_url ? `PDF ditemukan: <a href="${esc(t.detail.pdf_url)}" target="_blank" rel="noopener">buka</a>`
          : "Halaman peraturan terbuka, tetapi tautan PDF tidak terdeteksi");
    }
  }
  (t.notes || []).forEach((n) => { html += `<li class="note">ℹ ${esc(n)}</li>`; });
  html += "</ul>";
  if (t.samples && t.samples.length) {
    html += `<ul class="plain">${t.samples.map((r) => `<li><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.citation)}</a>
      ${r.pdf_url ? `<a class="pdf-chip" href="${esc(r.pdf_url)}" target="_blank" rel="noopener">PDF</a>` : ""}
      <div class="meta">${esc(r.judul)} · ${esc(r.status)}</div></li>`).join("")}</ul>`;
  }
  return html;
}
$("#sources").addEventListener("click", async (e) => {
  if (e.target.dataset.sync) return doSync(e.target, { source_ids: [+e.target.dataset.sync] });
  if (e.target.dataset.test) {
    const card = e.target.closest("[data-src]");
    const box = $(".test-result", card);
    const keyword = prompt("Kata kunci uji:", "keselamatan kerja");
    if (keyword === null) return;
    e.target.disabled = true;
    box.hidden = false;
    box.innerHTML = `<p class="muted">Menghubungi situs…</p>`;
    try {
      box.innerHTML = renderTest(await api(`/api/sources/${e.target.dataset.test}/test`, { method: "POST", body: { keyword } }));
    } catch (err) { box.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    e.target.disabled = false;
    return;
  }
  if (e.target.dataset.save) {
    const card = e.target.closest("[data-src]");
    let config;
    try { config = JSON.parse($("[name=config]", card).value || "{}"); } catch (_) { return toast("Konfigurasi bukan JSON yang valid"); }
    try {
      await api(`/api/sources/${card.dataset.src}`, { method: "PATCH", body: { base_url: $("[name=base_url]", card).value, config } });
      toast("Sumber disimpan");
    } catch (err) { toast(err.message); }
  }
});
$("#sources").addEventListener("change", async (e) => {
  if (e.target.name !== "enabled") return;
  const card = e.target.closest("[data-src]");
  await api(`/api/sources/${card.dataset.src}`, { method: "PATCH", body: { enabled: e.target.checked } });
  toast(e.target.checked ? "Sumber diaktifkan" : "Sumber dinonaktifkan");
});

/* ---------------------------------------------------------------- users & account */
const ROLE_LABEL = { admin: "Admin", editor: "Editor", viewer: "Viewer" };
async function loadUsers() {
  const users = await api("/api/users");
  $("#user-table tbody").innerHTML = users.map((u) => `<tr data-user="${u.id}">
    <td>${esc(u.name)}</td><td>${esc(u.email)}</td>
    <td><select name="role" ${u.id === state.me.id ? "disabled" : ""}>${Object.entries(ROLE_LABEL).map(([k, l]) =>
      `<option value="${k}" ${k === u.role ? "selected" : ""}>${l}</option>`).join("")}</select></td>
    <td><input type="checkbox" name="active" ${u.active ? "checked" : ""} ${u.id === state.me.id ? "disabled" : ""} aria-label="Aktif"></td>
    <td>${u.last_login ? fmtDate(u.last_login) : "—"}</td>
    <td><button class="link" data-reset="${u.id}">Reset password</button></td></tr>`).join("");
}
$("#user-table").addEventListener("change", async (e) => {
  const tr = e.target.closest("[data-user]");
  if (!tr) return;
  const body = e.target.name === "active" ? { active: e.target.checked } : { role: e.target.value };
  try { await api(`/api/users/${tr.dataset.user}`, { method: "PATCH", body }); toast("Pengguna diperbarui"); }
  catch (err) { toast(err.message); loadUsers(); }
});
$("#user-table").addEventListener("click", async (e) => {
  const id = e.target.dataset.reset;
  if (!id) return;
  const pw = prompt("Password baru (min. 8 karakter):");
  if (!pw) return;
  try { await api(`/api/users/${id}`, { method: "PATCH", body: { password: pw } }); toast("Password direset"); }
  catch (err) { toast(err.message); }
});
$("#form-user").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/users", { method: "POST", body: Object.fromEntries(new FormData(e.target)) });
    e.target.reset();
    toast("Pengguna ditambahkan");
    loadUsers();
  } catch (err) { toast(err.message); }
});

const dlgPw = $("#dlg-password");
$("#btn-password").addEventListener("click", () => dlgPw.showModal());
dlgPw.addEventListener("close", async () => {
  if (dlgPw.returnValue !== "ok") return;
  try {
    await api("/api/auth/password", { method: "POST", body: Object.fromEntries(new FormData($("#form-password"))) });
    toast("Password diganti");
  } catch (err) { toast(err.message); }
  $("#form-password").reset();
});
$("#btn-logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.href = "/login";
});

(async () => {
  state.me = await api("/api/auth/me");
  document.body.dataset.role = state.me.role;
  $("#me-name").textContent = state.me.name;
  $("#me-role").textContent = ROLE_LABEL[state.me.role];
  document.querySelectorAll(".admin-only").forEach((el) => (el.hidden = !isAdmin()));
  renderChips();
  refresh();
})();
