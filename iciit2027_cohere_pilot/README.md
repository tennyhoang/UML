# UML validate-and-repair harness

Code and data accompanying the paper *Improving the Reliability of LLM-Generated UML Class Diagrams
Through Automated Validation and Iterative Refinement*.

| File | Purpose |
|---|---|
| `validator.py` | Deterministic rule checker: G0 (schema), G1-G10, optional pack P1; pattern-agnostic feedback |
| `repair.py` | Validate-and-repair loop (C3/C4), LLM self-refine control (C5), best-of-N control (C6) |
| `metrics.py` | M1.1 F1, M1.2/M1.3 rubric score, M1.4 Stability Index, M2.x loop metrics |
| `llm.py` | Client interface and adapters (Cohere, OpenAI, Anthropic, Gemini); `MockLLM` for tests only |
| `run_experiments.py` | Resumable factorial runner; JSONL output + `<out>.meta.json` run log |
| `analyze.py` | Tables and paired tests (Wilcoxon, Holm, Cliff's delta) |
| `verify_protocol.py` | Checks a config: verbatim prompts, no pattern names, real references, valid model id |
| `convert_plantuml_to_json.py` | PlantUML -> JSON helper (not used for the reported references) |
| `tests/` | 22 unit tests: `python -m pytest tests` |
| `data/` | Expert references (`hms_reference.json`, `sensor_reference.json`); `*_example.json` files are test fixtures only |

## Data reported in the paper

| File | Content |
|---|---|
| `config_pilot.json` | Main pilot configuration (C0-C6, 2 runs, Cohere `command-a-03-2025`, T = 0.5, K = 3) |
| `pilot_cohere.jsonl` (+ `.meta.json`) | Main pilot: 84 records, 0 failed (5-6 Nov 2026 UTC) |
| `config_pilot_strict.json` | Second run of C3/C4 only. Contains `"strict": true`, but the runner does **not** pass this flag to the loop, so the run is non-strict (see paper, Sec. 4.6) |
| `pilot_cohere_strict.jsonl` (+ `.meta.json`) | Second run: 24 records, 0 failed (6 Nov 2026 UTC) |

Every record stores the raw model replies (`initial_reply`, `trace.raw_replies`), the model id and the full trace.

## Reproduce

```powershell
pip install cohere scipy pytest
python -m pytest tests
python verify_protocol.py config_pilot.json
$env:COHERE_API_KEY="..."          # never write the key into a file
python run_experiments.py --config config_pilot.json --out my_run.jsonl
python analyze.py --config config_pilot.json --results my_run.jsonl
```

`verify_protocol.py config_pilot_strict.json` reports missing conditions; this is expected because the second run
contains only C3 and C4.

`--dry-run` replaces the model by `MockLLM` to test the pipeline; its output is never data.
