# check-codeowners-dead-paths

A Python CLI tool for analyzing CODEOWNERS files. It can:
1. Check for non-existent paths in a CODEOWNERS file (dead/stale paths)
2. Find files in the repository that are not covered by any CODEOWNERS patterns
3. Automatically update CODEOWNERS patterns when files are moved/renamed

## Features

### Check for Dead Paths
Checks whether a path in CODEOWNERS points to a file that no longer exists and displays them in a table.

### Find Uncovered Files
Finds all git-tracked files in the repository that are not covered by any pattern in the CODEOWNERS file.

### Update Moved Files
Automatically updates CODEOWNERS patterns to reflect files that have been moved or renamed in git history. This feature:
- Detects moved/renamed files using git log
- Updates exact path patterns to their new locations
- Handles directory patterns (ending with /)
- Supports wildcard patterns with intelligent directory matching
- Preserves leading slashes and other pattern formatting

## Usage

```bash
# Check for non-existent paths in CODEOWNERS
python main.py CODEOWNERS

# Find files not covered by CODEOWNERS
python main.py CODEOWNERS --find-uncovered

# Update CODEOWNERS patterns for moved files
python main.py CODEOWNERS --update-moved

# Update patterns only for moves since a specific commit
python main.py CODEOWNERS --update-moved --since-commit abc123

# Generate a patch file to remove non-existent paths
python main.py CODEOWNERS --generate-patch

# Specify a custom project root directory
python main.py CODEOWNERS --project-root /path/to/repo
```

## Installation

Clone the repository and install dependencies:

```bash
git clone <repository-url>
cd check-codeowners-dead-paths
pip install -r requirements.txt
```
