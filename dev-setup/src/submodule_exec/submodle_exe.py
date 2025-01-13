#!/usr/bin/env python3
"""
run_submodules.py

Runs a shell command in each submodule (and optionally the parent repo),
concurrently. Prints the output for each repo in a contiguous block,
sorted alphabetically by module name.

Steps:
  1) Parse command-line arguments
  2) Assemble the collection of repos (submodules + optional parent)
  3) Perform the operations (run commands)
  4) Report the results

Usage:
    python run_submodules.py [--repo-dir /path/to/repo]
                             [--include-parent]
                             [--verbose]
                             <command> [<arg1> <arg2> ...]

Example:
    python run_submodules.py ls -la
    python run_submodules.py --repo-dir /path/to/repo --include-parent ls -la
    python run_submodules.py --verbose ls -la
"""

import argparse
import os
import sys
import subprocess
from git import Repo, GitCommandError
from dataclasses import dataclass

# anchorscad-utils
# pip install anchorscad-utils
from anchorscad_lib.utils.process_manager import ProcessManager, ProcessManagerEntry


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a shell command in each submodule (optionally the parent)."
    )
    parser.add_argument(
        "--repo-dir",
        default=".",
        help="Path to the local Git repository (default: current directory)."
    )
    parser.add_argument(
        "--include-parent",
        action="store_true",
        help="Also run the command in the parent repo directory."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="If set, report when each command finishes and whether it had an error."
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="The shell command (and optional arguments) to run in each submodule."
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="If set, only list the submodules, don't run any commands."
    )
    return parser.parse_args()


def gather_repos(args):
    """
    Opens the repository at args.repo_dir, reads all submodules, and optionally
    adds the parent repo itself. Returns a list of (module_name, path) tuples,
    sorted alphabetically by module_name.

    Exits if no submodules are found (per requirements).
    """
    repo_dir = os.path.abspath(args.repo_dir)
    try:
        repo = Repo(repo_dir)
    except (GitCommandError, Exception) as e:
        print(f"Error: Unable to open repository at {repo_dir}: {e}")
        sys.exit(1)

    submodules = repo.submodules
    if not submodules and not args.include_parent:
        print("Error: No submodules found in this repository, and --include-parent not set.")
        sys.exit(1)

    submodule_info = []
    for sm in submodules:
        submodule_info.append((sm.name, os.path.join(repo_dir, sm.path)))

    # Sort submodules by name
    submodule_info.sort(key=lambda x: x[0])

    if args.include_parent:
        # Prepend or append the parent so it appears in the final listing
        # We'll give it a special name, e.g., "(parent_repo)"
        submodule_info.insert(0, ("(parent_repo)", repo_dir))

    return submodule_info


@dataclass
class SubmoduleCommandEntry(ProcessManagerEntry):
    """
    A custom ProcessManagerEntry that runs a command in a given directory,
    captures stdout/stderr, and stores the return code.

    If 'verbose' is True, it prints a message when the process finishes.
    """
    module_name: str = None
    cmd_args: list = None
    cwd: str = None
    verbose: bool = False
    stdout: str = ""
    stderr: str = ""
    returncode: int = None

    def started(self):
        # Called just before process creation
        pass

    def ended(self, status):
        """
        Called when the subprocess finishes.
        We collect stdout/stderr by calling communicate()
        if we ran with stdout=PIPE, stderr=PIPE.
        """
        self.returncode = status
        if self.popen_obj:
            out, err = self.communicate()
            self.stdout = out.decode("utf-8", errors="replace") if out else ""
            self.stderr = err.decode("utf-8", errors="replace") if err else ""

        if self.verbose:
            # Immediately report that this module's command finished
            # and whether it failed
            result_str = "SUCCESS" if self.returncode == 0 else "ERROR"
            print(f"[VERBOSE] Command finished in module '{self.module_name}': {result_str}")


def run_commands(submodule_info, command, verbose):
    """
    Runs the specified command in each of the modules (parallel),
    using anchorscad_lib.utils.process_manager.

    Returns a list of SubmoduleCommandEntry objects with results.
    """
    # Create a ProcessManager (default max_jobs = num_cores - 1)
    manager = ProcessManager()

    entries = []
    for name, path in submodule_info:
        entry = SubmoduleCommandEntry(module_name=name, cmd_args=command, cwd=path, verbose=verbose)

        entries.append(entry)
        try:
            manager.run_proc(
                entry,
                command,
                cwd=path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        except FileNotFoundError:
            print(f"Error: command not found in {' '.join(command)}", file=sys.stderr)
            sys.exit(1)

    # Wait for all processes to finish
    success_count, failure_count = manager.finished_status()

    return entries, success_count, failure_count


##############################################################################
# 4) REPORT ON RESULTS
##############################################################################
def report_results(entries, success_count, failure_count):
    """
    Sorts entries by module name, prints each module's output in a contiguous block,
    then prints a summary. If any failures occurred, exits with code 1.
    """
    # Sort the entries in alphabetical order by module name
    entries.sort(key=lambda e: e.module_name.lower())

    # Print outputs in contiguous blocks
    for e in entries:
        print("=" * 60)
        print(f"Module: {e.module_name} status: {e.returncode}")
        print("=" * 60)
        # Print stdout
        if e.stdout:
            print(e.stdout, end="")
        # Print stderr to stderr (or you can unify them)
        if e.stderr:
            print(e.stderr, end="", file=sys.stderr)

    # Summary
    print("\nSummary")
    print("=======")
    print(f"Success: {success_count}, Failure: {failure_count}")
    if failure_count > 0:
        sys.exit(1)


def main():
    args = parse_args()
    
    if args.list_only:
        print("Listing submodules...", file=sys.stderr)
        submodule_info = gather_repos(args)
        for name, path in submodule_info:
            print(f"{name}: {path}")
        sys.exit(0)

    if not args.command:
        print("Error: No command provided.", file=sys.stderr)
        print("Example: run_submodules.py <command> [<arg1> <arg2> ...]", file=sys.stderr)
        sys.exit(1)

    # Gather repos
    submodule_info = gather_repos(args)
    if not submodule_info:
        # If there's absolutely no submodules + no parent, already handled
        sys.exit(1)

    # Perform operations (run commands)
    entries, success_count, failure_count = run_commands(
        submodule_info,
        args.command,
        args.verbose
    )

    # Step 4) Report results
    report_results(entries, success_count, failure_count)


if __name__ == "__main__":
    # sys.argv = [
    #     "submodule_exec.py",
    #     "--verbose",
    #     "git",
    #     "branch"
    # ]
    main()
