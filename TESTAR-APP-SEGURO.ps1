<#
.SYNOPSIS
  Validacao segura do PC Restore & Optimizer com fontes ficticias.
.DESCRIPTION
  Nao inicia o app, nao formata, nao exclui arquivos do usuario e nao executa
  testes de 2 GiB automaticamente. Salva logs em pasta NOVA no perfil.
#>
param([switch]$Completo)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher 'py' nao encontrado. Instale o Python 3 para Windows."
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
$folder = Join-Path $HOME ("PCRO-Relatorios\validacao-" + $stamp)
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$results = [System.Collections.ArrayList]::new()

function Invoke-PcroCheck {
    param([string]$Id, [string[]]$CmdArgs)
    $log = Join-Path $folder ($Id + ".log")
    $started = Get-Date
    Write-Host ("[PCRO] Executando: " + $Id) -ForegroundColor Cyan
    $code = 1
    try {
        & py @CmdArgs 2>&1 | Tee-Object -FilePath $log
        $code = $LASTEXITCODE
    }
    catch {
        ("Excecao durante teste: " + $_.Exception.Message) |
            Out-File -FilePath $log -Encoding UTF8 -Append
        Write-Host ("[PCRO] Falha ao executar " + $Id) -ForegroundColor Red
    }
    $result = [pscustomobject]@{
        teste = $Id
        aprovado = ($code -eq 0)
        codigo_saida = $code
        duracao_segundos = [math]::Round(((Get-Date)-$started).TotalSeconds, 2)
        log = $log
    }
    [void]$results.Add($result)
    Write-Host ("[PCRO] " + $Id + ": " +
        $(if ($result.aprovado) { "APROVADO" } else { "FALHOU" }))
}

$patterns = @(
    "test_inventory_paged_v044_v046.py",
    "test_inventory_file_index.py",
    "test_index_choices_bridge.py",
    "test_file_index_ui.py",
    "test_selection_backup_restore_e2e_v047.py",
    "test_backup_target_preflight_v082.py",
    "test_safe_features.py"
)
foreach ($pattern in $patterns) {
    $label = $pattern -replace '[^A-Za-z0-9_-]', '_'
    Invoke-PcroCheck -Id $label -CmdArgs @(
        '-3','-m','unittest','discover','-s','tests','-p',$pattern,'-v')
}
if ($Completo) {
    Write-Host "[PCRO] Iniciando regressao completa. Pode levar varios minutos."
    Invoke-PcroCheck -Id "regressao-completa" -CmdArgs @(
        '-3', 'tests/run_full_suite.py', '--timeout', '420')
}
$approved = @($results | Where-Object { $_.aprovado }).Count
$failed = @($results | Where-Object { -not $_.aprovado }).Count
$report = [ordered]@{
    schema = 'pcro-local-validation-v047'
    data = (Get-Date).ToString('o')
    modo = $(if ($Completo) { 'completo' } else { 'rapido' })
    testes_aprovados = $approved
    testes_falhos = $failed
    testes = @($results)
    fontes_reais_examinadas = $false
    backup_real_do_usuario_executado = $false
    ready_for_format = $false
    installation_authorized = $false
}
$output = Join-Path $folder "resultado-validacao-pcro.json"
$report | ConvertTo-Json -Depth 6 |
    Set-Content -LiteralPath $output -Encoding UTF8
Write-Host ("[PCRO] Relatorio: " + $output) -ForegroundColor Cyan
Write-Host ("[PCRO] Verificacoes aprovadas: " + $approved +
    " | falhas: " + $failed)
if ($failed -gt 0) { exit 1 }
