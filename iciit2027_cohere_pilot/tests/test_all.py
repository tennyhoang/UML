import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validator import validate, errors, score, check_notification_structure
from repair import run_repair, run_self_refine, extract_json
from llm import MockLLM
import metrics as M

D = os.path.join(os.path.dirname(__file__), "..", "data")
load = lambda n: json.load(open(os.path.join(D, n)))
flawed, ref = load("hms_flawed_example.json"), load("hms_reference_example.json")
rules = lambda m: {v.rule for v in validate(m)}


def test_flawed_model_is_detected():
    r = rules(flawed)
    assert {"G3_DUP_INHERIT", "G6_PUBLIC_ATTR", "G10_UNUSED_POLYMORPHIC_TYPE"} <= r, r


def test_abstraction_candidate_detected():
    m = {"classes": [{"name": "A", "attributes": [{"name": "x"}, {"name": "y"}], "operations": []},
                     {"name": "B", "attributes": [{"name": "x"}, {"name": "y"}], "operations": []}],
         "relationships": [{"type": "association", "source": "A", "target": "B", "multiplicity_target": "1"}]}
    assert "G7_MISSING_ABSTRACTION" in rules(m)


def test_cycle_and_dangling():
    m = {"classes": [{"name": "A"}, {"name": "B"}],
         "relationships": [{"type": "inheritance", "source": "A", "target": "B"},
                           {"type": "inheritance", "source": "B", "target": "A"},
                           {"type": "association", "source": "A", "target": "Z"}]}
    assert {"G4_CYCLE", "G2_DANGLING"} <= rules(m)


def test_reference_is_clean_of_errors():
    assert not errors(validate(ref))


def test_notify_pack():
    m = {"classes": [{"name": "Station", "operations": [{"name": "notifyAll"}]}, {"name": "Display"}],
         "relationships": [{"type": "association", "source": "Station", "target": "Display", "multiplicity_target": "*"}]}
    assert any(v.rule == "P1_NOTIFY_WITHOUT_LISTENER_TYPE" for v in check_notification_structure(m))


def test_repair_loop_converges_and_never_returns_worse():
    t = run_repair(MockLLM(skill=1.0), "task", flawed, k_max=3)
    assert t["converged"] and t["violation_scores"][t["best_index"]] <= t["violation_scores"][0]
    assert not errors(validate(t["best_model"]))


def test_repair_loop_with_useless_llm_keeps_best_and_stops():
    t = run_repair(MockLLM(skill=0.0), "task", flawed, k_max=5)
    assert not t["converged"] and t["iterations"] <= 3        # oscillation guard stops after 2 stale rounds
    assert t["best_index"] == 0


def test_self_refine_runs_without_feedback():
    t = run_self_refine(MockLLM(skill=1.0), "task", flawed, k_max=2)
    assert t["iterations"] == 2 and len(t["models"]) == 3


def test_metrics():
    p, r, f = M.structural_correctness(ref, ref)["all"]
    assert (p, r, f) == (1.0, 1.0, 1.0)
    assert M.structural_correctness(flawed, ref)["all"][2] < 1.0
    assert abs(M.stability_index({"p1": [0.5, 0.5], "p2": [0.5, 0.5]}) - 1.0) < 1e-9
    assert M.stability_index({"p1": [0.1, 0.9], "p2": [0.2, 0.8]}) < 1.0
    assert M.structural_agreement([ref, ref]) == 1.0
    assert M.cliffs_delta([3, 4], [1, 2]) == 1.0


def test_extract_json_fenced():
    assert extract_json('text\n```json\n{"a": {"b": 1}}\n```') == {"a": {"b": 1}}


# ---------------------------------------------------------------- v2 regression tests
import subprocess, tempfile, pytest
from validator import check_schema
from repair import run_best_of_n
from llm import RetryingLLM
import run_experiments as RE
import analyze as AN

SENSOR = load("sensor_reference_example.json")
NOTIFY = [check_notification_structure]


def test_sensor_example_is_clean():
    assert not errors(validate(SENSOR, NOTIFY))


