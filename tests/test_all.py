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


def test_retrying_wrapper_retries_then_succeeds():
    from llm import RetryingLLM, LLMClient
    class Flaky(LLMClient):
        n = 0
        def generate(self, system, user, temperature=0.5):
            Flaky.n += 1
            if Flaky.n < 2:
                raise RuntimeError("429")
            return "ok"
    import time
    orig, time.sleep = time.sleep, lambda s: None
    try:
        assert RetryingLLM(Flaky(), retries=3).generate("s", "u") == "ok"
    finally:
        time.sleep = orig


def test_initial_regenerates_on_malformed_reply():
    import run_experiments as R
    class L:
        calls = 0; last_tokens = 5
        def generate(self, s, u, t=0.5):
            L.calls += 1
            return "{ truncated" if L.calls < 3 else '{"classes": [], "relationships": []}'
    cfg = {"prompts": {"standard": {"system": "x"}}, "json_instruction": "y"}
    m, tok = R.initial(L(), cfg, "standard", "task", 0.5)
    assert m == {"classes": [], "relationships": []} and tok == 15
