"""
PROBOARD — Asynchronous API Fetch Engines
==========================================
High-speed, rate-limited fetchers for LeetCode (GraphQL) and
HackerRank (REST) using ``aiohttp`` + ``asyncio.Semaphore``.

Key design decisions
--------------------
- **Handle deduplication** before any network I/O.
- **Exponential backoff** on 429 / 5xx responses.
- **Zero-crash policy**: every call is wrapped in broad exception
  handlers and returns structured zeros on failure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import pandas as pd

from config import MAX_RETRIES, REQUEST_TIMEOUT, SEMAPHORE_LIMIT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LeetCode — GraphQL query
# ---------------------------------------------------------------------------
_LC_GRAPHQL_URL = "https://leetcode.com/graphql"
_LC_QUERY = """
query getUserProfile($username: String!) {
  matchedUser(username: $username) {
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
}
"""

_LC_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
}


def _empty_lc() -> dict[str, int]:
    return {"lc_easy": 0, "lc_medium": 0, "lc_hard": 0, "lc_total": 0}


async def _fetch_leetcode(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    handle: str,
) -> dict[str, int]:
    """
    Fetch accepted-submission counts from LeetCode's GraphQL API.

    Returns ``{lc_easy, lc_medium, lc_hard, lc_total}``; zeros on
    any failure (private profile, timeout, rate limit exhaustion).
    """
    payload = {"query": _LC_QUERY, "variables": {"username": handle}}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with sem:
                async with session.post(
                    _LC_GRAPHQL_URL,
                    json=payload,
                    headers=_LC_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "LC %s — %d, backing off %ds (attempt %d/%d)",
                            handle, resp.status, wait, attempt, MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue

                    if resp.status != 200:
                        logger.warning("LC %s — HTTP %d", handle, resp.status)
                        return _empty_lc()

                    data = await resp.json()

            # Parse response
            matched = (data or {}).get("data", {}).get("matchedUser")
            if matched is None:
                logger.info("LC %s — profile not found / private.", handle)
                return _empty_lc()

            ac_list = matched["submitStats"]["acSubmissionNum"]
            result = _empty_lc()
            for entry in ac_list:
                diff = entry.get("difficulty", "").lower()
                count = int(entry.get("count", 0))
                if diff == "easy":
                    result["lc_easy"] = count
                elif diff == "medium":
                    result["lc_medium"] = count
                elif diff == "hard":
                    result["lc_hard"] = count
                elif diff == "all":
                    result["lc_total"] = count

            # Fallback: compute total if "All" wasn't returned
            if result["lc_total"] == 0:
                result["lc_total"] = (
                    result["lc_easy"] + result["lc_medium"] + result["lc_hard"]
                )
            return result

        except Exception as exc:
            logger.error("LC %s — attempt %d error: %s", handle, attempt, exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    return _empty_lc()


# ---------------------------------------------------------------------------
# HackerRank — REST endpoints
# ---------------------------------------------------------------------------
_HR_BADGES_URL = "https://www.hackerrank.com/rest/hackers/{handle}/badges"
_HR_SCORES_URL = "https://www.hackerrank.com/rest/hackers/{handle}/scores_elo"

_HR_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; PROBOARD/1.0)",
}


def _empty_hr() -> dict[str, Any]:
    return {"hr_badges": 0, "hr_score": 0.0}


async def _fetch_hackerrank(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    handle: str,
) -> dict[str, Any]:
    """
    Fetch badge count and aggregate score from HackerRank.

    Returns ``{hr_badges, hr_score}``; zeros on any failure.
    """
    result = _empty_hr()

    # --- Badges -----------------------------------------------------------
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with sem:
                async with session.get(
                    _HR_BADGES_URL.format(handle=handle),
                    headers=_HR_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if resp.status != 200:
                        break
                    data = await resp.json()

            badges = data.get("models", data if isinstance(data, list) else [])
            result["hr_badges"] = len(badges)
            break

        except Exception as exc:
            logger.error("HR badges %s — attempt %d: %s", handle, attempt, exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    # --- Score ------------------------------------------------------------
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with sem:
                async with session.get(
                    _HR_SCORES_URL.format(handle=handle),
                    headers=_HR_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if resp.status != 200:
                        break
                    data = await resp.json()

            # Sum all practice-area scores
            scores = data.get("models", data if isinstance(data, list) else [])
            total = 0.0
            for s in scores:
                total += float(s.get("score", s.get("practice", {}).get("score", 0)))
            result["hr_score"] = round(total, 2)
            break

        except Exception as exc:
            logger.error("HR score %s — attempt %d: %s", handle, attempt, exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    return result


# ---------------------------------------------------------------------------
# Orchestrator — deduplicate, fan-out, map back
# ---------------------------------------------------------------------------
async def _run_all(
    lc_handles: list[str],
    hr_handles: list[str],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """
    Fetch stats for deduplicated handle lists concurrently.

    Returns two dicts mapping ``handle → result_dict``.
    """
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async with aiohttp.ClientSession() as session:
        # Build tasks
        lc_tasks = {
            h: asyncio.ensure_future(_fetch_leetcode(session, sem, h))
            for h in lc_handles
        }
        hr_tasks = {
            h: asyncio.ensure_future(_fetch_hackerrank(session, sem, h))
            for h in hr_handles
        }

        # Await all
        if lc_tasks:
            await asyncio.gather(*lc_tasks.values())
        if hr_tasks:
            await asyncio.gather(*hr_tasks.values())

    lc_results = {h: t.result() for h, t in lc_tasks.items()}
    hr_results = {h: t.result() for h, t in hr_tasks.items()}
    return lc_results, hr_results


def fetch_all_stats(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Orchestrate async fetches for every student in the cleaned DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns ``roll_no``, ``lc_handle``, ``hr_handle``
        (as produced by ``cleaner.clean_dataframe``).

    Returns
    -------
    list[dict]
        One dict per student with keys:
        ``roll_no, lc_easy, lc_medium, lc_hard, lc_total,
        hr_badges, hr_score, total_score``
        Ready to feed into ``database.bulk_upsert_daily_stats``.
    """
    # --- Deduplicate handles ---------------------------------------------
    lc_unique = sorted(
        {h for h in df["lc_handle"].dropna().unique() if h}
    )
    hr_unique = sorted(
        {h for h in df["hr_handle"].dropna().unique() if h}
    )
    logger.info(
        "Fetching stats — %d unique LC handles, %d unique HR handles.",
        len(lc_unique), len(hr_unique),
    )

    # --- Run async event loop --------------------------------------------
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Inside Streamlit / Jupyter — use nest_asyncio-safe approach
        import nest_asyncio  # type: ignore[import-untyped]
        nest_asyncio.apply()
        lc_results, hr_results = loop.run_until_complete(
            _run_all(lc_unique, hr_unique)
        )
    else:
        lc_results, hr_results = asyncio.run(_run_all(lc_unique, hr_unique))

    # --- Map results back to each student --------------------------------
    output: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        roll_no = row["roll_no"]
        lc = lc_results.get(row.get("lc_handle"), _empty_lc())
        hr = hr_results.get(row.get("hr_handle"), _empty_hr())

        total = lc["lc_total"] + hr["hr_score"]

        output.append(
            {
                "roll_no": roll_no,
                "lc_easy": lc["lc_easy"],
                "lc_medium": lc["lc_medium"],
                "lc_hard": lc["lc_hard"],
                "lc_total": lc["lc_total"],
                "hr_badges": hr["hr_badges"],
                "hr_score": hr["hr_score"],
                "total_score": round(total, 2),
            }
        )

    logger.info("Fetch complete — %d student results assembled.", len(output))
    return output
