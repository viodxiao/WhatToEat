from collections import Counter
from dataclasses import asdict
from random import sample
from unicodedata import normalize

from .recipe_data import ALIASES, AVAILABILITY_STOP, KINDS, PARENTHESES, canonical, expand, kind_of


LABELS = {"ingredient": "食材", "seasoning": "佐料", "tool": "厨具"}


def all_groups(recipe):
    return [*recipe.requirements, *(group for variant in recipe.variants for group in variant)]


class Planner:
    def __init__(self, recipes, rules, vocabulary):
        self.recipes = recipes
        self.rules = rules
        self.dishes = [recipe for recipe in recipes.values() if recipe.category != "配料"]
        self.preparations = {recipe.name: recipe.id for recipe in recipes.values() if recipe.category == "配料"}
        entries = Counter()
        csv_labels = set()
        for recipe in recipes.values():
            for tag in recipe.tags:
                name = canonical(tag)
                csv_labels.add(name)
                entries[kind_of(name, self.preparations), name] += 1
            for group in all_groups(recipe):
                for item in group.options:
                    entries[item.kind, item.name] += 1
        actual_catalog = {
            name: kind for kind, name in sorted(entries, key=entries.get)
        }
        for name in vocabulary:
            actual_catalog.setdefault(canonical(name), kind_of(canonical(name), self.preparations))
        self.facets = {kind: [] for kind in KINDS}
        terms = {}
        for alias, name in ALIASES.items():
            terms.setdefault(name, []).append(alias)
        for name, kind in sorted(actual_catalog.items(), key=lambda pair: (-entries[pair[1], pair[0]], pair[0])):
            if kind != "ingredient" and name not in csv_labels:
                continue
            self.facets[kind].append({
                "name": name, "prep_id": self.preparations.get(name),
                "terms": terms.get(name, []), "in_csv": name in csv_labels,
            })
        self.lookup = {recipe.id: self.summary(recipe) for recipe in recipes.values()}
        self.related_terms = {
            recipe.id: {
                canonical(note[1])
                for material in recipe.materials_text for note in PARENTHESES.finditer(material)
                if canonical(note[1]) in actual_catalog
            }
            for recipe in self.dishes
        }

    def summary(self, recipe):
        categories = {kind: [] for kind in KINDS}
        for group in all_groups(recipe):
            for item in group.options:
                if item.name not in categories[item.kind]:
                    categories[item.kind].append(item.name)
        for tag in recipe.tags:
            tag = canonical(tag)
            if tag != recipe.name and not any(tag in names for names in categories.values()):
                categories[kind_of(tag, self.preparations)].append(tag)
        return {
            "id": recipe.id, "name": recipe.name, "category": recipe.category,
            "difficulty": recipe.difficulty, "labels": categories,
        }

    def detail(self, recipe):
        return {
            **self.lookup[recipe.id],
            "source": recipe.source, "description": recipe.description, "energy": recipe.energy,
            "materials_text": recipe.materials_text, "requirements": [asdict(group) for group in recipe.requirements],
            "sections": recipe.sections,
        }

    def pantry(self, ingredients, preparation_ids):
        selected = set(ingredients) | {
            self.recipes[recipe_id].name for recipe_id in preparation_ids
            if recipe_id in self.recipes and self.recipes[recipe_id].category == "配料"
        }
        return selected, expand(selected, self.rules)

    def check(self, requirements, selected, covered, excluded):
        missing = []
        blocked = []
        direct = 0
        matched = 0
        available_supplies = 0
        ingredient_groups = 0
        for group in requirements:
            options = group.options
            direct_match = any(item.kind != "tool" and item.name in selected for item in options)
            ingredient_match = any(item.kind != "tool" and item.name in covered for item in options)
            supply_match = any(item.kind != "ingredient" and item.name not in excluded[item.kind] for item in options)
            direct += direct_match
            matched += ingredient_match
            available_supplies += supply_match
            if group.optional:
                continue
            ingredient_groups += any(item.kind == "ingredient" for item in options)
            if ingredient_match or supply_match:
                continue
            names = " / ".join(item.name for item in options)
            if any(item.kind == "ingredient" for item in options):
                missing.append(names)
            else:
                blocked.append(names)
        return missing, blocked, direct, matched, available_supplies, ingredient_groups

    def best_method(self, recipe, selected, covered, excluded):
        methods = recipe.variants or (recipe.requirements,)
        candidates = [(method, self.check(method, selected, covered, excluded)) for method in methods]
        return max(candidates, key=lambda candidate: (
            not candidate[1][1], -len(candidate[1][0]), candidate[1][2], candidate[1][3]
        ))

    def dishes_for_filters(self, levels, categories):
        return (recipe for recipe in self.dishes if recipe.difficulty in levels
                and (categories is None or recipe.category in categories))

    def recommendations(self, difficulties, previous_ids, *, categories=None, seasonings=(), tools=()):
        levels = set(difficulties)
        allowed = None if categories is None else set(categories)
        excluded = {"seasoning": set(seasonings), "tool": set(tools)}
        candidates = self.dishes_for_filters(levels, allowed)
        if any(excluded.values()):
            empty_pantry = set()
            candidates = (recipe for recipe in candidates
                          if not self.best_method(recipe, empty_pantry, empty_pantry, excluded)[1][1])
        previous = set(previous_ids)
        matches = [recipe.id for recipe in candidates]
        fresh = [recipe_id for recipe_id in matches if recipe_id not in previous]
        picked = sample(fresh, min(5, len(fresh)))
        if len(picked) < 5:
            repeats = [recipe_id for recipe_id in matches if recipe_id in previous]
            picked.extend(sample(repeats, min(5 - len(picked), len(repeats))))
        return [self.lookup[recipe_id] for recipe_id in picked]

    def find_recipes(self, query):
        terms = normalize("NFKC", query).casefold().split()
        if not terms:
            return []
        phrase = "".join(terms)
        matches = []
        for recipe in self.dishes:
            name = normalize("NFKC", recipe.name).casefold()
            if all(term in name for term in terms):
                rank = (name != phrase, not name.startswith(phrase), len(name))
                matches.append((rank, self.lookup[recipe.id]))
        return [recipe for _, recipe in sorted(matches, key=lambda match: match[0])]

    def search(self, ingredients, seasonings, tools, difficulties, preparation_ids, *, categories=None):
        selected, covered = self.pantry(ingredients, preparation_ids)
        excluded = {"seasoning": set(seasonings), "tool": set(tools)}
        levels = set(difficulties)
        allowed = None if categories is None else set(categories)
        if not selected and not any(excluded.values()) and levels == set(range(1, 6)) and allowed is None:
            return {"ready": [], "related": []}
        ready, related = [], []
        for recipe in self.dishes_for_filters(levels, allowed):
            _, (missing, blocked, direct, matched, supplies, groups) = self.best_method(recipe, selected, covered, excluded)
            if blocked:
                continue
            if not selected:
                # Ingredient availability is unspecified when browsing by other filters.
                ready.append(((-recipe.difficulty,), {**self.lookup[recipe.id], "missing": []}))
                continue
            all_labels = set(self.lookup[recipe.id]["labels"]["ingredient"])
            linked = len((all_labels | self.related_terms[recipe.id]) & covered)
            rank = (matched / max(1, groups), direct, matched, linked, supplies, -len(missing), -recipe.difficulty)
            item = {**self.lookup[recipe.id], "missing": missing}
            if not missing and (matched or linked):
                ready.append((rank, item))
            elif matched or linked:
                related.append((rank, item))
        return {
            "ready": [item for _, item in sorted(ready, key=lambda row: row[0], reverse=True)],
            "related": [item for _, item in sorted(related, key=lambda row: row[0], reverse=True)],
        }

    def shopping(self, ids, ingredients, seasonings, tools, *, include_missing=False):
        selected, covered = self.pantry(ingredients, ids)
        excluded = {"seasoning": set(seasonings), "tool": set(tools)}
        selected_preparations = {name for name, recipe_id in self.preparations.items() if recipe_id in ids}
        merged = {kind: {} for kind in KINDS}
        for recipe_id in dict.fromkeys(ids):
            recipe = self.recipes[recipe_id]
            requirements, _ = self.best_method(recipe, selected, covered, excluded)
            for group in requirements:
                if group.optional:
                    continue
                chosen = next((item for item in group.options if item.kind == "ingredient" and item.name in selected), None)
                if chosen is None:
                    chosen = next((item for item in group.options if (
                        item.name in covered if item.kind == "ingredient" else item.name not in excluded[item.kind]
                    )), group.options[0])
                if chosen.name in selected_preparations:
                    continue
                name, kind, grams = chosen.name, chosen.kind, chosen.grams
                amounts = merged[kind]
                previous = amounts.get(name)
                if previous is None:
                    amounts[name] = {"name": name, "grams": grams}
                    if chosen.quantity:
                        amounts[name]["quantity"] = chosen.quantity
                    if chosen.approximate:
                        amounts[name]["approximate"] = True
                    continue
                earlier_grams = previous["grams"]
                previous["grams"] = round(earlier_grams + grams, 5) if earlier_grams is not None and grams is not None else None
                previous.pop("quantity", None)
                if previous["grams"] is None:
                    previous.pop("approximate", None)
                elif chosen.approximate:
                    previous["approximate"] = True
        items = {kind: list(amounts.values()) for kind, amounts in merged.items()}
        if include_missing:
            items["missing"] = {
                "ingredient": [item for item in items["ingredient"] if item["name"] not in covered],
                "seasoning": [item for item in items["seasoning"]
                              if item["name"] in excluded["seasoning"] and item["name"] not in covered],
                "tool": [item for item in items["tool"] if item["name"] in excluded["tool"]],
            }
        return items

    def floating_labels(self):
        dishes = {recipe.name for recipe in self.dishes}
        labels = {
            kind: [entry["name"] for entry in self.facets[kind]
                   if entry["name"] not in dishes | AVAILABILITY_STOP and len(entry["name"]) <= 8][:120]
            for kind in KINDS[:2]
        }
        return {**labels, "dish": sorted(name for name in dishes if len(name) <= 9)}
