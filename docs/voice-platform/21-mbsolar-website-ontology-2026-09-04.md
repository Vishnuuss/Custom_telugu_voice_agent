# MB Solar Hub — ontology for the voice agent

Built 2026-09-04 from the live site (43 pages, re-fetched; content unchanged
since the Aug 30 scrape apart from nav stripping).

Purpose: the agent must answer ANY website question correctly, scoped to what
was asked, explained simply. This is the map it answers from. It is NOT a script.

---

## 0. The root fact everything hangs off

**MB Solar Hub is an aggregator. It does not sell solar and does not install it.**
Its own line: "We don't sell solar. We connect you to the best people who do."
It connects customers to admin-verified solar vendors; the vendor the customer
picks does the installation, the paperwork, the DISCOM approval and the net
metering.

Every answer must stay consistent with this. The commonest failure mode for this
agent is talking like a solar company. It is a marketplace.

**Free for the customer. No middlemen calls. The customer chooses the vendor.**

---

## 1. The five service families (the site's own top-level menu)

The site groups everything five ways. A caller asking "what do you provide?"
should hear these five, briefly — not a list of 21 items.

### FAMILY A — PM Surya Ghar / Residential (who: homeowners and housing communities)

| Sub-service | Who it is for | The one thing they need to know |
|---|---|---|
| Residential (PM Surya Ghar) | Independent house owners | Central subsidy paid direct to their bank account |
| GHS (Group Housing Society) | Society management committees | Targets shared load: lifts, water pumps, corridor lights, security. Bulk subsidy tier |
| RWA (Resident Welfare Association) | Registered colony/township associations | Common-area power; community funds protected by comparing verified bids |
| Apartments | Top-floor owners, apartment managers, builders | Shared-roof and vertical-wiring engineering; specialist vendors, not generalists |

### FAMILY B — Commercial (who: businesses)

| Sub-service | Who it is for | The one thing they need to know |
|---|---|---|
| Offices | Corporates, facility managers, builders | HVAC and server load; installed without disrupting working hours |
| Warehouses | Logistics, cold chain operators | Huge unshaded metal roofs; lightweight mounts so roof safety is not compromised |
| Schools / Colleges / Hospitals | Trusts, institutional boards | Hospitals need unbroken critical power, so hybrid plus battery storage |

### FAMILY C — Industrial (who: heavy industry)

| Sub-service | Who it is for | The one thing they need to know |
|---|---|---|
| Ground Mounted Solar | Plants with spare or non-arable land | No roof angle limits; sun-tracking systems generate more |
| Battery Storage (BESS) | Round-the-clock factories | "Peak shaving" — run off stored power during the utility's costliest hours |
| Industrial Solar Plants | Steel, cement, textiles, pharma, chemicals | Power is a large share of operating cost; open access and substation synchronisation |

### FAMILY D — Manufacturers Hub (who: buyers AND trade)

This family is a *supplier directory*, not an installation service. It connects
manufacturers, dealers, distributors, EPC firms and service providers.

| Sub-service | Note |
|---|---|
| Solar Panels | Compare brands, specs, nearby dealers |
| Solar Inverters | Categories: string, hybrid, commercial/industrial, grid-tied, off-grid, micro |
| Solar Structures | Rooftop, ground mount, carport, industrial, agricultural, utility-scale |
| Solar Earthing | Safety and surge protection. **Site inconsistency: the page is titled "Solar Earthing" but its breadcrumb and supplier lists say "Solar Injector". Treat it as earthing; do not say "injector" to a caller.** |
| Solar EV Charging | Home, office parking, public stations, fleets, malls and hotels |

### FAMILY E — Services (who: anyone; these are standalone products)

| Sub-service | Who it is for | The one thing they need to know |
|---|---|---|
| Solar Hybrid System | Anyone with power cuts | Unlike on-grid, it keeps running during a cut by switching to battery |
| Solar Hot Water | Homes, hotels, hospitals | Water heating is a large share of the bill; stays hot overnight |
| Solar Pumps | Farmers, plantations, rural townships | Replaces diesel; daytime irrigation without waiting for rural grid |
| Solar Fencing | Farms, remote and industrial property | Safe deterrent pulse, not harmful; off-grid perimeter |
| Solar Street Lights | RWAs, builders, corporates, campuses | All-in-one pole, no trenching or wiring; dusk-to-dawn and motion sensors |
| Solar CC Cameras | Remote sites, construction, farms | Standalone: solar plus 4G/5G, works with no power or internet line |
| Solar Accessories | Installers, contractors, DIY | Mounting, DC cables, lightning arrestors, SPDs, cleaning tools |

---

## 2. The customer journey (the site's 4 steps) — answer "how does it work?" with this

