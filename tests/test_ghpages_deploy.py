"""Tests for utils/ghpages_deploy — URL derivation and local static copy."""

from utils.ghpages_deploy import derive_pages_urls, derive_static_urls, _stage_local_copy


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

    def test_nested_time_subdirectory(self):
        """date_str 含时间子目录 → 同一天每轮唯一 URL。"""
        urls = derive_pages_urls("https://github.com/KKKKupor/redbook_agent.git", "2026-08-25/103000")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-25/103000/"
        assert urls["cover_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-25/103000/cover.png"
        assert urls["result_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-25/103000/result.png"
        assert urls["product_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-25/103000/product.png"


class TestDeriveStaticUrls:
    def test_static_mode_urls(self):
        """DEPLOY_MODE=static:URL 基于 PUBLIC_BASE_URL + /quiz/d/{date}/。"""
        urls = derive_static_urls("https://quiz.example.com", "2026-08-25/103000")
        assert urls["html_url"] == "https://quiz.example.com/quiz/d/2026-08-25/103000/"
        assert urls["cover_image_url"] == "https://quiz.example.com/quiz/d/2026-08-25/103000/cover.png"

    def test_missing_base_or_date_returns_empty(self):
        assert derive_static_urls("", "2026-08-25/103000")["html_url"] == ""
        assert derive_static_urls("https://quiz.example.com", "")["html_url"] == ""


class TestStageLocalCopy:
    def test_copies_existing_files_to_nested_day_dir(self, tmp_path, monkeypatch):
        import utils.ghpages_deploy as ghd

        monkeypatch.setattr(ghd, "REPO_ROOT", tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        (src / "index.html").write_text("<html>x</html>", encoding="utf-8")
        (src / "cover.png").write_bytes(b"png")
        # result/product 缺失:跳过,不报错
        day = ghd._stage_local_copy(src, "2026-08-25/103000")
        assert (day / "index.html").exists()
        assert (day / "cover.png").exists()
        assert not (day / "result.png").exists()
        assert day == tmp_path / "output" / "deploy" / "d" / "2026-08-25" / "103000"
