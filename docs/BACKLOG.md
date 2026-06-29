# Aurora — Backlog & Tech Debt

Prioritized. Move items to WORKLOG when done. Keep "Next up" honest.

## Next up (in order)
1. **M2 — Work IMAP account** (`mahdi.ali@matajari.co.id`, dapurhosting).
   - New `aurora/sources/imap.py` `ImapAccount(MailAccount)` using `imaplib` + `smtplib`
     (list/search/read, append to Drafts, send threaded replies via SMTP). Reuse `build_mime`.
   - Config: `WORK_EMAIL`, `WORK_PASSWORD`, `WORK_IMAP_HOST/PORT`, `WORK_SMTP_HOST/PORT` in `.env`
     (all optional; gitignored). Auto-detect host by probing `mail.matajari.co.id` / `d001.dapurhosting.com`.
   - Register as `"work"` in `registry.build_mail_accounts`. Verify "all"/"work" routing.
   - **Needs from user:** the work mailbox password.
2. **Proactive notifications** ("don't miss a thing") — the big one.
   - Background job (cron/systemd or in-process scheduler) that checks for new/important mail and
     pushes a Telegram message unprompted. Decide importance via defaults + learned feedback (D9).
   - Likely needs a "commitments ledger" (deadlines / awaiting-reply / tasks) — was in the original
     plan, not yet built.
3. **Compose a fresh email** (not just replies) — small: a `compose_email` action tool (to/subject/
   body) + `MailAccount.send_new`, same approval flow. Wrinkle: addressing (no contacts yet) and
   higher stakes (new recipient).

## Later / nice-to-have
- **Gmail draft management**: list/send existing Gmail drafts across sessions (today's
  `resend_last_draft` only works within the current conversation, server-side).
- **VPS deployment**: systemd service for the bot + timers for jobs. Currently laptop-only.
- **Autonomy modes UI**: `/mode` command to switch `approve_all` ↔ `digest` ↔ `auto_low_risk` ↔
  `autonomous` (config field exists; no command yet).
- **Reflection job** (nightly): consolidate corrections into cleaner rules.
- Multimodal input (PDFs/images/voice) — from the original vision.
- Obsidian notes, calendar, finance domains (same tool-use spine).

## Tech debt / risks
- **OAuth token expiry**: Google app is in "Testing" → refresh token may expire ~weekly →
  re-run `python -m aurora.sources.gmail_auth`. Option: publish app to Production (unverified) to
  stop expiry. Two client secrets currently exist on the OAuth client; the old one can be deleted.
- **Pending actions are in-memory**: `pending_replies` / `last_reply` / pending memories live in
  bot RAM — lost on restart (buttons/resend "expire"). Fine for now; persist if it annoys.
- **Bot lifecycle is manual**: started by hand each session; no auto-restart/supervision.
- **No real Gmail API integration tests** (unit tests use a fake service); live verification only.
- `.sim/` cost analysis is uncommitted — decide: commit as docs or add to `.gitignore`.
