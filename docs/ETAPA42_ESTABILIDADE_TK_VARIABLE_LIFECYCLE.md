# Etapa 42 — finalização segura do Tkinter após diagnóstico (sem escrita)

## Sinal observado no teste real da etapa 41

O relatório local para a branch `feature/backup-capacity-plan-readonly-20261019`
(commit `14828b2`) indicou **14 testes aprovados**, mas exibiu
mensagens intermitentes do Python 3.13/Tkinter:

- `RuntimeError: main thread is not in main loop` dentro de
  `tkinter.Variable.__del__`;
- `RuntimeWarning: the Tcl interpreter is leaked because it was
  deallocated in a thread other than the one it was created in`
  (referência ao problema CPython gh-83274).

O aviso ocorreu durante o teste de interface e não indica, por si só,
problemas nos discos ou execução de cópias. Não é possível concluir pela
saída isolada se a causa única foi o teste ou uma referência Tcl remanescente
no ciclo de vida do diálogo.

## Mitigação aplicada

1. No `drive_safety_ui.py`, são guardados os nomes de callback
   registrados com `StringVar.trace_add('write', ...)`.
   Eles são removidos explicitamente com `trace_remove` em
   `<Destroy>` da janela **quando a thread principal processa a
   destruição**. A ação só afeta callbacks desta janela.
2. Nos testes de capacidade, o interpretador Tcl de teste é destruído
   explicitamente e `gc.collect()` é executado pela **thread principal**
   após a destruição da janela. Isso reduz a chance de desalocação
   tardia em uma thread de trabalho.
3. O novo caso de regressão abre e fecha o diálogo cinco vezes e
   verifica as 15 remoções de callback sem consultar nenhum disco.

As tarefas de inventário continuam em worker com fila de resultados;
nenhum widget Tk é manipulado pela thread de trabalho.
A mitigação precisa ser validada novamente em ambiente Windows,
pois warnings intermitentes podem ter causas adicionais.

## Validação

Na pasta de checkout da nova branch:

```powershell
py -3 scripts\test_reporter.py --pattern "test_backup_capacity_plan_readonly.py" --publish
```

A bateria atual passa de 14 para **15 testes**. Confirme tanto `Ran 15
tests` e `OK` quanto **ausência dos avisos** `RuntimeError` de
`Variable.__del__` e `Tcl interpreter is leaked`.
Não suprimir avisos. Revise a prévia sanitizada antes de publicar o
comentário no PR #54.

As fontes de dados são fictícias e não há operações reais de backup,
reinstalação do Windows, exclusão, ajuste EFI ou formatação.
`physical_independence_verified=False`, `copy_authorized=False`,
`ready_for_format=False` e `installation_authorized=False`
continuam inalterados.
