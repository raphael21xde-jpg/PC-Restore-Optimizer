# Regras do revisor (erro vira regra)

Este arquivo é lido **só pelo revisor** (`.claude/agents/revisor.md`). O desenvolvedor não recebe
estas regras: ele segue o plano e o `CLAUDE.md`. O revisor confere cada regra no diff e **aponta**
o que não bate (arquivo:linha + número da regra). Quem corrige é o desenvolvedor.

**Como uma regra nasce:** toda falha que chegou à `main` ou à validação Windows, ou que a revisão
pegou e virou correção, ganha uma linha aqui, na mesma PR da correção.
Formato: `R-<nº> | regra curta e verificável | origem (PR, commit ou item) | data`.

**Poda:** a cada 10 regras novas, o coordenador cria um pedido do tipo `regras` no PCRO Monitor para o
Raphael revisar a lista (juntar repetidas, tirar as que não valem mais). Regras novas desde a última
poda: 0 (última poda: 31/10/2026, pedido `regras-20261031-poda-r14-r23`, issue #125; a R-24 nasceu
da separação da R-21 e não conta). A próxima poda é pedida quando chegarem 10 regras novas a partir da R-25.
Regras juntadas mantêm o número antigo na tabela, só como remissão, para não quebrar referências.

| Nº | Regra | Origem | Data |
|---|---|---|---|
| R-01 | Caminho mostrado ou gravado mantém a grafia original; `normcase`/minúsculas só para **comparar** (função de chave separada). | Restauração real de 20/10 (`5ff2128`, PR #56) e 4 FAIL no Windows da `main` (FIX-20261022-launchers-caminho-minusculo, PR #78) | 2026-10-20 |
| R-02 | Pasta que o usuário vai usar (restauração, conferência) não é criada com `tempfile.mkdtemp`: no Windows/Python 3.13 ela fica só para o dono e some para o usuário quando o app roda como administrador. | `5ff2128`, PR #56 | 2026-10-20 |
| R-03 | Mudou um texto de erro ou de bloqueio: o mesmo commit atualiza os testes e autotestes que comparam o texto antigo (`grep` no texto antigo deve dar zero). | 3 falhas na suíte completa por texto antigo (`51086f7`, PR #55) | 2026-10-19 |
| R-04 | O veredito do testador vem da **suíte completa** no commit atual, não de um arquivo de teste só. | PR #55 (`fix/full-suite-message-drift`): rodar por arquivo deixou passar as falhas da R-03 | 2026-10-20 |
| R-05 | Antes de `os.replace` sobre um destino do usuário, o destino é conferido de novo; se apareceu ou mudou durante a cópia, ele é preservado e o item falha. Só o `.pcro-partial` do próprio app pode ser descartado. | Revisão do P2-01 (`23a1d75`, PR #58) | 2026-10-21 |
| R-06 | Teste que inicia thread ou worker espera o fim **observado** (thread terminou, tela mostra o fim) antes de fechar a janela ou limpar o `TemporaryDirectory`. | `WinError 32` no Windows: correção #49 (`8438797`) e `3653b3f` | 2026-10-17 |
| R-07 | Texto de erro mostrado ou salvo leva no máximo o nome do arquivo/pasta e o tipo do erro; nunca o caminho completo nem a mensagem original do sistema (podem ter o nome de usuário). | FIX-P2-11-01 (PR #74) e revisão do P2-08 (`a29ef57`, PR #77) | 2026-10-21 |
| R-08 | A identidade de um backup (chaves de progresso, cópias) não depende da letra da unidade. | FIX-P2-11-02 (PR #76) | 2026-10-21 |
| R-09 | Arquivo que duas janelas ou instâncias do app podem gravar (diário, progresso, estado): `.parcial` com nome único criado com `O_CREAT\|O_EXCL`, `fsync` e `os.replace`; nunca `.parcial` de nome fixo, nunca gravar por cima de link. Antes de cada gravação, o arquivo é relido e conferido, ou protegido por trava exclusiva: gravar a lista da memória por cima nunca pode apagar entrada gravada por outra instância. | FIX-P2-11-02 (`833c145`, PR #76); juntada com a R-22 (revisão da PR #115, issue #116, FIX-P3-03-02) na poda de 31/10/2026 | 2026-10-21 |
| R-10 | Operação que pode esperar (disco, retentativas, `save_progress`) não roda na thread do Tk: vai para `Job`/thread e volta por `WindowTimers.after`. | FIX-P2-11-03 (PR #79) | 2026-10-22 |
| R-11 | Agendamento numa janela Tk usa `WindowTimers` (cancelado ao fechar), nunca `window.after` solto. Teste que cria raiz Tk usa `track_tk_root`/`close_tk_root` de `tests/tk_helpers.py`. | `invalid command name` e `Tcl interpreter is leaked` no log da `main` b0f669f (P2-07, PRs #80 e #81) | 2026-10-22 |
| R-12 | `st_file_attributes` pode vir `None` no Windows: ler sempre como `(getattr(info, 'st_file_attributes', 0) or 0)`. | Revisão do P2-08 (`a29ef57`, PR #77) | 2026-10-21 |
| R-13 | A recusa de rodar como administrador é a **primeira** coisa de cada motor e tela de restauração: antes de perguntar pasta, ler manifesto ou criar qualquer coisa. | Revisão do P2-02 (`f2cb23d`, PRs #59 e P2-02 fatia 2) | 2026-10-21 |
| R-14 | Texto mostrado ao usuário sai da mesma decisão da trava: se a resposta ficou negativa, o texto nunca afirma que os discos são separados (nem o título "Discos separados"), nem diz "liberado" ou "pode copiar"; negações como "nada foi considerado separado" são permitidas. | Revisão da PR #95 (P2-09 fatia 2b) e revisão da PR #97 | 2026-10-24 |
| R-15 | Texto do backlog ou docstring que descreve uma trava ou um token diz exatamente quando ele é gasto ou recusado; se há caminho de recusa que não gasta o token, isso é dito (ou o código passa a gastar). | Revisão da PR P2-09 fatia 3a (77387dd) | 2026-10-24 |
| R-16 | Linha de status no `docs/BACKLOG.md` não cita o nome de uma trava de segurança; o nome fica numa linha separada, para o status poder ser atualizado sem tocar a trava 3 do integrador. | Revisão do FIX-P2-09-04 (`d2d9273`, PR #100) | 2026-10-24 |
| R-17 | Função nova que reaproveita uma trava ou recusa já testada em outra função (ex.: modo real x área de teste) ganha os mesmos testes de recusa e de token (chamada malformada, caminho inexistente, link na origem, revalidação, retomada); "a lógica é compartilhada" não substitui o teste. | Revisão da P2-09 fatia 3b-1 (f8f2ed9) | 2026-10-24 |
| R-18 | Cada ação de tela listada nos critérios do backlog (botão, cancelar, trocar escolhas) tem teste de janela próprio; teste do controlador não substitui o da tela. | Revisão da P2-09 fatia 3b-2 (PR #106) | 2026-10-24 |
| R-19 | Texto de cancelamento ou de erro nunca afirma "Nada foi gravado" se o executor ou o adaptador pode ter sido chamado; essa frase só aparece quando o fluxo garante que nada foi chamado. Senão, a mensagem diz o que pode ter mudado: na cópia, "trate a cópia como não verificada"; se a gravação do diário falha depois que o adaptador já mexeu no sistema, diz o que mudou no sistema. | Revisão da PR #106 (P2-09 fatia 3b-2), FIX-P2-09-07; juntada com a R-23 (revisão da PR #124, FIX-P3-03-02) na poda de 31/10/2026 | 2026-10-24 |
| R-20 | Toda tela ou fluxo que grava arquivos do usuário (cópia, restauração, colocação) recusa rodar como administrador antes de ler discos, autorizar ou gravar, usando `elevation_guard.is_process_elevated`; a tela também mostra o aviso e desliga o botão (defesa dupla). | Validação do M2 (pedido `marco-20261024-p2-09-copia-real`), FIX-P2-09-08 | 2026-10-25 |
| R-21 | Teste que confere "nenhum trabalho foi iniciado" compara a identidade do Job antes e depois da ação (`assertIs`), nunca exige que ele seja vazio (`_power_job is None`), porque leituras anteriores também criam Job. | Validação Windows da main 866ce6f (FIX-20261030-teste-sem-admin); separada da R-24 na poda de 31/10/2026 | 2026-10-30 |
| R-22 | Juntada à **R-09** na poda de 31/10/2026 (confira a R-09). | Revisão da PR #115 (issue #116), FIX-P3-03-02 | 2026-10-31 |
| R-23 | Juntada à **R-19** na poda de 31/10/2026 (confira a R-19). | Revisão da PR #124 (FIX-P3-03-02) | 2026-10-31 |
| R-24 | Regra de processo: PR que mexe em tela (Tk) tem os testes de janela rodados na nuvem com o Python do uv + `xvfb-run` antes da revisão; o testador diz no veredito se eles rodaram ou foram ignorados. | Separada da R-21 (FIX-20261030-teste-sem-admin) na poda de 31/10/2026 | 2026-10-31 |
