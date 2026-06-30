"""Registry of Aurora's mail accounts, built from config.

Aurora may have zero, one, or both accounts connected. Tools always exist; if a
selected account isn't connected, the handler reports that rather than crashing.
"""

from __future__ import annotations

import logging

from aurora.sources.base import MailAccount
from aurora.sources.gmail import GmailAuthError, GmailClient
from aurora.sources.imap import ImapAccount, ImapError

logger = logging.getLogger("aurora.mail")


class MailAccounts:
    """A lookup over the connected accounts, keyed by label ('personal'/'work')."""

    def __init__(self, accounts: dict[str, MailAccount]) -> None:
        self._accounts = dict(accounts)

    def get(self, name: str) -> MailAccount | None:
        return self._accounts.get(name)

    def names(self) -> list[str]:
        return list(self._accounts)

    def is_empty(self) -> bool:
        return not self._accounts

    def resolve(self, selector: str | None) -> list[tuple[str, MailAccount]]:
        """Map a selector ('personal' | 'work' | 'all'/None) to (name, account) pairs."""
        if not selector or selector == "all":
            return list(self._accounts.items())
        account = self._accounts.get(selector)
        return [(selector, account)] if account else []


def build_mail_accounts(config) -> MailAccounts:
    """Construct the available accounts from config (skipping unconnected ones)."""
    accounts: dict[str, MailAccount] = {}

    try:
        accounts["personal"] = GmailClient.from_config(config, label="personal")
    except GmailAuthError as exc:
        logger.info("Personal Gmail not connected: %s", exc)

    try:
        accounts["work"] = ImapAccount.from_config(config, label="work")
    except ImapError as exc:
        logger.info("Work IMAP not connected: %s", exc)

    return MailAccounts(accounts)