def test_schema_deviation_is_reported_not_raised():
    bad = {"classes": [{"name": "A"}, {"name": "B"}], "relationships": [{"type": "inheritance", "from": "A", "to": "B"}]}
    v = validate(bad)
    assert v and all(x.rule == "G0_SCHEMA" for x in v)
    assert score(v) >= 1000
    assert validate("not a model")[0].rule == "G0_SCHEMA"
    assert validate({"classes": [{"name": "A", "attributes": None}], "relationships": []})[0].rule == "G0_SCHEMA"
    assert check_schema(flawed) == []


def test_repair_survives_schema_broken_reply_and_never_picks_it():
    class BadSchema(MockLLM):
        def generate(self, system, user, temperature=0.5):
            return json.dumps({"classes": [{"name": "A"}], "relationships": [{"type": "inheritance", "from": "A", "to": "B"}]})
    t = run_repair(BadSchema(), "task", flawed, k_max=3)          # used to raise KeyError and lose the trajectory
    assert t["best_index"] == 0 and t["best_model"] == flawed
    assert t["violation_scores"][1] >= 1000 and t["regressions"] >= 1
    assert any(x["rule"] == "G0_SCHEMA" for x in t["violations"][1])


def test_metrics_tolerate_malformed_models():
    assert M.structural_correctness({"classes": [{"nom": "x"}], "relationships": [{"type": "inheritance"}]}, ref)["all"][2] == 0.0
    assert M.structural_correctness("garbage", ref)["all"][2] == 0.0


def test_notify_pack_is_direction_agnostic_and_catches_emit():
    good = {"classes": [{"name": "Station", "operations": [{"name": "notifyObservers"}]},
                        {"name": "Listener", "interface": True}, {"name": "Display"}],
            "relationships": [{"type": "association", "source": "Station", "target": "Listener", "multiplicity_target": "*"}]}
    rev = json.loads(json.dumps(good)); rev["relationships"][0].update(source="Listener", target="Station")
    assert not check_notification_structure(good) and not check_notification_structure(rev)
    none = json.loads(json.dumps(good)); none["classes"][0]["operations"][0]["name"] = "emitEvent"; none["relationships"] = []
    assert check_notification_structure(none)


def test_alias_changes_f1_only_when_provided():
    renamed = json.loads(json.dumps(ref))
    for c in renamed["classes"]:
        if c["name"] == "BillingProcessor": c["name"] = "BillingContext"
    for r in renamed["relationships"]:
        for e in ("source", "target"):
            if r[e] == "BillingProcessor": r[e] = "BillingContext"
    assert M.structural_correctness(renamed, ref)["all"][2] < 1.0
    assert M.structural_correctness(renamed, ref, {"BillingProcessor": ["BillingContext"]})["all"][2] == 1.0


def test_best_of_n_picks_lowest_score_and_ignores_failed_samples():
    seq = iter([(None, 5, ""), (ref, 7, "ref_reply"), (flawed, 7, "flawed_reply")])
    t = run_best_of_n(lambda: next(seq), flawed, n_extra=3)
    assert t["best_index"] == 2 and t["best_model"] == ref and t["tokens"] == 19 and t["converged"]
    assert t["models"][1] == flawed                              # failed sample = "no new sample"


def test_retrying_llm_retries_then_raises():
    class Flaky(MockLLM):
        calls = 0
        def generate(self, *a, **k):
            Flaky.calls += 1
            if Flaky.calls < 3: raise RuntimeError("429")
            return "{}"
    assert RetryingLLM(Flaky(), tries=4, sleep=lambda s: None).generate("s", "u") == "{}"
    class Dead(MockLLM):
        def generate(self, *a, **k): raise RuntimeError("down")
    with pytest.raises(RuntimeError):
        RetryingLLM(Dead(), tries=2, sleep=lambda s: None).generate("s", "u")


class FakeProvider:
    """Scripted provider for runner tests. Class-level knobs control failures."""
    fail_standard_initial = 0
    initial_calls = 0
    last_tokens, last_model = 0, "fake-1"
    def __init__(self, name): pass
    def generate(self, system, user, temperature=0.5):
        if "Problems found" in user or "Current model" in user:
            start = user.index("Current model:\n") + 15
            end = user.index("\n\nProblems found") if "Problems found" in user else len(user)
            self.last_tokens = 11
            return user[start:end]
        FakeProvider.initial_calls += 1
        if "STANDARD" in system and FakeProvider.fail_standard_initial > 0:
            FakeProvider.fail_standard_initial -= 1
            raise RuntimeError("API down")
        self.last_tokens = 50
        return json.dumps(flawed)


