# OwlTester Action

Runs the OwlTester full artifact audit on an ontology release as a gate in your own CI.
Your build (ROBOT, ODK, Makefiles) stays as it is. The Action adds the checks those builds
usually lack: SHACL validation of the data against the shapes, reasoning over the whole release,
namespace integrity, datatypes, documentation examples and release hygiene. It can also write
the release's verification record.

This directory is the Action's source in OwlTesterService. It is published as
`dkoepsell/owltester-action` (see "Publishing" below).

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `path` | `.` | Directory or zip to audit |
| `profile` | `general` | `general`, `bfo` or `sool` |
| `config` | `audit.yaml` if present | Audit configuration |
| `fail-on` | `major` | Gate threshold: `critical`, `major` or `minor` |
| `budget` | `900` | Seconds for the whole audit |
| `record` | `false` | Also write `VERIFICATION.json` / `.md` into `path` |
| `attest` | `false` | The workflow signs the record (`actions/attest-build-provenance`) |
| `comment` | `false` | Post the summary as a pull-request comment (needs `pull-requests: write`) |
| `badge` | empty | Write shields.io endpoint JSON to this path |
| `image` | the digest in `IMAGE` | The OwlTester CLI image |

**Outputs:** `verdict`, `report-json`, `report-md`, `record` (path), `counts` (JSON).

**Behaviour:** writes the Markdown summary to the job summary; uploads the full report as a
workflow artifact; fails the step per `fail-on`. Exit 2 (a failed step that says the tool
could not run) is kept apart from a rejected release.

Findings the release declares in `audit.yaml` under `expected` (with a reason) do not count
toward the gate and are listed in the record.

## Workflows

Copy these into `.github/workflows/`:

- [`templates/audit.yml`](templates/audit.yml): every push and pull request, gate at `critical`,
  a summary comment on pull requests.
- [`templates/release.yml`](templates/release.yml): on a `v*` tag, build, stage the release files
  with [`templates/stage-release.sh`](templates/stage-release.sh) (copy to `scripts/`), audit at
  `major`, write and sign the verification record, zip, and publish a GitHub Release whose body is
  `VERIFICATION.md`. Nothing is published if the audit fails.
- [`templates/badge.yml`](templates/badge.yml): a README badge without a server.

## Checking a release

Anyone can check a downloaded release:

```
docker run --rm -v "$PWD:/w" -w /w ghcr.io/dkoepsell/owltester-cli verify my-release-v1.0.0.zip --reaudit
gh attestation verify VERIFICATION.json --repo <owner>/<repo>     # when the record was signed
```

## Running the CLI yourself

```
docker run --rm -v "$PWD:/w" -w /w ghcr.io/dkoepsell/owltester-cli \
  audit dist --profile bfo --fail-on major --json audit.json --summary-md summary.md
docker run --rm -v "$PWD:/w" -w /w ghcr.io/dkoepsell/owltester-cli \
  record dist --report audit.json --tag v1.0.0 --commit "$(git rev-parse HEAD)"
```

Exit codes: 0 pass, 1 the gate rejected the release, 2 usage or environment error.

## Publishing (maintainers)

1. Tag OwlTesterService (`v1.2.3`). `.github/workflows/cli-image.yml` builds the `cli` target and
   pushes `ghcr.io/dkoepsell/owltester-cli` tagged by version and commit, and prints the digest.
2. Write `ghcr.io/dkoepsell/owltester-cli@sha256:<digest>` into `IMAGE`, so this action version
   runs exactly that toolchain.
3. Copy this directory to the root of `dkoepsell/owltester-action`, tag it `v1.x.y`, and move
   the `v1` tag.
