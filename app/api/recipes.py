from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import CurrentUser
from app.services import CalibreError, calibre

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


class RecipeResponse(BaseModel):
    name: str
    title: str
    language: str | None
    description: str | None


class RecipeListResponse(BaseModel):
    items: list[RecipeResponse]
    total: int
    page: int
    page_size: int


@router.get("")
async def list_recipes(
    _: CurrentUser,
    search: str | None = Query(None, description="Search by title"),
    language: str | None = Query(None, description="Filter by language code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> RecipeListResponse:
    try:
        all_recipes = await calibre.list_builtin_recipes()
    except CalibreError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    filtered = all_recipes

    if search:
        search_lower = search.lower()
        filtered = [r for r in filtered if search_lower in r.title.lower()]

    if language:
        filtered = [r for r in filtered if r.language == language.lower()]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = filtered[start:end]

    return RecipeListResponse(
        items=[
            RecipeResponse(
                name=r.name,
                title=r.title,
                language=r.language,
                description=r.description,
            )
            for r in paginated
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{recipe_name}")
async def get_recipe(
    recipe_name: str,
    _: CurrentUser,
) -> RecipeResponse:
    try:
        all_recipes = await calibre.list_builtin_recipes()
    except CalibreError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    recipe = next((r for r in all_recipes if r.name == recipe_name), None)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    return RecipeResponse(
        name=recipe.name,
        title=recipe.title,
        language=recipe.language,
        description=recipe.description,
    )


@router.post("/refresh")
async def refresh_recipes(_: CurrentUser) -> dict:
    try:
        recipes = await calibre.list_builtin_recipes(force_refresh=True)
        return {"message": "Recipes refreshed", "count": len(recipes)}
    except CalibreError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
