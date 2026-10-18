"""Execute local unittest suites and optionally post sanitized details to a PR.

No GitHub Actions, pushes, filesystem scans, destructive operations or tokens
are required by this script. Only --publish invokes the GitHub CLI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / ".pcro-test-reports"
DEFAULT_REPO = "raphael21xde-jpg/PC-Restore-Optimizer"
MAX_DETAILS = 38_000


def sanitize_for_public_comment(value: str, home: Path | None = None) -> str:
    """Best-effort redaction. Review the preview: never assume logs are private."""
    home_str = str(home or Path.home())
    for prefix in (home_str, home_str.replace("\\", "/")):
        if prefix:
            value = re.sub(re.escape(prefix), "[HOME]", value, flags=re.IGNORECASE)
    value = re.sub(
        r"(?i)[a-z]:[\\/]Users[\\/][^\\/\s'\"<>]+",
        "[USER_HOME]", value)
    value = re.sub(
        r"(?i)\b(?:github_pat_[a-z0-9_]{12,}|gh[pousr]_[a-z0-9_]{12,}|sk-[a-z0-9_-]{10,})\b",
        "[REDACTED_TOKEN]", value)
    value = re.sub(
        r"(?i)(\b(?:authorization|token|password|secret|api[_-]?key)\s*[:=]\s*)([^\s,;]+)",
        r"\1[REDACTED]", value)
    value = re.sub(
        r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
        "[REDACTED_EMAIL]", value)
    value = value.replace("\x00", "")
    return value


def result_summary(log: str) -> str:
    lines = log.splitlines()
    selected = [line.strip() for line in lines
                if re.match(r"^\s*(?:Ran \d+ tests? in |OK(?:\s|$)|FAILED(?:\s|$))", line)]
    if selected:
        return "\n".join(selected[-2:])
    return "Resumo padrao do unittest nao localizado; consulte o log."


def report_comment(log: str, *, pattern: str, exit_code: int,
                   sha: str, date_utc: str) -> str:
    # Every published line is sanitized, including headers and stack traces.
    clean = sanitize_for_public_comment(log)
    tail = clean[-MAX_DETAILS:]
    cropped = len(clean) > len(tail)
    tail = tail.replace("~~~~", "----")
    summary = sanitize_for_public_comment(result_summary(log))
    status = "PASSOU" if exit_code == 0 else "FALHOU"
    return (
        "## PC Restore & Optimizer - testes locais\n\n"
        f"- Status: **{status}** (codigo de saida {exit_code})\n"
        f"- Data UTC: {date_utc}\n"
        f"- Commit testado: `{sha}`\n"
        f"- Padrao de testes: `{pattern}`\n"
        "- Execucao: **PowerShell/local, sem GitHub Actions**\n\n"
        "### Resultado\n\n"
        "~~~text\n" + summary + "\n~~~\n\n"
        "<details><summary>Saida detalhada sanitizada "
        + ("(trecho final; log integral salvo apenas no PC)" if cropped else "(completa)")
        + "</summary>\n\n~~~text\n" + tail + "\n~~~\n</details>\n\n"
        "> Revise o comentario antes de publicar informacoes sensiveis; a sanitizacao e preventiva, nao infalivel.\n"
    )


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=8, check=True)
        return result.stdout.strip() or "desconhecido"
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"


def run_unittest(pattern: str, log_path: Path) -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8:replace"
    command = [sys.executable, "-m", "unittest", "discover",
               "-s", "tests", "-p", pattern, "-v"]
    print("Executando:", " ".join(command), flush=True)
    with log_path.open("w", encoding="utf-8") as output:
        try:
            with subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=env, encoding="utf-8",
                errors="replace", text=True, bufsize=1,
            ) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    output.write(line)
                    output.flush()
                    print(line, end="", flush=True)
                return process.wait()
        except KeyboardInterrupt:
            print("\nInterrompido pelo usuario.", file=sys.stderr)
            return 130
        except OSError as error:
            print("Falha ao executar Python:", error, file=sys.stderr)
            output.write(f"Falha de execucao: {error}\n")
            return 127


def publish_comment(path: Path, repo: str, pr: int) -> bool:
    if not shutil.which("gh"):
        print("GitHub CLI nao encontrado. Instale com: winget install --id GitHub.cli --source winget")
        return False
    command = ["gh", "pr", "comment", str(pr), "--repo", repo,
               "--body-file", str(path)]
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True,
            text=True, timeout=45, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as error:
        print("Nao foi possivel publicar:", sanitize_for_public_comment(str(error)))
        return False
    if result.returncode:
        print("Publicacao falhou:", sanitize_for_public_comment(result.stderr.strip()))
        print("Confira a autenticacao usando: gh auth status")
        return False
    print("Relatorio publicado no PR:", f"https://github.com/{repo}/pull/{pr}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Testes locais com relatorio para PR.")
    parser.add_argument("--pattern", default="test_multi_source*.py")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--pr", type=int, default=54)
    parser.add_argument("--publish", action="store_true",
                        help="Publica no PR; sem essa flag os dados ficam somente no PC.")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"test_[a-zA-Z0-9_*?.-]+\.py", args.pattern):
        parser.error("Use apenas padroes test_*.py ou nomes de arquivos de teste.")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or args.pr <= 0:
        parser.error("Repositorio ou numero de PR invalido.")

    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = stamp + "-" + uuid.uuid4().hex[:6]
    log_path = REPORT_DIR / (run_id + ".log")
    preview_path = REPORT_DIR / (run_id + "-previsualizacao.md")
    outcome = run_unittest(args.pattern, log_path)
    log = log_path.read_text(encoding="utf-8", errors="replace")
    # unittest may exit successfully even when discovery matches no tests.
    if not re.search(r"(?m)^Ran [1-9][0-9]* tests? in ", log):
        print("Nenhum teste foi encontrado ou o resumo esta ausente.", file=sys.stderr)
        outcome = outcome or 4
    preview_path.write_text(
        report_comment(log, pattern=args.pattern, exit_code=outcome,
                       sha=git_commit(), date_utc=stamp + " UTC"),
        encoding="utf-8")
    print("\nLog integral local:", log_path)
    print("Previa sanitizada para publicacao:", preview_path)
    if args.publish:
        success = publish_comment(preview_path, args.repo, args.pr)
        if not success:
            return outcome if outcome else 3
    else:
        print("Nao publicado. Execute novamente com --publish para enviar ao PR.")
    return outcome


if __name__ == "__main__":
    sys.exit(main())
