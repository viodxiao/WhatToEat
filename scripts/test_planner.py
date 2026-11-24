import unittest

from scripts.planner import Planner
from scripts.recipe_data import Material, Requirement, canonical, expand, load_catalog


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = Planner(*load_catalog())

    def test_examples_from_rule_file(self):
        examples = [
            (["猪里脊"], {"猪里脊", "猪肉"}, {"五花肉"}),
            (["五花肉"], {"五花肉", "猪肉"}, {"猪里脊"}),
            (["猪肉"], {"猪肉"}, {"猪里脊", "五花肉"}),
            (["鲫鱼"], {"鲫鱼", "鱼"}, {"草鱼", "鱼头"}),
            (["口蘑"], {"口蘑", "蘑菇", "菌菇"}, set()),
            (["菌菇"], {"菌菇"}, {"口蘑"}),
            (["猪里脊", "土豆"], {"猪肉", "土豆"}, {"五花肉", "烤箱"}),
            (["茉莉绿茶"], {"茉莉绿茶", "绿茶", "茶叶"}, {"红茶"}),
        ]
        for selected, accepted, rejected in examples:
            with self.subTest(selected=selected):
                covered = expand(selected, self.planner.rules)
                self.assertTrue(accepted <= covered)
                self.assertTrue(rejected.isdisjoint(covered))
        requirements = [Requirement((Material(name, kind),)) for name, kind in [
            ("猪肉", "ingredient"), ("土豆", "ingredient"), ("烤箱", "tool"),
        ]]
        selected = {"猪里脊", "土豆"}
        covered = expand(selected, self.planner.rules)
        missing, blocked, *_ = self.planner.check(requirements, selected, covered, {"tool": {"烤箱"}, "seasoning": set()})
        self.assertEqual(missing, [])
        self.assertEqual(blocked, ["烤箱"])

    def test_required_ingredients_and_missing_supplies(self):
        curry = "炒菜/咖喱肥牛"
        potatoes = self.planner.search(["土豆"], [], [], [1, 2, 3, 4, 5], [])
        self.assertNotIn(curry, {recipe["id"] for recipe in potatoes["ready"]})
        self.assertTrue({curry, "炸品/香脆薯饼"} <= {recipe["id"] for recipe in potatoes["related"]})
        ingredients = ["洋葱", "胡萝卜", "土豆", "肥牛", "牛奶"]
        for seasonings, stars, expected in [([], [4], True), (["咖喱块"], [4], False), ([], [2], False)]:
            results = self.planner.search(ingredients, seasonings, [], stars, [])
            self.assertEqual(curry in {recipe["id"] for recipe in results["ready"]}, expected)

    def test_only_missing_supplies_still_lists_compatible_dishes(self):
        for seasonings, tools, blocked in [
            (["咖喱块"], [], "炒菜/咖喱肥牛"),
            ([], ["烤箱"], "烤类/烤茄子"),
        ]:
            with self.subTest(blocked=blocked):
                results = self.planner.search([], seasonings, tools, range(1, 6), [])
                ids = {recipe["id"] for recipe in results["ready"]}
                self.assertIn("炒菜/西红柿炒鸡蛋", ids)
                self.assertNotIn(blocked, ids)
                self.assertFalse(any(recipe["missing"] for recipe in results["ready"]))
                self.assertEqual(results["related"], [])
                if tools:
                    self.assertIn("烤类/烤鱼", ids)
        for tools, expected in [(["微波炉"], True), (["平底锅", "微波炉"], False)]:
            results = self.planner.search([], [], tools, [1], [])
            self.assertEqual(any(recipe["id"] == "主食/半成品意面" for recipe in results["ready"]), expected)

    def test_category_filter_combines_with_difficulty_and_pantry(self):
        categories = ["炒菜", "汤"]
        results = self.planner.search([], ["咖喱块"], [], [2, 4], [], categories=categories)
        self.assertEqual({recipe["category"] for recipe in results["ready"]}, set(categories))
        self.assertTrue(all(recipe["difficulty"] in {2, 4} for recipe in results["ready"]))
        self.assertFalse(any(recipe["id"] == "炒菜/咖喱肥牛" for recipe in results["ready"]))
        results = self.planner.search(["土豆"], [], [], [4], [], categories=["炒菜"])
        self.assertIn("炒菜/咖喱肥牛", {recipe["id"] for recipe in results["related"]})
        self.assertTrue(all(recipe["category"] == "炒菜" for recipe in results["ready"] + results["related"]))

    def test_recommendations_respect_difficulty_and_replace_previous_batch(self):
        first = self.planner.recommendations([2], [])
        previous_ids = {recipe["id"] for recipe in first}
        next_batch = self.planner.recommendations([2], previous_ids)
        next_ids = {recipe["id"] for recipe in next_batch}
        self.assertEqual(len(previous_ids), 5)
        self.assertEqual(len(next_ids), 5)
        self.assertTrue(previous_ids.isdisjoint(next_ids))
        self.assertTrue(all(recipe["difficulty"] == 2 and recipe["category"] != "配料" for recipe in first + next_batch))
        self.assertEqual(self.planner.recommendations([], previous_ids), [])

    def test_recommendations_respect_missing_supplies_and_categories(self):
        categories = ["炒菜", "烤类"]
        levels = [3, 4]
        seasonings, tools = ["咖喱块"], ["烤箱"]
        compatible = self.planner.search([], seasonings, tools, levels, [], categories=categories)
        allowed = {recipe["id"] for recipe in compatible["ready"]}
        previous = set()
        for _ in range(2):
            batch = self.planner.recommendations(
                levels, previous, categories=categories, seasonings=seasonings, tools=tools,
            )
            picked = {recipe["id"] for recipe in batch}
            self.assertEqual(len(picked), 5)
            self.assertTrue(picked <= allowed)
            self.assertTrue(previous.isdisjoint(picked))
            previous = picked
        self.assertEqual(self.planner.recommendations(levels, [], categories=[]), [])

    def test_search_by_dish_name(self):
        exact = self.planner.find_recipes("西红柿炒鸡蛋")
        self.assertEqual(exact[0]["id"], "炒菜/西红柿炒鸡蛋")
        partial = self.planner.find_recipes("咖喱 肥牛")
        self.assertIn("炒菜/咖喱肥牛", {recipe["id"] for recipe in partial})
        self.assertEqual(self.planner.find_recipes("  "), [])
        self.assertEqual(self.planner.find_recipes("不存在的菜谱名称"), [])

    def test_missing_list_uses_pantry_and_recipe_alternatives(self):
        curry = "炒菜/咖喱肥牛"
        curry_shopping = self.planner.shopping([curry], ["土豆"], ["咖喱块"], [], include_missing=True)
        missing = curry_shopping["missing"]
        ingredients = {item["name"]: item["grams"] for item in missing["ingredient"]}
        self.assertNotIn("土豆", ingredients)
        self.assertEqual(ingredients["肥牛"], 300)
        self.assertEqual([item["name"] for item in missing["seasoning"]], ["咖喱块"])
        self.assertEqual(missing["tool"], [])

        pasta = "主食/半成品意面"
        for tools, expected in [(["微波炉"], []), (["微波炉", "平底锅"], ["平底锅"])]:
            shopping = self.planner.shopping([pasta], ["半成品意大利面"], [], tools, include_missing=True)
            self.assertEqual([item["name"] for item in shopping["missing"]["tool"]], expected)
            self.assertEqual(shopping["missing"]["ingredient"], [])

    def test_optional_and_one_of(self):
        pasta = "主食/半成品意面"
        for tools, expected in [(["平底锅"], True), (["微波炉"], True), (["平底锅", "微波炉"], False)]:
            choices = self.planner.search(["半成品意大利面"], [], tools, [1], [])
            self.assertEqual(pasta in {recipe["id"] for recipe in choices["ready"]}, expected)
        eggs = "炒菜/西红柿炒鸡蛋"
        results = self.planner.search(["番茄", "鸡蛋"], ["糖", "葱"], [], range(1, 6), [])
        self.assertIn(eggs, {recipe["id"] for recipe in results["ready"]})

    def test_preparations_and_weights(self):
        curry, sliced = "炒菜/咖喱肥牛", "炒菜/家常土豆片"
        base = "配料/炒菜基料"
        shopping = self.planner.shopping([curry, sliced, base], [], [], [])
        ingredients = {item["name"]: item["grams"] for item in shopping["ingredient"]}
        self.assertEqual(ingredients["土豆"], 2000)
        self.assertNotIn("炒菜基料", ingredients)
        self.assertIn("蒸鱼豉油", {item["name"] for item in shopping["seasoning"]})
        linked = self.planner.recipes["炒菜/小炒鸡丁"]
        self.assertIn("调味料（小炒鸡丁）", {item.name for group in linked.requirements for item in group.options})
        names = {recipe["id"] for recipe in self.planner.search(["土豆"], [], [], range(1, 6), [base])["ready"]}
        self.assertIn(sliced, names)

    def test_quantities_remain_unknown_if_one_recipe_has_no_grams(self):
        sauce = "配料/草莓酱"
        syrup = "配料/蔗糖糖浆"
        available = self.planner.shopping([sauce, syrup], [], [], [])
        self.assertIn({"name": "白砂糖", "grams": 500.0}, available["seasoning"])
        unknown = "配料/小炒肉调料(2026年更新)"
        combined = self.planner.shopping([sauce, syrup, unknown], [], [], [])
        self.assertIn({"name": "白砂糖", "grams": None}, combined["seasoning"])

    def test_markdown_with_multiple_methods(self):
        soy_milk = "饮品/原味豆浆"
        for ingredients, tools, expected in [
            (["豆浆粉"], ["带煮浆功能的豆浆机"], True),
            (["黄豆"], [], True),
            (["黄豆"], ["带煮浆功能的豆浆机"], False),
        ]:
            results = self.planner.search(ingredients, [], tools, [2], [])
            self.assertEqual(soy_milk in {recipe["id"] for recipe in results["ready"]}, expected)
        self.assertEqual([section["title"] for section in self.planner.recipes[soy_milk].sections], ["现磨版", "冲调版"])

    def test_only_csv_tags_can_be_selected_for_seasonings_and_tools(self):
        csv_labels = {canonical(tag) for recipe in self.planner.recipes.values() for tag in recipe.tags}
        for kind, required, hidden in [
            ("seasoning", "咖喱块", {"盐", "食用油"}),
            ("tool", "烤箱", {"刀", "炒锅"}),
        ]:
            names = {tag["name"] for tag in self.planner.facets[kind]}
            self.assertTrue(names <= csv_labels)
            self.assertIn(required, names)
            self.assertTrue(hidden.isdisjoint(names))

    def test_formula_amounts_from_tomato_and_eggs(self):
        recipe_id = "炒菜/西红柿炒鸡蛋"
        detail = self.planner.detail(self.planner.recipes[recipe_id])
        original = {item["name"]: item for group in detail["requirements"] for item in group["options"]}
        shopping = self.planner.shopping([recipe_id], [], [], [])
        required = {item["name"]: item for items in shopping.values() for item in items}
        self.assertEqual(required["番茄"]["grams"], 180)
        self.assertTrue(required["番茄"]["approximate"])
        self.assertIn("1.5 个", required["鸡蛋"]["quantity"])
        self.assertIn("4ml", required["食用油"]["quantity"])
        self.assertIn("1.5-2g", required["盐"]["quantity"])
        self.assertIsNone(required["盐"]["grams"])
        self.assertIn("0-2g", original["糖"]["quantity"])


if __name__ == "__main__":
    unittest.main()
