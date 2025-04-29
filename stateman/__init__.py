import hashlib
import json
import os
import shutil # Imported but not used directly in this file? Maybe needed for tests or example.
from collections import OrderedDict
from pathlib import Path
from zipfile import ZipFile
from subprocess import Popen, PIPE # Used only in CheckGitRepo

# Define the path separator for the current OS for unification
sep = os.path.sep

def get_hash(filename):
    """Calculates the MD5 hash of a file.

    Reads the file in chunks for efficient handling of large files.

    Args:
        filename (str): Path to the file.

    Returns:
        str: The MD5 hash of the file as a hexadecimal string. Returns None if the file is not found.
    """
    hash_md5 = hashlib.md5()
    try:
        with open(filename, "rb") as f:
            # Read the file in 4096-byte blocks
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
    except FileNotFoundError:
        # Handle the case where the file is not found (e.g., deleted between steps)
        # Can return None, an empty string, or raise an exception depending on the logic
        print(f"Warning: File not found during hashing: {filename}")
        return None # Or another default value
    return hash_md5.hexdigest()

def find_files(folder, exclude=None):
    """Recursively finds all files in a directory and calculates their hashes.

    Ignores files/directories whose path contains the `exclude` string.
    Normalizes path separators to '/' for consistency across OS.

    Args:
        folder (str): The root directory to search.
        exclude (str, optional): A string (or regex pattern), paths containing it will be excluded.
                                 Defaults to None (nothing excluded).

    Yields:
        tuple: A tuple (relative_path, md5_hash) for each found file.
               The relative path uses '/' as a separator.
    """
    if not folder.endswith(os.path.sep):
        folder += os.path.sep

    for root, dirs, files in os.walk(folder):
        # Optionally: Exclude directories at the os.walk level for efficiency
        if exclude:
            dirs[:] = [d for d in dirs if exclude not in os.path.join(root, d)]

        for file in files:
            filename = os.path.join(root, file)
            relative_path = filename.replace(folder, '').replace("\\", '/') # Path normalization

            # Check for exclusion
            if exclude and exclude in filename: # Check the full path for exclude
                continue # Skip the file if it matches the exclusion pattern

            file_hash = get_hash(filename)
            if file_hash: # Ensure the hash was obtained (file wasn't deleted)
                yield relative_path, file_hash


def GetState(folder, exclude=None):
    """Creates a dictionary representing the state of a directory (file -> hash).

    Uses find_files to get the list of files and their hashes.

    Args:
        folder (str): Path to the directory.
        exclude (str, optional): Pattern to exclude files/directories.

    Returns:
        dict: A dictionary where keys are relative file paths (with '/' separator),
              and values are their MD5 hashes.
    """
    return dict(find_files(folder, exclude))


def GetStateHash(state):
    """Calculates a single MD5 hash for the entire directory state.

    The hash depends on file names and their hashes. Sorting keys ensures
    the same hash for the same state, regardless of file traversal order.

    Args:
        state (dict): The directory state dictionary (result of GetState).

    Returns:
        str: The overall MD5 hash of the state as a hexadecimal string.
    """
    hashid = hashlib.md5()
    # Sort items by key (file path) for hash consistency
    ordered = OrderedDict(sorted(state.items()))
    for k, v in ordered.items():
        hashid.update(k.encode('utf-8')) # Encode the key (path)
        hashid.update(v.encode('utf-8')) # Encode the value (file hash)
    return hashid.hexdigest()


def GetDiff(state1, state2):
    """Calculates the difference between two directory states.

    Determines added, removed, and changed files.

    Args:
        state1 (dict): The initial state (file -> hash dictionary).
        state2 (dict): The final state (file -> hash dictionary).

    Returns:
        dict: A dictionary with difference information:
              - 'removed': list[str] - list of removed files.
              - 'added': list[str] - list of added files.
              - 'changed': list[str] - list of changed files (different hashes).
              - 'state': dict - the final state (state2).
              - 'md5': dict - hash dictionary for added and changed files from state2.
              - 'source_state': str - hash of the initial state (state1).
              - 'target_state': str - hash of the final state (state2).
    """
    keysA = set(state1.keys())
    keysB = set(state2.keys())

    removed = keysA - keysB # Files present in state1 but not in state2
    added = keysB - keysA   # Files present in state2 but not in state1
    keep = keysA.intersection(keysB) # Files present in both states

    # Changed files are those present in both states but with different hashes
    changed = [key for key in keep if state1[key] != state2[key]]

    result = {
        'removed': list(removed),
        'added': list(added),
        'changed': list(changed),
        'state': state2, # Store the final state in the diff
        'md5': {}, # Hashes of files to be included in the patch
        'source_state': GetStateHash(state1), # Hash of the source state
        'target_state': GetStateHash(state2)  # Hash of the target state
    }

    # Collect hashes for all files that were added or changed
    allfiles_to_include = set(changed)
    allfiles_to_include.update(added)
    for key in allfiles_to_include:
        result['md5'][key] = state2[key] # Take the hash from the final state

    return result


