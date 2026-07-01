# Aurora — Work Log

Chronological journal of what was done each session. Newest at the bottom.
Append a dated entry at the end of every working session.

---

## Session 1 — Vision & foundation plan (2026-06-29)
- Turned `INIT.md` (the user's vision) into a concrete plan: Aurora = process-first personal
  assistant that learns preferences over time.
- Locked decisions: inbox-first, correct-and-remember, switchable autonomy (see DECISIONS).
- **M0 shipped** (`9e15fdd`): repo scaffolding, config/secrets, swappable `LLMClient` + DeepSeek,
  Telegram echo bot. Verified live end-to-end (bot replies via DeepSeek).

## Session 2 — Cost simulation (2026-06-29)
- Wrote a DeepSeek monthly cost simulation to `.sim/deepseek-cost-simulation.txt` for a heavy
  "startup CEO" persona. Headline: even heavy use ≈ low single dollars/month; risk is over-buying.
- Discovered current DeepSeek models are `deepseek-v4-flash` / `deepseek-v4-pro` (old
  `deepseek-chat`/`reasoner` deprecate 2026-07-24). Switched default to `deepseek-v4-flash`.
- (`.sim/` is left uncommitted — a scratch analysis artifact.)

## Session 3 — Memory slice (2026-06-29)
- **Memory shipped** (`6078923`): `MemoryStore` over `data/memory/memory.md` (plain, hand-editable);
  `/remember` `/memory` `/forget` `/new`; propose-to-remember via hidden `[[REMEMBER]]` marker →
  inline Remember/Dismiss buttons; short-term conversation thread (last 20 msgs).
- Fixed a real bug: bot was stateless per-message; added conversation history so it follows a thread.

## Session 4 — M1 Gmail, redesigned as a conversational agent (2026-06-29)
- User clarified the core principle: **Aurora is a delegate, not an email viewer** (no verbatim
  inbox dumps). Saved to Claude memory. This killed the original `/inbox`-list design.
- Chose **full Gmail API** (read + send). Work email confirmed **not Google** (dapurhosting, IMAP).
- **M1 shipped** (`f2df943`) as a tool-use agent:
  - `LLMClient.chat()` (function calling), `agent.py` loop, `MailAccount` interface, Gmail connector,
    registry, email tools, reply approval flow.
- Did the **Google Cloud setup via the Chrome extension** (project `aurora-500907`, Gmail API,
  OAuth consent, Desktop client). Got `credentials.json` (Google now blocks viewing secrets after
  creation → used "Add secret" + the user's real download click). Authorized → `data/token.json`.
  Connected personal Gmail; verified live (read real unread mail; sent + drafted real replies).

## Session 5 — M1 polish + session system (2026-06-29)
- Fixes from live testing:
  - Search now includes spam/trash (found an email hiding in spam).
  - Agent no longer dead-ends on step limit — forces a final natural-language answer.
  - Reply path ALWAYS uses the tool (buttons appear instantly; no "type Send it" step).
  - Added `resend_last_draft`. Stopped parking draft bodies in the short-term thread so that
    **forgetting a preference truly reverts behavior** (old drafts were biasing new ones).
- Committed M1 (`f2df943`). Created this `docs/` session-continuity system. 52 tests passing.
- **Deferred to next session:** Stage 5 — work IMAP account.

## Session 6 — M2 work IMAP/SMTP account (2026-06-29)
- **M2 shipped** as a second `MailAccount` connector — the stack above the mailbox was already
  provider-agnostic, so the surface/tools/agent needed **zero** changes:
  - `aurora/sources/imap.py` `ImapAccount(MailAccount)` over stdlib `imaplib`/`smtplib`
    (no new deps). Per-operation connections (IMAP drops idle sockets); `BODY.PEEK[]` fetches so
    reading never marks mail `\Seen`; special-folder resolution via IMAP special-use flags;
    `from:`/`subject:`/`TEXT` search over INBOX+Junk; draft via `APPEND`; send via SMTP **plus a
    copy filed to Sent**. DI via connection factories (mirrors `GmailClient(service)`).
  - Promoted `_strip_html` → `base.strip_html` (shared by both connectors).
  - `config.py` gained optional `work_*` fields (host defaults `d001.dapurhosting.com`, 993/465).
    `registry.build_mail_accounts` wires `accounts["work"]`, skipping cleanly on `ImapError`.
  - `tests/test_imap.py` (pure helpers + fake IMAP/SMTP) + a config-defaults test. 63 tests pass; ruff clean.
- Got the real connection details from the user's mail-client screenshot (host `d001.dapurhosting.com`,
  username = full email). **Verified live**: connect + list_unread + get_message (HTML→text body) +
  search against the real server; registry reports `['personal', 'work']`.
- **Live-tested through the bot**: Aurora read work mail, drafted, and **sent** a reply (SMTP) end-to-end.
- **Bug found & fixed during live test**: `_folder_name` only parsed *quoted* LIST names, but dapurhosting
  (Dovecot) returns **bare** names (`(... \\Sent) "." INBOX.Sent`), so special-folder resolution returned
  the delimiter `"."`. Effect: the Sent-copy `APPEND` (best-effort) silently failed; `create_draft` would
  have too. Fixed to handle bare + quoted names; added a regression test and switched the test fake to the
  real unquoted format. Re-verified live: `\Sent→INBOX.Sent`, `\Drafts→INBOX.Drafts`, and a real
  `create_draft` round-trip (appended to INBOX.Drafts, read back, cleaned up).
- **Behavior fix (fidelity)**: in the send test Aurora's read-back swapped 🕌→🕋 and confabulated an excuse —
  altering content during a functionality check eroded trust. Added a FIDELITY clause to the email prompt:
  paraphrase the framing, never the content; when quoting/confirming, reproduce the exact text acted on
  (don't regenerate from memory); quote verbatim when exactness might matter. See DECISIONS D12.

## Session 7 — M3: compose + proactive notifications that learn (2026-06-29)
- **Compose fresh email** (BACKLOG #2): `compose_email` action tool reusing the Send/Save-draft/Cancel
  flow (`_propose_action` builds a `Reply` with empty threading). Gmail `send_reply`/`create_draft` now
  omit `threadId` when empty (a fresh email isn't part of a thread).
- **Proactive notifications** (BACKLOG #1, realizing **D9**) — new `aurora/notify/` package:
  - `state.py` `NotifyState` — restart-safe JSON of seen message-ids per account; seeds silently on
    first contact (no startup flood); bounded to 500/account.
  - `classifier.py` — one batched `llm.complete` per poll over new mail + the user's memory; returns
    notify/ask/skip per email; tolerant JSON parse with notify-all fallback (never drop mail silently).
  - `job.py` — dependency-free asyncio poller (PTB's JobQueue needs APScheduler, not installed). Testable
    core `poll_once(accounts, state, llm, memory, notify)`; wiring starts it in `post_init`, cancels in
    `post_shutdown`; soft-caps pings/cycle; threads notifications into chat history + a `recent_notifications`
    buffer so reactions have context.
  - Learning: `notify_tools.py` `set_notification_rule` (inline tool) writes a rule straight to memory →
    the next poll's classifier sees it. A RECENT NOTIFICATIONS prompt block lets "that's important" /
    "stop notifying me about these" resolve to the right mail.
  - Config: `AURORA_NOTIFY_ENABLED` (default true), `AURORA_NOTIFY_INTERVAL_SECONDS` (default 600).
  - Decisions confirmed with user: default posture **smart-filter + ask**; interval **10 min**; feedback
    saved directly (no Remember-button). See DECISIONS D13.
- **Verified live**: `poll_once` against the real mailbox classified actual unread sensibly — money (Jago)
  and real people (colleagues, Mahdi) → notify; DeepSeek release + Faspay maintenance notices → ask. Dry
  run (nothing sent to Telegram). 86 tests pass; ruff clean.
- Live compose + live notification feedback loop still to be exercised through the bot.

## Session 8 — Direction reset + M4 don't-miss-a-thing engine (2026-06-30)
- **Stepped back to figure out what Aurora should become.** Researched (a) what great EAs/chiefs-of-
  staff actually do as transferable procedures (morning brief structure, GTD/"Waiting For", calendar
  defense, week-1 onboarding questions, observe-and-correct), (b) self-improving agent patterns
  (Reflexion/Self-Refine, episodic/semantic/procedural memory, write-gate, consolidation, drift
  guards), and (c) the framework question. Decisions: **D14** stay hand-rolled (don't adopt openclaw/
  Hermes; maybe Mem0-as-library later), **D17** plan onboarding + observe-and-correct + reflection.
- User's picks for direction: don't-miss-a-thing engine first; deeper framework comparison (done);
  calendar as next domain; learn via interview + observe-and-correct.
- **M4 shipped** — the "never miss a thing" substrate (**D15**, **D16**); 127 tests pass, ruff clean:
  - **Commitments ledger** (`aurora/ledger/store.py`, `__init__.py`): `LedgerStore`/`Commitment` over
    `data/ledger/commitments.md`; tolerant markdown (`text · key:val`), id backfill, source-dedup,
    atomic (tmp+`os.replace`) + locked writes, `prune_done`, `render_for_prompt`. Tools
    (`aurora/tools/ledger_tools.py`): inline `add/list/update/mark_done`. Tests: `test_ledger_store.py`,
    `test_ledger_tools.py`.
  - **Scheduler** (`aurora/schedule/`): pure `timing.py` (`daily_due`/`weekly_due`, offline catch-up),
    `state.py` (`ScheduleState` last-fired JSON), `runner.py` (60s tick, `pending_jobs`, tz resolve w/
    fixed-UTC+7 fallback). Tests: `test_schedule_timing.py`.
  - **Brief** (`aurora/brief/compose.py`) + **activity log** (`aurora/activity/log.py`): EA-section
    daily brief / weekly review via one `llm.complete`, quiet-day path, LLM-failure fallback; activity
    ring buffer feeds "handled". Tests: `test_brief_compose.py`.
  - **Wiring**: config knobs (`AURORA_TIMEZONE`/`BRIEF_*`/`WEEKLY_REVIEW_*`), `tzdata` dep; telegram
    bot_data + tools + prompt + scheduler hooks; commands `/brief` `/agenda`(`/waiting`) `/track`
    `/done`; activity recorded on send/draft.
  - **Email auto-capture**: classifier `Verdict.commitment`; job surfaces it + `email_id` in meta; a
    one-tap "➕ Track this" button (`on_track_button`, deduped by `email:<account>:<id>`). Tests extend
    `test_notify_job.py`.
- Not yet driven live through the running bot (brief send / Track-this tap) — see BACKLOG M4 follow-ups.

## Session 9 — VPS deployment, 24/7 (2026-06-30)
- **Aurora is now live on the VPS** (`prod`, `103.150.194.135`, Ubuntu 24.04), running 24/7 under
  systemd and auto-restarting. The laptop bot is retired (only one Telegram poller allowed). See **D18**.
- Probed the box first (read-only): login is **`matajari`** (passwordless sudo; no `mahdi` user),
  Python 3.12.3, `pip`/`ensurepip` missing, git/systemd/rsync present, **inbound :22 IP-restricted**
  but **outbound HTTPS to GitHub works**.
- **The sudo-under-`/home/mahdi` annoyance** (user's P.S.): root cause was the dir being `root:root`.
  Fixed with `sudo chown -R matajari:matajari /home/mahdi` → file ops there need no sudo now.
- Steps: `apt install python3.12-venv`; committed the M4 (+ prior uncommitted) work and pushed to the
  new private repo **`github.com/mahdialig/aurora`** (`main`); added `.sim/` to `.gitignore`; verified
  no secrets staged. VPS clones via a **read-only deploy key** (chosen over a PAT — zero user effort;
  outbound SSH to GitHub is open, inbound restriction untouched). Built venv, `pip install -e .[dev]`,
  config loads with real `.env`, **127 tests pass on the VPS**.
- `scp`'d secrets + data (`.env`, `credentials.json`, `data/{memory.md,notify_state.json,token.json}`),
  chmod 600 on secrets.
- **systemd**: `aurora-bot.service` (`User=matajari`, `Restart=always`, enabled at boot). Live logs
  confirm Telegram connected + Notifier + Scheduler started (Asia/Jakarta, brief 07:00, weekly Mon 07:30).
- **Pull-based CI/CD** (inbound is IP-restricted, so no push-deploy): installed a **self-hosted GitHub
  Actions runner** (v2.335.1) as a `matajari` service; `.github/workflows/deploy.yml` on push to `main`
  does `git reset --hard origin/main` → `pip install` → `pytest` (gate) → `systemctl restart aurora-bot`.
  First run **succeeded end-to-end in 16s**. Deploy loop verified.
- Follow-ups (both **done** same session): (1) silenced the Telegram token in logs (httpx→WARNING);
  (2) Gmail token expiry — published the OAuth app to **Production** via the Chrome extension, re-authed
  magyp.magyp@gmail.com (fresh non-expiring token, verified working, deployed to VPS), and hardened the
  code (expired refresh → GmailAuthError, skip + Telegram alert, no crash-loop). 129 tests pass.
- **M4 verified live through the bot**: `/track` (captured `c1`) → `/agenda` (listed it) → `/brief`
  (fixed-section morning brief, greeted "Aji", item under "Your focus today" with the due date); empty
  `/brief` hit the quiet-day path. The don't-miss-a-thing engine works end-to-end in production.
- **State updated for Phase 2** (self-learning / `/onboard` + reflection) — to be started in a fresh
  session; see STATE.md "Next up" and DECISIONS D17.

## Session 10 — Phase 2 slice 1: /onboard + preference profile (2026-06-30)
- **Planned Phase 2 and built slice 1** (the lowest-risk, immediately-useful piece). User picks this
  session: interview = one Q at a time, **preset buttons + free-text**; write gate = **confirm per answer**
  (and fields must stay adjustable later, by Aurora or the user); storage = **a new separate profile file**;
  question set = "you recommend it, but ground it in PA/EA best practice." Researched EA/PA week-1 onboarding
  practice (ProAssisting, Connect, Boldly, TheEACampus, Worxbee) → the recurring buckets (how to address +
  rhythm, channels/urgency, the principal's email voice, escalate-vs-handle, VIPs, notify threshold), each
  mapping to a real Aurora lever.
- **New `aurora/profile/` package** (mirrors `aurora/ledger/`); 155 tests pass (was 129; +26), ruff clean:
  - `store.py` — `ProfileStore`/`ProfileField` over `data/profile/profile.md` (hand-editable
    `- key: value · on:DATE src:SRC`). **Keyed**, so `set()` **upserts by key** (corrections update in place,
    no dupes) and `remove()` truly reverts (D8). Atomic (tmp + `os.replace`) + `threading.Lock` like the
    ledger. `render_for_prompt()` emits a `PROFILE — standing preferences` block (distinct empty-state that
    nudges `/onboard`).
  - `interview.py` — `Question` dataclass + `QUESTIONS` (8 core: preferred_name, work_hours, dnd,
    notify_threshold, vips, reply_tone, reply_length, signature; +2 optional: handle_vs_check, off_my_plate).
    `distill(llm, q, raw)` tidies free-text into one clean preference line via a single `llm.complete`, with
    **raw-text fallback on any failure** (mirrors `brief/compose.py`).
  - Tests: `test_profile_store.py` (roundtrip, upsert-no-dup, remove-reverts, empty-value rejected, render,
    hand-edited + unparseable-line tolerance), `test_profile_interview.py` (unique keys, well-formed options,
    core levers present, distill llm-output / fallback / empty).
- **Telegram wiring** (`surfaces/telegram.py`): registered `ProfileStore` in `bot_data`; injected
  `profile.render_for_prompt()` into `_respond`'s system prompt (before memory + ledger). New commands
  `/onboard` (start/re-run/review/cancel menu when a profile already exists) and `/profile`
  (`/profile forget <key>`). Hand-rolled multi-turn state in `chat_data["onboarding"]` (no
  `ConversationHandler` exists); `chat()` intercepts typed answers while a interview is active. New
  `on_onboard_button` `CallbackQueryHandler(pattern=r"^onb:")` — **preset tap saves directly + advances**
  (the tap is the confirmation); **free-text gets a Save/Edit/Skip confirm card** (distillation can be wrong).
  `/start` greeting now prefers the profile's `preferred_name` over the memory name guess.
- **Notify wire** (`notify/job.py` only, classifier untouched): `poll_once` gained an optional `profile=`;
  when non-empty its block is appended to the preferences fed to the classifier, so onboarding's
  `notify_threshold`/`vips` shape live pings. `start_notifier` reads `bot_data.get("profile")`.
- **NOT yet live-verified through the running bot** (deploy is `git push origin main` → self-hosted runner;
  laptop poller stays off). Next: deploy + walk `/onboard` end-to-end, confirm a draft reflects the chosen
  tone/signature, and that `/profile forget` reverts. Then slice 2 (three-layer memory) builds on this store.
- **Follow-ups same session (deployed):**
  - **`/help`** command listing all commands, grouped (`/start` points at it).
  - **A clock**: `_time_note(now)` injects the current date/time (configured tz, resolved once into
    `bot_data["tz"]`) into `_respond`'s prompt. Aurora was time-blind in chat; now she can answer
    "what time is it?" and reason correctly about today/tomorrow/due dates. Portable day-of-month (no
    `%-d`/`%#d`). Was prompted by the user noticing she couldn't tell the time.
  - **Proactive reminders + progress check-ins** (new `aurora/remind/`, realizes the M4 "proactive chasing"
    follow-up): rides the existing scheduler with a new `REMINDER_JOB` at `AURORA_REMINDER_TIME` (09:00
    default). `plan_nudges` (pure) — **dated** items get deadline reminders (overdue / due-today /
    due-tomorrow, repeating daily until done); **undated** items get **check-ins** once stale (no update for
    `reminder_stale_days`, default 3): "still waiting to hear back?" (owner=other) / "how's this going?"
    (owner=me). Check-ins are rate-limited per item via `RemindState` (`data/remind_state.json`) so she
    nudges, not nags; capped at 6/pass with an "…and N more" overflow line. Each nudge carries a "✅ Done"
    button (`rdone:<id>` → `ledger.mark_done`). Config knobs `AURORA_REMINDER_{ENABLED,TIME,STALE_DAYS}`;
    scheduler start-gate widened. Tests: `test_remind.py` (planner cases + state). 165 tests pass, ruff clean.
    **Not yet seen fire live** (next scheduled 09:00 Jakarta; can force-test by setting a due item + waiting).
  - **"Definition of done" standard** (D20): live-use surfaced Aurora declaring a withholding-tax task "all
    set ✅" when an email only confirmed vOffice *received* the bukti potong — she missed that paying DJP is
    the real obligation. User's call: adopt a Scrum-style definition-of-done rather than a tax-specific
    patch. Added a standing `SYSTEM_PROMPT` clause: don't call anything done/"all set" (in chat or via
    `mark_done`) unless the actual goal is achieved + confirmed; a counterparty's receipt/acknowledgement is
    only one step; money/tax/deadline/filing/other-party items count as in-progress until the outcome is
    confirmed; when unsure, state what's confirmed, name what's open, offer to track it. The *specific*
    bukti-potong→DJP workflow knowledge is deferred to the procedural-playbooks layer (slice 2) — its
    motivating example. (User also flagged an `.env` secret accidentally pasted into chat → advised rotating.)

## Session 11 — Slice α: structured multi-step tasks ("definition of done") (2026-06-30)
- **Built slice α** end-to-end (design = **D21**); **182 tests pass** (was 165, +17), ruff clean. User
  decisions this session: `remind` **defaults ON** with an explicit accept/opt-out two-button message;
  tick-off is **tool-driven only** in v1; the proposal card is **always shown** for conversational capture.
- **Store** (`aurora/ledger/store.py`): new `Step(text, done)`; `Commitment` += `steps: tuple[Step,...]`
  and `remind: bool = True`. `is_done` = all-steps-done when stepped, else the status flag (flat unchanged).
  Added `progress`/`open_step_texts`; serialize steps as GitHub-style `  - [ ] …` child lines + parse them
  (`_STEP_RE`, attached to the most recent parent); `remind:off` written only when off (default-on omitted →
  backward-compatible). New `set_step` (auto-completes the parent on the last step), `open_steps`,
  `mark_done` (ticks all steps); `add(steps=, remind=)`; `update` accepts `remind`. **Bug fix:** a timed
  `due` (`2026-07-03T17:00`) broke `==`/`due_on_or_before` comparisons → added `_due_date()` (date prefix)
  and used it in `query`, the brief, and the reminder planner.
- **Tools** (`aurora/tools/ledger_tools.py`): replaced inline `add_commitment` with **`propose_commitment`**
  (action tool, derives candidate steps) + added **`suggest_step_done`** (action tool); `mark_done` now
  **guards** — returns `needs_confirmation` + the open steps unless `force:true`.
- **`aurora/ledger/propose.py`** (new): `revise_steps(llm, payload, instruction)` — one LLM call returning
  `{text, due, steps[]}` (tolerates ```json fences), with unchanged-payload fallback (mirrors
  `profile/interview.distill`). Powers the "adjust" loop.
- **Telegram** (`surfaces/telegram.py`): `_propose_action` now handles `propose_commitment` (→ proposal
  card, `prop:track|adjust|cancel`) and `suggest_step_done` (→ tick card, `tick:on|off`). New handlers
  `on_proposal_button`, `on_remind_pref` (`prem:on|off`, after Track these), `on_tick_button`; "adjust" is a
  one-shot conversational loop (`chat_data["proposing"]` + a `chat()` interception mirroring onboarding) that
  re-proposes via `revise_steps`. `/done <id> [force]` and `on_reminder_done` now respect the guard
  (the reminder Done button ticks the chased open step rather than closing the whole item). `/agenda` shows
  `1/3` + the checklist. Registered three new `CallbackQueryHandler`s.
- **Consumers**: `remind/nudge.plan_nudges` compares on the date prefix, **honors `remind`** (opt-out skips;
  default-on still nudges), and **chases the first open step** (shows the due time); `brief/compose` shows
  `[n/total done]` and date-prefix windowing.
- **Tests**: extended `test_ledger_store.py` (steps round-trip, flat-unchanged, auto-complete, open_steps,
  remind default/opt-out, due-with-time, hand-edited checklist), rewrote `test_ledger_tools.py` (action-tool
  shapes + mark_done guard), extended `test_remind.py` (timed due-today, chase open step, remind-off skipped),
  `test_brief_compose.py` (progress + timed due), new `test_ledger_propose.py` (revise + fallbacks).
- **Deployed to prod** (`git push origin main` → self-hosted runner, 3 green deploys) and **live-verified the
  capture path**: told Aurora to track a real item → she proposed → the card rendered → ✅ Track these wrote it
  → the 🔔/🔕 reminder opt fired → `/agenda` listed it. **3 fixes found in real use, all shipped:**
  1. **Source-dedup collision** (`fix(ledger)` in the slice α commit `ba0de8d`): `add()` deduped on the raw
     `source`, but every chat-tracked item uses `source="chat"` → once one existed, every later track collapsed
     onto it and `add` returned an unrelated old task (user saw an NDA reminder come back as the bukti-potong
     task; Aurora correctly flagged the mismatch rather than lying — D20 fidelity working). Fix: dedup only on
     structured provenance keys (containing `:`, e.g. `email:work:ab12`). No data corruption. Regression test.
  2. **DeepSeek tool-call leak** (`e6f8710`): DeepSeek intermittently emits a tool call as *text* in `content`
     (its `｜｜DSML｜｜` markup tokens) instead of the structured `tool_calls` field → the agent loop saw none and
     relayed raw markup to the user. `DeepSeekClient.chat()` now recovers it: `_recover_tool_calls()` parses the
     leaked invoke/parameter markup into OpenAI-style `tool_calls` (lenient regex, coerces value types) and
     strips the markup, so the loop executes it normally. Only triggers when there are no real tool_calls and
     the markers are present. Tests in `test_llm_client.py`. (Model-side leak persists; this makes it a non-issue.)
  3. **Single-step-checklist redundancy** (`967ea3c`): a one-item checklist just restates the title → showed as
     two near-identical lines. Enforced "a checklist needs ≥2 steps, else flat" in `_as_steps` (store chokepoint)
     + `_present_proposal` (card) + the `propose_commitment` description. Parsing is unchanged, so a deliberate
     hand-edited single step is respected. Test added.
- **Test count 188, ruff clean.** Still to walk live: the **tick-off card** (`suggest_step_done`), the
  **mark_done guard** on an open-steps item, and a **09:00 reminder chasing the open step**. Cosmetic leftover:
  `c2` (tracked pre-fix #3) kept its lone redundant step — re-track it or clean the one `  - [ ] …` line in
  `data/ledger/commitments.md`. (Laptop poller stays off — VPS is live.)

## Session 12 — Live-verify slice α + /onboard; onboarding key-map bug fixed (2026-07-01)
- **Health checked**: VPS on `147652e`, service active, 0 errors/24h; Aurora's footprint ~50 MB RSS / near-0
  CPU (a rounding error on the 16 GB box). Noted swap=0 (fine at this load).
- **Slice α live checks (via the bot, user-driven):**
  - **Tick-off card ✅** — "Tick off the OpenWay NDA reminder" → Aurora first *asked* "have you actually
    reminded him?" (D20 definition-of-done caution), then on "I did" showed the suggest-and-confirm card and
    ticked the step. **Last-step auto-complete ✅** — closing the final step closed the whole commitment; `c2`
    correctly dropped off `/agenda`. That also retires the "clean up c2's lone step" chore (done + gone).
  - **Still unwalked**: the `mark_done` guard and a 09:00 reminder step-chase — no stepped open item remains
    to exercise them (c2 closed), so they need a fresh stepped commitment.
- **`/onboard` live-verified — and surfaced a real bug.** 7 of 8 answers filed correctly, but the **sign-off
  answer landed under `handle_vs_check`** ("Use best regards…") with the `signature` key left empty.
  - **Root cause**: onboarding callback buttons carried **no question index** (`onb:save`, `onb:skip`,
    `onb:pick:i`), so a tap on a **stale card** (left from an earlier question) applied to whatever question
    was current — mis-filing the answer.
  - **Data fix (live, no restart)**: renamed the mis-keyed line to `signature` in
    `data/profile/profile.md` on the VPS (backup `profile.md.bak`). `ProfileStore` reads fresh each turn, so
    it took effect immediately.
  - **Code fix (`f20ec5b`, deployed)**: every interview button now stamps the question it was issued for
    (`onb:save:7`, `onb:pick:7:2`, `onb:skip:7`); new pure `_parse_onb_action()` extracts it and the handler
    **ignores a stale tap** whose index ≠ the current question. Old index-less callbacks degrade to a `None`
    index (no crash). New `tests/test_onboard_callbacks.py` (parser + stale-tap detection). **193 tests, ruff
    clean.** Pushed → runner green → VPS on `f20ec5b`, restarted 15:29 Jakarta, healthy.
  - **Open**: not confirmed whether the actual trigger was a stale tap vs. a **skip-then-answer** (user
    skipping the sign-off question, then typing the sign-off on the next one). If the latter, add a second
    guard that warns when a distilled answer looks like it belongs to a different field. Awaiting user recall.
- **Then built Phase 2 slice 2a — procedural playbooks** (design = **D22**). User's calls: **playbooks
  first** (defer episodic to a slice 2b that pairs with the reflection job); creation **both ways**
  (teach-by-confirm + `/playbook` command); seed the withholding-tax playbook.
  - **`aurora/playbook/`** (`store.py` + `__init__.py`): `PlaybookStore`/`Playbook` over
    `data/playbook/playbooks.md` — hand-editable `##` blocks (trigger keywords + ordered steps + notes),
    keyed **upsert-by-name**, atomic + locked writes, `match(text)`, `render_for_prompt()`. Mirrors
    `ProfileStore`.
  - **`aurora/tools/playbook_tools.py`**: `propose_playbook` **action tool** (teach-by-confirm — no handler,
    short-circuits `run_agent` to a Save/Not-now card; never saves silently, D3).
  - **`surfaces/telegram.py`**: registered `PlaybookStore` + tool; injected `render_for_prompt()` into the
    turn prompt (so Aurora proposes a matching playbook's steps when capturing via `propose_commitment` — no
    change to the capture tool); `_present_playbook` card + `on_playbook_button` (`pb:save|cancel`);
    `/playbook` command (list + `forget <name>`); `/help` entry.
  - **Tests**: `test_playbook_store.py` (10) — roundtrip, upsert-by-name, remove-reverts, match by
    trigger/name, render (empty + populated), hand-edited tolerance, empty-steps rejected. **203 pass, ruff
    clean** (`0fc54bd`).
  - **Deployed** (`git push origin main` → runner green, VPS on `86720bf`, restarted). **Seeded 5 starter
    playbooks on the VPS** (`data/playbook/playbooks.md`, `src:seeded`) — user asked for several ("not an
    organized person in the beginning; we can adjust later"), so inferred from real activity:
    withholding-tax, respond-to-tender, invoice-client, onboard-vendor, contract-renewal. Verified they parse
    on the VPS (store reads fresh each turn → live without restart). All adjustable via `/playbook` / hand-edit.
- **Live-tested slice 2a through the bot** (user, ~16:11 WIB):
  - **Capture pulling a playbook ✅** — "track the withholding tax (bukti potong) for vOffice" → the proposal
    card showed the playbook's 3 steps incl. **"Pay the tax to DJP and keep the payment proof (NTPN)"**, which
    no single email would surface. Playbook wiring confirmed. (User tapped ✖ Not now — didn't want the test item.)
  - **Teach-by-confirm ✗ (fixed)** — "…whenever I hire a freelancer I …; save that as a playbook" → Aurora
    called `propose_commitment` (task) instead of `propose_playbook` → "I couldn't shape that into a task."
    A routing miss by deepseek-v4-flash. **Fix (`ed3af37`, deployed):** strengthened the `propose_playbook`
    description (explicit 'save as a playbook' / 'whenever'/'every time' triggers, NOT propose_commitment) and
    added the same disambiguation to the PLAYBOOKS prompt block. **Re-test through the bot pending.**
- **Release versioning added** (user request; **D23**): `aurora.__version__ = 0.6.0` / codename **"Playbooks"**
  (pyproject synced); new **`/version`** command reports release + codename + note + the **live git short SHA**.
  `/help` updated. `tests/test_version.py` (3). **206 tests, ruff clean** (`ed3af37`), deployed.
- **Next**: re-test teach-by-confirm live (routing fix). Then slice 3 (capture corrections) or slice 2b (episodic).
