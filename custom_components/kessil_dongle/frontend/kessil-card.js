/*
 * Kessil card – bundled with the kessil_dongle integration.
 *
 *   type: custom:kessil-card
 *   entity: light.default_ts      # the group's light entity
 *   name: Aquarium                # optional
 *
 * Intensity, color temperature, red, amber and mode entities are found automatically
 * on the same device (via their translation keys).
 *
 * The pencil button opens the program list: rename, duplicate and delete
 * programs, download a backup and import programs from a JSON file. It uses the
 * integration's actions (export_programs, save_program, rename_program,
 * delete_program); presets are read-only.
 */

const DOMAIN = "kessil_dongle";
const CARD_VERSION = "0.2.1";

const CHANNELS = [
  { key: "intensity", label: { de: "Intensität", en: "Intensity" }, track: "linear-gradient(90deg,#16202c,#4fc3f7)", index: 0 },
  { key: "color", label: { de: "Farbtemperatur", en: "Color temperature" }, track: "linear-gradient(90deg,#ffd98a,#ffffff,#d9d4ff)", index: 1, kelvin: true },
  { key: "spectrum", label: { de: "Spektrum", en: "Spectrum" }, track: "linear-gradient(90deg,#9e9e9e,#ffffff)", index: 1 },
  { key: "red", label: { de: "Rot", en: "Red" }, track: "linear-gradient(90deg,#3a1414,#e53935)", index: 3 },
  { key: "amber", label: { de: "Amber", en: "Amber" }, track: "linear-gradient(90deg,#3a2410,#f5761a)", index: 4 },
];

// Color temperature range per lamp type (groups on the dongle are per type).
// Tuna Sun: 6000-9000 K for all Tuna Sun models per manufacturer specs.
// Tuna Blue is left out on purpose: specs disagree and its channel mapping on
// the dongle is unverified.
const KELVIN_RANGES = {
  "Tuna Sun": [6000, 9000],
};

const pct = (raw) => Math.round((raw * 100) / 255);
const MAX_POINTS = 20;
const MAX_NAME_BYTES = 31;
const nameBytes = (name) => new TextEncoder().encode(name.trim()).length;
/** Program points (dongle format) -> compact curve points [min, ...ui, eid]. */
const compact = (points) => points.map((p) => [p.minutes, ...p.UI, p.eid ?? p.EID ?? -1]);

/** Linear interpolation over a 24 h circular schedule. points: [[min, ...ui]] */
function valueAt(points, minute, idx) {
  if (!points || points.length === 0) return 0;
  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  for (let i = 0; i < sorted.length; i++) {
    const cur = sorted[i];
    const next = sorted[(i + 1) % sorted.length];
    const start = cur[0];
    let end = next[0];
    let m = minute;
    if (end <= start) {
      end += 1440;
      if (m < start) m += 1440;
    }
    if (m >= start && m < end) {
      const t = end === start ? 0 : (m - start) / (end - start);
      return cur[idx] + (next[idx] - cur[idx]) * t;
    }
  }
  return sorted[0][idx];
}

