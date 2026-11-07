import hashlib
import json
import os
import shutil
import tempfile
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

# Hash algorithm used for new patches. Old (v1) patches used MD5 and are
# still readable by ApplyPatch via the legacy "md5" metadata format.
DEFAULT_HASH_ALGO = "sha256"
SUPPORTED_HASH_ALGOS = ("sha256", "md5")

# Size of chunks used when hashing / copying files.
_CHUNK_SIZE = 64 * 1024

# Zip-bomb protection defaults for ApplyPatch (can be overridden per call):
# a single member may not declare/expand to more than 4 GiB, all members
# together not more than 16 GiB, and the compression ratio is capped at 1000x.
DEFAULT_MAX_MEMBER_SIZE = 4 * 1024 ** 3
DEFAULT_MAX_TOTAL_SIZE = 16 * 1024 ** 3
DEFAULT_MAX_COMPRESSION_RATIO = 1000

# Define the path separator for the current OS for unification
sep = os.path.sep


class PatchError(Exception):
    """Base class for all stateman patch errors."""


class UnsafePatchPathError(PatchError):
    """A path contained in patch metadata is unsafe (escapes the target directory)."""


class PatchVerificationError(PatchError):
    """Patch content or the resulting state failed an integrity check."""


class PatchFormatError(PatchError):
    """The patch file is not a valid stateman patch."""


def get_hash(filename, algo=DEFAULT_HASH_ALGO):
    """Calculates the hash of a file.

    Reads the file in chunks for efficient handling of large files.

    Args:
        filename (str): Path to the file.
        algo (str): Hash algorithm name, e.g. "sha256" (default) or "md5".

    Returns:
        str: The hex digest of the file, or None if the file could not be read.
    """
    hasher = hashlib.new(algo)
    try:
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                hasher.update(chunk)
    except OSError:
        # File disappeared or is unreadable between steps
        return None
    return hasher.hexdigest()


def find_files(folder, exclude=None, algo=DEFAULT_HASH_ALGO):
    """Recursively finds all files in a directory and calculates their hashes.

    Ignores files/directories whose path contains the `exclude` string.
    Normalizes path separators to '/' for consistency across OS.

    Args:
        folder (str): The root directory to search.
        exclude (str, optional): A string, paths containing it will be excluded.
        algo (str): Hash algorithm used for file hashes.

    Yields:
        tuple: (relative_path, hash) for each found file.
               The relative path uses '/' as a separator.
    """
    if not folder.endswith(os.path.sep):
        folder += os.path.sep

    for root, dirs, files in os.walk(folder):
        if exclude:
            dirs[:] = [d for d in dirs if exclude not in os.path.join(root, d)]

        for file in files:
            filename = os.path.join(root, file)
            relative_path = filename.replace(folder, '').replace("\\", '/')  # Path normalization

            if exclude and exclude in filename:  # Check the full path for exclude
                continue

            file_hash = get_hash(filename, algo)
            if file_hash:  # Ensure the hash was obtained (file wasn't deleted)
                yield relative_path, file_hash


def GetState(folder, exclude=None, algo=DEFAULT_HASH_ALGO):
    """Creates a dictionary representing the state of a directory (file -> hash).

    Args:
        folder (str): Path to the directory.
        exclude (str, optional): Pattern to exclude files/directories.
        algo (str): Hash algorithm used for file hashes.

    Returns:
        dict: Relative file paths (with '/' separator) mapped to their hashes.
    """
    return dict(find_files(folder, exclude, algo))


def GetStateHash(state, algo=DEFAULT_HASH_ALGO):
    """Calculates a single hash for the entire directory state.

    The hash depends on file names and their hashes. Sorting keys ensures
    the same hash for the same state, regardless of file traversal order.

    Args:
        state (dict): The directory state dictionary (result of GetState).
        algo (str): Hash algorithm used for the state digest.

    Returns:
        str: The overall hash of the state as a hexadecimal string.
    """
    hasher = hashlib.new(algo)
    ordered = OrderedDict(sorted(state.items()))
    for k, v in ordered.items():
        hasher.update(k.encode('utf-8'))
        hasher.update(v.encode('utf-8'))
    return hasher.hexdigest()


