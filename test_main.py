import pytest
from stateman import GetState, GetDiff, CreatePatch, ApplyPatch, GetStateHash, get_hash
import os
import shutil
from pathlib import Path
import json

# --- Helper Functions ---

def write_file(filepath, text):
    """Вспомогательная функция для создания файла с текстом."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f:
        f.write(text)

def setup_test_dirs(tmp_path):
    """Создает базовые директории для теста."""
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    patch_file = tmp_path / "test.patch"
    source_dir.mkdir()
    target_dir.mkdir()
    return source_dir, target_dir, patch_file

# --- Test Cases ---

def test_get_state_empty_dir(tmp_path):
    """Тестирует GetState на пустой директории."""
    source_dir, _, _ = setup_test_dirs(tmp_path)
    state = GetState(str(source_dir))
    assert state == {}

def test_get_state_simple(tmp_path):
    """Тестирует GetState с несколькими файлами."""
    source_dir, _, _ = setup_test_dirs(tmp_path)
    file1_path = source_dir / "file1.txt"
    file2_path = source_dir / "file2.bin"
    write_file(file1_path, "content1")
    write_file(file2_path, "content2")

    state = GetState(str(source_dir))
    expected_state = {
        "file1.txt": get_hash(file1_path),
        "file2.bin": get_hash(file2_path),
    }
    assert state == expected_state

def test_get_state_subdirs(tmp_path):
    """Тестирует GetState с поддиректориями."""
    source_dir, _, _ = setup_test_dirs(tmp_path)
    file1_path = source_dir / "file1.txt"
    sub_dir = source_dir / "subdir"
    file2_path = sub_dir / "file2.txt"
    write_file(file1_path, "content1")
    write_file(file2_path, "sub content")

    state = GetState(str(source_dir))
    expected_state = {
        "file1.txt": get_hash(file1_path),
        f"subdir/file2.txt": get_hash(file2_path), # Используем '/' как разделитель в state
    }
    assert state == expected_state

def test_get_state_exclude(tmp_path):
    """Тестирует GetState с параметром exclude."""
    source_dir, _, _ = setup_test_dirs(tmp_path)
    file1_path = source_dir / "file1.txt"
    git_dir = source_dir / ".git"
    git_file_path = git_dir / "config"
    write_file(file1_path, "content1")
    write_file(git_file_path, "git stuff")

    # Исключаем папку .git
    exclude_pattern = f".git{os.path.sep}"
    state = GetState(str(source_dir), exclude=exclude_pattern)
    expected_state = {
        "file1.txt": get_hash(file1_path),
    }
    assert state == expected_state
    assert f".git/config" not in state

def test_get_diff_no_change(tmp_path):
    """Тестирует GetDiff, когда нет изменений."""
    source_dir, _, _ = setup_test_dirs(tmp_path)
    write_file(source_dir / "file1.txt", "content")
    state1 = GetState(str(source_dir))
    state2 = GetState(str(source_dir)) # Состояние то же самое
    diff = GetDiff(state1, state2)

    assert diff['added'] == []
    assert diff['removed'] == []
    assert diff['changed'] == []
    assert diff['source_state'] == GetStateHash(state1)
    assert diff['target_state'] == GetStateHash(state2)
    assert diff['source_state'] == diff['target_state']

def test_get_diff_add_remove_change(tmp_path):
    """Тестирует GetDiff с добавлением, удалением и изменением файлов."""
    source_dir, _, _ = setup_test_dirs(tmp_path)

    # Состояние 1
    write_file(source_dir / "file_keep.txt", "keep")
    write_file(source_dir / "file_change.txt", "original")
    write_file(source_dir / "file_remove.txt", "remove")
    state1 = GetState(str(source_dir))
    state1_hash = GetStateHash(state1)

    # Изменения для состояния 2
    os.remove(source_dir / "file_remove.txt")
    write_file(source_dir / "file_change.txt", "changed")
    write_file(source_dir / "file_add.txt", "added")
    state2 = GetState(str(source_dir))
    state2_hash = GetStateHash(state2)

    diff = GetDiff(state1, state2)

    assert sorted(diff['added']) == ["file_add.txt"]
    assert sorted(diff['removed']) == ["file_remove.txt"]
    assert sorted(diff['changed']) == ["file_change.txt"]
    assert "file_keep.txt" not in diff['added'] + diff['removed'] + diff['changed']
    assert diff['source_state'] == state1_hash
    assert diff['target_state'] == state2_hash
    assert state1_hash != state2_hash
    assert diff['md5']['file_add.txt'] == state2['file_add.txt']
    assert diff['md5']['file_change.txt'] == state2['file_change.txt']

def test_patch_apply_simple(tmp_path):
    """Тестирует полный цикл CreatePatch и ApplyPatch для простых изменений."""
    source_dir, target_dir, patch_file = setup_test_dirs(tmp_path)

    # Начальное состояние (будет в target_dir)
    write_file(source_dir / "file1.txt", "content1")
    write_file(source_dir / "file_to_remove.txt", "delete me")
    state1 = GetState(str(source_dir))
    shutil.copytree(str(source_dir), str(target_dir), dirs_exist_ok=True) # Копируем в target

    # Вносим изменения в source_dir
    os.remove(source_dir / "file_to_remove.txt")
    write_file(source_dir / "file1.txt", "changed content")
    write_file(source_dir / "new_file.txt", "i am new")
    state2 = GetState(str(source_dir))

    # Создаем и применяем патч
    diff = GetDiff(state1, state2)
    CreatePatch(str(source_dir), str(patch_file), diff)
    apply_result = ApplyPatch(str(target_dir), str(patch_file))

    # Проверки
    assert apply_result is True
    target_state_after_patch = GetState(str(target_dir))
    assert target_state_after_patch == state2 # Состояния должны совпадать
    assert not (target_dir / "file_to_remove.txt").exists()
    assert (target_dir / "file1.txt").read_text() == "changed content"
    assert (target_dir / "new_file.txt").read_text() == "i am new"
    assert GetStateHash(target_state_after_patch) == diff['target_state']

def test_patch_apply_complex_subdirs(tmp_path):
    """Тестирует патчи с поддиректориями."""
    source_dir, target_dir, patch_file = setup_test_dirs(tmp_path)
    sub_source = source_dir / "sub"
    sub_target = target_dir / "sub"

    # Начальное состояние
    write_file(source_dir / "root.txt", "root")
    write_file(sub_source / "sub_keep.txt", "keep")
    write_file(sub_source / "sub_change.txt", "original sub")
    state1 = GetState(str(source_dir))
    shutil.copytree(str(source_dir), str(target_dir), dirs_exist_ok=True)

    # Изменения в source
    os.remove(source_dir / "root.txt") # Удаляем из корня
    write_file(sub_source / "sub_change.txt", "changed sub") # Меняем в подпапке
    write_file(sub_source / "sub_add.txt", "added sub") # Добавляем в подпапку
    state2 = GetState(str(source_dir))

    # Патчим
    diff = GetDiff(state1, state2)
    CreatePatch(str(source_dir), str(patch_file), diff)
    ApplyPatch(str(target_dir), str(patch_file))

    # Проверки
    target_state_after_patch = GetState(str(target_dir))
    assert target_state_after_patch == state2
    assert not (target_dir / "root.txt").exists()
    assert (sub_target / "sub_keep.txt").exists()
    assert (sub_target / "sub_change.txt").read_text() == "changed sub"
    assert (sub_target / "sub_add.txt").read_text() == "added sub"

def test_apply_patch_wrong_state(tmp_path):
    """Тестирует ApplyPatch, когда состояние target не совпадает с source_state патча."""
    source_dir, target_dir, patch_file = setup_test_dirs(tmp_path)

    # Состояние 1 (для патча)
    write_file(source_dir / "file1.txt", "state1")
    state1 = GetState(str(source_dir))

    # Состояние 2 (для патча)
    write_file(source_dir / "file1.txt", "state2")
    write_file(source_dir / "file2.txt", "state2_new")
    state2 = GetState(str(source_dir))

    # Создаем патч state1 -> state2
    diff = GetDiff(state1, state2)
    CreatePatch(str(source_dir), str(patch_file), diff)

    # target_dir имеет другое состояние (не state1)
    write_file(target_dir / "other_file.txt", "completely different")

    # Попытка применить патч должна вызвать исключение
    with pytest.raises(Exception, match="The current state of the target directory does not match the source state required by the patch"):
        ApplyPatch(str(target_dir), str(patch_file))

def test_apply_patch_already_applied(tmp_path):
    """Тестирует ApplyPatch, когда target уже в целевом состоянии."""
    source_dir, target_dir, patch_file = setup_test_dirs(tmp_path)

    # Состояние 1
    write_file(source_dir / "file1.txt", "state1")
    state1 = GetState(str(source_dir))

    # Состояние 2 (целевое)
    write_file(source_dir / "file1.txt", "state2")
    state2 = GetState(str(source_dir))
    state2_hash = GetStateHash(state2)

    # Копируем состояние 2 в target
    shutil.copytree(str(source_dir), str(target_dir), dirs_exist_ok=True)
    target_state_before = GetState(str(target_dir))
    assert GetStateHash(target_state_before) == state2_hash # Убедимся, что target уже в state2

    # Создаем патч state1 -> state2
    # Для этого временно вернем source в state1
    write_file(source_dir / "file1.txt", "state1")
    diff = GetDiff(state1, state2) # state2 все еще хранит данные для file1="state2"
    # Вернем source в state2, чтобы CreatePatch взял правильный файл
    write_file(source_dir / "file1.txt", "state2")
    CreatePatch(str(source_dir), str(patch_file), diff)


    # Применяем патч к target_dir (который уже в state2)
    # Ожидаем, что функция вернет True и ничего не изменит
    apply_result = ApplyPatch(str(target_dir), str(patch_file))
    assert apply_result is True

    # Проверяем, что состояние target не изменилось
    target_state_after = GetState(str(target_dir))
    assert GetStateHash(target_state_after) == state2_hash
    assert target_state_after == target_state_before
