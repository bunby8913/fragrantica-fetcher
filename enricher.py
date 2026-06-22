"""Orchestrate enrichment of pyramid notes with Fragrantica odor profiles.

The scraper module handles raw HTML parsing of Fragrantica pages; this
module wires the scraper to the database cache so that:

* A pyramid returned by :func:`scraper.extract_perfume_data` is enriched
  in-place: each note gains an ``odor_profile`` field.
* Notes already cached in ``fragrantica_note_profiles`` are reused
  without making any HTTP request.
* Missing profiles are scraped and persisted for future calls.
* Conservative rate limiting is applied between note-page requests to
  reduce the risk of being rate-limited by Fragrantica.
* Failures are isolated: a single note that errors out does not abort
  the rest of the enrichment, and the note's ``odor_profile`` is set
  to an empty string. A short ``error`` field is set for debugging.
* For older entries whose stored ``pyramid_data`` predates the
  ``note_url`` field, the note URL is reconstructed from the
  ``note_id`` and ``note_name`` using the predictable Fragrantica URL
  pattern ``/notes/{slug}-{id}.html``.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Iterable
from urllib.parse import urljoin

from db import get_note_profile, get_note_profiles, upsert_note_profile
from scraper import (
    FRAGRANTICA_BASE,
    extract_note_group,
    extract_note_odor_profile,
    fetch_page,
)

PYRAMID_LEVELS = ("top_notes", "middle_notes", "base_notes")

DEFAULT_RATE_LIMIT_SECONDS = 0.5


def _slugify_note_name(name: str) -> str:
    """Convert a note name to a Fragrantica-style URL slug.

    Fragrantica note URLs use a slug derived from the note's display
    name (spaces and non-alphanumerics collapsed to hyphens, with any
    surrounding hyphens stripped).
    """
    if not name:
        return ""
    return re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-")


def _build_note_url(note_id: str, note_name: str) -> str:
    """Reconstruct an absolute Fragrantica note URL from id + name.

    Used as a fallback for older entries whose stored ``pyramid_data``
    does not include the original ``note_url`` field.
    """
    slug = _slugify_note_name(note_name)
    if not slug:
        return ""
    return urljoin(FRAGRANTICA_BASE, f"/notes/{slug}-{note_id}.html")


def _resolve_note_url(note: dict) -> str:
    """Return the note's absolute URL, reconstructing from id+name when missing."""
    note_id = str(note.get("note_id") or "")
    note_url = (note.get("note_url") or "").strip()
    if note_url:
        return note_url
    note_name = (note.get("name") or "").strip()
    if note_id and note_name:
        return _build_note_url(note_id, note_name)
    return ""


def _collect_note_ids(pyramid: dict) -> list[str]:
    note_ids: list[str] = []
    for level in PYRAMID_LEVELS:
        for note in pyramid.get(level, []) or []:
            note_id = str(note.get("note_id") or "")
            if note_id and note_id not in note_ids:
                note_ids.append(note_id)
    return note_ids


def _attach_profile(note: dict, profile: dict) -> None:
    note["odor_profile"] = (profile.get("odor_profile") or "") if profile else ""
    note["group_name"] = (profile.get("group_name") or "") if profile else ""


def _fetch_and_cache(
    note: dict,
    fetcher: Callable[[str], str],
    parser: Callable[[str], str],
) -> None:
    note_id = str(note.get("note_id") or "")
    note_url = _resolve_note_url(note)
    note_name = note.get("name") or ""

    if not note_id or not note_url:
        note["odor_profile"] = ""
        note["group_name"] = ""
        return

    try:
        html = fetcher(note_url)
        odor_profile = parser(html) or ""
        group_name = extract_note_group(html) or ""
        note["odor_profile"] = odor_profile
        note["group_name"] = group_name
        if note.get("note_url") != note_url:
            note["note_url"] = note_url
        upsert_note_profile(
            note_id=note_id,
            note_name=note_name,
            note_url=note_url,
            odor_profile=odor_profile,
            group_name=group_name,
        )
    except Exception as exc:  # noqa: BLE001 - we want to capture any failure
        note["odor_profile"] = ""
        note["group_name"] = ""
        note["error"] = str(exc)[:200]


