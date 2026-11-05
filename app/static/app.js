"use strict";

// Categories are configured in the app (tab Pengaturan); filled from /api/meta at start-up.
let CATS = ["K3", "Lingkungan", "Ketenagakerjaan", "Lainnya"];
const FALLBACK_CAT = "Lainnya";
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
    const known = Array.isArray(v) ? v.filter((c) => CATS.includes(c)) : [];
    if (known.length) return known;
  } catch (_) { /* storage unavailable */ }
  return CATS.filter((c) => c !== FALLBACK_CAT);
}
async function reloadCategories() {
  const meta = await api("/api/meta");
  CATS = meta.categories;
  state.cats = loadCats();
  saveCats();
  renderChips();
  $("#form-add [name=category]").innerHTML = CATS.map((c) => `<option>${esc(c)}</option>`).join("");
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
    `<button class="chip" aria-pressed="${state.cats.includes(c)}" data-cat="${esc(c)}">${esc(c)}</button>`).join("");
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
  $(".catbar").hidden = t === "pengguna" || t === "pengaturan";
  refresh();
});

function refresh() {
  ({ dashboard: loadDashboard, regulasi: loadRegs, pemenuhan: loadObligations, sumber: loadSources,
     pengguna: loadUsers, pengaturan: loadSettings })[state.tab]();
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
  $("#reg-in-text").checked = saved.in_text === "1";
} catch (_) { /* storage unavailable */ }

