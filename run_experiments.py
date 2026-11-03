"""Run the full factorial experiment and write one JSON line per generation.

    python run_experiments.py --config config.json --out results.jsonl            # real run (needs API keys)
    python run_experiments.py --config config.example.json --out dry.jsonl --dry-run  # pipeline check with MockLLM

Design: domains x prompts x models x conditions x runs. Conditions that repair an existing diagram reuse the
initial diagram of their base condition (paired design); the initial-generation cost is counted once.  Resumable: finished (domain,prompt,model,condition,run)
keys are skipped.  Conditions:
  C0 standard | C1 rule | C2 preference            initial generation only (the base study)
  C3 pvr      = C2 + validate-and-repair             (proposed)
  C4 sv       = C0 + validate-and-repair             (ablation: loop without preference examples)
  C5 psr      = C2 + LLM self-refine, no checker     (ablation: loop without external validation)
"""
import argparse, json, os, sys
from llm import MockLLM, OpenAIClient, AnthropicClient, GeminiClient, RetryingLLM
from repair import extract_json, run_repair, run_self_refine
from validator import validate, score, check_notification_structure

PACKS = {"notification": check_notification_structure}
def make_client(m):
    """provider: openai | anthropic | gemini | openai_compat (Groq, OpenRouter, Ollama: give base_url + api_key_env)"""
    p, name = m["provider"], m["name"]
    if p == "openai":
        c = OpenAIClient(name)
    elif p == "openai_compat":
        c = OpenAIClient(name, base_url=m["base_url"], api_key_env=m["api_key_env"])
    elif p == "anthropic":
        c = AnthropicClient(name)
    elif p == "gemini":
        c = GeminiClient(name)
    else:
        raise ValueError(f"unknown provider {p}")
    return RetryingLLM(c, min_interval=m.get("min_interval", 0.0), retries=m.get("retries", 6))
BASE = {"C0": ("standard", None), "C1": ("rule", None), "C2": ("preference", None),
        "C3": ("preference", "pvr"), "C4": ("standard", "sv"), "C5": ("preference", "psr")}


def initial(llm, cfg, base, task, temperature):
    system = cfg["prompts"][base]["system"] + "\n\n" + cfg["json_instruction"]
    reply = llm.generate(system, task, temperature)
    return extract_json(reply), getattr(llm, "last_tokens", 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    done, cache = set(), {}          # cache: initial diagram per (domain,prompt,model,base,run) -> paired design
    if os.path.exists(a.out):
        for line in open(a.out):
            d = json.loads(line)
            if d.get("error"):
                continue                      # failed (e.g. quota) -> retried on the next run
            done.add((d["domain"], d["prompt"], d["model"], d["condition"], d["run"]))
            if d["trace"]:
                cache[(d["domain"], d["prompt"], d["model"], BASE[d["condition"]][0], d["run"])] = (d["trace"]["models"][0], 0)
    temp, k_max = cfg.get("temperature", 0.5), cfg.get("k_max", 3)
    clients = {n: (MockLLM(skill=0.8, seed=i) if a.dry_run else make_client(m))
               for i, (n, m) in enumerate(cfg["models"].items())}
    fails = 0
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
                            try:
                                ck = (dom, pid, mname, base, run)
                                if ck not in cache:      # C3/C5 reuse C2's diagram, C4 reuses C0's: paired comparison
                                    cache[ck] = (initial(llm, cfg, base, task, temp) if not a.dry_run
                                                 else (json.load(open(D["dry_seed"])), 0))
                                m0, tok = cache[ck]
                                if mode == "pvr" or mode == "sv":
                                    tr = run_repair(llm, task, m0, packs, k_max, temperature=temp)
                                elif mode == "psr":
                                    tr = run_self_refine(llm, task, m0, packs, k_max, temp)
                                else:
                                    v = validate(m0, packs); s = score(v)
                                    tr = {"models": [m0], "violations": [[x.as_dict() for x in v]], "violation_scores": [s],
                                          "best_index": 0, "best_model": m0, "converged": not any(x.severity == "error" for x in v),
                                          "iterations": 0, "regressions": 0, "tokens": 0}
                                tr["tokens"] += tok
                                rec = {"domain": dom, "prompt": pid, "model": mname, "condition": cond, "run": run,
                                       "dry_run": a.dry_run, "trace": tr, "error": None}
                            except Exception as e:          # keep going; failures are data too
                                rec = {"domain": dom, "prompt": pid, "model": mname, "condition": cond, "run": run,
                                       "dry_run": a.dry_run, "trace": None, "error": repr(e)}
                            out.write(json.dumps(rec) + "\n"); out.flush()
                            fails = fails + 1 if rec["error"] else 0
                            if fails >= 5:
                                sys.exit("5 consecutive failures (quota or key problem?). Progress is saved; "
                                         "fix the cause and run the same command again to resume.\nLast error: " + rec["error"])


if __name__ == "__main__":
    main()
