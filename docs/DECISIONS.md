# Aurora — Decision Log

Durable decisions and the reasoning behind them. Add an entry when a real choice is made;
don't restate the code. Newest at the bottom.

---

### D1 — Aurora is a *process*, not a particular platform
The user cares about a process that supports their needs and learns over time, more than the
tech stack. Tech choices are deliberately swappable.

### D2 — Inbox first, but on a reusable spine
First domain is email / don't-miss-a-thing. Built so other domains (calendar, notes, finance)
plug into the same spine (Source → reasoning → proposal → approval → memory → reflection).

### D3 — Learning = "correct-and-remember"
Aurora proposes; the user accepts/edits/rejects; corrections become durable, human-readable
rules. Memory is plain markdown the user can read and edit (`data/memory/memory.md`).

### D4 — Approve-before-acting, but autonomy is switchable
Default mode `approve_all`. Anything that leaves a mailbox (send) is gated by an explicit user
tap regardless of mode. Autonomy is a first-class config value (`AURORA_AUTONOMY_MODE`) so modes
can change later — the user explicitly required being able to switch.

### D5 — Aurora is a delegate, not an email viewer  ⭐ core principle
The user said: *"If I want to read emails myself I can open the portal… I ask her to read and let
me know what's up. She is not a tool that reads all emails verbatim."* So: no `/inbox` list dumps.
She reads/searches/acts via tools and reports in her own words. This drove the redesign of M1 from
a command+list UI into a conversational tool-use agent. (Also saved as Claude memory.)

### D6 — Conversational tool-use (LLM function calling) is the spine
DeepSeek supports OpenAI-style function calling. The chat handler runs an agent loop: read-only
tools execute inline; the first *action* tool short-circuits to a user-approval prompt. This loop
is the reusable mechanism for every future capability — add a tool, not a new UI.

### D7 — Email: Gmail API for personal, IMAP/SMTP for work
Personal `magyp.magyp@gmail.com` = Gmail API + OAuth (scope `gmail.modify` = read/modify/draft/send,
no permanent delete). Work `mahdi.ali@matajari.co.id` is on dapurhosting (NOT Google) → will use
IMAP/SMTP with the mailbox password in gitignored `.env`. Both sit behind one `MailAccount`
interface so Aurora treats them identically. (User chose full read+send over ingress-only.)

### D8 — Forgetting must truly revert behavior
A forgotten preference must stop affecting Aurora, including via leftover examples. So generated
draft bodies are NOT stored in the short-term conversation thread (only a short note); style/length
follow current memory + latest instruction, not past drafts.

### D9 — Notifications should learn what matters (not work-only vs everything)
(Decided in principle, not yet built.) Proactive notifications should start with sensible defaults
and learn the user's threshold via feedback — not a hardcoded "work only" or "everything" rule.

### D13 — Proactive notifications: smart-filter + ask, learn via memory (realizes D9)
M3 makes Aurora proactive. Design choices:
- **Posture** (user-chosen): *smart-filter + ask* — notify clear-important, stay silent on obvious
  noise, ASK when genuinely unsure. Not notify-everything, not important-only-silent.
- **Mechanism**: a dependency-free asyncio poll loop (PTB's JobQueue needs APScheduler, which isn't
  installed), every `AURORA_NOTIFY_INTERVAL_SECONDS` (default 600 / user-chosen 10 min). Each new
  email is classified by one batched `llm.complete` call.
- **Restart-safe seen-state** (`NotifyState`, JSON in `data/`): seeds silently on first contact so
  startup doesn't flood; persistence means mail arriving while offline is still caught on next run.
- **Learning = memory**: notification feedback is saved *directly* (no Remember-button — it's an
  explicit instruction) via `set_notification_rule`, and the classifier reads memory, so a new rule
  takes effect on the very next poll. Same "correct-and-remember" spine as D3.
- **Fail-open**: if the classifier/parse fails, default to notifying (never silently drop mail).
- **Limitation**: laptop-only for now → notifications pause when the bot is off (motivates VPS deploy).

### D12 — Fidelity: paraphrase the framing, never the content
"Delegate, reports in her own words" (D5) governs *framing*, not *facts*. When Aurora reproduces
actual message text — quoting it, reading it back, confirming what she sent/drafted — she must copy
it exactly (no changed wording, numbers, names, or emoji) and use the real draft/message, not a
regeneration from memory. Trigger: a live send test where she silently swapped 🕌→🕋 in the read-back,
which (in a functionality check) made the user doubt the send worked. Altering a detail when the user
may be verifying correctness erodes trust. Encoded as a FIDELITY clause in the email-capability prompt.

