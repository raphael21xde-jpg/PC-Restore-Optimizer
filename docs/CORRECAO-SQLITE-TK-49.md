# Correção #49 — Windows Python 3.13 / SQLite após inventário

O teste de interface do seletor de unidades podia falhar com `WinError 32`
em `TemporaryDirectory.cleanup`. A causa era uma corrida: o SQLite já
registrava `terminado_com_lacunas`, mas a janela Tk ainda não havia
processado o evento `complete` e aberto/fechado o índice de revisão.
Assim, a rotina do teste fechava a janela quando a varredura ainda
estava ativa, deixando o arquivo de teste aberto.

O teste agora aguarda **o término observado pela interface** (pesquisa
habilitada e botão **Parar varredura** desabilitado) antes de abrir seu
próprio SQLite, e fecha a janela por seu handler habitual antes de sair da
pasta temporária. Em caso de teste interrompido, solicita cancelamento e
processa eventos Tk enquanto o worker encerra.

As variáveis Tk recebem mestre explícito (`master=win` ou
`master=popup`) para limitar referências cruzadas de intérpretes
Tcl, inclusive no Python 3.13.

## Teste local

Após atualizar o repositório, feche todas as janelas do aplicativo e
rode no PowerShell:

```powershell
py -3.13 -m unittest discover -s tests -p "test_file_index_ui.py" -v
```

Esperado: **3 testes OK** e nenhum `WinError 32`. Se aparecer erro,
envie todo o relatório; **não exclua nem force o desbloqueio** de seu
índice real ou dos arquivos do usuário.

Esta correção não altera o motor de backup, dados existentes,
discos nem autorização de reinstalação.
