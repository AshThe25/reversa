"""Guards the one boundary that makes every metric in this project meaningful.

GroundTruth is the simulator's answer key. If any engine reads it, the
evaluation numbers become circular and worthless. I did not want that to depend
on me remembering, so this walks the AST of every module under reversa/ and
fails the build if anything outside the allowlist so much as names it.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "reversa"

# The world writes and resolves ground truth (it IS the world), evaluation reads
# it to score us, models defines it. Nobody else gets to know it exists.
ALLOWED = {
    "models.py",
    "world/generator.py",
    "world/outcomes.py",
    "engines/evaluation_engine.py",
}

FORBIDDEN_NAMES = {"GroundTruth", "ground_truth", "resolve_u",
                   "true_p_natural", "true_best_action", "recovers_naturally"}


def _modules():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or rel.endswith("__init__.py"):
            continue
        yield rel, path


def test_no_engine_touches_the_answer_key():
    leaks = []
    for rel, path in _modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.alias):
                name = node.asname or node.name.rsplit(".", 1)[-1]
            if name in FORBIDDEN_NAMES:
                leaks.append(f"{rel}:{getattr(node, 'lineno', '?')} references {name}")
    assert not leaks, (
        "ground truth leaked into the system:\n  " + "\n  ".join(leaks)
    )


def test_allowlist_entries_still_exist():
    """A rename shouldn't silently turn the guard above into a no-op."""
    for rel in ALLOWED:
        assert (ROOT / rel).exists(), f"allowlisted module {rel} is gone"
