from stateman import GetState, GetDiff, CreatePatch, ApplyPatch
import os
import shutil

def write_file(filename, text):
    with open(filename,'w') as f:
        f.write(text)

if os.path.exists(".tmp"):
    shutil.rmtree(".tmp")
os.makedirs(".tmp")
root_dir = os.path.abspath(".tmp")
subfolder = os.path.join(root_dir,"subfolder")
os.makedirs(subfolder)
write_file(os.path.join(subfolder,"testfile1.txt"), "test1")
write_file(os.path.join(subfolder,"testfile2.txt"), "test2")
write_file(os.path.join(root_dir,"testfile3.txt"), "test3")
write_file(os.path.join(root_dir,"testfile4.txt"), "test4")
assert os.path.exists(root_dir)
root_dir = os.path.abspath(".tmp")
subfolder = os.path.join(root_dir,"subfolder")
patch_file="new.patch"
state1 = GetState(root_dir)
os.remove(os.path.join(subfolder,"testfile2.txt"))
os.remove(os.path.join(root_dir,"testfile4.txt"))
write_file(os.path.join(subfolder,"testfile2.txt"), "changed")
state2 = GetState(root_dir)
diff = GetDiff(state1, state2)
CreatePatch(root_dir, patch_file, diff)  

write_file(os.path.join(subfolder,"testfile1.txt"), "test1")
write_file(os.path.join(subfolder,"testfile2.txt"), "test2")
write_file(os.path.join(root_dir,"testfile3.txt"), "test3")
write_file(os.path.join(root_dir,"testfile4.txt"), "test4")

ApplyPatch(root_dir, patch_file)