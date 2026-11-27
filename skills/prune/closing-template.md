---
title: <App name>: <what changed, in plain words>
brief-id: closing-<yyyy-mm-dd>-<slug>
eyebrow: Thread closing · <d Month yyyy>
sub: <One sentence a stranger understands: what is now true that was not true before.>
---

## Answers

Is it finished?
: <Yes, or what is left, in one sentence.>

# Closing

<One sentence: the finished state, for a reader with no context.>

## What you asked for

<Two or three sentences: the problem as you described it, in your words where possible.>

## What was done

- **<Change>:** <what it does now, and why that fixes the problem>.
- **Repos touched:** `<repo>` (<commit range or SHAs>, merged / pushed / local only).
- **Deployed:** <what is live, where, and the SHA production serves>, or "Nothing deployed."
- **Where the results are:** <a link, an absolute path, or the page to open>.

## Next steps for you

<Numbered steps. One action per step. Each says what it checks or unblocks.
A step already approved into the task tracker is one line: what, the due date, and its link.>

1. <Step>.

:::draft
<command>
:::

## Next steps for us

<Optional. Only steps that truly add value. Each one: what it does, why it is worth it,
then the command to paste into a new Claude thread in the named repo.>

**<Short title>.** <What it does and why.> Run it in a new thread in `<repo>`:

:::draft
<command>
:::

<!--
Rules for this file (delete this comment when you fill it in):
- The reader has no memory of the thread. Every section stands alone.
- Plain English, Australian spelling, short sentences, no em dashes.
- Every path is absolute. Every shell command runs as pasted from any folder.
- A Claude command for a new thread names the repo it runs in, and carries this
  file's absolute path so the new thread starts with the context.
- Each command sits in its own :::draft box, so it gets a copy button.
- Omit "Next steps for you" and "Next steps for us" when there is nothing real.
  Write "Nothing. This work is finished." instead of an empty list.
-->
