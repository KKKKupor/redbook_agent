"""Git auto-commit wrapper for self-healing workflow."""

import os
from datetime import datetime
from pathlib import Path

from git import Repo, GitCommandError
from loguru import logger


class GitOps:
    """Safe Git operations for the self-healing agent."""

    def __init__(self, repo_path: str = "."):
        self.repo = Repo(repo_path)
        self.exclude_paths = os.getenv(
            "GIT_COMMIT_EXCLUDE_PATHS", ".env,__pycache__,data/"
        ).split(",")

    def auto_commit(self, message: str = "") -> str:
        """Stage all safe files and commit. Returns commit hash or empty string."""
        try:
            # Stage only safe paths — porcelain git add 遵守 .gitignore
            # (GitPython index.add(force=True) 会无视 gitignore,连带提交 .env/data/.git)
            for item in Path(self.repo.working_dir).iterdir():
                name = item.name
                if name == ".git":
                    continue
                if any(ex.strip("/") == name for ex in self.exclude_paths):
                    continue
                try:
                    self.repo.git.add(str(item))
                except GitCommandError:
                    # 被 .gitignore 忽略的路径 git add 会以非零码退出 — 跳过,不中断整体提交
                    logger.debug(f"git add skipped (ignored): {name}")

            if not self.repo.index.diff("HEAD"):
                logger.info("No changes to commit")
                return ""

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = message or f"🤖 Auto-commit before healing: {timestamp}"
            commit = self.repo.index.commit(commit_msg)
            logger.info(f"Committed: {commit.hexsha[:12]}")
            return commit.hexsha

        except GitCommandError as e:
            logger.error(f"Git commit failed: {e}")
            return ""


# Singleton
git_ops = GitOps()
