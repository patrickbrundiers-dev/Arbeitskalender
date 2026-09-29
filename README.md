# Dienstplan für Home Assistant

Dienste (Früh, Spät, Nacht …) pro Tag in einer Monatsansicht eintragen – daraus entstehen automatisch Kalendertermine.

- **Kalender** pro Person (`calendar.<name>_dienstplan`), sichtbar im HA-Kalender
- **Karte**: Tag antippen → Schicht wählen (auch für einen Zeitraum), **Kürzel in der Legende antippen → „Schnell eintragen“ (ein Tap pro Tag)**, Woche antippen → mehrere Tage auf einmal setzen oder Woche kopieren, Monatssumme, Wischen wechselt den Monat, Feiertage markiert
- **Abgleich** in einen anderen Kalender (Google, lokaler Kalender, CalDAV …); geänderte Uhrzeiten werden automatisch nachgezogen
- **Kalender-Link (iCal)** zum Abonnieren in Google/Apple/Outlook, ohne dass Home Assistant dafür einen Kalender-Zugang braucht
- **Stunden und Bilanz**: Wochenstunden, Soll/Ist, Urlaubstage und Resturlaub
- **Sensoren** für Automationen: Dienst heute/morgen, nächster Dienstbeginn (z. B. für den Wecker)
- Nachtdienste über Mitternacht, Urlaub/Krank als Ganztagstermin, freie Tage ohne Termin

## Installation

**HACS:** In HACS oben rechts (⋮) *Benutzerdefinierte Repositories* öffnen, `https://github.com/patrickbrundiers-dev/Arbeitskalender` mit Typ *Integration* hinzufügen, „Dienstplan“ herunterladen, Home Assistant neu starten.

**Manuell:** Ordner `custom_components/dienstplan` nach `config/custom_components/` kopieren, neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → Dienstplan*. Voraussetzung: Home Assistant 2024.11 oder neuer.

## Dienste festlegen

Ein Dienst pro Zeile: `Code;Name;Start;Ende;Typ;Farbe;Std`

| Feld | Bedeutung |
|------|-----------|
| Code | Kürzel wie im Dienstplan, z. B. `F1`, `S2`, `N1`, `U` |
| Name | Titel des Kalendertermins |
| Start / Ende | `HH:MM`. Ende früher als Start = Dienst endet am Folgetag. Beide leer = Ganztagstermin |
| Typ | leer = Dienst, `urlaub` = Ganztagstermin und zählt als Urlaubstag, `abwesend` = Ganztagstermin (z. B. Krank), `frei` = **kein** Termin |
| Farbe | optional `#RRGGBB` für die Karte |
| Std | optional: bezahlte Stunden (z. B. `6,5`). Ohne Angabe: Dauer von Start bis Ende, ohne Pausenabzug |

```
F1;Frühdienst 1;06:30;13:00;;;6,5
N1;Nachtdienst 1;21:00;06:00
F;Frühdienst
U;Urlaub;;;urlaub
K;Krank;;;abwesend
X;Frei;;;frei
```

> **Wichtig:** Die mitgelieferten Dienste stammen aus einem unscharfen Foto der Legende. Sicher lesbar waren nur die Stunden (F1 6,5 / F2 6 / F3 4 und S1 6,5 / S2 6 / S3 4). Die Uhrzeiten sind daraus abgeleitet und **müssen mit dem Aushang abgeglichen werden**. Dienste ohne Uhrzeit (`F`, `S`, `F4`, `S4`) erzeugen zunächst Ganztagstermine. Weitere Dienste (Zwischen- und Nachtdienste) einfach als neue Zeile ergänzen.

Optional bei der Einrichtung: **Wochensoll** (für die Bilanz), **Urlaubstage pro Jahr** (für den Resturlaub) und ein **Ziel-Kalender** für den Abgleich. Alles lässt sich später unter *Konfigurieren* ändern.

## Karte

Wird von der Integration automatisch bereitgestellt. Im Dashboard *Karte hinzufügen → Dienstplan* (mit grafischem Editor) oder per YAML:

```yaml
type: custom:dienstplan-card
entity: calendar.jenny_dienstplan
title: Dienstplan Jenny
show_times: true                  # optional: Uhrzeiten in den Tagen (Standard: an)
show_legend: true                 # optional: Legende / Schnell eintragen (Standard: an)
holidays: calendar.deutschland    # optional: Feiertagskalender
```

