#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci-base-trusted.yml"
CHECKER = ROOT / ".github/scripts/check-ci-base-trusted-workflow.rb"
RUNNER = ROOT / ".github/scripts/ci-base-trusted.sh"


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )


def must_run(command: list[str], *, cwd: Path) -> str:
    result = run(command, cwd=cwd)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, f"fixture não contém ocorrência única: {old!r}"
    return source.replace(old, new, 1)


def check_contract(
    workflow_source: str,
    runner_source: str,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        workflow = temp / "ci-base-trusted.yml"
        runner = temp / "ci-base-trusted.sh"
        workflow.write_text(workflow_source)
        runner.write_text(runner_source)
        return run(["ruby", str(CHECKER), str(workflow), str(runner)], cwd=ROOT)


class PullRequestRepository:
    def __init__(self, root: Path) -> None:
        self.origin = root / "origin.git"
        self.work = root / "work"
        must_run(["git", "init", "--bare", str(self.origin)], cwd=root)
        must_run(["git", "init", str(self.work)], cwd=root)
        must_run(["git", "config", "user.name", "CI Test"], cwd=self.work)
        must_run(["git", "config", "user.email", "ci@example.invalid"], cwd=self.work)
        must_run(["git", "remote", "add", "origin", str(self.origin)], cwd=self.work)

        self._write("profile/README.md", "perfil base\n")
        self._write(".github/workflows/ci-base-trusted.yml", "workflow protegido\n")
        self._write(".github/scripts/ci-base-trusted.sh", "runner protegido\n")
        self._write(
            ".github/scripts/check-ci-base-trusted-workflow.rb",
            "checker protegido\n",
        )
        self._write(".github/scripts/test-ci-base-trusted.py", "testes protegidos\n")
        must_run(["git", "add", "."], cwd=self.work)
        must_run(["git", "commit", "-m", "base"], cwd=self.work)
        self.base_sha = must_run(["git", "rev-parse", "HEAD"], cwd=self.work)
        must_run(["git", "push", "origin", "HEAD:refs/heads/main"], cwd=self.work)

    def _write(self, relative_path: str, content: str) -> None:
        path = self.work / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def create_head(
        self,
        *,
        changes: dict[str, str] | None = None,
        removals: tuple[str, ...] = (),
    ) -> str:
        must_run(["git", "checkout", "--detach", self.base_sha], cwd=self.work)
        for relative_path, content in (changes or {"change.txt": "válido\n"}).items():
            self._write(relative_path, content)
        for relative_path in removals:
            (self.work / relative_path).unlink()
        must_run(["git", "add", "-A"], cwd=self.work)
        must_run(["git", "commit", "-m", "head"], cwd=self.work)
        head_sha = must_run(["git", "rev-parse", "HEAD"], cwd=self.work)
        must_run(
            ["git", "push", "--force", "origin", "HEAD:refs/pull/17/head"],
            cwd=self.work,
        )
        must_run(["git", "checkout", "--detach", self.base_sha], cwd=self.work)
        return head_sha

    def run_guard(
        self,
        head_sha: str,
        *,
        pr_number: str = "17",
        base_sha: str | None = None,
        path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PR_NUMBER": pr_number,
                "BASE_SHA": base_sha or self.base_sha,
                "HEAD_SHA": head_sha,
            }
        )
        if path is not None:
            env["PATH"] = path
        return run(["bash", str(RUNNER)], cwd=self.work, env=env)


assert WORKFLOW.is_file(), "workflow base-trusted ausente"
assert CHECKER.is_file(), "checker base-trusted ausente"
assert RUNNER.is_file(), "runner base-trusted ausente"

workflow_source = WORKFLOW.read_text()
runner_source = RUNNER.read_text()
control = check_contract(workflow_source, runner_source)
assert control.returncode == 0, control.stdout + control.stderr
assert control.stdout.strip() == "CI base-trusted workflow contract: ok"

