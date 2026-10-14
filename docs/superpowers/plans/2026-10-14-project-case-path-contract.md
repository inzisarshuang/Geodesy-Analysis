# Project Case and Path Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only, tested Workflow contract for project roots, formal case IDs, acquisition handoff manifests, case-confined outputs, and canonical case-layout validation without moving or rewriting scientific data.

**Architecture:** Implement the contract entirely in `Geodesy-Workflow` as four focused modules: path binding, acquisition-manifest parsing, layout inspection, and a read-only CLI. The implementation accepts shared inputs anywhere inside the research project but confines normal outputs to one explicit case root; later Preprocessing, Analysis, and Visualization plans consume these interfaces without importing one another.

**Tech Stack:** Python 3.10+, standard-library `dataclasses`, `json`, `pathlib`, `argparse`, and `unittest`; existing setuptools entry points.

**Spec:** `../specs/2026-10-14-project-driven-study-layout-design.md`, especially sections 3-5, 7, 9, 12.1, and 13.

## Global Constraints

- This plan implements only subproject 1, **Project and path contract**; topography catalogs, manifest writers, component output migrations, and physical data migration remain later plans.
- `Geodesy-Workflow` owns the contract and read-only validator; it does not execute scientific algorithms.
- Formal case IDs use exactly two safe project-relative components, for example `S1/ASCENDING_128` and `SAOCOM/GUIZHOU`; scientific metadata is never parsed from those names.
- Inputs may resolve anywhere inside the research project root; normal outputs must remain inside the configured case root after symlink resolution.
- Acquisition manifests use schema version `1`, status `complete`, project-relative source/product paths, explicit metadata fields, and strict unknown-key rejection.
- Validators and CLI commands are read-only: they do not create case directories, repair manifests, move products, or write reports into the project.
- Existing S1 and SAOCOM products are inspected only; no 13-19 GiB result directory is copied, renamed, deleted, or regenerated.
- Every new production module starts with the repository's structured module documentation and every public function/class has a docstring.
- Tests use synthetic temporary projects and do not commit project-specific absolute paths or generated products.

## Review Focus

- A symlink inside the project or case that points outside must be rejected for both existing inputs and not-yet-created output descendants; Task 1 adds both tests.
- A syntactically safe path targeting another valid case must still be rejected as a case output; Task 1 adds a cross-case test.
- Unknown manifest keys or unsupported schema versions must fail before any product path is consumed; Task 2 adds strict-schema tests.
- Duplicate dates, duplicate product paths, invalid calendar dates, and empty polarization/product lists must be rejected with field-specific errors; Task 2 adds each input class.
- Validation must not mutate a partial or invalid project, even while reporting multiple issues; Task 3 snapshots the complete temporary tree before and after inspection.

---

## File Structure

All implementation files below are relative to the isolated
`Geodesy-Workflow` execution worktree.

```text
src/geodesy_workflow/
├── layout_paths.py       # project/case binding and containment-safe resolution
├── acquisition.py        # immutable schema-1 acquisition handoff reader
├── layout.py             # canonical case paths and read-only validation report
└── layout_cli.py         # geodesy-layout-validate command

tests/
├── test_layout_paths.py
├── test_acquisition.py
├── test_layout.py
└── test_layout_cli.py
```

Existing `registry.py`, run logging, and scientific shadow validators remain
unchanged. `pyproject.toml` changes only to expose the new read-only command;
`README.md` documents its purpose and exit status.

### Task 1: Project and Case Path Binding

**Files:**
- Create: `src/geodesy_workflow/layout_paths.py`
- Create: `tests/test_layout_paths.py`

**Interfaces:**
- Consumes: an existing research project directory, a formal case ID, and project-relative path text.
- Produces: `CaseRoots`, `bind_case`, `resolve_project_input`, and `resolve_case_output` for all later tasks.

- [ ] **Step 1: Write failing happy-path and identifier tests**

Add tests that assert:

```python
roots = bind_case(project, "S1/ASCENDING_128")
self.assertEqual(roots.project_root, project.resolve())
self.assertEqual(roots.case_id, "S1/ASCENDING_128")
self.assertEqual(roots.case_root, project.resolve() / "S1" / "ASCENDING_128")
```

Reject absolute IDs, one- or three-component IDs, empty components, `.`, `..`,
backslashes, lowercase sensor components, and characters outside
`[A-Z0-9_-]` with an error naming `case_id`.

- [ ] **Step 2: Run the path tests and verify the module is missing**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_layout_paths.py' -v
```

Expected: FAIL because `geodesy_workflow.layout_paths` does not exist.

- [ ] **Step 3: Implement the immutable root binding interface**

Create these public interfaces:

```python
@dataclass(frozen=True)
class CaseRoots:
    project_root: Path
    case_id: str
    case_root: Path

