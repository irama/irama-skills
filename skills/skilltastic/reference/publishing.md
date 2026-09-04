# Keeping a public repo publishable

Read this when installing the guard in a repo, writing its two lists, or working
out what a finding means.

**The guard is `assets/check-no-leaks.py`. It is vendored, not shared** — one
copy per repo, all copied from this skill. Edit it here and copy it out again,
never the other way round. CI checks out a repo, not a home directory, so a
symlink to a skill folder does not survive the trip.

## Install

```bash
mkdir -p scripts .githooks
cp <skill-dir>/assets/check-no-leaks.py scripts/
git config core.hooksPath .githooks
python3 scripts/check-no-leaks.py --selftest
python3 scripts/check-no-leaks.py --all
```

`.githooks/pre-commit` runs it over the staged diff. `.githooks/pre-push` runs
it over the authorship of the commits about to leave, because an author line is
metadata rather than a file and the content check cannot see it. Both hooks are
four lines; copy them from a repo that already has them.

In CI, one step:

```yaml
- name: Publishable
  run: python3 scripts/check-no-leaks.py --all
```

A hook is a local convenience and can be skipped with `--no-verify`. CI is the
one that actually holds, so wire both.

## The two lists

**`.leakrc` — the private literals. Gitignore it.** A guard that spells out the
domains it blocks and the names whose speech it refuses publishes both to
everyone who reads the guard. That is the failure it exists to prevent,
committed by the guard itself.

```
example-private-domain.test        a domain that must never appear
names: Surname                     someone who works on this repo
commands: internal-verb            a group read by another tool
```

A bare line is a domain. A `group: value` line belongs to a different reader, so
a domain never contains a colon and that is the whole test. The guard looks for
`$LEAKRC`, then the repo's own `.leakrc`, then a shared one in the config
directory — so a repo with no list of its own still gets covered, which is the
case that leaked.

Set `LEAK_PRIVATE_DOMAINS` and `LEAK_TEAM_NAMES` instead if a file is awkward.
With neither set the three private rules simply do not run, which is correct for
anyone who cloned the repo and has no such list.

**`skills/PUBLIC` — one skill name per line, committed.** A file staged under
`skills/<name>/` is refused unless the name is listed. Adding a line is a
decision: everything in that folder becomes public on push. A skill that only
ever talks to private infrastructure belongs in a private config repo — it
exposes the shape of that infrastructure and does nothing in anyone else's
hands.

## The findings

| Finding | What to do |
|---|---|
| absolute home path | Use `$HOME`, `~`, or `Path.home()`. This is a portability bug as much as a disclosure one — the path is simply not there on anyone else's machine. |
| possible API key, token, private key, JWT | Rotate it, then remove it. A commit is not the end of its life; a push is. |
| private app domain | Describe it generically. A war story that names a private app is how the inventory leaks back one line at a time. |
| personal email · personal launchd label | Use the noreply address, or a generic label. |
| quoted working conversation | Paraphrase the substance. The repo records the decision and the reason, never a quote of the exchange that produced it. Quoting a *source* is never what this means, and the rule is deliberately narrow so it does not fire on one. |
| hardcoded skill path | Address the file relatively, or through `<skill-dir>` resolved from where the skill loaded. |
| dead relative link | Fix the target or delete the link. Ten dead links once shipped pointing at a directory the repo never had. |
| shellcheck warning/error | Fix it. `bash -n` proves syntax, not correctness — it passed a quoting bug that word-split any path containing a space. |
| skill not approved for a public repo | Decide, then add the line to `skills/PUBLIC`, or move the skill to the private repo. |
| SKILL.md front matter faults | See the table in the parent `SKILL.md`. |

A `note:` line is not a finding. The body-size note means the skill's body is
over the ~5,000-token guidance and loads in full every time it fires; move the
long parts into `reference/`.

## Overriding

`git commit --no-verify` and `git push --no-verify` exist and are sometimes
right. Say out loud which finding is being overridden and why, in the same
breath — an override nobody mentioned is indistinguishable from a guard nobody
installed.
