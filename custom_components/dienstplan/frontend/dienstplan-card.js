/* Dienstplan-Karte für Home Assistant
 *
 * Konfiguration:
 *   type: custom:dienstplan-card
 *   entity: calendar.<name>_dienstplan
 *   title: Dienstplan Jenny        # optional
 *
 * Bedienung: Tag antippen, im Auswahlfenster die Schicht wählen – der Eintrag
 * wird sofort gespeichert und der Kalendertermin angelegt.
 */
(() => {
  const DOMAIN = "dienstplan";
  const MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
  ];
  const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
  const FALLBACK_COLORS = {
    F: "#f5a623", Z: "#43a047", S: "#e8743b", N: "#5c6bc0",
    U: "#26a69a", K: "#e53935", X: "#9e9e9e",
  };
  const DEFAULT_COLOR = "#607d8b";

  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const monthStart = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
  const mondayOffset = (d) => (d.getDay() + 6) % 7;

  const h = (tag, props = {}, ...children) => {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === false || value == null) continue;
      if (key === "class") el.className = value;
      else if (key === "style") el.style.cssText = value;
      else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else if (key === "disabled") el.disabled = true;
      else el.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child == null || child === false) continue;
      el.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return el;
  };

  const STYLE = `
    :host { display: block; }
    ha-card { padding: 12px; }
    .title { font-size: 1.15em; font-weight: 500; margin: 0 4px 8px; color: var(--primary-text-color); }
    .nav { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .nav .month { flex: 1; text-align: center; font-weight: 500; color: var(--primary-text-color); }
    button { font: inherit; cursor: pointer; color: var(--primary-text-color); }
    .icon-btn, .text-btn {
      background: var(--secondary-background-color, rgba(127,127,127,.15));
      border: none; border-radius: 8px; padding: 6px 12px; min-height: 36px;
    }
    .icon-btn { width: 40px; padding: 6px 0; font-size: 1.2em; line-height: 1; }
    .grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
    .wd { text-align: center; font-size: .75em; color: var(--secondary-text-color); padding-bottom: 2px; }
    .day {
      display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 2px;
      min-height: 52px; padding: 4px 0 3px; border-radius: 8px;
      background: var(--secondary-background-color, rgba(127,127,127,.1));
      border: 2px solid transparent; overflow: hidden;
    }
    .day.weekend { background: var(--divider-color, rgba(127,127,127,.2)); }
    .day.other .num { opacity: .4; }
    .day.today { border-color: var(--primary-color); }
    .num { font-size: .85em; line-height: 1.1; color: var(--primary-text-color); }
    .badge {
      color: #fff; font-size: .78em; font-weight: 700; border-radius: 6px;
      padding: 1px 5px; max-width: 92%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .footer { margin-top: 10px; min-height: 1.3em; }
    .status { font-size: .85em; color: var(--secondary-text-color); }
    .status.error { color: var(--error-color, #db4437); }
    .overlay {
      position: fixed; inset: 0; z-index: 9; background: rgba(0,0,0,.5);
      display: flex; align-items: center; justify-content: center; padding: 16px; box-sizing: border-box;
    }
    .dialog {
      background: var(--card-background-color, #fff); color: var(--primary-text-color);
      border-radius: 14px; width: min(100%, 380px); max-height: 82vh; display: flex; flex-direction: column;
      padding: 14px 12px 12px; box-sizing: border-box; box-shadow: 0 8px 30px rgba(0,0,0,.35);
    }
    .dlg-title { font-weight: 600; font-size: 1.05em; margin: 0 4px 10px; }
    .options { overflow-y: auto; display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
    .opt {
      display: flex; align-items: center; gap: 10px; text-align: left; width: 100%;
      background: var(--secondary-background-color, rgba(127,127,127,.12));
      border: 2px solid transparent; border-radius: 10px; padding: 8px 10px; min-height: 44px;
    }
    .opt.selected { border-color: var(--primary-color); }
    .dot { width: 14px; height: 14px; border-radius: 50%; flex: none; }
    .opt-code { font-weight: 700; min-width: 2.2em; }
    .opt-name { flex: 1; font-size: .92em; }
    .opt-time { font-size: .8em; color: var(--secondary-text-color); white-space: nowrap; }
    .opt.none .opt-name { color: var(--secondary-text-color); }
    button[disabled] { opacity: .5; cursor: default; }
  `;

  class DienstplanCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._month = monthStart(new Date());
      this._shifts = [];
      this._shiftMap = new Map();
      this._days = {};
      this._dialog = null; // Datum (YYYY-MM-DD) des geöffneten Auswahlfensters
      this._saving = false;
      this._loaded = false;
      this._status = "";
      this._error = "";
      this._hass = null;
      this._stamp = null;
      this._syncCalendar = null;
    }

    static getStubConfig() {
      return { entity: "calendar.dienstplan" };
    }

    getCardSize() {
      return 8;
    }

    setConfig(config) {
      if (!config || !config.entity || !String(config.entity).startsWith("calendar.")) {
        throw new Error("Bitte 'entity' mit einem Dienstplan-Kalender (calendar.…) angeben.");
      }
      this._config = config;
      this._render();
    }

    set hass(hass) {
      const first = this._hass === null;
      this._hass = hass;
      const state = hass.states[this._config.entity];
      const stamp = state ? state.last_updated : null;
      if (first) {
        this._load();
      } else if (stamp && stamp !== this._stamp && !this._saving) {
        this._load();
      }
      this._stamp = stamp;
    }

    // ---------------------------------------------------------------- Daten

    _gridDays() {
      const first = this._month;
      const start = addDays(first, -mondayOffset(first));
      const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
      const weeks = Math.ceil((mondayOffset(first) + daysInMonth) / 7);
      return Array.from({ length: weeks * 7 }, (_, i) => addDays(start, i));
    }

    async _load() {
      if (!this._hass || !this._config) return;
      const days = this._gridDays();
      const startKey = iso(days[0]);
      const endKey = iso(days[days.length - 1]);
      try {
        const res = await this._hass.callWS({
          type: `${DOMAIN}/get_days`,
          entity_id: this._config.entity,
          start: startKey,
          end: endKey,
        });
        this._shifts = res.shifts || [];
        this._shiftMap = new Map(this._shifts.map((s) => [s.code.toLowerCase(), s]));
        for (const key of Object.keys(this._days)) {
          if (key >= startKey && key <= endKey) delete this._days[key];
        }
        Object.assign(this._days, res.days || {});
        this._syncCalendar = res.sync_calendar || null;
        this._loaded = true;
        this._error = "";
      } catch (err) {
        this._error = (err && err.message) || "Dienstplan konnte nicht geladen werden.";
      }
      this._render();
    }

    _colorFor(code) {
      const shift = this._shiftMap.get((code || "").toLowerCase());
      if (shift && shift.color) return shift.color;
      return FALLBACK_COLORS[(code || "?")[0].toUpperCase()] || DEFAULT_COLOR;
    }

    _timeText(shift) {
      if (shift.start && shift.end) return `${shift.start}–${shift.end}`;
      return shift.kind === "off" ? "kein Termin" : "ganztägig";
    }

    // ---------------------------------------------------------------- Aktionen

    _open(key) {
      if (this._saving || !this._loaded) return;
      this._dialog = key;
      this._status = "";
      this._render();
    }

    _close() {
      this._dialog = null;
      this._render();
    }

    async _choose(code) {
      const key = this._dialog;
      if (!key || this._saving) return;
      if (code === (this._days[key] || "")) {
        this._close();
        return;
      }
      this._dialog = null;
      this._saving = true;
      this._error = "";
      this._status = "Speichere …";
      this._render();
      let saveError = "";
      try {
        await this._hass.callService(DOMAIN, "set_shift", { date: key, shift: code }, { entity_id: this._config.entity });
        this._status = code ? `${code} eingetragen.` : "Eintrag gelöscht.";
      } catch (err) {
        saveError = (err && err.message) || "Speichern fehlgeschlagen.";
        this._status = "";
      }
      this._saving = false;
      await this._load(); // setzt den Fehlerzustand zurück, daher danach erneut anzeigen
      if (saveError) {
        this._error = saveError;
        this._render();
      }
    }

    _go(deltaMonths) {
      const m = this._month;
      this._month = new Date(m.getFullYear(), m.getMonth() + deltaMonths, 1);
      this._load();
      this._render();
    }

    // ---------------------------------------------------------------- Darstellung

    _renderDialog() {
      const [y, m, d] = this._dialog.split("-").map(Number);
      const date = new Date(y, m - 1, d);
      const current = this._days[this._dialog] || "";
      return h(
        "div",
        {
          class: "overlay",
          onclick: (ev) => {
            if (ev.target === ev.currentTarget) this._close();
          },
        },
        h(
          "div",
          { class: "dialog", role: "dialog", "aria-label": "Dienst wählen" },
          h("div", { class: "dlg-title" }, `${WEEKDAYS_LONG[mondayOffset(date)]}, ${d}. ${MONTHS[m - 1]} ${y}`),
          h(
            "div",
            { class: "options" },
            this._shifts.map((shift) =>
              h(
                "button",
                {
                  class: `opt${current.toLowerCase() === shift.code.toLowerCase() ? " selected" : ""}`,
                  onclick: () => this._choose(shift.code),
                },
                h("span", { class: "dot", style: `background:${this._colorFor(shift.code)}` }),
                h("span", { class: "opt-code" }, shift.code),
                h("span", { class: "opt-name" }, shift.name),
                h("span", { class: "opt-time" }, this._timeText(shift))
              )
            ),
            h(
              "button",
              { class: `opt none${current ? "" : " selected"}`, onclick: () => this._choose("") },
              h("span", { class: "dot", style: "background:transparent;border:2px solid var(--secondary-text-color)" }),
              h("span", { class: "opt-name" }, "Kein Dienst (Eintrag löschen)")
            )
          ),
          h("button", { class: "text-btn", onclick: () => this._close() }, "Abbrechen")
        )
      );
    }

    _render() {
      const root = this.shadowRoot;
      if (!root || !this._config) return;
      root.replaceChildren();

      const todayKey = iso(new Date());
      const month = this._month.getMonth();

      const nav = h(
        "div",
        { class: "nav" },
        h("button", { class: "icon-btn", "aria-label": "Vorheriger Monat", onclick: () => this._go(-1) }, "‹"),
        h("div", { class: "month" }, `${MONTHS[month]} ${this._month.getFullYear()}`),
        h("button", { class: "icon-btn", "aria-label": "Nächster Monat", onclick: () => this._go(1) }, "›"),
        h(
          "button",
          {
            class: "text-btn",
            onclick: () => {
              this._month = monthStart(new Date());
              this._load();
              this._render();
            },
          },
          "Heute"
        )
      );

      const grid = h(
        "div",
        { class: "grid" },
        WEEKDAYS.map((wd) => h("div", { class: "wd" }, wd)),
        this._gridDays().map((day) => {
          const key = iso(day);
          const code = this._days[key] || "";
          const classes = ["day"];
          if (day.getDay() === 0 || day.getDay() === 6) classes.push("weekend");
          if (day.getMonth() !== month) classes.push("other");
          if (key === todayKey) classes.push("today");
          const label = `${day.getDate()}. ${MONTHS[day.getMonth()]}${code ? ", " + code : ""}`;
          return h(
            "button",
            { class: classes.join(" "), "aria-label": label, onclick: () => this._open(key) },
            h("span", { class: "num" }, day.getDate()),
            code ? h("span", { class: "badge", style: `background:${this._colorFor(code)}` }, code) : null
          );
        })
      );

      let statusText = this._error || this._status;
      if (!statusText && !this._loaded) statusText = "Lade …";
      if (!statusText && this._syncCalendar) statusText = `Termine werden auch nach ${this._syncCalendar} übertragen.`;
      const footer = h(
        "div",
        { class: "footer" },
        statusText ? h("div", { class: `status${this._error ? " error" : ""}` }, statusText) : null
      );

      root.append(
        h("style", {}, STYLE),
        h(
          "ha-card",
          {},
          this._config.title ? h("div", { class: "title" }, this._config.title) : null,
          nav,
          grid,
          footer,
          this._dialog ? this._renderDialog() : null
        )
      );
    }
  }

  if (!customElements.get("dienstplan-card")) {
    customElements.define("dienstplan-card", DienstplanCard);
  }
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dienstplan-card",
    name: "Dienstplan",
    description: "Monatsansicht: Tag antippen, Schicht wählen – erzeugt Kalendertermine.",
  });
})();
