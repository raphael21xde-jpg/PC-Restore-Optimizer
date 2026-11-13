# Automação do desenvolvimento — como a equipe de agentes trabalha

**Regra de ouro:** os agentes constroem o app sozinhos, todos os dias. Correções
(`FIX-...`) e itens que **já estão** no `docs/BACKLOG.md` andam sem o Raphael.
Ele decide em dois tipos de momento, sempre pelo **PCRO Monitor** (não por
comentário em issue):

**A. Funcionalidade nova** (um item que não está no backlog, ou que toca dados ou discos reais):
- **Gate 1, intent:** antes de qualquer código, o planejador cria um pedido `intent` com o problema, o que muda para quem usa e as perguntas do Grill. Só segue com "Aprovar".
- **Gate 2, fatiamento:** depois, um pedido `fatiamento` com as fatias verticais. Só começa o build com "Aprovar".

**B. Os quatro casos de sempre** (pedido `marco` ou `ajuda`):
1. **Validação de um marco:** um pedaço do app ficou pronto pra ele usar e dizer se está certo.
2. **Algo que só o PC dele faz:** por exemplo, a validação no Windows parou há mais de 24 h.
3. **Mexer nas travas de segurança:** formatar, apagar, executor multi-disco. Isso só acontece se ele pedir.
4. **Um erro que os agentes não conseguiram resolver** em 2 ciclos seguidos.

Enquanto um pedido espera, o ciclo continua com os `FIX-...` e o backlog.

(Regras aprovadas pelo Raphael em 21/10/2026; gates de funcionalidade nova e aprovações pelo Monitor em 22/10/2026.)

## A equipe

| Agente | Papel | Arquivo |
|---|---|---|
| **Coordenador** | É o próprio ciclo agendado. Segue este roteiro, chama os outros agentes, escreve o resumo e chama o Raphael quando precisa | (prompt da tarefa agendada) |
| **Planejador** | Gerente de produto: escolhe o próximo item do **marco atual** e divide em fatias que entregam algo usável. Em funcionalidade nova, cria os pedidos `intent` e `fatiamento` no Monitor | `.claude/agents/planejador.md` |
| **Desenvolvedor** | Programa a fatia com testes, no branch `auto/<ID>-<slug>` | `.claude/agents/desenvolvedor.md` |
| **Testador** | Roda a suíte completa no branch e na `main`. **Monitora** os resultados do Windows da `main` e transforma falhas em itens `FIX-...` | `.claude/agents/testador.md` |
| **Revisor** | Revisão independente contra as regras de segurança e `docs/REGRAS.md`. **Aponta**, não corrige. Pode bloquear | `.claude/agents/revisor.md` |
| **Integrador** | Atualiza a PR com a `main`, confere as travas e faz o **merge** | `.claude/agents/integrador.md` |

**Fora do Claude:** o **Agendador de Tarefas do Windows**, no PC do Raphael, testa a `main` no Windows de verdade a cada 3 h e publica os resultados no branch `validacao-windows`. Ele roda sozinho, e o Raphael não precisa fazer nada.

## Roteiro de cada ciclo (02:48, horário de Brasília; um por dia desde 22/10/2026)

0. **Ler as decisões do Raphael (coordenador).** Ler a coleção `aprovacoes` do Monitor (veja "Pedidos no PCRO Monitor"). Para cada pedido decidido desde o último ciclo:
   - copiar a decisão (e a resposta, se houver) como comentário na issue de registro e fechá-la quando for `aprovado` ou `descartado`;
   - `intent` aprovado → o planejador cria o pedido `fatiamento` neste ciclo;
   - `fatiamento` aprovado → as fatias entram no `docs/BACKLOG.md` como `pronto` e seguem o fluxo normal;
   - `ajustar` → o planejador refaz com o texto do Raphael e cria um **novo** pedido (o antigo fica no histórico);
   - `descartado` → a ideia é registrada no backlog como descartada, com a data, e não volta sem ele pedir;
   - `marco` aprovado → conta como validação do marco.
1. **Olhar a saúde do projeto (testador).**
   - Ler o resultado mais recente da `main` no branch `validacao-windows`.
   - Se o Windows falhou: criar ou retomar um item `FIX-<data>-<assunto>`, que vira **prioridade máxima**.
   - Se não chegou resultado novo há mais de 24 h: chamar o Raphael (caso 2).
