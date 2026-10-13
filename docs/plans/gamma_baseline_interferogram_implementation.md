# GAMMA Baseline and Interferogram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build installable, CFG-driven GAMMA baseline-selection and interferogram-generation workflows that consume PRE `registered_stack.json` products and publish validated manifests for the later filtering stage.

**Architecture:** Python owns configuration, validation, planning, progress, logging, restart safety, and publication; injected command runners invoke GAMMA for numerical work. Baseline selection and interferogram generation are separate analysis stages connected by a strict `baseline_manifest.json`, while existing pure numerical baseline plotting remains reusable.

**Tech Stack:** Python 3.10+, standard-library `configparser`/`dataclasses`/`json`/`subprocess`, NumPy, optional Matplotlib, GAMMA executables, `unittest`, envInSAR.

**Spec:** `docs/design/gamma_baseline_interferogram.md`

## Global Constraints

- Keep acquisition, DEM preparation, SLC generation, registration, and cropping outside Analysis.
- Do not import `geodesy_preprocessing`, legacy sibling `lib`, or the `GAMMA-InSAR` source tree from production modules.
- Keep Data Adapter unchanged; reading the published PRE JSON is an Analysis input-contract responsibility in this phase.
- Use `[project]`, `[defaults]`, and `[case:name]`, with CLI values limited to config path, case selection, and dry-run.
- Resolve all configured paths within the project root and reject unknown CFG keys.
- Call GAMMA executables directly; never invoke legacy `2-baseline_select` or `5-product`.
- Keep input RSLC, parameter, radar-height, and network files read-only.
- Publish an output directory only after all required products validate; conflicting existing output is an error.
- Emit the same `@@GEODESY_PROGRESS` protocol and console rendering used by PRE.
- Put detailed logs under `PROJECT/LOG/ANALYSIS/GAMMA/<STAGE>/<case>/` and keep credentials out of logs.
- `--dry-run` validates and reports a plan without creating products or logs.
- Use test doubles for unit tests; only the final envInSAR gate may call installed GAMMA.

## Review Focus

- A schema-v2 stack whose asset paths are valid but whose date/polarization grid is incomplete must fail before GAMMA starts; Task 2 adds this test.
- A baseline manifest copied from another stack or polarization must be rejected by its source digest; Task 5 adds this test.
- A radar-height file with the right name but wrong byte size must stop before topographic subtraction; Task 6 adds this test.
- A core GAMMA command that exits zero but omits its documented output must still fail and preserve logs; Tasks 4 and 6 add these tests.
- A complete output produced from different inputs must not be silently skipped or overwritten; Tasks 4 and 6 add these tests.

---

### Task 1: Shared Analysis workflow foundations

**Files:**
- Create: `src/geodesy_analysis/common/__init__.py`
- Create: `src/geodesy_analysis/common/paths.py`
- Create: `src/geodesy_analysis/common/progress.py`
- Create: `src/geodesy_analysis/common/command.py`
- Modify: `src/geodesy_analysis/io.py`
- Create: `tests/test_workflow_common.py`

**Interfaces:**
- Produces: `validate_within_root(path: Path, root: Path, label: str) -> Path`.
- Produces: `emit_progress(...) -> str` and `ConsoleProgress` with PRE-compatible output.
- Produces: `CommandResult`, `CommandExecutionError`, and `SubprocessCommandRunner.run(command: Sequence[str], *, cwd: Path, stdin_text: str | None, stdout_path: Path, stderr_path: Path) -> CommandResult`.
- Produces: `atomic_output_directory(destination: Path) -> Iterator[Path]`, rejecting existing destinations and renaming a sibling staging directory on success.

- [ ] **Step 1: Write failing shared-foundation tests**

Add tests named `test_paths_cannot_escape_project_root`, `test_progress_matches_pre_protocol`, `test_command_failure_names_stderr_log`, and `test_atomic_directory_publishes_only_on_success`. Assert traversal rejection, exact progress prefix/console text, structured command errors, and absence of a formal destination after a raised exception.

