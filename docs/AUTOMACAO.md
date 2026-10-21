# Automação do desenvolvimento (ciclo com agentes)

**Objetivo:** o projeto anda sozinho todo dia. O Raphael só entra nas
decisões marcadas no backlog, nos testes no hardware real e nas mudanças de
governança. O merge das PRs verdes é feito pelo agente **integrador**
(autorizado pelo Raphael em 21/10/2026).

## Peças

| Peça | Onde | Papel |
|---|---|---|
| Backlog | `docs/BACKLOG.md` | Lista ordenada de itens com critérios de aceite. É a fonte da verdade. |
| Integrador | `.claude/agents/integrador.md` | Faz o merge das PRs que passaram nas 7 travas (Windows, testador, revisor, sem veto, sem decisão pendente, sem governança, sem conflito). |
| Planejador | `.claude/agents/planejador.md` | Escolhe o próximo item `pronto` e escreve o plano. Não edita código. |
| Desenvolvedor | `.claude/agents/desenvolvedor.md` | Implementa o plano com testes no branch `auto/<ID>-<slug>`. |
| Testador | `.claude/agents/testador.md` | Roda a suíte completa no branch e na `main` e separa regressão de limitação do ambiente. |
| Revisor | `.claude/agents/revisor.md` | Revisão independente contra as regras do `CLAUDE.md`. Pode bloquear. |
| Validação Windows | `scripts/validar_windows.py` + `scripts/validar_windows_agendado.cmd` | O **Agendador de Tarefas do Windows**, no PC do Raphael, roda a suíte a cada 3 horas em **todos** os branches pendentes e publica os resultados no branch `validacao-windows`. O log fica em `%LOCALAPPDATA%\pcro-validacao.log`. |
| Ciclo diário | tarefa agendada no claude.ai | Executa o roteiro abaixo uma vez por dia, numa sessão nova na nuvem. |

## Roteiro de cada ciclo

0. **Sincronizar.**
   - `git fetch`.
   - Ler as PRs abertas (`gh api .../pulls?state=open`), os comentários de revisão nelas e os resultados do branch `validacao-windows`.
0.5. **Integrar.** O integrador confere as PRs abertas e faz o merge das que passaram nas 7 travas. As outras ganham um comentário com a trava que segurou.
1. **Consertar antes de criar.** A prioridade é, em ordem:
   1. Uma PR do ciclo com **falha na validação Windows** → o desenvolvedor corrige no mesmo branch.
   2. Uma PR com **comentário do Raphael pedindo mudança** → o desenvolvedor atende no mesmo branch.

   Novos commits entram na mesma PR, sempre sem `--force`.
2. **Limite de fila.** Se já houver **3 PRs do ciclo** abertas (depois do passo 0.5), não comece item novo. Faça só o passo 1, ou nada, e avise no resumo.
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
- Merge fora das 7 travas do integrador, `push --force`, apagar branches, disparar GitHub Actions.
- Mexer nas travas de segurança ou pegar item `bloqueado`.
- Tocar no PC real do Raphael, em discos reais ou em dados reais.
- Mudar o `CLAUDE.md` ou o status de um item de outro jeito que não seja a PR do próprio item.

## O que é do Raphael
1. **Uma vez só:** ligar a validação automática no Windows (veja abaixo).
2. **Decisões e testes no hardware real** marcados no backlog (`Raphael: ...`) ou numa PR ("Decisão para o Raphael", "Teste manual para o Raphael"). Responda com um comentário na PR ("aprovado" ou o que mudar).
3. **Vetar** qualquer PR, quando quiser, com a etiqueta `nao-mergear`.
4. **Governança:** PRs que mudam `CLAUDE.md`, agentes, este roteiro ou a validação.

### Ligar a validação automática no Windows (uma vez)
Num Terminal **normal** (não de administrador):
```
schtasks /Create /TN "PCRO validacao Windows" /TR "C:\Users\rapha\PCRO-restaurar-app\scripts\validar_windows_agendado.cmd" /SC HOURLY /MO 3 /ST 08:54 /F
```
Para testar na hora: `schtasks /Run /TN "PCRO validacao Windows"`. O log fica em `%LOCALAPPDATA%\pcro-validacao.log`.
Para desligar: `schtasks /Delete /TN "PCRO validacao Windows" /F`.

## Limites conhecidos
- A tarefa agendada do claude.ai **não tem terminal no PC** (só arquivos e navegador). Por isso a validação Windows usa o Agendador de Tarefas do próprio Windows, e não um agente do Claude.
- A validação só roda com o PC ligado e com a sessão do Windows iniciada.
- A nuvem roda Linux sem Tk: os testes de interface só rodam na validação Windows.
- Recursos que dependem do Windows (ACL, registro, winget, WMI) são testados com simulação na nuvem. A prova real é a validação Windows e, quando o backlog pedir, o teste do Raphael no PC.
