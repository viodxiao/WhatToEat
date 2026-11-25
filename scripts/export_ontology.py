"""导出规则抽取的实例与文件级证据；不把实例数量宣称为新建概念数量。"""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from .recipe_data import load_catalog, ALIASES

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export():
    recipes, rules, _ = load_catalog()
    sources = {str(p.relative_to(ROOT)): {'sha256': digest(p), 'bytes': p.stat().st_size}
               for p in sorted((ROOT / 'recipe').rglob('*')) if p.is_file()}
    instances = []
    for r in recipes.values():
        source_path = f'recipe/{r.id}.md'
        if source_path not in sources:
            source_path = f"recipe/{r.category}/{r.name.replace('/', '／')}.md"
        if source_path not in sources:
            raise ValueError(f'Cannot resolve source for {r.id}')
        instances.append({
            'id': r.id, 'type': 'Preparation' if r.category == '配料' else 'Dish',
            'name': r.name, 'category': r.category, 'difficulty': r.difficulty,
            'requires': [asdict(g) for g in r.requirements],
            'variants': [[asdict(g) for g in v] for v in r.variants],
            'evidence': {'file': source_path, 'sha256': sources.get(source_path, {}).get('sha256'),
                         'original_source': r.source, 'materials_text': r.materials_text},
            'review_status': 'rule_extracted_not_manually_verified',
        })
    result = {'schema_file': 'ontology/ontology.json',
              'schema_sha256': digest(ROOT / 'ontology/ontology.json'),
              'extractor_sha256': digest(ROOT / 'scripts/recipe_data.py'),
              'method': 'deterministic_rule_extraction',
              'evidence_granularity': 'file + original materials text; not per-triple entailment proof',
              'sources': sources, 'aliases': ALIASES, 'coverage_rules': {k: sorted(v) for k, v in sorted(rules.items())}, 'instances': instances}
    output = ROOT / 'ontology/instances.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(instances)} instances, {len(sources)} source files -> {output}')


if __name__ == '__main__':
    export()
