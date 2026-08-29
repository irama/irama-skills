#!/bin/bash
# netdiag continuous monitor. One CSV row per run.
#
#   ts,iface,gw,gw_loss,gw_ms,wan_loss,wan_ms,dns_ms,tcp_connect_s,tcp_fails,rtr_isp_loss
#
# gw_loss is the control (client -> own router): if it is not ~0, the fault is
# LAN/Wi-Fi and nothing further in this file means anything.
# rtr_isp_loss is router -> the ISP's own gateway: the figure an ISP cannot
# deflect. Blank when router SSH is unavailable; every other column still fills.
#
# Config (all optional):
#   NETDIAG_DIR=~/netdiag  NETDIAG_ROUTER=<ip, default = detected gateway>
#   NETDIAG_SSH_PORT=22    NETDIAG_SSH_USER=admin
#
# Schedule on macOS every 5 min — write ~/Library/LaunchAgents/org.netdiag.watch.plist
# with Label org.netdiag.watch, ProgramArguments [<this script>],
# StartInterval 300, RunAtLoad true, then:
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.netdiag.watch.plist
#   launchctl bootout   gui/$(id -u)/org.netdiag.watch      # stop, keeps the CSV
#
# ponytail: flat CSV + launchd, no daemon or DB. A TSDB only if this outgrows a
# spreadsheet, which for a fault ticket it never has.

set -u
DIR="${NETDIAG_DIR:-$HOME/netdiag}"; mkdir -p "$DIR"
CSV="$DIR/netwatch.csv"
IFACE=$(route -n get default 2>/dev/null | awk '/interface/{print $2}')
GW=$(route -n get default 2>/dev/null | awk '/gateway/{print $2}')
ROUTER="${NETDIAG_ROUTER:-$GW}"
PORT="${NETDIAG_SSH_PORT:-22}"
USER_="${NETDIAG_SSH_USER:-admin}"

[ -f "$CSV" ] || echo "ts,iface,gw,gw_loss,gw_ms,wan_loss,wan_ms,dns_ms,tcp_connect_s,tcp_fails,rtr_isp_loss" > "$CSV"

# host -> "loss_pct avg_ms"
p() {
  local o; o=$(ping -c 20 -i 0.2 -t 5 "$1" 2>/dev/null)
  echo "$(echo "$o" | awk -F'[ %]' '/packet loss/{print $7}') $(echo "$o" | awk -F/ '/round-trip/{printf "%.1f",$5}')"
}
read -r GL GM < <(p "$GW")
read -r WL WM < <(p 1.1.1.1)

DNS=$( { /usr/bin/time -p dig +tries=1 +time=2 @1.1.1.1 example.com >/dev/null; } 2>&1 \
  | awk '/real/{printf "%.3f",$2}')

# TCP connect times: ~1.0s / ~2.0s are SYN retransmits at the standard RTO, i.e.
# real loss. This is what answers "ICMP is deprioritised, ping proves nothing".
FAILS=0; SUM=0; N=0
for _ in 1 2 3 4 5; do
  t=$(curl -o /dev/null -s -w '%{time_connect}' --connect-timeout 6 https://1.1.1.1/ 2>/dev/null) \
    || { FAILS=$((FAILS+1)); continue; }
  SUM=$(echo "$SUM + $t" | bc); N=$((N+1))
done
AVG=$( [ "$N" -gt 0 ] && echo "scale=3; $SUM/$N" | bc || echo "" )

# busybox ping on the router: no fractional -i, so -c/-W/-q only.
RTR=$(ssh -p "$PORT" -o BatchMode=yes -o ConnectTimeout=8 "$USER_@$ROUTER" \
  'G=$(nvram get wan0_gateway 2>/dev/null); [ -n "$G" ] || G=1.1.1.1
   ping -c 30 -W 2 -q "$G" 2>/dev/null | sed -n "s/.*, \([0-9]*\)% packet loss.*/\1/p"' 2>/dev/null)

echo "$(date -Iseconds),$IFACE,$GW,$GL,$GM,$WL,$WM,$DNS,$AVG,$FAILS,$RTR" >> "$CSV"

# Self-check: NETDIAG_SELFTEST=1 ./netwatch.sh asserts a well-formed row was
# appended, so a silently-broken parser is caught rather than logging blanks.
if [ "${NETDIAG_SELFTEST:-0}" = "1" ]; then
  row=$(tail -1 "$CSV")
  [ "$(echo "$row" | awk -F, '{print NF}')" = "11" ] || { echo "FAIL: want 11 fields, got: $row" >&2; exit 1; }
  echo "$row" | awk -F, '$4=="" || $6=="" {exit 1}' || { echo "FAIL: loss columns empty: $row" >&2; exit 1; }
  echo "OK: $row"
fi