2. **Terminar o que está aberto (integrador + desenvolvedor).** Para cada PR aberta dos agentes:
   - **pronta** (testador sem regressão + revisor aprovou, no commit atual) → o integrador faz o merge;
   - **atrás da `main` ou com conflito** → o integrador faz `git merge origin/main` no branch (nunca rebase nem `--force`), roda a suíte de novo e faz o merge;
   - **reprovada** → o desenvolvedor corrige os pontos que o revisor apontou, depois testador e revisor de novo.
   - **PRs do Gemini (branches `gemini/`, ver `GEMINI.md`).** O Gemini trabalha no PC do Raphael, com fila própria, e abre PRs em rascunho. O Claude e o Gemini se falam **só pelo GitHub** (comentários nas PRs), e o Raphael decide **só pelo Monitor** (regra de 13/11/2026). Em cada ciclo, para **no máximo 2** PRs `gemini/` abertas:
     - **sem veredito no commit atual** → o testador roda a suíte completa e um revisor novo revisa o diff; os dois vereditos vão como comentário na PR;
     - **reprovada** → o comentário traz a lista do que corrigir, escrita para o Gemini seguir sem contexto extra. Os agentes **não corrigem** o código dessas PRs;
     - **aprovada** (testador sem regressão + revisor `APROVAR` ou `APROVAR COM RESSALVAS`, no commit atual) e ainda sem pedido → criar no Monitor um pedido do tipo `merge` (veja "Pedidos no PCRO Monitor"), com o número da PR, o que o usuário ganha e as ressalvas;
     - **pedido `merge` aprovado pelo Raphael** e a PR ainda no mesmo commit do pedido → o integrador confere as travas e faz o merge. Se o commit mudou depois do pedido, a PR volta para revisão e um pedido novo é criado;
     - **`ajustar`** → o texto do Raphael vai como comentário na PR, para o Gemini corrigir; **`descartado`** → comentar a decisão e pôr a etiqueta `nao-mergear` (não fechar a PR nem apagar o branch).

     Sem pedido `merge` aprovado, nenhuma PR `gemini/` é mesclada. Depois do merge, o coordenador marca o item como `concluído` no `docs/BACKLOG.md`. No painel, o Gemini aparece como um agente a mais, com o estado tirado dessas PRs.
3. **Avançar (planejador → desenvolvedor → testador → revisor → integrador).**
   - Ordem: os itens `FIX-...` primeiro, depois o primeiro `pronto` do marco atual.
   - **Uma fatia por vez, até o merge.**
   - Uma escolha de design **dentro** de um item do backlog é resolvida com a opção **mais segura**, registrada na PR e no resumo, sem parar.
   - **Funcionalidade nova** (fora do backlog, ou que toca dados ou discos reais) **não** é decidida pelos agentes: o planejador cria o pedido `intent` e o ciclo segue com o resto. Nada dela é programado antes dos dois "Aprovar".
4. **Marco pronto?** Se todos os itens do marco estiverem `concluído`, criar o pedido `marco` no Monitor com o passo a passo do backlog, e a issue **"Validar M<n>"** (etiqueta `precisa-do-raphael`) como registro (caso 1). Enquanto ele não responde, os agentes seguem para o próximo marco.
5. **Resumo (vai para o celular).** A primeira linha é sempre uma destas:
   - `🟢 Nada pra você.` + o que foi feito (merges e PRs), em até 5 linhas.
   - `📱 PRECISA DE VOCÊ: <assunto>` + "abra o PCRO Monitor" + o resumo do pedido em até 3 linhas.

## Pedidos no PCRO Monitor (aprovações)

