"""阶段三归一与校验层的单元测试：不调用模型，只测「本体这一层」。"""

import unittest

from .nl_query import (ontology_view, parse_params, passthrough, render_ontology,
                       normalize)
from .planner import Planner
from .recipe_data import load_catalog


class NormalizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = Planner(*load_catalog())
        cls.view = ontology_view(cls.planner)

    def params(self, **overrides):
        base = {"mode": "search", "ingredients": [], "seasonings": [], "tools": [],
                "difficulties": [1, 2, 3, 4, 5], "categories": None,
                "preparation_ids": [], "name_query": "", "unsupported_dimensions": [],
                "notes": ""}
        base.update(overrides)
        return base

    def test_alias_maps_to_canonical(self):
        clean, report = normalize(self.params(ingredients=["西红柿"]), self.view)
        self.assertEqual(clean["ingredients"], ["番茄"])
        self.assertEqual(report["aliases"], {"西红柿": "番茄"})

    def test_kind_mismatch_is_dropped_not_moved(self):
        # 生抽是佐料，写进 ingredients 说明模型搞错了方向；
        # 系统没有「我有佐料」的表达，只能丢弃并记录，不能搬进 seasonings（那表示没有）。
        clean, report = normalize(self.params(ingredients=["生抽"]), self.view)
        self.assertEqual(clean["ingredients"], [])
        self.assertEqual(clean["seasonings"], [])
        self.assertEqual(report["kind_mismatch"][0]["expected"], "seasoning")

    def test_unknown_name_recorded(self):
        clean, report = normalize(self.params(ingredients=["澳洲龙虾"]), self.view)
        self.assertEqual(clean["ingredients"], [])
        self.assertEqual(report["unmapped"]["ingredient"], ["澳洲龙虾"])

    def test_invalid_category_dropped(self):
        clean, report = normalize(self.params(categories=["川菜"]), self.view)
        self.assertEqual(clean["categories"], [])
        self.assertTrue(any("川菜" in item for item in report["violations"]))

    def test_difficulty_clamped(self):
        clean, report = normalize(self.params(difficulties=[0, 2, 9]), self.view)
        self.assertEqual(clean["difficulties"], [2])
        self.assertTrue(report["violations"])

    def test_polarity_conflict_keeps_valid_side(self):
        # 「生抽」在佐料里合法、在食材里非法：保留「没有生抽」，丢弃「有生抽」。
        clean, report = normalize(
            self.params(ingredients=["生抽"], seasonings=["生抽"]), self.view)
        self.assertEqual(clean["seasonings"], ["生抽"])
        self.assertEqual(clean["ingredients"], [])
        self.assertTrue(report["kind_mismatch"])

    def test_duplicates_removed(self):
        clean, _ = normalize(self.params(ingredients=["番茄", "西红柿", "番茄"]), self.view)
        self.assertEqual(clean["ingredients"], ["番茄"])

    def test_passthrough_keeps_raw_strings(self):
        raw = passthrough(self.params(ingredients=["西红柿"]))
        self.assertEqual(raw["ingredients"], ["西红柿"])

    def test_parse_params_tolerates_fence_and_missing_fields(self):
        params = parse_params('```json\n{"ingredients": ["番茄"]}\n```')
        self.assertEqual(params["ingredients"], ["番茄"])
        self.assertEqual(params["difficulties"], [1, 2, 3, 4, 5])
        self.assertEqual(params["mode"], "search")

    def test_prompt_carries_whole_vocabulary(self):
        text = render_ontology(self.view)
        self.assertEqual(len(self.view["categories"]), 14)
        for name in ("番茄", "生抽", "盐", "高压锅"):
            self.assertIn(name, text)

    def test_extraction_noise_kept_out_of_vocabulary(self):
        # 阶段二复查为 0 之后仍有数量短语和半截句子残留，不能塞进提示词。
        for name in ("一个容量在", "不加水融化会很慢", "2cm 两段葱段", "两个塑料簸箕"):
            self.assertNotIn(name, self.view["ingredient"])
            self.assertNotIn(name, self.view["accepted"]["ingredient"])

    def test_rare_name_accepted_but_not_in_prompt(self):
        # 只出现一次的真实原料不进提示词（省 token），但校验必须放行。
        self.assertIn("青蟹", self.view["accepted"]["ingredient"])
        self.assertNotIn("青蟹", self.view["ingredient"])

    def test_single_char_names_survive(self):
        for name in ("盐", "油", "糖", "葱"):
            self.assertIn(name, self.view["seasoning"])


if __name__ == "__main__":
    unittest.main()
