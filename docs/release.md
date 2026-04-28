# Release

Use this checklist before publishing a public release.

## Verify Metadata

Confirm the repository URLs in `pyproject.toml` match the actual GitHub repository.
Do not upload to TestPyPI or PyPI while the repository is private if the package
metadata points at GitHub URLs that should not be public yet.

```bash
git remote -v
gh auth status
```

## Check Locally

```bash
python3 -m pip install -e '.[dev]'
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest -q
python3 -m mini_eq --check-deps
```

## Build

```bash
rm -rf dist/
python3 -m build
python3 -m twine check dist/*
```

## GitHub Release Automation

Use the `Release` workflow from GitHub Actions after the local checks pass.
The default `dry_run=true` mode builds the wheel and sdist, runs
`twine check dist/*`, and uploads `dist/*` as workflow artifacts without
creating a GitHub release or publishing to a package index.

When creating a release, update the project version first, then dispatch the
workflow with `dry_run=false`, `create_github_release=true`, and
`tag_name=vX.Y.Z`. The workflow creates a GitHub release with generated notes
and attaches the built wheel and sdist. Keep `draft=true` for the first run,
review the generated notes and assets on GitHub, then publish the draft
manually.

For a production GitHub release plus PyPI publish, dispatch with:

```bash
gh workflow run release.yml --repo bhack/mini-eq --ref main \
  -f dry_run=false \
  -f create_github_release=true \
  -f tag_name=vX.Y.Z \
  -f target=main \
  -f draft=true \
  -f prerelease=false \
  -f publish_testpypi=false \
  -f publish_pypi=true
```

If the `pypi` environment requires approval, the publish job will stay in
`waiting` until the deployment is approved in GitHub Actions. The same approval
can be done with `gh` when the logged-in account is allowed to approve:

```bash
run_id=<workflow run id>
gh api "repos/bhack/mini-eq/actions/runs/${run_id}/pending_deployments"
environment_id=1234567890
gh api "repos/bhack/mini-eq/actions/runs/${run_id}/pending_deployments" \
  -X POST \
  -F environment_ids[]="$environment_id" \
  -f state=approved \
  -f comment='Publish vX.Y.Z to PyPI'
```

Draft GitHub release assets use temporary `untagged-*` download URLs. Publish
the draft before using release asset URLs in the Flathub manifest or other
public metadata.

Set `publish_testpypi=true` only after the `testpypi` GitHub environment and
TestPyPI trusted publisher are configured. The TestPyPI job uses
`pypa/gh-action-pypi-publish` with OIDC and does not use API tokens. Keep PyPI
publishing separate until TestPyPI installs have been validated. For a
TestPyPI-only validation run, use `dry_run=false`,
`create_github_release=false`, and `publish_testpypi=true`.

Configure the TestPyPI trusted publisher with:

- PyPI project name: `mini-eq`
- Owner: `bhack`
- Repository: `mini-eq`
- Workflow: `release.yml`
- Environment: `testpypi`

Set `publish_pypi=true` only after the `pypi` GitHub environment and PyPI
trusted publisher are configured. The PyPI job also uses
`pypa/gh-action-pypi-publish` with OIDC and does not use API tokens. Keep the
`pypi` environment protected with required review before publishing production
packages.

Configure the PyPI trusted publisher with:

- PyPI project name: `mini-eq`
- Owner: `bhack`
- Repository: `mini-eq`
- Workflow: `release.yml`
- Environment: `pypi`

## Security

Before changing repository visibility to public:

```bash
git rev-list --count HEAD
git ls-remote --heads origin
git ls-remote --tags origin
leak_pattern='(/home/|/Users/|secret|token|api[_-]?key|github_pat|BEGIN (RSA|OPENSSH|PRIVATE) KEY)'
git grep -n -I -E "$leak_pattern" HEAD -- . \
  ':(exclude)*.png' \
  ':(exclude)AGENTS.md' \
  ':(exclude)docs/release.md'
```

After changing repository visibility to public, enable these GitHub security
features in Settings > Advanced Security:

- Dependency graph
- Dependabot alerts
- Dependabot security updates
- Dependabot version updates
- Secret scanning
- Push protection
- Private vulnerability reporting
- CodeQL code scanning

Then protect `main` with a branch protection rule or ruleset that requires the
`test`, `wireplumber-0-4-compat`, `flatpak`, and `dependency-review` status
checks before merging.

## Test The Wheel

Use `--system-site-packages` so the test environment can see distro-provided GI bindings.

```bash
python3 -m venv --system-site-packages /tmp/mini-eq-wheel-test
/tmp/mini-eq-wheel-test/bin/python -m pip install --upgrade pip
/tmp/mini-eq-wheel-test/bin/python -m pip install dist/*.whl
/tmp/mini-eq-wheel-test/bin/mini-eq --check-deps
/tmp/mini-eq-wheel-test/bin/mini-eq --help
```

## Publish

For GitHub releases, dispatch the `Release` workflow after the local checks
above pass. Verify that the README, package URLs, issue tracker, license, and
screenshots render correctly without a logged-in GitHub session.

Validate package-index publishing on TestPyPI before enabling PyPI publishing.
For production PyPI publishing, dispatch the workflow with `dry_run=false`,
`create_github_release=true`, `tag_name=vX.Y.Z`, and `publish_pypi=true`.
Use Trusted Publishing/OIDC and the separate `pypi` environment rather than
long-lived API tokens.

After the workflow completes:

```bash
gh release view vX.Y.Z --repo bhack/mini-eq --json tagName,isDraft,isPrerelease,assets,url
curl -fsSL https://pypi.org/pypi/mini-eq/json | jq -r '.info.version'
git ls-remote --tags origin vX.Y.Z
```

Publish the draft GitHub release after reviewing its notes and assets. Then use
the published release tarball and SHA-256 for the Flathub repository update.
