# PC Restore & Optimizer — instruções para o Claude

App desktop Windows (Python 3.13 + Tkinter): inventário de discos, seleção do que preservar, backup verificado com SHA-256, restauração, **reinstalação guiada** do Windows e otimização. Escopo: **só Windows**, qualquer PC (fraco até topo de linha, qualquer marca). O dono do projeto é o Raphael. Responda em **português**, com linguagem simples: ele está aprendendo programação.

## Antes de começar qualquer tarefa
1. Confira o branch e o commit (`git status -sb`, `git log -1 --oneline`). Branch base: **`origin/main` atualizada** (desde o merge da PR #55, em 20/10/2026). Cada trabalho novo vai num branch próprio (`fix/`, `feature/` ou `auto/`).
2. Leia `docs/ETAPA31_AUDITORIA_E_ROTEIRO_PARA_VERSAO_UTILIZAVEL.md` e `docs/ESTADO-DO-PROJETO-E-PROXIMOS-MARCOS.md` antes de propor mudanças grandes. Não recomece o motor de backup.

## Regras de segurança (inegociáveis)
- **Nunca** formatar, particionar, apagar, alterar EFI/BCD, nem instalar o Windows. A reinstalação é **guiada**: o app prepara e orienta, e quem formata é o instalador oficial, operado pelo Raphael.
- "Não copiar" **nunca** significa apagar.
- Não habilitar o executor multi-disco real nem mudar as travas `copy_authorized`, `physical_independence_verified`, `ready_for_format`, `installation_authorized` e `deletions_authorized` sem pedido explícito.
- Testes só com arquivos sintéticos em `TemporaryDirectory`. Nunca use como alvo de teste dados reais, backups existentes ou o disco do Windows.
- Diagnósticos de disco e hardware: **somente leitura**. Antes de rodar qualquer comando que consulte discos reais, diga o que vai rodar e peça confirmação.
- Otimização: tudo medido antes e depois, reversível, com ponto de restauração. Nunca desligar Defender ou Windows Update, nunca fazer "debloat" agressivo, nunca mexer em BIOS automaticamente (só orientar).
- Não publicar dados pessoais, caminhos com nome de usuário, credenciais ou `preferencias-v05.json`.

## Git e GitHub
- Repositório: `raphael21xde-jpg/PC-Restore-Optimizer` (privado).
- Merge na `main`: só o Raphael **ou** o agente **integrador** (`.claude/agents/integrador.md`), e o integrador só quando as 7 travas dele estiverem verdes (autorizado pelo Raphael em 21/10/2026). Fora isso, **nunca fazer merge** sem aprovação explícita do Raphael. PRs nascem como **rascunho**. Mudanças de governança (`CLAUDE.md`, agentes, `docs/AUTOMACAO.md`, validação) e nas travas de segurança são sempre do Raphael.
- Commits com `[skip ci]` no final da primeira linha. **Não** disparar GitHub Actions sem pedido.
- Mensagens de commit em inglês, no formato `tipo(área): descrição`, como já é feito no histórico.
- Não reescrever histórico publicado (sem `push --force`) e não apagar branches sem confirmação.

## Testes
- Comando: `py -3 -m unittest discover -s tests` (Python 3.13.16). O Modo de Desenvolvedor do Windows está ligado, então os testes de links simbólicos e junções devem rodar.
- Durante o desenvolvimento, rode os testes da área alterada. **Antes de qualquer PR, ou ao fim de cada etapa, rode a suíte completa.** Rodar só um arquivo de teste por vez já deixou passar regressões antes.
- Se mudar uma mensagem de erro ou bloqueio, procure (`grep`) os testes e autotestes que dependem do texto antigo e atualize-os no mesmo commit.
- Não reexecutar à toa testes pesados (2 GiB, 22 mil arquivos, inventário de 1 milhão).

## Relatórios (obrigatório)
Ao terminar uma suíte de testes, uma etapa ou uma investigação, salve um relatório em
`relatorios-claude/AAAAMMDD-HHMM-<assunto>.md` contendo:
- branch e commit testados;
- comando executado;
- resumo (`Ran N tests`, aprovados, falhas, erros, ignorados);
- lista de falhas, erros e testes ignorados, **com o motivo**;
- o que foi alterado e o que ficou pendente.

A pasta `relatorios-claude/` fica **fora do git** (está no `.gitignore`). Esses relatórios são lidos pelo planejamento do projeto no claude.ai.

## Automação (ciclo com agentes)
- O desenvolvimento roda num **ciclo diário** com cinco agentes (`.claude/agents/`): integrador, planejador, desenvolvedor, testador e revisor. O roteiro está em `docs/AUTOMACAO.md`, e a fila de trabalho em `docs/BACKLOG.md`.
- O ciclo entrega PRs em rascunho. O **integrador** faz o merge sozinho quando todas as travas estão verdes. Decisões, testes no hardware real e governança continuam sendo do Raphael.
- A validação no Windows roda **sozinha** no PC do Raphael pelo Agendador de Tarefas do Windows (`scripts\validar_windows_agendado.cmd`, que chama `scripts\validar_windows.py`). Os resultados ficam no branch `validacao-windows`.

## Plano de entrega (resumo)
- **Fase 0:** suíte completa com 0 falhas no Windows → uma PR única (rascunho) com o trabalho fora da `main` → o Raphael revisa e faz o merge.
- **Fase 1:** preparar a formatação do PC do Raphael: diagnóstico atual dos discos (somente leitura) → backup real do C: para um disco que não vai ser formatado → teste de restauração (incluindo o osu! clássico: Songs, Skins, Replays e `osu!.db`) → checklist da instalação guiada → restauração pós-instalação.
- **Fase 2:** executor multi-disco protegido, estratégia de cópia com hardware real (jogos de ~120 GB), central de recuperação ligada ao app, mais launchers de jogos.
- **Fase 3:** otimização universal: perfil do hardware → medição → ajustes em 3 níveis (seguro com 1 clique / avançado com confirmação / BIOS só com orientação) → desfazer tudo.
- **Fase 4:** interface moderna, instalador, manual.
