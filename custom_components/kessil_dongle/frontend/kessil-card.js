/*
 * Kessil card – bundled with the kessil_dongle integration.
 *
 *   type: custom:kessil-card
 *   entity: light.default_ts      # the group's light entity
 *   name: Aquarium                # optional
 *
 * Colour, red, amber and mode entities are found automatically on the same
 * device (via their translation keys).
 */

const DOMAIN = "kessil_dongle";
const CARD_VERSION = "0.1.7";

const CHANNELS = [
  { key: "color", label: { de: "Lichtfarbe", en: "Light color" }, track: "linear-gradient(90deg,#ffe3a8,#ffffff,#8ecbff)", index: 1 },
  { key: "red", label: { de: "Rot", en: "Red" }, track: "linear-gradient(90deg,#3a1414,#e53935)", index: 3 },
  { key: "amber", label: { de: "Amber", en: "Amber" }, track: "linear-gradient(90deg,#3a2410,#f5761a)", index: 4 },
];

const ARC_START = 135; // degrees, measured clockwise from +x (SVG coordinates)
const ARC_SWEEP = 270;
const DIAL = { cx: 100, cy: 100, r: 80 };

const pct = (raw) => Math.round((raw * 100) / 255);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function polar(angleDeg, r = DIAL.r) {
  const a = (angleDeg * Math.PI) / 180;
  return [DIAL.cx + r * Math.cos(a), DIAL.cy + r * Math.sin(a)];
}