### D11 — Work IMAP connector: per-op connections, PEEK reads, copy-to-Sent
(M2.) `ImapAccount` opens a fresh IMAP/SMTP connection **per operation** (servers drop idle
sockets; the bot is long-lived), injected via factories so tests use fakes. Reads use
`BODY.PEEK[]` so Aurora reporting on mail never marks it `\Seen`. SMTP send does **not** auto-file
sent mail, so after a successful send we IMAP-`APPEND` a copy to the Sent folder (parallels Gmail).
Host/ports are explicit `.env` config (no auto-probing); username is the full email address.

### D10 — Runtime & deployment
DeepSeek `deepseek-v4-flash` default. Python on the user's VPS is the eventual home (`ssh prod`,
`/home/mahdi`, `sudo`); for now the bot runs on the laptop. Develop locally, deploy later.

### D14 — Stay hand-rolled; don't adopt an agent framework (yet)
After a head-to-head (openclaw, Hermes/n8n, Mem0, PydanticAI/LangGraph/Letta) we keep the
hand-rolled Python tool-use loop. For a single-user, single-surface, single-provider delegate,
frameworks add abstraction/lock-in without deleting code we actually have (Anthropic's *Building
Effective Agents*: simple composable patterns beat frameworks). `openclaw` is close in spirit but a
heavy TypeScript monolith — mine it for ideas (personality file, skills registry, cron), don't
migrate. Revisit only **Mem0** *as a library* if memory consolidation gets painful. Migration test:
if you can't name the code a framework deletes, you don't need it.

### D15 — Commitments ledger is the don't-miss-a-thing source of truth
A single, hand-editable markdown ledger (`data/ledger/commitments.md`, `aurora/ledger/`) tracks open
loops: tasks, replies owed, deadlines, meeting prep — each with owner/status/due/provenance. It's the
substrate the daily brief and proactive chasing read from, so nothing slips. Inline (non-approval)
tools `add/list/update/mark_done` let Aurora maintain it conversationally; `render_for_prompt()`
injects open items each turn. Unlike memory it's the source of truth for obligations, so writes are
**atomic** (tmp + `os.replace`) and locked. Email auto-capture proposes entries via a one-tap "Track
this" button on notifications, deduped by `email:<account>:<id>` so the chat and proactive paths can't
double-store. Realizes BACKLOG #2.

### D16 — Daily brief + weekly review on a reusable scheduler
Aurora sends a structured **morning brief** (EA section order: questions for you → your focus today →
handled → updates → FYIs; top-3 capped, "critical" rationed) and a **weekly review** (two weeks
ahead). Built on a small dependency-free scheduler (`aurora/schedule/`) — a coarse 60s tick plus a
persisted last-fired date (`ScheduleState`) — chosen over sleep-until-next because it gives offline
catch-up, no-double-send, and DST-safety for free. Timezone via `AURORA_TIMEZONE` (Jakarta default;
`tzdata` added so `zoneinfo` works on Windows, with a fixed UTC+7 fallback). The brief is one
`llm.complete` over ledger + a small activity log (`aurora/activity/`), with a quiet-day path that
sends nothing.

### D18 — VPS deployment: systemd service + self-hosted Actions runner (pull-based)
Aurora now runs 24/7 on the VPS (`prod`, `103.150.194.135`, Ubuntu 24.04) under **systemd**
(`aurora-bot.service`, `User=matajari`, `Restart=always`, enabled at boot) from `/home/mahdi/aurora`.
Deployment is **pull-based** because the VPS's **inbound port 22 is IP-restricted** (GitHub's cloud
runners can't SSH in): a **self-hosted GitHub Actions runner** on the VPS (service, runs as `matajari`)
makes only **outbound HTTPS 443** connections, and `.github/workflows/deploy.yml` (on push to `main`)
does `git reset --hard origin/main` → `pip install -e .[dev]` → `pytest` (gate) → `systemctl restart
aurora-bot`. The private repo is `github.com/mahdialig/aurora`; the VPS clones via a **read-only deploy
key**. Gitignored secrets (`.env`, `credentials.json`, `data/`) live on the VPS and survive deploys
(`reset --hard` leaves untracked files; the workflow never `git clean`s). The "needs sudo under
`/home/mahdi`" annoyance was the dir being `root`-owned → fixed with `chown -R matajari:matajari`. Only
one Telegram poller may run at once, so the laptop bot stays off. (Supersedes the laptop-only note in D10.)