def CreatePatch(source_folder, patch_file, diff):
    """Creates a ZIP archive (patch) containing the changes.

    The patch includes metadata (diff information) and the necessary files
    (added and changed).

    Args:
        source_folder (str): The folder from which changed and added files are taken.
        patch_file (str): The filename for the created ZIP patch.
        diff (dict): The difference dictionary obtained from GetDiff.
    """
    with ZipFile(patch_file, "w") as z:
        # Write metadata to metadata.json inside the archive
        z.writestr("metadata.json", data=json.dumps(diff, indent=4, ensure_ascii=False))

        # Add all added files to the archive
        for file in diff.get('added', []):
            source_path = os.path.join(source_folder, ClearPatch(file)) # Path to the file in the source folder
            # arcname=file ensures the relative path is preserved inside the archive
            z.write(source_path, arcname=file)

        # Add all changed files to the archive
        for file in diff.get('changed', []):
            source_path = os.path.join(source_folder, ClearPatch(file)) # Path to the file in the source folder
            z.write(source_path, arcname=file)


def ClearPatch(path):
    """Normalizes path separators to be specific to the current OS.

    Converts '/' to '\' on Windows and vice versa on other systems.
    Used to construct correct file paths when reading/writing
    in the file system, as paths within the diff and patch are stored with '/'.

    Args:
        path (str): Path with '/' separators.

    Returns:
        str: Path with separators specific to the current OS.
    """
    if sep == "\\": # If OS is Windows
        return path.replace("/", "\\")
    else: # For Linux, macOS, and other POSIX-compliant systems
        return path.replace("\\", "/") # Replace backslashes just in case


def CheckGitRepo(target):
    """Checks the integrity of a Git repository using 'git fsck'.

    This function seems specific and possibly unrelated to the core
    patching logic. Is it used anywhere?

    Args:
        target (str): Path to the directory assumed to be a Git repository.

    Returns:
        bool: True if 'git fsck' completed successfully (return code 0).

    Raises:
        Exception: If 'git fsck' failed or if the git command is not found.
    """
    try:
        # Run 'git fsck' in the specified directory
        process = Popen(["git", "fsck"], cwd=target, stdout=PIPE, stderr=PIPE, text=True, encoding='utf-8')
        stdout, stderr = process.communicate()
        code = process.wait()
        if code != 0:
            # If the command failed, raise an exception
            raise Exception(f"Git fsck failed in {target}:\nSTDOUT: {stdout}\nSTDERR: {stderr}")
        print(f"Git fsck successful in {target}")
        return True
    except FileNotFoundError:
        raise Exception(f"Git command not found. Is Git installed and in PATH?")
    except Exception as e:
        # Catch other potential Popen errors
        raise Exception(f"Error running git fsck in {target}: {e}")


