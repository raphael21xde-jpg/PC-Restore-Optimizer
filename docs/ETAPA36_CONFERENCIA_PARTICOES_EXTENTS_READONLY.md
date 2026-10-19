# Etapa 36 — Conferência cruzada de partições e extents (somente leitura)

## Objetivo

Continuar a identificar associações **lógicas** de volumes do Windows, sobretudo
quando Get-Disk, Get-Partition e IOCTL/extents retornam informações diferentes
para unidades como F: e G:.

A Etapa 35 passou nos 20 testes sintéticos da branch
`feature/extent-evidence-reconciliation-20261019`, mas ainda não existe
comprovação de mídia física independente nem diagnóstico real validado para
os dispositivos do usuário. A Etapa 36 não declara isso resolvido.

## Alterações

- `partition_extent_crosscheck.py` compara, em memória, números de disco
  reportados pelo **Get-Partition** e pelo **mapeamento IOCTL de extents**.
  Não abre discos, não realiza cópias e não chama PowerShell.
- `drive_safety_report.py` usa as duas evidências do **mesmo inventário recém
  coletado**. Resultado `conflict` ou `inconclusive` gera bloqueios. Um
  número de disco de Get-Partition pode aparecer como evidência secundária
  quando IOCTL está indisponível, mas não substitui o extent verificado.
- `drive_safety_ui.py` informa de maneira legível a concordância,
  divergência ou indisponibilidade da conferência no diálogo já existente.
- `drive_safety_export.py` publica apenas os estados predefinidos e os
  números **lógicos** de disco nessa nova seção do resumo seguro.
  Identificadores brutos do Windows, GUIDs, caminhos, modelos e números de
  série continuam fora do resumo.

Estados de comparação:

| Estado | Interpretação |
| --- | --- |
| `logical_match` | Get-Partition e IOCTL apontam os mesmos discos lógicos convencionais; não prova disco físico |
| `limited_match` | Associação lógica coincide, mas extent permanece virtual/não listado |
| `conflict` | Get-Partition e IOCTL apontam conjuntos de discos lógicos diferentes |
| `inconclusive` | Get-Partition contém referência inválida |
| `extent_only` | Apenas o IOCTL reportou associação |
| `partition_only` | Apenas Get-Partition reportou associação |
| `unavailable` | Dados insuficientes de ambas as fontes |

Uma possível colisão de disco relatada por **qualquer uma das fontes**
mantém o destino bloqueado. Não se interpreta ausência de referência como
prova de que uma unidade é independente. As flags
`physical_independence_verified`, `copy_authorized`,
`ready_for_format` e `installation_authorized` continuam `False`.

## Teste dirigido

Executar localmente, sem GitHub Actions:

```powershell
py -3 scripts\test_reporter.py --pattern "test_partition_extent_crosscheck.py" --publish
```

Os testes usam apenas inventários fictícios em memória e interface Tk com
coletor substituído por valores sintéticos. Revise a prévia sanitizada antes
de publicar o resultado no PR #54.

## Conferência de hardware real após aprovação

Abrir o aplicativo `py -3 app.py` e seguir
**Diagnóstico → Conferir origens e destinos (somente leitura)**.
Escolher explicitamente as unidades reais. Solicitar a leitura e, se
necessário, **Copiar resumo seguro** para uma análise do estado
`partition_crosscheck`. Nenhum relatório é enviado automaticamente.

Mesmo sem conflito lógico, **não** realizar formatação, exclusão,
instalação do Windows, mudança na EFI ou backup multidisco real.
A interpretação final precisa ser confirmada em hardware controlado,
considerando Storage Spaces, RAID e discos dinâmicos. Uma letra de volume
não equivale à identidade física de um SSD.