- **Tag antippen:** Schicht wählen; es wird sofort gespeichert. Mit *Bis einschließlich* trägst du einen ganzen Zeitraum ein. *Kein Dienst* löscht den Eintrag.
- **Schnell eintragen:** Unter dem Kalender steht die Legende mit allen Diensten und ihren Zeiten. Ein Kürzel antippen (Karte bekommt einen Rahmen), dann nacheinander die Tage antippen – jeder Tap setzt sofort den Dienst. *Löschen* in der Legende entfernt Einträge auf dieselbe Art. Dasselbe Kürzel nochmal antippen beendet den Modus. Passt gut, um eine Zeile vom Aushang abzutippen.
- **Monatssumme:** unter der Legende, z. B. „September: 48 h · 6 Dienste · 2 Urlaubstage“ (Urlaub nur Mo–Fr; `*` = Dienst ohne bekannte Stunden).
- **KW-Zelle antippen:** Wochentage markieren (Standard Mo–Fr) und eine Schicht wählen, oder die Woche aus der Vorwoche bzw. in die nächste Woche **kopieren**. Kopieren überschreibt nur Tage, an denen in der Quellwoche etwas steht, und löscht nichts.
- **KW-Zelle:** zeigt die Wochenstunden. Mit Wochensoll: rot = Minusstunden, grün = Plus. Ein `*` bedeutet, dass ein Dienst ohne bekannte Stunden dabei ist.
- **Wischen** (Handy) oder ‹ › wechselt den Monat.
- **Kalender-Link:** kopiert die Abo-Adresse (siehe unten).
- **Feiertage:** als `holidays` einen Kalender angeben, z. B. aus der HA-Integration *Feiertage*. Feiertage erscheinen rot.

### Karte erscheint nicht („Custom element doesn't exist: dienstplan-card“)

Die Integration liefert die Karte aus und trägt sie beim Start **selbst als Dashboard-Ressource** ein (*Einstellungen → Dashboards → ⋮ → Ressourcen*, nur wenn die Ressourcen im Speichermodus laufen, was der Standard ist). Das Dashboard lädt die Karte dann bei jedem Öffnen. Nach einer **Erstinstallation oder einem Update** gilt trotzdem:

1. Home Assistant neu starten und **warten, bis alles hochgefahren ist**.
2. **Handy-App:** *Einstellungen → Companion-App → Fehlerbehebung → Frontend-Cache zurücksetzen*, danach die App komplett schließen und neu öffnen. **Browser:** Strg+F5.
3. Steht im Karten-Editor noch eine rote Fehlermeldung, den Editor schließen und neu öffnen. Die Meldung entsteht, wenn die Karte beim Öffnen noch nicht geladen war, und verschwindet nicht von selbst.
4. **Prüfen, ob die Datei ausgeliefert wird:** `https://<deine-HA-Adresse>/dienstplan_static/dienstplan-card.js` im Browser öffnen. Es muss Programmtext erscheinen. Bei „404 Not Found“ ist die Integration nicht (vollständig) geladen bzw. der Ordner `frontend` fehlt in `custom_components/dienstplan/`.
5. **Ressourcen im YAML-Modus:** Dort kann die Integration nichts eintragen. Dann selbst die Ressource `/dienstplan_static/dienstplan-card.js` als *JavaScript-Modul* hinzufügen.

Im Protokoll steht beim Start „Dienstplan-Karte wird unter … bereitgestellt“ und beim ersten Mal „Dienstplan-Karte als Dashboard-Ressource eingetragen“. Wird die letzte Einrichtung entfernt, verschwindet auch die Ressource wieder.

## Sensoren

| Sensor | Inhalt |
|--------|--------|
| Dienst heute / Dienst morgen | Name des Dienstes (oder „Kein Dienst“); Attribute `code`, `start`, `end`, `hours` |
| Nächster Dienstbeginn | Zeitstempel (nur Dienste mit Uhrzeit); Attribute `code`, `name`, `end` |
| Stunden diese Woche | Wochenstunden (Mo–So); Attribute `target`, `balance` |
| Wochenbilanz | Ist minus Soll (nur mit Wochensoll) |
| Urlaub genommen | Urlaubstage dieses Jahres (Mo–Fr) |
| Resturlaub | Jahresurlaub minus genommen (nur mit Urlaubstagen) |

