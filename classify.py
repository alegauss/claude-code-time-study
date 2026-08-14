"""Classification rules: which file is a test, which command runs tests, etc.

Kept separate from analyze.py so the heuristics can be tuned without touching
the parsing/attribution machinery.
"""

import re

# --------------------------------------------------------------------------
# File-path classification
# --------------------------------------------------------------------------

_TEST_DIR_PARTS = (
    "/test/", "/tests/", "/__tests__/", "/spec/", "/specs/",
    "/src/test/", "/testing/", "/e2e/", "/it/", "/integration-tests/",
    "/cypress/", "/playwright/", "/test-utils/",
)

_TEST_FILE_RE = re.compile(
    r"(?:^|[/\\])(?:"
    r"test_[^/\\]+\.py"
    r"|[^/\\]+_test\.(?:py|go|ts|js|rb|dart)"
    r"|[^/\\]+\.(?:test|spec)\.(?:ts|tsx|js|jsx|mjs|cjs|py)"
    r"|[^/\\]+(?:Test|Tests|TestCase|IT|ITCase)\.(?:java|kt|cs|scala|groovy)"
    r"|[^/\\]+Spec\.(?:java|kt|rb|groovy|js|ts)"
    r"|conftest\.py"
    r"|[^/\\]*[Ff]ixtures?\.(?:py|ts|js|java)"
    r")$"
)

_DOC_EXT = {
    ".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc",
}

_CONFIG_EXT = {
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".properties",
    ".xml", ".lock", ".env", ".editorconfig", ".gitignore", ".dockerignore",
    ".csv", ".tsv",
}

_CONFIG_NAMES = {
    "dockerfile", "makefile", "jenkinsfile", "procfile", "vagrantfile",
    "package.json", "pom.xml", "build.gradle", "requirements.txt",
    "pyproject.toml", "cargo.toml", "go.mod", "go.sum",
}

_CODE_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".scala", ".groovy",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".m", ".dart", ".vue", ".svelte",
    ".css", ".scss", ".less", ".sass", ".html", ".htm", ".jsp", ".ftl",
    ".sh", ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".ex", ".exs", ".lua",
}


