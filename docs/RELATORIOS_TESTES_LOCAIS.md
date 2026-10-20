# Relatorios locais de testes no GitHub (sem Actions)

Esta ferramenta executa `unittest` no **proprio PC**, salva o log integral
em `.pcro-test-reports/` e pode publicar os resultados no PR #54 como
comentario. Nao envia commit, nao faz `git push`, nao cria workflow e
nao consome minutos de GitHub Actions.

## Preparacao unica no Windows

No PowerShell, dentro da pasta do projeto:

```powershell
gh --version
gh auth status
```

Se `gh` ainda nao existir:

```powershell
winget install --id GitHub.cli --source winget
```

Abra um novo PowerShell depois da instalacao e autentique, se necessario:

```powershell
gh auth login --web
gh auth status
```

**Nunca cole codigos de autenticacao, senhas ou tokens no chat.**

## Execucao

Primeiro, para validar somente a ferramenta, sem publicar:

```powershell
py -3 scripts\test_reporter.py --pattern "test_local_test_reporter.py"
```

Para executar **e publicar automaticamente** um relatorio de um unico modulo:

```powershell
py -3 scripts\test_reporter.py --pattern "test_local_test_reporter.py" --publish
```

Para publicar os testes multidisco ao terminar:

```powershell
py -3 scripts\test_reporter.py --pattern "test_multi_source*.py" --publish
```

Para executar a suite completa (pode demorar):

```powershell
py -3 scripts\test_reporter.py --pattern "test_*.py" --publish
```

Opcionalmente, usando a interface PowerShell:

```powershell
.\scripts\run_tests_report.ps1 -Suite multidisco -Publicar
.\scripts\run_tests_report.ps1 -Suite completo -Publicar
```

Caso a politica local bloqueie scripts PowerShell, use diretamente os
comandos `py -3` acima, sem alterar a politica da maquina.

## Privacidade e diagnostico

- O **log integral** permanece somente no PC.
- O comentario no GitHub contem o resumo e ate 38 mil caracteres finais
  da saida detalhada, com sanitizacao preventiva de usuarios, e-mails e
  formatos conhecidos de token; essa sanitizacao **nao e garantia**
  contra dados sensiveis inesperados.
- Sem `--publish` ou `-Publicar`, nenhum log sera enviado ao GitHub.
- A previsualizacao que seria publicada fica no arquivo
  `.pcro-test-reports/*-previsualizacao.md`. Confira se seus testes
  imprimem informacoes privadas antes de habilitar a publicacao.
- Em repositorios publicos, **comentarios em PR sao publicos**.
- Mesmo que os testes falhem, a ferramenta tenta publicar o resumo e
  os erros quando a publicacao foi explicitamente solicitada.
- O codigo de saida continua diferente de zero caso os testes falhem,
  nao sejam encontrados ou a publicacao falhe.
- O PR #54 e apenas o destino configurado por padrao. Em trabalhos
  futuros, defina `--pr 55` ou `-Pr 55`, por exemplo, conforme o caso.

Consultar os resultados: https://github.com/raphael21xde-jpg/PC-Restore-Optimizer/pull/54

A publicacao dos comentarios **nao acorda** esta conversa automaticamente:
quando voltar ao chat, basta pedir para ler os ultimos comentarios do PR.