1. **Select location** — so nearby vendors can be matched.
2. **Review vendor profiles** — services, past projects, reviews, response time.
3. **Request quotes** — from shortlisted vendors, and compare them.
4. **Choose a vendor** — that vendor installs, and handles paperwork, DISCOM
   approval, installation and net metering.

Most vendors reply within **2-4 hours** (the site also states 48h as an outer bound).

---

## 3. PM Surya Ghar Muft Bijli Yojana — the scheme most callers actually mean

These are the **government's published MNRE rates** and may be stated as such:

- Rs 30,000 per kW for the first 2 kW
- Rs 18,000 per kW above that, up to 3 kW
- **Capped at Rs 78,000** for systems of 3 kW and above
- GHS/RWA: Rs 18,000 per kW for common facilities including EV charging, up to
  500 kW (at 3 kW per house), inclusive of individual rooftop plants
- A well-sized system generates roughly **400 units a month**
- Scheme approved **February 2024**
- Subsidy is credited **directly to the customer's bank account**

---

## 4. Contact and identity (asked often; must be exact)

- **Address:** MAK Elite, GF2, Prashanthi Hospital Road, 2nd Right, MG Road,
  Vijayawada - 520010
- **Phones:** +91 91339 92799 and +91 79974 66699
- **Email:** mbsolarhub@gmail.com
- The company is **Vijayawada-based (Andhra Pradesh)**. Its gallery and events
  are in Vijayawada, Nellore and Tirupati. The site claims nationwide coverage;
  the demonstrated footprint is coastal Andhra. Say "across India" only as the
  platform's claim, and never invent a local branch.

**Speaking rule (ties to the Layer 1/2 work):** phone numbers are read in
English, two digits at a time. "." is said as "dot", never "chukka".

---

## 5. Real projects that can be named (from the gallery)

- 85 kW school solar project — vendor Niksol Solar (Sudha Kiranmai)
- 5 kW apartment solar — vendor Sunvision Solar (Konteswaramma Shesham)
- A solar temple project — Niksol Solar
- A PM Surya Ghar project — Sunvision Solar; 42 projects completed
- Awareness events: Nellore Municipal Grounds, Tirupati Convention Hall,
  Vijayawada Auditorium

## 6. Careers (a real caller intent — the site lists open roles)

Solar Panel Technician, Sales Executive, Site Supervisor, Team Leader Marketing,
Team Leader Promotions, Digital Marketing Executive, AI Video Creator, AI Content
Writer, AI Editor. **Freshers can apply for internships** in the AI and digital roles.

---

## 7. The FAQ gap — IMPORTANT

`faq.php` lists 7 questions and **carries no answers in the page text** (they are
collapsed behind JS). These are the questions the site itself expects, so the
agent MUST be able to answer them. Answers derived from the rest of the site:

| Question | Answer the agent should give |
|---|---|
| Does MB Solar Hub sell solar panels? | No. It connects you to verified vendors who do. |
| Is MB Solar Hub free for customers? | Yes, free for customers; no middlemen calls, and you choose who contacts you. |
| How are vendors verified? | Admin-verified on merit, credentials and genuine reviews before listing. |
| Can I get the PM Surya Ghar subsidy through MB Solar Hub? | Yes — a scheme-registered vendor handles documents, DISCOM approval and net metering; eligibility and amount are decided by the government. |
| Which regions does it cover? | The platform lists vendors across India and matches by your location. |
| How long for a vendor to respond? | Usually 2-4 hours; most within 48 hours. |

---

## 8. Claims that must NEVER be stated as fact by the agent

These appear on the site as marketing. They are not promises the agent can make.

- "90-99% reduction in electricity bills"
- "3-4 year payback", "2-year payback" (hot water), "up to 12% more" (trackers)
- "40% tax depreciation"
- "India's No.1", "the only option", "India's leading"
- "300+ free units" (the site says both 300+ and 400+; the MNRE figure is ~400)
- "The scheme is closing after 1 crore installations"
- Any specific price, any brand guarantee, any timeline.

Rule: price, subsidy amount, payback and timeline always depend on assessment,
vendor and government rules. Say that instead.

---

## 9. What the agent must collect (unchanged from the current KB)

Name, mobile number, location, electricity consumption or latest bill, property
type, roughly how much roof. **The bill matters most — it decides capacity.**

---

## 10. Answering policy — how to use this map

- Answer the question that was asked, at the level it was asked. A caller asking
  "do you do solar for my factory?" gets Family C, not all 21 services.
- "What services do you provide?" gives the five families in one short breath,
  then asks which one fits them. Never recite 21 items.
- Explain simply. No jargon unless the caller used it first. If a term must be
  used (net metering, DISCOM, EPC), explain it in half a sentence.
- Never turn into a brochure. One or two facts, then back to the caller.
