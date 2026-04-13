"""Shared helper for rendering an admin moderation card.

Extracted from ``src.presentation.admin_panel.admin_menu`` so that
``src.presentation.admin_panel.admin.archive`` can import it without creating a
circular dependency through the monolithic admin_menu module.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.submission import Submission
from src.domain.submission.submission_service import SubmissionService
from src.core.utils.ui_builder import GDPXRenderer

# Compiled phone-number pattern shared between archive search and inwork filter.
PHONE_QUERY_PATTERN = re.compile(r"(?:\+7|7|8)\d{10}")


async def render_admin_moderation_card(
    *,
    session: AsyncSession,
    submission: Submission,
) -> str:
    """Return HTML caption for a submission moderation card.

    Checks for phone-number duplicates and delegates rendering to
    ``GDPXRenderer``.  Public (no leading underscore) so callers can
    import it without accessing private admin_menu internals.
    """
    svc = SubmissionService(session=session)
    is_duplicate = await svc.has_phone_duplicate(
        submission_id=submission.id,
        phone=submission.description_text,
    )
    return GDPXRenderer().render_moderation_card(submission, is_duplicate=is_duplicate)


# Backward-compat alias kept so admin_menu.py can re-export the old private name
# without changing 15+ call-sites inside the monolith.
_render_admin_moderation_card = render_admin_moderation_card
