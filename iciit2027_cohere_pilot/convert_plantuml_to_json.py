#!/usr/bin/env python3
"""Convert PlantUML text to JSON schema used by the system"""
import json
import re
import sys

def parse_plantuml_to_json(plantuml_text):
    """
    Convert PlantUML text to JSON schema.
    
    Handles:
    - abstract class / class / interface
    - attributes with visibility and type
    - operations with visibility
    - inheritance (--|>, extends)
    - realization (..|>, implements)
    - associations with multiplicities
    - aggregations (o--)
    - compositions (*--)
    """
    
    classes = {}
    relationships = []
    
    # Remove @startuml/@enduml and comments
    lines = []
    for line in plantuml_text.split('\n'):
        line = line.strip()
        if line and not line.startswith("'") and not line.startswith('@'):
            lines.append(line)
    text = '\n'.join(lines)
    
    # Parse classes: (abstract )?(class|interface) Name { body }
    class_pattern = r'(abstract\s+)?(class|interface)\s+(\w+)(?:\s+extends\s+\w+)?(?:\s+implements\s+[\w,\s]+)?\s*\{([^}]*)\}'
    
    for match in re.finditer(class_pattern, text, re.DOTALL):
        is_abstract, class_type, class_name, body = match.groups()
        
        attrs = []
        ops = []
        
        # Parse attributes: (visibility) name : type
        for line in body.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Attribute: - name : type or + name : type
            attr_match = re.match(r'([+\-#~])\s*(\w+)\s*:\s*(\w+)', line)
            if attr_match:
                vis, name, typ = attr_match.groups()
                attrs.append({"name": name, "type": typ, "visibility": vis})
                continue
            
            # Operation: + methodName(...) : returnType or just + methodName()
            op_match = re.match(r'([+\-#~])\s*(\w+)\s*\([^)]*\)', line)
            if op_match:
                vis, name = op_match.groups()
                ops.append({"name": name, "visibility": vis})
                continue
        
        classes[class_name] = {
            "name": class_name,
            "abstract": bool(is_abstract) or (class_type == 'interface'),
            "interface": class_type == 'interface',
            "attributes": attrs,
            "operations": ops
        }
    
    # Parse relationships
    
    # Inheritance: Child --|> Parent or Child extends Parent
    for match in re.finditer(r'(\w+)\s+--\|>\s*(\w+)', text):
        source, target = match.groups()
        relationships.append({
            "type": "inheritance",
            "source": source,
            "target": target
        })
    
    # Realization: Impl ..|> Interface or Impl implements Interface  
    for match in re.finditer(r'(\w+)\s+\.\.\|>\s*(\w+)', text):
        source, target = match.groups()
        relationships.append({
            "type": "realization",
            "source": source,
            "target": target
        })
    
    # Alternative syntax: Class <|-- Child
    for match in re.finditer(r'(\w+)\s+<\|--\s*(\w+)', text):
        target, source = match.groups()  # reversed!
        relationships.append({
            "type": "inheritance",
            "source": source,
            "target": target
        })
    
    # Association with multiplicities: A "1" -- "0..*" B : label
    for match in re.finditer(r'(\w+)\s+"([^"]+)"\s+--\s+"([^"]+)"\s+(\w+)(?:\s*:\s*([^>\n]+))?', text):
        source, mult_s, mult_t, target, label = match.groups()
        rel = {
            "type": "association",
            "source": source,
            "target": target,
            "multiplicity_source": mult_s.strip(),
            "multiplicity_target": mult_t.strip()
        }
        if label:
            rel["label"] = label.strip()
        relationships.append(rel)
    
    # Aggregation: A o-- B or A "1" o-- "1" B
    for match in re.finditer(r'(\w+)(?:\s+"([^"]+)")?\s+o--\s+(?:"([^"]+)")?\s*(\w+)', text):
        source, mult_s, mult_t, target = match.groups()
        rel = {
            "type": "aggregation",
            "source": source,
            "target": target
        }
        if mult_s:
            rel["multiplicity_source"] = mult_s
        if mult_t:
            rel["multiplicity_target"] = mult_t
        relationships.append(rel)
    
    # Composition: A *-- B or A "1" *-- "1..*" B
    for match in re.finditer(r'(\w+)(?:\s+"([^"]+)")?\s+\*--\s+(?:"([^"]+)")?\s*(\w+)', text):
        source, mult_s, mult_t, target = match.groups()
        rel = {
            "type": "composition",
            "source": source,
            "target": target
        }
        if mult_s:
            rel["multiplicity_source"] = mult_s
        if mult_t:
            rel["multiplicity_target"] = mult_t
        relationships.append(rel)
    
    # Association without explicit multiplicities: A -- B
    for match in re.finditer(r'(\w+)\s+--\s+(\w+)(?:\s*:\s*([^>\n]+))?', text):
        source, target, label = match.groups()
        # Skip if already captured by other patterns
        if any(r['source'] == source and r['target'] == target for r in relationships):
            continue
        rel = {
            "type": "association",
            "source": source,
            "target": target
        }
        if label:
            rel["label"] = label.strip()
        relationships.append(rel)
    
    # Dependency: A ..> B
    for match in re.finditer(r'(\w+)\s+\.\.>\s*(\w+)', text):
        source, target = match.groups()
        relationships.append({
            "type": "dependency",
            "source": source,
            "target": target
        })
    
    return {
        "classes": list(classes.values()),
        "relationships": relationships
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python convert_plantuml_to_json.py <input.txt> [output.json]")
        print("\nConverts PlantUML text file to JSON schema")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.txt', '.json')
    
    try:
        plantuml_text = open(input_file, encoding='utf-8').read()
        model = parse_plantuml_to_json(plantuml_text)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(model, f, indent=2)
        
        print(f"✅ Converted {input_file} -> {output_file}")
        print(f"   Classes: {len(model['classes'])}")
        print(f"   Relationships: {len(model['relationships'])}")
        
    except FileNotFoundError:
        print(f"❌ File not found: {input_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
