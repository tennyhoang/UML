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
| `tests/` | 11 unit tests (`python -m pytest tests`) |

## Before you run anything
1. Fill `config.example.json` -> `config.json`: paste the three prompt texts (standard, rule-injected, preference
   few-shot), the 3 paraphrases per domain, the model ids, and the reference models (`data/*.json`).
   The two example JSON files in `data/` are illustrations only, not the benchmark reference models.
2. Export `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.
3. `python run_experiments.py --config config.json --out results.jsonl`
4. `python analyze.py --config config.json --results results.jsonl`

`--dry-run` replaces every model by `MockLLM` to check the plumbing. Its output is **not data** and the
analysis script prints a warning when it sees dry-run records.

## Free quick start (Gemini + Groq, no payment)
1. Get two free keys: Gemini at https://aistudio.google.com/apikey and Groq at https://console.groq.com/keys.
2. `pip install openai google-genai scipy`
3. Set the keys (Windows PowerShell):
   `$env:GEMINI_API_KEY="..."` and `$env:GROQ_API_KEY="..."`  (Linux/macOS: `export GEMINI_API_KEY=...`)
4. Check keys and model names (one tiny call per model): `python check_setup.py --config config.free.json`
   If a model name fails, look up the current name in the provider's console and edit `config.free.json`.
5. Run: `python run_experiments.py --config config.free.json --out results.jsonl`
   Free tiers have daily limits. When a limit is hit, the runner stops after 5 consecutive failures; **run the same
   command again the next day** and it resumes (failed items are retried, finished items are skipped).
   To make it smaller, lower `"runs"` in the config (e.g. 5) and say so in the paper.
6. `python analyze.py --config config.free.json --results results.jsonl`

`make_inputs.py` regenerates `config.free.json`, `data/hms_reference.json`, `data/sensor_reference.json` and `prompts/`.
The prompts, the paraphrases and the two reference models were written for this project from Table I of the base paper;
they are not the original authors' files. Say this in the paper and have an expert review the reference models.
The models used here are not the base study's models; report the exact model names and dates you actually ran.

## Evaluation protocol (important)
* The validator rules are *in-loop*: conditions C3 and C4 optimise them. Report the violation score, but do not
  use it as evidence of design quality.
* Evidence of quality = F1 against the expert reference + the **manual** ternary rubric (PAS, PES), scored by raters
  who do not know the condition (blind the files by shuffling and stripping the condition).
* Log the exact model versions, dates and the random seeds / API parameters you used.