- [ ] **Step 2: Run the new tests and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_workflow_common -v`

Expected: FAIL because the new modules and directory publisher do not exist.

- [ ] **Step 3: Implement the shared interfaces**

Copy the behavior, not the import, of PRE's progress protocol. Keep command execution generic and record argv without shell interpretation. Make directory staging a sibling of the destination so final `os.replace` stays on one filesystem.

- [ ] **Step 4: Run shared and existing I/O tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_workflow_common tests.test_io -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/geodesy_analysis/common src/geodesy_analysis/io.py tests/test_workflow_common.py
git commit -m "Add Analysis workflow foundations"
```

### Task 2: Registered-stack input contract

**Files:**
- Create: `src/geodesy_analysis/insar/common/__init__.py`
- Create: `src/geodesy_analysis/insar/common/registered_stack.py`
- Create: `tests/test_registered_stack.py`

**Interfaces:**
- Consumes: `validate_within_root` from Task 1.
- Produces: immutable `RegisteredAsset(date: str, polarization: str, data_path: Path, parameter_path: Path)`.
- Produces: immutable `RegisteredStack(source_path: Path, source_digest: str, sensor: str, reference_date: str, dates: tuple[str, ...], polarizations: tuple[str, ...], assets: tuple[RegisteredAsset, ...])`.
- Produces: `read_registered_stack(path: Path, *, project_root: Path, polarization: str) -> RegisteredStack`.

- [ ] **Step 1: Write failing stack-contract tests**

Test a valid schema-v2 `status=complete`, `backend.name=gamma`, `geometry_type=radar_grid` manifest. Add failures for diagnostic/failed status, wrong backend, wrong geometry, duplicate dates, missing requested polarization, one missing date/polarization asset, path traversal, and missing/empty data or parameter files.

- [ ] **Step 2: Run and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_registered_stack -v`

Expected: FAIL because `registered_stack` is not implemented.

- [ ] **Step 3: Implement strict read-only parsing**

Resolve asset paths relative to the manifest directory, validate the complete requested-polarization date grid, preserve manifest date order, and calculate `source_digest` from the manifest bytes. Do not import PRE models.

- [ ] **Step 4: Run contract and architecture tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_registered_stack tests.test_architecture -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/geodesy_analysis/insar/common tests/test_registered_stack.py
git commit -m "Add registered stack input contract"
```

### Task 3: GAMMA baseline configuration and plan

**Files:**
- Create: `src/geodesy_analysis/insar/baseline_selection/__init__.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/common/__init__.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/__init__.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/models.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/config.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/plan.py`
- Create: `tests/test_gamma_baseline_config.py`
- Create: `tests/test_gamma_baseline_plan.py`

**Interfaces:**
- Consumes: `read_registered_stack` from Task 2.
- Produces: `GammaBaselineCase(name, project_root, registered_stack, polarization, network_type, max_perpendicular_baseline, max_temporal_baseline, output_dir)`.
- Produces: `load_gamma_baseline_config(path: Path) -> tuple[GammaBaselineCase, ...]` and `select_gamma_baseline_case(cases, name) -> GammaBaselineCase`.
- Produces: `GammaBaselinePlan(case, stack, base_calc_command, expected_network_name)` and `build_gamma_baseline_plan(case) -> GammaBaselinePlan`.

- [ ] **Step 1: Write failing CFG tests**

Cover project-relative and absolute paths, defaults overridden by a case, DSI/SBAS/PSI normalization, positive finite thresholds, duplicate/unsafe case names, unknown sections/keys, ambiguous missing `--case`, and output/input overlap.

- [ ] **Step 2: Run CFG tests and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_config -v`

Expected: FAIL because the loader does not exist.

- [ ] **Step 3: Implement models and strict CFG loading**

Use exact keys from the design. DSI and PSI still parse threshold defaults but their `base_calc` command must retain legacy mode-specific arguments.

- [ ] **Step 4: Write failing plan tests**

Assert one selected asset per date, manifest reference date use, deterministic `images`/`SLC_tab` content, and exact DSI/SBAS/PSI `base_calc` argv matching old script semantics.

- [ ] **Step 5: Run plan tests and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_plan -v`

Expected: FAIL because the planner is not implemented.

