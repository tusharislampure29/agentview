# Publishing a release

Maintainer notes for cutting a release to [PyPI](https://pypi.org/). The package
name `agentview` is registered on first upload; it was confirmed available at the
time of writing.

## One-time setup

1. Create a PyPI account and enable 2FA.
2. Create a scoped **API token** (Account → API tokens). Never use your password.
3. Put it in `~/.pypirc` (or export it per-shell); keep it out of git:

   ```ini
   [pypi]
   username = __token__
   password = pypi-AgEIcHl...        # your token

   [testpypi]
   username = __token__
   password = pypi-AgEIcHl...        # a separate TestPyPI token
   ```

## Cut a release

```bash
# 1. Bump the version in pyproject.toml (and agentview/__init__.py __version__),
#    update CHANGELOG.md, commit.

# 2. Build fresh artifacts.
rm -rf dist build
python -m build                      # -> dist/agentview-X.Y.Z{.tar.gz,-py3-none-any.whl}

# 3. Validate metadata + long-description rendering.
python -m twine check dist/*         # must print PASSED for both

# 4. Smoke-test the built wheel in a throwaway venv.
python -m venv /tmp/av && /tmp/av/bin/pip install dist/*.whl
/tmp/av/bin/agentview --version
/tmp/av/bin/agentview check https://example.com --skip-agent-files

# 5. (Recommended) Upload to TestPyPI first and install from there.
python -m twine upload -r testpypi dist/*
pip install -i https://test.pypi.org/simple/ agentview

# 6. Upload to the real index.
python -m twine upload dist/*

# 7. Tag the release.
git tag -a vX.Y.Z -m "agentview X.Y.Z"
git push origin vX.Y.Z
```

## After publishing

- `pip install agentview`, `pipx install agentview`, and `uvx agentview ...` go live
  within a minute.
- The `[demo]` and `[render]` extras install on demand; `--render` additionally needs
  `python -m playwright install chromium`.
- Versions are immutable on PyPI — you cannot re-upload the same version. Bump and
  re-release to fix a bad artifact.
