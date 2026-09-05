# The booking was two days and one hour wrong — 30 August 2026

Runs 321, 322 and 323 on workflow 2, the first calls placed after commit
`01c4a4d`. Run 323 (WR-TEL-OUT-06749371, 100 s) qualified a caller cleanly —
bill, city, property type, roof, name, all six fields inside a minute — and then
booked him for the wrong day.

    AGENT   ఉచిత సైట్ సర్వే కోసం మీరు ఏ సమయానికి సిద్ధంగా ఉంటారు?
    CALLER  ఎల్లుండి సాయంత్రం ఐదు ఇంటికి.          day after tomorrow, 5, at home
    AGENT   మంచిది, సాయంత్రం ఐదు గంటలకు మీ ఇంటికి వచ్చి ...
    CALLER  ఓకే.
    AGENT   సారీ సార్, మీరు చెప్పిన సమయం మా ఎంపికలలో లేదు.
            రేపు ఉదయం ten o'clock లేదా ఎల్లుండి సాయంత్రం four o'clock?
    CALLER  4 ఓ క్లాక్
    AGENT   సరే, ఈ రోజు సాయంత్రం four o'clockకి మీ ఇంటికి వచ్చి ...

**Stored: `2026-08-30T16:00`. Offered: `2026-09-01T16:00`.** He chose the second
option and was booked for today. The vendor drives to the wrong house on the
wrong day, two days early, and nobody on that call could have detected it —
which is what makes this worse than an error message.

Four independent defects, each of which alone produces a wrong booking.

---

## 1. A time the caller volunteers before the menu is discarded

`CallState.note_booking` refused to read any number as a time until two slots
had been put to the caller:

```python
if not self.offered:
    return False
```

That gate is right, and it is why run 266 exists as a comment above it: the
parser used to run on every utterance, so "మూడు లక్షలు" — an answer to the
**bill** question on turn three — was read as three o'clock, a visit was booked,
and the call ended after 38 seconds.

It is also too wide. Run 323's agent asked, in as many words, *what time suits
you?* — and then threw the answer away, because the state block happened not to
have rendered its menu yet.

**Replayed through the state machine, the fix is visible in one line.** Before:

    turn 8  USER ఎల్లుండి సాయంత్రం ఐదు ఇంటికి   ->  appointment_iso = (none)

After:

    turn 8  USER ఎల్లుండి సాయంత్రం ఐదు ఇంటికి   ->  2026-09-01T17:00:00+05:30

The new gate tests the utterance's **structure**, not whether permission was
granted first: a day word (`ఎల్లుండి`, `రేపు`, `ఈ రోజు`) **plus a named hour**.

- A bill has no day word in it. "మూడు లక్షలు" never will — run 266 stays fixed.
- A day word alone is not enough either. *"ఎల్లుండి మా వాళ్ళు ఊరికి
  వెళ్తున్నారు"* — day after tomorrow my family are going to the village — names
  a day and asks for nothing. An hour has to be named too.

## 2. The agent told the caller his own time was unavailable

`offer_line()` ended with *"Offer nothing else and invent no other time."* That
is a constraint on the **agent's** inventions, and the model read it as a
constraint on the **caller** — hence *"మీరు చెప్పిన సమయం మా ఎంపికలలో లేదు"*, the
time you said is not among our options, said to a man who had named five o'clock
on a weekday evening.

Run 322 shows the same line failing the other way:

    AGENT   అర్థమైంది సార్, ఈ రెండు ఎంపికలలో ఏది మీకు బాగుంటుంది?
    USER    ఈరోజు సాయంత్రం          (he repeats himself, verbatim)

*Which of these two suits you* — having said neither of them. There was nothing
to choose between.

The line now says both things explicitly: **say both times aloud, never refer to
"the two options" without saying them; invent no time of your own, but accept
any time they name and never tell them a time is unavailable.**

## 3. An hour chosen from the menu resolved against the wall clock

The most damaging line in the call. `parse_slot` had never been shown the menu,
so a bare "4" fell through to *"a time with no day means the next occurrence of
it"* — 4 p.m. today, rather than the 4 p.m. that was actually on offer, two days
out.

A caller choosing from a menu says the half that distinguishes the options and
drops the rest. That is not sloppiness; it is how anyone answers a closed
question. So the dropped half has to come back from the menu:

| Caller says | Menu | Booked |
|---|---|---|
| `4 ఓ క్లాక్` | ten tomorrow / four ఎల్లుండి | **ఎల్లుండి 16:00** |
| `ఫోర్ ఓ క్లాక్` | same | ఎల్లుండి 16:00 |
| `four o'clock` | same | ఎల్లుండి 16:00 |
| `ten` | same | రేపు 10:00 |
| `రెండోది` / `మొదటిది` | same | the second / the first |

Answering by **position** now counts as a choice too, which it did not before.

