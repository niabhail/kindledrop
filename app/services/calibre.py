import asyncio
import hashlib
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
        """
        Execute a Calibre built-in recipe and generate EPUB.

        Args:
            recipe_name: Name of built-in Calibre recipe (e.g., "the_guardian")
            output_path: Where to save the generated EPUB
            max_articles: Maximum articles per feed
            oldest_days: Ignore articles older than this many days
            include_images: Whether to download and embed images

        Returns:
            Path to generated EPUB

        Raises:
            CalibreError: If recipe execution fails
        """
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build command
        cmd = [
            self.EBOOK_CONVERT,
            f"{recipe_name}.recipe",
            str(output_path),
            f"--max-articles-per-feed={max_articles}",
            f"--oldest-article={oldest_days}",
            "--output-profile=kindle",
        ]

        if not include_images:
            cmd.append("--dont-download-recipe")

        logger.info(f"Running Calibre: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                # Extract useful part of error message
                error_lines = [
                    line for line in error_msg.split("\n") if line.strip()
                ]
                short_error = error_lines[-1] if error_lines else error_msg
                raise CalibreError(
                    f"Recipe '{recipe_name}' failed: {short_error}"
                )

            # Validate output
            if not output_path.exists():
                raise CalibreError(
                    f"Recipe '{recipe_name}' produced no output file"
                )

            if output_path.stat().st_size == 0:
                output_path.unlink()  # Clean up empty file
                raise CalibreError(
                    f"Recipe '{recipe_name}' produced empty file"
                )

            logger.info(
                f"Generated EPUB: {output_path} "
                f"({output_path.stat().st_size / 1024:.1f} KB)"
            )
            return output_path

        except asyncio.TimeoutError:
            raise CalibreError(
                f"Recipe '{recipe_name}' timed out after {self.timeout}s"
            )

    async def fetch_rss(
        self,
        feed_url: str,
        title: str,
        output_path: Path,
        max_articles: int = 25,
        oldest_days: int = 7,
        include_images: bool = True,
    ) -> Path:
        """
        Fetch RSS feed and generate EPUB using a custom Calibre recipe.

        Creates a temporary recipe file for the RSS feed, runs it through
        Calibre, then cleans up.

        Args:
            feed_url: URL of the RSS feed
            title: Title for the generated ebook
            output_path: Where to save the generated EPUB
            max_articles: Maximum articles to fetch
            oldest_days: Ignore articles older than this many days
            include_images: Whether to download and embed images

        Returns:
            Path to generated EPUB

        Raises:
            CalibreError: If fetching or conversion fails
        """
        # Escape single quotes in title and URL for Python recipe
        safe_title = title.replace("'", "\\'")
        safe_url = feed_url.replace("'", "\\'")

        # Generate a custom recipe for this RSS feed
        recipe_content = f"""
from calibre.web.feeds.news import BasicNewsRecipe

class CustomRSSRecipe(BasicNewsRecipe):
    title = '{safe_title}'
    oldest_article = {oldest_days}
    max_articles_per_feed = {max_articles}
    auto_cleanup = True
    no_stylesheets = True

    feeds = [
        ('{safe_title}', '{safe_url}'),
    ]
"""

        # Create temp recipe file with unique name based on URL hash
        url_hash = hashlib.md5(feed_url.encode()).hexdigest()[:8]
        recipe_path = self.output_dir / f"rss_{url_hash}.recipe"

        try:
            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Write recipe file
            recipe_path.write_text(recipe_content)
            logger.debug(f"Created temp recipe: {recipe_path}")

            # Run the recipe (pass the full path, not .recipe suffix)
            # Calibre accepts recipe file paths directly
            return await self._run_recipe_file(
                recipe_path=recipe_path,
                output_path=output_path,
                include_images=include_images,
                feed_title=title,
            )

        finally:
            # Clean up temp recipe file
            if recipe_path.exists():
                recipe_path.unlink()
                logger.debug(f"Cleaned up temp recipe: {recipe_path}")

    async def _run_recipe_file(
        self,
        recipe_path: Path,
        output_path: Path,
        include_images: bool = True,
        feed_title: str = "RSS Feed",
    ) -> Path:
        """
        Run a recipe file through Calibre ebook-convert.

        Internal method used by fetch_rss.
        """
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.EBOOK_CONVERT,
            str(recipe_path),
            str(output_path),
            "--output-profile=kindle",
        ]

        if not include_images:
            cmd.append("--dont-download-recipe")

        logger.info(f"Running Calibre RSS: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                error_lines = [
                    line for line in error_msg.split("\n") if line.strip()
                ]
                short_error = error_lines[-1] if error_lines else error_msg
                raise CalibreError(f"RSS feed '{feed_title}' failed: {short_error}")

            # Validate output
            if not output_path.exists():
                raise CalibreError(
                    f"RSS feed '{feed_title}' produced no output file"
                )

            if output_path.stat().st_size == 0:
                output_path.unlink()
                raise CalibreError(
                    f"RSS feed '{feed_title}' produced empty file"
                )

            logger.info(
                f"Generated EPUB: {output_path} "
                f"({output_path.stat().st_size / 1024:.1f} KB)"
            )
            return output_path

        except asyncio.TimeoutError:
            raise CalibreError(
                f"RSS feed '{feed_title}' timed out after {self.timeout}s"
            )


calibre = CalibreWrapper()
