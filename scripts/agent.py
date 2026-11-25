"""可审计的自然语言解析；HTTP 搜索由调用方执行，模型不能选择工具地址。"""
from .nl_query import parse_params, normalize, parser_prompt, PROMPT_DIR

SEARCH_FIELDS = ('ingredients', 'seasonings', 'tools', 'difficulties', 'categories', 'preparation_ids')


def parse_request(text, planner, view, client, *, use_ontology=True):
    system = (parser_prompt(view) if use_ontology else
              (PROMPT_DIR / 'parser_plain.md').read_text(encoding='utf-8'))
    reply = client.chat(system, text)
    raw = parse_params(reply['text'])
    params, report = normalize(raw, view) if use_ontology else (raw, {})
    reasons = clarification_reasons(params, report, planner)
    return {
        'status': 'needs_clarification' if reasons else 'ready',
        'reasons': reasons, 'params_raw': raw, 'params': params, 'report': report,
        'search_payload': None if reasons else {k: params[k] for k in SEARCH_FIELDS},
        'trace': {'system_prompt': system, 'user': text, 'raw_response': reply['text'],
                  'model': reply.get('model', client.describe().get('model')),
                  'usage': reply.get('usage', {}), 'elapsed_ms': reply.get('elapsed_ms', 0),
                  'use_ontology': use_ontology,
                  'ontology_sha256': view['ontology_sha256'] if use_ontology else None},
        'assumptions': ['佐料和厨具默认齐备，除非明确声明缺少',
                        '无食材条件时只浏览候选，不保证现有食材能完成菜谱'],
    }


def clarification_reasons(params, report, planner):
    reasons = list(params['unsupported_dimensions'])
    if params['mode'] != 'search':
        reasons.append('当前自然语言入口只执行条件搜索，请明确食材和筛选条件')
    if report.get('dropped') or report.get('violations'):
        reasons.append('存在未映射或冲突条件，需修正后搜索')
    # Even plain mode must not silently discard unknown API filter values.
    valid_categories = {r.category for r in planner.dishes}
    if params['categories'] is not None and not set(params['categories']) <= valid_categories:
        reasons.append('分类不受搜索接口支持')
    if not set(params['preparation_ids']) <= set(planner.preparations.values()):
        reasons.append('半成品 ID 无效')
    return reasons
