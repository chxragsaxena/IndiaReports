"""How good is the text triage? Sends the hand-labelled reports to the real model and compares its answers with the labels.

    docker compose run --rm --no-deps -v "$PWD/services/ai/eval:/app/eval" -e PYTHONPATH=/app --entrypoint python ai-service -m eval.triage_eval

Needs a model (GROQ_API_KEY). It uses your daily request allowance: about one request per case.
"""

import asyncio
import sys

from app.analysis.analyzer import AnalysisError
from app.analysis.triage import TextContext, build_triager

from eval.triage_cases import CASES

LEVELS = ["low", "medium", "high", "critical"]


async def main() -> None:
    triager = build_triager()
    if triager is None or triager.provider == "mock":
        print("No real model is configured (set GROQ_API_KEY).")
        sys.exit(1)
    print(f"model: {triager.provider}/{triager.model}, {len(CASES)} cases\n")

    rows, failed = [], []
    for cid, title, description, category, language, urgency, spam, best in CASES:
        try:
            r = await triager.triage(TextContext(title, description, category))
        except AnalysisError as e:
            failed.append((cid, str(e)[:100]))
            continue
        rows.append((cid, language, urgency, spam, best, r))
        print(f"  {cid}  urgency {r.urgency:<8} spam {str(r.is_spam):<5} lang {r.language:<10} category {r.suggested_category}")

    scored = [x for x in rows if x[2] is not None]  # spam has no expected urgency
    exact = sum(1 for _, _, u, _, _, r in scored if r.urgency == u)
    within_one = sum(1 for _, _, u, _, _, r in scored if abs(LEVELS.index(r.urgency) - LEVELS.index(u)) <= 1)
    critical = [x for x in scored if x[2] == "critical"]
    critical_seen = sum(1 for *_, r in critical if r.urgency in ("high", "critical"))
    critical_exact = sum(1 for *_, r in critical if r.urgency == "critical")

    spam_true = [x for x in rows if x[3]]
    spam_found = sum(1 for *_, r in spam_true if r.is_spam)
    real = [x for x in rows if not x[3]]
    false_spam = [x for x in real if x[5].is_spam]
    flagged = spam_found + len(false_spam)

    lang = [x for x in rows if x[1] is not None]
    lang_ok = sum(1 for _, expected, *_, r in lang if r.language.lower().startswith(expected.lower()[:5]))
    category_ok = sum(1 for *_, best, r in [(x[0], x[1], x[2], x[3], x[4], x[5]) for x in rows if not x[3]] if r.suggested_category == best)

    print(f"\nanswered {len(rows)} of {len(CASES)} ({len(failed)} failed: {failed})\n")
    print(f"urgency exactly right        {exact}/{len(scored)}  ({exact / len(scored):.0%})")
    print(f"urgency within one level     {within_one}/{len(scored)}  ({within_one / len(scored):.0%})")
    print(f"critical cases rated high or critical   {critical_seen}/{len(critical)}   (exactly critical: {critical_exact}/{len(critical)})")
    print(f"spam found                   {spam_found}/{len(spam_true)}   recall {spam_found / max(1, len(spam_true)):.0%}")
    print(f"real reports wrongly called spam   {len(false_spam)}/{len(real)}   precision {spam_found / max(1, flagged):.0%}")
    print(f"language identified          {lang_ok}/{len(lang)}  ({lang_ok / max(1, len(lang)):.0%})")
    print(f"best category suggested      {category_ok}/{len(real)}  ({category_ok / max(1, len(real)):.0%})")

    print("\nmistakes:")
    for cid, expected_lang, urgency, spam, best, r in rows:
        problems = []
        if urgency is not None and r.urgency != urgency:
            problems.append(f"urgency {r.urgency} (label {urgency})")
        if spam != r.is_spam:
            problems.append(f"spam {r.is_spam} (label {spam})")
        if expected_lang is not None and not r.language.lower().startswith(expected_lang.lower()[:5]):
            problems.append(f"language {r.language} (label {expected_lang})")
        if not spam and r.suggested_category != best:
            problems.append(f"category {r.suggested_category} (label {best})")
        if problems:
            print(f"  {cid}: " + "; ".join(problems))


if __name__ == "__main__":
    asyncio.run(main())
