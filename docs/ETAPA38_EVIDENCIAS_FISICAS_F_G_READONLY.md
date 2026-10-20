# Etapa 38 — evidência auxiliar real de F: e G: sem identificadores privados

## Evidência já confirmada no PC de teste

O usuário executou a Etapa 37 sobre o Windows real, com origens C:, D:, F:
e destino *apenas candidato para diagnóstico* G:. O resumo retornou:

| Unidade | Extents | Get-Partition | Observação |
| --- | --- | --- | --- |
| C: | disco lógico 2 | disco lógico 2 | inicialização reportada no disco lógico 2 |
| D: | disco lógico 3 | disco lógico 3 | associação lógica coincidente |
| F: | disco lógico 1, `disk_not_listed` | nenhuma correspondência | disco 1 ausente do Get-Disk |
| G: | disco lógico 4, `virtual_spaces` | disco lógico 4 | associação limitada em Storage Spaces |

O usuário informou que **G: é um SSD interno ligado à placa-mãe**. Isso não
contradiz a apresentação pelo Windows de um disco lógico Storage Spaces.
A localização e identidade física dos membros do pool **ainda não foram
verificadas**. O destino G: permaneceu `blocked` e a origem F: não teve
o dispositivo físico identificado com segurança.

## O que esta etapa muda

O coletor `diagnostics.disk_inventory()` já inclui fontes secundárias,
sem necessidade de outro comando destrutivo:

- `spaces_membership`: associação entre `Get-VirtualDisk`,
  `Get-Disk` e `Get-PhysicalDisk`. Pode mostrar número de membros
  físicos relatados, associação incompleta ou ambígua e resiliência
  (Simple, Mirror, Parity). Não confirma independência física nem backup.
- `physical_evidence`: compara `Get-Disk` com `Win32_DiskDrive`;
  para um disco faltante nos extents como o F:, pode indicar presença na WMI
  sem copiar modelo, nome, serial ou dispositivo.
- `partition_evidence`: indica se `Win32_DiskPartition` encontrou
  partições para um número de disco que não aparece no Get-Disk.

A função `drive_hardware_evidence.summarize_hardware_evidence` resume
essas três fontes **em memória**, preservando apenas estados enumerados e
contagens limitadas. Nenhum dado físico bruto é copiado para o relatório
seguro. `drive_safety_report.py` inclui essas evidências no diagnóstico,
`drive_safety_export.py` faz uma segunda validação de privacidade por
lista de permissão e `drive_safety_ui.py` apresenta status com nomes claros.

A correção também usa fundo escuro na área de detalhes do diálogo,
evitando o contraste branco observado na captura de tela anterior.

## Testar (dados fictícios, sem varredura física)

```powershell
py -3 scripts\test_reporter.py --pattern "test_physical_evidence_readonly.py" --publish
```

Os testes simulam o comportamento de F: e G: com WMI e Storage Spaces,
incluindo falhas, ambiguidade, anonimização e interface. Revise a prévia
sanitizada antes de publicar no PR #54. Nenhum teste acessa discos
físicos, altera Windows ou usa GitHub Actions.

## Revisar no próprio Windows após os testes

Abrir `py -3 app.py`, escolher **Diagnóstico → Conferir origens e destinos
(somente leitura)** e informar, se forem as unidades ainda relevantes,
`C:,D:,F:` como origens e `G:` como destino candidato *apenas para
inspeção*. Clicar em **Conferir discos (SOMENTE LEITURA)** e então
**Copiar resumo seguro**.

Os novos campos `hardware_evidence` incluem:
- Para F: `wmi_diskdrive_status`, `wmi_partition_status` e
  `wmi_partition_count`, quando reportados.
- Para G: `spaces_membership_status`, `spaces_members_count` e
  `spaces_resiliency`, quando reportados.

Contagens e vínculos relatados **não** provam que um disco físico é
independente de outro. Não inferir que o SSD interno G: é seguro para
backup com base no número 4, na presença de membros reportados nem na
resiliência de Storage Spaces. Se as consultas retornarem desconhecido,
isso é um resultado válido, não um defeito da unidade.

`physical_independence_verified=False`,
`copy_authorized=False`, `ready_for_format=False`,
`installation_authorized=False` permanecem obrigatoriamente assim.
Nenhum disco deve ser formatado, apagado, desmontado ou usado como
destino real de backup por causa deste relatório.
