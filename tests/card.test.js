// Testet die Dienstplan-Karte ohne Browser (Mini-DOM). Aufruf: node tests/card.test.js
const assert = require("assert");
const path = require("path");

class N {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.style = {};
    this.className = "";
    this.disabled = false;
    this.nodeType = 1;
  }
  append(...c) { this.children.push(...c); }
  replaceChildren() { this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(e, f) { this.listeners[e] = f; }
  dispatchEvent(ev) { (this.listeners[ev.type] || (() => {}))(ev); }
  showModal() {
    if (this.tag !== "dialog") throw new Error("showModal nur auf <dialog>");
    this.modal = true;
    this.attrs.open = "";
  }
}
global.window = global;
global.document = { createElement: (t) => new N(t), createTextNode: (s) => ({ nodeType: 3, text: s }) };
global.HTMLElement = class extends N {
  constructor() { super("host"); }
  attachShadow() { this.shadowRoot = new N("shadow"); return this.shadowRoot; }
};
global.customElements = { _m: {}, get(n) { return this._m[n]; }, define(n, c) { this._m[n] = c; } };
const setNavigator = (value) => Object.defineProperty(globalThis, "navigator", { value, configurable: true });
require(path.join(__dirname, "..", "custom_components", "dienstplan", "frontend", "dienstplan-card.js"));

const text = (n) => (n.nodeType === 3 ? n.text : n.children.map(text).join(""));
const all = (n, out = []) => { out.push(n); (n.children || []).forEach((c) => all(c, out)); return out; };
const find = (root, pred) => all(root).find(pred);
const btn = (root, pred) => find(root, (n) => n.tag === "button" && pred(n));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0)); };

const SHIFTS = [
  { code: "F1", name: "Frühdienst 1", start: "06:30", end: "13:00", kind: "timed", category: "work", color: null, hours: 6.5 },
  { code: "S1", name: "Spätdienst 1", start: "13:30", end: "20:00", kind: "timed", category: "work", color: "#123456", hours: 6.5 },
  { code: "U", name: "Urlaub", start: null, end: null, kind: "allday", category: "vacation", color: null, hours: null },
  { code: "X", name: "Frei", start: null, end: null, kind: "off", category: "off", color: null, hours: null },
];

function setup(config = {}, extra = {}) {
  const calls = [];
  const server = { "2026-09-28": "F1", "2026-09-21": "F1", "2026-09-23": "S1" };
  const hass = {
    states: { "calendar.jenny": { last_updated: "1", attributes: { today_shift: null } } },
    callWS: async (msg) => {
      calls.push(["ws", msg]);
      const days = {};
      for (const [k, v] of Object.entries(server)) if (k >= msg.start && k <= msg.end) days[k] = v;
      return {
        shifts: SHIFTS,
        days,
        weeks: {
          "2026-09-28": { hours: 38.5, target: 38.5, balance: 0, missing: 0 },
          "2026-09-21": { hours: 30, target: 38.5, balance: -8.5, missing: 1 },
        },
        sync_calendar: extra.sync || null,
        ical_url: extra.ical === undefined ? "https://ha.example/api/dienstplan/feed/e1/tok/calendar.ics" : extra.ical,
      };
    },
    callService: async (d, s, data, t) => {
      calls.push(["svc", d, s, data, t]);
      if (extra.fail) throw new Error("Unbekannter Dienst „Q“");
      if (s === "set_shift") {
        const from = new Date(data.date + "T00:00:00Z");
        const to = new Date((data.end_date || data.date) + "T00:00:00Z");
        for (let d2 = from; d2 <= to; d2 = new Date(d2.getTime() + 86400000)) {
          const key = d2.toISOString().slice(0, 10);
          if (data.shift) server[key] = data.shift; else delete server[key];
        }
      } else {
        for (const [k, v] of Object.entries(data.days)) if (v) server[k] = v; else delete server[k];
      }
    },
  };
  if (extra.holidays) hass.callApi = async (m, p) => { calls.push(["api", m, p]); return extra.holidays; };
  const Card = customElements.get("dienstplan-card");
  const card = new Card();
  card.setConfig({ entity: "calendar.jenny", ...config });
  card._month = new Date(2026, 8, 1);
  return { card, hass, calls, server, root: () => card.shadowRoot, svc: () => calls.filter((c) => c[0] === "svc") };
}
const cellByLabel = (root, prefix) => btn(root, (n) => (n.attrs["aria-label"] || "").startsWith(prefix));
const overlay = (root) => find(root, (n) => n.className === "overlay");
const option = (root, label) => btn(overlay(root), (n) => n.className.includes("opt") && text(n).includes(label));

