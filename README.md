# check-codeowners-dead-paths

A Python CLI tool for analyzing CODEOWNERS files. It can:
1. Check for non-existent paths in a CODEOWNERS file (dead/stale paths)
2. Find files in the repository that are not covered by any CODEOWNERS patterns

## Features

### Check for Dead Paths
Small python script that checks whether a path in CODEOWNERS points to a file that no longer exists. Currently does not check whether it has been moved or anything and is therefore very dumb, but I may add this in the future.

### Find Uncovered Files
Finds all git-tracked files in the repository that are not covered by any pattern in the CODEOWNERS file.

## Usage

```bash
# Check for non-existent paths in CODEOWNERS
python main.py CODEOWNERS

# Find files not covered by CODEOWNERS
python main.py CODEOWNERS --find-uncovered

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
