# Analysis Project Case Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GAMMA baseline and interferogram workflows operate inside an explicit formal case root, publish portable case-aware manifests, and stop Analysis from creating figures or quicklooks.

**Architecture:** Add one Analysis-owned path boundary that separates project inputs from case-owned outputs. Existing component CLI labels such as `--case main` remain selectors, while every CFG supplies the formal `case_root` (`S1/ASCENDING_128`) and canonical stage paths. Readers keep schema-v1 Analysis manifest compatibility; new writers emit schema-v2 manifests with `case_id` and project-relative cross-stage references.

**Tech Stack:** Python 3.10+, `pathlib`, frozen dataclasses, strict `configparser`, JSON, `unittest`, injected GAMMA command runners.

**Spec:** `docs/superpowers/specs/2026-10-14-project-driven-study-layout-design.md`

## Global Constraints

- Analysis owns scientific products under `<case_root>/ANALYSIS/` and logs under `<case_root>/LOG/ANALYSIS/`; it never writes PRE or Visualization products.
- A formal case root is exactly two uppercase POSIX components such as `S1/ASCENDING_128` or `SAOCOM/GUIZHOU`.
- Project inputs may come from anywhere inside the resolved research project; Analysis outputs and logs must remain inside the resolved case root.
- Symlink resolution must not permit an input to escape the project or an output/config path to escape the case.
- Baseline output is `<case_root>/ANALYSIS/GAMMA/BASELINE`; interferogram output is `<case_root>/ANALYSIS/GAMMA/INTERFEROGRAM`.
- Pair products use `PAIRS/<master>-<slave>` and multilook products use `MLI`; Analysis creates no `quicklooks`, PNG, or `FIGURES` content.
- New manifests contain no absolute filesystem paths. Same-manifest assets are manifest-relative; cross-stage references are explicitly named project-relative fields.
- Existing registered-stack schema v2 and Analysis schema-v1 manifests remain readable during migration; writers emit only Analysis schema v2.
- No real project data is moved, copied, deleted, or regenerated in this plan.

## Review Focus

- A case-root or output symlink that leaves the project/case must be rejected before any directory is created (Task 1 tests).
- A valid project input belonging to another formal case must not be accepted as this case's PRE or baseline input (Tasks 2-3 tests).
- Legacy schema-v1 baseline manifests must remain readable while schema-v2 identity mismatches fail (Task 3 tests).
- Restart checks must reject old output whose portable case/input identity differs, rather than silently skipping (Tasks 2-3 tests).
- Runs from an unrelated current working directory must resolve CFG paths identically and must not create Analysis quicklooks or figures (Task 4 tests).

---

### Task 1: Analysis Case and Path Boundary

**Files:**
- Create: `src/geodesy_analysis/common/case_paths.py`
- Create: `tests/test_case_paths.py`
- Modify: `src/geodesy_analysis/common/__init__.py`

**Interfaces:**
- Consumes: an existing research project root, a CLI selector label, and CFG `case_root` text.
- Produces: immutable `AnalysisCasePaths`, `bind_analysis_case`, `resolve_project_input`, `resolve_case_input`, and `resolve_case_output` for Tasks 2-3.

