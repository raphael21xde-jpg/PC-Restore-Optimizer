# Etapa 43 — Reaproveitar tamanho da prévia dos arquivos escolhidos

## O que existe no aplicativo

O aplicativo já gera uma prévia de seleção usando
`backup_core.build_plan()`. A estrutura `Plan` contém, entre outros
campos, `files`, `selected`, `warnings` e `total`.
O `Plan.total` é a soma dos tamanhos dos arquivos enumerados durante
essa prévia. **Não** equivale, por si só, ao tamanho total de todos os
jogos, saves, navegadores, cofres ou discos do usuário.

No fluxo legado do `app.py` verificado nesta etapa, a prévia de
reinstalação filtra a seleção pelo disco do Windows em uso, normalmente
C:. Portanto, usar esse plano como se ele contivesse automaticamente
C:, D:, F: e G: seria incorreto e perigoso.

## Implementação

- `preview_plan_capacity.py` interpreta **somente os metadados já
  presentes em memória**, sem executar inventário, stat, scandir,
  PowerShell, backup ou escrita.
- Aceita uma prévia apenas se: há arquivos selecionados, nenhum alerta
  de leitura, tamanho `total` coerente com a soma, nenhum arquivo
  duplicado, caminhos absolutos que pertencem aos itens expressamente
  selecionados e todas as origens informadas têm arquivos cobertos.
  Qualquer lacuna ou origem extra causa recusa **sem assumir zero bytes**.
- Converte os bytes para GiB, **sempre arredondando para cima** à
  precisão de 0,001 GiB aceita pelo campo manual.
- O botão **Usar tamanho da prévia** aparece no diálogo
  **Diagnóstico → Conferir origens e destinos (somente leitura)**.
  O usuário deve indicar antes suas origens e clicar explicitamente no
  botão; o diagnóstico **não dispara automaticamente**. Isso somente
  preenche a estimativa manual.
- O botão recusa uma prévia só de C: quando são escolhidas também D: ou
  F:, em vez de inventar o tamanho das outras unidades. Para essas
  situações, ainda é possível informar um tamanho **manual** ou gerar,
  futuramente, uma prévia multidisco completa e validada.
- O preenchimento invalida consultas anteriores. Depois o operador
  deve clicar **Conferir discos (SOMENTE LEITURA)** para comparar
  metadados de capacidade, sem copiar qualquer arquivo.

## Teste dirigido

```powershell
py -3 scripts\test_reporter.py --pattern "test_preview_plan_capacity_readonly.py" --publish
```

Os testes sintetizam `Plan` e `FileTask` em memória, inclusive
múltiplas letras fictícias, itens ignorados, alertas, arquivos em
unidade errada, caminhos fora da seleção, somas divergentes, tamanhos
inválidos e comportamento de interface Tk. O inspecionador do diálogo
é substituído por um inventário fictício. Revisar a prévia sanitizada
antes de publicar no PR #54. Não executa Github Actions nem cópia,
exclusão ou formatação.

## Limitações e segurança

Isso é uma **ponte limitada ao plano já revisado**, não implementação
final do tamanho multidisco de backup. Dados externos ao `Plan.files`
(alguns saves, cofres de navegadores, dependências de jogos, etc.) não
são incluídos e exigem integração posterior com o inventário e suas
escolhas explícitas.

O destino não é validado como fisicamente independente por essa etapa.
Mesmo que `capacity_status=reported_sufficient`, as flags obrigatórias
permanecem `copy_authorized=False`,
`physical_independence_verified=False`, `ready_for_format=False`
e `installation_authorized=False`.

Próxima evolução: ligar a seleção multidisco e os itens relacionados
(jogos, saves, navegadores) a um manifesto **de planejamento** preciso,
verificável e sem ações de escrita, antes de qualquer trabalho em
um executor real de backup.
