import glob
import os
import re
import sys
import argparse
import subprocess # Added for git command
import fnmatch  # Added for pattern matching
from pathlib import Path
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


def matches_codeowners_pattern(file_path, pattern, project_root):
    """
    Check if a file path matches a CODEOWNERS pattern.
    
    This function handles various CODEOWNERS pattern types:
    - Simple glob patterns (* and ?)
    - Directory patterns (ending with /)
    - Recursive patterns (**)
    - Absolute paths (starting with /)
    - Relative paths
    """
    # Convert pattern to work with current directory structure
    if pattern.startswith("/"):
        # Absolute path from repository root
        pattern = pattern[1:]  # Remove leading slash
        full_pattern = os.path.join(project_root, pattern)
    else:
        # Relative path - could match anywhere in the repository
        if "**" in pattern:
            # Handle recursive patterns
            full_pattern = os.path.join(project_root, pattern)
        else:
            # For non-recursive patterns, try both relative to root and anywhere in repo
            full_pattern = os.path.join(project_root, pattern)
    
    # Handle directory patterns (ending with /)
    if pattern.endswith("/"):
        # Directory pattern - match any file within this directory
        pattern_without_slash = pattern.rstrip("/")
        if pattern.startswith("/"):
            dir_pattern = os.path.join(project_root, pattern_without_slash)
        else:
            dir_pattern = os.path.join(project_root, pattern_without_slash)
        
        # Check if the pattern matches any existing directories
        if "**" in pattern_without_slash or "*" in pattern_without_slash or "?" in pattern_without_slash:
            # Use glob for wildcard directory patterns
            matching_dirs = glob.glob(dir_pattern, recursive=True)
            return len(matching_dirs) > 0
        else:
            # Simple directory check
            return os.path.isdir(dir_pattern)
    
    # Handle file patterns
    if "**" in pattern:
        # Recursive pattern - use glob with recursive=True
        return len(glob.glob(full_pattern, recursive=True)) > 0
    elif "*" in pattern or "?" in pattern:
        # Simple glob pattern
        return len(glob.glob(full_pattern)) > 0
    else:
        # Literal file/directory path
        return os.path.exists(full_pattern)


def check_pattern_existence(file_pattern, project_root):
    """
    Enhanced function to check if a CODEOWNERS pattern has any matches.
    
    This function properly handles:
    - Wildcard patterns (* and ?)
    - Recursive patterns (**)
    - Directory patterns (ending with /)
    - Absolute and relative paths
    """
    # Handle absolute paths (starting with /)
    if file_pattern.startswith("/"):
        # Remove leading slash and work from project root
        pattern_without_slash = file_pattern[1:]
        effective_path = os.path.join(project_root, pattern_without_slash)
    else:
        # Relative path
        effective_path = os.path.join(project_root, file_pattern)
    
    # Normalize the path
    effective_path = os.path.normpath(effective_path)
    
    # Check if this is a directory pattern
    if file_pattern.endswith("/"):
        # Directory pattern - check if any directories match
        dir_pattern = effective_path.rstrip("/")
        if "*" in dir_pattern or "?" in dir_pattern:
            # Wildcard directory pattern
            matching_dirs = []
            if "**" in dir_pattern:
                # Recursive directory pattern
                matching_dirs = glob.glob(dir_pattern, recursive=True)
            else:
                # Simple directory pattern
                matching_dirs = glob.glob(dir_pattern)
            
            # Filter to only include directories
            matching_dirs = [d for d in matching_dirs if os.path.isdir(d)]
            return len(matching_dirs) > 0
        else:
            # Simple directory check
            return os.path.isdir(dir_pattern)
    
    # File pattern handling
    if "**" in file_pattern:
        # Recursive pattern
        matches = glob.glob(effective_path, recursive=True)
        return len(matches) > 0
    elif "*" in file_pattern or "?" in file_pattern:
        # Simple glob pattern
        matches = glob.glob(effective_path)
        return len(matches) > 0
    else:
        # Literal file/directory path
        return os.path.exists(effective_path)


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

            # Use the enhanced pattern existence check
            current_project_root = project_root or os.getcwd()
            exists = check_pattern_existence(file_pattern, current_project_root)

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