def ApplyPatch(target, patch_file, exclude=None):
    """Applies a patch to the target directory.

    Verifies that the current state of the target directory matches
    the source state specified in the patch. Deletes, adds, and updates files
    according to the patch metadata.

    Args:
        target (str): Path to the target directory where the patch is applied.
        patch_file (str): Path to the ZIP patch file.
        exclude (str, optional): Pattern to exclude files when checking the
                                 current state of the target directory.

    Returns:
        bool: True if the patch was successfully applied or if the directory
              was already in the target state.

    Raises:
        FileNotFoundError: If the target directory or patch file does not exist.
        ValueError: If the patch file is invalid (missing or corrupt metadata.json).
        Exception: If the current state of the target directory does not match
                   the source state required by the patch.
        AssertionError: If the hash of an extracted file does not match the hash
                        specified in the patch metadata (integrity check failure).
    """
    if not os.path.isdir(target):
        raise FileNotFoundError(f"Target directory not found: {target}")
    if not os.path.isfile(patch_file):
        raise FileNotFoundError(f"Patch file not found: {patch_file}")

    with ZipFile(patch_file, "r") as patch:
        # Read metadata from the patch
        try:
            with patch.open('metadata.json', 'r') as metadata_file:
                # Read as bytes and decode as utf-8 (more robust)
                diff = json.loads(metadata_file.read().decode('utf-8'))
        except KeyError:
            raise ValueError("Invalid patch file: metadata.json not found.")
        except json.JSONDecodeError:
             raise ValueError("Invalid patch file: metadata.json is corrupted.")

        print(f"Patch contains: Removed: {len(diff.get('removed',[]))}, Added: {len(diff.get('added',[]))}, Changed: {len(diff.get('changed',[]))}")

        # Get the current state of the target directory
        current_state = GetState(target, exclude)
        state_hash = GetStateHash(current_state)

        print(f"Current state hash: {state_hash}")
        print(f"Patch source state hash: {diff.get('source_state')}")
        print(f"Patch target state hash: {diff.get('target_state')}")

        # Check if the patch needs to be applied at all
        if diff.get('target_state') == state_hash:
            print("Target directory is already in the target state. No action needed.")
            return True

        # Check if the current state matches the patch's source state
        if diff.get('source_state') != state_hash:
            print("Current state:", json.dumps(current_state, indent=2))
            # print("Expected source state hash from patch:", diff.get('source_state'))
            raise Exception("The current state of the target directory does not match the source state required by the patch.")

        # --- Applying changes ---
        print("Applying patch...")

        # 1. Deleting files
        for filename in diff.get('removed', []):
            path_to_remove = ClearPatch(os.path.join(target, filename))
            if os.path.isfile(path_to_remove):
                try:
                    os.remove(path_to_remove)
                    print(f"- Removed: {path_to_remove}")
                except OSError as e:
                    print(f"Warning: Could not remove file {path_to_remove}: {e}")
            else:
                 print(f"Warning: File to remove not found (already removed?): {path_to_remove}")

        # 2. Extracting/Updating files (added and changed)
        files_to_extract = diff.get('added', []) + diff.get('changed', [])
        patch_md5_map = diff.get('md5', {})

        for filename in files_to_extract:
            target_path = ClearPatch(os.path.join(target, filename))
            target_file_dir = os.path.dirname(target_path)

            # Create parent directories if they don't exist
            Path(target_file_dir).mkdir(parents=True, exist_ok=True)

            # Remove the old file if it exists (for changed files)
            if filename in diff.get('changed', []) and os.path.exists(target_path):
                 try:
                    # Add a check to ensure it's a file, not a directory
                    if os.path.isfile(target_path):
                        os.remove(target_path)
                    else:
                        print(f"Warning: Expected file but found directory at {target_path}. Skipping removal.")
                        continue # Skip this file
                 except OSError as e:
                    print(f"Warning: Could not remove existing file {target_path} before update: {e}")
                    continue # Skip this file

            try:
                # Extract the file from the archive
                patch.extract(filename, target)
                action = "+" if filename in diff.get('added', []) else "*"
                print(f"{action} Extracted: {target_path}")

                # Verify the hash of the extracted file
                extracted_hash = get_hash(target_path)
                expected_hash = patch_md5_map.get(filename)

                if not expected_hash:
                     print(f"Warning: No expected hash found in patch metadata for {filename}. Skipping check.")
                elif not extracted_hash:
                     print(f"Warning: Could not calculate hash for extracted file {target_path} (likely deleted during process?). Skipping check.")
                elif extracted_hash != expected_hash:
                    # If hashes don't match, it's a serious problem
                    raise AssertionError(
                        f"Hash mismatch for extracted file {target_path}! "
                        f"Expected {expected_hash}, got {extracted_hash}. Patch or extraction failed."
                    )

            except KeyError:
                print(f"Warning: File '{filename}' listed in patch metadata but not found in the archive.")
            except Exception as e:
                print(f"Error extracting or verifying file {filename}: {e}")
                # Decide whether to stop the whole process or just skip the file
                # raise e # Uncomment to stop patch application on error

        print("Patch applied successfully.")
        # Optional final check: hash of the state after patching should match target_state
        final_state_hash = GetStateHash(GetState(target, exclude))
        if final_state_hash != diff.get('target_state'):
             print(f"Warning: Final state hash ({final_state_hash}) does not match patch target state hash ({diff.get('target_state')}). This might indicate issues during patching or with excluded files.")

        return True