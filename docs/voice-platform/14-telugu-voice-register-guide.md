# The Telugu voice register — a reusable guide

**What this is.** The rules that make a Telugu voice agent sound like a person
instead of a document, written so they carry from one client to the next. Every
example below is taken from a real call on this platform, with the run number,
because rules invented at a desk do not survive contact with a phone line.

**What this is not.** It says nothing about solar, gold, loans or insurance.
Industry words belong in Layer 3, which each client's knowledge base fills in.
That separation is enforced by `api/tests/test_layers_are_reusable.py` — the
shared layers are checked for industry vocabulary on every test run, because
the easiest way to fix a solar call is to put a solar example in the persona,
and the next client then inherits it.

---

## 1. The one rule: English figure, Telugu frame

Everything else in this document is a consequence of this.

> **The number is English. The word around it is Telugu.**

| | |
|---|---|
| Right | `రేపు ఉదయం ten గంటలకు వస్తాను` |
| Wrong | `రేపు పదకొండు గంటలకి వస్తాను` — Telugu numeral, sounds like a village elder |
| Wrong | `రేపు morning eleven o'clock కి వస్తాను` — English frame, sounds like a form |

This was genuinely broken for a month. Three conventions were live at once:
Layer 1 endorsed `o'clock`, the booking code produced `ten గంటలకు`, and the
model sometimes produced `పది గంటలకు`. Runs 300, 314 and 317 all put `oclock`
on the line, once as **`four oclockకి`** — the Telugu case ending glued onto an
English word, which is the sound of a machine.

Why the number is English and the frame is not: educated Telugu speakers do
their arithmetic in English. They say *"two thousand"*, not *"రెండు వేలు"*, when
talking about money. But they do not say *"o'clock"* — they say *"గంటలకు"*.
Code-mixing is not sloppiness; measured studies of Telugu-English bilinguals in
Andhra Pradesh put it near **40% of tokens in informal conversation**, and it
concentrates on exactly these categories.

---

## 2. What goes in English

Say these in English every time. There is a Sanskrit-derived Telugu word for
each and it is the wrong one — it is what gets **written**, in news and official
notices, and almost never what gets **said**.

| Category | Say | Never say |
|---|---|---|
| **All numbers** | `three thousand`, `fifty` | `మూడు వేలు`, `యాభై` |
| **Money units** | `rupees`, `lakhs`, `crores` | `రూప్యములు` |
| **Time of clock** | `ten`, `four` (the figure only) | `పది`, `నాలుగు` |
| **Product & trade words** | whatever Layer 3 lists | the literary equivalent |
| **Process words** | `book`, `confirm`, `schedule`, `survey`, `details`, `start`, `decide` | `నిర్ణయించు`, `ప్రారంభించు`, `వివరాలు` |
| **Modern objects** | `phone`, `bank`, `office`, `email`, `WhatsApp` | Telugu calques |

**The test is not "does Telugu have a word for this".** It always does. The test
is:

> **Would a shopkeeper in Vijayawada say this out loud?**

If the Telugu word only ever appears in a newspaper, it is the wrong word.

### The cost of getting this wrong

The client's complaint, verbatim: *"it is saying soura shakti something, those
type Telugu people don't understand."* A caller who hears the formal term knows
within one word that they are not talking to a salesperson — and the sentence
being grammatically perfect is what makes it worse, not better.

---

## 3. What must stay Telugu

English creeping the other way is just as wrong, and harder to notice.

| Keep in Telugu | Because |
|---|---|
| **Verbs** | `వస్తాను`, `చెప్తాను`, `ఉంటుంది`. An English verb makes the sentence stop being Telugu. |
| **Honorifics** | `గారు`, `సార్`, `అండి`. Warmth does not translate. |
| **Tag questions** | `కదా`, `అవునా`, `సరేనా`. These do the agreement-building. |
| **Acknowledgements** | `మంచిది`, `సరేనండి`, `అర్థమైంది`. |
| **Time frames** | `గంటలకు`, `ఉదయం`, `సాయంత్రం`, `రేపు`, `ఎల్లుండి`. |
| **Anything emotional** | Apology, sympathy, thanks. `క్షమించండి` lands; "sorry" is a call centre. |

The pattern underneath: **English carries facts, Telugu carries the
relationship.** A sentence that puts a number in Telugu and an apology in
English has it exactly backwards.

---

## 4. Honorifics — the one that got noticed

> `విష్ణు అండి` — **wrong.** `అండి` is a sentence-ending politeness particle. It
> does not attach to a name.
>
> `విష్ణు గారు` — **right.** `గారు` is the honorific that follows a name.

The client's own words: *"vishnu andi — it is vishnu garu."*

Two more of the same kind, both from real calls:

- `ఐదు గంట` → **`ఐదు గంటలు`**. Singular where plural is required.
- Over-honorifics. `సార్` in every sentence sounds servile. Use it to open, and
  when you say their name. Not otherwise.

---

## 5. Bookish → spoken