Two offers at the same hour still resolve to nothing — the caller is asked
again rather than guessed at, which is run 262's whole lesson.

## 4. The confirmation dropped the day, and welded కి onto o'clock

The state block said `BOOKED for ఎల్లుండి సాయంత్రం five o'clock`. The agent said
back *"సాయంత్రం ఐదు గంటలకు"* — the hour, alone, with no day attached to it. **A
time without a day is not an appointment**; it is something the caller and the
vendor will remember differently. The instruction now demands the exact words,
*the day included*.

And `four o'clockకి` — the Telugu dative case marker welded onto an English word.
Runs 300, 314 and 317 all said it;
[14-telugu-voice-register-guide.md](14-telugu-voice-register-guide.md) names it
as *the sound of a machine*; run 323 said it three times in its last four
sentences. `_hours()` only ever looked at `గంట`, so a clock already rendered in
English walked straight past it and picked up a Telugu suffix on the way out.

Dropping the marker is right rather than merely tidy: *"five o'clock వస్తాను"* is
how a code-mixing speaker says it, and it is exactly what `Slot.say()` produces —
so the sentence the agent reads back now **matches the record the booking system
holds**, instead of diverging from it by a suffix.

A fifth, smaller one, found while fixing the fourth: a slot more than two days
out was named by `strftime("%d/%m")`, so a slot ten days ahead was read to the
caller as **"01/09"**. It is now the Telugu weekday.

---

## What the scan turned up

Checking my own new regexes for a mangled escape sequence, I scanned the whole
`api/` tree — and found **nine literal backspace characters where `\b` had been
written**, five of them in live regexes rather than comments. The cause is
mechanical: `\\b` collapsing to `\x08` when a file is edited through a shell
heredoc. It has happened in this project before and it is invisible on screen,
because a backspace renders as nothing.

Two of the five matter:

```python
_QUESTION_WORDS = re.compile(
    r"(\?|ఎంత|ఎక్కడ|...|"
    r"\x08(what|when|where|how|why|which|who|can|do|does|is|are)\x08)")

_QUESTION_EN = re.compile(
    r"\x08(possible|available|worth it|how much|how many|what about|"
    r"tell me|explain|any idea|will (it|you|i)|should i)\x08")
```

Both English alternations were dead. The Telugu half of the question detector
worked; **the English half has never fired.** That is not cosmetic — `_is_question`
drives the state block's *"THE CALLER ASKED YOU SOMETHING: answer THAT, and
nothing else"* branch, which is the branch written specifically to fix run 218,
where the caller said *"అతను సోలార్ పెట్టొచ్చా అని అడిగాను, మీరేమో పేరు
అడుగుతున్నారు"* — I asked whether solar can be installed, and you are asking my
name. The word that case turns on is **"possible"**, in English, in
`_QUESTION_EN`.

Measured after the repair:

| Caller said | Detected as a question |
|---|---|
| `ఇట్స్ లైక్ బిగ్ వన్. పాసిబుల్ అయి ఉందా` | ✅ (was ✅ — Telugu particle) |
| `solar is possible or not` | ✅ (**was ❌**) |
| `how much cost` | ✅ (**was ❌**) |
| `what about subsidy` | ✅ (**was ❌**) |
| `ఓకే` / `ఇల్లు.` | ❌ correctly |

The other three were in comments — including, with some irony, the comments in
`amounts.py` and `booking.py` explaining *why `\b` does not work against Telugu
combining marks*.

---

## Verification

- **446 passing, 11 failing** across the Vaani subset. The baseline, measured by
  stashing the work and re-running the identical command, is **419 passing, 11
  failing** — the same eleven, by name. **+27, no regressions.**
- The eleven are pre-existing and unrelated: nine in `test_vaani_filler_cover.py`
  and one in `test_speculation_coordinator.py` need async fixtures from the
  `conftest.py` that cannot load without a database, and one is the known
  wording drift in `test_reply_sanitizer.py`.
- New file `api/tests/test_run323_booking.py`, 27 cases, every one drawn from
  the real transcript.
- Four existing assertions were repointed from exact prompt wording to intent —
  e.g. `assert "OFFER EXACTLY THESE TWO TIMES" in block` became a check that
  **each slot's own `say()` string** appears in the block. A test that pins the
  sentence breaks every time the sentence improves; one that pins the behaviour
  does not.
- Run 323 replayed end to end through `CallState`: booked
  `2026-09-01T17:00`, two days out, as he asked.

## Not fixed today

- `location` is still normalised inconsistently — run 322 stored `Aranthapur`
  in English, run 318 stored `అనంటపూర్` in Telugu script.
- Run 322 asked for `assessment_agreed` three times in different words before
  reaching the menu. The two-ask budget counts the field, not the paraphrase.
- Token usage is still not instrumented (`"dograh_token_usage": 0`).
- None of the above has been exercised by a live call yet.
