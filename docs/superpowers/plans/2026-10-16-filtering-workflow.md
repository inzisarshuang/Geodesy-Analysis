# InSAR Filtering Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one manifest-driven filtering workflow supporting NL-InSAR, GAMMA BM3D, and GAMMA ADF, and migrate the Gansu analysis products to the stage-first directory layout.

**Architecture:** A backend-neutral filtering layer validates `interferogram_manifest.json`, resolves a method adapter, and atomically publishes one normalized `filtering_manifest.json`. Existing numerical filtering functions remain import-compatible; GAMMA command details stay in method adapters. Project output defaults derive from the selected method and can be overridden explicitly.

**Tech Stack:** Python 3.10+, NumPy, SciPy, `insar-data-adapter`, GAMMA command-line programs, `unittest`, CFG/JSON manifests.

**Spec:** `docs/superpowers/specs/2026-10-16-filtering-unwrapping-design.md`

## Global Constraints

- Read pairs and product roles only from a complete schema-v1 `interferogram_manifest.json`; do not scan legacy `PRODUCT` directories or baseline files.
- Support exactly `nl_insar`, `gamma_bm3d`, and `gamma_adf` in this plan.
- Omitted `output_dir` maps from the input manifest's nearest `ANALYSIS` ancestor to sibling `FILTERING/NL_INSAR`, `GAMMA_BM3D`, or `GAMMA_ADF`; an explicit project-confined path overrides it.
- Do not generate `run_id`, numbered output directories, or compatibility aliases for `coherence_phase*`.
- Preserve old `geodesy_analysis.insar.filtering` public imports.
- Keep project CFG, logs, and generated products outside the code repository.
- Run Python checks with `/home/yilun/miniconda3/envs/envInSAR/bin/python`.

## Review Focus

- A manifest with a missing pair product must fail during planning before any output or log directory is created; pinned in Task 3.
- A user-specified output outside project root must be rejected; pinned in Task 2.
- An existing default output with a different input or parameter digest must report a conflict and must not be renamed automatically; pinned in Task 4.
- BM3D coherence must use the original `pair.tflt` plus master/slave MLI, not the BM3D output; pinned in Task 4.
- ADF first-pass files must remain staging-only when the second pass succeeds or fails; pinned in Task 4.

---

### Task 1: Migrate existing analysis paths to stage-first ownership

**Files:**
- Modify: `config_examples/gamma_baseline.cfg`
- Modify: `config_examples/gamma_interferogram.cfg`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`
- Modify: `docs/design/gamma_baseline_interferogram.md`
- Modify outside repository: `Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/gamma_baseline.cfg`
- Modify outside repository: `Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/gamma_interferogram.cfg`
- Move outside repository: `.../ANALYSIS/GAMMA/BASELINE` to `.../ANALYSIS/BASELINE_SELECTION/GAMMA`
- Move outside repository: `.../ANALYSIS/GAMMA/INTERFEROGRAM` to `.../ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA`

**Interfaces:**
- Consumes: existing baseline/interferogram manifests and project CFG files.
- Produces: canonical stage-first paths consumed by Task 3 and both real-project CFG files.

- [ ] **Step 1: Record the exact old path references**

Run: `rg -n "ANALYSIS/GAMMA/(BASELINE|INTERFEROGRAM)" config_examples docs /mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1/S1/ASCENDING_128/config`

Expected: only baseline/interferogram documentation and the two Gansu analysis CFG files.

- [ ] **Step 2: Update repository examples and documentation**

Replace baseline outputs with `ANALYSIS/BASELINE_SELECTION/GAMMA` and interferogram outputs with `ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA`. Update the documented log hierarchy to stage-first ownership.

- [ ] **Step 3: Move the two Gansu result directories without copying scientific rasters**

Create the two stage directories, move each existing method directory once, remove only the now-empty `ANALYSIS/GAMMA`, and update absolute references inside both manifests and both CFG files.

- [ ] **Step 4: Verify path migration only**

Run: `rg -n "ANALYSIS/GAMMA/(BASELINE|INTERFEROGRAM)" /mnt/beegfs/procesados/yiluntan/Geodesy-Analysis /mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1/S1/ASCENDING_128/config /mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1/S1/ASCENDING_128/ANALYSIS`

Expected: no live configuration or manifest reference; historical design discussion may retain an explicitly labeled old path.

- [ ] **Step 5: Commit**

```bash
git add config_examples docs
git commit -m "Adopt stage-first analysis paths"
```

### Task 2: Preserve the numerical API while creating the filtering package

**Files:**
- Delete: `src/geodesy_analysis/insar/filtering.py`
- Create: `src/geodesy_analysis/insar/filtering/__init__.py`
- Create: `src/geodesy_analysis/insar/filtering/methods/__init__.py`
- Create: `src/geodesy_analysis/insar/filtering/methods/nl_insar.py`
- Modify: `tests/test_filtering.py`

**Interfaces:**
- Consumes: all public functions currently defined in `insar/filtering.py`.
- Produces: the same symbols from `geodesy_analysis.insar.filtering`, plus an implementation module available as `filtering.methods.nl_insar`.

- [ ] **Step 1: Extend the compatibility test**

Add `test_public_functions_are_reexported_from_package`, asserting that the existing import path exposes `resolve_filter_parameters`, `estimate_boxcar_coherence`, `nonlocal_insar_filter`, and `compose_filtered_interferogram` and that each object is defined by `methods.nl_insar`.

- [ ] **Step 2: Run the focused test and confirm the package assertion fails**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering -v`

