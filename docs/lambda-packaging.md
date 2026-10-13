# Reproducible Lambda dependencies

CI installs from each package's `uv.lock` with `uv sync --locked`. Lambda builds
install the generated `requirements-lambda.txt` runtime closure, with exact
versions and wheel/source hashes from that same lockfile. The AWS SDK is bundled
too, so Lambda's managed SDK cannot silently differ from the SDK tested in CI.

CI and both deployment workflows check that the generated files still match
their lockfiles. Pip accepts only hashed binary wheels during the Linux x86_64
Python 3.12 build, preventing an unpinned source-build toolchain from being used.
The export tool version is pinned to uv 0.10.10 in those workflows to
keep generation consistent.

## Updating dependencies

1. Update dependencies and run `uv lock` in the affected package. The API depends
   on the agent, so check both lockfiles when the agent's dependency declarations
   change.
2. From the repository root, regenerate and check the runtime exports:

   ```bash
   python scripts/lambda_requirements.py
   python scripts/lambda_requirements.py --check
   ```

3. Run the package checks with `uv run --locked`, review both the lockfile and
   generated requirement changes, then commit them together. CI rejects a stale
   export.
4. Compare and deploy only the intended named stacks. Check deployed package
   versions, source bytes, health and the approved deployment smoke before
   recording deployment evidence. A successful dependency check does not prove
   provider reliability, policy compliance or production readiness.

The API and agent have separate lockfiles and may intentionally resolve different
versions of shared libraries. Each Lambda uses the lockfile for its own CI job.
