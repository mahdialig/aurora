# Aurora

A process-first personal assistant that **learns your preferences over time**.

Aurora's priority is the *process*, not the platform. Every domain it handles —
starting with your inbox — runs on one reusable spine:

```
Source → Reasoning (LLM) → Proposal → Autonomy Policy → [Approve / Act / Digest]
                                                                  │
                                                          Feedback capture
                                                                  │
 Commitments Ledger  ◀──────────────  Memory (rules)  ◀── Reflection (scheduled)
 (don't-miss-a-thing)
```

Aurora **proposes**, you **accept / edit / reject**, and every correction becomes a
durable, human-readable rule it follows next time. A scheduled reflection step
consolidates those corrections so it keeps getting better.

See `INIT.md` for the original vision and the plan in
`.claude/plans/` for the full design.

## Status

Milestone **M0 — Scaffolding**: project structure, config/secrets, a swappable
LLM client, and a Telegram echo bot wired to DeepSeek. This proves the surface +
LLM plumbing before any inbox work (M1+).

## Setup

```bash
# 1. Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Configure secrets
cp .env.example .env             # then fill in DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, AURORA_ALLOWED_USER_ID

# 3. Run the bot
aurora-bot                       # or: python -m aurora.surfaces.telegram
```

Then message your bot on Telegram — it replies via DeepSeek. Only the user id in
`AURORA_ALLOWED_USER_ID` is allowed to talk to it.

### Getting the prerequisites

- **DeepSeek API key:** https://platform.deepseek.com → API keys.
- **Telegram bot token:** message [@BotFather](https://t.me/BotFather) → `/newbot`.
- **Your Telegram user id:** message [@userinfobot](https://t.me/userinfobot), or
  start your bot and read the id it logs.

## Deploying to the VPS

Aurora is meant to run on the VPS (`ssh prod`, work under `/home/mahdi`). The same
steps apply there; a `systemd` service for the bot and timers for the daily jobs
come in later milestones.

## Roadmap

| Milestone | What it adds |
|-----------|--------------|
| **M0** | Scaffolding: surface + LLM plumbing *(current)* |
| M1 | Read-only Gmail → commitments ledger → morning digest |
| M2 | Proposals (reply draft / archive / label / reminder) with approve-before-acting |
| M3 | Memory + feedback: corrections become rules that shape next proposals |
| M4 | Reflection: nightly consolidation + evening confirmation |
| M5 | Switchable autonomy modes (`/mode`) |