(async () => {
  const Card = customElements.get("dienstplan-card");
  assert.throws(() => new Card().setConfig({}), /entity/);
  assert.throws(() => new Card().setConfig({ entity: "sensor.x" }), /entity/);

  // ---------- Laden, KW-Spalte, Zeiten
  {
    const { card, hass, calls, root } = setup({ title: "Dienstplan Jenny" }, { sync: "calendar.google" });
    card.hass = hass;
    await settle();
    assert.strictEqual(calls[0][1].start, "2026-08-31");
    assert.strictEqual(calls[0][1].end, "2026-10-04");
    const t = text(root());
    assert.ok(t.includes("September 2026") && t.includes("Dienstplan Jenny") && t.includes("calendar.google"));
    const kws = all(root()).filter((n) => n.className === "kw").map((n) => text(n));
    assert.deepStrictEqual(kws.map((s) => s.slice(0, 4)), ["KW36", "KW37", "KW38", "KW39", "KW40"]);
    assert.ok(kws[4].includes("38,5") && !kws[4].includes("*"));
    assert.ok(kws[3].includes("30*"), "fehlende Stunden werden mit * markiert");
    const kw39 = all(root()).filter((n) => n.className === "kw")[3];
    assert.ok(all(kw39).some((n) => n.className === "kw-h neg"), "negative Bilanz rot");
    const kw40 = all(root()).filter((n) => n.className === "kw")[4];
    assert.ok(all(kw40).some((n) => n.className === "kw-h"), "ausgeglichene Bilanz neutral");
    const f1 = cellByLabel(root(), "28. September, F1");
    assert.ok(f1 && text(f1).includes("6:30–13"), "Uhrzeit in der Zelle");
    assert.strictEqual(overlay(root()), undefined);
  }
  {
    const { card, hass, root } = setup({ show_times: false });
    card.hass = hass;
    await settle();
    assert.ok(!text(cellByLabel(root(), "28. September, F1")).includes("6:30"), "show_times: false blendet Zeiten aus");
  }

  // ---------- Tages-Dialog: einzelner Tag, Zeitraum, Löschen
  {
    const { card, hass, root, svc } = setup();
    card.hass = hass;
    await settle();
    cellByLabel(root(), "29. September").listeners.click();
    const dlg = text(overlay(root()));
    for (const s of ["Dienstag, 29. September 2026", "06:30–13:00 · 6,5 h", "Urlaub", "ganztägig", "kein Termin", "Kein Dienst"]) assert.ok(dlg.includes(s), s);
    assert.ok(find(overlay(root()), (n) => n.tag === "input" && n.attrs.type === "date" && n.attrs.min === "2026-09-29"));
    assert.ok(option(root(), "Kein Dienst").className.includes("selected"));
    option(root(), "Frühdienst 1").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[0].slice(1), ["dienstplan", "set_shift", { date: "2026-09-29", shift: "F1" }, { entity_id: "calendar.jenny" }]);
    assert.strictEqual(overlay(root()), undefined);
    assert.ok(cellByLabel(root(), "29. September, F1"));
    assert.ok(text(root()).includes("F1 eingetragen."));

    // gleiche Auswahl speichert nichts
    cellByLabel(root(), "29. September").listeners.click();
    assert.ok(option(root(), "Frühdienst 1").className.includes("selected"));
    option(root(), "Frühdienst 1").listeners.click();
    await settle();
    assert.strictEqual(svc().length, 1);

    // Zeitraum bis einschließlich
    cellByLabel(root(), "30. September").listeners.click();
    find(overlay(root()), (n) => n.tag === "input").listeners.change({ target: { value: "2026-10-02" } });
    option(root(), "Spätdienst 1").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[1][3], { date: "2026-09-30", shift: "S1", end_date: "2026-10-02" });
    assert.ok(text(root()).includes("S1 eingetragen bis 02.10."));
    assert.ok(cellByLabel(root(), "1. Oktober, S1") && cellByLabel(root(), "2. Oktober, S1"));

    // Enddatum vor/gleich Start wird ignoriert; Rest bleibt einzelner Tag
    cellByLabel(root(), "3. Oktober").listeners.click();
    find(overlay(root()), (n) => n.tag === "input").listeners.change({ target: { value: "2026-10-01" } });
    option(root(), "Urlaub").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[2][3], { date: "2026-10-03", shift: "U" });

    // Löschen
    cellByLabel(root(), "28. September").listeners.click();
    option(root(), "Kein Dienst").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[3][3], { date: "2026-09-28", shift: "" });
    assert.ok(!(cellByLabel(root(), "28. September").attrs["aria-label"]).includes("F1"));

    // Abbrechen / Hintergrund
    cellByLabel(root(), "4. Oktober").listeners.click();
    btn(overlay(root()), (n) => text(n) === "Abbrechen").listeners.click();
    assert.strictEqual(overlay(root()), undefined);
    cellByLabel(root(), "4. Oktober").listeners.click();
    const ov = overlay(root());
    ov.listeners.click({ target: {}, currentTarget: ov });
    assert.ok(overlay(root()), "Klick im Fenster schließt nicht");
    ov.listeners.click({ target: ov, currentTarget: ov });
    assert.strictEqual(overlay(root()), undefined);
    assert.strictEqual(svc().length, 4);
  }

  // ---------- Wochen-Dialog
  {
    const { card, hass, root, svc } = setup();
    card.hass = hass;
    await settle();
    const kw40 = all(root()).filter((n) => n.className === "kw")[4];
    kw40.listeners.click();
    let dlg = text(overlay(root()));
    assert.ok(dlg.includes("KW 40 · 28.09.–04.10.2026"), dlg.slice(0, 60));
    const chips = () => all(overlay(root())).filter((n) => /^wdchip( on)?$/.test(n.className));
    assert.deepStrictEqual(chips().map((n) => n.className.includes(" on")), [true, true, true, true, true, false, false]);
    option(root(), "Frühdienst 1").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[0].slice(2, 4), ["set_shifts", { days: {
      "2026-09-28": "F1", "2026-09-29": "F1", "2026-09-30": "F1", "2026-10-01": "F1", "2026-10-02": "F1" } }]);
    assert.ok(text(root()).includes("F1 für 5 Tage eingetragen."));

    // Samstag dazu (Auswahl bleibt für die nächste Öffnung erhalten)
    all(root()).filter((n) => n.className === "kw")[4].listeners.click();
    chips()[5].listeners.click();
    assert.ok(chips()[5].className.includes(" on") && chips()[5].attrs["aria-pressed"] === "true");
    option(root(), "Urlaub").listeners.click();
    await settle();
    assert.strictEqual(Object.keys(svc()[1][3].days).length, 6);
    assert.strictEqual(svc()[1][3].days["2026-10-03"], "U");

    // Alle Wochentage abwählen -> Hinweis, kein Service-Aufruf, Fenster bleibt offen
    all(root()).filter((n) => n.className === "kw")[4].listeners.click();
    chips().forEach((c, i) => { if (c.className.includes(" on")) chips()[i].listeners.click(); });
    option(root(), "Frühdienst 1").listeners.click();
    await settle();
    assert.ok(text(root()).includes("mindestens einen Wochentag"));
    assert.ok(overlay(root()));
    assert.strictEqual(svc().length, 2);

    // Löschen der markierten Tage
    chips()[0].listeners.click();
    option(root(), "Kein Dienst").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[2][3], { days: { "2026-09-28": "" } });
  }

  // ---------- Woche kopieren (ohne Vorhandenes zu löschen)
  {
    const { card, hass, root, svc, server } = setup();
    card.hass = hass;
    await settle();
    const kw40 = () => all(root()).filter((n) => n.className === "kw")[4];
    kw40().listeners.click();
    btn(overlay(root()), (n) => text(n) === "Vorwoche kopieren").listeners.click();
    await settle();
    // Vorwoche (21.09.): Mo F1, Mi S1 -> 28.09. und 30.09.
    assert.deepStrictEqual(svc()[0].slice(2, 4), ["set_shifts", { days: { "2026-09-28": "F1", "2026-09-30": "S1" } }]);
    assert.strictEqual(server["2026-09-28"], "F1");
    assert.ok(text(root()).includes("2 Tage kopiert."));

    kw40().listeners.click();
    btn(overlay(root()), (n) => text(n) === "In nächste Woche kopieren").listeners.click();
    await settle();
    assert.deepStrictEqual(svc()[1][3], { days: { "2026-10-05": "F1", "2026-10-07": "S1" } });

    // leere Quellwoche
    card._month = new Date(2026, 9, 1);
    await card._load();
    const rows = all(root()).filter((n) => n.className === "kw");
    rows[rows.length - 1].listeners.click(); // KW 44 (26.10.) – Vorwoche ist leer
    btn(overlay(root()), (n) => text(n) === "Vorwoche kopieren").listeners.click();
    await settle();
    assert.ok(text(root()).includes("nichts eingetragen"));
    assert.strictEqual(svc().length, 2);
  }

  // ---------- Dialog ist ein natives <dialog> in der Modal-Ebene (wird nie von Karte/Section beschnitten)
  {
    const { card, hass, root } = setup();
    card.hass = hass;
    await settle();
    cellByLabel(root(), "2. Oktober").listeners.click();
    const dlg = overlay(root());
    assert.strictEqual(dlg.tag, "dialog");
    assert.strictEqual(dlg.modal, true, "showModal() wurde aufgerufen");
    // Esc / Zurück-Geste schließt und verhindert das Standard-Schließen des Browsers
    let prevented = false;
    dlg.listeners.cancel({ preventDefault: () => { prevented = true; } });
    assert.ok(prevented);
    assert.strictEqual(overlay(root()), undefined);
    // Wochen-Dialog ebenso
    all(root()).filter((n) => n.className === "kw")[1].listeners.click();
    assert.strictEqual(overlay(root()).tag, "dialog");
    assert.strictEqual(overlay(root()).modal, true);
  }
  {
    // Ohne showModal (sehr alter Browser / nicht im DOM) wird der Dialog trotzdem angezeigt
    const { card, hass, root } = setup();
    card.hass = hass;
    await settle();
    const proto = Object.getPrototypeOf(root());
    const orig = proto.showModal;
    proto.showModal = function () { throw new Error("InvalidStateError"); };
    try {
      cellByLabel(root(), "2. Oktober").listeners.click();
      assert.strictEqual(overlay(root()).attrs.open, "", "Fallback setzt open");
    } finally {
      proto.showModal = orig;
    }
  }

  // ---------- Ladefehler: Klartext, Tippen versucht es erneut
  {
    const { card, hass, root, calls } = setup();
    hass.callWS = async (msg) => { calls.push(["ws", msg]); throw { code: "unknown_command", message: "Unknown command." }; };
    card.hass = hass;
    await settle();
    assert.ok(text(root()).includes("Integration „Dienstplan“ ist nicht geladen"), text(root()));
    assert.ok(find(root(), (n) => n.className === "status error"));
    const before = calls.length;
    cellByLabel(root(), "2. Oktober").listeners.click(); // Tippen: erneut laden statt still nichts tun
    await settle();
    assert.ok(calls.length > before, "erneuter Ladeversuch");
    assert.strictEqual(overlay(root()), undefined, "ohne Daten kein Dialog");
  }
  {
    const { card, hass, root } = setup();
    hass.callWS = async () => { throw { code: "not_found", message: "Dienstplan-Kalender nicht gefunden" }; };
    card.hass = hass;
    await settle();
    assert.ok(text(root()).includes("ist kein Dienstplan-Kalender") && text(root()).includes("calendar.jenny"), text(root()));
  }

  // ---------- Feiertage
  {
    const holidays = [{ start: { date: "2026-10-03" }, end: { date: "2026-10-04" }, summary: "Tag der Deutschen Einheit" }];
    const { card, hass, root, calls } = setup({ holidays: "calendar.feiertage" }, { holidays });
    card.hass = hass;
    await settle();
    const api = calls.find((c) => c[0] === "api");
    assert.ok(api && api[1] === "GET" && api[2].startsWith("calendars/calendar.feiertage?start="), api && api[2]);
    const cell = cellByLabel(root(), "3. Oktober");
    assert.ok(cell.className.includes("holiday") && cell.attrs["aria-label"].includes("Tag der Deutschen Einheit"));
    assert.ok(!cellByLabel(root(), "2. Oktober").className.includes("holiday"), "nur das Ende exklusiv");
    cell.listeners.click();
    assert.ok(text(overlay(root())).includes("Tag der Deutschen Einheit"), "Name im Tages-Dialog");
  }
  {
    const { card, hass, root } = setup({ holidays: "calendar.kaputt" }, {});
    hass.callApi = async () => { throw new Error("404"); };
    card.hass = hass;
    await settle();
    assert.ok(cellByLabel(root(), "3. Oktober") && !text(root()).includes("404"), "Fehler bei Feiertagen bleiben unsichtbar");
  }

  // ---------- Wischen
  {
    const { card, hass, root, calls } = setup();
    card.hass = hass;
    await settle();
    const grid = () => find(root(), (n) => n.className === "grid");
    const swipe = (x0, y0, x1, y1) => {
      grid().listeners.touchstart({ touches: [{ clientX: x0, clientY: y0 }] });
      grid().listeners.touchend({ changedTouches: [{ clientX: x1, clientY: y1 }] });
    };
    swipe(300, 100, 320, 105); // zu kurz
    swipe(300, 100, 150, 200); // zu schräg
    await settle();
    assert.ok(text(root()).includes("September 2026"));
    swipe(300, 100, 200, 110); // nach links -> nächster Monat
    await settle();
    assert.ok(text(root()).includes("Oktober 2026"));
    assert.strictEqual(calls[calls.length - 1][1].start, "2026-09-28");
    swipe(100, 100, 220, 90); // nach rechts -> zurück
    await settle();
    assert.ok(text(root()).includes("September 2026"));
    btn(root(), (n) => n.attrs["aria-label"] === "Nächster Monat").listeners.click();
    await settle();
    assert.ok(text(root()).includes("Oktober 2026"));
  }

  // ---------- Fehler beim Speichern
  {
    const { card, hass, root, svc } = setup({}, { fail: true });
    card.hass = hass;
    await settle();
    cellByLabel(root(), "2. Oktober").listeners.click();
    option(root(), "Frühdienst 1").listeners.click();
    await settle();
    assert.ok(text(root()).includes("Unbekannter Dienst"));
    assert.ok(find(root(), (n) => n.className === "status error"));
    assert.strictEqual(overlay(root()), undefined);
    assert.strictEqual(svc().length, 1);
  }

  // ---------- Kalender-Link
  {
    const { card, hass, root } = setup();
    setNavigator({}); // keine Zwischenablage -> Link wird angezeigt
    card.hass = hass;
    await settle();
    btn(root(), (n) => text(n) === "Kalender-Link").listeners.click();
    await settle();
    const status = find(root(), (n) => typeof n.className === "string" && n.className.startsWith("status"));
    assert.ok(text(status).includes("https://ha.example/api/dienstplan/feed/e1/tok/calendar.ics") && status.className.includes("selectable"));

    let copied = "";
    setNavigator({ clipboard: { writeText: async (s) => { copied = s; } } });
    btn(root(), (n) => text(n) === "Kalender-Link").listeners.click();
    await settle();
    assert.strictEqual(copied, "https://ha.example/api/dienstplan/feed/e1/tok/calendar.ics");
    assert.ok(text(root()).includes("Kalender-Link kopiert"));
  }
  {
    const { card, hass, root } = setup({}, { ical: null });
    card.hass = hass;
    await settle();
    assert.ok(!btn(root(), (n) => text(n) === "Kalender-Link"), "ohne Link kein Button");
  }

  // ---------- Editor und Stub-Konfiguration
  {
    assert.deepStrictEqual(Card.getStubConfig({ states: {} }), { entity: "calendar.dienstplan", show_times: true });
    assert.deepStrictEqual(
      Card.getStubConfig({ states: { "calendar.privat": { attributes: {} }, "calendar.jenny": { attributes: { today_shift: "F1" } } } }),
      { entity: "calendar.jenny", show_times: true }
    );
    assert.strictEqual(Card.getConfigElement().tag, "dienstplan-card-editor");

    const Editor = customElements.get("dienstplan-card-editor");
    const editor = new Editor();
    const events = [];
    editor.addEventListener("config-changed", (ev) => events.push(ev.detail.config));
    editor.hass = { states: {} };
    editor.setConfig({ entity: "calendar.jenny" });
    const form = editor.children[0];
    assert.strictEqual(form.tag, "ha-form");
    assert.deepStrictEqual(form.schema.map((s) => s.name), ["entity", "title", "show_times", "holidays"]);
    assert.deepStrictEqual(form.data, { show_times: true, entity: "calendar.jenny" });
    assert.strictEqual(form.computeLabel({ name: "holidays" }), "Feiertagskalender (optional)");
    form.listeners["value-changed"]({ detail: { value: { entity: "calendar.jenny", show_times: false } } });
    assert.deepStrictEqual(events, [{ entity: "calendar.jenny", show_times: false }]);
  }

  console.log("Karte: alle Prüfungen bestanden");
})().catch((e) => { console.error(e); process.exit(1); });
