#!/usr/bin/env bash

# rename_git_tag.sh
#
# Usage:
#   ./rename_git_tag.sh <old_tag_name> <new_tag_name>
#
# Description:
#   This script renames a Git tag by:
#     1. Verifying the old tag exists locally.
#     2. Verifying the new tag does NOT exist locally.
#     3. Creating a new tag with the desired name, pointing to the same commit.
#     4. Deleting the old tag locally.
#     5. Pushing the new tag to the remote.
#     6. Deleting the old tag from the remote.
#
#   It includes error checks that echo the command and status if any step fails.

set -euo pipefail

#######################################
# Run a command and check for errors.
# Globals:
#   None
# Arguments:
#   Command (string)
# Outputs:
#   If the command fails, prints an error and exits with its status code.
#######################################
run_cmd() {
  local cmd="$*"
  echo "Running: $cmd"
  eval "$cmd"
  local status=$?
  if [ $status -ne 0 ]; then
    echo "Error: '$cmd' failed with status $status"
    exit $status
  fi
}

# Verify we have two arguments
if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <old_tag_name> <new_tag_name>"
  exit 1
fi

OLD_TAG="$1"
NEW_TAG="$2"

# 1. Ensure the old tag exists in the local repository.
if ! git rev-parse -q --verify "refs/tags/$OLD_TAG" >/dev/null; then
  echo "Error: Tag '$OLD_TAG' does not exist in the local repository."
  echo "       Please fetch remote tags or ensure the tag name is correct."
  exit 1
fi

# 2. Ensure the new tag does not exist in the local repository.
if git rev-parse -q --verify "refs/tags/$NEW_TAG" >/dev/null; then
  echo "Error: Tag '$NEW_TAG' already exists in the local repository."
  exit 1
fi

echo "Renaming tag '$OLD_TAG' to '$NEW_TAG'..."

# 3. Create the new tag (pointing to the same commit as the old tag).
run_cmd "git tag \"$NEW_TAG\" \"$OLD_TAG\""

# 4. Delete the old tag locally.
run_cmd "git tag -d \"$OLD_TAG\""

# 5. Push the new tag to remote.
run_cmd "git push origin \"$NEW_TAG\""

# 6. Remove the old tag from remote.
run_cmd "git push origin :refs/tags/\"$OLD_TAG\""

echo "Tag '$OLD_TAG' has been successfully renamed to '$NEW_TAG'."
