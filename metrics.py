"""Metrics M1.1-M1.4 (as in the base study) and M2.x (new, loop-specific)."""
from itertools import combinations
from statistics import mean, pvariance


def element_sets(m):
    cls = {c["name"].strip().lower() for c in m.get("classes", [])}
    attrs = {(c["name"].strip().lower(), a["name"].strip().lower()) for c in m.get("classes", []) for a in c.get("attributes", [])}
    rels = {(r["type"], r["source"].strip().lower(), r["target"].strip().lower()) for r in m.get("relationships", [])}
    return {"classes": cls, "attributes": attrs, "relationships": rels}


def prf(pred, ref):
    tp = len(pred & ref)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(ref) if ref else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def structural_correctness(model, reference):
    """M1.1 - precision / recall / F1 per element category and over all elements."""
    a, b = element_sets(model), element_sets(reference)
    out = {k: prf(a[k], b[k]) for k in a}
    tag = lambda S: {(k, x) for k, v in S.items() for x in v}
    out["all"] = prf(tag(a), tag(b))
    return out


def rubric_score(marks):
    """M1.2 / M1.3 - ternary marks (0, 0.5, 1) averaged. Marks are assigned by human raters."""
    assert all(x in (0, 0.5, 1) for x in marks)
    return sum(marks) / len(marks) if marks else 0.0


def stability_index(scores):
    """M1.4 - SI = 1 / (1 + var_prompt + var_run).

    `scores[prompt] = [s_run1, s_run2, ...]` for one (model, condition, domain).
    var_run    = mean over prompts of the variance across runs
    var_prompt = variance across prompts of the per-prompt mean
    (our operationalisation; the base study does not spell out the aggregation)."""
    prompts = list(scores)
    var_run = mean(pvariance(v) if len(v) > 1 else 0.0 for v in scores.values())
    var_prompt = pvariance([mean(v) for v in scores.values()]) if len(prompts) > 1 else 0.0
    return 1.0 / (1.0 + var_prompt + var_run)


def structural_agreement(models):
    """M2.1 - mean pairwise Jaccard of element sets over a group of generated models.
    Captures the 'semantic consistency is not structural consistency' effect."""
    sets = [{(k, x) for k, v in element_sets(m).items() for x in v} for m in models]
    pairs = list(combinations(sets, 2))
    if not pairs:
        return 1.0
    return mean(len(a & b) / len(a | b) if a | b else 1.0 for a, b in pairs)


def loop_metrics(trace):
    """M2.2-M2.5 from a RepairTrace-like dict."""
    first, last = trace["violation_scores"][0], trace["violation_scores"][trace["best_index"]]
    return {
        "initial_violation_score": first,
        "final_violation_score": last,
        "converged": int(trace["converged"]),
        "iterations_used": trace["iterations"],
        "regressions": trace["regressions"],
        "tokens": trace.get("tokens", 0),
    }


def cliffs_delta(a, b):
    """Effect size for two samples (a vs b); positive means a tends to be larger."""
    if not a or not b:
        return 0.0
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))
