import asyncio
import hashlib
import logging
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

# Size thresholds for compression (in bytes)
COMPRESSION_THRESHOLD_HIGH = 8 * 1024 * 1024   # 8MB - aggressive compression
COMPRESSION_THRESHOLD_MED = 5 * 1024 * 1024    # 5MB - moderate compression
MAX_EMAIL_SIZE = 11 * 1024 * 1024              # 11MB - Mailjet limit with base64 overhead


def compress_epub_images(
    epub_path: Path,
    quality: int = 60,
    max_size: tuple[int, int] = (800, 1200),
) -> int:
    """
    Compress images in an EPUB file to reduce file size.

    EPUB is a ZIP file containing HTML and images. This function:
    1. Extracts the EPUB
    2. Compresses each image with Pillow (lossy JPEG)
    3. Repacks the EPUB

    Args:
        epub_path: Path to the EPUB file (modified in-place)
        quality: JPEG quality (1-100, lower = smaller file)
        max_size: Maximum image dimensions (width, height)

    Returns:
        Bytes saved by compression
    """
    # Read all files from EPUB
    with zipfile.ZipFile(epub_path, "r") as zin:
        items = {name: zin.read(name) for name in zin.namelist()}

    bytes_saved = 0
    images_processed = 0

    for name, data in list(items.items()):
        lower_name = name.lower()
        if lower_name.endswith((".jpg", ".jpeg", ".png", ".gif")):
            try:
                original_size = len(data)
                img = Image.open(BytesIO(data))

                # Resize if larger than max dimensions
                img.thumbnail(max_size, Image.Resampling.LANCZOS)

                # Convert to RGB if necessary (for JPEG output)
                if img.mode in ("RGBA", "P", "LA"):
                    # Create white background for transparent images
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                # Compress to JPEG
                output = BytesIO()
                img.save(output, "JPEG", quality=quality, optimize=True)
                compressed_data = output.getvalue()

                # Only use compressed version if smaller
                if len(compressed_data) < original_size:
                    # Update filename to .jpg if it was different
                    new_name = name.rsplit(".", 1)[0] + ".jpg"
                    if new_name != name:
                        del items[name]
                    items[new_name] = compressed_data
                    bytes_saved += original_size - len(compressed_data)
                    images_processed += 1

            except Exception as e:
                logger.warning(f"Failed to compress image {name}: {e}")
                continue

    # Repack EPUB with compressed images
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in items.items():
            zout.writestr(name, data)

    if images_processed > 0:
        logger.info(
            f"Compressed {images_processed} images, saved {bytes_saved / 1024:.1f} KB"
        )

    return bytes_saved


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

        # Look up the original title from cache (Calibre needs exact title, not slug)
        recipe_title = recipe_name  # Default to what was passed
        if self._recipe_cache:
            for r in self._recipe_cache:
                if r.name == recipe_name:
                    recipe_title = r.title
                    break
        else:
            # Try to load recipes if cache is empty
            try:
                recipes = await self.list_builtin_recipes()
                for r in recipes:
                    if r.name == recipe_name:
                        recipe_title = r.title
                        break
            except Exception:
                pass  # Fall back to using recipe_name as-is

        # Build command
        # Note: Built-in recipes don't universally support --recipe-specific-option
        # Those options only work if the recipe explicitly defines recipe_specific_options
        # For built-in recipes, we just use their defaults
        cmd = [
            self.EBOOK_CONVERT,
            f"{recipe_title}.recipe",
            str(output_path),
            # kindle_scribe profile works for Kindle Colorsoft (1264x1680 @ 300ppi)
            "--output-profile=kindle_scribe",
            # Brand as Kindledrop so user knows the source on their Kindle
            "--publisher=Kindledrop",
            "--authors=Kindledrop",
        ]

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

            file_size = output_path.stat().st_size
            logger.info(
                f"Generated EPUB: {output_path} ({file_size / 1024:.1f} KB)"
            )

            # Compress images if file is too large for email
            if file_size > COMPRESSION_THRESHOLD_MED:
                if file_size > COMPRESSION_THRESHOLD_HIGH:
                    # Aggressive compression for very large files
                    quality, max_dims = 50, (600, 900)
                else:
                    # Moderate compression
                    quality, max_dims = 70, (800, 1200)

                logger.info(
                    f"File size {file_size / 1024 / 1024:.1f}MB exceeds threshold, "
                    f"compressing with quality={quality}"
                )
                compress_epub_images(output_path, quality=quality, max_size=max_dims)

                new_size = output_path.stat().st_size
                logger.info(
                    f"After compression: {new_size / 1024:.1f} KB "
                    f"(reduced {(file_size - new_size) / 1024:.1f} KB)"
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

        # Generate a custom recipe for this RSS feed with compression settings
        recipe_content = f"""
from calibre.web.feeds.news import BasicNewsRecipe

class CustomRSSRecipe(BasicNewsRecipe):
    title = '{safe_title}'
    oldest_article = {oldest_days}
    max_articles_per_feed = {max_articles}
    auto_cleanup = True
    no_stylesheets = True

    # Image compression to reduce file size for email delivery
    compress_news_images = True
    compress_news_images_max_size = 100  # Max 100KB per image
    scale_news_images = (800, 1200)      # Max dimensions

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
            # kindle_scribe profile works for Kindle Colorsoft
            "--output-profile=kindle_scribe",
            # Brand as Kindledrop so user knows the source on their Kindle
            "--publisher=Kindledrop",
            "--authors=Kindledrop",
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

            file_size = output_path.stat().st_size
            logger.info(
                f"Generated EPUB: {output_path} ({file_size / 1024:.1f} KB)"
            )

            # Compress images if file is too large for email
            if file_size > COMPRESSION_THRESHOLD_MED:
                if file_size > COMPRESSION_THRESHOLD_HIGH:
                    quality, max_dims = 50, (600, 900)
                else:
                    quality, max_dims = 70, (800, 1200)

                logger.info(
                    f"File size {file_size / 1024 / 1024:.1f}MB exceeds threshold, "
                    f"compressing with quality={quality}"
                )
                compress_epub_images(output_path, quality=quality, max_size=max_dims)

                new_size = output_path.stat().st_size
                logger.info(
                    f"After compression: {new_size / 1024:.1f} KB "
                    f"(reduced {(file_size - new_size) / 1024:.1f} KB)"
                )

            return output_path

        except asyncio.TimeoutError:
            raise CalibreError(
                f"RSS feed '{feed_title}' timed out after {self.timeout}s"
            )


calibre = CalibreWrapper()
