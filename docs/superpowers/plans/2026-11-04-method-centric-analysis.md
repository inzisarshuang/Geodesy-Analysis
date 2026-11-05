# Method-Centric Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Analysis workflows to method-centric products, completion-aware reuse, and centralized stage quicklooks.

**Architecture:** Analysis binds a case plus explicit `processing_root`, derives product/figure/log defaults from a shared layout, and validates explicit overrides for non-overlap. A shared reuse classifier skips matching complete science, rejects stale or incomplete outputs, and lets figure repair run independently.

**Tech Stack:** Python 3.11, pathlib, configparser, JSON, NumPy, pytest, GAMMA command wrappers

**Spec:** `docs/superpowers/specs/2026-11-04-method-centric-project-layout-design.md`

## Global Constraints

- Preserve scientific algorithms and GAMMA command arguments.
- Use envInSAR for focused tests and Gansu dry-runs.
- Do not overwrite expensive completed Analysis products.
- Keep phase and coherence science in the same `INTF/PAIRS/<pair>` record.
- Keep `FIGURES/INTF` flat and deterministically named.
- Stage only scoped files in the already-dirty worktree.

## Review Focus

- Reject method roots outside the declared case.
- Reject overlap between science, figures, logs, inputs, and staging.
- Reject a complete manifest whose input/config signature changed.
- Repair a missing quicklook without invoking science commands.
- Preserve selected-case isolation when another CFG case is invalid.

---

### Task 1: Shared Analysis method layout

**Files:**
- Modify: `src/geodesy_analysis/common/case_paths.py`
- Create: `src/geodesy_analysis/common/product_layout.py`
- Modify: `tests/test_workflow_common.py`
- Create: `tests/test_product_layout.py`

**Interfaces:**
- Produces: `bind_analysis_case(project_root, label, project, processing_root)`
- Produces: `AnalysisProductLayout.product(*parts)`, `.figures(*parts)`, and `.logs(*parts)`
- Produces: portable path serialization for internal and explicit external paths

- [ ] **Step 1:** Add failing tests for S1/GAMMA and SAOCOM/GAMMA_mb defaults, containment, overlap, and portable serialization.
- [ ] **Step 2:** Run the two focused modules and confirm failure against the current two-argument case binding.
- [ ] **Step 3:** Implement the new layout without workflow-specific product names in `case_paths.py`.
- [ ] **Step 4:** Run the focused tests.
- [ ] **Step 5:** Commit as `refactor: add analysis method product layout`.

### Task 2: Analysis reuse contract

**Files:**
- Create: `src/geodesy_analysis/common/reuse.py`
- Create: `tests/test_reuse.py`
- Modify: `src/geodesy_analysis/io.py`

**Interfaces:**
- Produces: `ReuseState` and `classify_analysis_output(...)`
- Retains: atomic publication helpers for absent targets and Adapter/Visualization consumers
- Produces: stable mismatch/incomplete diagnostics

- [ ] **Step 1:** Add failing tests for absent, complete, incomplete, corrupt, signature-mismatched, and figure-missing states.
- [ ] **Step 2:** Run `tests/test_reuse.py` and confirm import failure.
- [ ] **Step 3:** Implement read-only classification and reusable diagnostics.
- [ ] **Step 4:** Run reuse and IO tests.
- [ ] **Step 5:** Commit as `feat: add analysis result reuse contract`.

### Task 3: Baseline and interferogram migration

**Files:**
- Modify: `src/geodesy_analysis/insar/baseline_selection/gamma/{config,plan,publication,runner,cli}.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/{config,models,plan,publication,runner,cli}.py`
- Modify: `src/geodesy_analysis/insar/common/gamma_quicklooks.py`
- Modify: `config_examples/analysis/gamma_baseline.cfg`
- Modify: `config_examples/analysis/gamma_geocoding.cfg`
- Modify: `config_examples/analysis/gamma_interferogram.cfg`
- Modify: baseline/interferogram/config-example tests

