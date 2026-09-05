"""Check a drafted prompt-layer section before it is spliced into a shared layer.

Layers 1, 2 and 4 are inherited unchanged by every client Vaani will ever run,
so a mistake here is a mistake on every call the platform makes. `api/tests/
test_layers_are_reusable.py` guards the shipped layers; this guards the DRAFT,
before it becomes one, and checks several things that test does not:

    industry vocabulary        the shared layers must carry none
    client names, ₹ figures    same reason
    the clock rule             fully English or fully Telugu -- never mixed
    the honorific rule         గారు after a name, అండి after a verb, no stacking
    digits in spoken examples  the speech engine reads them inconsistently
    literary Telugu            the register the whole persona exists to prevent

Run it on every drafted section:

    python tools/check_layer_section.py <file>...
    python tools/check_layer_section.py --full-layer <a whole layer>

Exit code is the number of files with findings, so it can gate a commit.

Why a separate tool rather than more test cases
------------------------------------------------
These checks are heuristics with false positives -- "గంటలకు" next to an English
numeral is usually the mixed clock and occasionally a legitimate quotation of
the WRONG form in a wrong/right table. A test that fails on a deliberate
counter-example is a test people learn to ignore. This reports and lets a human
judge, and the hard invariants stay in the test suite where they belong.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Kept in step with api/tests/test_layers_are_reusable.py, plus the verticals
# this platform has not run yet but will.
INDUSTRY_WORDS = [
    "సోలార్", "సౌర", "solar", "ప్యానెల్", "panel", "సబ్సిడీ", "subsidy",
    "విద్యుత్", "కరెంట్ బిల్లు", "kilowatt", "net metering", "నెట్ మీటరింగ్",
    "బంగారం", "jewellery", "gold", "insurance", "బీమా", "మ్యూచువల్ ఫండ్",
    "mutual fund", "loan emi", "రూఫ్", "టెర్రస్", "inverter", "ఇన్వర్టర్",
]

CLIENT_NAMES = ["MB Solar", "mbsolarhub", "BS Wealth", "బీఎస్", "Priya"]

# A concrete price belongs to one client's knowledge base, never to a layer
# every client inherits.
FIGURE = re.compile(r"₹\s*[\d,]{3,}|\b\d{4,}\s*(?:rupees|రూపాయ)")

# The mixed clock: an ENGLISH figure with the TELUGU clock frame after it.
# "ten గంటలకు" is the form the client corrected twice. A fully Telugu clock
# ("పది గంటలకు") and a fully English one ("ten o'clock") are both correct.
_EN_NUMERAL = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
               r"|టు|త్రీ|ఫోర్|ఫైవ్|సిక్స్|సెవెన్|ఎయిట్|నైన్|టెన్|\d+")
MIXED_CLOCK = re.compile(rf"\b({_EN_NUMERAL})\s+గంట(?:ల)?(?:కు|కి)")

# The Telugu case marker welded onto the English clock: "four o'clockకి".
OCLOCK_CASE = re.compile(r"o\s*'?\s*clock\s*(?:కి|కు)")

# అండి attaching to a name instead of a verb is caught by hand, but the stacked
# honorific is mechanical.
STACKED_HONORIFIC = re.compile(r"(?:సార్|మేడమ్)\s+గారు")

# Digits inside a Telugu example. Layer 1 requires spoken numbers to be English
# WORDS -- the speech engine reads digits inconsistently and the failure is
# silent. Only flagged inside quoted example lines.
DIGITS_IN_QUOTE = re.compile(r'"[^"]*\d[^"]*"')

# The literary register the persona exists to prevent. If one of these appears
# outside a "wrong" column it has been recommended by accident.
LITERARY = [
    "ధన్యవాదాలు", "తెలియజేస్తాను", "అందిస్తాను", "ప్రారంభించ", "వివరములు",
    "అనుకూలమైన", "ఆసక్తి కలిగి", "సందేహం ఉన్నట్లయితే", "ఉత్పత్తి",
]


# A wrong/right table puts the WRONG form in the first cell. Detecting that by
# keyword fails, because the row itself carries no keyword -- the header two
# lines up does. So the SHAPE is read instead: a two-cell row is a contrast
# pair, and its left cell is the one being warned against.
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")

_NEGATIVE = ("wrong", "never", "bad", "not this", "instead of", " not ",
             "avoid", "don't", "do not", "worse", "✗", "❌")


def wrong_column(header: str) -> int | None:
    """Which cell of a table holds the counter-example, read from its header.

    Assuming it is always the first cell is wrong often enough to matter: these
    layers carry `| wrong | right |`, `| pattern | right | wrong |` and
    `| said | means | reply |` tables, and guessing costs either a false
    positive on every row or a blind spot down a whole column.

    The header says so, so the header is read.
    """
    cells = [c.strip().lower() for c in header.strip().strip("|").split("|")]
    for i, cell in enumerate(cells):
        if any(m in cell for m in ("wrong", "bookish", "bad", "never", "avoid",
                                   "robotic", "scripted", "don't", "do not",
                                   "unnatural", "machine", "translated",
                                   "literary", "stiff", "formal", "fake")):
            return i
    return 0 if len(cells) >= 2 else None


def inspectable(line: str, wrong_col: int | None = 0) -> str:
    """The part of a line that is a RECOMMENDATION, not a counter-example.

    Three shapes carry a counter-example, and all three are in the layers:

        | bookish | spoken | why |     a table row -- the FIRST cell is wrong
        > Wrong: "..."                 a blockquote example
        `three thousand`, not `3000`   an inline correction

    Dropping the whole LINE for a table row is what the first version did, and
    it is too generous: a three-column table is mostly right-hand column, so a
    mistake there would never be seen. Only the wrong cell is dropped.
    """
    row = _TABLE_ROW.match(line)
    if row:
        if set(line.strip()) <= set("|-: "):
            return ""              # a header separator carries no example
        cells = row.group(1).split("|")
        if len(cells) < 2 or wrong_col is None:
            return line
        return " | ".join(c for i, c in enumerate(cells) if i != wrong_col)
    low = line.lower()
    if any(m in low for m in _NEGATIVE):
        return ""
    if any(m in line for m in ("తప్పు", "కాదు")):
        return ""
    return line


def check(path: Path, full_layer: bool = False) -> list[str]:
    text = path.read_text(encoding="utf-8")
    low = text.lower()
    out: list[str] = []

    found = [w for w in INDUSTRY_WORDS
             if (w.lower() in low if w.isascii() else w in text)]
    if found:
        out.append(f"industry vocabulary: {found}")

    named = [n for n in CLIENT_NAMES
             if (n.lower() in low if n.isascii() else n in text)]
    if named:
        out.append(f"client name: {named}")

    if text.startswith("# ") and not full_layer:
        out.append("starts with a '# ' title; sections must start at '## '")

    all_lines = text.splitlines()
    wrong_col = 0
    for n, raw in enumerate(all_lines, 1):
        if _TABLE_ROW.match(raw):
            if set(raw.strip()) <= set("|-: "):
                continue                  # the separator; the line above was the header
            nxt = all_lines[n] if n < len(all_lines) else ""
            if set(nxt.strip()) <= set("|-: ") and nxt.strip():
                wrong_col = wrong_column(raw)
        line = inspectable(raw, wrong_col)
        if not line.strip():
            continue
        for label, pattern in (("mixed clock", MIXED_CLOCK),
                               ("case marker on o'clock", OCLOCK_CASE),
                               ("stacked honorific", STACKED_HONORIFIC),
                               ("rupee figure", FIGURE)):
            m = pattern.search(line)
            if m:
                out.append(f"line {n}: {label} -- {m.group(0)!r}")
        for word in LITERARY:
            if word in line:
                out.append(f"line {n}: literary register {word!r} not marked wrong")
        m = DIGITS_IN_QUOTE.search(line)
        if m and "o'clock" not in m.group(0):
            out.append(f"line {n}: digits in a spoken example -- {m.group(0)[:60]!r}")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    full_layer = "--full-layer" in argv
    argv = [a for a in argv if not a.startswith("--")]
    bad = 0
    for name in argv:
        path = Path(name)
        if not path.exists():
            print(f"{path}: MISSING")
            bad += 1
            continue
        findings = check(path, full_layer=full_layer)
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if findings:
            bad += 1
            print(f"\n{path.name}  ({lines} lines)  {len(findings)} finding(s)")
            for f in findings:
                print(f"   {f}")
        else:
            print(f"{path.name}  ({lines} lines)  clean")
    return bad


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
