# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session start protocol ("Start")

When the user says **"Start"**, **"Start session"**, or otherwise opens a fresh working session,
do this before anything else:
1. Read `docs/STATE.md` (the project entry point), then `docs/WORKLOG.md`, `docs/DECISIONS.md`,
   and `docs/BACKLOG.md`.
2. Give a short recap (4–6 lines): where the project is, what's running, and the top "Next up" item.
3. Ask what to work on (defaulting to the top BACKLOG item).
At the **end** of a working session, update `docs/STATE.md` (the "Last updated" line + status) and
append entries to `WORKLOG.md` / `DECISIONS.md` / `BACKLOG.md` as needed. These docs are the
durable memory of the project — keep them honest and current.

## What Aurora is

A Telegram-based personal AI assistant the user **delegates to** (not a dashboard). The user talks
to her; she uses tools (currently email) to act and reports in her own words. She must never dump
data verbatim. Long-term goal (`INIT.md`): email/calendar/notes/finance, multimodal input, and a
system that learns the user's preferences over time. Core principles live in `docs/DECISIONS.md` —
read them; they constrain design (esp. D5 "delegate, not a viewer" and D4 "approve-before-acting").

## Commands

Windows; a virtualenv lives at `.venv`. Use the venv interpreter explicitly.

```bash
# Install (editable, with dev deps)
./.venv/Scripts/python.exe -m pip install -e ".[dev]"

# Tests (all) / single file / single test
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q
./.venv/Scripts/python.exe -m pytest tests/test_agent.py::test_plain_text_no_tools -q

# Lint
./.venv/Scripts/ruff.exe check aurora tests

# Run the Telegram bot (long-running; runs on the laptop for now)
./.venv/Scripts/python.exe -m aurora.surfaces.telegram

# One-time Gmail OAuth (opens a browser; writes data/token.json). Re-run if the token expires.
./.venv/Scripts/python.exe -m aurora.sources.gmail_auth
```

The above run command is for **local dev only**. In production the bot runs **on the VPS under systemd**
(see "Deployment" below) — do NOT start a second instance locally while the VPS bot is up (only one
Telegram poller may run at once). Restarting (either place) clears in-memory state (conversation threads,
pending actions).

Production runtime (VPS, `ssh prod`):
```bash
sudo systemctl status aurora-bot          # health
sudo systemctl restart aurora-bot         # restart
journalctl -u aurora-bot -f               # live logs
```
Deploy by pushing to `main` (`git push origin main`) — a self-hosted Actions runner on the VPS pulls,
tests, and restarts. See `docs/DECISIONS.md` D18.

## Architecture

Everything hangs off one **agent loop** with **tools**; adding a capability = adding a tool, not a UI.

- `aurora/surfaces/telegram.py` — the chat surface. `_respond()` builds the prompt
  (`SYSTEM_PROMPT` + email-capability note + `MemoryStore.render_for_prompt()` + recent thread),
  runs the agent loop, and either replies, offers a "remember this" button, or presents an action
  for approval (`_propose_action` → Send/Save-draft/Cancel). Commands: `/inbox` (a "summarize unread"
  shortcut), `/remember` `/memory` `/forget` `/new` `/whoami` `/start`.
- `aurora/agent.py` — `run_agent(llm, messages, tools)`: the tool-use loop. Read-only tools run
  inline and feed results back; the first **action** tool short-circuits to `AgentResult(action_*)`
  for user approval (it is NOT executed in the loop). Forces a final text answer if it runs long.
- `aurora/llm/client.py` — `LLMClient` interface; `DeepSeekClient` (OpenAI-compatible). `complete()`
  for plain text, `chat()` for function calling.
- `aurora/tools/email_tools.py` — `build_email_tools(accounts)` → read tools (`list_unread`,
  `search_mail`, `read_email`) + action tools (`reply_to_email`, `resend_last_draft`). Action tools
  have `is_action=True` and no handler.
- `aurora/sources/` — `base.py` (`MailAccount` ABC + `EmailSummary`/`EmailMessage`/`Reply` + MIME
  helpers), `gmail.py` (`GmailClient(MailAccount)` over the Gmail API; lazy Google imports),
  `gmail_auth.py` (OAuth CLI), `registry.py` (`MailAccounts` + `build_mail_accounts`). `imap.py`
  (work account) is not built yet — see `docs/BACKLOG.md`.
- `aurora/memory/store.py` — `MemoryStore` over `data/memory/memory.md` (plain markdown, hand-editable).
- `aurora/config.py` — `Config.load()` reads `.env` (secrets) and validates.

Data flow for a turn: Telegram message → `_respond` → `run_agent` (LLM ↔ tools) → reply OR an
approval card. Two memory layers: long-term (`MemoryStore`, persisted) and short-term (the per-chat
conversation thread, in RAM). Draft bodies are deliberately NOT stored in the thread (see D8).

## Secrets & data (never commit)

Gitignored: `.env` (DeepSeek key, Telegram token+allowed user id, model, autonomy mode, and later
work IMAP creds), `credentials.json` (Google OAuth client), `data/` (sqlite/token/memory). These
already exist locally — don't recreate them. Telegram bot `@paagentaurorabot` is locked to the
user's id. Both mailboxes are connected: personal Gmail (`gmail.modify`) and work IMAP/SMTP.

## Deployment (VPS) — LIVE

Aurora runs 24/7 on the VPS: `ssh prod` (user `matajari`, `103.150.194.135`), app at
`/home/mahdi/aurora`, under systemd `aurora-bot.service` (`Restart=always`, enabled at boot).
`/home/mahdi` is owned by `matajari` — **no sudo needed for file ops there** (sudo is still needed, and
is passwordless, for system-level things: apt, `/etc/systemd`, the runner service).

Deploy = `git push origin main` → a **self-hosted GitHub Actions runner** on the VPS (outbound-only;
inbound :22 is IP-restricted) pulls, runs `pytest`, and restarts the service
(`.github/workflows/deploy.yml`). Repo `github.com/mahdialig/aurora` (private; VPS uses a read-only
deploy key). Secrets (`.env`, `credentials.json`, `data/`) live on the VPS only and survive deploys.
Treat the VPS as production: confirm before destructive or outward-facing actions there. See D18.
