import glob
import os
import re
import sys
import argparse
import subprocess # Added for git command
from rich.console import Console
from rich.table import Table


def get_git_repo_root(path_within_repo):
    """Tries to find the root of the git repository containing the given path."""
    try:
        # Ensure the path is a directory for the -C argument if git version requires it
        # However, git rev-parse --show-toplevel usually works fine with a file path too
        # or from any subdirectory.
        # We use os.path.dirname to be safe and start from the directory of the path.
        start_dir = os.path.dirname(os.path.abspath(path_within_repo))
        if not os.path.isdir(start_dir):
             # If path_within_repo is a dir itself and exists
            if os.path.isdir(os.path.abspath(path_within_repo)):
                start_dir = os.path.abspath(path_within_repo)
            else: # Fallback if dirname doesn't make sense (e.g. top level file)
                start_dir = os.getcwd()

        toplevel = subprocess.check_output(
            ['git', '-C', start_dir, 'rev-parse', '--show-toplevel'],
            stderr=subprocess.STDOUT, # Suppress error messages on stderr for controlled failure
            text=True
        ).strip()
        return toplevel
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Git command failed or git not found
        return None


def parse_codeowners(codeowners_path, project_root):
    nonexistent_entries_details = []
    original_lines_with_eol = [] # To store all original lines
    if not os.path.exists(codeowners_path):
        Console().print(f"[bold red]Error: {codeowners_path} does not exist.[/bold red]")
        sys.exit(1)

    line_num_1_indexed = 0
    with open(codeowners_path, "r", encoding="utf-8") as file:
        for original_line_content_with_eol in file:
            original_lines_with_eol.append(original_line_content_with_eol) # Store raw line
            line_num_1_indexed += 1
            line = original_line_content_with_eol.strip()
            if not line or line.startswith("#"):
                continue

            parts = re.split(r"\s+", line, maxsplit=1)
            file_pattern = parts[0]
            owner_info = ""

            if len(parts) > 1:
                owner_info = parts[1]

            effective_path_to_check = file_pattern
            current_project_root = project_root or os.getcwd()

            if file_pattern.startswith("/"):
                path_in_codeowners = file_pattern[1:]
                effective_path_to_check = os.path.join(current_project_root, path_in_codeowners)
            else:
                effective_path_to_check = os.path.join(current_project_root, file_pattern)
            
            effective_path_to_check_normalized = os.path.normpath(effective_path_to_check)

            exists = False
            if "*" in file_pattern or "?" in file_pattern or "[" in file_pattern:
                if glob.glob(effective_path_to_check_normalized):
                    exists = True
            elif os.path.exists(effective_path_to_check_normalized):
                exists = True

            if not exists:
                display_owner = owner_info if owner_info else "<No owner specified>"
                nonexistent_entries_details.append((
                    file_pattern, 
                    display_owner, 
                    line_num_1_indexed, 
                    original_line_content_with_eol.rstrip('\r\n') # Store clean original line for display
                ))

    return nonexistent_entries_details, original_lines_with_eol


def generate_diff_patch(codeowners_filepath, nonexistent_entries, original_codeowners_lines_with_eol):
    patch_lines = []    
    abs_codeowners_filepath = os.path.abspath(codeowners_filepath)
    
    # Try to get path relative to git repo root
    git_repo_root = get_git_repo_root(abs_codeowners_filepath)
    
    if git_repo_root:
        try:
            relative_codeowners_filepath = os.path.relpath(abs_codeowners_filepath, git_repo_root)
        except ValueError: # Should not happen if git_repo_root is ancestor or same
            relative_codeowners_filepath = os.path.basename(abs_codeowners_filepath) # Fallback
    else:
        # Fallback: path relative to CWD or just basename
        cwd = os.getcwd()
        try:
            relative_path_from_cwd = os.path.relpath(abs_codeowners_filepath, cwd)
            # If relpath goes "up" (e.g., ../../file), it means it's outside cwd tree, use basename
            if relative_path_from_cwd.startswith("..") or os.path.isabs(relative_path_from_cwd):
                relative_codeowners_filepath = os.path.basename(abs_codeowners_filepath)
            else:
                relative_codeowners_filepath = relative_path_from_cwd
        except ValueError: # Happens if paths are on different drives on Windows
            relative_codeowners_filepath = os.path.basename(abs_codeowners_filepath)

    patch_lines.append(f"--- a/{relative_codeowners_filepath}")
    patch_lines.append(f"+++ b/{relative_codeowners_filepath}")

    # nonexistent_entries has (file_pattern, owner, line_num_1_indexed, original_line_for_display)
    lines_to_delete_numbers = {entry[2] for entry in nonexistent_entries}
    
    original_num_lines = len(original_codeowners_lines_with_eol)
    new_num_lines = original_num_lines - len(lines_to_delete_numbers)

    patch_lines.append(f"@@ -1,{original_num_lines} +1,{new_num_lines} @@")

    for i, line_content_with_eol in enumerate(original_codeowners_lines_with_eol):
        current_line_num_1_indexed = i + 1
        # Patch format requires no trailing newline on the content of +/- lines
        line_content_for_patch = line_content_with_eol.rstrip('\r\n')
        if current_line_num_1_indexed in lines_to_delete_numbers:
            patch_lines.append(f"-{line_content_for_patch}")
        else:
            patch_lines.append(f" {line_content_for_patch}")
            
    return "\n".join(patch_lines) + "\n" # Ensure final newline for patch format


def main():
    parser = argparse.ArgumentParser(description="Check for non-existent paths in a CODEOWNERS file.")
    parser.add_argument(
        "codeowners_path",
        help="Path to the CODEOWNERS file"
    )
    parser.add_argument(
        "--project-root",
        help="Path to the project root directory (default: current directory)",
        default=os.getcwd()
    )
    parser.add_argument(
        "--generate-patch",
        action="store_true",
        help="Generate a git patch to remove non-existent paths and save it to stale-codeowners.patch."
    )
    args = parser.parse_args()

    args.project_root = os.path.abspath(args.project_root)
    args.codeowners_path = os.path.abspath(args.codeowners_path)

    nonexistent_entries, original_codeowners_lines = parse_codeowners(args.codeowners_path, args.project_root)
    
    console = Console()

    if args.generate_patch:
        if nonexistent_entries:
            patch_content = generate_diff_patch(args.codeowners_path, nonexistent_entries, original_codeowners_lines)
            patch_filename = "stale-codeowners.patch"
            with open(patch_filename, "w", encoding="utf-8") as f:
                f.write(patch_content)
            console.print(f"[bold green]Patch file generated: {patch_filename}[/bold green]")
            sys.exit(0)
        else:
            console.print("[bold green]No non-existent entries found. Nothing to patch.[/bold green]")
            sys.exit(0)

    if nonexistent_entries:
        console.print(
            f"[bold yellow]{len(nonexistent_entries)} files/patterns in CODEOWNERS do not exist (anymore).[/bold yellow]"
        )
        table = Table(title="Non-existent files/patterns in CODEOWNERS")
        table.add_column("Line No.", style="dim")
        table.add_column("File/Pattern", style="cyan", no_wrap=True)
        table.add_column("Owner", style="magenta")
        table.add_column("Original Line Content", style="green")

        for file_pattern, owner, line_num, original_line in nonexistent_entries:
            table.add_row(str(line_num), file_pattern, owner, original_line)
        
        console.print(table)
    else:
        console.print("[bold green]All files/patterns listed in CODEOWNERS exist.[/bold green]")


if __name__ == "__main__":
    main()
