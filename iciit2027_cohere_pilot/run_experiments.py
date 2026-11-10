"""Run the full factorial experiment and write one JSON line per generation.

    python run_experiments.py --config config.json --out results.jsonl            # real run (needs API keys)
    python run_experiments.py --config config.example.json --out dry.jsonl --dry-run  # pipeline check with MockLLM
    python run_experiments.py --config config.json --out results.jsonl --retry-errors  # re-run records that failed

Design: domains x prompts x models x conditions x runs. Conditions that repair an existing diagram reuse the
initial diagram of their base condition (paired design). The cost (tokens) of a condition INCLUDES the
generation of its initial diagram, so conditions are directly comparable. Resumable: finished
(domain,prompt,model,condition,run) keys are skipped. If the initial diagram of a base condition could not be
generated, every condition that depends on it is recorded as failed (it never silently draws a different diagram).
Conditions:
  C0 standard | C1 rule | C2 preference            initial generation only (the base study)
  C3 pvr      = C2 + validate-and-repair             (proposed)
  C4 sv       = C0 + validate-and-repair             (ablation: loop without preference examples)
  C5 psr      = C2 + LLM self-refine, no checker     (ablation: loop without external validation)
  C6 bon      = C2 + k_max further independent samples, keep the best by validator score
                (OPTIONAL compute-matched control; add "C6" to "conditions" to enable it)
"""
import argparse, datetime, hashlib, json, os, platform, sys
from llm import MockLLM, OpenAIClient, AnthropicClient, GeminiClient, GroqClient, CohereClient, RetryingLLM
from repair import extract_json, run_repair, run_self_refine, run_best_of_n
from validator import validate, score, check_notification_structure

PACKS = {"notification": check_notification_structure}
FACTORY = {"openai": OpenAIClient, "anthropic": AnthropicClient, "gemini": GeminiClient, "groq": GroqClient, "cohere": CohereClient}
BASE = {"C0": ("standard", None), "C1": ("rule", None), "C2": ("preference", None),
        "C3": ("preference", "pvr"), "C4": ("standard", "sv"), "C5": ("preference", "psr"),
        "C6": ("preference", "bon")}


def initial(llm, cfg, base, task, temperature):
    system = cfg["prompts"][base]["system"] + "\n\n" + cfg["json_instruction"]
    reply = llm.generate(system, task, temperature)
    return extract_json(reply), getattr(llm, "last_tokens", 0), reply  # Return reply text too


