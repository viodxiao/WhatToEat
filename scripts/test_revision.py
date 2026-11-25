import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from . import stage3_eval as evaluation
from .agent import parse_request
from .main import app
from .llm_client import extract_json
from .nl_query import parse_params, ontology_view
from .planner import Planner
from .recipe_data import load_catalog


class FakeClient:
    configured = True
    def __init__(self, **payload): self.payload = payload
    def describe(self): return {'model': 'test-double'}
    def chat(self, *args, **kwargs):
        return {'text': json.dumps(self.payload), 'model': 'test-double', 'usage': {}}


class RevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = Planner(*load_catalog())
        cls.view = ontology_view(cls.planner)

    def test_json_string_braces(self):
        self.assertEqual(extract_json('结果： {"notes": "含有 } 字符"} 结束'), {'notes': '含有 } 字符'})

    def test_reject_malformed_constraints(self):
        for payload in [{'seasonings': '盐'}, {'tools': [True]}, {'categories': 3},
                        {'difficulties': [True]}, {'difficulties': []},
                        {'difficulties': [6]}, {'ingredients': {'鸡蛋': 1}}, {'surprise': 1}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_params(json.dumps(payload))

    def test_exact_penalizes_extra_field(self):
        gold = parse_params('{"ingredients":["鸡蛋"]}')
        pred = dict(gold, tools=['烤箱'])
        self.assertEqual(evaluation.score_params(pred, gold)['exact'], 0)
        self.assertEqual(evaluation.score_params(gold, gold)['exact'], 1)
        empty = parse_params('{}')
        self.assertEqual(evaluation.score_params(empty, empty)['exact'], 1)

    def test_unknown_exclusion_blocks_execution(self):
        result = parse_request('没有神秘酱', self.planner, self.view,
                               FakeClient(seasonings=['神秘酱']))
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertIsNone(result['search_payload'])

    def test_unsupported_time_blocks_execution(self):
        result = parse_request('十分钟内', self.planner, self.view,
                               FakeClient(unsupported_dimensions=['时间']))
        self.assertEqual(result['status'], 'needs_clarification')

    def test_replay_never_calls_model(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(evaluation, 'RECORD_ROOT', Path(directory)):
            client = FakeClient()
            with patch.object(client, 'chat', side_effect=AssertionError('network')):
                with self.assertRaises(ValueError):
                    evaluation.run_arm(self.planner, self.view, evaluation.TASKS[0], 'B', client, replay=True)

    def test_failure_remains_in_denominator(self):
        row = evaluation.summarize({}, evaluation.TASKS[:2])['C']
        self.assertEqual(row['tasks'], 2)
        self.assertEqual(row['errors'], 2)
        self.assertEqual(row['ready_zero_rate'], 1)

    def test_feasibility_includes_category_and_difficulty(self):
        dish = self.planner.dishes[0]
        gold = parse_params('{}')
        gold['difficulties'] = [n for n in range(1, 6) if n != dish.difficulty]
        gold['categories'] = ['不存在分类']
        record = {'result': {'items': [{'id': dish.id}]}}
        with patch.object(self.planner, 'best_method', return_value=([], ([], [], 0, 0, 0, 0))):
            evaluation.annotate_feasibility({'X': {'C': record}}, self.planner, [{'id': 'X', 'gold': gold}])
        self.assertEqual(record['feasible'], 0)

    def test_real_api_chain_with_fake_model(self):
        with TestClient(app) as client:
            app.state.llm_client = FakeClient(ingredients=['番茄', '鸡蛋'])
            parsed = client.post('/api/parse', json={'text': '有番茄鸡蛋'} )
            self.assertEqual(parsed.status_code, 200)
            body = parsed.json()
            self.assertEqual(body['status'], 'ready')
            response = client.post('/api/search', json=body['search_payload'])
            self.assertEqual(response.status_code, 200)
            expected = self.planner.search(['番茄','鸡蛋'], [], [], [1,2,3,4,5], [])
            self.assertEqual(response.json(), expected)
            self.assertIn('requires', body['trace']['system_prompt'])
            app.state.llm_client = FakeClient(seasonings='盐')
            self.assertEqual(client.post('/api/parse', json={'text': '没盐'}).status_code, 422)
            del app.state.llm_client

    def test_b_c_share_model_response(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(evaluation, 'RECORD_ROOT', Path(directory)):
            client = FakeClient(ingredients=['番茄'])
            with patch.object(client, 'chat', wraps=client.chat) as mocked:
                evaluation.run_arm(self.planner, self.view, evaluation.TASKS[0], 'B', client, replay=False)
                record = evaluation.run_arm(self.planner, self.view, evaluation.TASKS[0], 'C', client, replay=False)
                self.assertEqual(mocked.call_count, 1)
                self.assertEqual(record['paired_with'], 'B')


if __name__ == '__main__':
    unittest.main()