- [ ] **Step 6: Implement plan construction**

Represent temporary filenames relative to a future staging directory; do not create files or check for the GAMMA executable during planning.

- [ ] **Step 7: Run both baseline planning suites**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_config tests.test_gamma_baseline_plan -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/geodesy_analysis/insar/baseline_selection tests/test_gamma_baseline_config.py tests/test_gamma_baseline_plan.py
git commit -m "Plan GAMMA baseline selection"
```

### Task 4: GAMMA baseline execution, publication, CLI, and CFG

**Files:**
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/publication.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/runner.py`
- Create: `src/geodesy_analysis/insar/baseline_selection/gamma/cli.py`
- Create: `config_examples/gamma_baseline.cfg`
- Modify: `pyproject.toml`
- Create: `tests/test_gamma_baseline_runner.py`
- Create: `tests/test_gamma_baseline_cli.py`

**Interfaces:**
- Consumes: Task 1 command/progress/publication APIs and Task 3 `GammaBaselinePlan`.
- Produces: `parse_berp_sc(path: Path) -> tuple[BaselineRecord, ...]`, removing self-pairs, normalizing date order and sorting deterministically.
- Produces: `run_gamma_baseline(plan, *, command_runner, progress_sink=print) -> BaselineRunSummary`.
- Produces: schema-v1 `baseline_manifest.json` with stack digest, polarization, reference date, network type, network path, pair count, and provenance path.
- Produces: console script `geodesy-analysis-gamma-baseline`.

- [ ] **Step 1: Write failing runner tests**

Use a fake runner that writes controlled `Berp_SC` and `itab_SC`. Assert exact `images`, `image_pairs_*`, `baseline_select_*`, manifest fields, source digest, progress sequence, and plotting warning behavior. Assert missing output after a zero exit fails, logs are preserved, matching complete output skips, and a changed input digest conflicts.

- [ ] **Step 2: Run runner tests and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_runner -v`

Expected: FAIL because execution and publication are absent.

- [ ] **Step 3: Implement baseline execution and publication**

Write temporary `images` and `SLC_tab`, call `base_calc` once, validate outputs, reuse `plot_baseline_network`, write deterministic JSON plus provenance, and atomically publish. Preserve only logs on failure.

- [ ] **Step 4: Run runner tests and verify GREEN**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_runner -v`

Expected: PASS.

- [ ] **Step 5: Write failing CLI and CFG-contract tests**

Assert `--dry-run` JSON includes case, stack, reference date, network type, pair limits and output but creates nothing; assert operational errors return nonzero. Check the example CFG contains purpose, usage, dry-run, formal run, per-section parameter explanations, outputs, logs, completion judgment, rerun rules, and credential warning.

- [ ] **Step 6: Implement CLI, entry point, and fully commented example CFG**

Set `GEODESY_PROGRESS_PROTOCOL=1` behavior to raw protocol and otherwise use `ConsoleProgress`, matching PRE.

- [ ] **Step 7: Run baseline stage tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_baseline_config tests.test_gamma_baseline_plan tests.test_gamma_baseline_runner tests.test_gamma_baseline_cli -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/geodesy_analysis/insar/baseline_selection config_examples/gamma_baseline.cfg pyproject.toml tests/test_gamma_baseline_runner.py tests/test_gamma_baseline_cli.py
git commit -m "Implement GAMMA baseline workflow"
```

### Task 5: GAMMA interferogram configuration and plan

**Files:**
- Create: `src/geodesy_analysis/insar/interferogram_generation/__init__.py`
- Create: `src/geodesy_analysis/insar/interferogram_generation/common/__init__.py`
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/__init__.py`
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/models.py`
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/config.py`
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/plan.py`
- Create: `tests/test_gamma_interferogram_config.py`
- Create: `tests/test_gamma_interferogram_plan.py`

**Interfaces:**
- Consumes: Task 2 `RegisteredStack` and Task 4 schema-v1 baseline manifest.
- Produces: `GammaInterferogramCase` with looks, explicit radar height, spectral-filter policy, create-offset parameters, coherence windows, and output.
- Produces: `load_gamma_interferogram_config`, `select_gamma_interferogram_case`, and `read_baseline_manifest`.
- Produces: `GammaInterferogramPlan(case, stack, pairs, spectral_filter_range, spectral_filter_azimuth)` and `build_gamma_interferogram_plan(case) -> GammaInterferogramPlan`.

- [ ] **Step 1: Write failing CFG tests**

Cover all required keys, root confinement, positive looks/windows/search sizes, correlation threshold in `[0,1]`, `spectral_filter=auto|on|off`, unknown keys, and output/input overlap.

- [ ] **Step 2: Run CFG tests and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_config -v`