validation_step = """\
      - name: Validar conteúdo não confiável
        shell: bash
        env:
          PR_NUMBER: ${{ github.event.pull_request.number }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          bash .github/scripts/ci-base-trusted.sh
"""

workflow_mutations = {
    "evento não confiável": (
        replace_once(workflow_source, "pull_request_target:", "pull_request:"),
        "evento diverge",
    ),
    "branch alterada": (
        replace_once(workflow_source, "branches: [main]", "branches: [develop]"),
        "evento diverge",
    ),
    "permission elevada": (
        replace_once(workflow_source, "contents: read", "contents: write"),
        "permissions divergem",
    ),
    "OIDC habilitado": (
        replace_once(
            workflow_source,
            "permissions:\n  contents: read\n",
            "permissions:\n  contents: read\n  id-token: write\n",
        ),
        "permissions divergem",
    ),
    "contexto removido": (
        replace_once(workflow_source, "    name: CI Success\n", ""),
        "job ci-success diverge",
    ),
    "contexto renomeado": (
        replace_once(
            workflow_source, "    name: CI Success", "    name: Outro contexto"
        ),
        "job ci-success diverge",
    ),
    "runner self-hosted": (
        replace_once(workflow_source, "runs-on: ubuntu-latest", "runs-on: self-hosted"),
        "runner diverge",
    ),
    "checkout não pinado": (
        replace_once(
            workflow_source,
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/checkout@v7",
        ),
        "steps divergem",
    ),
    "checkout do head": (
        replace_once(
            workflow_source,
            "ref: ${{ github.event.pull_request.base.sha }}",
            "ref: ${{ github.event.pull_request.head.sha }}",
        ),
        "steps divergem",
    ),
    "credencial persistida": (
        replace_once(
            workflow_source,
            "persist-credentials: false",
            "persist-credentials: true",
        ),
        "steps divergem",
    ),
    "checker removido": (
        replace_once(
            workflow_source,
            "          ruby .github/scripts/check-ci-base-trusted-workflow.rb\n",
            "",
        ),
        "steps divergem",
    ),
    "mutações removidas": (
        replace_once(
            workflow_source,
            "          python3 .github/scripts/test-ci-base-trusted.py\n",
            "",
        ),
        "steps divergem",
    ),
    "validação removida": (
        replace_once(workflow_source, validation_step, ""),
        "steps divergem",
    ),
    "validação mascarada": (
        replace_once(
            workflow_source,
            "          bash .github/scripts/ci-base-trusted.sh\n",
            "          bash .github/scripts/ci-base-trusted.sh || true\n",
        ),
        "steps divergem",
    ),
    "head derivado da base": (
        replace_once(
            workflow_source,
            "HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
            "HEAD_SHA: ${{ github.event.pull_request.base.sha }}",
        ),
        "steps divergem",
    ),
    "secret disponibilizado": (
        replace_once(
            workflow_source,
            "          PR_NUMBER: ${{ github.event.pull_request.number }}\n",
            "          SECRET_TOKEN: ${{ secrets.TEST }}\n"
            "          PR_NUMBER: ${{ github.event.pull_request.number }}\n",
        ),
        "steps divergem",
    ),
}

for name, (mutated, expected) in workflow_mutations.items():
    result = check_contract(mutated, runner_source)
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"mutação de workflow aceita: {name}"
    assert expected in output, f"diagnóstico inesperado para {name}: {output}"
    print(f"workflow mutation rejected: {name}")

masked_runner = replace_once(
    runner_source,
    'git diff --no-ext-diff --no-textconv --check "$BASE_SHA...$HEAD_SHA"',
    'git diff --no-ext-diff --no-textconv --check "$BASE_SHA...$HEAD_SHA" || true',
)
masked_result = check_contract(workflow_source, masked_runner)
masked_output = masked_result.stdout + masked_result.stderr
assert masked_result.returncode != 0, "runner com diff-check mascarado foi aceito"
assert "runner diverge" in masked_output, masked_output
print("runner mutation rejected: diff-check mascarado")