def GetDiff(state1, state2, algo=DEFAULT_HASH_ALGO):
    """Calculates the difference between two directory states.

    Args:
        state1 (dict): The initial state (file -> hash dictionary).
        state2 (dict): The final state (file -> hash dictionary).
        algo (str): Hash algorithm the states were computed with. It is stored
                    in the diff so ApplyPatch can verify states consistently.

    Returns:
        dict: A dictionary with difference information:
              - 'removed': list[str] - removed files.
              - 'added': list[str] - added files.
              - 'changed': list[str] - changed files (different hashes).
              - 'state': dict - the final state (state2).
              - 'hashes': dict - hashes of added and changed files from state2.
              - 'hash_algo': str - hash algorithm used.
              - 'source_state': str - hash of the initial state (state1).
              - 'target_state': str - hash of the final state (state2).
    """
    keysA = set(state1.keys())
    keysB = set(state2.keys())

    removed = keysA - keysB  # Files present in state1 but not in state2
    added = keysB - keysA   # Files present in state2 but not in state1
    keep = keysA.intersection(keysB)

    changed = [key for key in keep if state1[key] != state2[key]]

    result = {
        'removed': list(removed),
        'added': list(added),
        'changed': list(changed),
        'state': state2,  # Store the final state in the diff
        'hashes': {},  # Hashes of files to be included in the patch
        'hash_algo': algo,
        'source_state': GetStateHash(state1, algo),
        'target_state': GetStateHash(state2, algo)
    }

    allfiles_to_include = set(changed)
    allfiles_to_include.update(added)
    for key in allfiles_to_include:
        result['hashes'][key] = state2[key]

    return result


def ClearPatch(path):
    """Normalizes path separators to be specific to the current OS.

    Converts '/' to '\\' on Windows and vice versa on other systems.
    Paths within diffs and patches are always stored with '/'.

    Args:
        path (str): Path with '/' separators.

    Returns:
        str: Path with separators specific to the current OS.
    """
    if sep == "\\":  # If OS is Windows
        return path.replace("/", "\\")
    else:
        return path.replace("\\", "/")


def safe_join(base, relative_path):
    """Joins `relative_path` (from patch metadata) to `base`, safely.

    Rejects absolute paths, drive letters, backslashes, null bytes and any
    '..' components, and verifies the resolved result stays inside `base`.
    This prevents path-traversal attacks from untrusted patches.

    Args:
        base (str): The target directory (trusted).
        relative_path (str): The path from patch metadata (untrusted).

    Returns:
        str: The safe absolute path of the file inside `base`.

    Raises:
        UnsafePatchPathError: If the relative path is unsafe.
    """
    if not relative_path or "\x00" in relative_path:
        raise UnsafePatchPathError(f"Empty or invalid path in patch metadata: {relative_path!r}")
    if "\\" in relative_path:
        raise UnsafePatchPathError(f"Backslash in patch path (expected '/'): {relative_path!r}")

    pure = PurePosixPath(relative_path)
    if pure.is_absolute():
        raise UnsafePatchPathError(f"Absolute path in patch metadata: {relative_path!r}")
    if any(part == ".." for part in pure.parts):
        raise UnsafePatchPathError(f"Path traversal ('..') in patch metadata: {relative_path!r}")

    base_real = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base_real, *pure.parts))
    # Belt and braces: never escape the base directory.
    try:
        inside = os.path.commonpath([base_real, full]) == base_real
    except ValueError:  # e.g. different drives on Windows
        inside = False
    if not inside:
        raise UnsafePatchPathError(f"Path escapes the target directory: {relative_path!r}")
    return full


