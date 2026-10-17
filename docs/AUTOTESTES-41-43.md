# Bateria #41–#43 — inventário, vínculos e recuperação segura

O teste #39 executado em Windows examinou quatro unidades, atingiu o limite
de 3.000 entradas em C: e G: e reportou 19 erros de leitura no total. Isso é
cobertura parcial, não uma prova de falha dos arquivos.

## #41 — Auditoria ampliada de metadados

- Somente após o clique do usuário, observa unidades locais enumeradas
  dinamicamente (não depende de C/D/F/G como letras obrigatórias).
- Observa **até 12.000 entradas por unidade**, profundidade máxima de cinco
  níveis, sem seguir atalhos, junções e links.
- Classifica erros como acesso negado, desaparecimento durante a enumeração e
  outros erros de sistema; marca explicitamente **cobertura parcial**.
- Não lê conteúdo dos arquivos, não avalia ACL NTFS em detalhe, não cria
  backups e não escreve nos volumes observados.
- O relatório pode incluir a letra/unidade raiz e contagens, mas não lista
  conteúdo de diretórios pessoais.

## #42 — Relações entre unidades sem falsas garantias

- Exercita `game_links.infer_links` em exemplos **100% fictícios**.
- Compara instalação em D:/F: e dados em C:/G:, inclusive um aplicativo cuja
  classificação não é jogo.
- Distingue associação aprovada manualmente de caminho ainda a revisar.
- Nunca conclui que backup foi feito apenas porque existe uma associação.
- Não afirma descobrir os vínculos reais do computador.

## #43 — Restauração após falha de gravação

- Gera três arquivos fictícios e cria backup SHA-256 isolado.
- Injeta erro na escrita da restauração, exige diário marcado como parcial
  e comprova limpeza de fragmentos incompletos.
- Retoma no **mesmo destino temporário**, verifica os hashes de todos os
  arquivos e preserva a fonte.
- Não testa falha elétrica, ACL real ou recuperação no C: original.

## Usar pelo PowerShell após integração à main

Dentro da cópia do projeto que já está no computador:

```powershell
Set-Location "$HOME\PCRO-testes-38-40"
git pull --ff-only origin main
py -3 -m unittest discover -s tests -p "test_autotestes_41_43.py" -v
.\INICIAR.bat
```

A janela de preservação possui a aba **Novos #41–43** e botão fixo
**Exportar relatório**. Gere um JSON para cada teste.

Todos os relatórios continuam declarando `ready_for_format=false` e
`installation_authorized=false`. Aprovação de ensaios não significa
formatação segura nem preservação total do computador.
