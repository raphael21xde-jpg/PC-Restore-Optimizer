# Central de projetos — rascunho do pedido do Raphael

Registro do que o Raphael pediu numa conversa no claude.ai (colada no Claude Code
em 13/11/2026) e do que já foi feito. É um **rascunho de intenção**, não um plano
aprovado: nada daqui é implementado pelos agentes do ciclo.

Este arquivo está guardado no repositório do PCRO só para não se perder. A
central é um projeto **acima** do PCRO e deve ganhar um repositório próprio
quando começar.

## O que o Raphael quer

1. **Uma central de projetos, como um escritório.** Um lugar só para ver todos os
   projetos desenvolvidos com o Claude. Cada projeto é uma "sala", com seus
   agentes (planejador, desenvolvedor, testador, revisor, integrador)
   trabalhando e se comunicando. O PCRO é a primeira sala.
2. **Gastar menos tokens.** Cada tipo de tarefa usa o modelo adequado; o modelo
   mais forte fica só onde a profundidade faz diferença.
3. **Visual com identidade própria.** Sem "cara de IA genérica": organizado,
   centralizado, com um design que conversa com quem usa. O Raphael vai mandar
   referências e skills antes de qualquer desenho.
4. **Substituir o PCRO Monitor** pela central, se fizer sentido. Ele quer saber
   se o Monitor gasta muitos tokens.

## Referências já recebidas

Três vídeos do canal Kauã Miguel (resumo feito na conversa do claude.ai):

- **Orquestrar com uma skill ("plan big, execute small"):** o modelo caro só
  planeja e os baratos executam. Subagentes herdam o modelo do principal se
  ninguém definir outro. Alerta do autor: tarefa pequena sai mais cara delegada
  do que feita direto.
- **Ferramentas de orquestração (Alethe, Orca, Claude Squad, CodeAgentSwarm):**
  apps de desktop que mostram vários agentes e projetos numa tela, com kanban e
  isolamento por git worktree. É a referência visual mais próxima do "escritório".
- **Economia de tokens (RTK, Headroom, Caveman):** comprimir a saída de comandos,
  comprimir contexto e responder curto. Técnicas: planejar antes de executar,
  um chat por assunto, `CLAUDE.md` curto.

Outras ideias de interface estão em `docs/IDEIAS-PARA-APLICAR.md` (regra dos 8
pontos; mascotes para os agentes).

## Fase 1 — enxugar o ciclo do PCRO

| Item | Situação em 13/11/2026 |
|---|---|
| Um modelo por agente (integrador haiku; testador e desenvolvedor sonnet; planejador e revisor opus) | **Feito** — PR #234, na `main` |
| Coordenador em modelo menor | **Em teste** — trocado de opus para sonnet na tarefa agendada (a conversa original sugeria haiku) |
| "Porteiro" barato no início do ciclo (encerra se não há nada a fazer) | Não feito |
| `CLAUDE.md` e arquivos dos agentes mais curtos; relatórios curtos | Não feito (exige conversa com o Raphael) |

### O que a primeira medição mostrou (ciclo extra de 13/11)

- Custo do ciclo: US$ 2,20. Opus (coordenador + revisor): 94%. Sonnet
  (testador): 5%. Haiku (integrador): 1%.
- O gasto está no **coordenador**, que relê um contexto de cerca de 160 mil
  tokens a cada passo. Trocar o modelo dos outros agentes economizou pouco.
- O desenvolvedor em sonnet ainda não foi observado (não rodou naquele ciclo).
- Correção ao que foi dito na conversa original: o ciclo roda **uma** vez por
  dia (02:48), não duas.

### Sobre o PCRO Monitor e os tokens

- Abrir o Monitor não gasta tokens: é uma página que lê um banco de dados.
- Quem gasta é o ciclo, ao ler os pedidos e regravar o painel no fim. Isso é uma
  parte pequena do trabalho do coordenador.
- Falta conferir se a página chama o Claude por dentro em algum botão.

## Fase 2 — a central

Não começa antes de o Raphael mandar as referências e skills de design.

Perguntas em aberto para ele:

1. Onde a central mora: repositório novo, só dela?
2. O que ela precisa fazer no primeiro dia: só mostrar o estado dos projetos, ou
   também mandar (disparar ciclo, pausar, aprovar pedidos, como o Monitor faz)?
3. Página web (como o Monitor) ou aplicativo de desktop (como as ferramentas dos
   vídeos)?
4. Quais outros projetos entram além do PCRO?
5. Os mascotes entram como a "cara" de cada agente?