**Interfaces:**
- Consumes: Tasks 1–2
- Produces defaults: `BASELINE`, `GEOCODING`, `INTF`, `FIGURES/BASELINE`, `FIGURES/GEOCODING`, `FIGURES/INTF`
- Produces flat names `<pair>.intensity.bmp`, `<pair>.phase.bmp`, `<pair>.coherence.bmp`

- [ ] **Step 1:** Add failing config/plan tests for the method-root defaults and explicit overrides.
- [ ] **Step 2:** Add failing runner tests for complete-result skip, absent-result run, signature mismatch failure, and flat adjacent quicklook names.
- [ ] **Step 3:** Run the affected modules and record the expected failures.
- [ ] **Step 4:** Migrate loaders, plans, manifests, and runners to the new paths and reuse decisions without changing GAMMA commands.
- [ ] **Step 5:** Add the required bilingual path-contract headers to all three CFG examples.
- [ ] **Step 6:** Run focused baseline/interferogram tests.
- [ ] **Step 7:** Commit as `refactor: migrate baseline and interferogram layout`.

### Task 4: Filtering, MCF, and quad detrending migration

**Files:**
- Modify: `src/geodesy_analysis/insar/filtering/{config,plan,publication,runner,cli}.py`
- Modify: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/{config,plan,publication,runner,cli,mask}.py`
- Modify: `src/geodesy_analysis/insar/detrending/gamma/quad/{config,plan,publication,runner,cli}.py`
- Modify: `config_examples/analysis/insar_filtering.cfg`
- Modify: `config_examples/analysis/gamma_mcf_unwrapping.cfg`
- Modify: `config_examples/analysis/gamma_quad_detrending.cfg`
- Modify: corresponding workflow tests

**Interfaces:**
- Consumes: Tasks 1–2 and Task 3 interferogram manifest schema
- Produces defaults: `FILTERING/<METHOD>`, `UNW/GAMMA_MCF`, `DETRENDING/GAMMA_QUAD` and matching FIGURES paths
- Consumes: `<processing_root>/pairs.txt`

- [ ] **Step 1:** Add failing tests for new defaults, shared `pairs.txt`, selected-case isolation, and safe explicit directories.
- [ ] **Step 2:** Add failing runner tests for pair-aware reuse and mismatched completed outputs.
- [ ] **Step 3:** Run only filtering, MCF, and quad test modules.
- [ ] **Step 4:** Implement the method-root paths, manifests, and reuse branches while preserving algorithms.
- [ ] **Step 5:** Update CFG headers to name all required PRE/earlier-Analysis inputs and downstream users.
- [ ] **Step 6:** Run the focused workflow tests.
- [ ] **Step 7:** Commit as `refactor: migrate filtering unwrapping and detrending layout`.

### Task 5: Figure-only repair and documentation

**Files:**
- Create: `src/geodesy_analysis/common/figures.py`
- Create: `tests/test_figure_repair.py`
- Modify: Analysis workflow CLIs and runners
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`

**Interfaces:**
- Produces: `repair_missing_figures(manifest_path, command_runner) -> tuple[Path, ...]`
- Produces: CLI behavior that repairs missing figures before returning a science skip

- [ ] **Step 1:** Add failing tests showing a valid science manifest plus missing BMP invokes only quicklook commands.
- [ ] **Step 2:** Run `tests/test_figure_repair.py` and confirm failure.
- [ ] **Step 3:** Implement manifest-driven repair for supported GAMMA quicklooks.
- [ ] **Step 4:** Update user documentation with the method-centric tree, skip rules, and delete-to-rerun workflow.
- [ ] **Step 5:** Run focused workflow tests, all example loaders, `compileall`, and `git diff --check`.
- [ ] **Step 6:** Commit as `feat: repair analysis quicklooks independently`.
