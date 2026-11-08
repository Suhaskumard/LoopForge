# ADR-0015: Language profiles and repository input

**Status:** accepted (Phase 8)

**Context.** Until Phase 7 every task was a greenfield FastAPI + pytest project: the Planner, Builder,
Verifier, quality checks, dependency policy and sandbox all assumed Python, `Project.language` was stored
but never read, and bug-fix benchmark tasks pasted the broken code into the requirement (ADR-0012).

**Decision.**
- `execution/languages.py::LanguageProfile` describes what differs per language: test command, report
  parsing, lint command, dependency manifest and policy, test-file naming, prompt labels, sandbox image.
  `python` keeps the previous behaviour exactly; `javascript` covers JavaScript and TypeScript (Jest + ESLint,
  `ts-jest` preinstalled). Everything goes through the existing allowlisted `run_command` and the same
  isolation flags (ADR-0008); the image is chosen from the (already allowlisted) command, so a profile cannot
  pick an arbitrary image.
- **No network in the sandbox, so no `npm install`.** The Node image preinstalls an approved package set
  (`sandbox/node/approved_packages_js.txt`); `package.json` may only name those exact versions and may not
  define install-time scripts. Same model as `approved_packages.txt`.
- **Repository input.** A task has `source_type` none|zip|git. A zip is uploaded to `POST /tasks/{id}/source`
  (size-capped before reading); a git URL is cloned in `execute_run`, i.e. in the worker in queue mode, never
  in a request. The result is written as **iteration 0** (`iter_0/`, no `Iteration` row), so iteration 1 is
  `fork_iteration(from_number=0)` and `diff_iterations(0, 1)` shows the change against the original.
- **Repo understanding is deterministic.** `agents/repo_map.py` builds a bounded map (tree, entry points, test
  files, symbols via `ast`/regex) with no LLM and no execution; it is given to the Planner as untrusted input.
- **Changes are whole files for the touched files only** (deviation from the roadmap's "patches"): the plan
  lists only the files to `modify`/`create`, the Builder sees their current content and returns exactly those
  files, and everything else is carried over from the seed. A unified-diff output schema was not added; the diff
  view already renders the patch. Repair is unchanged (it already edits an existing tree).
- **Anti-cheating on existing suites.** The decision engine's "suite may not shrink" baseline starts at a
  static count of the repository's own tests, so deleting tests cannot produce a green run.

**Threat model for untrusted repositories.** Nothing from a repository is executed outside the sandbox. On
import: archive/file-count/per-file/total/depth limits; zip-slip, absolute and drive paths rejected before any
prefix stripping; symlinks and special files skipped; per-entry compression-ratio and real-read caps against
zip bombs; `.git`, `node_modules`, build dirs, binaries and non-UTF-8 files skipped; paths must satisfy the same
rules as generated code (so dotfiles and extension-less files such as `Dockerfile`/`.env` are not imported).
Git: https only, no credentials, public-address check on every resolved IP, `--depth 1`, no submodules, no
hooks/templates, `protocol.allow=never` except https, timeout. **Secrets:** a file matching a credential pattern
or secret filename is excluded from the seed and so from every prompt; the audit event records the file and the
kind, never the value.

**Consequences / limits.**
- Dotfiles (`.eslintrc`, `.github/`) and extension-less files are not imported; a repository that needs them to
  run its tests will fail honestly rather than run partially.
- The repo's own dependency manifest must satisfy the approved-package policy, otherwise the Verifier blocks the
  run before execution (the sandbox could not install them anyway).
- Secret scanning is pattern-based; unusual formats pass. Excluding a source file can break the repo's tests.
- The git clone downloads into a temporary directory before size checks (a `blob:limit` filter helps only if the
  server supports it); DNS rebinding between the address check and `git clone` is not prevented.
- ESLint runs without a project config unless the repo ships `eslint.config.js`; no JS security scanner is in
  the image, so JS runs have no Bandit equivalent and no "clean scan" is claimed.
- **Not exercised in this environment:** the Node sandbox image build and a real Docker JS run, a real remote
  `git clone`, and any real-model quality on repo/JS tasks. Jest report parsing was checked against real Jest 29.7
  output; the 20 new benchmark tasks were validated with real pytest/Jest (reference passes, repo/empty fails).
