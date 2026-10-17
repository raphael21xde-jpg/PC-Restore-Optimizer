<#
.SYNOPSIS
  Validacao segura do PC Restore & Optimizer com fontes ficticias.
.DESCRIPTION
  Nao inicia o app, nao formata, nao exclui arquivos do usuario e nao executa
  testes de 2 GiB automaticamente. Salva logs em pasta NOVA no perfil.
#>
param([switch]$Completo, [string]$Apenas = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$pythonCommand = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python Launcher 'py' nao encontrado. Instale o Python 3 para Windows."
}
$pythonExecutable = $pythonCommand.Source

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
$folder = Join-Path $HOME ("PCRO-Relatorios\validacao-" + $stamp)
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$results = [System.Collections.ArrayList]::new()

function Invoke-PcroCheck {
    param([string]$Id, [string[]]$CmdArgs)
    $log = Join-Path $folder ($Id + ".log")
    $stdout = Join-Path $folder ($Id + ".stdout.log")
    $stderr = Join-Path $folder ($Id + ".stderr.log")
    $started = Get-Date
    Write-Host ("[PCRO] Executando: " + $Id) -ForegroundColor Cyan
    $code = -1
    $errorMessage = $null
    try {
        # Windows PowerShell 5.1 promotes Python's unittest stderr output
        # to NativeCommandError if piped with 2>&1 under Stop. This caused
        # every successful test to be reported incorrectly as a failure.
        # Redirect streams at the OS process level and rely on ExitCode.
        $process = Start-Process -FilePath $pythonExecutable -ArgumentList $CmdArgs `
            -NoNewWindow -Wait -PassThru -ErrorAction Stop `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $code = [int]$process.ExitCode
        foreach ($part in @($stdout, $stderr)) {
            if (Test-Path -LiteralPath $part -PathType Leaf) {
                Get-Content -LiteralPath $part -Encoding UTF8 |
                    Tee-Object -FilePath $log -Append
            }
        }
    }
    catch {
        $errorMessage = $_.Exception.Message
        ("Erro ao iniciar ou registrar teste: " + $errorMessage) |
            Out-File -FilePath $log -Encoding UTF8 -Append
        Write-Host ("[PCRO] Falha no executor: " + $errorMessage) -ForegroundColor Red
    }
    $result = [pscustomobject]@{
        teste = $Id
        aprovado = ($code -eq 0)
        codigo_saida = $code
        erro_executor = $errorMessage
        duracao_segundos = [math]::Round(((Get-Date)-$started).TotalSeconds, 2)
        log = $log
    }
    [void]$results.Add($result)
    Write-Host ("[PCRO] " + $Id + ": " +
        $(if ($result.aprovado) { "APROVADO" } else { "FALHOU" }) +
        " (codigo " + $code + ")")
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
if ($Apenas) {
    if ($Completo) {
        throw "Nao combine -Apenas com -Completo."
    }
    if ($Apenas -notin $patterns) {
        throw "Nome de teste fora da lista de verificacoes seguras."
    }
    $patterns = @($Apenas)
}
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
