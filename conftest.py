# Ensures the project root is on sys.path so tests can `import tools`,
# `import agent`, and `from utils.data_loader import ...` regardless of where
# pytest is invoked from. pytest adds the directory containing this conftest.py
# to sys.path automatically.
