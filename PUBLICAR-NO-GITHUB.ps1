param([string]$RepoUrl = "https://github.com/raphael21xde-jpg/PC-Restore-Optimizer.git")
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "Git nao encontrado. Instale Git for Windows ou GitHub Desktop." -ForegroundColor Yellow
  exit 1
}
$clone = Join-Path $env:TEMP ("pcro-publish-" + [guid]::NewGuid().ToString("N"))
Write-Host "Clonando o repositorio privado para uma pasta temporaria..."
git clone $RepoUrl $clone
if ($LASTEXITCODE -ne 0) { throw "Falha no clone. Confirme acesso ao repositorio com sua conta GitHub." }
try {
  $excludeDirs = @(".git", "__pycache__", ".venv", "venv", "backups", "Backups", "vaults", "restore-data", ".pytest_cache")
  $excludeFiles = @("*.pyc", "*.pyo", "*.log", "*.bak", "*.tmp", "*.csv", "*.sqlite", "*.db", "*.key", "*.pem", "*.pfx", "*.zip", "*.7z", "*.iso", "*.img", "*.vhd", "*.vhdx", "*.wim", "*.esd", ".env")
  & robocopy $here $clone /E /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -gt 7) { throw "Falha ao copiar os arquivos (robocopy codigo $LASTEXITCODE)." }
  Push-Location $clone
  try {
    git add .
    Write-Host ""
    git status --short
    Write-Host ""
    Write-Host "Confira acima. NAO prossiga se aparecerem dados pessoais, senhas ou backups."
    $ok = Read-Host "Digite PUBLICAR para fazer o commit e enviar ao GitHub"
    if ($ok -cne "PUBLICAR") { Write-Host "Operacao cancelada sem commit."; exit 0 }
    git commit -m "feat: incorporar base de codigo v0.7.0-dev e testes"
    if ($LASTEXITCODE -ne 0) { throw "Falha no commit. Configure git user.name e user.email." }
    git push origin HEAD:main
    if ($LASTEXITCODE -ne 0) { throw "Falha no push. Verifique sua autenticacao no GitHub." }
    Write-Host "Codigo publicado com sucesso."
  } finally { Pop-Location }
} finally {
  Write-Host "Copia temporaria em $clone"
}
