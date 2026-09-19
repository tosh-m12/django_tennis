"""Public discovery must never publish member or management URLs."""
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from tennis_project.middleware import SearchIndexingMiddleware


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ORIGIN_VERIFY_ENABLED=False,
    CANONICAL_HOST="",
    TURNSTILE_ENABLED=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class SearchDiscoveryTests(SimpleTestCase):
    def test_home_metadata_and_existing_registration_entry(self):
        response = self.client.get("/?utm_source=test")
        self.assertContains(response, "テニスサークルの出欠・対戦表・戦績管理｜DeuceNet")
        self.assertContains(response, 'rel="canonical" href="https://deucenet.app/"', count=1)
        self.assertContains(response, 'name="google-site-verification"', count=1)
        self.assertContains(response, "デュースネット")
        self.assertContains(response, "サークルを登録")
        self.assertContains(response, "デモを試す")
        self.assertNotIn("X-Robots-Tag", response)

    def test_public_legal_pages_have_their_own_canonical(self):
        for path in ("/privacy/", "/terms/", "/guide/", "/how-to/attendance/", "/how-to/matches/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, f'rel="canonical" href="https://deucenet.app{path}"')
                self.assertNotIn("X-Robots-Tag", response)

    def test_sitemap_lists_only_public_information(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        root = ElementTree.fromstring(response.content)
        locations = [element.text for element in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        self.assertEqual(locations, ["https://deucenet.app/", "https://deucenet.app/privacy/", "https://deucenet.app/terms/", "https://deucenet.app/guide/", "https://deucenet.app/how-to/attendance/", "https://deucenet.app/how-to/matches/"])

    def test_robots_allows_search_and_noindex_observation(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        parser = RobotFileParser()
        parser.parse(response.content.decode().splitlines())
        self.assertEqual(parser.site_maps(), ["https://deucenet.app/sitemap.xml"])
        for bot in ("Googlebot", "Bingbot", "OAI-SearchBot"):
            for path in ("/", "/privacy/", "/terms/", "/guide/", "/how-to/attendance/", "/how-to/matches/", "/sitemap.xml", "/c/test/"):
                self.assertTrue(parser.can_fetch(bot, path), (bot, path))
            self.assertFalse(parser.can_fetch(bot, "/admin/"))

    def test_private_success_redirect_and_errors_are_noindex(self):
        factory = RequestFactory()
        paths = ("/c/test/", "/c/test/admin/secret/", "/c/test/member/1/", "/c/test/event/1/", "/demo", "/verify/test/", "/recover/", "/api/match/save_score/")
        for path in paths:
            for status in (200, 302, 403, 404):
                with self.subTest(path=path, status=status):
                    request = factory.get(path)
                    request.resolver_match = resolve(path)
                    middleware = SearchIndexingMiddleware(lambda request: HttpResponse(status=status))
                    self.assertEqual(middleware(request)["X-Robots-Tag"], "noindex, nofollow")

    def test_error_pages_and_post_responses_are_noindex(self):
        response = self.client.get("/does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        request = RequestFactory().post("/")
        request.resolver_match = resolve("/")
        middleware = SearchIndexingMiddleware(lambda request: HttpResponse())
        self.assertEqual(middleware(request)["X-Robots-Tag"], "noindex, nofollow")

    def test_discovery_endpoints_are_read_only(self):
        for path in ("/robots.txt", "/sitemap.xml"):
            self.assertEqual(self.client.post(path).status_code, 405)
