"""Summarise a results file: per (domain, model, condition) means, SI, convergence, plus paired tests.

    python analyze.py --config config.json --results results.jsonl
Principle adherence (PAS) and pattern emergence (PES) are RUBRIC scores assigned by human raters and are
not computed here. The validator violation score is an IN-LOOP metric: conditions C3/C4 optimise it directly,
so it must not be used as the evidence for design quality (use F1 against the reference and the manual rubric)."""
import argparse, json
from collections import defaultdict
from statistics import mean
import metrics as M


def holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i]); out = [0] * len(pvals); prev = 0
    for rank, i in enumerate(order):
        prev = max(prev, min(1.0, (len(pvals) - rank) * pvals[i])); out[i] = prev
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", required=True); ap.add_argument("--results", required=True)
    a = ap.parse_args(); cfg = json.load(open(a.config))
    recs = [json.loads(l) for l in open(a.results)]
    if any(r["dry_run"] for r in recs):
        print("!!! DRY RUN (MockLLM): these numbers are NOT experimental data !!!\n")
    refs = {d: json.load(open(D["reference"])) for d, D in cfg["domains"].items() if __import__("os").path.exists(D["reference"])}
    g = defaultdict(list)
    for r in recs:
        if r["trace"]:
            g[(r["domain"], r["model"], r["condition"])].append(r)
    print("domain  model  cond | n  F1  initVC  finalVC  conv  iters  regress  SI(F1)  agree")
    f1s = {}
    for (d, m, c), rs in sorted(g.items()):
        f1 = [M.structural_correctness(r["trace"]["best_model"], refs[d])["all"][2] for r in rs] if d in refs else [0] * len(rs)
        f1s[(d, m, c)] = f1
        lm = [M.loop_metrics(r["trace"]) for r in rs]
        by = defaultdict(lambda: defaultdict(list))
        for r, f in zip(rs, f1): by[r["prompt"]][0].append(f)
        si = M.stability_index({p: v[0] for p, v in by.items()})
        ag = M.structural_agreement([r["trace"]["best_model"] for r in rs])
        print(f"{d} {m} {c} | {len(rs)} {mean(f1):.3f} {mean(x['initial_violation_score'] for x in lm):.2f} "
              f"{mean(x['final_violation_score'] for x in lm):.2f} {mean(x['converged'] for x in lm):.2f} "
              f"{mean(x['iterations_used'] for x in lm):.2f} {mean(x['regressions'] for x in lm):.2f} {si:.3f} {ag:.3f}")
    try:
        from scipy.stats import wilcoxon
    except ImportError:
        return
    keyed = defaultdict(dict)
    for r in recs:
        if r["trace"] and r["domain"] in refs:
            keyed[(r["domain"], r["model"], r["condition"])][(r["prompt"], r["run"])] = M.structural_correctness(
                r["trace"]["best_model"], refs[r["domain"]])["all"][2]
    pairs = [("C2", "C3"), ("C0", "C4"), ("C5", "C3")]
    rows = []
    for d in cfg["domains"]:
        for m in cfg["models"]:
            for x, y in pairs:
                KA, KB = keyed.get((d, m, x), {}), keyed.get((d, m, y), {})
                common = sorted(set(KA) & set(KB))
                if common:
                    A, B = [KA[k] for k in common], [KB[k] for k in common]
                    try:
                        p = wilcoxon(B, A).pvalue
                    except ValueError:                   # all differences are zero
                        p = 1.0
                    rows.append((d, m, x, y, M.cliffs_delta(B, A), p))
    adj = holm([r[5] for r in rows])
    print("\nF1: second vs first condition (paired Wilcoxon, Holm-adjusted p, Cliff's delta)")
    for r, p in zip(rows, adj):
        print(f"{r[0]} {r[1]} {r[2]}->{r[3]}: delta={r[4]:+.2f} p_holm={p:.4f}")


if __name__ == "__main__":
    main()
