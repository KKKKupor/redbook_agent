"""Regression tests for utils.git_ops auto_commit — sensitive paths must never be committed."""

import subprocess
from pathlib import Path

from utils.git_ops import GitOps


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "init"], check=True)


def _committed_paths(root: Path) -> set:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    return set(out.split())


def test_auto_commit_excludes_sensitive_and_ignored(tmp_path, monkeypatch):
    # 独立 scratch 仓库,不影响主仓库
    repo_root = tmp_path / "scratch"
    repo_root.mkdir()
    _init_repo(repo_root)
    (repo_root / ".gitignore").write_text("ignored_dir/\n*.log\n", encoding="utf-8")
    (repo_root / "safe.txt").write_text("safe", encoding="utf-8")
    (repo_root / ".env").write_text("SECRET=1", encoding="utf-8")
    (repo_root / "data").mkdir()
    (repo_root / "data" / "cookies.json").write_text("{}", encoding="utf-8")
    (repo_root / "ignored_dir").mkdir()
    (repo_root / "ignored_dir" / "x.txt").write_text("x", encoding="utf-8")

    ops = GitOps(str(repo_root))
    ops.exclude_paths = [".env", "__pycache__", "data"]
    commit_hash = ops.auto_commit()

    assert commit_hash, "commit should succeed"
    paths = _committed_paths(repo_root)
    assert "safe.txt" in paths
    assert ".env" not in paths
    assert "data/cookies.json" not in paths
    assert "ignored_dir/x.txt" not in paths
    assert not any(p.startswith(".git/") for p in paths)


def test_no_changes_returns_empty(tmp_path, monkeypatch):
    repo_root = tmp_path / "empty"
    repo_root.mkdir()
    _init_repo(repo_root)
    ops = GitOps(str(repo_root))
    assert ops.auto_commit() == ""
