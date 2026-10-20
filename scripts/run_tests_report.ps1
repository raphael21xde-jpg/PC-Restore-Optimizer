# Executa testes locais, registra o log e (se solicitado) comenta no PR.
# Funciona no PowerShell 5.1 e 7, sem GitHub Actions ou git push.
param(
    [ValidateSet("multidisco", "completo")]
    [string]$Suite = "multidisco",
    [string]$Padrao = "",
    [int]$Pr = 54,
    [switch]$Publicar
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Padrao)) {
    if ($Suite -eq "completo") {
        $Padrao = "test_*.py"
    } else {
        $Padrao = "test_multi_source*.py"
    }
}

$script = Join-Path $PSScriptRoot "test_reporter.py"
$arguments = @(
    "-3", $script,
    "--pattern", $Padrao,
    "--repo", "raphael21xde-jpg/PC-Restore-Optimizer",
    "--pr", [string]$Pr
)
if ($Publicar) {
    $arguments += "--publish"
}

& py @arguments
exit $LASTEXITCODE
