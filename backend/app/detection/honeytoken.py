"""Planted fake credentials, and catching anyone who tries to use one.

A honeyfile tells you someone *looked*. A honeytoken tells you someone took
what they found and tried it. That is a different class of signal: browsing a
folder has innocent explanations, replaying a credential lifted out of a decoy
file does not. So it scores far higher than any behavioural rule and gets its
own action type instead of folding into OPEN/DOWNLOAD.

Planting: the decoy generator writes `<redacted in this build>` wherever a
secret would go. Before the body is cached, each of those markers is replaced
with a freshly minted token and a `honeytokens` row. A decoy with no marker -
a budget spreadsheet, say - simply carries no token, because a real one
wouldn't.

Catching: every inbound request is scanned for any known token, in the headers,
the query string and the body. Nothing in this system ever treats a honeytoken
as valid; being seen at all is the whole event.
"""
import secrets

from sqlalchemy.orm import Session as DbSession

from app.models import Honeytoken, utcnow

# The marker the decoy generator's system prompt asks the model to emit.
PLACEHOLDER = "<redacted in this build>"

# Plausible-looking but unmistakably ours once you know the prefix. Nothing
# accepts these as credentials anywhere - they exist only to be noticed.
TOKEN_PREFIX = "hv_live_"
TOKEN_BYTES = 16

# Cap on how much request body is scanned, so a large upload cannot turn one
# request into an expensive substring sweep.
MAX_SCAN_BYTES = 64 * 1024


def mint_token() -> str:
    return TOKEN_PREFIX + secrets.token_hex(TOKEN_BYTES)


def _label_for(content: str, index: int) -> str:
    """Best-effort name for the field a marker was standing in, for display.

    Looks left from the marker for a `KEY=` or `key:` style name on the same
    line. Purely cosmetic - it only ever reaches the admin dashboard.
    """
    line_start = content.rfind("\n", 0, index) + 1
    prefix = content[line_start:index]
    for sep in ("=", ":"):
        if sep in prefix:
            name = prefix.rsplit(sep, 1)[0].strip().strip("#").strip()
            if name and len(name) <= 64:
                return name
    return prefix.strip()[:64] or None


def plant_tokens(db: DbSession, f, content: str) -> str:
    """Replace every redaction marker in `content` with a minted token.

    Returns the rewritten body. Each replacement gets its own `honeytokens`
    row pointing at this file, so a leak can be traced to the exact field.
    Content with no marker comes back unchanged and plants nothing.
    """
    if PLACEHOLDER not in content:
        return content

    out = []
    cursor = 0
    while True:
        index = content.find(PLACEHOLDER, cursor)
        if index == -1:
            out.append(content[cursor:])
            break
        out.append(content[cursor:index])
        token = mint_token()
        db.add(
            Honeytoken(
                file_id=f.id,
                token=token,
                label=_label_for(content, index),
            )
        )
        out.append(token)
        cursor = index + len(PLACEHOLDER)

    db.flush()
    return "".join(out)


def clear_tokens(db: DbSession, f) -> int:
    """Drop the tokens planted in one file, before its body is regenerated."""
    rows = db.query(Honeytoken).filter(Honeytoken.file_id == f.id).all()
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


def find_in(db: DbSession, haystack: str):
    """Return the first known honeytoken appearing in `haystack`, or None.

    The token set is tiny (a handful of rows), so a straight scan is cheaper
    and clearer than anything cleverer. The prefix check short-circuits the
    overwhelming majority of requests without touching the database.
    """
    if not haystack or TOKEN_PREFIX not in haystack:
        return None
    for row in db.query(Honeytoken).all():
        if row.token in haystack:
            return row
    return None


def mark_used(db: DbSession, row: Honeytoken) -> None:
    row.use_count = int(row.use_count or 0) + 1
    if row.first_used_at is None:
        row.first_used_at = utcnow()
    db.flush()