Expected: FAIL because the loader is absent.

- [ ] **Step 3: Implement interferogram models and CFG loading**

Use legacy defaults `create_offset` start `0 0`, window `32 32`, search `64 64`, threshold `0.35`, and coherence window `5 5` with estimator mode `2`.

- [ ] **Step 4: Write failing plan and cross-stage tests**

Assert source digest, reference date and polarization must match the baseline manifest; all network dates must exist; duplicate/reversed/self pairs fail; Sentinel-1 auto resolves spectral filtering to `0 0`, other sensors to `1 1`; explicit on/off overrides auto.

- [ ] **Step 5: Run plan tests and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_plan -v`

Expected: FAIL because planning is absent.

- [ ] **Step 6: Implement baseline-manifest reading and plan construction**

Preserve network-table order for processing and reject any digest mismatch before checking GAMMA availability.

- [ ] **Step 7: Run interferogram planning suites**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_config tests.test_gamma_interferogram_plan -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/geodesy_analysis/insar/interferogram_generation tests/test_gamma_interferogram_config.py tests/test_gamma_interferogram_plan.py
git commit -m "Plan GAMMA interferogram generation"
```

### Task 6: GAMMA interferogram execution and publication

**Files:**
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/publication.py`
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/runner.py`
- Create: `tests/test_gamma_interferogram_runner.py`

**Interfaces:**
- Consumes: Task 1 workflow foundations and Task 5 `GammaInterferogramPlan`.
- Produces: `run_gamma_interferograms(plan, *, command_runner, progress_sink=print) -> InterferogramRunSummary`.
- Produces: schema-v1 `interferogram_manifest.json`, listing MLI assets, pair products, radar-height provenance, resolved filter flags, looks, and logs.

- [ ] **Step 1: Write failing execution-order tests**

Use a fake runner that creates expected outputs and parameter files. Assert each acquisition receives one `multi_look`, `ave_image` runs once, and every pair receives the exact ordered core sequence from the design with resolved filter flags and configured `create_offset` stdin.

- [ ] **Step 2: Run and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_runner -v`

Expected: FAIL because the runner is absent.

- [ ] **Step 3: Implement MLI and pair execution**

Use per-date and per-pair subdirectories in staging; write command stdout/stderr to project logs; validate non-empty outputs immediately after every core command.

- [ ] **Step 4: Add failing safety/publication tests**

Assert radar-height byte-size mismatch stops before `phase_sim_orb`; command failure and zero-exit/missing-output both preserve failure logs without publishing; matching completed output skips; changed input or parameters conflict; quicklook failure records warning but still publishes scientific products.

- [ ] **Step 5: Run safety tests and verify RED for the new cases**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_runner -v`

Expected: the newly added safety cases FAIL.

- [ ] **Step 6: Implement validation, provenance, and atomic publication**

Calculate the radar-height expected size from the generated MLI `range_samples × azimuth_lines × 4` bytes. Preserve formal results only when all pair products and the manifest validate.

