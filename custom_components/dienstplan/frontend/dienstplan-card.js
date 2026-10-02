/* Dienstplan-Karte für Home Assistant
 *
 * Konfiguration (alles außer entity ist optional; die Karte hat einen grafischen Editor):
 *   type: custom:dienstplan-card
 *   entity: calendar.<name>_dienstplan
 *   title: Dienstplan Jenny
 *   show_times: true                    # Uhrzeiten in den Tageszellen
 *   show_legend: true                   # Legende (zugleich Palette für „Schnell eintragen“)
 *   holidays: calendar.deutschland      # Feiertagskalender (z. B. Integration „Feiertage“)
 *
 * Bedienung:
 *   Tag antippen        -> Schicht wählen, optional „bis einschließlich“ für einen Zeitraum
 *   Kürzel in der Legende antippen -> „Schnell eintragen“: danach jeden Tag mit einem Tap setzen
 *   KW-Zelle antippen   -> Schicht für markierte Wochentage setzen oder Woche kopieren
 *   Wischen / ‹ ›       -> Monat wechseln
 */
// Absicherung: Scheitert der Start (egal woran), werden die Elemente trotzdem angemeldet und zeigen den Grund.
// Ohne das meldet Home Assistant nur „Custom element doesn't exist“, und der Grund bleibt verborgen.
(function boot(main) {
  try {
    main();
  } catch (err) {
    const reason = (err && err.message) || String(err);
    console.error("Dienstplan-Karte: Start fehlgeschlagen", err);
    const message = `Dienstplan-Karte konnte nicht starten: ${reason}. Bitte die Seite neu laden (Browser-Cache leeren) oder die Integration aktualisieren.`;
    const broken = () =>
      class extends HTMLElement {
        setConfig() {}
        set hass(_hass) {}
        getCardSize() {
          return 2;
        }
        connectedCallback() {
          this.style.cssText = "display:block;padding:16px;color:var(--error-color,#db4437)";
          this.textContent = message;
        }
      };
    for (const tag of ["dienstplan-card", "dienstplan-card-editor", "dienstplan-panel"]) {
      if (!customElements.get(tag)) customElements.define(tag, broken());
    }
  }
})(() => {
  const DOMAIN = "dienstplan";
  // Muss zur Version der Integration passen (const.py); die Integration meldet ihre Version bei jedem Laden
  // mit, und bei Abweichung zeigt die Karte einen Hinweis samt Knopf zum Neuladen.
  const CARD_VERSION = "0.5.0";
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
  const parseIso = (s) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const monthStart = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
  const mondayOffset = (d) => (d.getDay() + 6) % 7;
  const mondayOf = (d) => addDays(d, -mondayOffset(d));
  const fmtDate = (d) => `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.`;
  const fmtH = (n) => String(Math.round(n * 100) / 100).replace(".", ",");
  const isoWeek = (d) => {
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    return Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
  };
  // "06:30" -> "6:30", "13:00" -> "13"
  const shortTime = (t) => {
    const [h, m] = t.split(":");
    return m === "00" ? String(Number(h)) : `${Number(h)}:${m}`;
  };

  const flatten = (list) =>
    list.reduce((all, item) => all.concat(Array.isArray(item) ? flatten(item) : [item]), []);

  const h = (tag, props = {}, ...children) => {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === false || value == null) continue;
      if (key === "class") el.className = value;
      else if (key === "style") el.style.cssText = value;
      else if (key === "value") el.value = value;
      else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else if (key === "disabled") el.disabled = true;
      else el.setAttribute(key, value === true ? "" : value);
    }
    for (const child of flatten(children)) {
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
    .grid { display: grid; grid-template-columns: 2.9em repeat(7, minmax(0, 1fr)); gap: 4px; touch-action: pan-y; grid-template-rows: auto; grid-auto-rows: 1fr; }
    .wd { text-align: center; font-size: .75em; color: var(--secondary-text-color); padding-bottom: 2px; }
    .day {
      display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 1px;
      min-height: 58px; padding: 3px 0 2px; border-radius: 8px;
      background: var(--secondary-background-color, rgba(127,127,127,.1));
      border: 2px solid transparent; overflow: hidden;
    }
    .day.weekend { background: var(--divider-color, rgba(127,127,127,.2)); }
    .day.other .num { opacity: .4; }
    .day.today { border-color: var(--primary-color); }
    .day.holiday .num { color: var(--error-color, #db4437); font-weight: 700; }
    .num { font-size: .85em; line-height: 1.1; color: var(--primary-text-color); }
    .badge {
      color: #fff; font-size: .78em; font-weight: 700; border-radius: 6px;
      padding: 1px 5px; max-width: 92%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .time { font-size: .6em; line-height: 1.1; color: var(--secondary-text-color); white-space: nowrap; }
    .kw {
      display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
      background: transparent; border: 2px solid var(--divider-color, rgba(127,127,127,.3));
      border-radius: 8px; padding: 2px 0; min-height: 58px;
    }
    .kw-n { font-size: .68em; color: var(--secondary-text-color); }
    .kw-h { font-size: .72em; font-weight: 600; }
    .kw-h.neg { color: var(--error-color, #db4437); }
    .kw-h.pos { color: var(--success-color, #43a047); }
    ha-card.brushing { box-shadow: inset 0 0 0 2px var(--primary-color); }
    .legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .chip {
      display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px 3px 8px; min-height: 32px;
      border-radius: 16px; border: 2px solid transparent; font-size: .8em;
      background: var(--secondary-background-color, rgba(127,127,127,.15));
    }
    .chip.on { border-color: var(--primary-color); font-weight: 700; }
    .chip .dot { width: 10px; height: 10px; }
    .chip small { font-size: .85em; color: var(--secondary-text-color); font-weight: 400; }
    .summary { margin-top: 8px; font-size: .85em; color: var(--secondary-text-color); }
    .footer { margin-top: 10px; min-height: 1.3em; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .status { flex: 1 1 60%; font-size: .85em; color: var(--secondary-text-color); }
    .status.error { color: var(--error-color, #db4437); }
    .status.selectable { user-select: all; word-break: break-all; }
    .stale {
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; padding: 8px 10px;
      border-radius: 8px; font-size: .85em; color: var(--primary-text-color);
      background: color-mix(in srgb, var(--warning-color, #ffa600) 25%, transparent);
    }
    .stale span { flex: 1 1 60%; }
    .link-btn { font-size: .8em; padding: 4px 10px; min-height: 30px; }
    /* Natives <dialog>: liegt in der "top layer" und wird nie von Karten, Sections oder Themes beschnitten */
    dialog.overlay {
      padding: 0; border: none; background: transparent; color: inherit; overflow: visible;
      width: min(calc(100vw - 32px), 380px); max-width: none; max-height: none;
    }
    dialog.overlay::backdrop { background: rgba(0,0,0,.5); }
    .dialog {
      background: var(--card-background-color, #fff); color: var(--primary-text-color);
      border-radius: 14px; width: 100%; max-height: 86vh; display: flex; flex-direction: column;
      padding: 14px 12px 12px; box-sizing: border-box; box-shadow: 0 8px 30px rgba(0,0,0,.35);
    }
    .dialog:focus { outline: none; }
    .dlg-title { font-weight: 600; font-size: 1.05em; margin: 0 4px 8px; }
    .dlg-sub { font-size: .8em; color: var(--secondary-text-color); margin: 0 4px 6px; }
    .range { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 0 4px 8px; font-size: .85em; }
    .range input { font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color, rgba(127,127,127,.12)); border: none; border-radius: 8px; padding: 6px 8px; }
    .wdchips { display: flex; gap: 4px; margin: 0 0 8px; }
    .wdchip {
      flex: 1; min-height: 34px; border-radius: 8px; border: 2px solid transparent;
      background: var(--secondary-background-color, rgba(127,127,127,.12)); font-size: .85em;
    }
    .wdchip.on { border-color: var(--primary-color); font-weight: 700; }
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
    .opt-time { font-size: .78em; color: var(--secondary-text-color); white-space: nowrap; }
    .opt.none .opt-name { color: var(--secondary-text-color); }
    .copy-row { display: flex; gap: 6px; margin-bottom: 8px; }
    .copy-row .text-btn { flex: 1; font-size: .85em; }
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
      this._weeks = {};
      this._holidays = {};
      this._dialog = null; // {type: "day", key} | {type: "week", monday}
      this._rangeEnd = "";
      this._weekDays = [true, true, true, true, true, false, false];
      this._saving = false;
      this._brush = null; // Schnell eintragen: null = aus, "" = löschen, sonst Kürzel
      this._pending = 0; // laufende Speichervorgänge im Schnell-Modus
      this._queue = Promise.resolve();
      this._paintError = "";
      this._loaded = false;
      this._status = "";
      this._statusSelectable = false;
      this._error = "";
      this._hass = null;
      this._stamp = null;
      this._syncCalendar = null;
      this._icalUrl = null;
      this._serverVersion = null;
    }

    static getConfigElement() {
      return document.createElement("dienstplan-card-editor");
    }

    static getStubConfig(hass) {
      const states = (hass && hass.states) || {};
      const entity = Object.keys(states).find(
        (id) => id.startsWith("calendar.") && states[id].attributes && "today_shift" in states[id].attributes
      );
      return { entity: entity || "calendar.dienstplan", show_times: true };
    }

    getCardSize() {
      return 9;
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
      } else if (stamp && stamp !== this._stamp && !this._saving && !this._pending) {
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

    _fetch(startKey, endKey) {
      return this._hass.callWS({
        type: `${DOMAIN}/get_days`,
        entity_id: this._config.entity,
        start: startKey,
        end: endKey,
      });
    }

    async _load() {
      if (!this._hass || !this._config) return;
      const days = this._gridDays();
      const startKey = iso(days[0]);
      const endKey = iso(days[days.length - 1]);
      try {
        const res = await this._fetch(startKey, endKey);
        if (this._pending) return; // es wird noch gespeichert: der Abschluss lädt den aktuellen Stand selbst
        this._shifts = res.shifts || [];
        this._shiftMap = new Map(this._shifts.map((s) => [s.code.toLowerCase(), s]));
        for (const key of Object.keys(this._days)) {
          if (key >= startKey && key <= endKey) delete this._days[key];
        }
        Object.assign(this._days, res.days || {});
        Object.assign(this._weeks, res.weeks || {});
        this._serverVersion = res.version || null;
        this._syncCalendar = res.sync_calendar || null;
        this._icalUrl = res.ical_url || null;
        this._loaded = true;
        this._error = "";
      } catch (err) {
        this._error = this._loadErrorText(err);
      }
      this._render();
      await this._loadHolidays(days[0], days[days.length - 1]);
    }

    // Klartext statt nackter Fehlercodes: sagt, woran es liegt
    _loadErrorText(err) {
      const code = err && err.code;
      if (code === "unknown_command") {
        return "Die Integration „Dienstplan“ ist nicht geladen. Bitte unter Einstellungen → Geräte & Dienste prüfen und Home Assistant neu starten.";
      }
      if (code === "not_found") {
        return `„${this._config.entity}“ ist kein Dienstplan-Kalender (oder die Integration ist nicht geladen). Bitte die Entität der Karte prüfen.`;
      }
      return (err && err.message) || "Dienstplan konnte nicht geladen werden.";
    }

    async _loadHolidays(first, last) {
      const entity = this._config && this._config.holidays;
      if (!entity || !this._hass || !this._hass.callApi) return;
      try {
        const startIso = new Date(first.getFullYear(), first.getMonth(), first.getDate()).toISOString();
        const endIso = new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1).toISOString();
        const events = await this._hass.callApi(
          "GET",
          `calendars/${entity}?start=${encodeURIComponent(startIso)}&end=${encodeURIComponent(endIso)}`
        );
        for (const key of Object.keys(this._holidays)) {
          if (key >= iso(first) && key <= iso(last)) delete this._holidays[key];
        }
        for (const ev of events || []) {
          const s = (ev.start && (ev.start.date || (ev.start.dateTime || "").slice(0, 10))) || "";
          const e = (ev.end && (ev.end.date || (ev.end.dateTime || "").slice(0, 10))) || s;
          if (!s) continue;
          let d = parseIso(s);
          const stop = parseIso(e);
          do {
            this._holidays[iso(d)] = ev.summary || "Feiertag";
            d = addDays(d, 1);
          } while (d < stop);
        }
        this._render();
      } catch (err) {
        // Feiertage sind optional – Fehler stillschweigend ignorieren
      }
    }

    _colorFor(code) {
      const shift = this._shiftMap.get((code || "").toLowerCase());
      if (shift && shift.color) return shift.color;
      return FALLBACK_COLORS[(code || "?")[0].toUpperCase()] || DEFAULT_COLOR;
    }

    _timeText(shift) {
      let text = shift.kind === "off" ? "kein Termin" : "ganztägig";
      if (shift.start && shift.end) text = `${shift.start}–${shift.end}`;
      if (shift.hours != null) text += ` · ${fmtH(shift.hours)} h`;
      return text;
    }

    // Volle Stunden einzeilig ("6–14"), sonst Beginn/Ende in zwei Zeilen (passt auch in schmale Zellen)
    _cellTime(code) {
      const shift = this._shiftMap.get((code || "").toLowerCase());
      if (!shift || !shift.start || !shift.end) return null;
      if (shift.start.endsWith(":00") && shift.end.endsWith(":00")) {
        return [`${shortTime(shift.start)}–${shortTime(shift.end)}`];
      }
      return [shortTime(shift.start), `–${shortTime(shift.end)}`];
    }

    _shortSpan(shift) {
      return shift.start && shift.end ? `${shortTime(shift.start)}–${shortTime(shift.end)}` : "";
    }

    // Stunden und Dienste des angezeigten Monats (nur aus den geladenen Tagen)
    _monthSummary() {
      const year = this._month.getFullYear();
      const month = this._month.getMonth();
      let hours = 0;
      let work = 0;
      let vacation = 0;
      let missing = false;
      for (const [key, code] of Object.entries(this._days)) {
        const day = parseIso(key);
        if (day.getFullYear() !== year || day.getMonth() !== month) continue;
        const shift = this._shiftMap.get((code || "").toLowerCase());
        if (!shift) continue;
        if (shift.category === "work") {
          work += 1;
          if (shift.hours != null) hours += shift.hours;
          else missing = true;
        } else if (shift.category === "vacation" && day.getDay() % 6 !== 0) {
          vacation += 1; // wie der Sensor: nur Montag bis Freitag
        }
      }
      if (!work && !vacation) return "";
      const parts = [];
      if (work) parts.push(`${fmtH(hours)}${missing ? "*" : ""} h · ${work} ${work === 1 ? "Dienst" : "Dienste"}`);
      if (vacation) parts.push(`${vacation} ${vacation === 1 ? "Urlaubstag" : "Urlaubstage"}`);
      return `${MONTHS[month]}: ${parts.join(" · ")}`;
    }

    // ---------------------------------------------------------------- Aktionen

    _toggleBrush(code) {
      this._brush = this._brush === code ? null : code;
      this._status = "";
      this._error = "";
      this._render();
    }

    _dayTap(key) {
      if (this._brush !== null) this._paint(key);
      else this._openDay(key);
    }

    // Ein Tap = ein Tag. Anzeige sofort, Speichern nacheinander im Hintergrund, am Ende der echte Stand.
    _paint(key) {
      const code = this._brush;
      if (code === null || this._saving || !this._loaded) return;
      if ((this._days[key] || "") === code) return;
      if (code) this._days[key] = code;
      else delete this._days[key];
      this._error = "";
      this._status = "";
      this._pending += 1;
      this._render();
      this._queue = this._queue
        .then(() => this._hass.callService(DOMAIN, "set_shift", { date: key, shift: code }, { entity_id: this._config.entity }))
        .catch((err) => {
          this._paintError = (err && err.message) || "Speichern fehlgeschlagen.";
        })
        .then(async () => {
          this._pending -= 1;
          if (this._pending > 0) return;
          const saveError = this._paintError;
          this._paintError = "";
          await this._load(); // zeigt den tatsächlichen Stand, auch nach einem Fehler
          if (saveError) {
            this._error = saveError;
            this._render();
          }
        });
    }

    _openDay(key) {
      if (this._saving) return;
      if (!this._loaded) {
        this._load(); // erneut versuchen; ein Fehler steht danach unter dem Kalender
        return;
      }
      this._dialog = { type: "day", key };
      this._rangeEnd = "";
      this._status = "";
      this._render();
    }

    _openWeek(monday) {
      if (this._saving) return;
      if (!this._loaded) {
        this._load();
        return;
      }
      this._dialog = { type: "week", monday };
      this._status = "";
      this._render();
    }

    _close() {
      this._dialog = null;
      this._render();
    }

    async _call(service, data, okText) {
      this._dialog = null;
      this._saving = true;
      this._error = "";
      this._statusSelectable = false;
      this._status = "Speichere …";
      this._render();
      let saveError = "";
      try {
        await this._hass.callService(DOMAIN, service, data, { entity_id: this._config.entity });
        this._status = okText;
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

    async _chooseDay(code) {
      const dialog = this._dialog;
      if (!dialog || dialog.type !== "day" || this._saving) return;
      const key = dialog.key;
      const end = this._rangeEnd && this._rangeEnd > key ? this._rangeEnd : "";
      if (!end && code === (this._days[key] || "")) {
        this._close();
        return;
      }
      const data = { date: key, shift: code };
      if (end) data.end_date = end;
      const until = end ? ` bis ${fmtDate(parseIso(end))}` : "";
      await this._call("set_shift", data, code ? `${code} eingetragen${until}.` : `Einträge gelöscht${until}.`);
    }

    async _chooseWeek(code) {
      const dialog = this._dialog;
      if (!dialog || dialog.type !== "week" || this._saving) return;
      const monday = parseIso(dialog.monday);
      const days = {};
      this._weekDays.forEach((on, i) => {
        if (on) days[iso(addDays(monday, i))] = code;
      });
      const count = Object.keys(days).length;
      if (!count) {
        this._status = "Bitte mindestens einen Wochentag markieren.";
        this._render();
        return;
      }
      const text = code ? `${code} für ${count} ${count === 1 ? "Tag" : "Tage"} eingetragen.` : "Einträge gelöscht.";
      await this._call("set_shifts", { days }, text);
    }

    async _copyWeek(direction) {
      const dialog = this._dialog;
      if (!dialog || dialog.type !== "week" || this._saving) return;
      const monday = parseIso(dialog.monday);
      const source = direction < 0 ? addDays(monday, -7) : monday;
      const target = direction < 0 ? monday : addDays(monday, 7);
      let res;
      try {
        res = await this._fetch(iso(source), iso(addDays(source, 6)));
      } catch (err) {
        this._error = (err && err.message) || "Woche konnte nicht gelesen werden.";
        this._render();
        return;
      }
      const days = {};
      for (let i = 0; i < 7; i++) {
        const code = (res.days || {})[iso(addDays(source, i))];
        if (code) days[iso(addDays(target, i))] = code;
      }
      const count = Object.keys(days).length;
      if (!count) {
        this._status = "In der Quellwoche ist nichts eingetragen.";
        this._render();
        return;
      }
      await this._call("set_shifts", { days }, `${count} ${count === 1 ? "Tag" : "Tage"} kopiert.`);
    }

    async _copyLink() {
      const url = this._icalUrl;
      if (!url) return;
      try {
        await navigator.clipboard.writeText(url);
        this._status = "Kalender-Link kopiert. In Google/Apple Kalender als Abo (per URL) hinzufügen.";
        this._statusSelectable = false;
      } catch (err) {
        this._status = url;
        this._statusSelectable = true;
      }
      this._error = "";
      this._render();
    }

    _go(deltaMonths) {
      const m = this._month;
      this._month = new Date(m.getFullYear(), m.getMonth() + deltaMonths, 1);
      this._load();
      this._render();
    }

    // ---------------------------------------------------------------- Darstellung

    _options(current, pick, noneLabel) {
      return h(
        "div",
        { class: "options" },
        this._shifts.map((shift) =>
          h(
            "button",
            {
              class: `opt${current && current.toLowerCase() === shift.code.toLowerCase() ? " selected" : ""}`,
              onclick: () => pick(shift.code),
            },
            h("span", { class: "dot", style: `background:${this._colorFor(shift.code)}` }),
            h("span", { class: "opt-code" }, shift.code),
            h("span", { class: "opt-name" }, shift.name),
            h("span", { class: "opt-time" }, this._timeText(shift))
          )
        ),
        h(
          "button",
          { class: `opt none${current === "" ? " selected" : ""}`, onclick: () => pick("") },
          h("span", { class: "dot", style: "background:transparent;border:2px solid var(--secondary-text-color)" }),
          h("span", { class: "opt-name" }, noneLabel)
        )
      );
    }

    _renderDayDialog() {
      const key = this._dialog.key;
      const date = parseIso(key);
      const current = this._days[key] || "";
      return h(
        "div",
        { class: "dialog", role: "dialog", "aria-label": "Dienst wählen", tabindex: "-1", autofocus: true },
        h(
          "div",
          { class: "dlg-title" },
          `${WEEKDAYS_LONG[mondayOffset(date)]}, ${date.getDate()}. ${MONTHS[date.getMonth()]} ${date.getFullYear()}`
        ),
        this._holidays[key] ? h("div", { class: "dlg-sub" }, this._holidays[key]) : null,
        h(
          "label",
          { class: "range" },
          "Bis einschließlich (optional)",
          h("input", {
            type: "date",
            min: key,
            value: this._rangeEnd,
            onchange: (ev) => {
              this._rangeEnd = ev.target.value || "";
            },
          })
        ),
        this._options(current, (code) => this._chooseDay(code), "Kein Dienst (Eintrag löschen)"),
        h("button", { class: "text-btn", onclick: () => this._close() }, "Abbrechen")
      );
    }

    _renderWeekDialog() {
      const monday = parseIso(this._dialog.monday);
      const sunday = addDays(monday, 6);
      return h(
        "div",
        { class: "dialog", role: "dialog", "aria-label": "Woche bearbeiten", tabindex: "-1", autofocus: true },
        h(
          "div",
          { class: "dlg-title" },
          `KW ${isoWeek(monday)} · ${fmtDate(monday)}–${fmtDate(sunday)}${sunday.getFullYear()}`
        ),
        h("div", { class: "dlg-sub" }, "Gilt für die markierten Wochentage:"),
        h(
          "div",
          { class: "wdchips" },
          WEEKDAYS.map((wd, i) =>
            h(
              "button",
              {
                class: `wdchip${this._weekDays[i] ? " on" : ""}`,
                "aria-pressed": this._weekDays[i] ? "true" : "false",
                onclick: () => {
                  this._weekDays[i] = !this._weekDays[i];
                  this._render();
                },
              },
              wd
            )
          )
        ),
        this._options(undefined, (code) => this._chooseWeek(code), "Kein Dienst (Einträge löschen)"),
        h(
          "div",
          { class: "copy-row" },
          h("button", { class: "text-btn", onclick: () => this._copyWeek(-1) }, "Vorwoche kopieren"),
          h("button", { class: "text-btn", onclick: () => this._copyWeek(1) }, "In nächste Woche kopieren")
        ),
        h("button", { class: "text-btn", onclick: () => this._close() }, "Abbrechen")
      );
    }

    _renderLegend() {
      if (this._config.show_legend === false || !this._shifts.length) return null;
      const chip = (code, dotStyle, label, span, title) =>
        h(
          "button",
          {
            class: `chip${this._brush === code ? " on" : ""}`,
            "aria-pressed": this._brush === code ? "true" : "false",
            title,
            onclick: () => this._toggleBrush(code),
          },
          h("span", { class: "dot", style: dotStyle }),
          label,
          span ? h("small", {}, span) : null
        );
      return h(
        "div",
        { class: "legend" },
        this._shifts.map((shift) =>
          chip(shift.code, `background:${this._colorFor(shift.code)}`, shift.code, this._shortSpan(shift), `${shift.name} – zum Schnell-Eintragen antippen`)
        ),
        chip("", "background:transparent;border:2px solid var(--secondary-text-color)", "Löschen", "", "Einträge löschen – zum Schnell-Löschen antippen")
      );
    }

    _renderKw(monday) {
      const key = iso(monday);
      const stats = this._weeks[key];
      let hoursNode = null;
      let title = `KW ${isoWeek(monday)}`;
      if (stats && (stats.hours || stats.missing)) {
        let cls = "kw-h";
        if (stats.balance != null) cls += stats.balance < -0.01 ? " neg" : stats.balance > 0.01 ? " pos" : "";
        hoursNode = h("span", { class: cls }, `${fmtH(stats.hours)}${stats.missing ? "*" : ""}`);
        title += ` · ${fmtH(stats.hours)} h`;
        if (stats.target != null) {
          const sign = stats.balance > 0 ? "+" : "";
          title += ` · Soll ${fmtH(stats.target)} · Bilanz ${sign}${fmtH(stats.balance)}`;
        }
        if (stats.missing) title += ` · ${stats.missing} Dienst(e) ohne Stunden`;
      }
      return h(
        "button",
        { class: "kw", title, "aria-label": title, onclick: () => this._openWeek(key) },
        h("span", { class: "kw-n" }, `KW${isoWeek(monday)}`),
        hoursNode
      );
    }

    // Karte (Browser, evtl. aus dem Zwischenspeicher) und Integration (Server) haben verschiedene Versionen
    _staleBanner() {
      if (!this._serverVersion || this._serverVersion === CARD_VERSION) return null;
      return h(
        "div",
        { class: "stale", role: "alert" },
        h(
          "span",
          {},
          `Karte (${CARD_VERSION}) und Integration (${this._serverVersion}) passen nicht zusammen. Nach einem Update Home Assistant neu starten, dann hier neu laden.`
        ),
        h("button", { class: "text-btn", onclick: () => hardReload() }, "Neu laden")
      );
    }

    _render() {
      const root = this.shadowRoot;
      if (!root || !this._config) return;
      root.replaceChildren();

      const todayKey = iso(new Date());
      const month = this._month.getMonth();
      const showTimes = this._config.show_times !== false;

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

      const cells = [h("div", { class: "wd" }, "KW"), ...WEEKDAYS.map((wd) => h("div", { class: "wd" }, wd))];
      const gridDays = this._gridDays();
      for (let i = 0; i < gridDays.length; i += 7) {
        cells.push(this._renderKw(gridDays[i]));
        for (const day of gridDays.slice(i, i + 7)) {
          const key = iso(day);
          const code = this._days[key] || "";
          const classes = ["day"];
          if (day.getDay() === 0 || day.getDay() === 6) classes.push("weekend");
          if (day.getMonth() !== month) classes.push("other");
          if (key === todayKey) classes.push("today");
          if (this._holidays[key]) classes.push("holiday");
          const holiday = this._holidays[key] ? ` (${this._holidays[key]})` : "";
          const label = `${day.getDate()}. ${MONTHS[day.getMonth()]}${code ? ", " + code : ""}${holiday}`;
          const time = showTimes && code ? this._cellTime(code) : null;
          cells.push(
            h(
              "button",
              { class: classes.join(" "), title: this._holidays[key] || null, "aria-label": label, onclick: () => this._dayTap(key) },
              h("span", { class: "num" }, day.getDate()),
              code ? h("span", { class: "badge", style: `background:${this._colorFor(code)}` }, code) : null,
              time ? time.map((line) => h("span", { class: "time" }, line)) : null
            )
          );
        }
      }
      const grid = h("div", { class: "grid" }, cells);

      // Wischen wechselt den Monat
      let startX = 0;
      let startY = 0;
      grid.addEventListener(
        "touchstart",
        (ev) => {
          const t = ev.touches[0];
          startX = t.clientX;
          startY = t.clientY;
        },
        { passive: true }
      );
      grid.addEventListener("touchend", (ev) => {
        const t = ev.changedTouches[0];
        const dx = t.clientX - startX;
        const dy = t.clientY - startY;
        if (Math.abs(dx) > 60 && Math.abs(dy) < 40) this._go(dx < 0 ? 1 : -1);
      });

      const summaryText = this._monthSummary();
      let statusText = this._error || this._status;
      if (!statusText && this._brush !== null) {
        statusText = this._brush
          ? `Schnell eintragen: „${this._brush}“ – Tage antippen. Kürzel nochmal antippen zum Beenden.`
          : "Schnell löschen – Tage antippen. „Löschen“ nochmal antippen zum Beenden.";
      }
      if (!statusText && !this._loaded) statusText = "Lade …";
      if (!statusText && this._syncCalendar) statusText = `Termine werden auch nach ${this._syncCalendar} übertragen.`;
      const footer = h(
        "div",
        { class: "footer" },
        statusText
          ? h("div", { class: `status${this._error ? " error" : ""}${this._statusSelectable && !this._error ? " selectable" : ""}` }, statusText)
          : null,
        this._icalUrl ? h("button", { class: "text-btn link-btn", onclick: () => this._copyLink() }, "Kalender-Link") : null
      );

      const dialog = this._dialog
        ? h(
            "dialog",
            {
              class: "overlay",
              // Klick auf den abgedunkelten Hintergrund (Ziel ist das <dialog> selbst) schließt
              onclick: (ev) => {
                if (ev.target === ev.currentTarget) this._close();
              },
              // Esc / Zurück-Geste: selbst schließen, damit der Zustand der Karte stimmt
              oncancel: (ev) => {
                ev.preventDefault();
                this._close();
              },
            },
            this._dialog.type === "week" ? this._renderWeekDialog() : this._renderDayDialog()
          )
        : null;

      root.append(
        h("style", {}, STYLE),
        h(
          "ha-card",
          { class: this._brush !== null ? "brushing" : null },
          this._staleBanner(),
          this._config.title ? h("div", { class: "title" }, this._config.title) : null,
          nav,
          grid,
          this._renderLegend(),
          summaryText ? h("div", { class: "summary" }, summaryText) : null,
          footer,
          dialog
        )
      );

      if (dialog) {
        try {
          dialog.showModal();
        } catch (err) {
          // Karte (noch) nicht im DOM oder sehr alter Browser: ohne Modal-Ebene anzeigen
          dialog.setAttribute("open", "");
        }
      }
    }
  }

  // ------------------------------------------------------------------ Grafischer Editor

  const EDITOR_SCHEMA = [
    { name: "entity", required: true, selector: { entity: { domain: "calendar" } } },
    { name: "title", selector: { text: {} } },
    { name: "show_times", selector: { boolean: {} } },
    { name: "show_legend", selector: { boolean: {} } },
    { name: "holidays", selector: { entity: { domain: "calendar" } } },
  ];
  const EDITOR_LABELS = {
    entity: "Dienstplan-Kalender",
    title: "Titel (optional)",
    show_times: "Uhrzeiten in den Tagen anzeigen",
    show_legend: "Legende anzeigen (Schnell eintragen)",
    holidays: "Feiertagskalender (optional)",
  };

  class DienstplanCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = { show_times: true, show_legend: true, ...config };
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._form) this._form.hass = hass;
    }

    _render() {
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.computeLabel = (schema) => EDITOR_LABELS[schema.name] || schema.name;
        this._form.addEventListener("value-changed", (ev) => {
          this._config = ev.detail.value;
          this.dispatchEvent(
            new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true })
          );
        });
        this.append(this._form);
      }
      this._form.hass = this._hass;
      this._form.schema = EDITOR_SCHEMA;
      this._form.data = this._config;
    }
  }

  // ------------------------------------------------------------------ Seite in der Seitenleiste

  // Eigene Seite „Dienstplan“: Home Assistant lädt dieses Modul beim Öffnen selbst. Sie funktioniert daher auch dann,
  // wenn die Karte im Dashboard (noch) nicht bereitsteht.
  const PANEL_STYLE = `
    :host { display: block; min-height: 100vh; box-sizing: border-box; background: var(--primary-background-color); }
    header {
      display: flex; align-items: center; gap: 8px; box-sizing: border-box; min-height: 56px;
      padding: env(safe-area-inset-top, 0) 12px 0 4px;
      background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff);
    }
    header h1 { flex: 1; margin: 0; font-size: 1.15em; font-weight: 500; }
    header select {
      max-width: 55%; padding: 6px 8px; border-radius: 6px; font: inherit;
      color: var(--primary-text-color); background: var(--card-background-color, #fff); border: 1px solid var(--divider-color);
    }
    .menu {
      width: 44px; height: 44px; border: 0; border-radius: 50%; background: transparent; color: inherit;
      cursor: pointer; display: grid; place-items: center;
    }
    .menu svg { width: 24px; height: 24px; fill: currentColor; }
    main { max-width: 640px; margin: 0 auto; padding: 12px; box-sizing: border-box; }
    .empty { padding: 24px 8px; text-align: center; color: var(--secondary-text-color); line-height: 1.5; }
  `;
  const MENU_PATH = "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z";

  class DienstplanPanel extends HTMLElement {
    constructor() {
      super();
      this._hass = null;
      this._narrow = false;
      this._entity = null;
      this._listKey = null;
      this._card = null;
      this.attachShadow({ mode: "open" });
    }

    set hass(hass) {
      this._hass = hass;
      this._update();
    }

    set narrow(value) {
      this._narrow = !!value;
      if (this._menu) this._menu.style.display = this._narrow ? "" : "none";
    }

    set route(_value) {}

    set panel(_value) {}

    // Alle Dienstplan-Kalender (Entitäten dieser Integration)
    _entities() {
      const hass = this._hass;
      if (!hass) return [];
      const registry = hass.entities || {};
      const ids = Object.keys(hass.states || {}).filter((id) => {
        if (!id.startsWith("calendar.")) return false;
        const entry = registry[id];
        if (entry && entry.platform) return entry.platform === DOMAIN;
        const attributes = hass.states[id].attributes || {};
        return "today_shift" in attributes; // Ersatz, falls die Registry nicht mitgeliefert wird
      });
      return ids.sort();
    }

    _update() {
      if (!this._hass) return;
      const ids = this._entities();
      const key = ids.join("|");
      if (key !== this._listKey) {
        this._listKey = key;
        if (!ids.includes(this._entity)) this._entity = ids[0] || null;
        this._build(ids);
      }
      if (this._card) this._card.hass = this._hass;
    }

    _build(ids) {
      const hass = this._hass;
      const root = this.shadowRoot;
      root.replaceChildren();
      this._card = null;

      const name = (id) => (hass.states[id] && hass.states[id].attributes.friendly_name) || id;
      const menu = h(
        "button",
        {
          class: "menu",
          "aria-label": "Menü",
          onclick: () =>
            this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true, detail: {} })),
        },
        (() => {
          const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          svg.setAttribute("viewBox", "0 0 24 24");
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute("d", MENU_PATH);
          svg.append(path);
          return svg;
        })()
      );
      menu.style.display = this._narrow ? "" : "none";
      this._menu = menu;

      const picker =
        ids.length > 1
          ? h(
              "select",
              {
                "aria-label": "Dienstplan wählen",
                onchange: (ev) => {
                  this._entity = ev.target.value;
                  this._build(ids);
                  this._update();
                },
              },
              ids.map((id) => h("option", { value: id, selected: id === this._entity }, name(id)))
            )
          : null;

      let content;
      if (this._entity) {
        this._card = document.createElement("dienstplan-card");
        this._card.setConfig({ type: "custom:dienstplan-card", entity: this._entity, show_times: true });
        content = this._card;
      } else {
        content = h(
          "div",
          { class: "empty" },
          "Noch kein Dienstplan eingerichtet. Bitte unter Einstellungen → Geräte & Dienste → „Dienstplan“ hinzufügen."
        );
      }

      root.append(h("style", {}, PANEL_STYLE), h("header", {}, menu, h("h1", {}, "Dienstplan"), picker), h("main", {}, content));
    }
  }

  // Aufräumen ist Sache des Nutzers: bei Bedarf Zwischenspeicher leeren und neu laden (Knopf auf der Karte)
  async function hardReload() {
    try {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((registration) => registration.unregister()));
    } catch (err) {
      // kein Service Worker: nichts zu tun
    }
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    } catch (err) {
      // kein Zwischenspeicher: nichts zu tun
    }
    location.reload();
  }

  if (!customElements.get("dienstplan-card")) {
    customElements.define("dienstplan-card", DienstplanCard);
  }
  if (!customElements.get("dienstplan-card-editor")) {
    customElements.define("dienstplan-card-editor", DienstplanCardEditor);
  }
  if (!customElements.get("dienstplan-panel")) {
    customElements.define("dienstplan-panel", DienstplanPanel);
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === "dienstplan-card")) {
    window.customCards.push({
      type: "dienstplan-card",
      name: "Dienstplan",
      description: "Monatsansicht: Tag antippen, Schicht wählen – erzeugt Kalendertermine.",
    });
  }
  console.info(`%c DIENSTPLAN %c ${CARD_VERSION} `, "color:#fff;background:#3f51b5;font-weight:700", "color:#3f51b5");
});
