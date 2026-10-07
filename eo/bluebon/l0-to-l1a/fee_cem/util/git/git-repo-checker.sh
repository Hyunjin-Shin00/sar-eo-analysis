#!/bin/bash

make_sure_git_repo_clean() {

  # Make sure the repository is clean with no changes
  if [ -n "$(git status --porcelain)" ]; then
    echo "--------------------------------- [Critical Warning] ---------------------------------"
    echo "The repository is dirty (there are uncommitted changes). Below are the changed files."
    echo "--------------------------------------------------------------------------------------"
    git status --porcelain
    echo "--------------------------------------------------------------------------------------"
    echo "Aborting."
    return 1
  fi

  current_branch=$(git rev-parse --abbrev-ref HEAD)
  if [ "$current_branch" != "master" ]; then
    echo "--------------------------------- [Critical Warning] ---------------------------------"
    echo "You are currently on branch '$current_branch', not 'master'."
    echo "--------------------------------------------------------------------------------------"
    read -p "- You are recommended to stop the procedure and check your branch. but do you want to continue? (y/n): " choice

    if [ "$choice" != "y" ]; then
        echo "Aborting."
        return 1
    fi
  fi
}

make_sure_git_repo_clean