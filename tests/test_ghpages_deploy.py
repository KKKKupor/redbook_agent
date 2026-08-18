"""Tests for utils/ghpages_deploy.derive_pages_urls — pure URL derivation."""

from utils.ghpages_deploy import derive_pages_urls


class TestDerivePagesUrls:
    def test_https_remote_with_git_suffix(self):
        urls = derive_pages_urls("https://github.com/KKKKupor/redbook_agent.git", "2026-08-18")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/"
        assert urls["cover_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/cover.png"
        assert urls["result_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/result.png"
        assert urls["product_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/product.png"

    def test_https_remote_without_git_suffix(self):
        urls = derive_pages_urls("https://github.com/KKKKupor/redbook_agent", "2026-08-19")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-19/"

    def test_ssh_remote(self):
        urls = derive_pages_urls("git@github.com:KKKKupor/redbook_agent.git", "2026-08-18")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/"

    def test_empty_remote_returns_empty(self):
        assert derive_pages_urls("", "2026-08-18") == {
            "html_url": "",
            "cover_image_url": "",
            "result_image_url": "",
            "product_image_url": "",
        }

    def test_unparseable_remote_returns_empty(self):
        assert derive_pages_urls("not-a-remote", "2026-08-18")["html_url"] == ""
        assert derive_pages_urls("https://example.com/a/b.git", "2026-08-18")["html_url"] == ""

    def test_missing_date_returns_empty(self):
        assert derive_pages_urls("https://github.com/KKKKupor/redbook_agent.git", "")["html_url"] == ""
