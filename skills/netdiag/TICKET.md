# Escalating to the provider

Reached only when SKILL.md §3 named the **ISP** as owner. Two artefacts: a full
report to attach, and a short description to paste into a form.

## Before writing

- **Identify the retailer** — who the user pays. Web-search their current support
  contacts (phone, email, portal) rather than reciting remembered ones; telco
  contact details churn. Prefer the 24/7 technical line over email: a phone call
  yields a reference number immediately, then email the report quoting it.
- **Check the provider's network status page first.** A known incident means the
  user just waits.
- **Do not contact the wholesale carrier**, even when traceroute is full of their
  hostnames. They have no relationship with the user, and the retailer must raise
  it. Explain this — the hostnames confuse people into ringing the wrong company.
- **Collect the identifiers you cannot derive**: account number, service address,
  service ID (in Australia, the nbn AVC). Leave them as explicit `[fill in]`
  placeholders and tell the user which ones to complete.

## The full report

Write it as Markdown at `~/netdiag/<provider>-fault-report.md`, then zip it with
the CSVs. Sections, in order:

1. **Identifiers** — customer, account, address, service ID, plan, router model
   and firmware, WAN IP and whether CGNAT, date/time window of testing in the
   user's local timezone.
2. **Summary** — one paragraph, leading with the headline loss figure and the
   words *this is loss, not speed*. State that tests were run from the router, so
   no customer equipment is in the measurement path.
3. **The decisive table** — router→ISP gateway loss, router→public DNS loss, and
   LAN loss as the control on the same rows.
4. **Customer-side causes eliminated** — a table of check → result → what it rules
   out. This is the section that gets you past L1 triage, so make it exhaustive:
   interface error counters with the packet count they are drawn from, link
   speed/duplex, syslog quiet on flaps, uplink utilisation, router load, LAN loss,
   a second device on a separate path, and the power cycle already performed.
5. **TCP-level confirmation** — the handshake times, explicitly labelled as SYN
   retransmissions at 1s/2s RTO, contrasted with the ~15ms successes.
6. **Traceroute** — annotated: hop 1 answers every probe, loss begins at hop N.
   Note which hops belong to the wholesale carrier and that this is expected.
7. **Continuous monitoring** — min/median/max per metric, sample count, window,
   and how many samples were clean. "0 of 27 clean" is the strongest single line
   in the document.
8. **Requested action** — numbered, specific: line test, check the access service
   for errors and discards, check upstream aggregation for the CGNAT range at the
   named POI, raise a wholesale/nbn fault if the line shows errors.
9. **Attachments** — list them.

Close the requested-action section by asking to **escalate past reboot-level
triage**, justified by the measurements, and note the power cycle is already done.

## The short description

Support forms cap the description field, commonly at 1000 characters. Write to the
cap and **count it** (`wc -m`) — do not estimate.

Priority order when cutting, most valuable first:

1. **"Measured FROM MY ROUTER"** — the phrase that kills the Wi-Fi deflection
   before it starts. Never cut.
2. **Loss % to the ISP's own gateway, one hop away**, with the packet count.
3. **N of N samples show loss** — rules out "intermittent, try again later".
4. **LAN loss 0.0%** — the control. Proves the measurement rig is sound.
5. **Zero interface errors / uplink % idle / already power cycled** — pre-empts
   the three standard triage deflections in one clause.
6. **TCP retransmit evidence** — pre-empts the ICMP objection, which a competent
   L2 technician *will* raise.
7. WAN IP, router model, connection type.
8. Requested actions, compressed to one sentence.

Cut first: the traceroute (it is in the zip), any second public-DNS figure
(redundant), router load average, uptime, and everything about the second device
beyond a single clause.

Tell the user what you cut and why, so they can add it back if the agent on the
phone asks.

## After submitting

- Keep monitoring running. Fresh samples attach to the same ticket and answer
  follow-up questions without re-litigating.
- Offer to re-run the router-side test on demand — it takes 30 seconds and gives
  a freshly timestamped figure when they push back.
- If the provider insists on a power cycle first: agree, do it, then report that
  loss persisted. Refusing their script wastes more time than complying does.
- **Do not close the ticket the moment it works.** Ask what they found; a cause on
  record protects the user if it recurs.
