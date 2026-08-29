# Getting shell on the router

Router-side measurement is the pivot of `netdiag` — it is what an ISP cannot
deflect to "your Wi-Fi". Enabling it needs the router's admin login, which is the
user's to hold, so this is one of the few genuine asks in the skill.

## Shape of the request

- **Ask for a public key install, never a password.** The user pastes your public
  key into the router; you never hold a credential, and the key cannot be used to
  log into the web UI.
- **Give the exact menu path**, not "enable SSH". Verify against the vendor's
  current docs if the model is unfamiliar; firmware UIs move.
- **Say why**, in one line: router-side loss is the measurement the ISP must own.
  Users approve this readily once they see it is the difference between a fault
  ticket and a shrug.
- **LAN only.** Never `LAN + WAN` — that exposes a router shell to the internet.
- **Close it afterwards** (SKILL.md §7), and verify the port refuses.

Print the key for them to copy:

    cat ~/.ssh/id_ed25519.pub    # create with ssh-keygen -t ed25519 if absent

Probe first — it may already be on, and the port is often not 22:

    nc -zvw3 <router-ip> 22
    nc -zvw3 <router-ip> 1024

## ASUS (ASUSWRT / Asuswrt-Merlin) — verified on RT-BE86U

1. Browse to the router IP, sign in as admin.
2. **Advanced Settings** → **Administration**.
3. Top tab row → **System**.
4. Find the **Service** section (newer ASUSWRT UI may label it **Local Access
   Config**). The UI search box, top-right, finds it on `SSH`.
5. Set:
   - **Enable SSH** → `LAN only`
   - **Allow Password Login** → `No`
   - **SSH Authentication key** → paste the public key, one line, unwrapped
   - **SSH service port** → note whatever it is; non-default is common and fine
   - **Idle Timeout** → `0`, or it drops mid-capture
6. **Apply**, wait ~20s for the service restart.

Ask for the **username** too — ASUS uses the admin account name, which is often
not `admin`.

Verify, and capture the model while you are there:

    ssh -p <port> -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      <user>@<router-ip> 'nvram get productid; nvram get buildno; uname -a'

Useful ASUS specifics:

- WAN interface and gateway: `nvram get wan0_ifname`, `wan0_gateway`,
  `wan0_ipaddr`, `wan0_proto`
- Syslog: `/tmp/syslog.log`, `/tmp/syslog.log-1`
- `ping` is busybox — **no fractional `-i`**. `-i 0.2` prints usage and silently
  gives you nothing; use `ping -c N -W 2 -q <host>`.
- Suppress the OpenSSH post-quantum warning in captured output by filtering
  `post-quantum` and `store now` from stderr.
- Disable again: `nvram set sshd_enable=0; nvram commit; service restart_sshd`
  (`sshd_enable` = 0 off, 1 LAN+WAN, 2 LAN only).

## Other vendors

Unverified — check the vendor's current docs before instructing the user, and
prefer the vendor UI over telnet backdoors.

- **OpenWrt** — SSH (dropbear) is on by default; keys at System → Administration
  → SSH-Keys. Richest data of any platform: `ifstatus`, `logread`, full `ip`.
- **Ubiquiti UniFi** — enable in the controller: Settings → System → Advanced →
  **Device SSH Authentication**, plus SSH keys. Shell is on the gateway, not the
  controller.
- **Fritz!Box, Telstra/Optus/TP-Link ISP-supplied units** — usually no SSH at
  all. Fall back to the web UI's own diagnostics page and statistics/DSL error
  counters, and screenshot them. Client-side tests plus TCP retransmit evidence
  (SKILL.md §4) still make a workable case; you lose the router-side test, so say
  so plainly rather than implying the case is as strong.

If no router access is obtainable at all, the investigation still works — it is
just deflectable. Lean harder on the TCP retransmit ladder and on a second device
on a separate path showing identical symptoms.
