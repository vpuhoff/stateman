import pytest

@pytest.fixture
def local():
    pytest.vars = {}