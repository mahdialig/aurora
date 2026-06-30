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
