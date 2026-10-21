# Automação do desenvolvimento (ciclo com agentes)

**Objetivo:** o projeto anda sozinho todo dia, e o Raphael só entra nos
pontos que são dele por regra: revisar e fazer o merge, validar no Windows e
tomar as decisões marcadas no backlog.

## Peças

| Peça | Onde | Papel |
|---|---|---|
| Backlog | `docs/BACKLOG.md` | Lista ordenada de itens com critérios de aceite. É a fonte da verdade. |
| Planejador | `.claude/agents/planejador.md` | Escolhe o próximo item `pronto` e escreve o plano. Não edita código. |
| Desenvolvedor | `.claude/agents/desenvolvedor.md` | Implementa o plano com testes no branch `auto/<ID>-<slug>`. |
| Testador | `.claude/agents/testador.md` | Roda a suíte completa no branch e na `main` e separa regressão de limitação do ambiente. |
| Revisor | `.claude/agents/revisor.md` | Revisão independente contra as regras do `CLAUDE.md`. Pode bloquear. |
| Validação Windows | `scripts/validar_windows.py` | Um comando no PC do Raphael roda a suíte em **todos** os branches pendentes e publica os resultados no branch `validacao-windows`. |
| Ciclo diário | tarefa agendada no claude.ai | Executa o roteiro abaixo uma vez por dia, numa sessão nova na nuvem. |

## Roteiro de cada ciclo

0. **Sincronizar.**
   - `git fetch`.
   - Ler as PRs abertas (`gh api .../pulls?state=open`), os comentários de revisão nelas e os resultados do branch `validacao-windows`.
1. **Consertar antes de criar.** A prioridade é, em ordem:
   1. Uma PR do ciclo com **falha na validação Windows** → o desenvolvedor corrige no mesmo branch.
   2. Uma PR com **comentário do Raphael pedindo mudança** → o desenvolvedor atende no mesmo branch.

   Novos commits entram na mesma PR, sempre sem `--force`.
2. **Limite de fila.** Se já houver **3 PRs do ciclo** (título com ID do backlog) esperando o Raphael, não comece item novo. Faça só o passo 1, ou nada, e avise no resumo.
3. **Planejar.** O planejador escolhe o item e escreve o plano.
4. **Desenvolver.** O desenvolvedor trabalha no branch `auto/<ID>-<slug>` a partir da `origin/main`.
5. **Testar.** O testador roda a suíte completa no branch e na `main`. Se houver regressão, o desenvolvedor corrige (no máximo 2 rodadas). Se ainda falhar, a PR é aberta marcada como `[BLOQUEADA]`, com o diagnóstico.
6. **Revisar.** O revisor faz a revisão independente. `BLOQUEAR` → o desenvolvedor corrige (no máximo 2 rodadas) e o revisor revê.
7. **Entregar.**
   - Abrir uma PR em **rascunho** pela API REST (`gh api repos/.../pulls -f draft=true`), com o título `<ID>: <título>`.
   - O corpo da PR leva:
     - o plano;
     - os critérios de aceite, cada um com o teste que o cobre;
     - o veredito do testador e do revisor;
     - o aviso "falta validar no Windows".
   - Commits com `[skip ci]`.
8. **Resumo.** Uma mensagem curta: o que foi feito, o link da PR e o que espera o Raphael.

## O que o ciclo NUNCA faz
- Merge, `push --force`, apagar branches, disparar GitHub Actions.
- Mexer nas travas de segurança ou pegar item `bloqueado`.
- Tocar no PC real do Raphael, em discos reais ou em dados reais.
- Mudar o `CLAUDE.md` ou o status de um item de outro jeito que não seja a PR do próprio item.

## O que é do Raphael (fila de espera)
1. **Validar no Windows** (de preferência 1 vez por dia ou quando o ciclo avisar), num Terminal normal, na pasta do repositório:
   ```
   git switch main; git pull; py -3 scripts\validar_windows.py
   ```
   O script roda a suíte em todos os branches pendentes, em cópias temporárias, sem mexer no branch atual, e publica os resultados.
2. **Revisar e fazer o merge** das PRs que estiverem verdes no Windows.
3. **Decisões e testes no hardware real** marcados no backlog (`Raphael: ...`).

## Limites conhecidos
- A nuvem roda Linux sem Tk: os testes de interface só rodam na validação Windows.
- Recursos que dependem do Windows (ACL, registro, winget, WMI) são testados com simulação na nuvem. A prova real é a validação Windows e, quando o backlog pedir, o teste do Raphael no PC.