def enrich_notes_with_odor_profiles(
    pyramid: dict,
    *,
    fetcher: Callable[[str], str] = fetch_page,
    parser: Callable[[str], str] = extract_note_odor_profile,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """Enrich a pyramid dict with cached or freshly scraped odor profiles.

    The function mutates and returns the same ``pyramid`` dict. Each note
    in ``top_notes``/``middle_notes``/``base_notes`` gains an
    ``odor_profile`` string (possibly empty). Notes already in the cache
    are not refetched.
    """
    if not pyramid:
        return pyramid

    note_ids = _collect_note_ids(pyramid)
    if not note_ids:
        return pyramid

    cached = get_note_profiles(note_ids)

    made_request = False
    for level in PYRAMID_LEVELS:
        for note in pyramid.get(level, []) or []:
            note_id = str(note.get("note_id") or "")
            if not note_id:
                note["odor_profile"] = ""
                note["group_name"] = ""
                continue

            profile = cached.get(note_id)
            if profile is not None:
                _attach_profile(note, profile)
                continue

            if made_request and rate_limit_seconds > 0:
                sleep_fn(rate_limit_seconds)
            _fetch_and_cache(note, fetcher, parser)
            made_request = True

    return pyramid


def enrich_single_note(
    note_id: str,
    note_name: str = "",
    note_url: str = "",
    *,
    fetcher: Callable[[str], str] = fetch_page,
    parser: Callable[[str], str] = extract_note_odor_profile,
) -> dict:
    """Fetch and cache the odor profile *and* note group for a note.

    Used for lazy, per-note enrichment triggered by the UI on hover. The
    database cache table is consulted first; only on a miss (or when a
    legacy cached row lacks ``group_name``) is the note page fetched.

    Returns ``{"odor_profile": "...", "group_name": "..."}``.
    """
    empty = {"odor_profile": "", "group_name": ""}
    note_id = str(note_id or "")
    if not note_id:
        return empty

    cached = get_note_profile(note_id)
    if cached is not None:
        group_name = cached.get("group_name")
        if group_name is not None:
            return {
                "odor_profile": cached.get("odor_profile") or "",
                "group_name": group_name or "",
            }

    resolved_url = (note_url or "").strip() or _build_note_url(note_id, note_name or "")
    if not resolved_url:
        return empty

    try:
        html = fetcher(resolved_url)
        odor_profile = parser(html) or ""
        group_name = extract_note_group(html) or ""
    except Exception:
        return empty

    upsert_note_profile(
        note_id=note_id,
        note_name=note_name or "",
        note_url=resolved_url,
        odor_profile=odor_profile,
        group_name=group_name,
    )

    return {"odor_profile": odor_profile, "group_name": group_name}


def collect_unique_note_ids(pyramids: Iterable[dict]) -> list[str]:
    """Collect unique note_ids from a sequence of pyramid dicts."""
    seen: set[str] = set()
    result: list[str] = []
    for pyramid in pyramids or []:
        for note_id in _collect_note_ids(pyramid):
            if note_id not in seen:
                seen.add(note_id)
                result.append(note_id)
    return result


def missing_note_ids(pyramids: Iterable[dict]) -> list[str]:
    """Return note_ids that are not yet cached in the database."""
    pyramids = list(pyramids or [])
    all_ids = collect_unique_note_ids(pyramids)
    if not all_ids:
        return []
    cached = get_note_profiles(all_ids)
    return [note_id for note_id in all_ids if note_id not in cached]


def backfill_note_profiles(
    pyramids: Iterable[dict],
    *,
    fetcher: Callable[[str], str] = fetch_page,
    parser: Callable[[str], str] = extract_note_odor_profile,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Fetch and cache any missing note profiles for the given pyramids.

    Returns the number of note profiles newly inserted/updated. Notes
    already cached (and having an ``odor_profile``) are skipped. The
    backfill is no longer auto-invoked from the page-load path; it is
    exposed as a manual endpoint for users who want to pre-warm the
    cache for all of their stored perfumes.
    """
    pyramids = list(pyramids or [])
    all_ids = collect_unique_note_ids(pyramids)
    if not all_ids:
        return 0

    cached = get_note_profiles(all_ids)
    target_notes = []
    for pyramid in pyramids:
        for level in PYRAMID_LEVELS:
            for note in pyramid.get(level, []) or []:
                note_id = str(note.get("note_id") or "")
                if note_id and note_id not in cached:
                    target_notes.append(note)

    added = 0
    for index, note in enumerate(target_notes):
        if index and rate_limit_seconds > 0:
            sleep_fn(rate_limit_seconds)
        before = note.get("odor_profile", "__missing__")
        _fetch_and_cache(note, fetcher, parser)
        if note.get("odor_profile") and note.get("odor_profile") != before:
            added += 1

    return added
