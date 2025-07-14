import glob
import os
import re
import sys
import argparse
import subprocess # Added for git command
import fnmatch  # Added for pattern matching
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


def get_moved_files(project_root, since_commit=None):
    """Get all files that have been moved/renamed in git history."""
    try:
        # Base command to get renamed/moved files
        cmd = ['git', '-C', project_root, 'log', '--diff-filter=R', '--name-status', '--pretty=format:']
        
        # Add since commit if specified
        if since_commit:
            cmd.append(f'{since_commit}..HEAD')
        
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            text=True
        ).strip()
        
        if not output:
            return []
        
        moved_files = []
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Git log with --name-status shows: R<percentage>    old_path    new_path
            # or just: R    old_path    new_path
            parts = line.split('\t')
            if len(parts) >= 3 and parts[0].startswith('R'):
                old_path = parts[1]
                new_path = parts[2]
                moved_files.append((old_path, new_path))
        
        return moved_files
    except (subprocess.CalledProcessError, FileNotFoundError):
        Console().print("[bold red]Error: Could not get moved files from git. Make sure you're in a git repository.[/bold red]")
        return []


def update_codeowners_for_moved_files(codeowners_path, moved_files, project_root):
    """Update CODEOWNERS patterns to reflect moved files."""
    if not moved_files:
        Console().print("[bold green]No moved files detected.[/bold green]")
        return False
    
    if not os.path.exists(codeowners_path):
        Console().print(f"[bold red]Error: {codeowners_path} does not exist.[/bold red]")
        return False
    
    # Read current CODEOWNERS content
    with open(codeowners_path, "r", encoding="utf-8") as file:
        lines = file.readlines()
    
    updated_lines = []
    changes_made = False
    console = Console()
    
    console.print(f"[bold blue]Checking {len(moved_files)} moved files against CODEOWNERS patterns...[/bold blue]")
    
    for line_num, original_line in enumerate(lines, 1):
        line = original_line.strip()
        updated_line = original_line
        
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            updated_lines.append(updated_line)
            continue
        
        # Parse the line to get pattern and owners
        parts = re.split(r"\s+", line, maxsplit=1)
        if not parts:
            updated_lines.append(updated_line)
            continue
        
        pattern = parts[0]
        owners = parts[1] if len(parts) > 1 else ""
        
        # Check if this pattern needs updating based on moved files
        updated_pattern = update_pattern_for_moved_files(pattern, moved_files)
        
        if updated_pattern != pattern:
            # Reconstruct the line with the updated pattern
            if owners:
                updated_line = f"{updated_pattern} {owners}\n"
            else:
                updated_line = f"{updated_pattern}\n"
            
            console.print(f"[bold yellow]Line {line_num}: Updated pattern[/bold yellow]")
            console.print(f"  [red]- {pattern}[/red]")
            console.print(f"  [green]+ {updated_pattern}[/green]")
            changes_made = True
        
        updated_lines.append(updated_line)
    
    # Write back the updated content if changes were made
    if changes_made:
        with open(codeowners_path, "w", encoding="utf-8") as file:
            file.writelines(updated_lines)
        console.print(f"[bold green]CODEOWNERS file updated successfully.[/bold green]")
        return True
    else:
        console.print("[bold green]No CODEOWNERS patterns needed updating.[/bold green]")
        return False


def update_pattern_for_moved_files(pattern, moved_files):
    """Update a single CODEOWNERS pattern based on moved files."""
    # Handle leading slash
    has_leading_slash = pattern.startswith('/')
    clean_pattern = pattern[1:] if has_leading_slash else pattern
    
    # Handle directory patterns (ending with /)
    is_dir_pattern = clean_pattern.endswith('/')
    if is_dir_pattern:
        clean_pattern = clean_pattern[:-1]
    
    # Check if pattern contains wildcards
    has_wildcards = any(char in clean_pattern for char in ['*', '?', '['])
    
    if has_wildcards:
        # For wildcard patterns, we need to be more careful
        # We'll check if the pattern structure matches moved directories
        updated_pattern = update_wildcard_pattern(clean_pattern, moved_files)
    else:
        # For exact patterns, check direct matches
        updated_pattern = clean_pattern
        for old_path, new_path in moved_files:
            if clean_pattern == old_path:
                updated_pattern = new_path
                break
            elif clean_pattern.startswith(old_path + '/'):
                # Pattern is a subpath of moved directory
                updated_pattern = clean_pattern.replace(old_path + '/', new_path + '/', 1)
                break
    
    # Reconstruct the pattern with original formatting
    result = updated_pattern
    if is_dir_pattern:
        result += '/'
    if has_leading_slash:
        result = '/' + result
    
    return result


def update_wildcard_pattern(pattern, moved_files):
    """Update a wildcard pattern based on moved files."""
    # For wildcard patterns, we need to check if the base directory structure changed
    # This is more complex and heuristic-based
    
    # Find the non-wildcard prefix of the pattern
    wildcard_pos = min(
        (pattern.find(char) for char in ['*', '?', '['] if char in pattern),
        default=len(pattern)
    )
    
    if wildcard_pos == 0:
        # Pattern starts with wildcard, harder to update automatically
        return pattern
    
    # Get the directory part before wildcards
    pattern_prefix = pattern[:wildcard_pos]
    if '/' in pattern_prefix:
        pattern_dir = '/'.join(pattern_prefix.split('/')[:-1])
    else:
        pattern_dir = ''
    
    # Check if this directory was moved
    for old_path, new_path in moved_files:
        if pattern_dir == old_path:
            # Direct directory match
            return pattern.replace(old_path, new_path, 1)
        elif pattern_dir.startswith(old_path + '/'):
            # Pattern directory is a subdirectory of moved directory
            return pattern.replace(old_path + '/', new_path + '/', 1)
    
    return pattern


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
        "--update-moved",
        action="store_true",
        help="Update CODEOWNERS patterns to reflect files that have been moved/renamed in git."
    )
    parser.add_argument(
        "--since-commit",
        help="When using --update-moved, only consider moves since this commit (default: all history)."
    )
    args = parser.parse_args()

    args.project_root = os.path.abspath(args.project_root)
    args.codeowners_path = os.path.abspath(args.codeowners_path)

    console = Console()

    # Handle update moved files mode
    if args.update_moved:
        moved_files = get_moved_files(args.project_root, args.since_commit)
        if moved_files:
            console.print(f"[bold blue]Found {len(moved_files)} moved files:[/bold blue]")
            for old_path, new_path in moved_files:
                console.print(f"  [yellow]{old_path}[/yellow] → [green]{new_path}[/green]")
            
            updated = update_codeowners_for_moved_files(args.codeowners_path, moved_files, args.project_root)
            sys.exit(0 if updated else 1)
        else:
            console.print("[bold green]No moved files found in git history.[/bold green]")
            sys.exit(0)

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

        for file_pattern, owner, line_num, original_line in nonexistent_entries:
            table.add_row(str(line_num), file_pattern, owner, original_line)
        
        console.print(table)
    else:
        console.print("[bold green]All files/patterns listed in CODEOWNERS exist.[/bold green]")


if __name__ == "__main__":
    main()
