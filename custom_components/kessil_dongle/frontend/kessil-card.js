/*
 * Kessil card – bundled with the kessil_dongle integration.
 *
 *   type: custom:kessil-card
 *   entity: light.default_ts      # the group's light entity
 *   name: Aquarium                # optional
 *
 * Intensity, light color, red, amber and mode entities are found automatically
 * on the same device (via their translation keys).
 */

const DOMAIN = "kessil_dongle";
const CARD_VERSION = "0.1.11";

const CHANNELS = [
  { key: "intensity", label: { de: "Intensität", en: "Intensity" }, track: "linear-gradient(90deg,#16202c,#4fc3f7)", index: 0 },
  { key: "color", label: { de: "Lichtfarbe", en: "Light color" }, track: "linear-gradient(90deg,#ffe3a8,#ffffff,#8ecbff)", index: 1 },
  { key: "red", label: { de: "Rot", en: "Red" }, track: "linear-gradient(90deg,#3a1414,#e53935)", index: 3 },
  { key: "amber", label: { de: "Amber", en: "Amber" }, track: "linear-gradient(90deg,#3a2410,#f5761a)", index: 4 },
];

const pct = (raw) => Math.round((raw * 100) / 255);

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
    if (sig === this._signature || this._dragging) return;
    this._signature = sig;
    this._render();
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

    const sliders = CHANNELS.filter((c) => (related[c.key] && hass.states[related[c.key]]) || c.key === "intensity")
      .map((c) => {
        const st = related[c.key] ? hass.states[related[c.key]] : null;
        const v = percentOf(c.key);
        return `
          <div class="slider">
            <div class="slider-head"><span>${c.label[lang]}</span><span class="val" data-val="${c.key}">${v} %</span></div>
            <input type="range" min="0" max="100" step="1" value="${v}" data-key="${c.key}"
                   style="--track:${c.track}" ${st && st.state === "unavailable" ? "disabled" : ""}>
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

        ${modes ? `<div class="modes">${modes}</div>` : ""}

        ${curve ? this._curveSvg(curve, curveName, t) : ""}

        <div class="sliders">${sliders}</div>
      </ha-card>`;

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

  _curveSvg(points, name, t) {
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
          <span class="legend"><i class="l-int"></i>${t("Intensität", "Intensity")} <i class="l-col"></i>${t("Lichtfarbe", "Light color")}</span>
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
          <line class="now" x1="${x(minute)}" x2="${x(minute)}" y1="${PAD}" y2="${y(0)}"></line>
          <circle class="now-dot" cx="${x(minute)}" cy="${y(nowVal)}" r="3"></circle>
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
