# AGENTS.md
Guidance for agentic coding assistants working in this repository.

## 1) Repository Reality Check
- Repository is currently minimal: `.git/` and `README.md` only.
- No verified build system, test framework, linter config, or package manifest is committed.
- No Cursor rules found in `.cursor/rules/`.
- No `.cursorrules` file found.
- No Copilot instructions found at `.github/copilot-instructions.md`.
- Until project tooling appears, this file is the default operating guide.

## 2) Source Of Truth Priority
When instructions conflict, follow this order:
1. Direct user request in the current session.
2. Explicit repository rule files (if later added):
   - `.cursor/rules/**`
   - `.cursorrules`
   - `.github/copilot-instructions.md`
3. This `AGENTS.md`.
4. Existing conventions in files you touch.
5. Sensible language/framework defaults.

## 3) Build / Lint / Test Commands
### Current status
- There are no guaranteed commands yet for build, lint, or tests.
- Do not claim any command is mandatory unless a matching tool config exists.
- Discover tooling first, then run commands that fit the discovered stack.

### Tooling discovery checklist
Check for these files before picking commands:
- JavaScript/TypeScript: `package.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`.
- Python: `pyproject.toml`, `requirements.txt`, `poetry.lock`, `pytest.ini`.
- Go: `go.mod`.
- Rust: `Cargo.toml`.
- Java/Kotlin: `pom.xml`, `build.gradle`, `build.gradle.kts`.
- Ruby: `Gemfile`.
- .NET: `*.sln`, `*.csproj`.
- Generic runners: `Makefile`, `Taskfile.yml`, `justfile`.

### Preferred execution order (once tooling exists)
1. Run targeted test(s) for changed behavior.
2. Run fast lint/type checks for touched scope.
3. Run full test suite.
4. Run production build if relevant.

### Single-test command patterns (only when stack matches)
Python / pytest:
- `pytest tests/test_module.py`
- `pytest tests/test_module.py::test_case_name`
- `pytest tests/test_module.py::TestClass::test_case_name`

JavaScript / Vitest:
- `npx vitest run path/to/file.test.ts`
- `npx vitest run -t "test name"`

JavaScript / Jest:
- `npx jest path/to/file.test.ts`
- `npx jest -t "test name"`

JavaScript / npm scripts:
- `npm test -- path/to/file.test.ts`
- `npm test -- -t "test name"`

Go:
- `go test ./path/to/package`
- `go test ./path/to/package -run TestName`

Rust:
- `cargo test test_name`
- `cargo test -p crate_name`

### Lint / format command patterns (only when configured)
- JS/TS lint: `npm run lint` (or `pnpm lint`, `yarn lint`, `bun run lint`).
- JS/TS format check: `npm run format:check` or `npx prettier --check .`.
- Python lint: `ruff check .`.
- Python format: `ruff format .` or `black .`.
- Python type check: `mypy .` or `pyright`.
- Go lint: `golangci-lint run`.
- Go format: `gofmt -w .` (or repo wrapper).
- Rust lint: `cargo clippy --all-targets --all-features -D warnings`.
- Rust format: `cargo fmt --all -- --check`.

### Build command patterns (only when configured)
- JS/TS: `npm run build` (or package-manager equivalent).
- Python packaging: `python -m build`.
- Go: `go build ./...`.
- Rust: `cargo build --workspace`.
- Java/Kotlin: `./gradlew build` or `mvn -B verify`.

## 4) Code Style Guidelines
Because this repo has no active code conventions yet, use conservative defaults.

### Core principles
- Match local style in any touched file.
- Keep diffs focused; avoid drive-by refactors.
- Prefer clarity over cleverness.
- Use descriptive names and explicit control flow.
- Keep functions cohesive and reasonably small.

### Imports and dependencies
- Follow local import style; if none, group standard library, third-party, then local.
- Keep import ordering deterministic (formatter/linter defaults).
- Remove unused imports.
- Avoid adding dependencies unless clearly justified.

### Formatting
- Use project formatter when present.
- Keep indentation and line length consistent with nearby code.
- Avoid unrelated whitespace-only churn.
- Ensure files end with a trailing newline.

### Types and interfaces
- Prefer explicit types for public APIs.
- Keep internal types strict without excessive annotation noise.
- Avoid `any`/untyped escapes unless necessary, and explain why.
- Prefer designs that make invalid states hard to represent.

### Naming conventions
- Types/classes/components: `PascalCase`.
- Functions/variables: `camelCase` (or language-native convention).
- Constants: `UPPER_SNAKE_CASE` for true constants.
- Files: follow repo convention once it exists.
- Tests: name by behavior, not implementation details.

### Error handling and logging
- Validate inputs at boundaries and fail fast.
- Return/raise actionable errors.
- Preserve original context when wrapping/rethrowing errors.
- Never swallow errors silently.
- Keep logs concise and free of secrets/PII.

### Testing expectations
- Add/update tests for behavior changes.
- Prefer focused tests near touched logic.
- Cover at least one happy path and one edge/failure path.
- Keep tests deterministic and isolated.
- Use single-test runs during iteration; run broader suites before handoff.

### Documentation expectations
- Update docs when behavior or setup changes.
- Keep README and developer guidance aligned with actual tooling.
- Prefer short, runnable examples.

## 5) Safety and Change Management
- Never commit secrets or credentials.
- Avoid destructive operations unless explicitly requested.
- Do not revert unrelated local changes.
- Minimize blast radius: touch only required files.
- State assumptions clearly when config/tooling is missing.

## 6) Future Rule Files
If any of the following appear, re-read them and apply them immediately:
- `.cursor/rules/**`
- `.cursorrules`
- `.github/copilot-instructions.md`

If those files conflict with this document, repository-specific rule files take precedence.
