"""Validate-and-repair loop with best-so-far tracking and oscillation guard."""
import json
import re
from validator import validate, score, errors

SYSTEM_REPAIR = (
    "You are a software design assistant. You will receive a UML class model as JSON and a numbered list of "
    "problems found by an automatic checker. Return the corrected model as one JSON object with exactly the "
    "same schema. Rules: fix every listed problem; change as little else as possible; do not delete elements "
    "that are correct; do not add commentary. Output JSON only.")


def extract_json(text):
    """Parse the first top-level JSON object in an LLM reply (handles ``` fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    
    # First pass: try to find properly closed JSON
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    pass  # Continue searching for valid JSON
    
    # Second pass: JSON not properly closed, try to recover
    json_candidate = text[start:]
    
    # Strategy 1: Add missing closing braces
    open_braces = json_candidate.count("{") - json_candidate.count("}")
    if open_braces > 0:
        fixed = json_candidate + "}" * open_braces
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
    
    # Strategy 2: Try to find the longest valid JSON prefix
    # Start from the end and work backwards
    for i in range(len(json_candidate) - 1, 0, -1):
        if json_candidate[i] == "}":
            try:
                return json.loads(json_candidate[:i+1])
            except json.JSONDecodeError:
                continue
    
    # Strategy 3: Aggressive recovery - remove incomplete trailing content
    # Look for last complete property and close there
    lines = json_candidate.split('\n')
    for num_lines in range(len(lines), 0, -1):
        partial = '\n'.join(lines[:num_lines])
        open_br = partial.count("{") - partial.count("}")
        if open_br > 0:
            attempt = partial + "}" * open_br
            try:
                result = json.loads(attempt)
                # Validate it has expected structure
                if isinstance(result, dict) and ("classes" in result or "relationships" in result):
                    return result
            except json.JSONDecodeError:
                continue
    
    raise ValueError("unterminated JSON")


def feedback_text(violations):
    return "\n".join(f"{i}. [{v.severity.upper()}] ({v.rule}) {v.where}: {v.message}" for i, v in enumerate(violations, 1))


def run_repair(llm, task, initial_model, packs=(), k_max=3, strict=False, temperature=0.5):
    """Iteratively repair `initial_model`. Returns a trace dict.

    converged  : no errors (and no warnings if strict) at some iteration <= k_max
    best_index : iteration with the lowest violation score (ties -> earliest)
    regressions: number of repair steps whose score got worse than the previous one
    Stops early when converged or when two consecutive repairs bring no improvement (oscillation guard)."""
    models, viols, scores_, tokens, regress, stale = [initial_model], [validate(initial_model, packs)], [], 0, 0, 0
    raw_replies = []  # Store raw LLM responses
    scores_.append(score(viols[0]))
    ok = lambda vs: not (vs if strict else errors(vs))
    it = 0
    while not ok(viols[-1]) and it < k_max:
        it += 1
        prompt = (f"Task description:\n{task}\n\nCurrent model:\n{json.dumps(models[-1], indent=1)}\n\n"
                  f"Problems found:\n{feedback_text(viols[-1])}\n\nReturn the corrected JSON model.")
        reply = llm.generate(SYSTEM_REPAIR, prompt, temperature)
        raw_replies.append(reply)  # Save raw reply
        tokens += getattr(llm, "last_tokens", 0)
        try:
            new = extract_json(reply)
        except (ValueError, json.JSONDecodeError, TypeError):
            new = models[-1]                       # unparsable reply counts as no change
        # A parseable reply with a broken schema is NOT discarded here: the validator reports it as G0_SCHEMA
        # (score >= 1000), so it is never selected as best and the next round is told what to fix.
        models.append(new)
        viols.append(validate(new, packs))
        scores_.append(score(viols[-1]))
        if scores_[-1] > scores_[-2]:
            regress += 1
        stale = stale + 1 if scores_[-1] >= min(scores_[:-1]) else 0
        if stale >= 2:
            break
    best = min(range(len(scores_)), key=lambda i: (scores_[i], i))
    return {"models": models, "violations": [[v.as_dict() for v in vs] for vs in viols], "violation_scores": scores_,
            "best_index": best, "best_model": models[best], "converged": ok(viols[best]), "iterations": it,
            "regressions": regress, "tokens": tokens, "raw_replies": raw_replies}


SYSTEM_SELF_REFINE = (
    "You are a software design assistant. Review the UML class model below against good object-oriented design "
    "(abstraction, encapsulation, separation of concerns) and return an improved model as one JSON object with "
    "exactly the same schema. Output JSON only.")


def run_self_refine(llm, task, initial_model, packs=(), k_max=3, temperature=0.5):
    """Control condition: the LLM reviews its own output WITHOUT any external checker feedback.
    The validator is only used afterwards, to log the violation score of each round."""
    models, tokens = [initial_model], 0
    raw_replies = []  # Store raw LLM responses
    for _ in range(k_max):
        reply = llm.generate(SYSTEM_SELF_REFINE, f"Task description:\n{task}\n\nCurrent model:\n{json.dumps(models[-1], indent=1)}", temperature)
        raw_replies.append(reply)  # Save raw reply
        tokens += getattr(llm, "last_tokens", 0)
        try:
            models.append(extract_json(reply))
        except (ValueError, json.JSONDecodeError, TypeError):
            models.append(models[-1])
    viols = [validate(m, packs) for m in models]
    sc = [score(v) for v in viols]
    regress = sum(1 for a, b in zip(sc, sc[1:]) if b > a)
    return {"models": models, "violations": [[v.as_dict() for v in vs] for vs in viols], "violation_scores": sc,
            "best_index": len(models) - 1, "best_model": models[-1], "converged": not errors(viols[-1]),
            "iterations": k_max, "regressions": regress, "tokens": tokens, "raw_replies": raw_replies}


def run_best_of_n(sample, initial_model, packs=(), n_extra=3):
    """Compute-matched control (C6): draw `n_extra` further INDEPENDENT samples with the same prompt as the
    initial diagram (no feedback) and keep the one with the lowest validator score (ties -> earliest).
    `sample()` must return (model_or_None, tokens, reply). A failed sample counts as "no new sample".
    Answers: is the repair loop better than simply sampling again and filtering with the same validator?"""
    models, tokens = [initial_model], 0
    raw_replies = []  # Save raw replies from samples
    for _ in range(n_extra):
        new, tok, reply = sample()
        tokens += tok
        raw_replies.append(reply if reply else "")
        models.append(new if isinstance(new, dict) else initial_model)
    viols = [validate(m, packs) for m in models]
    sc = [score(v) for v in viols]
    best = min(range(len(sc)), key=lambda i: (sc[i], i))
    return {"models": models, "violations": [[v.as_dict() for v in vs] for vs in viols], "violation_scores": sc,
            "best_index": best, "best_model": models[best], "converged": not errors(viols[best]),
            "iterations": n_extra, "regressions": 0, "tokens": tokens, "raw_replies": raw_replies}