### D17 — (planned) Learn preferences via onboarding + observe-and-correct
Not yet built; recorded so the direction is durable. Aurora will discover the user's preferences with
a short `/onboard` interview (proven week-1 EA questions) to seed a profile, then learn by the user's
corrections on real proposals — completing the "correct" half of D3. Backed by a three-layer memory
(episodic log / distilled semantic preferences / procedural playbooks) with a confirm-before-save
write gate (scope, provenance, dedup) and a nightly reflection job. Guardrails: distilled lessons in
the prompt (not transcripts), every durable memory human-confirmed + traceable, TTL/decay vs drift.

**Slice-1 build note (session 10):** the profile is a new keyed store `ProfileStore`
(`aurora/profile/`, `data/profile/profile.md`) — deliberately separate from the flat `MemoryStore`, and
modeled on the ledger (atomic+locked, **upsert-by-key**) rather than memory, because preferences must
update in place and forgetting must truly revert (D8). This store **is the seed of the semantic layer**:
slice 2 keeps it as-is and adds episodic + procedural alongside; slices 3–4 write corrections/reflections
back through its `set()` (upsert = dedup + provenance for free). Interview UX (user-chosen): one question
at a time, preset buttons + free-text; a **preset tap saves directly** (the tap is the confirmation) while
**free-text is distilled and gated** by a Save/Edit/Skip card — honoring "confirm per answer" (D4) without
double-tapping. Onboarding answers also feed the notify classifier so threshold/VIPs bite the same day.

### D19 — A clock in the prompt + proactive reminders ride the scheduler
Two gaps surfaced by the user (session 10): Aurora was **time-blind in chat** (the conversational prompt
never carried the date/time, only the brief knew it) and she **only ever responded** — no targeted
reminders or progress check-ins. Fixes, both small and on existing machinery:
- **Clock**: inject the real current date/time (in `AURORA_TIMEZONE`, resolved once into `bot_data["tz"]`)
  into every chat turn's system prompt. Cheap, and it also makes due-date/"tomorrow" reasoning correct.
- **Reminders + check-ins** (`aurora/remind/`): a third scheduled job (`REMINDER_JOB`, 09:00 default) over
  the commitments ledger. Design split: **dated** items → deadline reminders that **repeat daily until
  done** (that's the job of a reminder); **undated** items → **check-ins that are rate-limited** per item
  (`RemindState`, re-ask only after `reminder_stale_days`) so Aurora nudges without nagging — "still waiting
  on X?" for `owner=other`, "how's this going?" for `owner=me`. Capped per pass with an overflow line; each
  nudge has a ✅ Done button (`rdone:` → `mark_done`). Chose a once-daily scheduled pass (simple, matches a
  daily agenda cadence) over riding the 10-min notifier loop; revisit if mid-day items need faster pickup.
  This is the same 4-touch scheduler recipe slice-4's reflection job will reuse.

### D20 — Aurora applies a "definition of done" (receipt ≠ completion)
Trigger (session 10): Aurora read an email where vOffice confirmed receiving the *bukti potong* and told
the user "you're all set ✅" — but that's only step 1 of a withholding-tax obligation; the real task is
**paying DJP**, which she knew nothing about. She declared an obligation complete from a counterparty's
receipt-confirmation. The user's framing: adopt a **definition-of-done standard** (à la Scrum) rather than
patch tax specifically. So a standing clause in `SYSTEM_PROMPT`: before calling anything done/"all set" — in
chat or by marking a ledger item complete — the actual GOAL must be achieved and **confirmed** (by the user
or unambiguous evidence), not merely a step acknowledged. A third party receiving/acknowledging closes only
that step; for money/taxes/deadlines/filings/another party's action, "received" = **in progress**. When
steps remain or she's unsure, she states what's confirmed, names what's open, and offers to track it —
she doesn't close the loop on the user's behalf. This is the *general* judgment fix; the *specific* workflow
knowledge ("for withholding tax, bukti-potong is step 1, DJP payment is the real done") belongs in the
**procedural playbooks** layer (Phase 2 slice 2) — this is its motivating example.
