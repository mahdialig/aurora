# Aurora — Backlog & Tech Debt

Prioritized. Move items to WORKLOG when done. Keep "Next up" honest.

## Next up (in order)
0. ~~**Slice α — structured multi-step tasks ("definition of done")**~~ ✅ **SHIPPED + LIVE (session 11)** —
   design **D21**. Optional checklist per commitment (`Step`s as hand-editable `  - [ ] …` child lines; 0 steps
   = flat task). Capture via `propose_commitment` (action tool → `✅ Track these / ✏️ Yes, but adjust /
   ✖ Not now` card; adjust = a `revise_steps` loop) + a two-button 🔔/🔕 reminder opt (default on). Tick-off
   via `suggest_step_done` (suggest-and-confirm). `mark_done` guards on open steps; last step auto-completes;
   `due` may carry a time; `/agenda`/brief/reminders show `1/3`, honor `remind`, chase the open step. Deployed;
   **capture path live-verified**; 3 fixes shipped from real use (source-dedup collision, DeepSeek
   tool-call-leak recovery, single-step-checklist collapse — see WORKLOG s11). 188 tests, ruff clean.
   **Loose ends**: ~~tick-off card~~ ✅ + ~~last-step auto-complete~~ ✅ + ~~tidy `c2`~~ ✅ (all session 12).
   Remaining: walk the **mark_done guard** + a **09:00 reminder step-chase** — need a fresh stepped item
   (c2 closed). Then Phase 2 slice 2.
1. **Self-learning upgrade (Phase 2)** — make D3's "correct" half real (see D17). Build incrementally:
   - **Slice 1 — onboarding interview (`/onboard`)** ✅ (session 10): week-1 EA questions → new keyed,
     hand-editable `ProfileStore` (`data/profile/profile.md`), rendered into the chat prompt + notify
     classifier. ✅ **Live-verified (session 12)**; fixed a stale-card key-map bug (buttons now carry the
     question index — `f20ec5b`). *Open: confirm stale-tap vs skip-then-answer trigger.*
   - **Slice 2a — procedural playbooks** ✅ (session 12, built — design **D22**): `PlaybookStore`
     (`aurora/playbook/`, `data/playbook/playbooks.md`) = reusable step templates for recurring workflows;
     `propose_playbook` action tool (teach-by-confirm) + `/playbook` command; injected into the turn prompt so
     capture pulls a matching playbook's steps (closes D20/D21). *Still to do: deploy; seed the withholding-tax
     playbook on the VPS; live-verify teach-by-confirm + a matching capture.*
   - **Slice 2b — episodic log**: deferred to pair with the reflection job (slice 4), where it earns its keep.
   - **Slice 3 — write-gate + capture corrections**: turn edited/cancelled drafts + notification reactions
     into one-line, scoped, deduped, provenance-carrying lessons (reuse slice 1's confirm gate + upsert).
   - **Slice 4 — nightly reflection job**: ride `aurora/schedule/` to consolidate episodic entries + decay
     stale ones (user confirms).
2. **Calendar (Google) — Phase 3** — feed meetings/deadlines into the ledger + brief; conflict checks,
   time-blocking. Then tasks (largely the ledger itself), Obsidian notes, finance.

## Done
- **VPS deployment** ✅ (session 9) — Aurora runs 24/7 on `prod` under systemd; pull-based deploys via
  a self-hosted Actions runner (`git push origin main`). See **D18** + STATE "Live runtime".

## M4 follow-ups (don't-miss-a-thing engine — landed; polish later)
- ~~**Proactive chasing**~~ ✅ (session 10): `aurora/remind/` rides the scheduler — dated items get
  deadline reminders (overdue/today/tomorrow, daily until done), undated items get rate-limited progress /
  "still waiting on X?" check-ins, each with a ✅ Done button. Fires 09:00 Jakarta (`AURORA_REMINDER_*`).
  *Polish later: snooze button; per-item due-soon thresholds; fold into the brief vs. separate message;
  catch items added mid-day (currently a once-daily pass, not the 10-min notifier loop).*
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
- `.sim/` cost analysis — now in `.gitignore` (treated as local scratch).
- ~~VPS: bot token leaks into journald~~ ✅ **Fixed** (session 9): httpx logger set to WARNING so the
  Telegram token no longer appears in logs.
- ~~VPS: Gmail OAuth token expiry~~ ✅ **Resolved** (session 9): OAuth app published to **Production**
  (project `aurora-500907`), so refresh tokens no longer expire after ~7 days; re-authed magyp.magyp@
  gmail.com to mint a fresh non-expiring token and deployed it. Also hardened in code: an expired/
  revoked refresh token now raises `GmailAuthError` (skip Gmail, keep running) and the bot sends a
  Telegram alert at startup instead of failing silently. NOTE: the `gmail.modify` scope is "restricted",
  so adding *other* users would require Google verification — fine for the single owner.
- **M4 (don't-miss-a-thing)**: brief/scheduler are unit-tested + import-verified but NOT yet driven
  through the running bot (no live brief send / live "Track this" tap yet). Auto-capture quality
  depends on the classifier's new `commitment` field — watch for noise. Activity log only records
  email send/draft so far (the brief's "handled" section is thin until more actions log). Scheduler,
  like the notifier, only runs while the bot is up (→ VPS). Weekly review is same-day-only (a review
  missed because the bot was off all day is skipped, not fired late on the wrong day).