Urlaub und Krank an Werktagen werden für die Bilanz mit Soll/5 Stunden gutgeschrieben.

**Beispiel: Wecker 90 Minuten vor Dienstbeginn** (Entity-ID des Sensors prüfen):

```yaml
triggers:
  - trigger: time
    at: sensor.jenny_naechster_dienstbeginn
    offset: "-01:30:00"
actions:
  - action: notify.mobile_app_handy
    data:
      message: "Gleich geht der Dienst los"
```

## Kalender-Link (iCal)

Die Kalender-Entität hat das Attribut `ical_url`; die Karte kopiert es über den Knopf *Kalender-Link*. In Google Kalender: *Weitere Kalender → Per URL*, in Apple Kalender: *Ablage → Neues Kalenderabonnement*.

- Der Link enthält einen geheimen Token und braucht keine Anmeldung. **Wer den Link kennt, sieht den Dienstplan.** Mit dem Service *Kalender-Link erneuern* wird der alte Link ungültig.
- Damit Google/Apple den Link erreichen, muss Home Assistant von außen erreichbar sein (Nabu Casa oder eigene Domain, hinterlegt als externe URL).
- Abos werden von den Anbietern nur alle paar Stunden aktualisiert (bei Google teils bis zu 24 h). Für sofortige Termine den Abgleich nutzen.

## Abgleich in einen anderen Kalender

Unter *Konfigurieren* einen Kalender bei *Zusätzlich in diesen Kalender eintragen* wählen. Beim Speichern werden neue und geänderte Tage dorthin übertragen (`calendar.create_event`). Jeder Termin enthält im Beschreibungstext eine Kennung `[dienstplan:…]`.

- Wird ein Tag geändert oder gelöscht, entfernt die Integration den alten Termin **nur, wenn der Ziel-Kalender Löschen unterstützt** (z. B. Google, lokaler Kalender) und der Termin die Kennung trägt. Sonst erscheint eine Benachrichtigung mit den Tagen, die manuell zu löschen sind. Termine ohne Kennung werden nie angefasst.
- Ändern sich Name oder Uhrzeit eines Dienstes in den Einstellungen, werden die betroffenen Tage (ab 14 Tage zurück) automatisch neu übertragen.
- Wechselst du den Ziel-Kalender, wird alles neu dorthin übertragen. Die Termine im alten Kalender bleiben bestehen.
- Schlägt das Anlegen fehl, wird der Tag nicht als übertragen markiert. Der Service *Abgleichen* wiederholt den Versuch.

## Services

| Service | Zweck |
|---------|-------|
| `dienstplan.set_shift` | Dienst für Tag oder Zeitraum setzen (`date`, optional `end_date`, `shift`; leer = löschen) |
| `dienstplan.set_shifts` | Mehrere Tage auf einmal (`days: {"2026-10-05": "F1", …}`) |
| `dienstplan.sync` | Alle noch nicht übertragenen oder geänderten Tage in den Ziel-Kalender schreiben |
| `dienstplan.regenerate_link` | Neuen iCal-Link erzeugen |

Alle Services richten sich an die Kalender-Entität (`target: entity_id`).

```yaml
action: dienstplan.set_shift
target:
  entity_id: calendar.jenny_dienstplan
data:
  date: "2026-10-05"
  end_date: "2026-10-09"
  shift: F1
```

## Bekannte Grenzen

- Die Integration wurde ohne laufende Home-Assistant-Instanz entwickelt. Die Logik (Zeiten, Abgleich, Stunden, Feed) und die Karte sind mit eigenen Tests geprüft, die Einrichtung in Home Assistant selbst noch nicht. Fehler bitte als Issue melden.
- Stunden werden ohne Pausenabzug berechnet, sofern bei `Std` nichts angegeben ist.
- Feiertage werden nur markiert, nicht in die Stunden eingerechnet.

## Entwicklung

```
python -m pytest tests -q          # Dienste, Stunden, iCal
python tests/check_manager.py      # Manager/Abgleich mit Home-Assistant-Stubs
python tests/check_setup.py        # Einrichtung: Karte ausliefern, Dashboard-Ressource
node tests/card.test.js            # Karte mit Mini-DOM
```

Bei jedem Push prüft GitHub Actions zusätzlich hassfest und die HACS-Validierung.
