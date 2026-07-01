# Aurora — Project State

> **This is the session entry point.** When the user says "Start" / "Start session",
> read this file first, then `WORKLOG.md`, `DECISIONS.md`, and `BACKLOG.md` in this
> folder, then give a 4–6 line recap and ask what to work on. Keep this file current
> at the end of each working session.

_Last updated: 2026-07-01 (session 12 — live-verified slice α **tick-off card + last-step auto-complete** through the bot (both ✅), and `/onboard` end-to-end. Found + fixed an onboarding bug: buttons carried no question index, so a stale-card tap mis-filed the sign-off answer under `handle_vs_check` — data fixed live + code hardened (`_parse_onb_action` + stale-tap guard, `f20ec5b`, deployed). 193 tests, ruff clean. Still to walk live: mark_done guard + 09:00 reminder step-chase (need a fresh stepped item). Then **built Phase 2 slice 2a — procedural playbooks** (`PlaybookStore` + `propose_playbook` teach-by-confirm tool + `/playbook`; D22), 203 tests, ruff clean, committed `0fc54bd` — **not yet deployed** (seed the withholding-tax playbook + live-verify next).)_

## One-line status
Aurora is a Telegram-based conversational AI assistant that reads, searches, replies to, and
**composes** mail across the user's **personal Gmail** and **work email** (dapurhosting
IMAP/SMTP), **proactively notifies** about new mail that matters, and now tracks **open
commitments** + sends a **daily brief / weekly review** so nothing slips — learning the user's
preferences over time. Built through M4.

## What Aurora is
A personal assistant the user *delegates to* (not a dashboard). The user talks to her in
Telegram; she uses tools (currently email) to act, and reports in her own words. See
`DECISIONS.md` for the product principles.

## Where we are
- **M0 — Scaffolding** ✅ (commit `9e15fdd`): Telegram bot + swappable LLM client (DeepSeek) + config/secrets.
- **Memory slice** ✅ (commit `6078923`): persistent long-term memory (`data/memory/memory.md`),
  `/remember` `/memory` `/forget` `/new`, propose-to-remember buttons, short-term conversation thread.
- **M1 — Conversational email agent (Gmail)** ✅ (commit `f2df943`):
  - Stage 1: `LLMClient.chat()` with OpenAI-style function calling.
  - Stage 2: `MailAccount` interface + Gmail connector + registry.
  - Stage 3: agent loop + read tools (`list_unread`, `search_mail`, `read_email`).
  - Stage 4: action tools (`reply_to_email`, `resend_last_draft`) with Send/Save-draft/Cancel approval.
  - Fixes: spam/trash search, no agent dead-ends, forgotten preferences truly revert.
- **M2 — Work IMAP/SMTP account** ✅ (session 6): `aurora/sources/imap.py`
  `ImapAccount(MailAccount)` over `imaplib`/`smtplib` — read/search (INBOX+Junk), draft via
  IMAP APPEND, send via SMTP + a copy filed to Sent. Shared `strip_html` helper promoted to
  `base.py`. Config gained `work_*` fields; registry wires `accounts["work"]`. Verified live
  end-to-end through the bot (read + draft round-trip + real SMTP send + Sent copy). Fixed a
  folder-resolution bug found in testing (Dovecot returns bare LIST names, not quoted). Also added
  a FIDELITY prompt clause (D12) after Aurora altered an emoji in a send-confirmation read-back.
- **M3 — Compose + proactive notifications** ✅ (session 7):
  - **Compose**: `compose_email` action tool (new email, not a reply) reusing the Send/Save-draft/
    Cancel flow; Gmail send/draft now omit an empty `threadId`.
  - **Proactive notifications** (`aurora/notify/`): a dependency-free asyncio poller (`job.py`,
    started in PTB `post_init`) scans unread every `AURORA_NOTIFY_INTERVAL_SECONDS` (default 600),
    diffs against `NotifyState` (`state.py`, restart-safe JSON, seeds silently on first contact),
    and a batched LLM `classifier.py` decides notify/ask/skip (smart-filter + ask posture). Learns
    via `set_notification_rule` (`notify_tools.py`) → memory; reactions resolve through a RECENT
    NOTIFICATIONS prompt block. Realizes **D9**; see D13.
  - Verified live: `poll_once` against the real mailbox classified actual mail sensibly (money/people
    → notify; release/maintenance notices → ask). 86 tests pass.