def get_all_tracked_files(project_root):
    """Get all files tracked by git in the repository."""
    try:
        # Get all tracked files relative to the repo root
        output = subprocess.check_output(
            ['git', '-C', project_root, 'ls-files'],
            stderr=subprocess.STDOUT,
            text=True
        ).strip()
        
        if not output:
            return []
            
        files = output.split('\n')
        return [f.strip() for f in files if f.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        Console().print("[bold red]Error: Could not get tracked files from git. Make sure you're in a git repository.[/bold red]")
        return []


def normalize_codeowners_pattern(pattern):
    """Normalize a CODEOWNERS pattern for matching."""
    # Remove leading slash if present (it means "from root")
    if pattern.startswith('/'):
        pattern = pattern[1:]
    
    return pattern


def file_matches_pattern(file_path, pattern):
    """Check if a file path matches a CODEOWNERS pattern."""
    # Normalize the pattern
    normalized_pattern = normalize_codeowners_pattern(pattern)
    
    # Handle directory patterns (ending with /)
    if normalized_pattern.endswith('/'):
        # This pattern matches directories and everything in them
        dir_pattern = normalized_pattern.rstrip('/')
        # Check if file is in this directory
        if file_path.startswith(dir_pattern + '/') or file_path == dir_pattern:
            return True
        # Also check with glob pattern matching for wildcards
        return fnmatch.fnmatch(os.path.dirname(file_path) + '/', normalized_pattern)
    
    # Regular file pattern matching
    if fnmatch.fnmatch(file_path, normalized_pattern):
        return True
    
    # Check if any parent directory matches the pattern
    path_parts = file_path.split('/')
    for i in range(len(path_parts)):
        partial_path = '/'.join(path_parts[:i+1])
        if fnmatch.fnmatch(partial_path, normalized_pattern):
            return True
    
    return False


def get_codeowners_patterns(codeowners_path):
    """Extract all patterns from the CODEOWNERS file."""
    patterns = []
    
    if not os.path.exists(codeowners_path):
        Console().print(f"[bold red]Error: {codeowners_path} does not exist.[/bold red]")
        return patterns
    
    with open(codeowners_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            parts = re.split(r"\s+", line, maxsplit=1)
            if parts:
                patterns.append(parts[0])
    
    return patterns


def group_uncovered_by_directories(uncovered_files, all_tracked_files):
    """Group uncovered files by directories when all files in a directory are uncovered."""
    if not uncovered_files:
        return []
    
    uncovered_set = set(uncovered_files)
    
    # Find all directories and the files they contain
    dir_to_files = {}
    for file_path in all_tracked_files:
        dir_path = os.path.dirname(file_path)
        if dir_path:  # Only consider files in subdirectories
            if dir_path not in dir_to_files:
                dir_to_files[dir_path] = []
            dir_to_files[dir_path].append(file_path)
    
    # Find directories where ALL tracked files are uncovered
    fully_uncovered_dirs = []
    for dir_path, files_in_dir in dir_to_files.items():
        if all(file_path in uncovered_set for file_path in files_in_dir):
            fully_uncovered_dirs.append(dir_path)
    
    # Sort by depth (deepest first) to prefer most specific directories
    fully_uncovered_dirs.sort(key=lambda d: d.count('/'), reverse=True)
    
    # Remove parent directories if their children are already included
    final_dirs = []
    for dir_path in fully_uncovered_dirs:
        # Check if any already selected directory is a child of this one
        is_parent_of_selected = any(
            selected_dir.startswith(dir_path + '/') 
            for selected_dir in final_dirs
        )
        if not is_parent_of_selected:
            final_dirs.append(dir_path)
    
    # Build result list
    result = []
    covered_files = set()
    
    # Add directories
    for dir_path in sorted(final_dirs):
        result.append(f"{dir_path}/")
        # Mark all files in this directory as covered
        for file_path in dir_to_files[dir_path]:
            covered_files.add(file_path)
    
    # Add individual uncovered files not in any covered directory
    individual_files = [
        file_path for file_path in uncovered_files 
        if file_path not in covered_files
    ]
    result.extend(sorted(individual_files))
    
    return result


def find_uncovered_files(project_root, codeowners_path):
    """Find all tracked files that are not covered by any CODEOWNERS pattern."""
    tracked_files = get_all_tracked_files(project_root)
    if not tracked_files:
        return []
    
    codeowners_patterns = get_codeowners_patterns(codeowners_path)
    if not codeowners_patterns:
        Console().print("[bold yellow]No patterns found in CODEOWNERS file.[/bold yellow]")
        return tracked_files
    
    uncovered_files = []
    
    for file_path in tracked_files:
        is_covered = False
        for pattern in codeowners_patterns:
            if file_matches_pattern(file_path, pattern):
                is_covered = True
                break
        
        if not is_covered:
            uncovered_files.append(file_path)
    
    # Group by directories when appropriate
    return group_uncovered_by_directories(uncovered_files, tracked_files)


def get_pattern_matches(file_pattern, project_root, max_matches=20):
    """
    Get a list of files that match a CODEOWNERS pattern.
    
    This is useful for debugging and understanding what files
    a pattern is matching.
    """
    # Handle absolute paths (starting with /)
    if file_pattern.startswith("/"):
        # Remove leading slash and work from project root
        pattern_without_slash = file_pattern[1:]
        effective_path = os.path.join(project_root, pattern_without_slash)
    else:
        # Relative path
        effective_path = os.path.join(project_root, file_pattern)
    
    # Normalize the path
    effective_path = os.path.normpath(effective_path)
    
    matches = []
    
    # Check if this is a directory pattern
    if file_pattern.endswith("/"):
        # Directory pattern - find matching directories
        dir_pattern = effective_path.rstrip("/")
        if "*" in dir_pattern or "?" in dir_pattern:
            # Wildcard directory pattern
            if "**" in dir_pattern:
                # Recursive directory pattern
                all_matches = glob.glob(dir_pattern, recursive=True)
            else:
                # Simple directory pattern
                all_matches = glob.glob(dir_pattern)
            
            # Filter to only include directories
            matches = [d for d in all_matches if os.path.isdir(d)]
        else:
            # Simple directory check
            if os.path.isdir(dir_pattern):
                matches = [dir_pattern]
    else:
        # File pattern handling
        if "**" in file_pattern:
            # Recursive pattern
            matches = glob.glob(effective_path, recursive=True)
        elif "*" in file_pattern or "?" in file_pattern:
            # Simple glob pattern
            matches = glob.glob(effective_path)
        else:
            # Literal file/directory path
            if os.path.exists(effective_path):
                matches = [effective_path]
    
    # Convert absolute paths back to relative paths from project root
    relative_matches = []
    for match in matches[:max_matches]:  # Limit to prevent overwhelming output
        try:
            relative_path = os.path.relpath(match, project_root)
            relative_matches.append(relative_path)
        except ValueError:
            # Handle cases where paths are on different drives (Windows)
            relative_matches.append(match)
    
    return relative_matches


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
    parser.add_argument(
        "--find-uncovered",
        action="store_true",
        help="Find files in the repository that are not covered by any CODEOWNERS pattern."
    )
    parser.add_argument(
        "--debug-pattern",
        help="Debug a specific pattern by showing what files it matches (use with --show-matches)."
    )
    parser.add_argument(
        "--show-matches",
        action="store_true",
        help="Show what files match each pattern (useful for debugging wildcard patterns)."
    )
    args = parser.parse_args()

    args.project_root = os.path.abspath(args.project_root)
    args.codeowners_path = os.path.abspath(args.codeowners_path)

    console = Console()

    # Handle debug pattern mode
    if args.debug_pattern:
        console.print(f"[bold cyan]Debugging pattern: {args.debug_pattern}[/bold cyan]")
        matches = get_pattern_matches(args.debug_pattern, args.project_root)
        
        if matches:
            console.print(f"[bold green]Pattern matches {len(matches)} files:[/bold green]")
            for match in matches:
                console.print(f"  {match}")
        else:
            console.print("[bold red]Pattern matches no files[/bold red]")
        
        # Check if pattern exists
        exists = check_pattern_existence(args.debug_pattern, args.project_root)
        console.print(f"[bold yellow]Pattern exists: {exists}[/bold yellow]")
        return

    # Handle find uncovered files mode
    if args.find_uncovered:
        uncovered_files = find_uncovered_files(args.project_root, args.codeowners_path)
        
        if uncovered_files:
            console.print(
                f"[bold yellow]{len(uncovered_files)} files in the repository are not covered by CODEOWNERS.[/bold yellow]"
            )
            table = Table(title="Files not covered by CODEOWNERS")
            table.add_column("File Path", style="cyan")
            
            for file_path in sorted(uncovered_files):
                table.add_row(file_path)
            
            console.print(table)
            sys.exit(1)  # Exit with error code to indicate uncovered files found
        else:
            console.print("[bold green]All tracked files are covered by CODEOWNERS patterns.[/bold green]")
            sys.exit(0)

    nonexistent_entries, original_codeowners_lines = parse_codeowners(args.codeowners_path, args.project_root)

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
        if args.show_matches:
            table.add_column("Sample Matches", style="yellow")

        for file_pattern, owner, line_num, original_line in nonexistent_entries:
            row_data = [str(line_num), file_pattern, owner, original_line]
            
            if args.show_matches:
                matches = get_pattern_matches(file_pattern, args.project_root, max_matches=3)
                if matches:
                    matches_str = ", ".join(matches)
                    if len(matches) > 3:
                        matches_str += f" (+{len(get_pattern_matches(file_pattern, args.project_root)) - 3} more)"
                else:
                    matches_str = "No matches"
                row_data.append(matches_str)
            
            table.add_row(*row_data)
        
        console.print(table)
    else:
        console.print("[bold green]All files/patterns listed in CODEOWNERS exist.[/bold green]")


if __name__ == "__main__":
    main()
