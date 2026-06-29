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

### D10 — Runtime & deployment
DeepSeek `deepseek-v4-flash` default. Python on the user's VPS is the eventual home (`ssh prod`,
`/home/mahdi`, `sudo`); for now the bot runs on the laptop. Develop locally, deploy later.