- [ ] **Step 1: Write failing binding and containment tests**

  Test `bind_analysis_case(project, "main", "S1/ASCENDING_128")` resolves the project and case without creating directories. Reject absolute, one/three-component, lowercase, backslash, dot, parent, empty, and symlink-escaped case roots. Test project inputs may be outside the case but inside the project, case inputs/outputs must remain inside the case, and future outputs beneath an escaping symlink fail.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_case_paths -v`

  Expected: import failure because `geodesy_analysis.common.case_paths` does not exist.

- [ ] **Step 3: Implement the immutable boundary**

  Create:

  ```python
  @dataclass(frozen=True)
  class AnalysisCasePaths:
      label: str
      case_id: str
      project_root: Path
      case_root: Path

  def bind_analysis_case(project_root: str | Path, label: str, case_root: str | Path) -> AnalysisCasePaths: ...
  def resolve_project_input(paths: AnalysisCasePaths, value: str | Path, *, must_exist: bool = True) -> Path: ...
  def resolve_case_input(paths: AnalysisCasePaths, value: str | Path, *, must_exist: bool = True) -> Path: ...
  def resolve_case_output(paths: AnalysisCasePaths, value: str | Path) -> Path: ...
  ```

  Preserve raw relative path text long enough to reject `~`, empty components, `.`/`..`, absolute paths, and backslashes. Resolve existing symlinks before containment checks and never create a path.

- [ ] **Step 4: Run focused and existing common-path tests**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_case_paths tests.test_workflow_common -v`

  Expected: all tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/geodesy_analysis/common tests/test_case_paths.py
  git commit -m "Add Analysis case path boundary"
  ```

### Task 2: Case-Aware GAMMA Baseline Workflow

**Files:**
- Modify: `src/geodesy_analysis/insar/baseline_selection/gamma/models.py`
- Modify: `src/geodesy_analysis/insar/baseline_selection/gamma/config.py`
- Modify: `src/geodesy_analysis/insar/baseline_selection/gamma/plan.py`
- Modify: `src/geodesy_analysis/insar/baseline_selection/gamma/runner.py`
- Modify: `tests/test_gamma_baseline_config.py`
- Modify: `tests/test_gamma_baseline_plan.py`
- Modify: `tests/test_gamma_baseline_runner.py`
- Modify: `tests/test_gamma_baseline_cli.py`

**Interfaces:**
- Consumes: Task 1 `AnalysisCasePaths`; legacy registered-stack schema v2 under canonical case PRE input.
- Produces: a case-bound baseline plan, case-local logs, and schema-v2 `baseline_manifest.json` consumed by Task 3 and Visualization.

- [ ] **Step 1: Write failing canonical CFG tests**

  Require `case_root` in every `[case:<label>]`. Use `S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json` and `S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE`; assert the model exposes `case_id == "S1/ASCENDING_128"`. Reject a PRE path from another case, noncanonical output, output symlink escape, and missing/unknown `case_root`.

- [ ] **Step 2: Run config/plan tests and verify RED**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_config tests.test_gamma_baseline_plan -v`

  Expected: failures because the model/config do not bind a formal case.

- [ ] **Step 3: Bind baseline configuration to Task 1 paths**

  Add `paths: AnalysisCasePaths` to `GammaBaselineCase`, retain `name` as a read-only property returning `paths.label`, and expose `case_id`, `project_root`, and `case_root` properties. Require the two canonical input/output paths exactly after symlink-safe resolution; keep `--case main` selection behavior unchanged.

- [ ] **Step 4: Write failing portable writer and restart tests**

  Assert logs go to `S1/ASCENDING_128/LOG/ANALYSIS/GAMMA/BASELINE`, no PNG is created, and schema-v2 manifest/provenance contain `case_id`, `backend`, and `registered_stack_project_path` without the absolute temporary project path. Change `case_id` or the registered-stack project path in an existing output and assert restart rejects it.

- [ ] **Step 5: Run runner/CLI tests and verify RED**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_runner tests.test_gamma_baseline_cli -v`

  Expected: failures on legacy log placement and schema-v1/absolute provenance output.

- [ ] **Step 6: Implement schema-v2 baseline publication**

  Write project-relative cross-stage references and manifest-relative owned assets. Set `schema_version = 2`, `case_id`, and `backend = {"name": "gamma"}`. Keep numerical commands, network tables, signatures, atomic publication, and progress events unchanged.

- [ ] **Step 7: Run all baseline tests**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_config tests.test_gamma_baseline_plan tests.test_gamma_baseline_runner tests.test_gamma_baseline_cli -v`

  Expected: all tests pass.

- [ ] **Step 8: Commit**

  ```bash
  git add src/geodesy_analysis/insar/baseline_selection/gamma tests/test_gamma_baseline_*.py
  git commit -m "Bind GAMMA baseline to formal cases"
  ```

### Task 3: Portable GAMMA Interferogram Workflow

**Files:**
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/models.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/config.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/plan.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/runner.py`
- Modify: `tests/test_gamma_interferogram_config.py`
- Modify: `tests/test_gamma_interferogram_plan.py`
- Modify: `tests/test_gamma_interferogram_runner.py`
- Modify: `tests/test_gamma_interferogram_cli.py`

**Interfaces:**
- Consumes: Task 1 case paths and Task 2 schema-v2 baseline manifest; remains able to read schema-v1 baseline manifests during migration.
- Produces: schema-v2 case-aware interferogram manifest with `MLI/` and `PAIRS/` owned assets and no visualization products.

- [ ] **Step 1: Write failing case/input identity tests**

  Require `case_root`; require canonical registered stack, baseline manifest, radar height under case PRE geometry, and exact interferogram output. Assert another case's baseline/height and symlink escapes fail. Add schema-v2 baseline reader tests for matching `case_id` and project-relative stack path, mismatched identity, traversal, missing target, and legacy schema-v1 compatibility.

- [ ] **Step 2: Run config/plan tests and verify RED**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_config tests.test_gamma_interferogram_plan -v`

  Expected: failures because case identity and schema-v2 fields are not implemented.

