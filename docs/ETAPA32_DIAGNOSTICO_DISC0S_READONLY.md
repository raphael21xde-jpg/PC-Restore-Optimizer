# Etapa 32 — Diagnóstico atualizado de discos (somente leitura)

**Base:** `docs/release-readiness-audit-20261019`, auditoria da Etapa 31.

## Objetivo

Iniciar a resolução do bloqueador P0 da auditoria: relacionar as unidades de
origem e os destinos *escolhidos pelo usuário* com discos lógicos e alertas de
inicialização, sem pressupor letras fixas. Não habilitar nenhuma cópia real nem
qualquer operação destrutiva.

- `drive_safety_report.py`: recebe uma seleção explícita de origens/destinos,
  recolhe um **novo** inventário pelo coletor `diagnostics.disk_inventory`
  e produz um resumo de inspeção. Em testes, aceita um coletor fictício.
- `scripts/diagnose_disks_readonly.py`: modo opcional de linha de comando
  para execução local no Windows, somente leitura. Não grava arquivo, não
  publica nem envia relatórios para o GitHub.
- `tests/test_drive_safety_report.py`: casos sintéticos para cruzamento
  lógico, volume de boot, ausência de extents, dados duplicados, espaço,
  falhas de coleta, entrada inválida e ocultação de identificadores.

O resumo inclui apenas letras de volume, números lógicos, estados e motivos
de bloqueio. **Não imprime número de série, nome/modelo, caminho local,
conteúdo dos discos, GUID de volume nem saída bruta de PowerShell.**

## Executar os testes (sem GitHub Actions)

```powershell
py -3 scripts\test_reporter.py --pattern "test_drive_safety_report.py" --publish
```

O `--publish` publica somente o log de teste sanitizado no PR #54. Revise
a prévia antes de publicar em um PR público.

## Diagnóstico opcional de um computador Windows

Executar somente se desejar conferir o **inventário atual**, substituindo
as letras **pelas unidades que você escolheu**:

```powershell
py -3 scripts\diagnose_disks_readonly.py --sources C,D --targets G
```

O programa não é executado automaticamente. A leitura usa os módulos de
diagnóstico pré-existentes do projeto (PowerShell/Get-Disk/Get-Volume e mapeamento
de extents). **Não executa DiskPart, format, mount, bcdboot, cópia, limpeza
ou qualquer alteração em discos.**

A ausência de conflito lógico não comprova duas mídias fisicamente distintas:
Storage Spaces, discos virtuais, dispositivos USB, RAID e discos dinâmicos
precisam de revisão adicional. A capacidade é apenas pontual. Para qualquer
resultado, permanecem invariavelmente:

- `physical_independence_verified=False`
- `copy_authorized=False`
- `ready_for_format=False`
- `installation_authorized=False`

## Pendências

1. Validar o resumo em diferentes topologias **controladas** de hardware.
2. Aperfeiçoar tratamento de unidades que não possuem letras, mídia removível,
   Storage Spaces, USB desconectado, múltiplos extents e volumes montados por
   caminhos. Nunca interpretar mapeamento parcial como seguro.
3. Integrar a prévia de modo **somente leitura** à experiência do aplicativo,
   revisando permissões e mensagens. Não conectar ao executor de cópia real.
4. Reavaliar TOCTOU da escrita real e independência física antes de planejar
   desbloqueio das funções multidisco de produção.