def bind_case(project_root: str | Path, case_id: str) -> CaseRoots: ...
```

`bind_case` resolves an existing project directory strictly, validates the
two-component uppercase ID, and computes but does not create `case_root`.

- [ ] **Step 4: Add failing input/output containment tests**

Cover these exact behaviors:

```python
self.assertEqual(
    resolve_project_input(roots, "TOPOGRAPHY/jishishan_cop30/topography_manifest.json"),
    expected_manifest.resolve(),
)
self.assertEqual(
    resolve_case_output(roots, "S1/ASCENDING_128/PRE/GAMMA/RSLC"),
    roots.case_root / "PRE" / "GAMMA" / "RSLC",
)
```

Assert rejection of absolute path text, `..`, missing required input, project
escape, existing symlink escape, not-yet-created output beneath an escaping
symlink, and output `S1/DESCENDING_135/PRE/GAMMA/RSLC`.

- [ ] **Step 5: Run the tests and verify containment cases fail**

Run the Task 1 command again.

Expected: identifier tests PASS; containment tests FAIL because the resolver
functions do not exist.

- [ ] **Step 6: Implement the two path resolvers**

Add:

```python
def resolve_project_input(
    roots: CaseRoots,
    value: str | Path,
    *,
    must_exist: bool = True,
) -> Path: ...

def resolve_case_output(roots: CaseRoots, value: str | Path) -> Path: ...
```

Both reject absolute/user-home forms and resolve existing symlink components
before checking `Path.is_relative_to`. Input containment uses `project_root`;
output containment uses `case_root`. Neither function creates a path.

- [ ] **Step 7: Run Task 1 tests**

Run the Task 1 command.

Expected: all tests PASS.

- [ ] **Step 8: Commit the path contract**

```bash
git add src/geodesy_workflow/layout_paths.py tests/test_layout_paths.py
git commit -m "Add project and case path contract"
```

### Task 2: Acquisition Handoff Contract Reader

**Files:**
- Create: `src/geodesy_workflow/acquisition.py`
- Create: `tests/test_acquisition.py`

**Interfaces:**
- Consumes: `CaseRoots` and `resolve_project_input` from Task 1; one schema-1 `PRE/acquisition_manifest.json`.
- Produces: immutable `AcquisitionProduct`, `AcquisitionManifest`, and `load_acquisition_manifest` for the layout validator and later Preprocessing writer plan.

- [ ] **Step 1: Write the failing valid-manifest test**

Use a synthetic S1 project containing a real `source_manifest.json` placeholder
and two `.SAFE` directories. Assert:

```python
manifest = load_acquisition_manifest(path, roots)
self.assertEqual(manifest.schema_version, 1)
self.assertEqual(manifest.status, "complete")
self.assertEqual(manifest.case_id, "S1/ASCENDING_128")
self.assertEqual(manifest.sensor, "sentinel1")
self.assertEqual(manifest.orbit_direction, "ascending")
self.assertEqual(manifest.relative_orbit, 128)
self.assertEqual(manifest.polarizations, ("VV",))
self.assertEqual(tuple(item.date for item in manifest.products), ("20231226", "20240131"))
```

- [ ] **Step 2: Run the acquisition tests and verify the module is missing**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_acquisition.py' -v
```

Expected: FAIL because `geodesy_workflow.acquisition` does not exist.

- [ ] **Step 3: Implement the schema models and loader**

Create:

```python
@dataclass(frozen=True)
class AcquisitionProduct:
    date: str
    paths: tuple[Path, ...]

@dataclass(frozen=True)
class AcquisitionManifest:
    schema_version: int
    status: str
    case_id: str
    sensor: str
    orbit_direction: str | None
    relative_orbit: int | None
    track: str | None
    frame: str | None
    polarizations: tuple[str, ...]
    source_manifest: Path
    products: tuple[AcquisitionProduct, ...]

def load_acquisition_manifest(
    path: str | Path,
    roots: CaseRoots,
) -> AcquisitionManifest: ...
```

Allow exactly the documented top-level fields:
`schema_version`, `status`, `case_id`, `sensor`, `orbit_direction`,
`relative_orbit`, `track`, `frame`, `polarizations`, `source_manifest`, and
`products`. Optional metadata fields are present with JSON `null`; additions
require a schema bump. Product entries allow only `date` and `paths`.

- [ ] **Step 4: Add failing strict-schema and identity tests**

Test unsupported schema `2`, non-`complete` status, unknown top-level/product
keys, a manifest path outside `case_root/PRE`, mismatched `case_id`, empty or
duplicate polarizations, and wrong primitive types. Assert each error names the
offending field.

- [ ] **Step 5: Add failing product and path tests**

Test an invalid calendar date (`20230229`), unsorted dates, duplicate dates,
empty `paths`, duplicate product paths, missing source manifest/product,
absolute product paths, `..` traversal, and an external symlink. No resolved
path may leave `project_root`.

