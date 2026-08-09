#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
CHECKER = ROOT / ".github/scripts/check-ci-workflow.rb"


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, f"fixture não contém ocorrência única: {old!r}"
    return source.replace(old, new, 1)


def check(source: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml") as fixture:
        fixture.write(source)
        fixture.flush()
        return subprocess.run(
            ["ruby", str(CHECKER), fixture.name],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )


assert CHECKER.is_file(), "checker versionado ausente"
workflow = WORKFLOW.read_text()
control = check(workflow)
assert control.returncode == 0, control.stdout + control.stderr
assert control.stdout.strip() == "CI workflow contract: ok", control.stdout

validation_step = """\
      - name: Validar diff e profile
        shell: bash
        run: |
          set -euo pipefail
          git diff --check \"${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }}\"
          test -s profile/README.md
"""

mutations = {
    "tag explícita em chave": (
        replace_once(workflow, "permissions:\n", "!!str permissions:\n"),
        "tags YAML explícitas não são permitidas",
    ),
    "anchor em chave": (
        replace_once(workflow, "permissions:\n", "&permissions permissions:\n"),
        "anchors não são permitidos",
    ),
    "top-level extra": (
        replace_once(workflow, "permissions:\n", "env: {}\n\npermissions:\n"),
        "top-level diverge",
    ),
    "chave on substituída por true": (
        replace_once(workflow, "on:\n", "true:\n"),
        "top-level diverge",
    ),
    "branch do evento alterada": (
        replace_once(workflow, "branches: [main]", "branches: [develop]"),
        "evento diverge",
    ),
    "permission elevada": (
        replace_once(workflow, "contents: read", "contents: write"),
        "permissions divergem",
    ),
    "diff-check removido": (
        replace_once(
            workflow,
            '          git diff --check "${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }}"\n',
            "",
        ),
        "steps divergem",
    ),
    "profile-check removido": (
        replace_once(workflow, "          test -s profile/README.md\n", ""),
        "steps divergem",
    ),
    "step de validação removido": (
        replace_once(workflow, validation_step, ""),
        "steps divergem",
    ),
    "contexto removido": (
        replace_once(workflow, "    name: CI Success\n", ""),
        "job ci-success diverge",
    ),
    "contexto renomeado": (
        replace_once(workflow, "    name: CI Success", "    name: Outro contexto"),
        "job ci-success diverge",
    ),
    "job renomeado": (
        replace_once(workflow, "  ci-success:\n", "  outro-job:\n"),
        "jobs divergem",
    ),
    "runner self-hosted": (
        replace_once(workflow, "runs-on: ubuntu-latest", "runs-on: self-hosted"),
        "runner diverge",
    ),
    "checkout não pinado": (
        replace_once(
            workflow,
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/checkout@v7",
        ),
        "steps divergem",
    ),
    "credencial persistida": (
        replace_once(
            workflow, "persist-credentials: false", "persist-credentials: true"
        ),
        "steps divergem",
    ),
    "checker removido do gate": (
        replace_once(
            workflow, "          ruby .github/scripts/check-ci-workflow.rb\n", ""
        ),
        "steps divergem",
    ),
}

for name, (mutated, expected) in mutations.items():
    result = check(mutated)
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"mutação aceita: {name}"
    assert expected in output, f"diagnóstico inesperado para {name}: {output}"
    print(f"mutation rejected: {name}")

print("CI workflow mutations: ok")