def _ext(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return base[dot:].lower() if dot > 0 else ""


def classify_path(path: str) -> str:
    """Return one of: test, code, docs, config, unknown."""
    if not path:
        return "unknown"
    p = path.replace("\\", "/")
    low = p.lower()
    base = low.rsplit("/", 1)[-1]
    ext = _ext(low)

    # A test file wins over everything else -- a .yml inside /tests/ that a
    # test reads as a fixture is still test-authoring work.
    if any(part in low for part in _TEST_DIR_PARTS) or _TEST_FILE_RE.search(p):
        return "test"

    if ext in _DOC_EXT:
        return "docs"
    if base in _CONFIG_NAMES or ext in _CONFIG_EXT:
        return "config"
    if ext in _CODE_EXT:
        return "code"
    return "unknown"


# --------------------------------------------------------------------------
# Bash-command classification
# --------------------------------------------------------------------------

# An ad-hoc script passed inline rather than run from a file. Extremely common
# and it hides its real intent in the body, so it gets a dedicated look.
_INLINE_SCRIPT_RE = re.compile(
    r"(?:python[23]?|node|deno|bun)\s+(?:-\s*(?:<<|$)|-c\b|-e\b|-p\b|-m\s+py_compile)"
    r"|<<\s*'?(?:PY|PYEOF|EOF|JS|NODE)'?",
    re.I)

# Inside an inline script, these mean it is asserting behaviour, not inspecting.
_INLINE_TEST_RE = re.compile(
    r"\b(?:assert\w*|unittest|pytest|expect\(|should\b|describe\(|it\("
    r"|self\.assert|raise\s+AssertionError|test_\w+)", re.I)

# Ordered: first match wins.
_CMD_RULES = [
    ("test_run", re.compile(
        r"\b(?:"
        r"pytest|py\.test|python[23]?\s+-m\s+(?:pytest|unittest)|unittest|nose2|tox"
        r"|jest|vitest|mocha|jasmine|karma|ava\b|tap\b"
        r"|node\s+--test|--test-force-exit|--experimental-test"
        r"|playwright\s+test|cypress\s+(?:run|open)|testcafe"
        r"|npm\s+(?:run\s+)?test|npm\s+run\s+test:|yarn\s+test|pnpm\s+(?:run\s+)?test"
        r"|mvn\w*\s+[^\n]*\btest\b|mvn\w*\s+[^\n]*\bverify\b|gradlew?\s+[^\n]*\btest\b"
        r"|go\s+test|cargo\s+test|dotnet\s+test|phpunit|rspec|minitest"
        r"|ctest|bats\b|behave|robot\b|coverage\s+run|nyc\b|c8\b"
        r")", re.I)),
    ("verify", re.compile(
        r"\b(?:"
        r"tsc\b|eslint|prettier|ruff|flake8|pylint|mypy|black\b|isort"
        r"|npm\s+run\s+(?:build|lint|typecheck|check|compile)"
        r"|yarn\s+(?:build|lint)|pnpm\s+(?:build|lint)"
        r"|mvn\w*\s+(?:clean\s+)?(?:compile|package|install)|gradlew?\s+build"
        r"|go\s+(?:build|vet)|cargo\s+(?:build|check|clippy)|dotnet\s+build"
        r"|make\b|cmake|webpack|vite\s+build|next\s+build|docker\s+build"
        r"|checkstyle|spotless|sonar"
        r")", re.I)),
    ("run_app", re.compile(
        r"\b(?:"
        r"npm\s+(?:run\s+)?(?:dev|start|serve|preview)|yarn\s+(?:dev|start)"
        r"|pnpm\s+(?:dev|start)|vite\b(?!\s+build)|next\s+dev"
        r"|docker(?:\s+compose)?\s+(?:up|run|start)|docker-compose\s+up"
        r"|flask\s+run|uvicorn|gunicorn|manage\.py\s+runserver"
        r"|spring-boot:run|java\s+-jar|dotnet\s+run|\.exe\b"
        r"|python[23]?\s+-m\s+\w+|PYTHONPATH=|python[23]?\s+[^\s]+\.py\b"
        r"|node\s+[^\s-]+\.(?:js|mjs|cjs)\b"
        r"|curl\b|wget\b|Invoke-(?:WebRequest|RestMethod)|http\s"
        r")", re.I)),
    ("vcs", re.compile(
        r"\b(?:git|gh|run-commit(?:\.cmd)?|hub)\b", re.I)),
    ("explore", re.compile(
        r"\b(?:cat|head|tail|less|more|grep|rg|find|ls|dir|tree|wc"
        r"|Get-(?:Content|ChildItem|Item)|Select-String|Test-Path"
        r"|jq\b|awk|sed\s+-n)\b", re.I)),
]


def classify_command(cmd: str) -> str:
    """Return one of: test_run, verify, run_app, vcs, explore, other."""
    if not cmd:
        return "other"
    # Only look at the first ~600 chars for intent; long heredocs are payload.
    head = cmd[:600]

    # An explicit test runner anywhere in the line beats everything else.
    if _CMD_RULES[0][1].search(head):
        return "test_run"

    # Inline scripts declare nothing useful in their first tokens, so read the
    # body: asserting behaviour is a test, anything else is an ad-hoc check.
    if _INLINE_SCRIPT_RE.search(head):
        return "test_run" if _INLINE_TEST_RE.search(cmd[:4000]) else "verify"

    for label, rx in _CMD_RULES[1:]:
        if rx.search(head):
            return label
    return "other"


# --------------------------------------------------------------------------
# User-prompt classification -- did the human just test something by hand?
# --------------------------------------------------------------------------

_MANUAL_TEST_RE = re.compile(
    r"\b(?:"
    # Portuguese
    r"testei|testando|testar|testou|funcionou|n[ãa]o\s+funcion\w*|deu\s+erro"
    r"|abri\s+o|rodei|executei|cliquei|apareceu|n[ãa]o\s+aparece|continua\s+"
    r"|quebrou|travou|est[áa]\s+errado|olha\s+(?:o|a)\s+"
    # English
    r"|i\s+tested|i\s+ran|i\s+tried|i\s+clicked|it\s+works|doesn'?t\s+work"
    r"|still\s+(?:broken|fails|failing)|got\s+(?:an?\s+)?error|reproduce"
    r")", re.I)

_REVIEW_RE = re.compile(
    r"\b(?:revis\w+|review|olhei|vi\s+que|acho\s+que|prefiro|melhor\s+seria"
    r"|na\s+verdade|actually|instead|refactor|renomeia|muda\s+)", re.I)


def classify_prompt(text: str, has_image: bool) -> str:
    """Return one of: manual_test, review, direction."""
    if has_image:
        # A pasted screenshot is near-conclusive evidence of hands-on testing.
        return "manual_test"
    if not text:
        return "direction"
    head = text[:1500]
    if _MANUAL_TEST_RE.search(head):
        return "manual_test"
    if _REVIEW_RE.search(head):
        return "review"
    return "direction"


# --------------------------------------------------------------------------
# Tool -> work-phase mapping
# --------------------------------------------------------------------------

_EXPLORE_TOOLS = {
    "Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch",
    "Task", "Agent", "Explore", "ToolSearch", "Skill", "LS",
}
_WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Update"}

# Deciding what to do and tracking it -- overhead that exists with or without
# Claude, so it is worth seeing separately rather than buried in "other".
_PLANNING_TOOLS = {
    "TodoWrite", "AskUserQuestion", "ExitPlanMode", "EnterPlanMode",
    "CronCreate", "CronDelete", "CronList", "ScheduleWakeup", "Workflow",
    "TaskOutput", "TaskStop", "SendMessage", "PushNotification",
}

# Roadkeep operations that only read or bookkeep, as opposed to the ones that
# write roadmap prose.
_ROADKEEP_QUERY_OPS = {
    "list", "pick", "budget", "lint", "claim", "block_list", "non_goal_list",
    "get", "show", "status", "next", "brief", "diff", "search",
}


def classify_tool(name: str, tool_input: dict) -> str:
    """Map a tool_use to a work phase.

    Returns one of: feature, test_write, docs_write, config_write, test_run,
    verify, run_app, explore, planning, vcs, other.
    """
    if name.startswith("mcp__roadkeep__"):
        # Roadkeep is both planning and documentation: the operations that
        # mutate the roadmap are authoring docs, the rest is planning.
        op = name[len("mcp__roadkeep__"):]
        return "planning" if op in _ROADKEEP_QUERY_OPS else "docs_write"

    if name in _PLANNING_TOOLS:
        return "planning"
    if name in _WRITE_TOOLS:
        kind = classify_path(tool_input.get("file_path") or
                             tool_input.get("notebook_path") or "")
        return {
            "test": "test_write",
            "code": "feature",
            "docs": "docs_write",
            "config": "config_write",
        }.get(kind, "feature")

    if name == "Bash" or name == "PowerShell":
        cmd = tool_input.get("command") or ""
        c = classify_command(cmd)
        if c == "explore":
            return "explore"
        return c

    if name in _EXPLORE_TOOLS:
        return "explore"

    return "other"