- **M4 — Don't-miss-a-thing engine** ✅ (session 8): the "never miss a thing" substrate.
  - **Commitments ledger** (`aurora/ledger/`): hand-editable `data/ledger/commitments.md` tracking
    tasks/replies/deadlines/meeting-prep with owner/status/due/provenance; atomic+locked writes.
    Inline tools `add/list/update/mark_done` (`aurora/tools/ledger_tools.py`); open items injected
    into the prompt each turn. Commands `/agenda` (`/waiting`), `/track`, `/done`.
  - **Daily brief + weekly review** (`aurora/brief/`, `aurora/schedule/`): a dependency-free
    scheduler (60s tick + persisted last-fired, offline-catch-up + DST-safe via `tzdata`) composes a
    structured EA-style brief (one `llm.complete`, quiet-day path) from the ledger + a small activity
    log (`aurora/activity/`). `/brief` on demand. Config: `AURORA_TIMEZONE`/`AURORA_BRIEF_*`/
    `AURORA_WEEKLY_REVIEW_*`.
  - **Email auto-capture**: the notify classifier now also suggests a `commitment`; notifications get
    a one-tap "➕ Track this" button (deduped by `email:<account>:<id>`). See D14–D17.
  - **129 tests pass; ruff clean.** **Verified live through the bot** (session 9): `/track` → `/agenda`
    → `/brief` produced the fixed-section morning brief (greeted by name, item under "focus today");
    empty `/brief` hit the quiet-day path.
- **VPS deployment** ✅ (session 9): Aurora now runs 24/7 on the VPS under systemd; deploy via
  `git push origin main` (self-hosted runner). See **D18**. Gmail OAuth published to Production (token
  no longer expires); Telegram token no longer logged. Both session-9 follow-ups closed.

## Next up — **Slice α: structured multi-step tasks — SHIPPED + LIVE (session 11)**
Design **D21**; built and **deployed to prod** this session. A commitment owns an optional checklist (`Step`s as
hand-editable `  - [ ] …` child lines; 0 steps = flat task, fully backward-compatible). Capture goes through
`propose_commitment` (an **action tool** → a `✅ Track these / ✏️ Yes, but adjust / ✖ Not now` card; "adjust" is
a conversational loop via `revise_steps`), then a two-button **🔔/🔕 reminder opt** (default on). Tick-off is
`suggest_step_done` (suggest-and-confirm; never silent). `mark_done` guards on open steps; the last step
auto-completes. `due` may carry a time; `/agenda` + brief + reminders show `1/3` progress, honor `remind`, and
chase the open step. **188 tests, ruff clean.**

**Live-verified:** the capture path — Aurora proposes, the card renders, ✅ Track these writes it, the 🔔/🔕
opt fires, `/agenda` lists it. **3 fixes shipped from real use** (see WORKLOG session 11): (1) `add()`
deduped on the generic `source="chat"` → every chat item collapsed onto the first (returned an unrelated old
task) — now dedups only on structured provenance keys; (2) DeepSeek intermittently leaks a tool call as text
(`｜｜DSML｜｜` markup) → `DeepSeekClient.chat()` now recovers it into real `tool_calls`; (3) a one-item
checklist is redundant (title + a lone step restating it) → checklists now require ≥2 steps, else flat.

**Live-verified (session 12):** the **tick-off card** (suggest-and-confirm — Aurora asked "have you actually
reminded him?" first, D20, then ticked) and **last-step auto-complete** (closing the final step closed the
commitment; `c2` dropped off `/agenda`). That also retired the `c2` lone-step cleanup (done + gone).

**Still to do:** walk the **mark_done guard** on an open-steps item and a **09:00 reminder chasing the open
step** — both need a **fresh stepped commitment** (no stepped open item remains). Then **Phase 2 slice 2**
(playbooks fill these step templates). See BACKLOG item 0.

## Next up — Phase 2: make Aurora *learn* you (in progress, after slice α)
The roadmap's next milestone (BACKLOG #1; design in **D17**). Goal: complete D3's "correct" half so
Aurora discovers and adapts to the user's preferences instead of only ever *adding* to a flat memory.
Scope (build incrementally, one slice per session):
1. **Onboarding interview** ✅ (session 10) — `/onboard` runs the week-1 EA question set (8 core + 2
   optional, grounded in PA/EA best practice); one question at a time, preset buttons + free-text;
   confirm per answer (preset tap saves directly, free-text gets a Save/Edit/Skip card). Answers land in a
   new keyed, hand-editable **`ProfileStore`** (`data/profile/profile.md`, atomic+locked, upsert-by-key so
   corrections update in place and forgetting truly reverts). `profile.render_for_prompt()` is injected into
   the chat prompt and the notify classifier, so tone/escalation/VIPs/threshold bite immediately. `/profile`
   views it; `/profile forget <key>` clears one. **Live-verified (session 12)** — and a key-map bug was found
   + fixed: interview buttons carried no question index, so a stale-card tap mis-filed the sign-off answer
   under `handle_vs_check`; buttons now stamp their question index + the handler ignores stale taps (`f20ec5b`).
   *Open:* confirm whether the trigger was a stale tap or a skip-then-answer (if the latter, add a
   looks-like-wrong-field guard).