def _cfg(tmp, conditions, runs=2):
    cfg = {"retry": {"tries": 2, "base_delay": 0}, "temperature": 0.5, "k_max": 2, "runs": runs, "conditions": conditions, "json_instruction": "JSON only",
           "prompts": {"standard": {"system": "STANDARD"}, "rule": {"system": "RULE"}, "preference": {"system": "PREF"}},
           "models": {"fake": {"provider": "fake", "name": "fake-1"}},
           "domains": {"HMS": {"packs": [], "prompts": {"P1": "task"}, "reference": os.path.join(D, "hms_reference_example.json"),
                               "aliases": {}, "dry_seed": os.path.join(D, "hms_flawed_example.json")}}}
    p = os.path.join(tmp, "cfg.json"); json.dump(cfg, open(p, "w")); return p


def _read(path): return [json.loads(l) for l in open(path)]


def test_runner_failed_initial_is_not_silently_redrawn_and_retry_works():
    RE.FACTORY["fake"] = FakeProvider
    with tempfile.TemporaryDirectory() as tmp:
        cfg, out = _cfg(tmp, ["C0", "C4"], runs=1), os.path.join(tmp, "r.jsonl")
        FakeProvider.fail_standard_initial, FakeProvider.initial_calls = 2, 0     # both attempts (tries=2) fail
        RE.main(["--config", cfg, "--out", out])
        recs = {r["condition"]: r for r in _read(out)}
        assert recs["C0"]["trace"] is None and recs["C4"]["trace"] is None      # C4 did NOT draw a different diagram
        assert "initial generation failed" in recs["C4"]["error"]
        assert FakeProvider.initial_calls == 2                                   # only C0's two attempts, nothing for C4
        RE.main(["--config", cfg, "--out", out, "--retry-errors"])
        last = AN.load_records(out)
        by = {r["condition"]: r for r in last}
        assert by["C0"]["trace"] and by["C4"]["trace"]
        assert by["C4"]["trace"]["models"][0] == by["C0"]["trace"]["models"][0]  # paired
        assert by["C4"]["initial_tokens"] == by["C0"]["initial_tokens"] == 50


def test_runner_token_accounting_and_resume_keep_initial_cost():
    RE.FACTORY["fake"] = FakeProvider
    with tempfile.TemporaryDirectory() as tmp:
        cfg, out = _cfg(tmp, ["C2", "C3", "C5", "C6"], runs=1), os.path.join(tmp, "r.jsonl")
        RE.main(["--config", cfg, "--out", out])
        r = {x["condition"]: x for x in _read(out)}
        assert r["C2"]["trace"]["tokens"] == 50 and r["C3"]["trace"]["tokens"] >= 50 and r["C5"]["trace"]["tokens"] >= 50 + 2 * 11
        assert r["C6"]["trace"]["tokens"] == 50 + 2 * 50 and r["C6"]["trace"]["iterations"] == 2
        n = len(_read(out)); RE.main(["--config", cfg, "--out", out]); assert len(_read(out)) == n   # resume = no-op
        assert r["C3"]["model_id"] == "fake-1"


def test_runner_refuses_changed_config_on_resume():
    RE.FACTORY["fake"] = FakeProvider
    with tempfile.TemporaryDirectory() as tmp:
        cfg, out = _cfg(tmp, ["C2"], runs=1), os.path.join(tmp, "r.jsonl")
        RE.main(["--config", cfg, "--out", out])
        c = json.load(open(cfg)); c["prompts"]["preference"]["system"] = "CHANGED"; json.dump(c, open(cfg, "w"))
        with pytest.raises(SystemExit):
            RE.main(["--config", cfg, "--out", out])


def test_analyze_fails_loudly_on_missing_reference_for_real_data():
    RE.FACTORY["fake"] = FakeProvider
    with tempfile.TemporaryDirectory() as tmp:
        cfg, out = _cfg(tmp, ["C2"], runs=1), os.path.join(tmp, "r.jsonl")
        RE.main(["--config", cfg, "--out", out])
        c = json.load(open(cfg)); c["domains"]["HMS"]["reference"] = os.path.join(tmp, "missing.json"); json.dump(c, open(cfg, "w"))
        with pytest.raises(SystemExit) as e:
            AN.main(["--config", cfg, "--results", out])
        assert "reference model" in str(e.value)