- [ ] **Step 6: Run Task 2 tests and verify the new validations fail**

Run the Task 2 command again.

Expected: valid manifest PASS; strict and product edge cases FAIL until their
validation is implemented.

- [ ] **Step 7: Complete strict parsing and validation**

Require non-empty lowercase `sensor`, `orbit_direction` in
`ascending|descending` when not null, positive `relative_orbit` when not null,
unique uppercase polarization labels, strictly increasing unique calendar
dates, and unique non-empty project inputs. Use Task 1 for every filesystem
resolution and never scan the source archive.

- [ ] **Step 8: Run Task 1 and Task 2 tests**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_layout_paths.py' -v
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_acquisition.py' -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit the acquisition reader**

```bash
git add src/geodesy_workflow/acquisition.py tests/test_acquisition.py
git commit -m "Add acquisition handoff contract reader"
```

### Task 3: Read-Only Canonical Case Validator

**Files:**
- Create: `src/geodesy_workflow/layout.py`
- Create: `tests/test_layout.py`

**Interfaces:**
- Consumes: `CaseRoots`, `bind_case`, and `load_acquisition_manifest` from Tasks 1-2.
- Produces: `CaseLayout`, `LayoutIssue`, `LayoutReport`, and `validate_case_layout`; no filesystem mutations.

- [ ] **Step 1: Write the failing canonical-layout test**

Create a synthetic case with:

```text
S1/ASCENDING_128/
├── config/{preprocessing,analysis,visualization}/
├── PRE/acquisition_manifest.json
├── PRE/GAMMA/{SLC,GEOMETRY,RSLC,RSLC_SUBSET}/
├── ANALYSIS/GAMMA/{BASELINE,INTERFEROGRAM,FILTERING,UNWRAPPING}/
├── VISUALIZATION/GAMMA/{BASELINE,INTF,COHERENCE,UNW}/
└── LOG/{PRE,ANALYSIS,VISUALIZATION}/GAMMA/
```

Assert `report.valid is True`, `report.case_id == "S1/ASCENDING_128"`, and
`report.issues == ()`.

- [ ] **Step 2: Run the layout tests and verify the module is missing**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_layout.py' -v
```

Expected: FAIL because `geodesy_workflow.layout` does not exist.

- [ ] **Step 3: Implement layout paths and report models**

Create:

```python
@dataclass(frozen=True)
class CaseLayout:
    roots: CaseRoots
    config_root: Path
    acquisition_manifest: Path
    preprocessing_root: Path
    analysis_root: Path
    visualization_root: Path
    log_root: Path

@dataclass(frozen=True)
class LayoutIssue:
    code: str
    path: Path
    message: str

@dataclass(frozen=True)
class LayoutReport:
    case_id: str
    valid: bool
    issues: tuple[LayoutIssue, ...]

def validate_case_layout(project_root: str | Path, case_id: str) -> LayoutReport: ...
```

The function constructs canonical paths, validates the acquisition contract,
and reports all deterministic issues in path/code order rather than failing on
the first missing directory.

- [ ] **Step 4: Add failing incomplete and forbidden-layout tests**

Require stable issue codes for missing case root, each missing `config` stage,
missing `PRE/acquisition_manifest.json`, malformed acquisition manifest,
legacy `WORK`, legacy `FIGURES`, Analysis `quicklooks`, and a repeated
`ascending` or `descending` directory directly beneath a case owner/backend
root. Optional stage-output directories may be absent before those stages run.

- [ ] **Step 5: Add the read-only guarantee test**

Snapshot every relative directory/file/symlink plus file bytes in a partial
invalid synthetic project, call `validate_case_layout`, and assert the snapshot
is byte-for-byte and entry-for-entry unchanged afterward.

- [ ] **Step 6: Run Task 3 tests and verify issue coverage fails**

Run the Task 3 command again.

Expected: canonical layout PASS; issue-code and read-only tests FAIL until the
inspection logic is complete.

- [ ] **Step 7: Complete deterministic read-only inspection**

Use `Path.exists`, `is_dir`, and explicit canonical paths only. Directory
inspection may detect the named forbidden legacy components, but must never
infer scientific assets or stage completion from arbitrary files. Catch
acquisition validation errors and expose them as `acquisition_invalid` without
changing the source exception message.

- [ ] **Step 8: Run Tasks 1-3 tests**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_layout*.py' -v
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_acquisition.py' -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit the validator**

```bash
git add src/geodesy_workflow/layout.py tests/test_layout.py
git commit -m "Add read-only case layout validator"
```

### Task 4: Validation CLI, Documentation, and Integration Gate

**Files:**
- Create: `src/geodesy_workflow/layout_cli.py`
- Create: `tests/test_layout_cli.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `validate_case_layout(project_root, case_id)` from Task 3.
- Produces: installed `geodesy-layout-validate --project ROOT --case CASE_ID [--case CASE_ID ...]`, JSON stdout, exit `0` for all valid cases and `2` for any invalid case.