def CreatePatch(source_folder, patch_file, diff):
    """Creates a ZIP archive (patch) containing the changes.

    The patch includes metadata (diff information) and the necessary files
    (added and changed), compressed with DEFLATE.

    Args:
        source_folder (str): The folder from which changed and added files are taken.
        patch_file (str): The filename for the created ZIP patch.
        diff (dict): The difference dictionary obtained from GetDiff.

    Raises:
        UnsafePatchPathError: If a path in the diff escapes the source folder.
        PatchError: If a required file is missing from the source folder.
    """
    with ZipFile(patch_file, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("metadata.json", data=json.dumps(diff, indent=4, ensure_ascii=False))

        for file in diff.get('added', []) + diff.get('changed', []):
            source_path = safe_join(source_folder, file)  # Also validates the path
            if not os.path.isfile(source_path):
                raise PatchError(f"File listed in diff not found in source folder: {file}")
            z.write(source_path, arcname=file)


def ApplyPatch(target, patch_file, exclude=None,
               max_member_size=DEFAULT_MAX_MEMBER_SIZE,
               max_total_size=DEFAULT_MAX_TOTAL_SIZE,
               max_compression_ratio=DEFAULT_MAX_COMPRESSION_RATIO):
    """Applies a patch to the target directory.

    Verifies that the current state of the target directory matches the source
    state specified in the patch, deletes, adds, and updates files according
    to the patch metadata, and verifies the final state hash. Every file
    written from the patch is checked against its expected hash.

    The application is transactional: if any step fails (hash mismatch,
    missing archive member, final state mismatch), all changes made so far
    are rolled back and an exception is raised. The target directory is left
    in its original state.

    Zip-bomb protection: each archive member is checked against the declared
    uncompressed size, the compression ratio, a per-member cap and a
    cumulative cap before and during extraction.

    Supports both the current v2 patches (SHA-256, 'hashes' metadata key)
    and legacy v1 patches (MD5, 'md5' metadata key).

    Args:
        target (str): Path to the target directory where the patch is applied.
        patch_file (str): Path to the ZIP patch file.
        exclude (str, optional): Pattern to exclude files when checking the
                                 current state of the target directory.
        max_member_size (int): Maximum uncompressed size of a single archive
                               member in bytes (default 4 GiB).
        max_total_size (int): Maximum total uncompressed size of all members
                              extracted by this patch in bytes (default 16 GiB).
        max_compression_ratio (int): Maximum allowed compression ratio of an
                                     archive member (default 1000).

    Returns:
        bool: True if the patch was successfully applied or if the directory
              was already in the target state.

    Raises:
        FileNotFoundError: If the target directory or patch file does not exist.
        PatchFormatError: If the patch file is invalid (not a ZIP, missing or
                          corrupt metadata.json, unsupported hash algorithm).
        UnsafePatchPathError: If a path in patch metadata is unsafe.
        PatchVerificationError: If the current state of the target directory
                   does not match the patch source state, if an extracted file
                   fails its hash check, or if the final state does not match
                   the patch target state.
        PatchError: For other fatal errors during patch application.
    """
    if not os.path.isdir(target):
        raise FileNotFoundError(f"Target directory not found: {target}")
    if not os.path.isfile(patch_file):
        raise FileNotFoundError(f"Patch file not found: {patch_file}")

    try:
        patch = ZipFile(patch_file, "r")
    except BadZipFile as e:
        raise PatchFormatError(f"Invalid patch file (not a ZIP archive): {patch_file}") from e

    with patch:
        # Read metadata from the patch
        try:
            with patch.open('metadata.json', 'r') as metadata_file:
                diff = json.loads(metadata_file.read().decode('utf-8'))
        except KeyError:
            raise PatchFormatError("Invalid patch file: metadata.json not found.")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise PatchFormatError("Invalid patch file: metadata.json is corrupted.")

        algo = diff.get('hash_algo', 'md5')  # v1 patches have no 'hash_algo'
        if algo not in SUPPORTED_HASH_ALGOS:
            raise PatchFormatError(f"Unsupported hash algorithm in patch: {algo}")

        # v2 patches use 'hashes'; v1 patches used 'md5'
        expected_hashes = diff.get('hashes') or diff.get('md5') or {}

        removed = list(diff.get('removed', []))
        added = list(diff.get('added', []))
        changed = list(diff.get('changed', []))
        files_to_extract = added + changed

        print(f"Patch contains: Removed: {len(removed)}, Added: {len(added)}, Changed: {len(changed)}")

        # Validate every path up front, before touching the file system.
        for filename in removed + files_to_extract:
            safe_join(target, filename)

        # Get the current state of the target directory
        current_state = GetState(target, exclude, algo=algo)
        state_hash = GetStateHash(current_state, algo)

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
            raise PatchVerificationError(
                "The current state of the target directory does not match the source state required by the patch."
            )

        # --- Applying changes (transactionally) ---

        # Backup directory (outside the target tree) used for rollback.
        target_parent = os.path.dirname(os.path.abspath(target)) or os.path.curdir
        try:
            backup_dir = tempfile.mkdtemp(prefix=".stateman-backup-", dir=target_parent)
        except OSError:
            backup_dir = tempfile.mkdtemp(prefix="stateman-backup-")

        # (relative_path -> backup location) for files we replace/delete,
        # and list of files we created (did not exist before).
        backed_up = {}
        created = []
        total_extracted = 0
        # Current umask, used to give extracted files the same permissions
        # they would get from a plain open(path, "wb") (mkstemp uses 0600).
        umask = os.umask(0)
        os.umask(umask)

        def _rollback():
            """Restore the target directory to its pre-patch state."""
            for rel in created:
                try:
                    os.remove(safe_join(target, rel))
                except OSError:
                    pass
            for rel, backup_path in backed_up.items():
                try:
                    original = safe_join(target, rel)
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                    shutil.move(backup_path, original)
                except OSError:
                    pass
            shutil.rmtree(backup_dir, ignore_errors=True)

        try:
            print("Applying patch...")

            # 1. Back up every file that will be deleted or replaced
            for filename in removed + changed:
                original = safe_join(target, filename)
                if os.path.isfile(original):
                    backup_path = os.path.join(backup_dir, ClearPatch(filename))
                    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                    shutil.move(original, backup_path)
                    backed_up[filename] = backup_path

            # 2. Extract and verify files (added and changed)
            for filename in files_to_extract:
                target_path = safe_join(target, filename)
                target_file_dir = os.path.dirname(target_path)
                Path(target_file_dir).mkdir(parents=True, exist_ok=True)

                try:
                    member = patch.getinfo(filename)
                except KeyError:
                    raise PatchVerificationError(
                        f"File '{filename}' listed in patch metadata but not found in the archive."
                    )

                # Zip-bomb guards, checked against the (untrusted) declared
                # sizes before any decompression happens.
                if member.file_size > max_member_size:
                    raise PatchVerificationError(
                        f"Archive member '{filename}' declares {member.file_size} bytes, "
                        f"which exceeds the per-member limit of {max_member_size}."
                    )
                if member.compress_size and member.file_size > member.compress_size * max_compression_ratio:
                    raise PatchVerificationError(
                        f"Archive member '{filename}' has a suspicious compression ratio "
                        f"({member.file_size} / {member.compress_size}), possible zip bomb."
                    )

                # Extract to a temporary file in the same directory, verify its
                # hash, and only then atomically move it into place. A failure
                # at any point (corrupted stream, hash mismatch) can never
                # leave a partially written file at the target path (issue #4).
                fd, tmp_path = tempfile.mkstemp(prefix=".stateman-tmp-", dir=target_file_dir)
                os.close(fd)
                try:
                    written = 0
                    with patch.open(member) as src, open(tmp_path, "wb") as dst:
                        while True:
                            chunk = src.read(_CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > max_member_size:
                                raise PatchVerificationError(
                                    f"Archive member '{filename}' expanded beyond the "
                                    f"per-member limit of {max_member_size} bytes."
                                )
                            dst.write(chunk)
                    total_extracted += written
                    if total_extracted > max_total_size:
                        raise PatchVerificationError(
                            f"Patch expanded beyond the total size limit of {max_total_size} bytes."
                        )

                    # Verify the hash of the extracted file before moving it into place
                    extracted_hash = get_hash(tmp_path, algo)
                    expected_hash = expected_hashes.get(filename)
                    if not expected_hash:
                        raise PatchVerificationError(
                            f"No expected hash found in patch metadata for {filename}."
                        )
                    if extracted_hash != expected_hash:
                        raise PatchVerificationError(
                            f"Hash mismatch for extracted file {target_path}! "
                            f"Expected {expected_hash}, got {extracted_hash}. Patch is corrupted."
                        )

                    os.chmod(tmp_path, 0o666 & ~umask)  # mkstemp creates 0600
                    os.replace(tmp_path, target_path)  # atomic on POSIX and Windows
                finally:
                    # Clean up the temp file if anything failed before the replace
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass

                if filename not in backed_up:
                    created.append(filename)

                action = "+" if filename in added else "*"
                print(f"{action} Extracted: {target_path}")

            # 3. Delete removed files (already backed up in step 1)
            for filename in removed:
                if filename in backed_up:  # existed and was moved to backup - done
                    print(f"- Removed: {safe_join(target, filename)}")
                else:
                    print(f"Warning: File to remove not found (already removed?): {filename}")

            # 4. Final verification: state after patching must match target_state
            final_state_hash = GetStateHash(GetState(target, exclude, algo=algo), algo)
            if final_state_hash != diff.get('target_state'):
                raise PatchVerificationError(
                    f"Final state hash ({final_state_hash}) does not match patch target state hash "
                    f"({diff.get('target_state')}). Rolling back."
                )
        except Exception:
            _rollback()
            print("Patch application failed. Changes rolled back, target directory restored.")
            raise

        # Success: drop the backup
        shutil.rmtree(backup_dir, ignore_errors=True)
        print("Patch applied successfully.")
        return True
