# Protocol notes

Deviations and decisions, in the order they matter for the reported results. The paper (Sec. 4.6, 6) is
the authoritative description.

## Material taken from the base study (arXiv:2604.00851, replication package)
- The six domain prompts (3 HMS, 3 Sensor) are verbatim copies of `HMS- Paraphrasing.docx` and
  `Sensor Network- Paraphrasing.docx`. Only the final output-format sentence ("Generate a UML class diagram in
  plantUML ... Only repond with plantuml nothing else") was removed, because output format is set by the JSON
  instruction. Consequence: outputs are JSON, not PlantUML, so absolute numbers are not directly comparable with
  the base study.
- Standard prompt (C0): empty system message.
- Rule-injected prompt (C1): `Instructions.txt` + `Good Design Practices.txt`, verbatim, except that the curly
  apostrophe in "isn’t" (U+2019, in Good Design Practices.txt) became a straight apostrophe.
- Preference prompt (C2): the five cross-domain pairs of `dataset.json`, preferred solution first according to
  the `choice` field. No benchmark solution and no pattern name appears in any prompt.

## Expert references (`data/`)
- `hms_reference.json`: from the PlantUML code in `Task Description-HMS.pdf`. The original misspelling
  `InPatitent` / `OutPatitent` was corrected to `InPatient` / `OutPatient`.
- `sensor_reference.json`: from the PlantUML code in `Design Task- WeatherReporting.pdf`. The source line
  `ReportingContext --o ReportingStrategy` puts the aggregation diamond at ReportingStrategy; the JSON makes
  ReportingContext the whole, deliberately reversing the source to match the intended structure.
- No alias table was used (`"aliases": {}`), so F1 is a literal (case-insensitive) name match.

## Runs
- Main pilot: `config_pilot.json` -> `pilot_cohere.jsonl`, 84 records, 0 failed. Model Cohere
  `command-a-03-2025`, temperature 0.5, K = 3, non-strict, max 4000 output tokens. One interrupted session was
  resumed with `--retry-errors` under the same config hash (see `.meta.json`).
- Second run: `config_pilot_strict.json` -> `pilot_cohere_strict.jsonl`, C3 and C4 only, 24 records, 0 failed.
  The config sets `"strict": true`, but `run_experiments.py` does not pass `strict` to `run_repair`; the run is
  therefore **non-strict** and is reported as such. Its initial diagrams were generated afresh (new output file),
  so it is not paired with the main pilot.

## Known data issues
- Record (HMS, P1, C0, run 0) in `pilot_cohere.jsonl` has no logged `model_id` and an empty `initial_reply`.
- One of 191 model replies in the main pilot was parsed only through the tolerant JSON recovery in
  `repair.extract_json`.
- Manual rubric scores (PAS, PES) have not been assigned yet.

## Results summary (details in the paper)
- Main pilot: initial diagrams had 1 rule error and 13 warnings in 36; the repair loop was never triggered.
  Self-refinement without a checker (C5) worsened the violation score in 10/12 records; validator-guided
  best-of-N (C6) reached zero violations in 12/12.
- Second run: the loop was triggered in 3/24 records (two G10 errors, one schema violation, all HMS); all
  three reached zero violations after one round, with F1 changing by -0.002 to -0.003.
