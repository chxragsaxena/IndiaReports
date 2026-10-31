"""How good is the duplicate check? Runs the server's own rule over the hand-labelled cases and prints precision,
recall and the mistakes, then shows what other settings would have done.

    docker compose run --rm --no-deps -v "$PWD/backend/eval:/app/eval" -e PYTHONPATH=/app --entrypoint python report-service -m eval.duplicates_eval

This needs no database and no model: the duplicate check is distance plus word overlap, not AI.
"""

from app.services.similarity import MIN_TEXT_MATCH, RADIUS_M, SAME_SPOT_M, is_duplicate, text_match, words

from eval.duplicate_cases import CASES


def score(case) -> float:
    _, nt, nd, ot, od, *_ = case
    return text_match(words(nt, nd), words(ot, od))


def confusion(**settings):
    tp = fp = fn = tn = 0
    wrong = []
    for case in CASES:
        metres, label = case[5], case[6]
        predicted = is_duplicate(metres, score(case), **settings)
        if predicted and label:
            tp += 1
        elif predicted and not label:
            fp += 1
            wrong.append(("FALSE POSITIVE", case))
        elif label:
            fn += 1
            wrong.append(("MISSED", case))
        else:
            tn += 1
    return tp, fp, fn, tn, wrong


def rates(tp, fp, fn, tn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def main() -> None:
    positives = sum(1 for c in CASES if c[6])
    print(f"{len(CASES)} labelled pairs: {positives} the same problem, {len(CASES) - positives} different\n")

    tp, fp, fn, tn, wrong = confusion()
    precision, recall, f1 = rates(tp, fp, fn, tn)
    print(f"Server settings (radius {RADIUS_M} m, same spot {SAME_SPOT_M} m, word overlap {MIN_TEXT_MATCH}):")
    print(f"  precision {precision:.2f}   recall {recall:.2f}   F1 {f1:.2f}   (TP {tp}, FP {fp}, FN {fn}, TN {tn})\n")

    print("Mistakes:")
    for kind, case in wrong:
        print(f"  {kind:14} {case[0]}  {case[5]:>4} m  overlap {score(case):.2f}  - {case[7]}")

    print("\nWhat other word-overlap thresholds would do (distance rules unchanged):")
    print("  threshold  precision  recall    F1")
    for t in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        p, r, f = rates(*confusion(min_text=t)[:4])
        print(f"  {t:>8}  {p:>9.2f}  {r:>6.2f}  {f:>4.2f}" + ("   <- server" if t == MIN_TEXT_MATCH else ""))

    print("\nWhat other same-spot distances would do (word threshold unchanged):")
    print("  metres   precision  recall    F1")
    for m in (0, 10, 20, 30, 50):
        p, r, f = rates(*confusion(same_spot=m)[:4])
        print(f"  {m:>6}  {p:>9.2f}  {r:>6.2f}  {f:>4.2f}" + ("   <- server" if m == SAME_SPOT_M else ""))


def shared_words(case) -> int:
    _, nt, nd, ot, od, *_ = case
    return len(words(nt, nd) & words(ot, od))


def sweep_minimum_shared() -> None:
    """Does asking for at least N words in common (as well as the overlap share) help? Measured here only."""
    print("\nRequiring a minimum number of shared words (on top of the overlap share):")
    print("  shared  precision  recall    F1")
    for n in (1, 2, 3):
        tp = fp = fn = tn = 0
        for case in CASES:
            metres, label = case[5], case[6]
            predicted = metres <= RADIUS_M and (metres <= SAME_SPOT_M or (score(case) >= MIN_TEXT_MATCH and shared_words(case) >= n))
            tp, fp, fn, tn = tp + (predicted and label), fp + (predicted and not label), fn + (not predicted and label), tn + (not predicted and not label)
        p, r, f = rates(tp, fp, fn, tn)
        print(f"  {n:>6}  {p:>9.2f}  {r:>6.2f}  {f:>4.2f}   (FP {fp}, FN {fn})")


if __name__ == "__main__":
    main()
    sweep_minimum_shared()
