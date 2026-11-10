"""Summarise a results file: per (domain, model, condition) means, SI, convergence, failures, plus paired tests.

    python analyze.py --config config.json --results results.jsonl
Principle adherence (PAS) and pattern emergence (PES) are RUBRIC scores assigned by human raters and are
not computed here. The validator violation score is an IN-LOOP metric: conditions C3/C4/C6 optimise it directly,
so it must not be used as the evidence for design quality (use F1 against the reference and the manual rubric).

Failed runs (record with "trace": null) are EXCLUDED from every mean and test, and counted in the `fail` column.
If failures are unevenly spread over models or conditions, the comparison is biased: report and investigate them.
If a record key appears twice (e.g. after --retry-errors) the last one wins."""
import argparse, json, math, os, sys
from collections import defaultdict
from statistics import mean
import metrics as M

PAIRS = [("C2", "C3"), ("C0", "C4"), ("C5", "C3"), ("C2", "C6"), ("C6", "C3")]


def holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i]); out = [0] * len(pvals); prev = 0
    for rank, i in enumerate(order):
        prev = max(prev, min(1.0, (len(pvals) - rank) * pvals[i])); out[i] = prev
    return out


def load_records(path):
    """Read JSONL; keep the last record per (domain, prompt, model, condition, run)."""
    last = {}
    for line in open(path):
        if line.strip():
            r = json.loads(line)
            last[(r["domain"], r["prompt"], r["model"], r["condition"], r["run"])] = r
    return list(last.values())


def load_references(cfg, recs):
    """Return {domain: reference model}. A missing reference file is a hard error for real data (it used to give
    F1 = 0 silently); for dry-run data it is only a warning and F1 is reported as nan."""
    refs = {}
    for d, D in cfg["domains"].items():
        path = D.get("reference", "")
        if path and os.path.exists(path):
            refs[d] = json.load(open(path))
            continue
        real = any(r["domain"] == d and not r["dry_run"] for r in recs)
        msg = f"reference model for domain '{d}' not found: {path!r}"
        if real:
            sys.exit("ERROR: " + msg + ". Provide the expert reference model before analysing real results.")
        print("WARNING: " + msg + " (dry-run data) -> F1 shown as nan\n")
    return refs


def fmt(x, nd=3):
    return "nan" if isinstance(x, float) and math.isnan(x) else f"{x:.{nd}f}"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--config", required=True); ap.add_argument("--results", required=True)
    a = ap.parse_args(argv); cfg = json.load(open(a.config))
    recs = load_records(a.results)
    if any(r["dry_run"] for r in recs):
        print("!!! DRY RUN (MockLLM): these numbers are NOT experimental data !!!\n")
    refs = load_references(cfg, recs)
    aliases = {d: D.get("aliases") for d, D in cfg["domains"].items()}
    f1_of = lambda r: M.structural_correctness(r["trace"]["best_model"], refs[r["domain"]], aliases[r["domain"]])["all"][2]

    ok, bad = defaultdict(list), defaultdict(int)
    for r in recs:
        k = (r["domain"], r["model"], r["condition"])
        if r["trace"]:
            ok[k].append(r)
        else:
            bad[k] += 1
    print("domain  model  cond | n  fail  F1  initVC  finalVC  conv  iters  regress  SI(F1)  agree  tokens")
    for k in sorted(set(ok) | set(bad)):
        d, m, c = k
        rs = ok.get(k, [])
        expected = len(cfg["domains"][d]["prompts"]) * cfg["runs"]
        flag = "  <-- INCOMPLETE" if len(rs) + bad.get(k, 0) < expected else ""
        if not rs:
            print(f"{d} {m} {c} | 0 {bad[k]}  (no successful run){flag}")
            continue
        f1 = [f1_of(r) for r in rs] if d in refs else [float("nan")] * len(rs)
        lm = [M.loop_metrics(r["trace"]) for r in rs]
        by = defaultdict(list)
        for r, f in zip(rs, f1):
            by[r["prompt"]].append(f)
        si = M.stability_index(by) if d in refs else float("nan")
        ag = M.structural_agreement([r["trace"]["best_model"] for r in rs])
        print(f"{d} {m} {c} | {len(rs)} {bad.get(k, 0)} {fmt(mean(f1))} {mean(x['initial_violation_score'] for x in lm):.2f} "
              f"{mean(x['final_violation_score'] for x in lm):.2f} {mean(x['converged'] for x in lm):.2f} "
              f"{mean(x['iterations_used'] for x in lm):.2f} {mean(x['regressions'] for x in lm):.2f} {fmt(si)} {ag:.3f} "
              f"{mean(x['tokens'] for x in lm):.0f}{flag}")
    if sum(bad.values()):
        print(f"\nNOTE: {sum(bad.values())} failed run(s) excluded; see the `fail` column and the 'error' field of the records.")
    try:
        from scipy.stats import wilcoxon
    except ImportError:
        print("\n(scipy not installed: paired tests skipped)")
        return
    keyed = defaultdict(dict)
    for r in recs:
        if r["trace"] and r["domain"] in refs:
            keyed[(r["domain"], r["model"], r["condition"])][(r["prompt"], r["run"])] = f1_of(r)
    rows = []
    for d in cfg["domains"]:
        for m in cfg["models"]:
            for x, y in PAIRS:
                KA, KB = keyed.get((d, m, x), {}), keyed.get((d, m, y), {})
                common = sorted(set(KA) & set(KB))
                if common:
                    A, B = [KA[k] for k in common], [KB[k] for k in common]
                    try:
                        p = wilcoxon(B, A).pvalue
                    except ValueError:                   # all differences are zero
                        p = 1.0
                    rows.append((d, m, x, y, M.cliffs_delta(B, A), p, len(common)))
    adj = holm([r[5] for r in rows])
    print("\nF1: second vs first condition (paired Wilcoxon, Holm-adjusted p, Cliff's delta, n = pairs)")
    for r, p in zip(rows, adj):
        print(f"{r[0]} {r[1]} {r[2]}->{r[3]}: delta={r[4]:+.2f} p_holm={p:.4f} n={r[6]}")


if __name__ == "__main__":
    main()
