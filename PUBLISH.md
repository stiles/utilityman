## How to publish

This project uses `hatchling` to build wheels and `twine` to upload. You can publish to TestPyPI or PyPI.

### Prereqs

- Python 3.9+
- `pip install build twine`
- Environment tokens
  - `PYPI_TEST` for TestPyPI (token value)
  - `PYPI` for PyPI (token value)

### Versioning

- Bump `__version__` in `scorebug/__init__.py`
- Update `CHANGELOG.md` and `README.md`

### Build

```bash
python -m build
```

### Upload

TestPyPI:
```bash
python -m twine upload --repository-url https://test.pypi.org/legacy/ -u __token__ -p "$PYPI_TEST" dist/*
```

PyPI:
```bash
python -m twine upload -u __token__ -p "$PYPI" dist/*
```

### Install from TestPyPI

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple scorebug
```


