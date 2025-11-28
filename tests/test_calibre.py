
from app.services.calibre import CalibreWrapper, Recipe


class TestCalibreWrapper:
    def test_title_to_name_basic(self):
        wrapper = CalibreWrapper()
        assert wrapper._title_to_name("The Guardian") == "the_guardian"

    def test_title_to_name_special_chars(self):
        wrapper = CalibreWrapper()
        assert wrapper._title_to_name("The New York Times") == "the_new_york_times"
        assert wrapper._title_to_name("BBC News (UK)") == "bbc_news_uk"

    def test_parse_recipe_list_basic(self):
        wrapper = CalibreWrapper()
        output = """en
The Guardian
The New York Times
de
Der Spiegel
"""
        recipes = wrapper._parse_recipe_list(output)
        assert len(recipes) == 3
        assert recipes[0].title == "The Guardian"
        assert recipes[0].language == "en"
        assert recipes[1].title == "The New York Times"
        assert recipes[1].language == "en"
        assert recipes[2].title == "Der Spiegel"
        assert recipes[2].language == "de"

    def test_recipe_cache_returns_cached(self):
        wrapper = CalibreWrapper()
        cached = [Recipe(name="test", title="Test")]
        wrapper._recipe_cache = cached

        # This should return cached without calling list
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wrapper.list_builtin_recipes(force_refresh=False)
        )
        assert result == cached