O Monitor (https://claude.ai/artifact/JF9WAdMxDfXyJiJwDHTiqq) tem a seção **"Precisa de você"**, com os
botões **Aprovar**, **Ajustar** (pede um texto) e **Descartar**. Os agentes usam a ferramenta
`ArtifactData` (carregar via ToolSearch) com o `url` do Monitor, na coleção `aprovacoes`.

**Criar um pedido:** `set` em `aprovacoes/<id>`, com `id` = `<tipo>-<AAAAMMDD>-<slug>` (curto, só letras, números e `-`):

| Campo | Conteúdo |
|---|---|
| `id` | o mesmo do documento |
| `tipo` | `intent`, `fatiamento`, `marco`, `regras`, `ajuda` ou `merge` (PR do Gemini aprovada na revisão; `detalhes.itens` traz o número da PR, o commit revisado `sha12`, o que o usuário ganha e as ressalvas) |
| `titulo` | uma linha, em português simples |
| `resumo` | até 3 linhas: o que se pede e por quê |
| `detalhes` | `{texto, itens: [..], perguntas: [{pergunta, proposta}]}`. No `intent`: Problema, "Antes o usuário ___ / Depois ___", fora de escopo e as perguntas do Grill; no `fatiamento`: uma fatia por item (o que entrega, critério de aceite); no `marco`: o passo a passo |
| `link_issue` | URL da issue de registro (ou `""`) |
| `criado_em` | `"DD/MM/AAAA HH:MM"` (Brasília) |
| `status` | sempre `"pendente"` ao criar |
| `resposta`, `decidido_em`, `decidido_por`, `decidido_como` | `""` ao criar |
| `respostas` | `[]` ao criar (o Monitor grava uma resposta por pergunta) |

**Perguntas do Grill** (obrigatórias no `intent`, cada uma com a proposta **mais segura** dos agentes, que o Raphael confirma ou corrige):
1. O que acontece com os dados do usuário se a operação falhar no meio?
2. A operação é reversível? Como?
3. Funciona num PC que não tem C:, D:, F: e G:? (o PC do Raphael é só ambiente de teste)
4. Precisa de confirmação explícita antes de executar?
5. Como o usuário sabe que deu certo (SHA-256, contagem de arquivos, tamanho)?

**Ler as decisões:** `list` (ou `query`) em `aprovacoes`. Vale só a decisão com `status` diferente de `pendente`,
`decidido_como == "dono"` e `decidido_em` preenchido. Os agentes **nunca** gravam `status`, `resposta`,
`respostas`, `decidido_*` num pedido: só criam pedidos novos. Um pedido decidido não é reaberto; para mudar algo, crie outro.

**Segurança:** só o Raphael decide.
- No banco do Monitor, a coleção `aprovacoes` tem a regra de escrita `owner`: só o dono do Monitor grava nela (o servidor recusa qualquer outra pessoa, mesmo um editor convidado).
- A tela só mostra os botões para o dono (`isOwner()`); para qualquer outra pessoa eles ficam desligados.
- A tela grava `decidido_por` (o id opaco do dono) e `decidido_como: "dono"`. Decisão sem isso é **ignorada** pelo ciclo.
- Os agentes rodam com a conta do Raphael, por isso a regra acima (nunca gravar decisão) é obrigatória: a única origem válida de uma decisão é o botão no Monitor.

**Limpeza:** no máximo 200 pedidos na coleção. Passou disso, o coordenador apaga os decididos mais antigos (mais de 60 dias), depois de copiar a decisão para a issue.

## Erro vira regra (`docs/REGRAS.md`)
- Toda falha que chegou à `main` ou à validação Windows, ou que a revisão pegou e virou correção, ganha uma linha em `docs/REGRAS.md` na mesma PR da correção: `R-<nº> | regra curta e verificável | origem | data`.
- Só o **revisor** lê `docs/REGRAS.md`. O desenvolvedor não recebe as regras: ele segue o plano.
- A cada 10 regras novas, o coordenador cria um pedido `regras` no Monitor para o Raphael revisar e podar a lista.

## Quem corrige o quê
- O revisor **aponta** (arquivo:linha + regra). Quem corrige é o desenvolvedor, e depois o revisor olha de novo.
- Se o revisor mudar algum arquivo por conta própria, a PR lista essas mudanças à parte, com o título **"alterado pelo revisor"**, e o integrador só faz o merge depois de um **novo** revisor aprovar o commit atual.
- Nenhum agente aprova o próprio código.

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
- Mudar as regras (`CLAUDE.md`, agentes, este roteiro, a validação). Isso só acontece numa conversa com o Raphael. (Acrescentar linhas em `docs/REGRAS.md` é permitido; mudar ou apagar uma regra, não.)
- Gravar uma decisão no Monitor, ou programar uma funcionalidade nova sem os dois "Aprovar".

## Validação no Windows (PC do Raphael, já configurada)
- Tarefa do Agendador **"PCRO validacao Windows"**, a cada 3 h, como usuário normal. Ela roda `scripts\validar_windows_agendado.cmd`, que atualiza a `main` e roda `scripts\validar_windows.py`.
- O log fica em `%LOCALAPPDATA%\pcro-validacao.log`.
- Pausar: `schtasks /Change /TN "PCRO validacao Windows" /DISABLE`. Voltar: `/ENABLE`.

## Limites conhecidos
- A tarefa agendada do claude.ai não tem terminal no PC. Por isso o Windows é testado pelo Agendador do próprio Windows, e só com o PC ligado.
- A nuvem roda Linux sem Tk: os testes de interface rodam só na validação Windows, depois do merge.