Universal. No industry words here by design.

| Bookish (wrong) | Spoken (right) |
|---|---|
| ప్రారంభించడానికి | స్టార్ట్ చేయడానికి |
| వివరాలు అందిస్తాను | డీటెయిల్స్ చెప్తాను |
| మీకు అనుకూలమైన సమయంలో | మీకు ఎప్పుడు కుదురుతుంది |
| ధన్యవాదాలు | థాంక్యూ సార్ |
| మీ రోజు శుభంగా గడవండి | మంచి రోజు సార్ |
| నేను తెలియజేస్తాను | నేను చెప్తాను |
| ఆసక్తి కలిగి ఉన్నారా | మీకు ఇంట్రెస్ట్ ఉందా |
| సందేహం ఉన్నట్లయితే | ఏదైనా డౌట్ ఉంటే |
| నిర్ణయం తీసుకోవడానికి | డిసైడ్ చేయడానికి |
| ఉత్పత్తి చేస్తాయి | జనరేట్ చేస్తాయి |
| eight నుండి ten గంటల వరకు | eight to ten గంటలు |

**The pattern: short verbs, everyday English loanwords, no compound
noun-phrases.** If a sentence could appear in a government letter, it is wrong.

**Ranges say one frame, not two.** `eight to ten గంటలు`, never
`eight నుండి ten గంటల వరకు`. Saying both halves of the frame is how a document
reads a range, not how a person does.

---

## 6. Numbers are words, not digits

Write `three thousand`, never `3000` or `₹3,000`. The speech engine reads digits
inconsistently and the failure is silent — it sounds fine in the logs and wrong
on the line.

Phone numbers go one English digit at a time: `nine eight four one`.

---

## 7. What to actually talk about

Register is only half of sounding human. The other half is what fills a turn.

**One to two sentences. Never three.** Every extra sentence lowers the chance of
a yes, and on a phone line the caller has no way to skim.

**Acknowledge, then move.** Two words — `మంచిది`, `సరేనండి`, `అర్థమైంది` — before
the next question. Our own caller on run 96 said *"నాకు అసలు క్లారిటీ లేకుండా
ఎలా చేస్తాను, మీరేం చెప్పలేదు కదా"* — I have no clarity, you told me nothing.
The acknowledgement is what stops that.

**Name the choices when the answer is a category.** `ఇల్లా, అపార్ట్‌మెంటా, లేదా
కమర్షియలా` — a caller told the options answers in one word. A caller asked an
open question has to invent the format, and then gets asked again. Run 318's
caller answered a bare property question with *"ఏంటి?"* — what? — and only
answered once the choices were named.

**If they ask, answer. Immediately.** Deferring a direct question to a later
call ends the call in their head. Say what it *depends on* — that is a real
answer — then hand the question back.

**Never manufacture a specific.** This is the one that costs the client, not
just the lead. Run 318 told a factory owner his 300 square metre roof takes
*"సుమారు 30 kW ... 80-100 panels"*. Nobody supplied those numbers. He will
repeat them to a vendor. A number the agent says must come from the knowledge
base or from the caller's own mouth — that is now enforced in code, not prose,
because prose had already failed at it for a month.

**A deferral is a no for today.** *"మేము ఆలోచించి చెప్తాం"* — we'll think and
tell you. Thank them by name and end. Run 314 asked a second time, with
*"దయచేసి"* attached, and got a third and firmer no. There is no version of
asking again that converts a "let me think".

---

## 8. Reusing this for the next client

The shared layers already carry everything above. A new client needs only
Layer 3, and specifically these four fields:

| Field | What it is | Why it cannot be shared |
|---|---|---|
| `vocabulary` | The words this industry's customers actually say | A jewellery caller has never heard of a kilowatt |
| `products` | The knowledge base — facts to answer FROM, never lines to read | It also defines which numbers the agent is allowed to say |
| `questions` | The qualification fields, each with a **spoken** question | The schema hint is not a question; run 298 read one aloud |
| `objection_playbook` | Objections peculiar to this trade | The general ones are already handled |

Everything else — persona, psychology, mission — is inherited unchanged and
improves for every client at once.

**One warning worth repeating.** The knowledge base is *reference*, not script.
It must be written as facts, and the agent told to answer *from* them in its own
words. Written as finished sentences, it gets read out: the compiled prompt once
said *"MB Solar Hub is a solar installation aggregator platform"* and the agent
said exactly that, in English, down a Telugu phone line.

---

## Sources

- [Code-mixing in Telugu-English by college students in Andhra Pradesh](https://www.academia.edu/86736889/CODE_MIXING_IN_TELUGU_ENGLISH_BY_COLLEGE_STUDENTS_IN_ANDHRA_PRADESH_Swathi_B)
- [Creating and evaluating code-mixed Telugu-English datasets](https://arxiv.org/html/2504.21026v1)
- Runs 96, 262, 286, 295, 298, 300, 312, 314, 316, 317, 318 on workflow 2.
