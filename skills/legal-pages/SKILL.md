---
name: legal-pages
description: Create /privacy and /terms pages for an app — Australian-context legal content (Privacy Act 1988/APPs, ACL, not-professional-advice disclaimers) tailored to the app's actual risk profile, plus public routing, Settings/landing links, and render tests. Use when the user asks for a privacy policy, terms & conditions, terms of service, legal pages, or disclaimers for their app.
---

# Legal pages (/privacy + /terms)

Build a public Terms & Conditions page and Privacy Policy tailored to **this specific app**, not a generic template. Written for the Australian context by default.

**You are producing a strong template, not legal advice.** Say so at the end of the task and recommend solicitor review before real users sign up.

## Phase 1 — Understand the app before writing a word

Read the project spec / CLAUDE.md / README and skim the codebase for:

- **What the app does and for whom** — consumers vs business users, free vs paid tiers, age of audience.
- **The app's "regulated neighbour"** — the licensed profession the app looks adjacent to. This drives the core disclaimer:
  - finance/budgeting/investing → not financial/tax/credit advice
  - health/fitness/mental-wellbeing → not medical/psychological advice
  - legal tooling → not legal advice
  - coaching/planning → not a substitute for qualified professional consultation
- **Data flows** — every third-party the app sends data to (auth provider, DB/hosting, analytics/warehouse, background jobs, AI providers, payment processors) and every source it ingests from (APIs, file uploads). These get named by category in the privacy policy.
- **AI usage** — what data is sent to AI providers, for what. Needs BOTH a privacy clause (what's shared, no-training commitment) and a terms clause (AI output can be wrong).
- **Money handling** — if the app only reads/aggregates financial data, say so prominently: read-only tool, not a bank/ADI, cannot hold, transmit, or move funds. If it DOES move money, that's a licensing question — flag to the user rather than drafting around it.
- **Contact email, product name, operator entity name** — from the project. **Never fabricate ABN, ACN, registered state, or company details** — omit or ask.

## Phase 2 — Australian legal content

### Terms & Conditions — clause checklist

- **About the Service** — what it actually does, in its own vocabulary (name the real features and source types).
- **Not professional advice** (the load-bearing clause; make it prominent, bold the key sentences):
  - For financial apps: operator does not hold an AFSL and is not licensed to provide financial product advice under the *Corporations Act 2001* (Cth); not a registered tax agent under the *Tax Agent Services Act 2009* (Cth); content is general information generated from the user's own data and does not consider their objectives, financial situation, or needs; **confirm decisions with an accountant and/or licensed financial adviser**.
  - Adapt the statute references to the domain (health → AHPRA-registered practitioner, etc.).
- **Accuracy of information** — third-party data may be delayed, incomplete, duplicated, or miscategorised; derived figures may be wrong as a result; **AI-generated output can be incorrect**; verify against source records before acting.
- **Eligibility** — 18+ for financial apps; 16+ acceptable for general tools. If workspaces/households share data, users are responsible for access they grant.
- **Connected services** — user warrants authority to connect/upload the data; third-party services governed by their own terms; disconnecting stops new collection.
- **Acceptable use, user content licence** (limited licence to host/process/display solely to operate the service), **IP**, **third-party links**.
- **Australian Consumer Law savings clause** — nothing excludes non-excludable consumer guarantees under the ACL (Sch 2, *Competition and Consumer Act 2010* (Cth)); where liability for breach of a non-excludable guarantee can be limited, limit it to resupply of the services or the cost of resupply (the s 64A pattern). **This clause is what keeps the whole limitation framework enforceable — never omit it.**
- **Warranties disclaimer** — "as is / as available", expressly *subject to* the ACL clause.
- **Limitation of liability** — subject to the ACL clause and to the maximum extent permitted: exclude indirect/consequential loss (including decisions made in reliance on the app); cap total liability at **amounts actually paid in the prior 12 months ("(if any)")**.
  - **Do NOT add a US-style nominal floor ("or $100 if you paid nothing").** A cap is a ceiling on recovery, not an entitlement — but the floor buys nothing in Australia: enforceability rests on the ACL savings clause, not on the cap looking non-illusory (exclusion clauses are enforced per their terms — *Darlington Futures v Delco*). Nil cap for free users is defensible and strictly lower exposure.
- **Indemnity** (carve out loss the operator caused), **suspension/termination** (with survival list), **changes**, **governing law** — "laws in force in Australia" unless the user specifies a state, **contact**.

### Privacy Policy — APP-aligned structure

Frame under the *Privacy Act 1988* (Cth) and the Australian Privacy Principles:

- **What we collect** — account info, the app's actual data categories (name the real source types and upload formats), user-created content, technical data, cookies (state if no ad cookies).
- **How we collect** — directly, automatically, via authorised connections (read-only wherever the provider supports it).
- **How we use it** — service provision, the app's actual processing (analytics, categorisation, gamification…), support, security, legal compliance. State plainly: **we do not sell personal information** (and, if true, no advertising use).
- **AI processing** — what's sent, only to produce the result, providers not permitted to train on it.
- **Who we share with** — provider categories bound to service-only use; legal compulsion; genuine business transfer.
- **Overseas disclosure (APP 8)** — name that providers store/process outside Australia (usually the US); reasonable steps to ensure APP-consistent handling.
- **Security** — encryption in transit, access controls, read-only credentials; no method fully secure; commit to the **Notifiable Data Breaches scheme** (notify affected users + OAIC on likely serious harm).
- **Retention and deletion** — while account active; deletion on request subject to legal retention; note that disconnecting a source ≠ deleting already-imported data.
- **Access, correction, portability** (APP 12/13) — via the contact email.
- **Complaints** — contact operator first; escalation to the **OAIC** ([oaic.gov.au](https://www.oaic.gov.au), 1300 363 992).
- **Children** — align with the terms' age floor. **Changes**, **contact**.

If the app clearly targets non-Australian users too, flag GDPR/CCPA gaps to the user instead of guessing at them.

## Phase 3 — Implementation

- **Public reachability is a gate.** Legal pages must render logged-out. Check the auth middleware: allow-list routes (Clerk `createRouteMatcher` etc.) mean new routes are public by default — verify rather than assume; block-list middleware needs an explicit exception.
- **Route group with shared layout** — e.g. `src/app/(legal)/layout.tsx` + `terms/page.tsx` + `privacy/page.tsx`. Style to match the app's *public/landing* look, not the authed app shell. Keep pages as plain semantic markup (`article`/`h1`/`h2`/`p`/`ul`); apply typography once in the layout (Tailwind arbitrary variants `[&_h2]:…` or the prose plugin). Pure server components → prerender static.
- **Per-page `metadata`** (title + description), a **"Last updated"** date, and cross-links (each page links the other; footer links both + contact email; back-link to `/`).
- **Link surfaces** (all three):
  - landing/marketing page footer;
  - a "Legal" row or card on the app's **Settings** index (signed-in users need a path to the documents);
  - anywhere the user accepts them (sign-up flow) if one exists.
- **Tests** — a render test per page asserting the h1 and the load-bearing disclaimers exist. Assert on `container.textContent`, not `getByText` — bold/`em` spans inside sentences cause multi-element matches.
- **Verify visually** at desktop + 375px mobile before claiming done (long text pages: check no horizontal overflow, links styled visibly).

## Phase 4 — Report back

- Surface the questions only the user can answer: operator entity details (ABN/state) for the governing-law clause, liability-cap amount, age floor, whether a solicitor review is planned.
- State explicitly that the pages are a considered template, **not legal advice**.