with tempfile.TemporaryDirectory() as temp_dir:
    repository = PullRequestRepository(Path(temp_dir))

    valid_head = repository.create_head()
    valid = repository.run_guard(valid_head)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert valid.stdout.strip() == "CI base-trusted content: ok"
    print("behavior accepted: conteúdo válido")

    whitespace_head = repository.create_head(changes={"bad.txt": "espaço inválido \n"})
    whitespace = repository.run_guard(whitespace_head)
    assert whitespace.returncode != 0, "whitespace inválido foi aceito"
    print("behavior rejected: whitespace inválido")

    empty_profile_head = repository.create_head(changes={"profile/README.md": ""})
    empty_profile = repository.run_guard(empty_profile_head)
    assert empty_profile.returncode != 0, "profile vazio foi aceito"
    assert "profile/README.md vazio" in empty_profile.stderr, empty_profile.stderr
    print("behavior rejected: profile vazio")

    absent_profile_head = repository.create_head(removals=("profile/README.md",))
    absent_profile = repository.run_guard(absent_profile_head)
    assert absent_profile.returncode != 0, "profile ausente foi aceito"
    assert "profile/README.md ausente" in absent_profile.stderr, absent_profile.stderr
    print("behavior rejected: profile ausente")

    trusted_head = repository.create_head(
        changes={".github/scripts/ci-base-trusted.sh": "alterado\n"}
    )
    trusted = repository.run_guard(trusted_head)
    assert trusted.returncode != 0, "path trusted alterado foi aceito"
    assert "workflow/scripts protegidos alterados" in trusted.stderr, trusted.stderr
    print("behavior rejected: path trusted alterado")

    invalid_number = repository.run_guard(valid_head, pr_number="17;echo")
    assert invalid_number.returncode != 0, "número de PR inválido foi aceito"
    assert "PR_NUMBER inválido" in invalid_number.stderr, invalid_number.stderr
    print("behavior rejected: número de PR inválido")

    invalid_sha = repository.run_guard("HEAD")
    assert invalid_sha.returncode != 0, "SHA inválido foi aceito"
    assert "HEAD_SHA inválido" in invalid_sha.stderr, invalid_sha.stderr
    print("behavior rejected: SHA inválido")

    divergent_sha = repository.run_guard("0" * 40)
    assert divergent_sha.returncode != 0, "SHA divergente do ref foi aceito"
    assert "FETCH_HEAD diverge de HEAD_SHA" in divergent_sha.stderr, (
        divergent_sha.stderr
    )
    print("behavior rejected: SHA divergente")

    expected_head = repository.create_head(changes={"expected.txt": "esperado\n"})
    repository.create_head(changes={"other.txt": "outro ref\n"})
    divergent_ref = repository.run_guard(expected_head)
    assert divergent_ref.returncode != 0, "ref divergente foi aceito"
    assert "FETCH_HEAD diverge de HEAD_SHA" in divergent_ref.stderr, (
        divergent_ref.stderr
    )
    print("behavior rejected: ref divergente")

    with tempfile.TemporaryDirectory() as fake_bin_dir:
        fake_bin = Path(fake_bin_dir)
        fake_git = fake_bin / "git"
        real_git = shutil.which("git")
        assert real_git is not None
        fake_git.write_text(
            "#!/bin/sh\n"
            'case " $* " in\n'
            '  *" --check "*) exit 88 ;;\n'
            "esac\n"
            'exec "$REAL_GIT" "$@"\n'
        )
        fake_git.chmod(0o755)
        os.environ["REAL_GIT"] = real_git
        failed_command = repository.run_guard(
            valid_head,
            path=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        )
        assert failed_command.returncode != 0, (
            "falha do comando obrigatório foi mascarada"
        )
        print("behavior rejected: comando obrigatório falhou")

print("CI base-trusted mutations: ok")
