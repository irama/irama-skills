---
name: netdiag
description: Diagnose a slow or unreliable internet connection by measurement instead of rebooting things — locates the fault at LAN, Wi-Fi, router, access line, or ISP, then builds the evidence to escalate. Use when the user says their internet is slow/dreadful/unreliable/dropping out, that pages hang or calls break up, asks to troubleshoot their network or NBN/broadband, or wants to know whether to raise a fault with their provider.
---

Find where a connection is actually failing, by measuring each hop, and stop when
one hop is exonerated. Never diagnose from the user's guess — they report a
symptom ("the NBN is dreadful"), and the symptom names the wrong layer as often
as the right one.

Two ideas carry this whole skill:

- **Loss, not speed.** Users and ISPs both reach for throughput tests, which is
  why bad connections get misdiagnosed for months. A link at full advertised
  speed and 40% packet loss feels broken and tests fine — TCP recovers from loss
  by stalling, so the felt experience is latency while the number is bandwidth.
  Measure loss first; treat a healthy speed test as no evidence at all.
- **Router-side.** A test run from the user's laptop can always be deflected to
  "your Wi-Fi". The same test run *from the router* to the ISP's own gateway
  removes Wi-Fi, LAN, and the client from the path. That single measurement is
  what converts a complaint into a fault the ISP must own, so getting shell on
  the router is the pivot of the whole investigation.

## 1. Measure before touching anything

Run these first, always, before asking the user for anything. Cheap, and they
usually localise the fault on their own.

    # gateway, DNS, interface
    route -n get default | grep -E 'gateway|interface'
    scutil --dns | grep 'nameserver\[' | sort -u

    # LAN control vs WAN — the key comparison
    ping -c 20 -i 0.2 <gateway>
    ping -c 20 -i 0.2 1.1.1.1

    # macOS only: capacity AND idle latency in one shot
    networkQuality

    # TCP-level truth (see §4)
    for i in $(seq 10); do curl -o /dev/null -s -w '%{time_connect}\n' \
      --connect-timeout 6 https://1.1.1.1/; done

    # where does loss begin?
    traceroute -q 5 -w 2 -m 15 1.1.1.1

On macOS also check Wi-Fi signal — `system_profiler SPAirPortDataType | grep -E
'Signal|Channel|PHY Mode'`. Above roughly -70 dBm is healthy; -80 and worse is a
real Wi-Fi problem.

**Retry `networkQuality` once before believing a failure.** It errors against its
own test endpoint on a healthy link — `Code=1003 "Incorrect response status code
on latency measuring connection"` — and passes on the next run. Treat a single
failure as a dud sample, not a signal; two consecutive failures while pings
succeed points at HTTPS interception or a captive portal, not loss.

Report a **repeatable latency outlier** even when loss is zero: a spike an order
of magnitude above the median, appearing in every run, is real but is not a loss
fault — on Wi-Fi it is usually power-save or channel contention. Name it, say it
is not actionable at 0% loss, and move on.

**Completion criterion:** you can state LAN loss %, WAN loss %, idle latency, and
which traceroute hop loss begins at. Do not proceed on partial numbers.

## 2. Read the numbers against this table

Work down it and stop at the first row that matches — each row is a different
fault with a different owner.

| LAN loss | WAN loss | Latency | Verdict |
|---|---|---|---|
| >1% | any | any | **Wi-Fi or LAN.** Signal, channel, cabling, switch. Fault is the user's. Fix here; do not escalate. |
| 0% | >2% | normal on survivors | **Loss fault upstream.** Go to §3 — this is the case the skill exists for. |
| 0% | 0% | idle latency high (>100ms) | **Bufferbloat.** Something is saturating the link. Check utilisation (§3); enable SQM/QoS. |
| 0% | 0% | normal, throughput low | **Genuine speed problem.** Plan tier, peak congestion, or a slow server — not a fault. |
| 0% | 0% | all normal | **Not the network.** Look at DNS resolution time, the specific app, or the destination. |

`networkQuality`'s **idle latency** is the most underrated number here: measured
with no load, so a high value cannot be blamed on the user's own traffic.

**Completion criterion:** one row named, with the numbers that selected it.

## 3. Get router access — the pivot

Reaching §3 means loss is upstream of the client and you need to measure from the
router. This is the one place the skill needs something only the user can give:
their router's admin credentials are theirs, so enabling SSH is their action.

Ask for it in one message, with the exact clicks, and explain *why* you need it —
that router-side loss is what an ISP cannot deflect. Full per-vendor
instructions, the key setup, and the security shape of the request:
[`ROUTER-ACCESS.md`](ROUTER-ACCESS.md).

Never ask for a router password. Ask them to install a public key.

Once in, run all four — each kills a different explanation:

    # a) THE decisive test: router -> ISP's own gateway, one hop away
    ping -c 100 -W 2 -q $(nvram get wan0_gateway)     # ASUS/busybox
    ping -c 100 -W 2 -q 1.1.1.1

    # b) WAN interface error counters
    cat /proc/net/dev        # read the WAN iface row: errs, drop, frame, carrier

    # c) link state and syslog — flaps, PPPoE/DHCP renegotiation
    ethtool <wan_iface> | grep -Ei 'speed|duplex|link'
    cat /tmp/syslog.log | grep -viE 'vpnclient|openvpn' | tail -30
    uptime

    # d) live utilisation — is the user saturating their own uplink?
    #    sample the WAN iface byte counters in /proc/net/dev 5s apart