- [ ] **Step 1: Write failing CLI behavior tests**

Call `layout_cli.main` with a valid case and assert exit `0` plus one JSON
document containing `project_root` and a `cases` list. Call it with one valid
and one invalid case and assert exit `2`, both reports remain present in input
order, and issue objects contain only `code`, `path`, and `message`.

- [ ] **Step 2: Add failing command-discovery and external-CWD tests**

Parse `pyproject.toml` and require:

```toml
geodesy-layout-validate = "geodesy_workflow.layout_cli:main"
```

Run the module in a subprocess from a temporary directory with `PYTHONPATH`
pointing at `src`; assert path resolution is independent of current working
directory and no project entry changes.

Also build three valid synthetic cases (`S1/ASCENDING_128`,
`S1/DESCENDING_135`, and `SAOCOM/GUIZHOU`) beside three unrelated topography
dataset directories. Validate all cases in one invocation and assert the case
order is preserved and no topography dataset is inferred or added to the
report.

- [ ] **Step 3: Run CLI tests and verify they fail**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -p 'test_layout_cli.py' -v
```

Expected: FAIL because the CLI and entry point do not exist.

- [ ] **Step 4: Implement the read-only CLI and entry point**

Add:

```python
def main(arguments: Sequence[str] | None = None) -> int: ...
```

Require at least one repeatable `--case`. Serialize resolved paths as strings,
sort keys inside objects while preserving requested case order, write only to
stdout, and catch user/configuration errors as an invalid report with exit `2`
rather than a traceback.

- [ ] **Step 5: Run CLI tests**

Run the Task 4 test command.

Expected: all tests PASS.

- [ ] **Step 6: Document the contract and non-destructive first phase**

Add a README section covering formal case IDs, shared-input/case-output
containment, the acquisition manifest as the handoff, CLI examples for
`S1/ASCENDING_128` and `SAOCOM/GUIZHOU`, exit codes, and the explicit statement
that validation never creates or migrates data. Do not document topography
catalog commands that are not implemented in this plan.

- [ ] **Step 7: Run the complete Workflow suite and static checks**

Run:

```bash
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m unittest discover -s tests -v
PYTHONPATH=src /home/yilun/miniconda3/envs/envInSAR/bin/python \
  -m compileall -q src/geodesy_workflow
git diff --check
```

Expected: complete suite reports `OK`; compileall and diff check exit `0`.

- [ ] **Step 8: Install and verify the public command**

Install the isolated Workflow worktree without resolving or downloading
dependencies, then invoke help from outside the repository:

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/python -m pip install \
  --no-build-isolation --no-deps -e .
cd /tmp
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-layout-validate --help
```

Expected: installation succeeds, help exits `0`, and documents repeatable
`--case` plus required `--project`.

- [ ] **Step 9: Perform the real-project read-only gate**

Before and after the gate, record only directory entry counts and existing
manifest hashes outside the repository; do not create a validation report in
the study project. Verify with `jq` that the current S1 stack still has three
dates and the SAOCOM diagnostic stack still has six dates/twelve assets. Then
run:

```bash
geodesy-layout-validate \
  --project /mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1 \
  --case S1/ASCENDING_128 \
  --case SAOCOM/GUIZHOU
```

Expected before migration: exit `2` with `case_root_missing` for both target
cases, no created target directory, and unchanged hashes for
`S1/WORK/GAMMA/ascending/RSLC/registered_stack.json` and
`SAOCOM_Guizhou/WORK/GAMMA/RSLC_DIAGNOSTIC/registered_stack.json`. This is a
successful read-only inventory result, not a migration failure.

- [ ] **Step 10: Commit the public validator**

```bash
git add pyproject.toml README.md \
  src/geodesy_workflow/layout_cli.py tests/test_layout_cli.py
git commit -m "Expose project layout validation command"
```

- [ ] **Step 11: Review the full branch against the plan**

Confirm exactly four implementation commits, no changes outside
`Geodesy-Workflow`, no project runtime products in Git, and no product-data
mutations. Re-run the commands from Steps 7-8 if review changes any file.

## Deferred to Later Approved Plans

- writing `TOPOGRAPHY/catalog.json` or any topography manifest;
- creating `PRE/acquisition_manifest.json` from S1 query/download or imported
  SAOCOM products;
- changing existing Preprocessing, Analysis, or Visualization CFG parsers;
- creating canonical case directories in the real project;
- removing Analysis quicklook behavior or moving Visualization outputs;
- moving, renaming, copying, deleting, or regenerating real scientific data.