- [ ] **Step 7: Run runner and architecture tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_runner tests.test_architecture -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/geodesy_analysis/insar/interferogram_generation/gamma/publication.py src/geodesy_analysis/insar/interferogram_generation/gamma/runner.py tests/test_gamma_interferogram_runner.py
git commit -m "Implement GAMMA interferogram execution"
```

### Task 7: Interferogram CLI, documentation, and installed-package gate

**Files:**
- Create: `src/geodesy_analysis/insar/interferogram_generation/gamma/cli.py`
- Create: `config_examples/gamma_interferogram.cfg`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Create: `docs/workflows/gamma_insar.md`
- Create: `tests/test_gamma_interferogram_cli.py`
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Consumes: Task 5 planner and Task 6 runner.
- Produces: console script `geodesy-analysis-gamma-interferogram` and human workflow from PRE stack through both new stages.

- [ ] **Step 1: Write failing CLI, packaging, and documentation tests**

Assert dry-run JSON fields and no writes; operational error exit codes; both `pyproject.toml` entry points; example CFG documentation requirements; workflow order; and no legacy imports/runtime paths.

- [ ] **Step 2: Run and verify RED**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_cli tests.test_architecture -v`

Expected: FAIL because CLI, entry point, and documentation are absent.

- [ ] **Step 3: Implement CLI, example CFG, and human documentation**

Document absolute commands usable from any directory, formal outputs, logs, completion checks, rerun behavior, and the current requirement for a matching radar-height file.

- [ ] **Step 4: Run the complete repository suite**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Build and install in envInSAR**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pip install --no-deps -e /mnt/beegfs/procesados/yiluntan/Geodesy-Analysis`

Expected: editable installation succeeds and both executables resolve from `/home/yilun/miniconda3/envs/envInSAR/bin/`.

- [ ] **Step 6: Run installed-entry dry runs from outside the repository**

Create project-local CFG files for the selected real validation case, then run both absolute executables from `/mnt/beegfs/procesados/yiluntan`. Expected: valid JSON plans, no product directories from dry-run, and paths resolve relative to the CFG project root.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/interferogram_generation/gamma/cli.py config_examples/gamma_interferogram.cfg pyproject.toml README.md docs tests/test_gamma_interferogram_cli.py tests/test_architecture.py
git commit -m "Expose GAMMA analysis workflows"
```

### Task 8: Focused real-stack parity validation

**Files:**
- Create in study project: `Gansu_Jishishan_LT1/config/analysis/gamma_baseline.cfg`
- Create in study project: `Gansu_Jishishan_LT1/config/analysis/gamma_interferogram.cfg`
- Create in study project: `Gansu_Jishishan_LT1/LOG/ANALYSIS/GAMMA/validation/validation.json`
- Modify: `MIGRATION_PROVENANCE.md`

**Interfaces:**
- Consumes: installed commands from Tasks 4 and 7 and the completed S1 ascending PRE stack.
- Produces: a project-local validation record and repository-level provenance note; no study-project data enters git.

- [ ] **Step 1: Verify the real input boundary read-only**

Use `S1/WORK/GAMMA/ascending/RSLC/registered_stack.json`, confirm its three VV dates and reference date, and identify the matching existing radar-height file. Do not rerun PRE.

- [ ] **Step 2: Run the new baseline workflow**

Configure the S1 ascending validation case as SBAS with a 40-day temporal limit so the
three-date stack produces one representative pair, then run the installed absolute command.
Expected: formal baseline output, readable manifest, unified progress, and detailed project
logs.

- [ ] **Step 3: Compare baseline output with legacy semantics**

Compare pair membership, date ordering, perpendicular/time baseline columns, and plot generation against a legacy `base_calc` reference without modifying the legacy output.

- [ ] **Step 4: Run a bounded interferogram validation**

Use the one-pair formal baseline result from Step 2. Expected: `.int`, `.off`, `.baseline`,
`.int.flt`, `.sim.topo.unw`, `.tflt`, `.cc`, MLI files, manifest, provenance, and logs are
all non-empty and dimensionally consistent.

- [ ] **Step 5: Record parity evidence**

Write JSON containing input digests, commands, output sizes, parsed dimensions, pair identity, and pass/fail. Update `MIGRATION_PROVENANCE.md` with the validation location and result, without copying generated products into the repository.

- [ ] **Step 6: Run final installed and repository verification**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest discover -s /mnt/beegfs/procesados/yiluntan/Geodesy-Analysis/tests -v`

Expected: all tests PASS after the real run.

- [ ] **Step 7: Commit repository evidence**

```bash
git add MIGRATION_PROVENANCE.md
git commit -m "Record GAMMA analysis workflow validation"
```
