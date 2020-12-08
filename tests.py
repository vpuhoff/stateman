import pytest
from stateman import GetState, GetDiff, CreatePatch, ApplyPatch
import os
import shutil

def write_file(filename, text):
    with open(filename,'w') as f:
        f.write(text)

def setup_module(module):
    if os.path.exists(".tmp"):
        shutil.rmtree(".tmp")
    if os.path.exists(".tmp2"):
        shutil.rmtree(".tmp2")
    if os.path.isfile("new.patch"):
        os.remove("new.patch")

def teardown_module(module):
    if os.path.exists(".tmp"):
        shutil.rmtree(".tmp")
    if os.path.exists(".tmp2"):
        shutil.rmtree(".tmp2")
    if os.path.isfile("new.patch"):
        os.remove("new.patch")


def test_all(local):
    import example