"""Verify that the experimental protocol matches the paper's specification.

Run this before submitting results to ensure:
1. Config uses authentic data from Supporting_Files
2. All 7 conditions (C0-C6) are enabled
3. Model configuration is correct
4. Reference models point to correct files
5. No data leakage (aliases are empty)
"""
import json
import sys
import os


def verify_config(config_path):
    """Check config_full.json against protocol requirements."""
    errors = []
    warnings = []
    
    with open(config_path) as f:
        cfg = json.load(f)
    
    # Check 1: All conditions present
    required_conditions = ["C0", "C1", "C2", "C3", "C4", "C5", "C6"]
    actual_conditions = cfg.get("conditions", [])
    missing = set(required_conditions) - set(actual_conditions)
    if missing:
        errors.append(f"Missing conditions: {sorted(missing)}")
    
    # Check 2: Aliases must be empty (no data leakage)
    for domain, D in cfg.get("domains", {}).items():
        aliases = D.get("aliases", {})
        if aliases:
            errors.append(f"Domain {domain} has non-empty aliases: {aliases}. Must be {{}} to avoid data leakage.")
    
    # Check 3: Reference files exist and must NOT contain "_example"
    for domain, D in cfg.get("domains", {}).items():
        ref = D.get("reference", "")
        if ref:
            if "_example" in ref:
                errors.append(f"Reference file contains '_example': {ref}. Must use authentic reference (hms_reference.json or sensor_reference.json)")
            if not os.path.exists(ref):
                errors.append(f"Reference file missing: {ref}")
            elif domain == "HMS" and "hms_reference" not in ref:
                warnings.append(f"HMS reference points to: {ref} (expected hms_reference.json)")
            elif domain == "Sensor" and "sensor_reference" not in ref:
                warnings.append(f"Sensor reference points to: {ref} (expected sensor_reference.json)")
    
    # Check 4: Dry seed files correct
    for domain, D in cfg.get("domains", {}).items():
        dry_seed = D.get("dry_seed", "")
        if dry_seed:
            if not os.path.exists(dry_seed):
                errors.append(f"Dry seed file missing: {dry_seed}")
            elif domain == "HMS" and "hms_flawed" not in dry_seed:
                errors.append(f"HMS dry_seed points to wrong domain: {dry_seed}")
            elif domain == "Sensor" and "sensor_flawed" not in dry_seed:
                errors.append(f"Sensor dry_seed points to wrong domain: {dry_seed}")
    
    # Check 5: Standard prompt system should be empty
    standard_system = cfg.get("prompts", {}).get("standard", {}).get("system", None)
    if standard_system != "":
        warnings.append(f"Standard prompt system is not empty (length: {len(standard_system)})")
    
    # Check 6: Rule prompt should contain authentic instructions
    rule_system = cfg.get("prompts", {}).get("rule", {}).get("system", "")
    if "strive to produce simplest model" not in rule_system:
        errors.append("Rule prompt does not contain expected Instructions.txt content")
    if "Good Design Practices:" not in rule_system:
        errors.append("Rule prompt does not contain expected Good Design Practices.txt content")
    
    # Check 7: Preference prompt should have examples from dataset.json
    pref_system = cfg.get("prompts", {}).get("preference", {}).get("system", "")
    if "EXAMPLE 1" not in pref_system or "GOOD:" not in pref_system or "BAD:" not in pref_system:
        errors.append("Preference prompt missing GOOD/BAD examples structure")
    
    # Check 8: HMS and Sensor paraphrases present
    for domain, D in cfg.get("domains", {}).items():
        prompts = D.get("prompts", {})
        if len(prompts) < 3:
            errors.append(f"Domain {domain} has only {len(prompts)} prompts, expected 3 (P1, P2, P3)")
    
    # Check 9: Paraphrases match source files (all P1, P2, P3) and forbidden words
    FORBIDDEN_PATTERNS = ["strategy", "observer", "singleton", "factory", "decorator", "composite", 
                          "adapter", "bridge", "prototype", "proxy", "facade", "flyweight",
                          "chain of responsibility", "command", "interpreter", "iterator", 
                          "mediator", "memento", "state", "template method", "visitor"]
    
    # Check HMS prompts P1-P3
    hms_prompts = cfg.get("domains", {}).get("HMS", {}).get("prompts", {})
    hms_key_phrases = {
        "P1": "enterprise hospital management platform",
        "P2": "enterprise-grade hospital management system",
        "P3": "large-scale hospital administration platform"
    }
    
    for pid in ["P1", "P2", "P3"]:
        if pid in hms_prompts:
            prompt = hms_prompts[pid]
            # Check key phrase
            if hms_key_phrases[pid] not in prompt:
                errors.append(f"HMS {pid} does not contain expected phrase: '{hms_key_phrases[pid]}'")
            # Check PlantUML forbidden
            if "Generate a UML class diagram in plantUML" in prompt or "plantuml" in prompt.lower():
                errors.append(f"HMS {pid} contains PlantUML format instruction (should be removed per Việc 1)")
            # Check forbidden pattern names (case-insensitive)
            prompt_lower = prompt.lower()
            found_patterns = [p for p in FORBIDDEN_PATTERNS if p in prompt_lower]
            if found_patterns:
                errors.append(f"HMS {pid} contains forbidden pattern names: {', '.join(found_patterns)}")
    
    # Check Sensor prompts P1-P3
    sensor_prompts = cfg.get("domains", {}).get("Sensor", {}).get("prompts", {})
    sensor_key_phrases = {
        "P1": "distributed environmental monitoring platform",
        "P2": "distributed platform for environmental monitoring",
        "P3": "environmental monitoring system operating in a distributed architecture"
    }
    
    for pid in ["P1", "P2", "P3"]:
        if pid in sensor_prompts:
            prompt = sensor_prompts[pid]
            # Check key phrase
            if sensor_key_phrases[pid] not in prompt:
                errors.append(f"Sensor {pid} does not contain expected phrase: '{sensor_key_phrases[pid]}'")
            # Check PlantUML forbidden
            if "Generate a UML class diagram in plantUML" in prompt or "plantuml" in prompt.lower():
                errors.append(f"Sensor {pid} contains PlantUML format instruction (should be removed)")
            # Check forbidden pattern names
            prompt_lower = prompt.lower()
            found_patterns = [p for p in FORBIDDEN_PATTERNS if p in prompt_lower]
            if found_patterns:
                errors.append(f"Sensor {pid} contains forbidden pattern names: {', '.join(found_patterns)}")
    
    # Check 10: Model ID validation
    for model_name, model_cfg in cfg.get("models", {}).items():
        model_id = model_cfg.get("name", "")
        provider = model_cfg.get("provider", "")
        
        # Check for placeholder/empty model ID
        if not model_id or "<" in model_id or "TODO" in model_id.upper() or "PLACEHOLDER" in model_id.upper():
            errors.append(f"Model {model_name} has invalid/placeholder ID: '{model_id}'. Must provide actual model ID.")
        
        # Provider-specific checks (not hard-coded to Claude)
        if provider == "anthropic" and model_id and "<" not in model_id:
            if not model_id.startswith("claude-"):
                warnings.append(f"Model {model_name} with provider 'anthropic' should start with 'claude-', got: {model_id}")
        elif provider == "openai" and model_id and "<" not in model_id:
            if "gpt-" not in model_id:
                warnings.append(f"Model {model_name} with provider 'openai' should contain 'gpt-', got: {model_id}")
        elif provider == "gemini" and model_id and "<" not in model_id:
            if not model_id.startswith("gemini-"):
                warnings.append(f"Model {model_name} with provider 'gemini' should start with 'gemini-', got: {model_id}")
    
    return errors, warnings


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config_pilot.json"
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found")
        sys.exit(1)
    
    print("Verifying experimental protocol...")
    errors, warnings = verify_config(config_path)
    
    if errors:
        print("\n❌ ERRORS FOUND:")
        for e in errors:
            print(f"  - {e}")
    
    if warnings:
        print("\n⚠️  WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    
    if not errors and not warnings:
        print("\n✅ Protocol verification passed!")
        return 0
    elif not errors:
        print("\n✅ No errors (warnings only)")
        return 0
    else:
        print("\n❌ Protocol verification failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
