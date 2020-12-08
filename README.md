Creating binary patch files containing changes in the directory

## Simple usage :
```
from stateman import GetState, GetDiff, CreatePatch, ApplyPatch
import os
import shutil
patch_file="new.patch"

def write_file(filename, text):
    with open(filename,'w') as f:
        f.write(text)


# Clear workspace
if os.path.exists(".tmp"):
    shutil.rmtree(".tmp")
if os.path.exists(".tmp2"):
    shutil.rmtree(".tmp2")


# Init workspace .tmp with one subfolder
root_dir = os.path.abspath(".tmp")
target_dir = os.path.abspath(".tmp2")
os.makedirs(".tmp")
subfolder = os.path.join(root_dir,".git")
os.makedirs(subfolder)

# Create files in workspace
write_file(os.path.join(subfolder,"testfile1.txt"), "test1")
write_file(os.path.join(subfolder,"testfile2.txt"), "test2")
write_file(os.path.join(root_dir,"testfile3.txt"), "test3")
write_file(os.path.join(root_dir,"testfile4.txt"), "test4")

# Get state of workspace
state1 = GetState(root_dir, exclude = r'.git'+os.path.sep)
print(state1)

# Make a copy of workspace
shutil.copytree(root_dir, target_dir)

# Make a changes
os.remove(os.path.join(subfolder,"testfile2.txt"))
os.remove(os.path.join(root_dir,"testfile4.txt"))
write_file(os.path.join(subfolder,"testfile2.txt"), "changed")

# Get state of workspace after changes
state2 = GetState(root_dir, exclude = r'.git'+os.path.sep)
print(state2)

# Get diff between spaces
diff = GetDiff(state1, state2)
print (diff)

# Create patch file
CreatePatch(root_dir, patch_file, diff)  

# Apply patch on copy of workspace, maked before changes
ApplyPatch(target_dir, patch_file, exclude = r'.git'+os.path.sep)

# Copy of workspace after apply patch identical as workspace 
```

## Source Code:
* [https://github.com/vpuhoff/stateman](https://github.com/vpuhoff/stateman)

## Travis CI Deploys:
* [https://travis-ci.com/vpuhoff/patchgen](https://travis-ci.com/vpuhoff/patchgen) [![Build Status](https://travis-ci.com/vpuhoff/patchgen.svg?branch=master)](https://travis-ci.com/vpuhoff/patchgen)