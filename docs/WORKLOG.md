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
