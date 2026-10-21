# Automação do desenvolvimento — como a equipe de agentes trabalha

**Regra de ouro:** os agentes constroem o app sozinhos, todos os dias. O
Raphael **não aprova nada no dia a dia**. Ele só é chamado, por notificação no
celular e com o passo a passo, em quatro casos:
1. **Validação de um marco:** um pedaço do app ficou pronto pra ele usar e dizer se está certo.
2. **Algo que só o PC dele faz:** por exemplo, a validação no Windows parou há mais de 24 h.
3. **Mexer nas travas de segurança:** formatar, apagar, executor multi-disco. Isso só acontece se ele pedir.
4. **Um erro que os agentes não conseguiram resolver** em 2 ciclos seguidos.

(Regras aprovadas pelo Raphael em 21/10/2026.)

## A equipe

| Agente | Papel | Arquivo |
|---|---|---|
| **Coordenador** | É o próprio ciclo agendado. Segue este roteiro, chama os outros agentes, escreve o resumo e chama o Raphael quando precisa | (prompt da tarefa agendada) |
| **Planejador** | Gerente de produto: escolhe o próximo item do **marco atual** e divide em fatias que entregam algo usável | `.claude/agents/planejador.md` |
| **Desenvolvedor** | Programa a fatia com testes, no branch `auto/<ID>-<slug>` | `.claude/agents/desenvolvedor.md` |
| **Testador** | Roda a suíte completa no branch e na `main`. **Monitora** os resultados do Windows da `main` e transforma falhas em itens `FIX-...` | `.claude/agents/testador.md` |
| **Revisor** | Revisão independente contra as regras de segurança. Pode bloquear | `.claude/agents/revisor.md` |
| **Integrador** | Atualiza a PR com a `main`, confere as travas e faz o **merge** | `.claude/agents/integrador.md` |

**Fora do Claude:** o **Agendador de Tarefas do Windows**, no PC do Raphael, testa a `main` no Windows de verdade a cada 3 h e publica os resultados no branch `validacao-windows`. Ele roda sozinho, e o Raphael não precisa fazer nada.

## Roteiro de cada ciclo (02:48 e 14:48, horário de Brasília)

1. **Olhar a saúde do projeto (testador).**
   - Ler o resultado mais recente da `main` no branch `validacao-windows`.
   - Se o Windows falhou: criar ou retomar um item `FIX-<data>-<assunto>`, que vira **prioridade máxima**.
   - Se não chegou resultado novo há mais de 24 h: chamar o Raphael (caso 2).
2. **Terminar o que está aberto (integrador + desenvolvedor).** Para cada PR aberta dos agentes:
   - **pronta** (testador sem regressão + revisor aprovou, no commit atual) → o integrador faz o merge;
   - **atrás da `main` ou com conflito** → o integrador faz `git merge origin/main` no branch (nunca rebase nem `--force`), roda a suíte de novo e faz o merge;
   - **reprovada** → o desenvolvedor corrige, depois testador e revisor de novo.
3. **Avançar (planejador → desenvolvedor → testador → revisor → integrador).**
   - Ordem: os itens `FIX-...` primeiro, depois o primeiro `pronto` do marco atual.
   - **Uma fatia por vez, até o merge.** Se sobrar tempo no ciclo, pegar a próxima.
   - Uma escolha de design é resolvida com a opção **mais segura**, registrada na PR e no resumo, sem parar.
4. **Marco pronto?** Se todos os itens do marco estiverem `concluído`, abrir a issue **"Validar M<n>"**, com a etiqueta `precisa-do-raphael` e o passo a passo do backlog, e chamar o Raphael (caso 1). Enquanto ele não responde, os agentes seguem para o próximo marco.
5. **Resumo (vai para o celular).** A primeira linha é sempre uma destas:
   - `🟢 Nada pra você.` + o que foi feito (merges e PRs), em até 5 linhas.
   - `📱 PRECISA DE VOCÊ: <assunto>` + o link da issue + o passo a passo numerado (no máximo 6 passos, cada um com o comando exato ou o clique).

## Travas do integrador (todas precisam passar)
1. A PR é dos agentes (branch `auto/` ou `fix/`).
2. Sem a etiqueta `nao-mergear`. O Raphael pode vetar qualquer coisa a qualquer hora com ela.
3. O diff não toca em linhas com `copy_authorized`, `physical_independence_verified`, `ready_for_format`, `installation_authorized` ou `deletions_authorized`, nem em `CLAUDE.md`, `.claude/agents/`, `docs/AUTOMACAO.md` ou `scripts/validar_windows*`.
4. O testador rodou a suíte completa **no commit atual** e não achou regressão.
5. O revisor deu APROVAR ou APROVAR COM RESSALVAS **no commit atual**.
6. A PR está atualizada com a `main` e sem conflito.

O merge é feito preso ao `sha` testado. O Windows confere **depois**, na `main`. Se quebrar, o próximo ciclo conserta primeiro (passo 1).

## O que os agentes NUNCA fazem
- `push --force`, rebase de branch publicado, apagar branches, disparar GitHub Actions.
- Mexer nas travas de segurança ou pegar um item `bloqueado` por elas.
- Tocar no PC do Raphael, em discos, backups ou dados reais. Testes só com `TemporaryDirectory`.
- Mudar as regras (`CLAUDE.md`, agentes, este roteiro, a validação). Isso só acontece numa conversa com o Raphael.

## Validação no Windows (PC do Raphael, já configurada)
- Tarefa do Agendador **"PCRO validacao Windows"**, a cada 3 h, como usuário normal. Ela roda `scripts\validar_windows_agendado.cmd`, que atualiza a `main` e roda `scripts\validar_windows.py`.
- O log fica em `%LOCALAPPDATA%\pcro-validacao.log`.
- Pausar: `schtasks /Change /TN "PCRO validacao Windows" /DISABLE`. Voltar: `/ENABLE`.

## Limites conhecidos
- A tarefa agendada do claude.ai não tem terminal no PC. Por isso o Windows é testado pelo Agendador do próprio Windows, e só com o PC ligado.
- A nuvem roda Linux sem Tk: os testes de interface rodam só na validação Windows, depois do merge.
