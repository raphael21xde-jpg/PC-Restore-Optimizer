# Etapa 35 — preservar evidências de extents incompletos (somente leitura)

## Motivação

O resumo seguro da Etapa 34 retornou o volume **F:** como `incomplete`
e o destino candidato **G:** também como `incomplete`, apesar de haver
possíveis informações parciais em fontes anteriores de diagnóstico do Windows.
O código anterior de `drive_safety_report._drive_extents()` descartava
`disk_numbers` sempre que o status era diferente de
`logical_disk_reported` ou `reported`.

O coletor **já** distinguia estados como:

- `disk_not_listed`: a API de extents forneceu o número lógico, mas o
  número **não apareceu** em `Get-Disk`;
- `virtual_spaces`: volume associado a disco lógico de Storage Spaces,
  sem confirmação dos membros físicos;
- `multi_disk`: volume com extents em mais de um disco lógico;
- `unknown`: consulta insuficiente, resposta inválida ou indisponível.

## O que mudou

`drive_safety_report.py` preserva o(s) **número(s) lógico(s) relatado(s)**
quando o status identificado é `disk_not_listed`, `virtual_spaces` ou
`multi_disk`. Se o coletor disser `reported` mas o número estiver ausente
de `Get-Disk` ou o `BusType` for Storage Spaces, o estado é rebaixado para
a categoria prudente correspondente.

Identificadores duplicados/ambíguos, tipos inválidos e status
`unknown` continuam sem associação confiável (`incomplete` com lista
de discos vazia).

O diálogo apresenta categorias legíveis, e `drive_safety_export.py`
aceita esses novos valores na lista estrita de campos liberados para
**Copiar resumo seguro**. Não exporta serial, GUID ou descrições brutas
de erros. Conflitos lógicos reportados entre origem e destino ainda bloqueiam
o destino mesmo com dados parciais.

**Importante:** mostrar "F: → disco lógico 1 — não listado pelo Get-Disk"
ou "G: → disco lógico 4 — Storage Spaces" NÃO confirma que se trata de
dois dispositivos físicos independentes. Esses números são somente
observações do coletor atual e exigem revisão.

## Executar uma só bateria de testes combinada

A suíte `test_safe_hardware_report.py` agora verifica o filtro seguro e
os cenários simulados equivalentes a uma associação F: `disk_not_listed`
e G: `virtual_spaces`. Os testes não consultam hardware real.

```powershell
py -3 scripts\test_reporter.py --pattern "test_safe_hardware_report.py" --publish
```

Revise a prévia sanitizada antes de publicar no PR #54. Não são usados
GitHub Actions nem operações destrutivas.

## Revisão opcional no hardware existente

Após aprovação da bateria, na aba **Diagnóstico → Conferir origens e
destinos (somente leitura)**, selecione apenas as unidades relevantes e
clique em **Conferir discos**. Copie o resumo seguro e examine
`extent_status`, `logical_disk_numbers`, `status` e
`blocker_count`. O resultado pode continuar **incomplete** se o próprio
Windows não fornecer a associação.

A investigação física de F: e G: **não está encerrada** por esta alteração.
Desligar/desconectar, limpar, formatar, modificar EFI/BCD ou transferir
arquivos para qualquer unidade não faz parte desta etapa. As flags
`physical_independence_verified`, `copy_authorized`,
`ready_for_format` e `installation_authorized` permanecem **False**.
