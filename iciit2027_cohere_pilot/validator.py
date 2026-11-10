"""Deterministic validator for UML class models (JSON form).

Model schema
------------
{"classes": [{"name": str, "abstract": bool, "interface": bool,
              "attributes": [{"name": str, "type": str, "visibility": "-|+|#|~"}],
              "operations": [{"name": str, "visibility": "-|+|#|~"}]}],
 "relationships": [{"type": "inheritance|realization|association|aggregation|composition|dependency",
                    "source": str, "target": str,
                    "multiplicity_source": str, "multiplicity_target": str, "label": str}]}
Direction: inheritance/realization go child -> parent / implementor -> interface.

Feedback messages are written in structural terms and never name a design
pattern, so that the repair loop does not leak pattern names into the prompt.
"""
from dataclasses import dataclass, asdict
from itertools import combinations

INH = ("inheritance", "realization")
USE = ("association", "aggregation", "composition", "dependency")
REL_TYPES = INH + USE
SCHEMA_WEIGHT = 1000     # a schema-broken model must never be chosen as "best" over a well-formed one
# Operation-name prefixes that mark "this class announces changes" (rule pack P1). Frozen before benchmark runs.
NOTIFY_PREFIXES = ("notify", "broadcast", "publish", "emit", "fireevent")


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: str          # "error" | "warning"
    where: str
    message: str

    def as_dict(self):
        return asdict(self)


def check_schema(m):
    """G0 (error): the model does not follow the JSON schema. Every other rule assumes a well-formed model,
    so when G0 fires `validate` returns only the G0 violations (instead of raising KeyError)."""
    def v(where, msg):
        return Violation("G0_SCHEMA", "error", where, msg)
    if not isinstance(m, dict):
        return [v("model", "The model must be one JSON object with 'classes' and 'relationships'.")]
    out = []
    classes, rels = m.get("classes"), m.get("relationships")
    if not isinstance(classes, list):
        out.append(v("classes", "'classes' must be a list of class objects."))
        classes = []
    if not isinstance(rels, list):
        out.append(v("relationships", "'relationships' must be a list of relationship objects."))
        rels = []
    for i, c in enumerate(classes):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"].strip():
            out.append(v(f"classes[{i}]", "Every class needs a non-empty string 'name'."))
            continue
        for key in ("attributes", "operations"):
            items = c.get(key, [])
            if not isinstance(items, list) or any(not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in items):
                out.append(v(f"{c['name']}.{key}", f"'{key}' of '{c['name']}' must be a list of objects with a string 'name'."))
    for i, r in enumerate(rels):
        if not isinstance(r, dict):
            out.append(v(f"relationships[{i}]", "Every relationship must be an object."))
            continue
        if r.get("type") not in REL_TYPES:
            out.append(v(f"relationships[{i}]", f"Relationship type '{r.get('type')}' is not one of: {', '.join(REL_TYPES)}."))
        for end in ("source", "target"):
            if not isinstance(r.get(end), str):
                out.append(v(f"relationships[{i}]", f"Relationship {i} needs a string '{end}' (use the keys 'source' and 'target')."))
    return out


def _classes(m):
    return {c["name"]: c for c in m.get("classes", [])}


def _rels(m, kinds=None):
    return [r for r in m.get("relationships", []) if kinds is None or r.get("type") in kinds]


def _parents(m):
    p = {}
    for r in _rels(m, INH):
        p.setdefault(r["source"], []).append(r["target"])
    return p


def _ancestors(parents, name):
    seen, stack = set(), list(parents.get(name, []))
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack.extend(parents.get(x, []))
    return seen


def check_duplicate_class(m):
    names = [c["name"] for c in m.get("classes", [])]
    return [Violation("G1_DUP_CLASS", "error", n, f"Class '{n}' is declared more than once.")
            for n in sorted({n for n in names if names.count(n) > 1})]


def check_dangling(m):
    cl, out = _classes(m), []
    for r in m.get("relationships", []):
        for end in ("source", "target"):
            if r.get(end) not in cl:
                out.append(Violation("G2_DANGLING", "error", f"{r.get('source')}->{r.get('target')}",
                                     f"Relationship refers to undefined class '{r.get(end)}'."))
    return out


def check_duplicate_inheritance(m):
    seen, out = set(), []
    for r in _rels(m, INH):
        k = (r["source"], r["target"])
        if k in seen:
            out.append(Violation("G3_DUP_INHERIT", "error", f"{k[0]}->{k[1]}",
                                 f"The generalization from '{k[0]}' to '{k[1]}' is drawn more than once."))
        seen.add(k)
    return out


def check_cycle(m):
    parents, out, reported = _parents(m), [], set()
    for c in parents:
        if c in _ancestors(parents, c):
            key = frozenset(x for x in _ancestors(parents, c) if c in _ancestors(parents, x)) | {c}
            if key not in reported:
                reported.add(key)
                out.append(Violation("G4_CYCLE", "error", ",".join(sorted(key)),
                                     "Classes inherit from each other in a cycle: " + ", ".join(sorted(key)) + "."))
    return out


def check_multi_parent(m):
    cl, out = _classes(m), []
    for c, ps in _parents(m).items():
        concrete = {p for p in ps if p in cl and not cl[p].get("interface")}
        if len(concrete) > 1:
            out.append(Violation("G5_MULTI_PARENT", "warning", c,
                                 f"'{c}' inherits from several classes ({', '.join(sorted(concrete))}); "
                                 "choose a single parent or use an interface."))
    return out


