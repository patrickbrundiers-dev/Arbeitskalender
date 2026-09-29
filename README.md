# Dienstplan für Home Assistant

Dienste (Früh, Spät, Nacht …) pro Tag in einer Monatsansicht eintragen – daraus entstehen automatisch Kalendertermine.

- **Kalender-Entität** pro Person (`calendar.<name>_dienstplan`), sichtbar im HA-Kalender
- **Karte** zum Eintragen: Dienst wählen, Tage antippen, speichern
- **Optionaler Abgleich** in einen anderen Kalender (Google, lokaler Kalender, CalDAV …), damit die Termine auch auf dem Handy erscheinen
- Nachtdienste über Mitternacht, Urlaub/Krank als Ganztagstermin, freie Tage ohne Termin
- Attribute `today_shift`, `tomorrow_shift` (und `_name`) für Automationen, z. B. Wecker oder Licht

## Installation

**HACS:** In HACS oben rechts (⋮) *Benutzerdefinierte Repositories* öffnen, `https://github.com/patrickbrundiers-dev/Arbeitskalender` mit Typ *Integration* hinzufügen, „Dienstplan“ herunterladen, Home Assistant neu starten.

**Manuell:** Ordner `custom_components/dienstplan` nach `config/custom_components/` kopieren, neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → Dienstplan*.

## Dienste festlegen

Ein Dienst pro Zeile: `Code;Name;Start;Ende;Typ;Farbe`

| Feld | Bedeutung |
|------|-----------|
| Code | Kürzel wie im Dienstplan, z. B. `F1`, `S2`, `N1`, `U` |
| Name | Titel des Kalendertermins |
| Start / Ende | `HH:MM`. Ende früher als Start = Dienst endet am Folgetag. Beide leer = Ganztagstermin |
| Typ | leer = normaler Dienst, `abwesend` = Ganztagstermin (Urlaub, Krank), `frei` = **kein** Termin |
| Farbe | optional `#RRGGBB` für die Karte |

```
F1;Frühdienst 1;06:00;14:00
N1;Nachtdienst 1;21:00;06:00
U;Urlaub;;;abwesend
X;Frei;;;frei
```

> **Wichtig:** Die mitgelieferten Zeiten sind Platzhalter. Bitte mit dem Aushang abgleichen und unter *Konfigurieren* der Integration anpassen. Änderungen an Zeiten gelten für die Anzeige im Dienstplan-Kalender sofort; bereits in einen Ziel-Kalender übertragene Termine bleiben unverändert (Tag neu eintragen oder Termin dort ändern).

## Karte

Die Karte wird von der Integration automatisch bereitgestellt. Im Dashboard:

```yaml
type: custom:dienstplan-card
entity: calendar.jenny_dienstplan
title: Dienstplan Jenny
```

Bedienung: Tag antippen, im Auswahlfenster die Schicht wählen (mit Uhrzeiten, „Kein Dienst“ löscht den Eintrag). Der Eintrag wird sofort gespeichert und der Kalendertermin angelegt. Mit ‹ › wechselst du den Monat.

## Abgleich in einen anderen Kalender

In den Optionen einen Kalender unter *Zusätzlich in diesen Kalender eintragen* wählen. Beim Speichern werden neue und geänderte Tage dorthin übertragen (`calendar.create_event`). Jeder übertragene Termin enthält im Beschreibungstext eine Kennung `[dienstplan:…]`.

- Wird ein Tag geändert oder gelöscht, entfernt die Integration den alten Termin **nur, wenn der Ziel-Kalender Löschen unterstützt** (z. B. Google, lokaler Kalender) und der Termin die Kennung trägt. Andernfalls erscheint eine Benachrichtigung mit den Tagen, die manuell zu löschen sind.
- Termine ohne Kennung werden nie angefasst.
- Schlägt das Anlegen fehl, wird der Tag nicht als übertragen markiert; der Service *Dienstplan: Abgleichen* wiederholt den Versuch.

## Services

| Service | Zweck |
|---------|-------|
| `dienstplan.set_shift` | Dienst für Tag oder Zeitraum setzen (`date`, optional `end_date`, `shift`; leer = löschen) |
| `dienstplan.set_shifts` | Mehrere Tage auf einmal (`days: {"2026-10-05": "F1", …}`) |
| `dienstplan.sync` | Alle noch nicht übertragenen Tage in den Ziel-Kalender schreiben |

Alle Services richten sich an die Kalender-Entität (`target: entity_id`).

```yaml
service: dienstplan.set_shift
target:
  entity_id: calendar.jenny_dienstplan
data:
  date: "2026-10-05"
  end_date: "2026-10-09"
  shift: F1
```

## Entwicklung

`tests/test_shifts.py` prüft Parser und Zeitberechnung (`pytest`). Benötigt Home Assistant 2024.11 oder neuer.