Expected: FAIL because `filtering` is still a module rather than the planned package.

- [ ] **Step 3: Move the numerical implementation and re-export it**

Move the existing implementation unchanged into `methods/nl_insar.py`. Re-export its current public functions from `filtering/__init__.py`; do not alter formulas or defaults.

- [ ] **Step 4: Run the numerical compatibility test**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/geodesy_analysis/insar/filtering tests/test_filtering.py
git commit -m "Package the NL-InSAR filtering core"
```

### Task 3: Add strict configuration and manifest planning

**Files:**
- Create: `src/geodesy_analysis/insar/filtering/models.py`
- Create: `src/geodesy_analysis/insar/filtering/config.py`
- Create: `src/geodesy_analysis/insar/filtering/plan.py`
- Create: `src/geodesy_analysis/insar/filtering/publication.py`
- Create: `tests/test_filtering_config.py`
- Create: `tests/test_filtering_plan.py`

**Interfaces:**
- Produces: `FilteringMethod`, `FilteringCase`, `FilteringPair`, `InterferogramManifest`, and `FilteringPlan` frozen dataclasses.
- Produces: `load_filtering_config(path: Path) -> tuple[FilteringCase, ...]`.
- Produces: `build_filtering_plan(case: FilteringCase) -> FilteringPlan`.
- Produces: `filtering_input_signature(plan: FilteringPlan) -> str`, `ensure_nonempty(path: Path, label: str) -> Path`, and `gamma_parameter(path: Path, key: str) -> int`.

- [ ] **Step 1: Write configuration tests**

Cover all three method names, method-specific defaults, unknown keys, missing input manifest, explicit output override, default output mapping from the input manifest's case-local `ANALYSIS` ancestor, required explicit output when that ancestor is absent, and rejection of an output outside `[project] root`.

- [ ] **Step 2: Run configuration tests and verify they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering_config -v`

Expected: FAIL because the loader is not defined.

- [ ] **Step 3: Implement models and `load_filtering_config`**

Use the existing strict `[project]`, `[defaults]`, `[case:name]` pattern. Make `output_dir` optional; when omitted, locate the input manifest's nearest ancestor named `ANALYSIS` and append the fixed method directory before applying `validate_within_root`. Require explicit output when no such ancestor exists.

- [ ] **Step 4: Write planning tests**

Create a minimal schema-v1 interferogram manifest and assert deterministic pair order, resolved MLI/differential-interferogram paths, width/line parsing, digest stability, and early failure for missing `pair.tflt`, pair MLI, malformed status/schema, or mismatched byte size.

- [ ] **Step 5: Implement `build_filtering_plan` and publication helpers**

Resolve only manifest-declared assets relative to the manifest directory. Require `status=complete`, `schema_version=1`, unique date pairs, nonempty files, matching MLI shapes, and exact complex/float raster byte sizes.