let regTimer;
function scheduleRegs() { clearTimeout(regTimer); regTimer = setTimeout(loadRegs, 200); }
// Some mobile browsers only fire "change" (not "input") on <select>, so listen to both.
Object.values(REG_FILTERS).forEach((sel) => ["input", "change"].forEach((ev) => $(sel).addEventListener(ev, scheduleRegs)));
$("#reg-in-text").addEventListener("change", scheduleRegs);
$("#reg-reset").addEventListener("click", () => {
  Object.values(REG_FILTERS).forEach((sel) => { $(sel).value = ""; });
  $("#reg-in-text").checked = false;
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
  filters.in_text = $("#reg-in-text").checked ? "1" : "";
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
        <div class="judul">${esc(r.judul)}${r.has_text ? ` <span class="pdf-chip ghost" title="Teks peraturan tersedia untuk analisa">teks</span>` : ""}</div>
        ${r.text_snippet ? `<div class="snippet">${esc(r.text_snippet)}</div>` : ""}</td>
      <td><select data-cat-of="${r.id}">${CATS.map((c) => `<option ${c === r.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></td>
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
$("#form-add [name=category]").innerHTML = CATS.map((c) => `<option>${esc(c)}</option>`).join("");
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
    <div class="doclinks">
      <h3>Analisa isi peraturan</h3>
      <p class="muted" id="d-an-status">Memeriksa…</p>
      <button id="d-analyse" class="secondary">Buka analisa isi</button>
    </div>
    <div class="card-head"><h2>Aktivitas pemenuhan (${r.obligations.length})</h2><button id="d-add-obl" class="secondary">+ Kewajiban</button></div>
    <div id="d-obls">${r.obligations.map(oblForm).join("") || `<p class="muted">Belum ada kewajiban. ${
      r.relevance !== "relevan" ? "Tandai regulasi sebagai relevan untuk mulai melacak pemenuhan." : ""}</p>`}</div>`;
  $("#drawer").hidden = false;
  body.dataset.id = id;
  lock(body);
  $("#d-analyse").disabled = false;  // reading the analysis is open to every role
  api(`/api/regulations/${id}/analysis`).then((a) => {
    const st = $("#d-an-status");
    if (!st) return;
    st.textContent = !a.text ? "Teks peraturan belum diambil. Buka analisa untuk mengambil dari PDF resmi atau mengunggahnya."
      : a.ocr_job && a.ocr_job.active ? `OCR berjalan: halaman ${a.ocr_job.done_pages} dari ${a.ocr_job.total_pages || "…"}.`
      : a.text.needs_ocr ? `PDF hasil scan — ${a.text.needs_ocr} halaman perlu OCR. Buka analisa untuk menjalankannya.`
      : `${a.candidates.length} usulan persyaratan dari ${a.articles} pasal · ${a.candidates.filter((c) => c.added).length} sudah ditambahkan.`;
  }).catch(() => {});
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
  if (e.target.id === "d-analyse") return openAnalysis(id);
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
  const [sources, log, meta] = await Promise.all([api("/api/sources"), api("/api/sync/log"), api("/api/meta")]);
  state.sources = sources;
  const pi = $("#portable-info");
  pi.hidden = !meta.portable;
  if (meta.portable) {
    pi.innerHTML = `<h2>Mode portable — database bersama</h2>
      <p>Database: <code>${esc(meta.database)}</code></p>
      <ul class="checks">
        <li class="ok">✓ Hanya satu komputer yang bisa sinkronisasi dalam satu waktu (komputer lain diberi tahu siapa yang sedang sinkron).</li>
        <li class="ok">✓ Database dibackup otomatis ke folder <code>backups</code> sebelum setiap sinkronisasi (10 terakhir disimpan).</li>
        <li class="note">ℹ Sebaiknya sinkronisasi dijalankan oleh satu orang yang ditunjuk, di luar jam sibuk.</li>
      </ul>`;
  }
  $("#kw-list").innerHTML = state.cats.filter((c) => meta.search_keywords[c]).map((c) =>
    `<div class="kw-row"><b>${c}</b> ${meta.search_keywords[c].map((k) => `<span class="kw">${esc(k)}</span>`).join("")}</div>`)
    .join("") || `<p class="muted">Kategori terpilih tidak memiliki kata kunci pencarian.</p>`;
  $("#sources").innerHTML = sources.filter((s) => !["manual", "import"].includes(s.kind)).map((s) => `
    <div class="card source" data-src="${s.id}">
      <div class="head"><h2>${esc(s.name)}${s.code.startsWith("custom-") ? ` <small class="muted">(${s.kind === "jdihn" ? "feed JSON" : "situs JDIH"} tambahan)</small>` : ""}</h2>
        <label style="margin:0"><input type="checkbox" name="enabled" ${s.enabled ? "checked" : ""}> Aktif</label></div>
      ${s.kind === "seed" ? `<p class="muted">Katalog awal regulasi kunci K3, lingkungan &amp; ketenagakerjaan beserta usulan kewajiban. Verifikasi status melalui JDIH.</p>` : `
      <label>URL dasar <input type="text" name="base_url" value="${esc(s.base_url)}"></label>
      <label>Konfigurasi (JSON) <textarea name="config" rows="3">${esc(JSON.stringify(s.config, null, 1))}</textarea></label>`}
      <div class="status">${s.last_sync ? fmtDate(s.last_sync) + " — " + esc(s.last_status) : "Belum pernah disinkronkan"}</div>
      <div class="actions">${s.kind === "seed" ? "" : `<button class="secondary" data-save="${s.id}">Simpan</button>`}
        ${s.kind === "seed" ? "" : `<button class="secondary" data-test="${s.id}">Tes koneksi</button>`}
        <button data-sync="${s.id}">Sinkronkan</button>
        ${s.code.startsWith("custom-") ? `<button class="danger admin-only" data-del-src="${s.id}" ${isAdmin() ? "" : "hidden"}>Hapus</button>` : ""}</div>
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
  if (e.target.dataset.delSrc) {
    const src = state.sources.find((x) => String(x.id) === e.target.dataset.delSrc);
    if (!confirm(`Hapus sumber “${src.name}”? Peraturan yang sudah ditemukannya tetap tersimpan.`)) return;
    try {
      await api(`/api/sources/${src.id}`, { method: "DELETE" });
      toast("Sumber dihapus");
      loadSources();
    } catch (err) { toast(err.message); }
    return;
  }
  if (e.target.dataset.sync) return doSync(e.target, { source_ids: [+e.target.dataset.sync] });
  if (e.target.dataset.test) {
    const card = e.target.closest("[data-src]");
    const box = $(".test-result", card);
    const isFeed = state.sources.find((x) => String(x.id) === e.target.dataset.test)?.kind === "jdihn";
    const keyword = isFeed ? "" : prompt("Kata kunci uji:", "keselamatan kerja");
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

/* ---------------------------------------------------------------- offline legal analysis */
const AN_TYPES = { kewajiban: "Kewajiban", larangan: "Larangan", pelaporan: "Pelaporan", perizinan: "Perizinan / dokumen" };
const ORIGIN = { pdf_url: "PDF resmi", upload: "file unggahan", paste: "teks tempelan", ocr: "OCR dari PDF scan" };
const an = { id: null, data: null, types: new Set(Object.keys(AN_TYPES)), showGov: false, picked: new Map() };
const dlgAn = $("#dlg-analysis");

async function openAnalysis(id) {
  an.id = id;
  const r = await api(`/api/regulations/${id}`);
  $("#an-title").textContent = "Analisa isi · " + r.citation;
  $("#an-sub").textContent = r.judul;
  an.reg = r;
  if (!an.ocr) an.ocr = await api("/api/ocr/status").catch(() => ({ available: false, message: "" }));
  if (!dlgAn.open) dlgAn.showModal();
  await loadAnalysis();
}
let ocrPoll = null;
function watchOcr() {
  clearTimeout(ocrPoll);
  const job = an.data && an.data.ocr_job;
  if (!job || !job.active || !dlgAn.open) return;
  ocrPoll = setTimeout(async () => {
    try {
      const r = await api(`/api/regulations/${an.id}/ocr`);
      if (r.job && r.job.active) {
        an.data.ocr_job = r.job;
        const bar = $("#an-body .ocr-progress");
        if (bar) bar.outerHTML = ocrBox(an.data.text, r.job);
        return watchOcr();
      }
      await loadAnalysis();  // finished: show the OCR text's analysis
      if (r.job) toast(r.job.message || "OCR selesai");
    } catch (_) { watchOcr(); }
  }, 1500);
}
function ocrBox(t, job) {
  if (job && job.active) {
    const pct = job.total_pages ? Math.round((100 * job.done_pages) / job.total_pages) : 0;
    return `<div class="ocr-progress"><b>OCR berjalan</b> · halaman ${job.done_pages} dari ${job.total_pages || "…"}
      · oleh ${esc(job.holder || "")}${job.status === "cancelling" ? " · membatalkan…" : ""}
      <div class="meter"><span style="width:${pct}%"></span></div>
      <p class="muted">Aplikasi tetap bisa dipakai; hasilnya tersimpan untuk semua komputer.</p>
      <button class="secondary editor-only" data-an="ocr-cancel">Batalkan OCR</button></div>`;
  }
  let html = "";
  if (job && ["error", "cancelled"].includes(job.status)) html += `<p class="an-warn">⚠ ${esc(job.message)}</p>`;
  if (t && t.needs_ocr) {
    html += `<div class="ocr-need"><b>⚠ ${t.scanned ? "PDF hasil scan" : `${t.needs_ocr} halaman berupa gambar`}</b> —
      ${t.needs_ocr} dari ${t.pages} halaman tidak punya lapisan teks, jadi belum bisa dianalisa.
      ${an.ocr && an.ocr.available
        ? `<div class="an-actions"><button class="editor-only" data-an="ocr-start">Jalankan OCR (${t.needs_ocr} halaman)</button>
           <span class="muted">Perkiraan 2–6 detik per halaman, offline.</span></div>`
        : `<p class="muted">${esc((an.ocr && an.ocr.message) || "OCR tidak tersedia di komputer ini.")} Sebagai alternatif, tempel teks hasil OCR.</p>`}
      ${an.ocr && an.ocr.message && an.ocr.available ? `<p class="muted">${esc(an.ocr.message)}</p>` : ""}</div>`;
  }
  if (t && t.origin === "ocr") {
    html += `<p class="an-note">ℹ Teks ini hasil OCR (${t.ocr_pages} halaman)${t.edited ? " dan sudah disunting" : ""}.
      ${t.ocr_low_pages.length ? `<b>Periksa halaman ${t.ocr_low_pages.join(", ")}</b> — keyakinan OCR rendah. ` : ""}
      Bila nomor pasal atau kata penting salah baca, perbaiki lewat <b>Sunting teks</b>.</p>`;
  }
  return html;
}
async function loadAnalysis(data) {
  an.data = data || await api(`/api/regulations/${an.id}/analysis`);
  an.picked = new Map();
  (an.data.candidates || []).forEach((c, i) => {
    if (c.suggested && !c.added && canEdit()) an.picked.set(i, c.description);
  });
  renderAnalysis();
}
function sourceBar(a) {
  const t = a.text;
  const editBtns = `
    ${an.reg.pdf_url ? `<button class="secondary editor-only" data-an="fetch">Ambil dari PDF resmi</button>` : ""}
    <button class="secondary editor-only" data-an="upload">Unggah PDF / teks</button>
    <button class="secondary editor-only" data-an="paste">Tempel teks</button>`;
  return `<div class="an-source">
    <div>${t ? `<b>Teks:</b> ${ORIGIN[t.origin] || t.origin}${t.filename ? ` (${esc(decodeURIComponent(t.filename))})` : ""}
      · ${t.pages ? t.pages + " halaman · " : ""}${Math.round(t.chars / 1000)} rb karakter · ${fmtDate(t.fetched_at)}${t.fetched_by ? " oleh " + esc(t.fetched_by) : ""}`
      : `<b>Teks peraturan belum diambil.</b> Ambil dari PDF resmi, atau unggah/tempel bila situs JDIH tidak dapat diakses.`}</div>
    <div class="an-actions">${editBtns}
      ${t ? `<button class="link" data-an="view">Lihat teks lengkap</button>
        <button class="secondary editor-only" data-an="edit">Sunting teks</button>
        <button class="danger editor-only" data-an="delete">Hapus teks</button>` : ""}</div>
    <div class="an-paste" hidden><textarea rows="8" placeholder="Tempel teks lengkap peraturan di sini (mis. hasil salin dari PDF)…"></textarea>
      <div class="an-actions"><button data-an="paste-save">Simpan &amp; analisa</button><button class="secondary" data-an="paste-cancel">Batal</button></div></div>
    <div class="an-edit" hidden><p class="muted">Perbaiki teks (mis. salah baca OCR). Pertahankan baris “Pasal N” dan penanda ayat “(1)” di awal baris.</p>
      <textarea rows="16"></textarea>
      <div class="an-actions"><button data-an="edit-save">Simpan &amp; analisa ulang</button><button class="secondary" data-an="edit-cancel">Batal</button></div></div>
  </div>${ocrBox(t, a.ocr_job)}`;
}
function renderAnalysis() {
  const a = an.data;
  const body = $("#an-body");
  let html = sourceBar(a);
  if (a.text && !(a.text.scanned && a.text.needs_ocr)) {
    const list = a.candidates.map((c, i) => [c, i]).filter(([c]) => an.types.has(c.type) && (an.showGov || c.party !== "pemerintah"));
    html += `<p class="an-note">ℹ Usulan dibuat otomatis dari pola bahasa peraturan (<i>wajib, dilarang, paling lambat,
      dikenai sanksi</i> …). Periksa setiap usulan terhadap teks resmi sebelum ditambahkan; ini bukan nasihat hukum.</p>
      <div class="an-filters">${Object.entries(AN_TYPES).map(([k, l]) =>
        `<button class="chip" aria-pressed="${an.types.has(k)}" data-an-type="${k}">${l} <b>${a.counts[k] || 0}</b></button>`).join("")}
        <label class="check"><input type="checkbox" id="an-gov" ${an.showGov ? "checked" : ""}> Tampilkan kewajiban pemerintah/instansi</label>
        <span class="muted">${a.articles} pasal dibaca</span></div>
      <div class="an-list">${list.map(([c, i]) => `
        <div class="an-item ${c.added ? "added" : ""}" data-i="${i}">
          <input type="checkbox" class="an-pick" aria-label="Pilih" ${an.picked.has(i) ? "checked" : ""} ${c.added || !canEdit() ? "disabled" : ""}>
          <div class="an-main">
            <div class="an-tags"><b>${esc(c.pasal)}</b>
              <span class="tag t-${c.type}">${esc(c.type_label)}</span>
              <span class="tag">${esc(c.party_label)}</span>
              <span class="tag conf-${c.confidence}">keyakinan ${c.confidence}</span>
              ${c.timing ? `<span class="tag">⏱ ${esc(c.timing)}</span>` : ""}
              ${c.sanction.length ? `<span class="tag t-larangan">ada sanksi: ${esc(c.sanction.join(", "))}</span>` : ""}
              ${c.added ? `<span class="tag t-ok">✓ sudah di kewajiban</span>` : ""}</div>
            <input class="an-desc" value="${esc(an.picked.get(i) ?? c.description)}" ${c.added || !canEdit() ? "disabled" : ""} aria-label="Deskripsi kewajiban">
            <details><summary>Kutipan pasal</summary><p class="quote">${esc(c.quote)}</p>
              ${c.context ? `<p class="quote ctx"><b>${esc(c.article)} lengkap:</b> ${esc(c.context)}</p>` : ""}</details>
          </div>
        </div>`).join("") || `<p class="muted">Tidak ada usulan untuk filter ini.</p>`}</div>
      ${a.sanctions.length ? `<details class="an-sanctions"><summary>Ketentuan sanksi (${a.sanctions.length})</summary>${a.sanctions.map((x) =>
        `<p><b>${esc(x.pasal)}</b>${x.refers_to.length ? ` → ${esc(x.refers_to.join(", "))}` : ""}: ${esc(x.text)}</p>`).join("")}</details>` : ""}`;
  }
  body.innerHTML = html;
  $("#an-foot").hidden = !a.text || !canEdit() || (a.text.scanned && a.text.needs_ocr);
  updateAnCount();
  if (!canEdit()) body.querySelectorAll(".editor-only").forEach((el) => (el.hidden = true));
  watchOcr();
}
function updateAnCount() {
  $("#an-count").textContent = `${an.picked.size} usulan dipilih`;
  $("#an-apply").disabled = an.picked.size === 0;
}
async function anCall(btn, fn) {
  const old = btn && btn.textContent;
  if (btn) { btn.disabled = true; btn.textContent = "Memproses…"; }
  try { await loadAnalysis(await fn()); } catch (err) { toast(err.message); if (btn) { btn.disabled = false; btn.textContent = old; } }
}
$("#an-body").addEventListener("click", async (e) => {
  const act = e.target.dataset.an;
  const type = e.target.closest("[data-an-type]");
  if (type) {
    const k = type.dataset.anType;
    an.types.has(k) ? an.types.delete(k) : an.types.add(k);
    return renderAnalysis();
  }
  if (!act) return;
  const box = $(".an-paste", $("#an-body"));
  if (act === "fetch") return anCall(e.target, () => api(`/api/regulations/${an.id}/text/fetch`, { method: "POST" }));
  if (act === "upload") return $("#an-file").click();
  if (act === "paste") { box.hidden = false; return $("textarea", box).focus(); }
  if (act === "paste-cancel") { box.hidden = true; return; }
  if (act === "ocr-start") {
    e.target.disabled = true;
    try {
      const r = await api(`/api/regulations/${an.id}/ocr`, { method: "POST" });
      an.data.ocr_job = r.job;
      renderAnalysis();
    } catch (err) { toast(err.message); e.target.disabled = false; }
    return;
  }
  if (act === "ocr-cancel") {
    const r = await api(`/api/regulations/${an.id}/ocr/cancel`, { method: "POST" });
    an.data.ocr_job = r.job;
    return renderAnalysis();
  }
  const edit = $(".an-edit", $("#an-body"));
  if (act === "edit") {
    const t = await api(`/api/regulations/${an.id}/text`);
    $("textarea", edit).value = t.content;
    edit.hidden = false;
    return $("textarea", edit).focus();
  }
  if (act === "edit-cancel") { edit.hidden = true; return; }
  if (act === "edit-save") {
    const text = $("textarea", edit).value;
    return anCall(e.target, () => api(`/api/regulations/${an.id}/text`, { method: "PATCH", body: { text } }));
  }
  if (act === "paste-save") {
    const text = $("textarea", box).value;
    return anCall(e.target, () => api(`/api/regulations/${an.id}/text`, { method: "POST", body: { text } }));
  }
  if (act === "view") {
    const t = await api(`/api/regulations/${an.id}/text`);
    const w = window.open("", "_blank");
    if (w) { w.document.title = an.reg.citation; const pre = w.document.createElement("pre");
      pre.style.cssText = "white-space:pre-wrap;font:14px/1.5 system-ui;padding:24px;max-width:900px"; pre.textContent = t.content;
      w.document.body.appendChild(pre); }
    return;
  }
  if (act === "delete" && confirm("Hapus teks peraturan yang tersimpan? Kewajiban yang sudah ditambahkan tidak terhapus.")) {
    await api(`/api/regulations/${an.id}/text`, { method: "DELETE" });
    return loadAnalysis();
  }
});
$("#an-body").addEventListener("change", (e) => {
  if (e.target.id === "an-gov") { an.showGov = e.target.checked; return renderAnalysis(); }
  const item = e.target.closest("[data-i]");
  if (!item) return;
  const i = +item.dataset.i;
  if (e.target.classList.contains("an-pick")) {
    e.target.checked ? an.picked.set(i, $(".an-desc", item).value) : an.picked.delete(i);
    updateAnCount();
  }
});
$("#an-body").addEventListener("input", (e) => {
  const item = e.target.closest("[data-i]");
  if (item && e.target.classList.contains("an-desc") && an.picked.has(+item.dataset.i)) an.picked.set(+item.dataset.i, e.target.value);
});
$("#an-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  toast("Membaca file…");
  await anCall(null, () => api(`/api/regulations/${an.id}/text/upload`, { method: "POST", body: fd }));
  e.target.value = "";
});
$("#an-apply").addEventListener("click", async () => {
  const items = [...an.picked.entries()].map(([i, description]) => {
    const c = an.data.candidates[i];
    const notes = [c.timing && `Waktu: ${c.timing}`, c.sanction.length && `Sanksi: ${c.sanction.join(", ")}`,
      "Dari analisa isi otomatis"].filter(Boolean).join(" · ");
    return { pasal: c.pasal, description, notes };
  });
  try {
    const r = await api(`/api/regulations/${an.id}/analysis/apply`, { method: "POST", body: { items } });
    toast(`${r.added} kewajiban ditambahkan${r.skipped ? `, ${r.skipped} dilewati (pasal sudah ada)` : ""}`);
    await loadAnalysis();
  } catch (err) { toast(err.message); }
});
function closeAnalysis() { clearTimeout(ocrPoll); dlgAn.close(); if (!$("#drawer").hidden && an.id) openDrawer(an.id); }
$("#an-close").addEventListener("click", closeAnalysis);
dlgAn.addEventListener("cancel", (e) => { e.preventDefault(); closeAnalysis(); });

/* ---------------------------------------------------------------- add a sync source */
const dlgSrc = $("#dlg-source");
const formSrc = $("#form-source");
function showKindFields() {
  const kind = formSrc.kind.value;
  formSrc.querySelectorAll("[data-kind]").forEach((el) => (el.hidden = el.dataset.kind !== kind));
}
formSrc.kind.addEventListener("change", showKindFields);
$("#btn-add-source").addEventListener("click", () => {
  formSrc.reset();
  showKindFields();
  $("#source-error").textContent = "";
  dlgSrc.showModal();
});
formSrc.addEventListener("submit", async (e) => {
  if (e.submitter && e.submitter.value === "cancel") return;  // let the dialog close
  e.preventDefault();
  const f = Object.fromEntries(new FormData(formSrc));
  const body = { kind: f.kind, name: f.name, base_url: f.base_url, config: {} };
  if (f.kind === "html") {
    Object.assign(body.config, { search_url: f.search_url.trim(), link_pattern: f.link_pattern.trim(),
      max_pages: f.max_pages || 2 });
    if (f.pdf_pattern.trim()) body.config.pdf_pattern = f.pdf_pattern.trim();
  } else {
    body.config.feed_url = f.feed_url.trim();
  }
  try {
    await api("/api/sources", { method: "POST", body });
    dlgSrc.close();
    toast("Sumber ditambahkan — tekan Tes koneksi untuk mencobanya");
    loadSources();
  } catch (err) { $("#source-error").textContent = err.message; }
});

/* ---------------------------------------------------------------- settings: categories & keywords */
const kwText = (list) => (list || []).join("\n");
async function loadSettings() {
  const cats = await api("/api/categories");
  $("#cat-list").innerHTML = cats.map((c) => `
    <div class="card cat-card" data-cat-id="${c.id}">
      <div class="head">
        <input name="name" value="${esc(c.name)}" maxlength="40" aria-label="Nama kategori" ${c.fallback ? "disabled" : ""}>
        <span class="muted">${c.regulations} peraturan</span>
      </div>
      <label>Kata kunci pencarian di JDIH
        <textarea name="search_keywords" rows="6">${esc(kwText(c.search_keywords))}</textarea></label>
      ${c.fallback ? `<p class="muted">Peraturan yang tidak cocok dengan kategori lain otomatis masuk ke sini; kategori ini tidak dapat dihapus atau diganti nama.</p>`
        : `<label>Kata kunci pengenal judul
        <textarea name="title_keywords" rows="6">${esc(kwText(c.title_keywords))}</textarea></label>`}
      <div class="actions">
        ${c.fallback ? "" : `<button class="danger" data-cat-del="${c.id}">Hapus</button>`}
        <span class="spacer"></span><span class="muted saved"></span>
        <button data-cat-save="${c.id}">Simpan</button>
      </div>
    </div>`).join("");
  $("#reclass-result").innerHTML = "";
  $("#btn-reclass-apply").hidden = true;
}
$("#cat-list").addEventListener("click", async (e) => {
  const card = e.target.closest("[data-cat-id]");
  if (!card) return;
  const id = card.dataset.catId;
  if (e.target.dataset.catSave) {
    const body = { search_keywords: card.querySelector("[name=search_keywords]").value };
    const name = card.querySelector("[name=name]");
    if (!name.disabled) body.name = name.value;
    const title = card.querySelector("[name=title_keywords]");
    if (title) body.title_keywords = title.value;
    try {
      await api(`/api/categories/${id}`, { method: "PATCH", body });
      $(".saved", card).textContent = "Tersimpan";
      await reloadCategories();
      if (title) toast("Kata kunci disimpan. Gunakan “Pratinjau perubahan” untuk menerapkannya ke peraturan yang ada.");
    } catch (err) { toast(err.message); }
  }
  if (e.target.dataset.catDel) {
    const name = card.querySelector("[name=name]").value;
    if (!confirm(`Hapus kategori “${name}”? Peraturannya dipindah ke “${FALLBACK_CAT}”; penilaian dan kewajiban tetap.`)) return;
    try {
      const r = await api(`/api/categories/${id}`, { method: "DELETE" });
      toast(`Kategori dihapus; ${r.moved_to_fallback} peraturan dipindah ke ${FALLBACK_CAT}`);
      await reloadCategories();
      loadSettings();
    } catch (err) { toast(err.message); }
  }
});
$("#form-cat").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const c = await api("/api/categories", { method: "POST", body: Object.fromEntries(new FormData(e.target)) });
    e.target.reset();
    toast(`Kategori “${c.name}” ditambahkan`);
    await reloadCategories();
    loadSettings();
  } catch (err) { toast(err.message); }
});
async function reclassify(dryRun) {
  const r = await api("/api/categories/reclassify", { method: "POST", body: { dry_run: dryRun } });
  const rows = Object.entries(r.changes).map(([k, n]) => `<li>${esc(k)}: <b>${n}</b> peraturan</li>`).join("");
  $("#reclass-result").innerHTML = r.moved
    ? `<p>${dryRun ? "Akan dipindah" : "Dipindah"}: <b>${r.moved}</b> peraturan</p><ul class="plain">${rows}</ul>`
    : `<p class="muted">Tidak ada peraturan yang perlu dipindah.</p>`;
  $("#btn-reclass-apply").hidden = !(dryRun && r.moved);
  if (!dryRun) loadSettings().then(() => { $("#reclass-result").innerHTML = `<p>✓ ${r.moved} peraturan dipindah.</p>`; });
}
$("#btn-reclass-preview").addEventListener("click", () => reclassify(true).catch((err) => toast(err.message)));
$("#btn-reclass-apply").addEventListener("click", () => reclassify(false).catch((err) => toast(err.message)));

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
  await reloadCategories();
  refresh();
})();