Interpretation, and this is the part that decides who gets the ticket:

- **Interface errors > 0** (errs/frame/carrier climbing) → **physical fault**
  between router and modem/NTD: cable, port, or NTD. Often the user's to fix.
- **Interface errors 0, uplink mostly idle, no link flaps, yet router→gateway
  loses packets** → **the fault is upstream. The ISP owns it.** Nothing on the
  user's side can produce this.
- **Uplink >70% utilised** → self-inflicted saturation. Find the uploader
  (backup, sync client, seedbox) before blaming anyone.
- **Link flaps / repeated DHCP or PPPoE renegotiation in syslog** → unstable
  access line; quote the timestamps.
- **Router uptime long and WAN IP unchanged** across a fix → proof the change was
  upstream, not a local reset. Capture both before and after.

Watch for a **symptom masquerading as a cause**: a VPN client or tunnel
reconnecting every few minutes looks alarming in syslog but is usually the loss
biting it, not the source. A userland client cannot cause 50% ICMP loss to a
gateway one hop away on an idle link. Say so rather than chasing it.

**Completion criterion:** router-side loss % stated, interface counters stated,
utilisation stated, and one owner named — user, physical, or ISP.

## 4. Pre-empt the two deflections

Both will come up, from the ISP or from a sceptical reader. Have the answer in
the evidence before it is asked.

- **"Ping is ICMP, it's deprioritised, that's not a real test."** Sometimes
  legitimately true. Answer it with TCP: handshake times of ~1.0s and ~2.0s are
  SYN retransmissions at the standard 1s/2s RTO. A ladder of 1.02 / 2.02 / 5.0 /
  timeout against 15ms on success **is** packet loss, at the transport layer, and
  is not arguable. Always collect this alongside the pings.
- **"Your Wi-Fi / your router / reboot it."** Answered by router-side loss plus
  zero interface errors plus an idle uplink. State that the modem has already
  been power cycled.

Also **check the provider chain before naming anyone.** Traceroute rDNS often
shows a *wholesale carrier*, not the company the user pays — a retailer reselling
someone else's network. Escalate to the retailer only; they own the customer
relationship. Web-search the retailer's current wholesale arrangement rather than
inferring it from hostnames, and note the POI and CGNAT range from the traceroute.

## 5. Monitor continuously

One sample is a moment; a fault needs a pattern, and time-of-day shape separates
congestion from a hardware fault.

Run [`netwatch.sh`](netwatch.sh) — logs LAN loss, WAN loss, DNS time, TCP connect
time, and router-side loss to CSV, one row per run. Install it on a 5-minute
schedule (macOS launchd; see the header comment in the script for the plist).
Point it at the router with `NETDIAG_ROUTER`, `NETDIAG_SSH_PORT`,
`NETDIAG_SSH_USER`; the router column is skipped cleanly if SSH is unavailable.

Roughly 30 minutes of samples is enough to open a fault when every sample shows
loss. Do not wait for a full day of data before escalating — the provider's own
line test takes days, so lead time beats completeness, and later samples attach
to the same ticket. Say this explicitly when the user asks whether to wait.

**Completion criterion:** the CSV exists, has more than one row, and you can
state min/median/max loss and how many samples were clean.

## 6. Escalate

When §3 named the ISP, write the fault report and the ticket text:
[`TICKET.md`](TICKET.md).

## 7. Stand down

When the fault is fixed or the user calls it off, close what you opened — leaving
a router shell exposed is a real cost of this investigation:

    # stop monitoring, keep the data
    launchctl bootout gui/$(id -u)/org.netdiag.watch

    # disable router SSH (ASUS), then VERIFY the port refuses
    ssh -p <port> <user>@<router> 'nvram set sshd_enable=0; nvram commit; \
      nohup service restart_sshd >/dev/null 2>&1 &'
    nc -zvw5 <router> <port>      # must be refused

Keep the CSV and the report — a documented baseline makes a recurrence far
faster to prove the second time.

**Completion criterion:** SSH verified refused, monitoring confirmed unloaded,
evidence files listed for the user.

## Confirm the fix, don't assume it

When the user thinks it is fixed, re-run §1 *and* the §3 router-side test and
present before/after side by side. A fix shows as loss to zero, idle latency
collapsing, and TCP retransmits disappearing entirely — the retransmits are the
cleanest signal, since a single 1.02s handshake means it is not fixed.

Expect throughput to *rise* after a loss fix; loss suppresses measured speed, so
the user was never seeing their real plan.

Flag two things honestly rather than declaring victory: a **momentary total
blackout** in the log right before recovery is usually the repair itself (link
bounce or reroute) — quote its timestamp. And when two measurements of the same
path disagree, say so and retest rather than reporting the worse one; repeated
large ping bursts can trip **ICMP rate-limiting** on an ISP gateway, which looks
exactly like loss but does not reproduce.

Advise against closing the ticket immediately. If the fix was congestion rather
than hardware it returns at peak, and monitoring already running is worth more
than monitoring restarted after a relapse.
