"""Tests für die Sprachantworten (ohne Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime

from _loader import load

voice = load("voice")
shifts = load("shifts")

TODAY = date(2026, 9, 29)  # Dienstag
NOW = datetime(2026, 9, 29, 10, 0)

SHIFTS = shifts.parse_shifts(
    """
F1;Frühdienst 1;06:00;14:00;;;8
F2;Frühdienst 2;06:30;13:00
N;Nachtdienst;21:00;06:00
F;Frühdienst
U;Urlaub;;;urlaub
K;Krank;;;abwesend
D;Fortbildung;;;abwesend
X;Frei;;;frei
"""
)


def person(name="Jenny", plan=None, entity="calendar.dienstplan_jenny_dienstplan"):
    days = {date.fromisoformat(k): v for k, v in (plan or {}).items()}
    return voice.Person(name, entity, lambda d: shifts.find_shift(SHIFTS, days.get(d)))


def ask(people, who="", day="heute", now=NOW):
    return voice.answer(people, who, day, now)


# ------------------------------------------------------------------ Namen und Tage


def test_display_name_drops_the_word_dienstplan():
    assert voice.display_name("Dienstplan Jenny") == "Jenny"
    assert voice.display_name("Jenny Dienstplan") == "Jenny"
    assert voice.display_name("Jenny") == "Jenny"
    assert voice.display_name("Dienstplan") == "Dienstplan"


def test_parse_day():
    p = voice.parse_day
    assert p("", TODAY) == TODAY and p(None, TODAY) == TODAY
    assert p("heute", TODAY) == TODAY
    assert p("Morgen", TODAY) == date(2026, 9, 30)
    assert p("übermorgen", TODAY) == date(2026, 10, 1)
    assert p("gestern", TODAY) == date(2026, 9, 28)
    assert p("morgen früh", TODAY) == date(2026, 9, 30), "Zusatzwörter stören nicht"
    assert p("am Freitag", TODAY) == date(2026, 10, 2)
    assert p("Dienstag", TODAY) == TODAY, "heutiger Wochentag = heute"
    assert p("montag", TODAY) == date(2026, 10, 5), "nächster Montag"
    assert p("2026-10-05", TODAY) == date(2026, 10, 5)
    assert p("2026-10-05T00:00:00", TODAY) == date(2026, 10, 5)
    assert p("5.10.", TODAY) == date(2026, 10, 5)
    assert p("05.10.2027", TODAY) == date(2027, 10, 5)
    assert p("2026-W41", TODAY) is None, "Alexa-Wochenangabe wird nicht geraten"
    assert p("2026-02-30", TODAY) is None
    assert p("Jenny", TODAY) == TODAY, "ohne Tagesangabe gilt heute"
    # ganze Sätze (Assist/Alexa reichen den Satz durch)
    assert p("Jenny übermorgen", TODAY) == date(2026, 10, 1)
    assert p("wie arbeitet Jenny am Freitag eigentlich", TODAY) == date(2026, 10, 2)
    assert p("hat sie am 5.10. Dienst", TODAY) == date(2026, 10, 5)
    assert p("Jenny 2026-W41", TODAY) is None


def test_day_phrase():
    ph = voice.day_phrase
    assert ph(TODAY, TODAY) == "heute"
    assert ph(date(2026, 9, 30), TODAY) == "morgen"
    assert ph(date(2026, 10, 2), TODAY) == "am Freitag"
    assert ph(date(2026, 10, 12), TODAY) == "am Montag, den 12. Oktober"
    assert ph(date(2026, 9, 26), TODAY) == "am Samstag, den 26. September"


def test_spoken_time():
    from datetime import time

    assert voice.spoken_time(time(6, 0)) == "6 Uhr"
    assert voice.spoken_time(time(13, 30)) == "13 Uhr 30"


# ------------------------------------------------------------------ Sätze


def test_timed_work_shift():
    r = ask([person(plan={"2026-09-30": "F1"})], day="morgen")
    assert r["speech"] == "Jenny hat morgen Frühdienst 1, von 6 Uhr bis 14 Uhr."
    assert r["date"] == "2026-09-30"
    assert r["people"] == [
        {"name": "Jenny", "entity_id": "calendar.dienstplan_jenny_dienstplan", "code": "F1", "shift": "Frühdienst 1",
         "category": "work", "start": "06:00", "end": "14:00", "hours": 8.0}
    ]


def test_minutes_are_spoken():
    r = ask([person(plan={"2026-09-29": "F2"})])
    assert r["speech"] == "Jenny hat heute Frühdienst 2, von 6 Uhr 30 bis 13 Uhr."


def test_night_shift_ends_next_day():
    r = ask([person(plan={"2026-09-29": "N"})])
    assert r["speech"] == "Jenny hat heute Nachtdienst, von 21 Uhr bis 6 Uhr am nächsten Tag."


def test_shift_without_times():
    assert ask([person(plan={"2026-09-29": "F"})])["speech"] == "Jenny hat heute Frühdienst."


def test_vacation_off_sick_absent_and_empty():
    plan = {"2026-09-29": "U", "2026-09-30": "X", "2026-10-01": "K", "2026-10-02": "D"}
    p = person(plan=plan)
    assert ask([p], day="heute")["speech"] == "Jenny hat heute Urlaub."
    assert ask([p], day="morgen")["speech"] == "Jenny hat morgen frei."
    assert ask([p], day="übermorgen")["speech"] == "Jenny ist übermorgen krank."
    assert ask([p], day="Freitag")["speech"] == "Jenny ist am Freitag abwesend: Fortbildung."
    assert ask([p], day="2026-10-20")["speech"] == "Bei Jenny ist am Dienstag, den 20. Oktober nichts eingetragen."
    assert ask([p], day="heute")["people"][0]["category"] == "vacation"
    r = ask([person()], day="morgen")
    assert r["speech"] == "Bei Jenny ist morgen nichts eingetragen."
    assert r["people"][0]["code"] is None and r["people"][0]["hours"] is None


def test_past_tense():
    p = person(plan={"2026-09-28": "F1", "2026-09-27": "U", "2026-09-26": "K"})
    assert ask([p], day="gestern")["speech"] == "Jenny hatte gestern Frühdienst 1, von 6 Uhr bis 14 Uhr."
    assert ask([p], day="2026-09-27")["speech"] == "Jenny hatte vorgestern Urlaub."
    assert ask([p], day="2026-09-26")["speech"] == "Jenny war am Samstag, den 26. September krank."
    assert ask([person()], day="gestern")["speech"] == "Bei Jenny war gestern nichts eingetragen."


def test_unparseable_day():
    r = ask([person()], day="2026-W41")
    assert r["speech"] == "Das Datum habe ich nicht verstanden." and r["date"] is None


# ------------------------------------------------------------------ Personen


def test_no_plans_loaded():
    assert ask([])["speech"] == "Ich finde keinen geladenen Dienstplan."


def test_single_plan_answers_for_any_wording():
    p = person(plan={"2026-09-29": "F1"})
    for who in ("", "sie", "meine Frau", "Jenny", "jenny", "wer", "Jenny heute", "heute", "wie arbeitet Jenny"):
        assert ask([p], who)["speech"].startswith("Jenny hat heute"), who


def test_several_plans():
    jenny = person("Jenny", {"2026-09-29": "F1"}, "calendar.jenny")
    max_ = person("Max", {"2026-09-29": "N"}, "calendar.max")
    both = ask([jenny, max_], "wer")
    assert both["speech"] == "Jenny hat heute Frühdienst 1, von 6 Uhr bis 14 Uhr. Max hat heute Nachtdienst, von 21 Uhr bis 6 Uhr am nächsten Tag."
    assert [e["name"] for e in both["people"]] == ["Jenny", "Max"]
    assert ask([jenny, max_], "")["speech"] == both["speech"]
    assert ask([jenny, max_], "max")["speech"].startswith("Max hat heute")
    assert ask([jenny, max_], "Wie arbeitet Max")["speech"].startswith("Max hat heute"), "Name im längeren Text"
    assert ask([jenny, max_], "Peter")["speech"] == "Für Peter habe ich keinen Dienstplan."
    # ganzer Satz in beiden Feldern (so ruft die Assist-Automation den Service auf)
    for sentence in ("Max heute", "wann arbeitet Max heute", "Max"):
        assert ask([jenny, max_], sentence, sentence)["speech"].startswith("Max hat heute"), sentence
    assert ask([jenny, max_], "heute", "heute")["speech"] == both["speech"], "„wer arbeitet heute“ meint alle"
    assert ask([jenny, max_], "Peter morgen", "Peter morgen")["speech"] == "Für Peter habe ich keinen Dienstplan."


# ------------------------------------------------------------------ Nächster Dienst


def test_next_shift_skips_non_work_and_finished_shifts():
    plan = {"2026-09-29": "F1", "2026-09-30": "U", "2026-10-01": "X", "2026-10-03": "N"}
    p = person(plan=plan)
    # 10 Uhr: der Frühdienst von heute (6–14) läuft noch -> zählt
    r = ask([p], day="nächster", now=datetime(2026, 9, 29, 10, 0))
    assert r["speech"] == "Jenny arbeitet als Nächstes heute: Frühdienst 1, von 6 Uhr bis 14 Uhr."
    # 15 Uhr: vorbei -> nächster Arbeitsdienst (Urlaub/Frei zählen nicht)
    r = ask([p], day="nächster", now=datetime(2026, 9, 29, 15, 0))
    assert r["speech"] == "Jenny arbeitet als Nächstes am Samstag: Nachtdienst, von 21 Uhr bis 6 Uhr am nächsten Tag."
    assert r["date"] == "2026-10-03" and r["people"][0]["date"] == "2026-10-03"
    assert voice.wants_next("wieder") and voice.wants_next("nächster Dienst") and not voice.wants_next("morgen")
    assert voice.wants_next("wann arbeitet Jenny wieder") and not voice.wants_next("wie arbeitet Jenny morgen")
    r = ask([p], "wann arbeitet Jenny wieder", "wann arbeitet Jenny wieder", now=datetime(2026, 9, 29, 15, 0))
    assert r["date"] == "2026-10-03"


def test_next_shift_none_found():
    r = ask([person()], day="nächster")
    assert r["speech"] == "Bei Jenny ist in den nächsten 90 Tagen kein Dienst eingetragen."
    assert r["date"] is None


def test_next_shift_night_shift_started_today_still_counts():
    p = person(plan={"2026-09-29": "N"})
    r = ask([p], day="nächster", now=datetime(2026, 9, 29, 23, 30))
    assert r["speech"].startswith("Jenny arbeitet als Nächstes heute: Nachtdienst")
