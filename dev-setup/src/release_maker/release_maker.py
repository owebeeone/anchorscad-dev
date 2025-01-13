"""
Reads a set of pyproject.toml files and bumps the version number.

Version numbers are of the format X.Y.Z where X, Y and Z are integers.

X is the major version number (the most significant version number)
Y is the minor version number (the middle significant version number)
Z is the patch version number (the least significant version number)


When a level is bumped, all levels below it are reset to 0. e.g. if the
current version is 1.2.3 and the minor level is bumped, the new version
will be 1.3.0. Similarly, if the major level is bumped, the new version
will be 2.0.0 or if the patch level is bumped, the new version will be 1.2.4.

The pyproject.toml are edited in place.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
import tomli
import tomli_w
import os
import sys

from git import Repo, InvalidGitRepositoryError

VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

def bump_version(version: str, bump_level: str) -> str:
    """
    Bumps the version number by the specified level.

    Args:
        version: Version string in format "X.Y.Z" where X, Y, Z are integers
        bump_level: One of "major", "minor", or "patch"

    Raises:
        ValueError: If version string is invalid or bump_level is not recognized
    """

    match = VERSION_PATTERN.match(version)

    if not match:
        raise ValueError(
            f"Invalid version format: {version}. "
            "Expected format: X.Y.Z where X, Y, Z are integers"
        )

    major, minor, patch = map(int, match.groups())

    if bump_level == "major":
        return f"{major + 1}.0.0"
    elif bump_level == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"Invalid bump level: {bump_level}. Must be one of: major, minor, patch")

def tag_to_version(tag: str) -> str:
    """Converts a git version tag to a version string."""
    match = TAG_PATTERN.match(tag)
    
    if not match:
        raise ValueError(
            f"Invalid tag format: {tag}. "
            "Expected format: vX.Y.Z where X, Y, Z are integers"
        )

    major, minor, patch = map(int, match.groups())

    return f"{major}.{minor}.{patch}"

@dataclass
class VersionBumpResult:
    file_path: Path
    toml_result: dict[str, Any]
    old_version: str
    new_version: str
    git_repo: Path | None
    all_tags: set[str] | None
    fetched_tags: list[str] | None

    def get_relative_path(self, root: Path) -> str:
        """Returns the directory name of the file relative to the directory "root".
        If the directory is not a subdirectory of "root", the full path is returned."""
        try:
            return self.file_path.relative_to(root).parent
        except ValueError:
            return str(self.file_path)
        
    def new_version_tag_already_exists(self) -> bool:
        """Returns True if the *new* version tag already exists in the repository."""
        return self.all_tags and f"v{self.new_version}" in self.all_tags

    def old_version_tag_already_exists(self) -> bool:
        """Returns True if the *old* version tag already exists in the repository."""
        return self.all_tags and f"v{self.old_version}" in self.all_tags


def fetch_and_get_fetched_tags(repo_path: Path, verbose: bool) -> list[str]:
    """
    Fetches remote tags and returns a list of fetched tag names.

    Args:
      repo_path (str): Path to the Git repository.

    Returns:
      list: A list of fetched tag names.

    Raises:
      Exception: If an error occurs during tag fetching.
    """
    try:
        repo = Repo(repo_path)
        # Store the current set of local tags
        original_local_tags = set(tag.name for tag in repo.tags)
        if verbose:
            print(f"Original local tags for {repo_path}: {sorted(original_local_tags)}")

        repo.git.fetch("--tags")  # Fetch all remote tags

        # Get the updated set of local tags
        updated_local_tags = set(tag.name for tag in repo.tags)
        if verbose:
            print(f"Updated local tags for {repo_path}: {sorted(updated_local_tags)}")  

        # Determine the newly fetched tags
        fetched_tags = updated_local_tags - original_local_tags
        if verbose:
            print(f"Fetched tags for {repo_path}: {sorted(fetched_tags)}")

        return (updated_local_tags, list(fetched_tags))

    except Exception as e:
        print(f"Error fetching remote tags for repo: {repo_path}: {e}")
        return []


def apply_version_bump_to_file(
    file: Path, bump_level: str, git_repo: Path | None, fetch_remote_tags: bool, verbose: bool
) -> VersionBumpResult:
    """
    Applies the version bump to the specified file.
    """

    fetched_tags = None
    all_tags = None
    if fetch_remote_tags:
        all_tags, fetched_tags = fetch_and_get_fetched_tags(git_repo, verbose)

    with open(file, "rb") as f:
        toml_result = tomli.load(f)

    project_dir = toml_result.get("project", None)
    if not project_dir:
        raise RuntimeError(f"No project section found in {file}")
    old_version = project_dir.get("version", None)
    if not old_version:
        raise RuntimeError(f"No version found in {file}")
    new_version = bump_version(old_version, bump_level)

    toml_result["project"]["version"] = new_version

    return VersionBumpResult(
        file, toml_result, old_version, new_version, git_repo, all_tags, fetched_tags)


def is_git_repo(path: Path) -> bool:
    """Returns True if the specified path is a git repository."""
    try:
        Repo(path, search_parent_directories=False)
        return True
    except InvalidGitRepositoryError:
        return False


def is_repo_clean(path: Path) -> tuple[bool, str]:
    """
    Checks if the git repository at the given path is clean (no uncommitted changes).
    
    Returns:
        tuple[bool, str]: (is_clean, status_message)
    """
    try:
        repo = Repo(path)
        if repo.is_dirty():
            return False, f"Repository at {path} has uncommitted changes"
        if repo.untracked_files:
            return False, f"Repository at {path} has untracked files: {repo.untracked_files}"
        return True, "clean"
    except InvalidGitRepositoryError:
        return True, "not a git repository"


def apply_version_bump(sources: list[str], bump_level: str, fetch_remote_tags: bool, verbose: bool):
    """
    Applies the version bump to the specified sources atomically. This only applies
    the version bump to the specified sources and returns a list of results
    that can then be written back to the files if desired.
    """

    results: list[VersionBumpResult] = []
    git_repo_stack: list[Path] = [None]

    for source in sources:
        if os.path.isdir(source):
            try:
                if is_git_repo(source):
                    git_repo_stack.append(source)
                source_toml_found_at = None
                file = Path(source) / "pyproject.toml"
                if file.exists():
                    result = apply_version_bump_to_file(
                        file, bump_level, git_repo_stack[-1], fetch_remote_tags, verbose
                    )
                    results.append(result)
                    source_toml_found_at = file
                for top, dirs, _ in os.walk(source):
                    for d in dirs:
                        try:
                            if is_git_repo(Path(top) / d):
                                git_repo_stack.append(Path(top) / d)

                            abs_dir = Path(top) / d
                            file = Path(abs_dir) / "pyproject.toml"
                            if file.exists():
                                if source_toml_found_at:
                                    print(
                                        f"multiple pyproject.toml in {source} ar {source_toml_found_at} and {file}"
                                    )
                                result = apply_version_bump_to_file(
                                    file, bump_level, git_repo_stack[-1], fetch_remote_tags, verbose
                                )
                                results.append(result)
                                source_toml_found_at = file
                        finally:
                            if git_repo_stack:
                                git_repo_stack.pop()
                if not source_toml_found_at:
                    print(f"No pyproject.toml found in {source}", file=sys.stderr)
                    raise RuntimeError(f"No pyproject.toml found in {source}")
            finally:
                if git_repo_stack:
                    git_repo_stack.pop()

    return results


def write_results(results: list[VersionBumpResult]):
    """
    Writes the results back to the files atomically. Either all files are updated or none are.
    """
    temp_files = []
    had_write_errors = False
    
    for result in results:
        is_clean, message = is_repo_clean(result.file_path)
        if not is_clean:
            had_write_errors = True
            print(f"Error: Git repository {str(result.file_path)} is not clean: {message}", file=sys.stderr)

    try:
        # First, try to write all temporary files, reporting any failures
        for result in results:
            temp_file = str(result.file_path) + ".tmp"
            try:
                with open(temp_file, "wb") as f:
                    tomli_w.dump(result.toml_result, f)
                temp_files.append((temp_file, result.file_path))
            except Exception as e:
                print(f"Failed to write temporary file: {temp_file}: {e}", file=sys.stderr)
                had_write_errors = True

        if had_write_errors:
            raise RuntimeError("Failed to write one or more temporary files")

        # If all temporary files were written successfully, perform the replacements,
        # but if a replace fails we continue with all other files and report the error.
        success_count = 0
        while temp_files:
            temp_file, target_file = temp_files[-1]
            try:
                os.replace(temp_file, target_file)
                temp_files.pop()
                success_count += 1
            except (OSError, FileNotFoundError, PermissionError) as e:
                print(f"Failed to replace {target_file} with {temp_file}: {e}", file=sys.stderr)
                if success_count == 0:
                    raise  # If we failed on the first file, let's assume all will fail.
                
        # Commit the changes.
        for result in results:
            if result.git_repo:
                repo = Repo(result.git_repo)
                # Add the modified file to staging
                repo.index.add([str(result.file_path)])
                repo.git.commit("-m", f"Bump version to v{result.new_version}")
                repo.git.push() 

    finally:
        # Clean up all remaining temporary files
        for temp_file, _ in temp_files:
            try:
                os.remove(temp_file)
            except Exception:
                print(f"Failed to remove temporary file: {temp_file}", file=sys.stderr)
                pass  # Best effort cleanup


def write_tags(results: list[VersionBumpResult]):
    """
    Writes the new tags if they don't exist.
    """
    for result in results:
        if result.git_repo:
            repo = Repo(result.git_repo)
            if not result.new_version_tag_already_exists():
                repo.git.tag(f'v{result.new_version}')
                # Push the new tag to the remote repository
                repo.git.push("origin", f'v{result.new_version}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bump-level", type=str, help="Which level to bump the version by, major, minor or patch"
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not actually write to the files")
    parser.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false", help="Actually write to the files"
    )
    parser.set_defaults(dry_run=False)

    parser.add_argument("--verbose", action="store_true", help="Describe what has been done.")
    parser.add_argument("--no-verbose", dest="verbose", action="store_false", help="Be quiet.")
    parser.set_defaults(verbose=True)

    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="The root directory to use for reporting"
    )
    parser.add_argument(
        "--git-tag", action="store_true", help="Create a git tag for the new version"
    )
    parser.add_argument(
        "--no-git-tag",
        dest="git_tag",
        action="store_false",
        help="Create a git tag for the new version",
    )
    parser.set_defaults(git_tag=False)

    # Fetch remote tags or not - regardless of the dry run flag.
    parser.add_argument("--fetch-remote-tags", action="store_true", help="Fetch remote tags")
    parser.add_argument(
        "--no-fetch-remote-tags",
        dest="fetch_remote_tags",
        action="store_false",
        help="Do not fetch remote tags",
    )
    parser.set_defaults(fetch_remote_tags=False)

    # Directories where the pyproject.toml are searched for or alternatively actual pyproject.toml files
    parser.add_argument(
        "sources",
        type=str,
        nargs="+",
        help="Directories where the pyproject.toml are searched for or alternatively "
        "actual pyproject.toml files to act on.",
    )

    args = parser.parse_args()

    # Check if the root is a directory
    if not args.root.is_dir():
        print(f"The root directory {args.root} is not a directory", file=sys.stderr)
        return 1

    print(args.sources)
    results = apply_version_bump(args.sources, args.bump_level, args.fetch_remote_tags, args.verbose)

    if args.verbose or args.dry_run:  # Always print the results if a dry run
        print(f"Bumping version {args.bump_level} in {args.sources}")
        for result in results:
            path = result.get_relative_path(args.root)
            old_version = result.old_version
            new_version = result.new_version
            old_tag_exists = result.old_version_tag_already_exists()
            new_tag_exists = result.new_version_tag_already_exists()
            new_tags = result.fetched_tags
            print(
                f"  {old_version}{'(E)' if old_tag_exists else '(?)'} ->"
                f" {new_version}{'(X)' if new_tag_exists else '(Will create)'}"
                f" {new_tags if new_tags else ' NO NEW TAGS'}"
                f" : {path}"
            )

    if not args.dry_run:
        write_results(results)
        write_tags(results)
    else:
        print("*** Dry run complete. No changes were made. ***")

    return 0


if __name__ == "__main__":
    # sys.argv = [
    #     "release_maker.py",
    #     "--dry-run",
    #     "--verbose",
    #     "--fetch-remote-tags",
    #     "--bump-level",
    #     "minor",
    #     "to_3mf",
    #     "pythonopenscad",
    # ]
    print(sys.argv)
    sys.exit(main())