- [ ] **Step 6: Run the focused configuration and plan tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering_config tests.test_filtering_plan -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/filtering tests/test_filtering_config.py tests/test_filtering_plan.py
git commit -m "Plan manifest-driven InSAR filtering"
```

### Task 4: Implement the three filtering method adapters and atomic runner

**Files:**
- Create: `src/geodesy_analysis/insar/filtering/methods/gamma/__init__.py`
- Create: `src/geodesy_analysis/insar/filtering/methods/gamma/bm3d.py`
- Create: `src/geodesy_analysis/insar/filtering/methods/gamma/adf.py`
- Create: `src/geodesy_analysis/insar/filtering/runner.py`
- Create: `tests/test_filtering_runner.py`

**Interfaces:**
- Produces: `run_nl_insar_pair(pair: FilteringPair, plan: FilteringPlan, output_dir: Path) -> dict[str, Path]`.
- Produces: `bm3d_commands(pair: FilteringPair, plan: FilteringPlan, output_dir: Path) -> tuple[tuple[str, ...], ...]`.
- Produces: `adf_commands(pair: FilteringPair, plan: FilteringPlan, output_dir: Path) -> tuple[tuple[str, ...], ...]`.
- Produces: `run_filtering(plan: FilteringPlan, *, command_runner: object | None = None, progress_sink: Callable[[str], object] | None = None) -> FilteringRunSummary`.

- [ ] **Step 1: Write runner contract tests with a fake GAMMA runner**

Assert exact legacy BM3D arguments, `cc_wave` inputs, exact two-pass ADF arguments, NL-InSAR pair product roles, `coh_ave.coh`, normalized pair paths, provenance, schema-v1 manifest contents, progress events, failed-log preservation, and staging cleanup.

- [ ] **Step 2: Add restart tests**

Assert matching complete output returns `skipped`, while incomplete output or a different digest raises a conflict without creating a numbered directory.

- [ ] **Step 3: Run runner tests and confirm they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering_runner -v`

Expected: FAIL because adapters and runner are not defined.

- [ ] **Step 4: Implement method adapters**

NL-InSAR reads big-endian GAMMA rasters and uses the existing numerical functions. BM3D emits the legacy `bm3d` command followed by `cc_wave` using original `pair.tflt`; ADF emits the `0.4/64/5` pass followed by `0.4/16/5` and never publishes temporary products.

- [ ] **Step 5: Implement atomic batch execution**

Use one staging directory, per-pair logs, normalized `pairs/<pair>/pair.tflt.filt` and `pair.coh.filt`, streaming arithmetic mean coherence, provenance, digest-based restart validation, and final `filtering_manifest.json` publication.

- [ ] **Step 6: Run focused runner and numerical tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering tests.test_filtering_runner -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/filtering tests/test_filtering_runner.py
git commit -m "Run NL-InSAR BM3D and ADF filtering"
```

### Task 5: Add the public CLI, project configuration, and focused real-data check

**Files:**
- Create: `src/geodesy_analysis/insar/filtering/cli.py`
- Create: `tests/test_filtering_cli.py`
- Create: `config_examples/insar_filtering.cfg`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`
- Create outside repository: `Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/insar_filtering.cfg`

**Interfaces:**
- Consumes: `load_filtering_config`, `build_filtering_plan`, and `run_filtering` from Tasks 3–4.
- Produces: installed command `geodesy-analysis-filtering --config PATH --case NAME [--dry-run]`.

- [ ] **Step 1: Write CLI tests**

Assert case selection, all-case execution, `--dry-run` without publication, unknown case exit code, concise summary, and default-output display.

- [ ] **Step 2: Run CLI tests and confirm they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering_cli -v`

Expected: FAIL because the CLI is not defined.

- [ ] **Step 3: Implement the CLI and package entry point**

Follow the existing baseline/interferogram CLI behavior and progress protocol. Add the example CFG with all method-specific parameters and automatic-output comments.

- [ ] **Step 4: Add the Gansu filtering CFG**

Create three active cases pointing at the migrated interferogram manifest: `nl_insar`, `gamma_bm3d`, and `gamma_adf`. Omit `output_dir` in all three so each method exercises its distinct automatic path.

- [ ] **Step 5: Run only the focused repository tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering tests.test_filtering_config tests.test_filtering_plan tests.test_filtering_runner tests.test_filtering_cli -v`

Expected: PASS.

- [ ] **Step 6: Run the Gansu dry-run and one selected real filtering case**

Run the installed source entry through `envInSAR`, first with `--dry-run`, then for the three Gansu method cases on the existing single pair. Check only manifest status, pair count, declared file existence/size, and coherence range; do not rerun preprocessing or unrelated tests.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml README.md config_examples docs src/geodesy_analysis/insar/filtering tests/test_filtering_cli.py
git commit -m "Expose the InSAR filtering workflow"
```
