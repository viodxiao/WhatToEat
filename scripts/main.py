import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

if __package__ in (None, ""):
    # 直接运行 scripts/main.py（IDE 的 Run 按钮）时没有父包，相对导入会失败。
    # 把仓库根加进 sys.path 并补上包名，使脚本方式与 `-m uvicorn` 方式都能启动。
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "scripts"

from .llm_client import Client
from .planner import Planner
from .recipe_data import RECIPE_DIR, canonical, load_catalog


FRONTEND = Path(__file__).resolve().parent / "frontend"
Stars = Annotated[int, Field(ge=1, le=5)]
Names = Annotated[list[str], Field(max_length=1000)]


class Pantry(BaseModel):
    ingredients: Names = Field(default_factory=list)
    seasonings: Names = Field(default_factory=list)
    tools: Names = Field(default_factory=list)

    def choices(self):
        return [[canonical(name) for name in names] for names in (self.ingredients, self.seasonings, self.tools)]


class Filters(Pantry):
    difficulties: list[Stars] = Field(default_factory=lambda: [1, 2, 3, 4, 5], max_length=5)
    preparation_ids: Names = Field(default_factory=list)
    categories: Names | None = None


class Basket(Pantry):
    ids: Names = Field(default_factory=list)
    include_missing: bool = False


class RecommendationRequest(BaseModel):
    difficulties: list[Stars] = Field(max_length=5)
    previous_ids: list[str] = Field(default_factory=list, max_length=5)
    seasonings: Names = Field(default_factory=list)
    tools: Names = Field(default_factory=list)
    categories: Names | None = None


@asynccontextmanager
async def lifespan(app):
    app.state.planner = Planner(*load_catalog())
    app.state.recipe_categories = sorted(path.name for path in RECIPE_DIR.iterdir()
                                         if path.is_dir() and path.name != "配料")
    # 启动时读一次模型配置（环境变量优先，其次项目根目录 llm.local.json）
    app.state.llm_client = Client.load()
    yield


app = FastAPI(title="今天吃什么？", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/catalog")
def catalog(request: Request):
    planner = request.app.state.planner
    return {
        "facets": planner.facets, "floating": planner.floating_labels(), "dish_count": len(planner.dishes),
        "categories": request.app.state.recipe_categories,
        "recipe_index": [{"id": recipe.id, "name": recipe.name, "category": recipe.category}
                         for recipe in planner.recipes.values()],
    }


@app.post("/api/search")
def search(filters: Filters, request: Request):
    return request.app.state.planner.search(
        *filters.choices(), filters.difficulties, filters.preparation_ids, categories=filters.categories,
    )


@app.post("/api/recommendations")
def recommendations(filters: RecommendationRequest, request: Request):
    return request.app.state.planner.recommendations(
        filters.difficulties, filters.previous_ids, categories=filters.categories,
        seasonings=[canonical(name) for name in filters.seasonings],
        tools=[canonical(name) for name in filters.tools],
    )


@app.get("/api/recipes")
def find_recipes(request: Request, q: str = Query(max_length=100)):
    return request.app.state.planner.find_recipes(q)


@app.get("/api/recipe")
def recipe(request: Request, recipe_id: str = Query(alias="id")):
    planner = request.app.state.planner
    record = planner.recipes.get(recipe_id)
    if record is None:
        raise HTTPException(404, "找不到该菜谱")
    return planner.detail(record)


@app.get("/api/random")
def random_recipe(request: Request):
    planner = request.app.state.planner
    return planner.detail(random.choice(planner.dishes))


@app.post("/api/shopping")
def shopping(basket: Basket, request: Request):
    planner = request.app.state.planner
    if any(recipe_id not in planner.recipes for recipe_id in basket.ids):
        raise HTTPException(404, "选中的菜谱不存在")
    return planner.shopping(basket.ids, *basket.choices(), include_missing=basket.include_missing)


class NaturalLanguageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    use_ontology: bool = True


@app.post('/api/parse')
def parse_natural_language(body: NaturalLanguageRequest, request: Request):
    from .agent import parse_request
    from .llm_client import Client, LLMError
    from .nl_query import ontology_view
    client = getattr(request.app.state, 'llm_client', None) or Client.load()
    if not client.configured:
        raise HTTPException(503, '请配置 WTE_LLM_BASE_URL、WTE_LLM_API_KEY、WTE_LLM_MODEL，'
                                 '或填写项目根目录的 llm.local.json')
    try:
        planner = request.app.state.planner
        return parse_request(body.text, planner, ontology_view(planner), client,
                             use_ontology=body.use_ontology)
    except ValueError:
        raise HTTPException(422, '模型返回的搜索参数不合法，请重新描述需求') from None
    except LLMError:
        raise HTTPException(502, '模型调用或响应解析失败，请检查服务配置') from None


if __name__ == "__main__":
    # 供直接运行本文件时启动服务；用 `-m uvicorn scripts.main:app` 启动时不会走到这里。
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