class KessilCard extends HTMLElement {
  static getStubConfig(hass) {
    const light = Object.values(hass.entities || {}).find(
      (e) => e.platform === DOMAIN && e.entity_id.startsWith("light.")
    );
    return { entity: light ? light.entity_id : "" };
  }

  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("light.")) {
      throw new Error("kessil-card: 'entity' must be the light entity of a Kessil group");
    }
    this._config = config;
    this._signature = null;
    if (this._hass) this._render();
  }

  getCardSize() {
    return 7;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const sig = this._computeSignature();
    if (sig === this._signature || this._dragging || this._editing()) return;
    this._signature = sig;
    this._render();
  }

  /** True while the user types in the program panel (don't re-render then). */
  _editing() {
    const el = this.shadowRoot?.activeElement;
    return !!el && el.tagName === "INPUT" && el.type === "text";
  }

  // ---- entity lookup ------------------------------------------------------

  _lang() {
    return (this._hass.locale?.language || this._hass.language || "en").startsWith("de") ? "de" : "en";
  }

  _related() {
    const ents = this._hass.entities || {};
    const own = ents[this._config.entity];
    const out = {};
    if (!own || !own.device_id) return out;
    for (const e of Object.values(ents)) {
      if (e.device_id === own.device_id && e.platform === DOMAIN && e.translation_key) {
        out[e.translation_key] = e.entity_id;
      }
    }
    return out;
  }

  _computeSignature() {
    const ids = [this._config.entity, ...Object.values(this._related())];
    const minute = Math.floor(Date.now() / 300000); // re-render every 5 min for the "now" marker
    return JSON.stringify([
      minute,
      this._lang(),
      ids.map((id) => {
        const s = this._hass.states[id];
        return s ? [s.state, s.attributes.brightness, s.attributes.programs ? Object.keys(s.attributes.programs) : 0] : null;
      }),
    ]);
  }

  // ---- service calls -------------------------------------------------------

  _setNumber(entityId, value) {
    this._hass.callService("number", "set_value", { entity_id: entityId, value });
  }

  _selectMode(entityId, option) {
    this._hass.callService("select", "select_option", { entity_id: entityId, option });
  }

  async _action(service, data = {}, withResponse = false) {
    const msg = {
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: { entity_id: this._config.entity, ...data },
    };
    if (withResponse) msg.return_response = true;
    const result = await this._hass.callWS(msg);
    return result?.response;
  }

  // ---- program panel -------------------------------------------------------

  async _openPrograms() {
    this._pm = { open: true, list: null, edit: null, message: null, imports: null };
    this._render();
    await this._loadPrograms();
  }

  async _loadPrograms() {
    try {
      this._pm.list = await this._action("export_programs", {}, true);
    } catch (err) {
      this._pm.message = { error: true, text: err.message || String(err) };
    }
    this._render();
  }

  /** Run a writing action, then reload the list; show the result. */
  async _write(service, data, success) {
    this._pm.busy = true;
    this._render();
    try {
      await this._action(service, data);
      this._pm.edit = null;
      this._pm.imports = null;
      this._pm.message = { error: false, text: success };
      this._pm.list = await this._action("export_programs", {}, true);
    } catch (err) {
      this._pm.message = { error: true, text: err.message || String(err) };
    }
    this._pm.busy = false;
    this._render();
  }

  _download() {
    const data = this._pm.list;
    const date = new Date().toISOString().slice(0, 10);
    const type = (data.lamp_type || "programs").toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const blob = new Blob([JSON.stringify(data, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `kessil-${type}-${date}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /** Accept a single program ({name, points}) or a backup ({programs: [...]}). */
  async _readImport(file, t) {
    try {
      const data = JSON.parse(await file.text());
      const list = Array.isArray(data.programs) ? data.programs : [data];
      const programs = list.filter((p) => p && Array.isArray(p.points) && p.points.length);
      if (!programs.length) throw new Error(t("Keine Programme in der Datei", "No programs in this file"));
      this._pm.imports = programs.map((p) => ({ name: String(p.name || file.name.replace(/\.json$/i, "")), points: p.points }));
      this._pm.edit = programs.length === 1 ? { kind: "import", index: 0, name: this._pm.imports[0].name } : null;
      this._focused = false;
      this._pm.message = null;
    } catch (err) {
      this._pm.message = { error: true, text: `${t("Datei nicht lesbar", "Cannot read file")}: ${err.message}` };
    }
    this._render();
  }

  /** Validate a program name for the current edit; also used while typing. */
  _nameCheck(value, t) {
    const pm = this._pm;
    const programs = pm.list?.programs || [];
    const name = value.trim();
    const bytes = nameBytes(value);
    const same = programs.find((p) => p.name === name);
    const own = pm.edit?.kind === "rename" ? programs[pm.edit.index]?.name : null;
    let err = "";
    if (!name) err = t("Name fehlt", "Name missing");
    else if (bytes > MAX_NAME_BYTES)
      err = t(`Name zu lang (${bytes}/${MAX_NAME_BYTES} Bytes)`, `Name too long (${bytes}/${MAX_NAME_BYTES} bytes)`);
    else if (same?.preset) err = t("Name einer Voreinstellung", "Name of a preset");
    else if (same && pm.edit?.kind === "rename" && name !== own) err = t("Name schon vergeben", "Name already in use");
    else if (pm.edit?.kind === "import" && pm.imports[pm.edit.index].points.length > MAX_POINTS)
      err = t(`Höchstens ${MAX_POINTS} Punkte`, `At most ${MAX_POINTS} points`);
    const note = !err && same && name !== own ? t("Überschreibt das vorhandene Programm", "Overwrites the existing program") : "";
    return { err, note };
  }

  _programPanel(t, runningPid) {
    const pm = this._pm;
    const list = pm.list?.programs;
    const lock = `<span class="lock" title="${t("Voreinstellung – nicht änderbar", "Preset – read-only")}">${LOCK_ICON}</span>`;
    const programs = list || [];
    const nameField = (value) => {
      const check = this._nameCheck(value, t);
      return {
        ok: !check.err,
        html: `<input type="text" class="name" value="${escapeHtml(value)}" maxlength="64">
               <div class="hint name-hint ${check.err ? "err" : ""}">${check.err || check.note}</div>`,
      };
    };
    const editRow = (title, field, saveLabel, extra = "") => `
      <div class="edit">
        <div class="edit-title">${title}</div>
        ${field.html}
        ${extra}
        <div class="buttons">
          <button class="btn" data-pm="cancel">${t("Abbrechen", "Cancel")}</button>
          <button class="btn primary" data-pm="save" ${field.ok && !pm.busy ? "" : "disabled"}>${saveLabel}</button>
        </div>
      </div>`;

    const rows = programs
      .map((p, i) => {
        const running = p.pid === runningPid;
        const e = pm.edit;
        if (e && e.index === i && e.kind === "rename") {
          return editRow(t("Umbenennen", "Rename"), nameField(e.name), t("Speichern", "Save"));
        }
        if (e && e.index === i && e.kind === "copy") {
          return editRow(
            t(`„${escapeHtml(p.name)}“ duplizieren`, `Duplicate "${escapeHtml(p.name)}"`),
            nameField(e.name),
            t("Duplizieren", "Duplicate")
          );
        }
        if (e && e.index === i && e.kind === "delete") {
          return `
            <div class="edit danger">
              <div class="edit-title">${t(`„${escapeHtml(p.name)}“ aus dem Dongle löschen?`, `Delete "${escapeHtml(p.name)}" from the dongle?`)}</div>
              <div class="buttons">
                <button class="btn" data-pm="cancel">${t("Abbrechen", "Cancel")}</button>
                <button class="btn danger" data-pm="save" ${pm.busy ? "disabled" : ""}>${t("Löschen", "Delete")}</button>
              </div>
            </div>`;
        }
        const del = running
          ? `<button class="icon" disabled title="${t("Läuft gerade – erst anderen Modus wählen", "Running – choose another mode first")}">${TRASH_ICON}</button>`
          : `<button class="icon" data-pm="delete" data-i="${i}" title="${t("Löschen", "Delete")}">${TRASH_ICON}</button>`;
        return `
          <div class="row">
            <div class="row-name">${p.preset ? lock : ""}<span>${escapeHtml(p.name)}</span>
              ${running ? `<span class="tag">${t("läuft", "running")}</span>` : ""}</div>
            <div class="row-meta">${p.points.length} ${t("Punkte", "points")}</div>
            <div class="row-actions">
              ${p.preset ? "" : `<button class="icon" data-pm="rename" data-i="${i}" title="${t("Umbenennen", "Rename")}">${PENCIL_ICON}</button>`}
              <button class="icon" data-pm="copy" data-i="${i}" title="${t("Duplizieren", "Duplicate")}">${COPY_ICON}</button>
              ${p.preset ? "" : del}
            </div>
          </div>`;
      })
      .join("");

    let imports = "";
    if (pm.imports) {
      const e = pm.edit;
      if (e && e.kind === "import") {
        const prog = pm.imports[e.index];
        const field = nameField(e.name);
        const preview = this._curveSvg(compact(prog.points), prog.name, t, { now: false });
        imports = editRow(
          t("Importieren", "Import"),
          field,
          t("Im Dongle speichern", "Save to dongle"),
          `${preview}<div class="hint">${prog.points.length} ${t("Punkte", "points")}</div>`
        );
      } else {
        imports = `
          <div class="edit">
            <div class="edit-title">${t("Programme in der Datei", "Programs in the file")}</div>
            ${pm.imports
              .map(
                (p, i) => `
              <div class="row">
                <div class="row-name"><span>${escapeHtml(p.name)}</span></div>
                <div class="row-meta">${p.points.length} ${t("Punkte", "points")}</div>
                <div class="row-actions"><button class="btn" data-pm="pick" data-i="${i}">${t("Importieren", "Import")}</button></div>
              </div>`
              )
              .join("")}
            <div class="buttons"><button class="btn" data-pm="cancel">${t("Schließen", "Close")}</button></div>
          </div>`;
      }
    }

    const message = pm.message
      ? `<div class="message ${pm.message.error ? "err" : "ok"}">${escapeHtml(pm.message.text)}</div>`
      : "";
    return `
      <div class="programs">
        <div class="programs-head">
          <span>${t("Programme im Dongle", "Programs in the dongle")}${pm.list ? ` · ${escapeHtml(pm.list.lamp_type)}` : ""}</span>
          <button class="icon" data-pm="close" title="${t("Schließen", "Close")}">${CLOSE_ICON}</button>
        </div>
        ${message}
        ${list ? rows : `<div class="hint">${pm.message ? "" : t("Lade …", "Loading …")}</div>`}
        ${imports}
        <div class="buttons footer">
          <button class="btn" data-pm="download" ${list ? "" : "disabled"}>${DOWNLOAD_ICON}${t("Sicherung herunterladen", "Download backup")}</button>
          <button class="btn" data-pm="import" ${list ? "" : "disabled"}>${UPLOAD_ICON}${t("Aus Datei importieren", "Import from file")}</button>
          <input type="file" accept=".json,application/json" hidden>
        </div>
      </div>`;
  }

  _bindProgramPanel(t) {
    const root = this.shadowRoot.querySelector(".programs");
    if (!root) return;
    const pm = this._pm;
    const programs = pm.list?.programs || [];
    const nameInput = root.querySelector("input.name");
    if (nameInput) {
      const hint = root.querySelector(".name-hint");
      const save = root.querySelector('[data-pm="save"]');
      nameInput.addEventListener("input", () => {
        pm.edit.name = nameInput.value;
        const check = this._nameCheck(nameInput.value, t);
        hint.textContent = check.err || check.note;
        hint.classList.toggle("err", !!check.err);
        save.disabled = !!check.err || pm.busy;
      });
      nameInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !save.disabled) save.click();
        if (ev.key === "Escape") root.querySelector('[data-pm="cancel"]').click();
      });
      if (!this._focused) {
        nameInput.focus();
        nameInput.select();
        this._focused = true;
      }
    }
    const fileInput = root.querySelector("input[type=file]");
    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) this._readImport(fileInput.files[0], t);
    });
    root.querySelectorAll("[data-pm]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const i = Number(btn.dataset.i);
        const p = programs[i];
        const e = pm.edit;
        pm.message = null;
        switch (btn.dataset.pm) {
          case "close":
            this._pm = null;
            break;
          case "rename":
            pm.edit = { kind: "rename", index: i, name: p.name };
            this._focused = false;
            break;
          case "copy":
            pm.edit = { kind: "copy", index: i, name: `${p.name} 2`.slice(0, MAX_NAME_BYTES) };
            this._focused = false;
            break;
          case "delete":
            pm.edit = { kind: "delete", index: i };
            break;
          case "pick":
            pm.edit = { kind: "import", index: i, name: pm.imports[i].name };
            this._focused = false;
            break;
          case "cancel":
            if (e?.kind === "import" && pm.imports.length > 1) pm.edit = null;
            else {
              pm.edit = null;
              if (e?.kind === "import" || !e) pm.imports = null;
            }
            break;
          case "download":
            this._download();
            return;
          case "import":
            fileInput.value = "";
            fileInput.click();
            return;
          case "save": {
            const name = (nameInput ? nameInput.value : e.name || "").trim();
            if (e.kind === "rename") {
              const old = programs[e.index].name;
              if (name === old) pm.edit = null;
              else this._write("rename_program", { program: old, new_name: name }, t(`Umbenannt in „${name}“`, `Renamed to "${name}"`));
            } else if (e.kind === "copy") {
              this._write("save_program", { name, points: programs[e.index].points }, t(`„${name}“ gespeichert`, `"${name}" saved`));
            } else if (e.kind === "import") {
              this._write("save_program", { name, points: pm.imports[e.index].points }, t(`„${name}“ gespeichert`, `"${name}" saved`));
            } else if (e.kind === "delete") {
              const old = programs[e.index].name;
              this._write("delete_program", { program: old }, t(`„${old}“ gelöscht`, `"${old}" deleted`));
            }
            return;
          }
        }
        this._render();
      })
    );
  }

  // ---- rendering -----------------------------------------------------------

  _render() {
    const hass = this._hass;
    const lang = this._lang();
    const t = (de, en) => (lang === "de" ? de : en);
    const light = hass.states[this._config.entity];
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });

    if (!light) {
      this.shadowRoot.innerHTML = `<ha-card><div class="warn">${t("Entität nicht gefunden", "Entity not found")}: ${this._config.entity}</div></ha-card>`;
      return;
    }

    const related = this._related();
    const modeState = related.mode ? hass.states[related.mode] : null;
    const name = this._config.name || light.attributes.friendly_name || "Kessil";
    const isManual = modeState ? modeState.state === "manual" : !!light.attributes.manual;
    const programs = modeState?.attributes.programs || {};
    const modeLabel = (opt) => (opt === "manual" ? t("Manuell", "Manual") : opt);

    // percent value of a channel; intensity falls back to the light's brightness
    const percentOf = (key) => {
      const st = related[key] ? hass.states[related[key]] : null;
      const v = st ? Number(st.state) : NaN;
      if (Number.isFinite(v)) return v;
      if (key === "intensity") return pct(light.state === "on" ? light.attributes.brightness || 0 : 0);
      return 0;
    };

    // Curve: the running program, or in manual mode a constant line at the current values.
    let curve = null;
    let curveName = null;
    if (isManual) {
      const raw = (key) => Math.round((percentOf(key) * 255) / 100);
      curve = [[0, raw("intensity"), raw("color"), 0, 0, 0]];
      curveName = t("Manuell (konstant)", "Manual (constant)");
    } else if (modeState && programs[modeState.state]) {
      curve = programs[modeState.state];
      curveName = modeState.state;
    }

    const kelvin = KELVIN_RANGES[light.attributes.lamp_type] || null;
    const fmtK = (k) => `${k} K`;
    const sliders = CHANNELS.filter((c) => (related[c.key] && hass.states[related[c.key]]) || c.key === "intensity")
      .map((c) => {
        const st = related[c.key] ? hass.states[related[c.key]] : null;
        const v = percentOf(c.key);
        return `
          <div class="slider">
            <div class="slider-head"><span>${c.label[lang]}</span><span class="val" data-val="${c.key}">${v} %</span></div>
            <input type="range" min="0" max="100" step="1" value="${v}" data-key="${c.key}"
                   style="--track:${c.track}" ${st && st.state === "unavailable" ? "disabled" : ""}>
            ${c.kelvin && kelvin ? `<div class="slider-ends"><span>warm · ${fmtK(kelvin[0])}</span><span>${fmtK(kelvin[1])} · ${t("kühl", "cool")}</span></div>` : ""}
          </div>`;
      })
      .join("");

    const modes = modeState
      ? modeState.attributes.options
          .map(
            (opt) =>
              `<button class="chip ${opt === modeState.state ? "active" : ""}" data-option="${encodeURIComponent(opt)}">${escapeHtml(modeLabel(opt))}</button>`
          )
          .join("")
      : "";

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title">${escapeHtml(name)}</div>
          ${curve ? this._lightAmountBadge(curve, lang, t) : ""}
        </div>

        ${modes ? `<div class="modes">${modes}<button class="icon edit-programs ${this._pm ? "active" : ""}" data-open-programs title="${t("Programme verwalten", "Manage programs")}">${PENCIL_ICON}</button></div>` : ""}

        ${curve ? this._curveSvg(curve, curveName, t) : ""}

        ${this._pm ? this._programPanel(t, isManual ? null : modeState?.attributes.program_id) : `<div class="sliders">${sliders}</div>`}
      </ha-card>`;

    this.shadowRoot.querySelector("[data-open-programs]")?.addEventListener("click", () => {
      if (this._pm) {
        this._pm = null;
        this._render();
      } else this._openPrograms();
    });
    if (this._pm) this._bindProgramPanel(t);

    this.shadowRoot.querySelectorAll("input[type=range]").forEach((input) => {
      const key = input.dataset.key;
      const label = this.shadowRoot.querySelector(`[data-val="${key}"]`);
      input.addEventListener("pointerdown", () => (this._dragging = true));
      input.addEventListener("pointerup", () => (this._dragging = false));
      input.addEventListener("input", () => (label.textContent = `${input.value} %`));
      input.addEventListener("change", () => {
        this._dragging = false;
        const value = Number(input.value);
        if (related[key]) {
          this._setNumber(related[key], value);
        } else if (key === "intensity") {
          // older setups without the intensity number entity
          this._hass.callService("light", "turn_on", {
            entity_id: this._config.entity,
            brightness: Math.max(1, Math.round((value * 255) / 100)),
          });
        }
      });
    });
    this.shadowRoot.querySelectorAll(".chip").forEach((btn) =>
      btn.addEventListener("click", () => {
        const opt = decodeURIComponent(btn.dataset.option);
        if (opt !== modeState.state) this._selectMode(related.mode, opt);
      })
    );
  }

  /** Daily light amount = hours at full intensity (integral of intensity over 24 h). */
  _lightAmountBadge(points, lang, t) {
    let sum = 0;
    for (let m = 0; m < 1440; m++) sum += valueAt(points, m + 0.5, 1);
    const hours = sum / 255 / 60;
    const text = hours.toLocaleString(lang === "de" ? "de-DE" : "en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const tip = t(
      `Tageslichtmenge: entspricht ${text} Stunden bei voller Intensität`,
      `Daily light amount: equals ${text} hours at full intensity`
    );
    return `<div class="badge amount" title="${escapeHtml(tip)}">${SUN_ICON}<span>${text} h</span></div>`;
  }

  _curveSvg(points, name, t, { now: showNow = true } = {}) {
    const W = 300;
    const H = 90;
    const PAD = 4;
    const x = (m) => PAD + (m / 1440) * (W - 2 * PAD);
    const y = (raw) => H - PAD - (raw / 255) * (H - 2 * PAD);
    const series = (idx) => {
      const pts = [];
      for (let m = 0; m <= 1440; m += 10) pts.push(`${x(m).toFixed(1)},${y(valueAt(points, m % 1440, idx)).toFixed(1)}`);
      return pts.join(" ");
    };
    const now = new Date();
    const minute = now.getHours() * 60 + now.getMinutes();
    const nowVal = valueAt(points, minute, 1);
    const fmt = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
    const effectPoints = points.filter((p) => p.length > 6 && p[6] >= 0);
    const effectLabel = (p) =>
      `${p[6] === 0 ? t("Gewitter", "Thunderstorm") : `${t("Effekt", "Effect")} ${p[6]}`} ${fmt(p[0])}`;
    // dashed marker lines inside the (non-uniformly scaled) chart ...
    const effectLines = effectPoints
      .map((p) => `<line class="effect" x1="${x(p[0])}" x2="${x(p[0])}" y1="${PAD}" y2="${y(0)}"></line>`)
      .join("");
    // ... and undistorted cloud-with-lightning icons positioned on top in HTML
    const effectIcons = effectPoints
      .map(
        (p) => `<div class="effect-icon" style="left:${((x(p[0]) / W) * 100).toFixed(2)}%" title="${escapeHtml(effectLabel(p))}">${STORM_ICON}</div>`
      )
      .join("");
    const ticks = [0, 6, 12, 18, 24]
      .map((h) => `<text x="${x(h * 60)}" y="${H + 12}" text-anchor="middle">${h}</text>`)
      .join("");

    return `
      <div class="curve">
        <div class="curve-head">
          <span>${t("Tageskurve", "Daily curve")}: ${escapeHtml(name)}</span>
          <span class="legend"><i class="l-int"></i>${t("Intensität", "Intensity")} <i class="l-col"></i>${this._related().color ? t("Farbtemperatur", "Color temp.") : t("Spektrum", "Spectrum")}</span>
        </div>
        <div class="chart">
        ${effectIcons}
        <svg viewBox="0 0 ${W} ${H + 16}" preserveAspectRatio="none">
          <line class="grid" x1="${PAD}" x2="${W - PAD}" y1="${y(0)}" y2="${y(0)}"></line>
          <line class="grid" x1="${PAD}" x2="${W - PAD}" y1="${y(255)}" y2="${y(255)}"></line>
          <polyline class="s-col" points="${series(2)}"></polyline>
          <polygon class="s-int-fill" points="${x(0)},${y(0)} ${series(1)} ${x(1440)},${y(0)}"></polygon>
          <polyline class="s-int" points="${series(1)}"></polyline>
          ${effectLines}
          ${showNow ? `<line class="now" x1="${x(minute)}" x2="${x(minute)}" y1="${PAD}" y2="${y(0)}"></line>
          <circle class="now-dot" cx="${x(minute)}" cy="${y(nowVal)}" r="3"></circle>` : ""}
          ${ticks}
        </svg>
        </div>
      </div>`;
  }
}

const SUN_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="currentColor"/>
  <g stroke="currentColor" stroke-width="2" stroke-linecap="round">
    <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>
  </g></svg>`;

// Cloud with lightning bolt (original drawing), used to mark the thunderstorm effect.
const STORM_ICON = `<svg viewBox="0 0 24 22" aria-hidden="true">
  <path d="M6.5 13.5a4.2 4.2 0 0 1-.4-8.38A5.6 5.6 0 0 1 16.9 4.3a4 4 0 0 1 .9 7.9 3 3 0 0 1-.8 1.3z"
        fill="var(--secondary-text-color, #8a8a8a)" opacity="0.9"/>
  <path d="M12.2 10.5 8.8 16.2h2.7l-1.3 5.3 4.9-7h-2.8l1.6-4z" fill="#f5b301"
        stroke="var(--card-background-color, #fff)" stroke-width="0.8" stroke-linejoin="round"/>
</svg>`;

const svgIcon = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}" fill="currentColor"/></svg>`;
// Simple original glyphs (pencil, copy, trash, lock, close, download, upload).
const PENCIL_ICON = svgIcon("M4 17.2V20h2.8L17.6 9.2l-2.8-2.8zM19.7 7.1a1 1 0 0 0 0-1.4l-1.4-1.4a1 1 0 0 0-1.4 0l-1.2 1.2 2.8 2.8z");
const COPY_ICON = svgIcon("M8 3h10a2 2 0 0 1 2 2v12h-2V5H8zm-3 4h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zm0 2v10h9V9z");
const TRASH_ICON = svgIcon("M9 3h6l1 1h4v2H4V4h4zM6 8h12l-1 12a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2zm3 2v9h2v-9zm4 0v9h2v-9z");
const LOCK_ICON = svgIcon("M7 10V8a5 5 0 0 1 10 0v2h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zm2 0h6V8a3 3 0 0 0-6 0z");
const CLOSE_ICON = svgIcon("M6.4 5 12 10.6 17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4z");
const DOWNLOAD_ICON = svgIcon("M11 4h2v8.2l3.3-3.3 1.4 1.4L12 16l-5.7-5.7 1.4-1.4 3.3 3.3zM5 18h14v2H5z");
const UPLOAD_ICON = svgIcon("M11 16h2V7.8l3.3 3.3 1.4-1.4L12 4 6.3 9.7l1.4 1.4L11 7.8zM5 18h14v2H5z");

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const STYLE = `
  ha-card { padding: 16px; }
  .warn { color: var(--error-color, #db4437); }
  .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .title { font-size: 1.2em; font-weight: 500; color: var(--primary-text-color); }
  .badge { font-size: 0.8em; padding: 2px 10px; border-radius: 12px; white-space: nowrap;
           background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .badge.amount { display: inline-flex; align-items: center; gap: 5px; background: rgba(245,179,1,0.15);
                  color: #c98a00; font-variant-numeric: tabular-nums; cursor: help; }
  .badge.amount svg { width: 15px; height: 15px; }

  .sliders { display: grid; gap: 10px; margin-top: 16px; }
  .slider-head { display: flex; justify-content: space-between; font-size: 0.9em; color: var(--secondary-text-color); }
  .slider-head .val { color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  .slider-ends { display: flex; justify-content: space-between; font-size: 0.75em; color: var(--secondary-text-color); margin-top: 2px; }
  input[type=range] { -webkit-appearance: none; appearance: none; width: 100%; height: 10px; border-radius: 5px;
                      background: var(--track); margin: 6px 0 0; outline: none; }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%;
                      background: var(--card-background-color, #fff); border: 2px solid var(--primary-text-color); cursor: pointer; }
  input[type=range]::-moz-range-thumb { width: 18px; height: 18px; border-radius: 50%;
                      background: var(--card-background-color, #fff); border: 2px solid var(--primary-text-color); cursor: pointer; }
  input[type=range]:disabled { opacity: 0.4; }

  .modes { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  .chip { border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color);
          border-radius: 16px; padding: 4px 12px; font: inherit; font-size: 0.9em; cursor: pointer; }
  .chip.active { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }

  .curve { margin-top: 16px; }
  .curve-head { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px;
                font-size: 0.85em; color: var(--secondary-text-color); margin-bottom: 4px; }
  .legend i { display: inline-block; width: 10px; height: 3px; margin: 0 4px 2px 8px; vertical-align: middle; }
  .legend .l-int { background: #4fc3f7; }
  .legend .l-col { background: #c9b98a; }
  .curve svg { width: 100%; height: 110px; overflow: visible; }
  .curve text { font-size: 9px; fill: var(--secondary-text-color); }
  .curve .grid { stroke: var(--divider-color, rgba(127,127,127,0.25)); stroke-width: 0.5; }
  .curve .s-int { fill: none; stroke: #4fc3f7; stroke-width: 1.8; vector-effect: non-scaling-stroke; }
  .curve .s-int-fill { fill: rgba(79,195,247,0.15); stroke: none; }
  .curve .s-col { fill: none; stroke: #c9b98a; stroke-width: 1.2; stroke-dasharray: 3 2; vector-effect: non-scaling-stroke; }
  .curve .now { stroke: var(--primary-text-color); stroke-width: 1; stroke-dasharray: 2 2; vector-effect: non-scaling-stroke; }
  .curve .now-dot { fill: var(--primary-text-color); }
  .curve .chart { position: relative; padding-top: 22px; }
  .curve .effect { stroke: #f5b301; stroke-width: 1; stroke-dasharray: 1 2; vector-effect: non-scaling-stroke; opacity: 0.7; }
  .curve .effect-icon { position: absolute; top: 0; width: 24px; height: 22px; transform: translateX(-50%); }
  .curve .effect-icon svg { width: 100%; height: 100%; display: block; }

  .modes .edit-programs { margin-left: auto; }
  button.icon { border: none; background: none; color: var(--secondary-text-color); padding: 4px; border-radius: 50%;
                width: 30px; height: 30px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
  button.icon svg { width: 18px; height: 18px; }
  button.icon:hover:not(:disabled), button.icon.active { background: var(--secondary-background-color); color: var(--primary-text-color); }
  button.icon:disabled { opacity: 0.3; cursor: default; }

  .programs { margin-top: 16px; border-top: 1px solid var(--divider-color); padding-top: 8px; }
  .programs-head { display: flex; justify-content: space-between; align-items: center;
                   font-size: 0.9em; font-weight: 500; color: var(--primary-text-color); }
  .row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px;
         padding: 4px 0; border-bottom: 1px solid var(--divider-color); min-height: 38px; }
  .row:last-of-type { border-bottom: none; }
  .row-name { display: flex; align-items: center; gap: 6px; min-width: 0; color: var(--primary-text-color); }
  .row-name span:not(.tag):not(.lock) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row-meta { font-size: 0.8em; color: var(--secondary-text-color); white-space: nowrap; }
  .row-actions { display: flex; }
  .lock { color: var(--secondary-text-color); display: inline-flex; }
  .lock svg { width: 14px; height: 14px; }
  .tag { font-size: 0.72em; padding: 1px 7px; border-radius: 8px; background: var(--primary-color);
         color: var(--text-primary-color, #fff); }
  .edit { margin: 6px 0; padding: 10px; border-radius: 8px; background: var(--secondary-background-color); }
  .edit.danger { background: rgba(219,68,55,0.1); }
  .edit-title { font-size: 0.9em; margin-bottom: 6px; color: var(--primary-text-color); }
  .edit .row { border-bottom: none; }
  .edit .curve { margin-top: 8px; }
  input.name { width: 100%; box-sizing: border-box; font: inherit; padding: 6px 8px; border-radius: 6px;
               border: 1px solid var(--divider-color); background: var(--card-background-color, #fff);
               color: var(--primary-text-color); }
  .hint { font-size: 0.8em; color: var(--secondary-text-color); margin-top: 4px; }
  .hint.err, .message.err { color: var(--error-color, #db4437); }
  .message { font-size: 0.85em; margin: 6px 0; }
  .message.ok { color: var(--success-color, #43a047); }
  .buttons { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; margin-top: 8px; }
  .buttons.footer { justify-content: flex-start; margin-top: 12px; }
  .btn { display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 0.85em; cursor: pointer;
         border: 1px solid var(--divider-color); background: var(--card-background-color, #fff);
         color: var(--primary-text-color); border-radius: 16px; padding: 5px 12px; }
  .btn svg { width: 16px; height: 16px; }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
  .btn:disabled { opacity: 0.45; cursor: default; }
`;

if (!customElements.get("kessil-card")) {
  customElements.define("kessil-card", KessilCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "kessil-card",
    name: "Kessil",
    description: "Mode, daily curve and channel sliders for a Kessil group",
    preview: false,
  });
  console.info(`%c KESSIL-CARD %c ${CARD_VERSION} `, "background:#f5761a;color:#fff", "background:#333;color:#fff");
}