def write_meta(path, cfg, cfg_bytes, argv, allow_change):
    """Append one run-metadata entry; refuse to resume with a different config (prompts/models would mix)."""
    digest = hashlib.sha256(cfg_bytes).hexdigest()
    entries = json.load(open(path)) if os.path.exists(path) else []
    if entries and entries[-1]["config_sha256"] != digest and not allow_change:
        sys.exit(f"ERROR: the config changed since the last run that wrote {path}. Mixing prompts or models in one "
                 "results file invalidates the comparison. Use a new --out file, or pass --allow-config-change.")
    entries.append({"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                    "argv": argv, "python": platform.python_version(), "config_sha256": digest,
                    "temperature": cfg.get("temperature", 0.5), "k_max": cfg.get("k_max", 3), "runs": cfg["runs"],
                    "conditions": cfg["conditions"], "models": cfg["models"]})
    json.dump(entries, open(path, "w"), indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry-errors", action="store_true", help="re-run records that previously failed")
    ap.add_argument("--allow-config-change", action="store_true")
    a = ap.parse_args(argv)
    cfg_bytes = open(a.config, "rb").read(); cfg = json.loads(cfg_bytes)
    unknown = [c for c in cfg["conditions"] if c not in BASE]
    if unknown:
        sys.exit(f"ERROR: unknown conditions {unknown}; known: {sorted(BASE)}")
    write_meta(a.out + ".meta.json", cfg, cfg_bytes, sys.argv[1:] if argv is None else list(argv), a.allow_config_change)
    done, cache = set(), {}          # cache: initial diagram per (domain,prompt,model,base,run) -> paired design
    if os.path.exists(a.out):
        for line in open(a.out):
            d = json.loads(line)
            if d["trace"] is None and a.retry_errors:
                continue
            done.add((d["domain"], d["prompt"], d["model"], d["condition"], d["run"]))
            if d["trace"]:
                cache[(d["domain"], d["prompt"], d["model"], BASE[d["condition"]][0], d["run"])] = {
                    "model": d["trace"]["models"][0], "tokens": d.get("initial_tokens", 0), "error": None}
    temp, k_max = cfg.get("temperature", 0.5), cfg.get("k_max", 3)
    retry = cfg.get("retry", {})            # {"tries": 4, "base_delay": 2.0}: transient API errors are retried
    clients = {n: (MockLLM(skill=0.8, seed=i) if a.dry_run else
                   RetryingLLM(FACTORY[m["provider"]](m["name"]), tries=retry.get("tries", 4), base_delay=retry.get("base_delay", 2.0)))
               for i, (n, m) in enumerate(cfg["models"].items())}

    def get_initial(ck, llm, D, base, task):
        if ck not in cache:
            try:
                if a.dry_run:
                    m0, tok, initial_reply = json.load(open(D["dry_seed"])), 0, ""
                else:
                    m0, tok, initial_reply = initial(llm, cfg, base, task, temp)
                cache[ck] = {"model": m0, "tokens": tok, "error": None, "initial_reply": initial_reply}
            except Exception as e:                       # remembered, so dependent conditions do not redraw
                cache[ck] = {"model": None, "tokens": 0, "error": "initial generation failed: " + repr(e), "initial_reply": ""}
        return cache[ck]

    with open(a.out, "a") as out:
        for dom, D in cfg["domains"].items():
            packs = [PACKS[p] for p in D.get("packs", [])]
            for pid, task in D["prompts"].items():
                for mname, llm in clients.items():
                    for cond in cfg["conditions"]:
                        base, mode = BASE[cond]
                        for run in range(cfg["runs"]):
                            key = (dom, pid, mname, cond, run)
                            if key in done:
                                continue
                            rec = {"domain": dom, "prompt": pid, "model": mname, "condition": cond, "run": run,
                                   "dry_run": a.dry_run, "trace": None, "error": None, "initial_tokens": 0, "model_id": None, "initial_reply": ""}
                            try:
                                ini = get_initial((dom, pid, mname, base, run), llm, D, base, task)
                                if ini["error"]:
                                    raise RuntimeError(ini["error"])
                                m0, tok, initial_reply = ini["model"], ini["tokens"], ini.get("initial_reply", "")
                                if mode in ("pvr", "sv"):
                                    tr = run_repair(llm, task, m0, packs, k_max, temperature=temp)
                                elif mode == "psr":
                                    tr = run_self_refine(llm, task, m0, packs, k_max, temp)
                                elif mode == "bon":
                                    def sample():
                                        try:
                                            if a.dry_run:
                                                return json.load(open(D["dry_seed"])), 0, ""
                                            else:
                                                return initial(llm, cfg, base, task, temp)
                                        except Exception:
                                            return None, 0, ""
                                    tr = run_best_of_n(sample, m0, packs, k_max)
                                else:
                                    v = validate(m0, packs)
                                    tr = {"models": [m0], "violations": [[x.as_dict() for x in v]], "violation_scores": [score(v)],
                                          "best_index": 0, "best_model": m0, "converged": not any(x.severity == "error" for x in v),
                                          "iterations": 0, "regressions": 0, "tokens": 0, "raw_replies": [initial_reply]}  # Include initial reply
                                tr["tokens"] += tok
                                rec.update(trace=tr, initial_tokens=tok, model_id=getattr(llm, "last_model", None), initial_reply=initial_reply)
                            except Exception as e:          # keep going; failures are reported by analyze.py
                                rec["error"] = repr(e)
                            out.write(json.dumps(rec) + "\n"); out.flush()


if __name__ == "__main__":
    main()
