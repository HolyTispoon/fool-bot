"""
Whether this process publishes, and where to: the `CODEX_PUBLISH_*`
variables in the `.env`, read once as the cog loads (docs/pbd-site.md,
decision 8; docs/design/collaboration.md, "The Codex bot").

They are set on the `K:\\` checkout alone, so a developer's test games
never reach the live site. With any of the three credentials missing, or
boto3 not installed, the publisher is off and says so once at INFO.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping, Optional

from botkit.objectstore import ObjectStore, R2Store

LOGGER = logging.getLogger(__name__)

ACCOUNT_ID = "CODEX_PUBLISH_ACCOUNT_ID"
ACCESS_KEY_ID = "CODEX_PUBLISH_ACCESS_KEY_ID"
SECRET_ACCESS_KEY = "CODEX_PUBLISH_SECRET_ACCESS_KEY"
BUCKET = "CODEX_PUBLISH_BUCKET"

#: The bucket's name where `CODEX_PUBLISH_BUCKET` is not set.
DEFAULT_BUCKET = "pbd"

REQUIRED = (ACCOUNT_ID, ACCESS_KEY_ID, SECRET_ACCESS_KEY)


def store_from_env(environ: Optional[Mapping[str, str]] = None) -> Optional[ObjectStore]:
    """The bucket to publish into, or `None` where the publisher is off."""
    environ = os.environ if environ is None else environ
    values = {name: (environ.get(name) or "").strip() for name in REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        LOGGER.info("Codex games are not published to the web: %s not set.", ", ".join(missing))
        return None
    bucket = (environ.get(BUCKET) or "").strip() or DEFAULT_BUCKET
    try:
        store = R2Store(values[ACCOUNT_ID], values[ACCESS_KEY_ID], values[SECRET_ACCESS_KEY], bucket)
    except ImportError:
        LOGGER.info("Codex games are not published to the web: boto3 is not installed.")
        return None
    LOGGER.info("Codex games are published to the R2 bucket %s.", bucket)
    return store
