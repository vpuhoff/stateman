# Stateman: Directory Binary Patching Utility

This module provides tools to track changes in the content of a directory and create compact binary "patches" that can be used to synchronize another copy of that directory.

## Why is this needed?

Imagine you have a large directory with files (e.g., installed software, game assets, a dataset), and you need to distribute updates for this directory. Transferring the entire directory can be inefficient, especially if the changes affect only a small portion of the files.

`stateman` solves this problem by allowing you to:

1.  **Capture the state** of a directory at a specific point in time (list of files and their MD5 checksums).
2.  **Compare two states** (e.g., before and after an update) to determine which files were added, removed, or modified.
3.  **Create a binary patch** (a ZIP archive) containing only the added and modified files, along with metadata about the changes.
4.  **Apply the patch** to another copy of the directory (which is in the initial state) to bring it to the updated state.

This is useful for:
* Application or game update systems.
* Synchronizing large datasets between machines.
* Managing configurations where precise change tracking is needed.

## How does it work?

The basic workflow is:

1.  **`GetState(folder)`**: Scans the specified folder, calculates the MD5 hash for each file, and returns a dictionary `{relative_path: hash}`. This is a "snapshot" of the folder's state.
2.  **`GetDiff(state1, state2)`**: Compares two such "snapshots" and returns a dictionary describing the difference: lists of added, removed, changed files, and the hashes of the source and target states.
3.  **`CreatePatch(source_folder, patch_file, difference)`**: Takes the difference dictionary (`diff`) and the files from `source_folder` that were added or changed, and packages them along with metadata into a ZIP archive (`patch_file`).
4.  **`ApplyPatch(target_folder, patch_file)`**: Unpacks the `patch_file`. First, it checks if the current state of `target_folder` matches the *source* state hash from the patch. If yes, it deletes files marked as removed and extracts/overwrites files from the archive. After applying, the state of `target_folder` should match the *target* state hash from the patch.

## Usage Example:

```python
from stateman import GetState, GetDiff, CreatePatch, ApplyPatch, GetStateHash
import os
import shutil
from pathlib import Path

# --- Setup ---
# Use temporary directories for the example
base_path = Path("./stateman_example_workspace")
if base_path.exists():
    shutil.rmtree(base_path)
base_path.mkdir()

root_dir = base_path / "source_app" # Folder with the "original" application/data
target_dir = base_path / "user_app" # Folder where we will apply the patch
patch_file = base_path / "update.patch" # The patch file

root_dir.mkdir()
subfolder = root_dir / ".git" # Folder to be excluded
subfolder.mkdir()

def write_file(filepath, text):
    """Helper function to write text to a file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(text, encoding='utf-8')

print("--- 1. Creating initial files ---")
write_file(subfolder / "config", "git config")
write_file(root_dir / "main.py", "print('Hello')")
write_file(root_dir / "data" / "file1.txt", "data v1")
write_file(root_dir / "readme.txt", "Initial readme")

# --- Get initial state (excluding .git) ---
# Important to use os.path.sep for correct exclusion on different OS
exclude_pattern = f".git{os.path.sep}"
print(f"\n--- 2. Getting initial state (excluding '{exclude_pattern}') ---")
state1 = GetState(str(root_dir), exclude=exclude_pattern)
print("Initial state (State 1):")
print(state1)
state1_hash = GetStateHash(state1)
print(f"Initial state hash: {state1_hash}")

# --- Copy to simulate user's folder ---
print("\n--- 3. Copying initial state to target folder ---")
shutil.copytree(root_dir, target_dir, dirs_exist_ok=True)
print(f"Copied {root_dir} to {target_dir}")
# Verify that the target state matches
assert GetStateHash(GetState(str(target_dir), exclude=exclude_pattern)) == state1_hash

# --- Making changes in the source folder ---
print("\n--- 4. Making changes in the source folder ---")
os.remove(root_dir / "readme.txt") # Remove a file
write_file(root_dir / "data" / "file1.txt", "data v2") # Modify a file
write_file(root_dir / "new_module.py", "# New feature") # Add a file
print("- Removed readme.txt")
print("* Modified data/file1.txt")
print("+ Added new_module.py")

# --- Get the new state ---
print("\n--- 5. Getting new state after changes ---")
state2 = GetState(str(root_dir), exclude=exclude_pattern)
print("New state (State 2):")
print(state2)
state2_hash = GetStateHash(state2)
print(f"New state hash: {state2_hash}")

# --- Calculate the difference ---
print("\n--- 6. Calculating the difference between states ---")
diff = GetDiff(state1, state2)
print("Difference (Diff):")
# Print only keys for brevity
print(f"  Removed: {diff['removed']}")
print(f"  Added: {diff['added']}")
print(f"  Changed: {diff['changed']}")
print(f"  Source State Hash: {diff['source_state']}")
print(f"  Target State Hash: {diff['target_state']}")
# Verify state hashes in the diff
assert diff['source_state'] == state1_hash
assert diff['target_state'] == state2_hash

# --- Create the patch ---
print(f"\n--- 7. Creating the patch file: {patch_file} ---")
CreatePatch(str(root_dir), str(patch_file), diff)
print(f"Patch created.")
assert patch_file.exists()

# --- Apply the patch ---
print(f"\n--- 8. Applying the patch to the target folder: {target_dir} ---")
# Before applying, ensure the target state is still state1
assert GetStateHash(GetState(str(target_dir), exclude=exclude_pattern)) == state1_hash
ApplyPatch(str(target_dir), str(patch_file), exclude=exclude_pattern)

# --- Verify the result ---
print("\n--- 9. Verifying target folder state after patch ---")
state_target_after = GetState(str(target_dir), exclude=exclude_pattern)
state_target_after_hash = GetStateHash(state_target_after)
print("Target folder state after patch:")
print(state_target_after)
print(f"Target folder state hash after patch: {state_target_after_hash}")

# The target folder state should now match state2
assert state_target_after == state2, "Target folder state does not match expected State 2"
assert state_target_after_hash == state2_hash, "Target folder state hash does not match expected State 2 hash"
print("\nSuccess! Target folder successfully updated using the patch.")

# --- Cleanup ---
# shutil.rmtree(base_path)
# print(f"\nWorkspace folder {base_path} removed.")

````

## Testing

The module includes a test suite (`tests.py`) using `pytest`. To run the tests, execute `pytest` in the project's root folder.

## Source Code:

  * [https://github.com/vpuhoff/stateman](https://github.com/vpuhoff/stateman)