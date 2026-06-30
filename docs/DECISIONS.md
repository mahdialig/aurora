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

### D17 — (planned) Learn preferences via onboarding + observe-and-correct
Not yet built; recorded so the direction is durable. Aurora will discover the user's preferences with
a short `/onboard` interview (proven week-1 EA questions) to seed a profile, then learn by the user's
corrections on real proposals — completing the "correct" half of D3. Backed by a three-layer memory
(episodic log / distilled semantic preferences / procedural playbooks) with a confirm-before-save
write gate (scope, provenance, dedup) and a nightly reflection job. Guardrails: distilled lessons in
the prompt (not transcripts), every durable memory human-confirmed + traceable, TTL/decay vs drift.