- [ ] **Step 3: Implement case-bound configuration and manifest reading**

  Add `paths: AnalysisCasePaths` to `GammaInterferogramCase` with the same compatibility properties as Task 2. For schema v2, require `case_id`, `backend.name == "gamma"`, and `registered_stack_project_path`; resolve it within the project and require it equals the configured registered stack. Preserve current schema-v1 digest/polarization/network validation.

- [ ] **Step 4: Write failing output-layout and no-quicklook tests**

  Assert run output uses `MLI/` and `PAIRS/<date-pair>/`, logs use `S1/ASCENDING_128/LOG/ANALYSIS/GAMMA/INTERFEROGRAM`, and neither `quicklooks`, PNG, nor `FIGURES` is created even when a legacy quicklook callback is supplied. Assert schema-v2 manifest/provenance contain no absolute project path and restart rejects changed case/input identity.

- [ ] **Step 5: Run runner/CLI tests and verify RED**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_runner tests.test_gamma_interferogram_cli -v`

  Expected: failures on lowercase directories, quicklook creation, legacy logs, and absolute references.

- [ ] **Step 6: Implement portable interferogram publication**

  Remove quicklook directory/callback execution while retaining `quicklook_renderer=None` as an ignored compatibility keyword for existing callers. Preserve scientific GAMMA commands, and publish schema v2 with `case_id`, `backend`, `registered_stack_project_path`, `baseline_manifest_project_path`, and `radar_height_project_path`. Owned MLI/pair/provenance paths remain manifest-relative.

- [ ] **Step 7: Run all interferogram tests**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_config tests.test_gamma_interferogram_plan tests.test_gamma_interferogram_runner tests.test_gamma_interferogram_cli -v`

  Expected: all tests pass.

- [ ] **Step 8: Commit**

  ```bash
  git add src/geodesy_analysis/insar/interferogram_generation/gamma tests/test_gamma_interferogram_*.py
  git commit -m "Publish portable interferogram products"
  ```

### Task 4: Examples, Documentation, and Integration Gates

**Files:**
- Modify: `config_examples/gamma_baseline.cfg`
- Modify: `config_examples/gamma_interferogram.cfg`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`
- Modify: `tests/test_architecture.py`
- Modify: `tests/test_config_examples.py` (create if absent)

**Interfaces:**
- Consumes: Tasks 1-3 public CFG and manifest contracts.
- Produces: executable canonical examples and repository-level regression gates for later Preprocessing/Visualization plans.

- [ ] **Step 1: Write failing example/architecture tests**

  Parse both example CFGs in a synthetic `S1/ASCENDING_128` project from an unrelated CWD. Assert `case_root`, `RSLC_SUBSET`, canonical Analysis outputs, case-local logs, `MLI`/`PAIRS`, and no Analysis quicklook/PNG claims. Add a source scan rejecting production references to `LOG/ANALYSIS/.../<case-label>`, `/quicklooks`, Analysis `FIGURES`, and old `ANALYSIS/GAMMA/<direction>` examples.

- [ ] **Step 2: Run documentation gates and verify RED**

  Run: `PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_architecture tests.test_config_examples -v`

  Expected: failures because examples and docs still describe the legacy layout.

- [ ] **Step 3: Update examples and documentation**

  Use `[case:main]`, `case_root = S1/ASCENDING_128`, project-relative canonical inputs/outputs, and explain that the CLI label does not determine directory identity. Document schema-v1 read compatibility, schema-v2 writes, Visualization ownership of all rendering, and that this code change does not migrate real project data.

- [ ] **Step 4: Run the complete suite and static checks**

  Run:

  ```bash
  PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest discover -s tests -v
  PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python -m compileall -q src/geodesy_analysis
  git diff --check
  ```

  Expected: complete suite reports `OK`; compileall and diff check exit 0.

- [ ] **Step 5: Install and run external-CWD help/dry-run gates**

  Install editable with `--no-build-isolation --no-deps`, run both `--help` commands from `/tmp`, and run both dry-runs against a synthetic canonical project. Assert no output or log directory is created.

- [ ] **Step 6: Commit**

  ```bash
  git add config_examples README.md docs src tests
  git commit -m "Document project-driven Analysis cases"
  ```

- [ ] **Step 7: Review and GitHub integration**

  Review the full branch against this plan, confirm no study-project data or runtime products are tracked, verify the configured GitHub remote, then perform the single user-authorized push of the completed feature branch. Do not force-push.

## Deferred to Later Plans

- Writing schema-v3 registered-stack manifests with mandatory `case_id` from Geodesy-Preprocessing.
- Moving or linking real `Gansu_Jishishan_LT1` products into canonical case roots.
- Visualization consumption of schema-v2 baseline/interferogram manifests.
- Filtering, unwrapping, time-series, MintPy, and DS-InSAR migration.