function arcPath(fraction) {
  const f = clamp(fraction, 0, 1);
  const [x0, y0] = polar(ARC_START);
  if (f <= 0.0005) return `M ${x0} ${y0}`;
  const end = ARC_START + ARC_SWEEP * f;
  const [x1, y1] = polar(end);
  const large = ARC_SWEEP * f > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${DIAL.r} ${DIAL.r} 0 ${large} 1 ${x1} ${y1}`;
}

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

  _setBrightness(raw) {
    if (raw <= 0) {
      this._hass.callService("light", "turn_off", { entity_id: this._config.entity });
    } else {
      this._hass.callService("light", "turn_on", { entity_id: this._config.entity, brightness: raw });
    }
  }

  _toggle() {
    this._hass.callService("light", "toggle", { entity_id: this._config.entity });
  }

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
    const brightness = light.state === "on" ? light.attributes.brightness || 0 : 0;
    const name = this._config.name || light.attributes.friendly_name || "Kessil";
    const isManual = modeState ? modeState.state === "manual" : !!light.attributes.manual;
    const programs = modeState?.attributes.programs || {};
    const programNames = Object.keys(programs);
    const curveName = !isManual && programs[modeState?.state] ? modeState.state : programNames[0];
    const curve = curveName ? programs[curveName] : null;

    const modeLabel = (opt) => (opt === "manual" ? t("Manuell", "Manual") : opt);

    const sliders = CHANNELS.filter((c) => related[c.key] && hass.states[related[c.key]])
      .map((c) => {
        const st = hass.states[related[c.key]];
        const val = Number(st.state);
        const v = Number.isFinite(val) ? val : 0;
        return `
          <div class="slider">
            <div class="slider-head"><span>${c.label[lang]}</span><span class="val" data-val="${c.key}">${v} %</span></div>
            <input type="range" min="0" max="100" step="1" value="${v}" data-key="${c.key}"
                   style="--track:${c.track}" ${st.state === "unavailable" ? "disabled" : ""}>
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
          <div class="badge ${isManual ? "manual" : "program"}">${
            isManual ? t("Manuell", "Manual") : escapeHtml(modeState?.state || t("Programm", "Program"))
          }</div>
        </div>

        <div class="dial-wrap">
          <svg class="dial" viewBox="0 0 200 200">
            <path class="track" d="${arcPath(1)}"></path>
            <path class="value" d="${arcPath(brightness / 255)}"></path>
            <circle class="knob" r="9" cx="${polar(ARC_START + ARC_SWEEP * (brightness / 255))[0]}"
                    cy="${polar(ARC_START + ARC_SWEEP * (brightness / 255))[1]}"></circle>
          </svg>
          <button class="center" title="${t("Ein/Aus", "On/Off")}">
            <span class="pct">${pct(brightness)}<small>%</small></span>
            <span class="lbl">${t("Intensität", "Intensity")}</span>
          </button>
        </div>

        <div class="sliders">${sliders}</div>

        ${modes ? `<div class="modes">${modes}</div>` : ""}

        ${curve ? this._curveSvg(curve, curveName, t) : ""}
      </ha-card>`;

    this._wireDial(brightness);
    this.shadowRoot.querySelector(".center").addEventListener("click", () => this._toggle());
    this.shadowRoot.querySelectorAll("input[type=range]").forEach((input) => {
      const key = input.dataset.key;
      const label = this.shadowRoot.querySelector(`[data-val="${key}"]`);
      input.addEventListener("pointerdown", () => (this._dragging = true));
      input.addEventListener("pointerup", () => (this._dragging = false));
      input.addEventListener("input", () => (label.textContent = `${input.value} %`));
      input.addEventListener("change", () => {
        this._dragging = false;
        this._setNumber(related[key], Number(input.value));
      });
    });
    this.shadowRoot.querySelectorAll(".chip").forEach((btn) =>
      btn.addEventListener("click", () => {
        const opt = decodeURIComponent(btn.dataset.option);
        if (opt !== modeState.state) this._selectMode(related.mode, opt);
      })
    );
  }

  _wireDial(initial) {
    const svg = this.shadowRoot.querySelector(".dial");
    const valuePath = svg.querySelector(".value");
    const knob = svg.querySelector(".knob");
    const pctEl = this.shadowRoot.querySelector(".pct");
    let current = initial;

    const fromEvent = (ev) => {
      const rect = svg.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * 200 - DIAL.cx;
      const y = ((ev.clientY - rect.top) / rect.height) * 200 - DIAL.cy;
      let deg = (Math.atan2(y, x) * 180) / Math.PI;
      let rel = (deg - ARC_START + 720) % 360;
      if (rel > ARC_SWEEP) rel = rel > ARC_SWEEP + (360 - ARC_SWEEP) / 2 ? 0 : ARC_SWEEP;
      return Math.round((rel / ARC_SWEEP) * 255);
    };
    const show = (raw) => {
      current = raw;
      valuePath.setAttribute("d", arcPath(raw / 255));
      const [kx, ky] = polar(ARC_START + ARC_SWEEP * (raw / 255));
      knob.setAttribute("cx", kx);
      knob.setAttribute("cy", ky);
      pctEl.innerHTML = `${pct(raw)}<small>%</small>`;
    };

    svg.addEventListener("pointerdown", (ev) => {
      this._dragging = true;
      svg.setPointerCapture(ev.pointerId);
      show(fromEvent(ev));
    });
    svg.addEventListener("pointermove", (ev) => {
      if (this._dragging && svg.hasPointerCapture(ev.pointerId)) show(fromEvent(ev));
    });
    const finish = (ev) => {
      if (!svg.hasPointerCapture(ev.pointerId)) return;
      svg.releasePointerCapture(ev.pointerId);
      this._dragging = false;
      this._setBrightness(current);
    };
    svg.addEventListener("pointerup", finish);
    svg.addEventListener("pointercancel", finish);
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
    const ticks = [0, 6, 12, 18, 24]
      .map((h) => `<text x="${x(h * 60)}" y="${H + 12}" text-anchor="middle">${h}</text>`)
      .join("");

    return `
      <div class="curve">
        <div class="curve-head">
          <span>${t("Tageskurve", "Daily curve")}: ${escapeHtml(name)}</span>
          <span class="legend"><i class="l-int"></i>${t("Intensität", "Intensity")} <i class="l-col"></i>${t("Lichtfarbe", "Light color")}</span>
        </div>
        <svg viewBox="0 0 ${W} ${H + 16}" preserveAspectRatio="none">
          <line class="grid" x1="${PAD}" x2="${W - PAD}" y1="${y(0)}" y2="${y(0)}"></line>
          <line class="grid" x1="${PAD}" x2="${W - PAD}" y1="${y(255)}" y2="${y(255)}"></line>
          <polyline class="s-col" points="${series(2)}"></polyline>
          <polygon class="s-int-fill" points="${x(0)},${y(0)} ${series(1)} ${x(1440)},${y(0)}"></polygon>
          <polyline class="s-int" points="${series(1)}"></polyline>
          <line class="now" x1="${x(minute)}" x2="${x(minute)}" y1="${PAD}" y2="${y(0)}"></line>
          <circle class="now-dot" cx="${x(minute)}" cy="${y(nowVal)}" r="3"></circle>
          ${ticks}
        </svg>
      </div>`;
  }
}

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
  .badge.manual { background: rgba(245,118,26,0.15); color: #f5761a; }
  .badge.program { background: rgba(var(--rgb-primary-color, 3,169,244),0.15); color: var(--primary-color); }

  .dial-wrap { position: relative; width: 220px; max-width: 100%; margin: 8px auto 0; aspect-ratio: 1; }
  .dial { width: 100%; height: 100%; touch-action: none; cursor: pointer; }
  .dial path { fill: none; stroke-linecap: round; stroke-width: 14; }
  .dial .track { stroke: var(--divider-color, rgba(127,127,127,0.25)); }
  .dial .value { stroke: var(--kessil-dial-color, #4fc3f7); }
  .dial .knob { fill: var(--card-background-color, #fff); stroke: var(--kessil-dial-color, #4fc3f7); stroke-width: 4; }
  .center { position: absolute; inset: 28%; border: none; background: none; border-radius: 50%; cursor: pointer;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            color: var(--primary-text-color); font: inherit; }
  .center:focus-visible { outline: 2px solid var(--primary-color); }
  .pct { font-size: 2.6em; font-weight: 400; line-height: 1; }
  .pct small { font-size: 0.45em; margin-left: 2px; color: var(--secondary-text-color); }
  .lbl { font-size: 0.85em; color: var(--secondary-text-color); margin-top: 4px; }

  .sliders { display: grid; gap: 10px; margin-top: 4px; }
  .slider-head { display: flex; justify-content: space-between; font-size: 0.9em; color: var(--secondary-text-color); }
  .slider-head .val { color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  input[type=range] { -webkit-appearance: none; appearance: none; width: 100%; height: 10px; border-radius: 5px;
                      background: var(--track); margin: 6px 0 0; outline: none; }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%;
                      background: var(--card-background-color, #fff); border: 2px solid var(--primary-text-color); cursor: pointer; }
  input[type=range]::-moz-range-thumb { width: 18px; height: 18px; border-radius: 50%;
                      background: var(--card-background-color, #fff); border: 2px solid var(--primary-text-color); cursor: pointer; }
  input[type=range]:disabled { opacity: 0.4; }

  .modes { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }
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
`;

if (!customElements.get("kessil-card")) {
  customElements.define("kessil-card", KessilCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "kessil-card",
    name: "Kessil",
    description: "Intensity dial, spectrum sliders, mode and daily curve for a Kessil group",
    preview: false,
  });
  console.info(`%c KESSIL-CARD %c ${CARD_VERSION} `, "background:#f5761a;color:#fff", "background:#333;color:#fff");
}