2. **Three-layer memory** — sequenced by leverage (D22). **Slice 2a — procedural playbooks ✅ (session 12,
   built; not yet deployed):** new `PlaybookStore` (`aurora/playbook/`, `data/playbook/playbooks.md`) =
   reusable step templates for recurring workflows (the content that fills slice-α checklists correctly;
   closes D20/D21). `propose_playbook` action tool (teach-by-confirm) + `/playbook` command; rendered into
   the turn prompt so capture pulls a matching playbook's steps. **Slice 2b — episodic log** deferred to pair
   with the reflection job (slice 4). `MemoryStore` + `ProfileStore` left as-is (no risky migration).
3. **Write-gate + capture corrections** — the "Remember this" button is already the gate; also turn an
   edited/cancelled draft or notification reaction into a one-line lesson (scope + provenance + dedup).
4. **Nightly reflection job** — ride the Phase-1 scheduler (`aurora/schedule/`) to consolidate recent
   episodic entries into cleaner rules and decay stale ones (user confirms). This is the long-promised
   "Reflection job."
Guardrails (D17): distilled lessons in the prompt (not transcripts), every durable memory
human-confirmed + traceable, TTL/decay vs drift. After Phase 2: **Calendar (Google)**, then notes/finance.

## Live runtime (current)
- The bot runs **on the VPS** (`prod`, `103.150.194.135`, Ubuntu 24.04) under **systemd**:
  `aurora-bot.service` (`User=matajari`, `Restart=always`, **enabled at boot**) from
  `/home/mahdi/aurora`, venv at `.venv`. Manage with `sudo systemctl {status,restart} aurora-bot` and
  `journalctl -u aurora-bot -f`. The laptop bot stays OFF (only one Telegram poller allowed).
- **Deploys are pull-based**: push to `main` → a **self-hosted GitHub Actions runner** on the VPS
  (`actions.runner.mahdialig-aurora.aurora-vps`, runs as `matajari`) pulls + tests + restarts. No
  inbound access needed (VPS inbound :22 is IP-restricted). Repo: `github.com/mahdialig/aurora`
  (private; VPS clones via a read-only deploy key). See **D18**.
- Telegram bot: **@paagentaurorabot**, locked to the user's Telegram id `6959305748`.
- Model: `deepseek-v4-flash`. Autonomy mode: `approve_all` (sending always needs a tap).
- Proactive notifications: ON, every 600s. Daily brief 07:00 / weekly review Mon 07:30 / **reminders +
  check-ins 09:00** (Asia/Jakarta). State persists in `data/notify_state.json`, `data/schedule_state.json`,
  `data/remind_state.json`. Now truly 24/7.
- Aurora now **knows the current date/time** (injected into her chat prompt in the configured tz), so
  "what time is it?" works and her relative-date / due-date reasoning is correct.
- Connected mailboxes:
  - **personal Gmail** `magyp.magyp@gmail.com` (OAuth, scope `gmail.modify`). Google Cloud
    project: `aurora-500907`, OAuth app **published to Production** (session 9) → refresh token no
    longer expires. Re-auth (if ever needed): `python -m aurora.sources.gmail_auth` on the laptop,
    then `scp data/token.json` to the VPS and restart.
  - **work email** `mahdi.ali@matajari.co.id` on dapurhosting (IMAP/SMTP `d001.dapurhosting.com`,
    993/465 SSL). Creds in `.env` (`WORK_EMAIL`/`WORK_PASSWORD`); both gitignored.

## How to resume a working session
1. Read this file + `WORKLOG.md` + `DECISIONS.md` + `BACKLOG.md`.
2. Verify health: `cd` to repo, run `./.venv/Scripts/python.exe -m pytest -q` (expect all green)
   and `./.venv/Scripts/ruff.exe check aurora tests`.
3. Develop locally and **deploy by `git push origin main`** (self-hosted runner pulls + tests +
   restarts). Do **NOT** start the bot on the laptop while the VPS bot is up — only one Telegram
   poller may run at once. `.env`, `credentials.json`, `data/token.json` exist locally (gitignored) —
   don't recreate them. To watch prod: `ssh prod`, `journalctl -u aurora-bot -f`.
4. Pick the top BACKLOG item — currently **Phase 2** (see "Next up" above) — or whatever the user asks.

## Key facts a new session must not re-derive
- Accounts: personal = Gmail (API/OAuth); work = `mahdi.ali@matajari.co.id` on dapurhosting →
  **IMAP/SMTP, NOT Google** (now connected; password in `.env`). Username = full email address.
- Aurora must never dump the inbox verbatim — she's a delegate, not a viewer.
- Anything that leaves a mailbox (send) is approval-gated regardless of autonomy mode.
- Secrets live only in gitignored files; never commit them.
