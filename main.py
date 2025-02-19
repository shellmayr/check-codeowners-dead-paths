import os
import re
import sys


def parse_codeowners(codeowners_path):
    nonexistent_files = []
    if not os.path.exists(codeowners_path):
        print(f"Error: {codeowners_path} does not exist.")
        sys.exit(1)

    with open(codeowners_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = re.split(r"\s+", line)
            file_path = parts[0]
            owner = parts[1]

            if file_path.startswith("/"):
                file_path = file_path[1:]

            if not os.path.exists(file_path):
                nonexistent_files.append((file_path, owner))

    return nonexistent_files


def main():
    codeowners_path = ".github/CODEOWNERS"
    nonexistent_files = parse_codeowners(codeowners_path)
    print(
        f"{len(nonexistent_files)} files that are in CODEOWNERS do not exist (anymore)."
    )
    if nonexistent_files:
        print("The following files listed in CODEOWNERS do not exist:")
        for file, owner in nonexistent_files:
            if "*" not in file:
                print(f"- {file}")
    else:
        print("All files listed in CODEOWNERS exist.")


if __name__ == "__main__":
    main()
