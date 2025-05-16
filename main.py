import glob
import os
import re
import sys
import argparse
from rich.console import Console
from rich.table import Table


def parse_codeowners(codeowners_path, project_root):
    nonexistent_files = []
    if not os.path.exists(codeowners_path):
        Console().print(f"[bold red]Error: {codeowners_path} does not exist.[/bold red]")
        sys.exit(1)

    with open(codeowners_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = re.split(r"\s+", line, maxsplit=1)
            file_pattern = parts[0]
            owner_info = ""

            if len(parts) > 1:
                owner_info = parts[1]

            effective_path_to_check = file_pattern
            if file_pattern.startswith("/"):
                path_in_codeowners = file_pattern[1:]
                effective_path_to_check = os.path.join(project_root, path_in_codeowners)
            else:
                effective_path_to_check = os.path.join(project_root, file_pattern)
            
            if not os.path.exists(effective_path_to_check) and not glob.glob(effective_path_to_check):
                display_owner = owner_info if owner_info else "<No owner specified>"
                nonexistent_files.append((file_pattern, display_owner))

    return nonexistent_files


def main():
    parser = argparse.ArgumentParser(description="Check for non-existent paths in a CODEOWNERS file.")
    parser.add_argument(
        "codeowners_path",
        help="Path to the CODEOWNERS file"
    )
    parser.add_argument(
        "--project-root",
        help="Path to the project root directory (default: current directory)"
    )
    args = parser.parse_args()

    nonexistent_files = parse_codeowners(args.codeowners_path, args.project_root)
    
    console = Console()

    if nonexistent_files:
        console.print(
            f"[bold yellow]{len(nonexistent_files)} files/patterns in CODEOWNERS do not exist (anymore).[/bold yellow]"
        )
        table = Table(title="Non-existent files/patterns in CODEOWNERS")
        table.add_column("File/Pattern", style="cyan", no_wrap=True)
        table.add_column("Owner", style="magenta")

        for file, owner in nonexistent_files:
            table.add_row(file, owner)
        
        console.print(table)
    else:
        console.print("[bold green]All files/patterns listed in CODEOWNERS exist.[/bold green]")


if __name__ == "__main__":
    main()
