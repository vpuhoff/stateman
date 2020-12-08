from collections import OrderedDict
from zipfile import ZipFile
from pathlib import Path
import hashlib
import json
import os
sep = os.path.sep

def get_hash(filename):
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def find_files(folder, exclude=None):
    if folder[-1]!=os.path.sep:
        folder+=os.path.sep
    for root, dirs, files in os.walk(folder):
        for file in files:
            filename = os.path.join(root, file)
            if exclude:
                if not exclude in filename:
                    yield filename.replace(folder,'').replace("\\",'/'),get_hash(filename)
            else:
                yield filename.replace(folder,'').replace("\\",'/'),get_hash(filename)
                

def GetState(folder,exclude=None):
    return dict(find_files(folder, exclude))
                           
def GetStateHash(state):
    hashid = hashlib.md5()
    ordered = OrderedDict(sorted(state.items()))
    for k, v in ordered.items(): 
        hashid.update(k.encode())
        hashid.update(v.encode())
    return hashid.hexdigest()
                           
def GetDiff(state1,state2):
    keysA = set(state1.keys())
    keysB = set(state2.keys())
    removed = keysA - keysB
    added = keysB - keysA
    keep = keysA.intersection(keysB)
    changed = [key for key in keep if state1[key]!=state2[key]]
    result = {}
    result['removed'] = list(removed)
    result['added'] = list(added)
    result['changed'] = list(changed)
    result['state'] = state2
    result['md5'] = {}
    result['source_state'] = GetStateHash(state1)
    result['target_state'] = GetStateHash(state2)
    allfiles = set(changed)
    allfiles.update(added)
    for key in allfiles:
        result['md5'][key]=state2[key]
    return result
                                             

def CreatePatch(source_folder, patch_file, diff):
    with ZipFile(patch_file, "w") as z:
        z.writestr("metadata.json", data=json.dumps(diff, indent=4,  ensure_ascii=False))
        for file in diff['added']:
            z.write(os.path.join(source_folder, file),arcname=file)
        for file in diff['changed']:
            z.write(os.path.join(source_folder, file),arcname=file)
                 

def ClearPatch(path):
    if sep == "\\":
        newpath = path.replace("/","\\")
    else:
        newpath = path.replace("\\","/")
    return newpath

def CheckGitRepo(target):
    from subprocess import Popen, PIPE
    process= Popen("git fsck", cwd=target, stdout=PIPE, stderr=PIPE)
    data = process.communicate()
    code = process.wait()
    if code!= 0:
        raise Exception(data[0].decode()+"\n"+data[1].decode())
    return True

def ApplyPatch(target, patch_file, exclude=None):
    with ZipFile(patch_file, "r") as patch:
        with patch.open('metadata.json','r') as metadata:
            diff = json.loads(metadata.read())
        print("Removed: ", len(diff['removed']))
        print("Added: ", len(diff['added']))
        print("Changed: ", len(diff['changed']))
        current_state = GetState(target, exclude)
        state_hash = GetStateHash(current_state)
        print(f"Current state: {state_hash}")
        print(f"Source state: {diff['source_state']}")
        print(f"Target state: {diff['target_state']}")
        if diff['target_state'] ==state_hash:
            #Ничего делать не нужно
            print("The target state corresponds to the patch")
            return True
        else:
            if diff['source_state'] != state_hash:
                print(diff)
                raise Exception("The current state does not match the patch")
            else:
                for filename in diff['removed']:
                    path = ClearPatch(os.path.join(target, filename))
                    if os.path.isfile(path):
                        os.remove(path)
                        print("-: ", path)
                for filename in diff['added']:
                    path = ClearPatch(os.path.join(target, filename))
                    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
                    patch.extract(filename, target)
                    assert get_hash(path)==diff['md5'][filename]
                    print("+: ", path)
                for filename in diff['changed']:
                    path = ClearPatch(os.path.join(target, filename))
                    if os.path.isfile(path):
                        os.remove(path)
                    else:
                        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
                    patch.extract(filename, target)
                    assert get_hash(path)==diff['md5'][filename]
                    print("*: ", path)
                return True
        


