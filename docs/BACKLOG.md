# Aurora — Backlog & Tech Debt

Prioritized. Move items to WORKLOG when done. Keep "Next up" honest.

## Next up (in order)
1. **VPS deployment** — so proactive notifications AND the daily brief run 24/7 (currently
   laptop-only; both pause when the bot is off). systemd service for the bot; `.env`/
   `credentials.json`/`data/` onto `prod`. Publish the Google OAuth app to Production to stop the
   ~weekly token expiry. Now doubly motivated: the M4 morning brief only matters if always-on.
2. **Self-learning upgrade (Phase 2)** — make D3's "correct" half real (see D17): onboarding
   interview (`/onboard`), three-layer memory (episodic / semantic / procedural), confirm-before-save
   write gate with scope+provenance+dedup, and the nightly **reflection job** that consolidates
   corrections + decays stale entries. Capture corrections (edited/cancelled drafts) as lessons.
3. **Calendar (Google) — Phase 3** — feed meetings/deadlines into the ledger + brief; conflict checks,
   time-blocking. Then tasks (largely the ledger itself), Obsidian notes, finance.

## M4 follow-ups (don't-miss-a-thing engine — landed; polish later)
- **Proactive chasing**: have the notifier/scheduler nudge on ledger items as due dates approach and
  on stale `waiting`-on-others items ("you haven't heard back from X") — the ledger now exists for it.
- **Brief tuning**: per-user brief time learned from when they read it; `/brief weekly` on demand;
  let the brief link back to the source email for each item.
- **Notification polish** (carried over): `/mute` `/notify` quick commands; per-account toggles;
  dedupe threads so a busy thread pings once; per-thread (not per-email) classification.

## Later / nice-to-have
- **Gmail draft management**: list/send existing Gmail drafts across sessions (today's
  `resend_last_draft` only works within the current conversation, server-side).
- **Autonomy modes UI**: `/mode` command to switch `approve_all` ↔ `digest` ↔ `auto_low_risk` ↔
  `autonomous` (config field exists; no command yet).
- Multimodal input (PDFs/images/voice) — from the original vision.

## Tech debt / risks
- **OAuth token expiry**: Google app is in "Testing" → refresh token may expire ~weekly →
  re-run `python -m aurora.sources.gmail_auth`. Option: publish app to Production (unverified) to
  stop expiry. Two client secrets currently exist on the OAuth client; the old one can be deleted.
- **Pending actions are in-memory**: `pending_replies` / `last_reply` / pending memories live in
  bot RAM — lost on restart (buttons/resend "expire"). Fine for now; persist if it annoys.
- **Bot lifecycle is manual**: started by hand each session; no auto-restart/supervision.
- **No real Gmail API integration tests** (unit tests use a fake service); live verification only.
- **IMAP specifics** (M2): per-operation login adds latency on each read; `archive` is best-effort
  and unused by any tool; work mailbox password sits in plaintext `.env`. (Live draft/send verified;
  folder-name parsing fixed for Dovecot's bare names.)
- **Notifications** (M3): poller runs only while the bot is up (laptop) → offline arrivals only caught
  on next start; classifier is per-email not per-thread (a chatty thread can ping repeatedly); seen-state
  keyed on unread message-ids (reading mail elsewhere doesn't notify); live feedback loop + live compose
  not yet exercised through the bot (unit-tested + dry-run verified only).
- `.sim/` cost analysis is uncommitted — decide: commit as docs or add to `.gitignore`.
- **M4 (don't-miss-a-thing)**: brief/scheduler are unit-tested + import-verified but NOT yet driven
  through the running bot (no live brief send / live "Track this" tap yet). Auto-capture quality
  depends on the classifier's new `commitment` field — watch for noise. Activity log only records
  email send/draft so far (the brief's "handled" section is thin until more actions log). Scheduler,
  like the notifier, only runs while the bot is up (→ VPS). Weekly review is same-day-only (a review
  missed because the bot was off all day is skipped, not fired late on the wrong day).
