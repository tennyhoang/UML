# UML validate-and-repair harness

Code that accompanies the paper *Improving the Reliability of LLM-Generated UML Class Diagrams Through
Automated Validation and Iterative Refinement*.

| file | purpose |
|---|---|
| `validator.py` | deterministic rule checker (G1-G10 generic rules, optional rule packs), pattern-agnostic feedback |
| `repair.py` | validate-and-repair loop (best-so-far, oscillation guard) and the LLM self-refine control |
| `metrics.py` | M1.1-M1.4 of the base study (F1, rubric score, Stability Index) and M2.x (agreement, loop metrics) |
| `llm.py` | client interface, OpenAI / Anthropic / Gemini adapters, `MockLLM` (tests only) |
| `run_experiments.py` | full factorial runner, resumable, JSONL output |
| `analyze.py` | tables and paired tests (paired Wilcoxon, Holm correction, Cliff's delta) |
| `tests/` | 10 unit tests (`python -m pytest tests`) |

## Before you run anything
1. Fill `config.example.json` -> `config.json`: paste the three prompt texts (standard, rule-injected, preference
   few-shot), the 3 paraphrases per domain, the model ids, and the reference models (`data/*.json`).
   The two example JSON files in `data/` are illustrations only, not the benchmark reference models.
2. Export `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.
3. `python run_experiments.py --config config.json --out results.jsonl`
4. `python analyze.py --config config.json --results results.jsonl`

`--dry-run` replaces every model by `MockLLM` to check the plumbing. Its output is **not data** and the
analysis script prints a warning when it sees dry-run records.

## Evaluation protocol (important)
* The validator rules are *in-loop*: conditions C3 and C4 optimise them. Report the violation score, but do not
  use it as evidence of design quality.
* Evidence of quality = F1 against the expert reference + the **manual** ternary rubric (PAS, PES), scored by raters
  who do not know the condition (blind the files by shuffling and stripping the condition).
* Log the exact model versions, dates and the random seeds / API parameters you used.