def check_encapsulation(m):
    out = []
    for c in m.get("classes", []):
        if c.get("interface"):
            continue
        for a in c.get("attributes", []):
            if a.get("visibility", "-") == "+":
                out.append(Violation("G6_PUBLIC_ATTR", "warning", f"{c['name']}.{a['name']}",
                                     f"Attribute '{a['name']}' of '{c['name']}' is public; hide it and expose operations."))
    return out


def check_abstraction(m, jaccard=0.6, min_shared=2):
    cl, parents, out = _classes(m), _parents(m), []
    names = [n for n, c in cl.items() if not c.get("interface")]
    for a, b in combinations(sorted(names), 2):
        if (_ancestors(parents, a) & _ancestors(parents, b)) or a in _ancestors(parents, b) or b in _ancestors(parents, a):
            continue
        sa = {x["name"].lower() for x in cl[a].get("attributes", [])}
        sb = {x["name"].lower() for x in cl[b].get("attributes", [])}
        if len(sa & sb) >= min_shared and len(sa | sb) and len(sa & sb) / len(sa | sb) >= jaccard:
            out.append(Violation("G7_MISSING_ABSTRACTION", "warning", f"{a},{b}",
                                 f"'{a}' and '{b}' share attributes ({', '.join(sorted(sa & sb))}) but have no common parent; "
                                 "consider factoring the shared state into a superclass."))
    return out


def check_orphans(m):
    used = {r.get(e) for r in m.get("relationships", []) for e in ("source", "target")}
    cls = m.get("classes", [])
    if len(cls) < 2:
        return []
    return [Violation("G8_ORPHAN", "warning", c["name"], f"Class '{c['name']}' has no relationship to any other class.")
            for c in cls if c["name"] not in used]


def check_multiplicity(m):
    out = []
    for r in _rels(m, ("association", "aggregation", "composition")):
        if not (r.get("multiplicity_source") or r.get("multiplicity_target")):
            out.append(Violation("G9_NO_MULTIPLICITY", "warning", f"{r['source']}->{r['target']}",
                                 f"The {r['type']} between '{r['source']}' and '{r['target']}' has no multiplicity."))
    return out


def check_unused_polymorphic_type(m):
    """A purely behavioural type (interface, or abstract class without state) with >=2 specialisations
    that nobody outside its hierarchy refers to. Abstract classes that carry state (e.g. a Patient
    superclass) are legitimate generalisations and are not flagged."""
    cl, parents, out = _classes(m), _parents(m), []
    children = {}
    for c, ps in parents.items():
        for p in ps:
            children.setdefault(p, set()).add(c)
    for p, ch in sorted(children.items()):
        if p not in cl or len(ch) < 2:
            continue
        behavioural = cl[p].get("interface") or (cl[p].get("abstract") and not cl[p].get("attributes"))
        if not behavioural:
            continue
        family = ch | {p}
        users = [r for r in _rels(m, USE) if r["target"] == p and r["source"] not in family]
        users += [r for r in _rels(m, USE) if r["source"] == p and r["target"] not in family]
        if not users:
            out.append(Violation("G10_UNUSED_POLYMORPHIC_TYPE", "error", p,
                                 f"'{p}' has {len(ch)} specialisations ({', '.join(sorted(ch))}) but no other class refers to it, "
                                 "so the variation is never used; add the class that holds a reference to it."))
    return out


GENERIC_RULES = [check_duplicate_class, check_dangling, check_duplicate_inheritance, check_cycle, check_multi_parent,
                 check_encapsulation, check_abstraction, check_orphans, check_multiplicity, check_unused_polymorphic_type]


def check_notification_structure(m):
    """Optional rule pack for event-driven domains: a class that announces changes must reach its listeners
    through a polymorphic type. Described structurally (no pattern name). The direction in which the link is
    drawn does not matter (LLMs draw navigation either way)."""
    cl, out = _classes(m), []
    for c in m.get("classes", []):
        ops = [o["name"].lower() for o in c.get("operations", [])]
        if any(o.startswith(NOTIFY_PREFIXES) for o in ops):
            others = set()
            for r in _rels(m, USE):
                if r["source"] == c["name"]:
                    others.add(r["target"])
                elif r["target"] == c["name"]:
                    others.add(r["source"])
            poly = [t for t in others if t in cl and (cl[t].get("interface") or cl[t].get("abstract"))]
            if not poly:
                out.append(Violation("P1_NOTIFY_WITHOUT_LISTENER_TYPE", "error", c["name"],
                                     f"'{c['name']}' announces changes but does not reference an abstract listener type."))
    return out


def validate(model, packs=()):
    """Return a sorted list of Violation. `packs` is a list of extra rule functions."""
    bad = check_schema(model)
    if bad:
        return sorted(bad, key=lambda v: v.where)
    out = []
    for rule in list(GENERIC_RULES) + list(packs):
        out.extend(rule(model))
    return sorted(out, key=lambda v: (v.severity != "error", v.rule, v.where))


def score(violations, w_error=3, w_warning=1):
    return sum(SCHEMA_WEIGHT if v.rule == "G0_SCHEMA" else w_error if v.severity == "error" else w_warning
               for v in violations)


def errors(violations):
    return [v for v in violations if v.severity == "error"]
