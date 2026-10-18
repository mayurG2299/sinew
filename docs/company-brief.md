# The made-up companies: what you need to know to test Sinew

Demo "today" is **Saturday 17 October 2026, 12:00**. "This week" = 10–17 Oct. All people, customers and numbers are made up.

## Northwind Goods (the main story)

An online store selling **kitchen, home, audio, fitness and outdoor** products in three regions: **west, north, south**.
About **200 customers**, **600 orders in the last 30 days**, **133 support tickets**.

### How parcels move
Parcels go from a first hub to a last-mile hub, carried by a courier.

| Hub | Region | Courier | Capacity (parcels/day) |
|---|---|---|---|
| W1 | west | Courier X | 12 |
| **W2** | west | **Courier Y** (since 18 Aug; before that Courier X) | **14** |
| W4 | west | Courier X | 10 (the spare route) |
| N1, N2 | north | Courier Z | 10, 8 |
| S1, S2, S3 | south | X, Z, X | 10, 8, 6 |

West orders normally go **W1 → W2 → customer**, promised within **2 days**.

### People (sign in as them)

| Person | Job | Can see | Refund limit |
|---|---|---|---|
| Daniel Reyes | CEO | everything | — |
| Grace Okafor | Head of support | support, operations; privacy requests | $2,000 |
| Meera Nair | Team lead, west | support, operations | $500 |
| Ravi Kumar, Anna Schmidt | Support agents, west | west customers; support, operations | $100 |
| Tom Becker, Li Wei | Support agents, north | north customers | $100 |
| Sofia Rossi | Support agent, south | south customers | $100 |
| Karan Mehta | Contractor (overflow queue) | only customers with a ticket in his queue; no payments; no operations | — |
| Lucas Martin | Logistics manager | operations, support | — |
| Chloe Dubois | Brand marketer | marketing, operations (no costs, no customers) | — |
| Priya Raman | CMO | marketing, operations, **finance** | — |
| Ken Watanabe | Analyst | support, operations, marketing | — |

Everyone also reads company-wide policies.

### What happened (the story Sinew should find)

| Date | Event |
|---|---|
| 18 Aug | **Lucas** moves west deliveries to **Courier Y** to cut cost (about 12% cheaper per parcel). Assumes **Courier Y is ≥ 90% on time through Hub W2**. |
| 7 Sep | **Grace** sets the **2-day delivery standard** for the west (assumes W2 ≥ 85% on time). |
| 17 Sep | **Lucas** ends the **backup courier** contract (assumes W2 alone can carry west volume). |
| 5 Oct | **Chloe** decides the **Festive Flash Sale**: 40% off kitchen, code **FEST40**, 7–19 Oct, west. Delivery capacity was **not** checked with logistics. |
| 7–17 Oct | FEST40 floods Hub W2: **1.57× its capacity**. Courier Y falls to **77% on time**. **22 late-delivery complaints**, all through W2; 58% of W2's parcels used the FEST40 coupon. |
| 15 Oct | **Chloe** decides the **Winter Sale**: 25% off home, code **WINTER25**, starts **27 Oct** (in 10 days), also through W2. |
| Now | **21 customers** still waiting on **25 parcels** at W2 (12 late). Option: route the Winter Sale through **Hub W4** instead. |

A second, separate problem: **Batch B7 of the Blender X** (supplier S3) has **62.5 complaints per 100 orders**, against 22.2 for all products.

### This week in numbers
- Tickets **54** (29 last week) · open tickets 59 · overdue agreed refunds 10
- Deliveries on time **85%** company-wide; **Hub W2 77%** (worst); 14 parcels late now
- Orders **191** (153 last week); 31% used a coupon
- Revenue **$17,949.49** (+25%); refunds paid $1,830.19 *(finance only)*
- Costs per parcel: Courier X $4.80, **Courier Y $4.20**, Courier Z $5.10; FEST40 ad spend $3,500; Winter Sale budget $4,000 *(finance only)*

### Customers worth knowing
| Customer | Situation |
|---|---|
| **Desiree Davis** | Wrong item on **#4397**; a refund of $64.38 was agreed for 15 Oct and **not paid**; she wrote again on 16 Oct |
| **Ladli Kakar** | Refund for **#4156** ($98.53) overdue since 3 Oct; two more orders late at W2 |
| **Laura Phillips** | **#4520** (Kettle Pro, Blender X, $75.85) **30 h late at W2**; new delivery date agreed for 18 Oct |
| Order **#4581** | Coffee Grinder, $65.81, FEST40, in transit (not late) |

### Documents Sinew can read
| Document | Area (who can read it) |
|---|---|
| Refund policy (limits $100 / $500 / above; refund within 3 working days; returns 30 days) | everyone |
| Delivery standard: west region (2 days; what to do when late) | everyone |
| Courier Y agreement, service terms (90% on time; review after 60 days) | operations |
| Ops meeting notes, 18 Aug and 17 Sep | operations |
| Festive Flash Sale plan, Winter Sale plan | marketing |
| Cost sheet, October | **finance only** (CEO, CMO) |

There is **no leave policy, HR, or anything outside these** — Sinew should say it has no information.

## Larkspur Home (the second company)

A smaller home-goods store (lamps, rugs, throws, vases, chairs) in **east and central**. Its data arrives in other systems' formats
(a Shopify-like store, a Zendesk-like helpdesk, a courier feed) and is mapped in, which shows Sinew works for any company.

- **Story:** on 7 Sep **Hannah Berg** (logistics) moved east deliveries to **Courier Q**, assuming **92% on time through Hub E2**.
  It is now **66%**; **7 late-delivery complaints** this week all went through E2. No campaigns involved.
- **People:** Felix Moreau (care agent, east), Asha Rao (care agent, central), Imogen Hale (care lead), Hannah Berg (logistics),
  Mateo Silva (head of operations; sees everything).
- **No cost data** at Larkspur: cost questions should get "no information".

## Good questions to try
- As **Daniel**: "Why are complaints up this week, and what should we do?" · "Is batch B7 a problem?" · "What should I worry about?"
- As **Ravi**: click Desiree Davis · "can I refund $150 myself?" · "where is order 4520?"
- As **Chloe** vs **Priya**: "How is the company doing this week?" · "What does Courier Y cost per parcel?"
- As **Lucas**: "how's W2 holding up?" · "Tell me about the courier Y switch"
- As **Karan**: "Why are complaints up?" (should be refused)
