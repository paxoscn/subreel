# Releasing subreel

Publishing is fully automated by [`.github/workflows/release.yml`](../.github/workflows/release.yml):
push a `v*` tag → the workflow builds the sdist + wheel, checks the metadata,
publishes to PyPI through **OIDC trusted publishing**, then opens a GitHub
Release with the artefacts attached. No PyPI API token is stored in the repo or
in GitHub secrets.

## One-time setup (PyPI side)

Trusted publishing needs a *pending publisher* registered before the first
release:

1. Log in to <https://pypi.org> → **Account settings → Publishing → Add a
   pending publisher**.
2. Fill in exactly:

   | Field             | Value        |
   | ----------------- | ------------ |
   | PyPI project name | `subreel`    |
   | Owner             | `paxoscn`    |
   | Repository name   | `subreel`    |
   | Workflow name     | `release.yml` |
   | Environment name  | `pypi`       |

3. In the GitHub repo: **Settings → Environments → New environment → `pypi`**
   (no secrets, no protection rules required).

The `pypi` environment name in the workflow must match the one registered on
PyPI, otherwise the OIDC exchange is rejected.

## Cutting a release

```bash
# 1. bump the version in pyproject.toml (single source of truth)
# 2. move the CHANGELOG [Unreleased] entries under a dated version heading
# 3. commit, then tag and push
git commit -am "chore: release v0.2.0"
git tag -a v0.2.0 -m "v0.2.0"
git push origin main --follow-tags
```

Watch the run under **Actions → Release**. Afterwards:

- <https://pypi.org/project/subreel/> shows the new version;
- the GitHub Release carries `subreel-0.2.0.tar.gz` and
  `subreel-0.2.0-py3-none-any.whl`;
- `pip install subreel` works.

## After the first publish

Two cosmetic follow-ups in `README.md` / `README.zh-CN.md`:

1. Uncomment the commented-out PyPI badge in the badge block at the top.
2. The installation section can drop the "not on PyPI yet" wording.

## Local dry run

Exactly what CI does, without touching PyPI:

```bash
pip install --upgrade build twine
python -m build                       # dist/ sdist + wheel
python -m twine check --strict dist/* # metadata must PASS
python -m venv /tmp/smoke
/tmp/smoke/bin/pip install dist/*.whl
/tmp/smoke/bin/subreel --version      # console entry point works
```

`TestPyPI` can be used to rehearse: register a pending publisher for the
*TestPyPI* project as well, then add an `--repository-url
https://test.pypi.org/legacy/` (plus `skip-existing: true`) variant of the
publish step if you want the rehearsal to live in the same workflow.