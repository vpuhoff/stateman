Creating binary patch files containing changes in the directory

root_dir = os.path.abspath(".tmp")

patch_file="new.patch"

# Get snapshot metadata of folder
state1 = GetState(root_dir)

# change files

# Get snapshot metadata of folder after changes
state2 = GetState(root_dir)

# Calculate diff
diff = GetDiff(state1, state2)

# Create patch file
CreatePatch(root_dir, patch_file, diff)  

# Apply patch file
ApplyPatch(root_dir, patch_file)
