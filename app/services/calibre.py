import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class CalibreError(Exception):
    pass


class CalibreNotFoundError(CalibreError):
    pass


@dataclass
class Recipe:
    name: str
    title: str
    language: str | None = None
    description: str | None = None


class CalibreWrapper:
    EBOOK_CONVERT = "ebook-convert"

    def __init__(self, output_dir: Path | None = None, timeout: int = 600):
        self.output_dir = output_dir or settings.epub_dir
        self.timeout = timeout
        self._recipe_cache: list[Recipe] | None = None

    async def verify_installation(self) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.EBOOK_CONVERT,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            version = stdout.decode().strip().split("\n")[0]
            logger.info(f"Calibre version: {version}")
            return version
        except FileNotFoundError:
            raise CalibreNotFoundError("Calibre not found. Is it installed?")
        except asyncio.TimeoutError:
            raise CalibreError("Calibre version check timed out")

    async def list_builtin_recipes(self, force_refresh: bool = False) -> list[Recipe]:
        if self._recipe_cache is not None and not force_refresh:
            return self._recipe_cache

        try:
            proc = await asyncio.create_subprocess_exec(
                self.EBOOK_CONVERT,
                "--list-recipes",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise CalibreError(f"Failed to list recipes: {error_msg}")

            recipes = self._parse_recipe_list(stdout.decode())
            self._recipe_cache = recipes
            logger.info(f"Loaded {len(recipes)} Calibre recipes")
            return recipes

        except asyncio.TimeoutError:
            raise CalibreError("Recipe listing timed out")

    def _parse_recipe_list(self, output: str) -> list[Recipe]:
        recipes = []
        current_lang = None

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            lang_match = re.match(r"^(\w{2,3})(?:\s|$)", line)
            if lang_match and len(line) <= 10:
                current_lang = lang_match.group(1).lower()
                continue

            recipe_match = re.match(r"^(.+?)\s*(?:\[(.+?)\])?\s*$", line)
            if recipe_match:
                title = recipe_match.group(1).strip()
                name = self._title_to_name(title)
                if name:
                    recipes.append(
                        Recipe(
                            name=name,
                            title=title,
                            language=current_lang,
                        )
                    )

        return recipes

    def _title_to_name(self, title: str) -> str:
        name = re.sub(r"[^\w\s-]", "", title)
        name = re.sub(r"\s+", "_", name.strip())
        return name.lower()

    async def fetch_recipe(
        self,
        recipe_name: str,
        output_path: Path,
        max_articles: int = 25,
        oldest_days: int = 7,
        include_images: bool = True,
    ) -> Path:
        # Phase 2 implementation
        raise NotImplementedError("fetch_recipe will be implemented in Phase 2")

    async def fetch_rss(
        self,
        feed_url: str,
        title: str,
        output_path: Path,
        max_articles: int = 25,
        oldest_days: int = 7,
    ) -> Path:
        # Phase 2 implementation
        raise NotImplementedError("fetch_rss will be implemented in Phase 2")


calibre = CalibreWrapper()
