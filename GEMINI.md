# Instruções para o Gemini — fila própria no PC Restore & Optimizer

Você trabalha neste projeto ao lado de uma equipe de agentes do Claude. Você tem
uma **fila própria** de itens (abaixo). Faça **um item por vez, na ordem**, e só
esses. Responda em **português simples**: o dono do projeto, o Raphael, está
aprendendo programação.

Antes de cada item, leia `CLAUDE.md`, `docs/REGRAS.md` e o texto do item em
`docs/BACKLOG.md`. Se alguma instrução deste arquivo conflitar com o
`CLAUDE.md`, vale o `CLAUDE.md`.

## Sua fila (nesta ordem)

| Ordem | Item | Branch | Observação |
|---|---|---|---|
| 1 | FIX-P4-01-13 | `gemini/FIX-P4-01-13-destino-navegadores` | Tela: o rótulo "Destino atual" acompanha "Escolher destino" |
| 2 | FIX-P4-01-14 | `gemini/FIX-P4-01-14-previa-unidades` | Tela: a prévia da Preservação monta a lista de unidades a partir do plano, só leitura |
| 3 | P4-02 · Primeiro uso guiado | `gemini/P4-02-proposta` e depois `gemini/P4-02-...` | **Em duas etapas**: veja a seção "P4-02" abaixo |

Já entregues (não refazer): P4-03 (PR #247), FIX-P4-01-16 (PR #248) e FIX-P4-01-15 (PR #249).

Os outros itens do backlog são dos agentes do Claude. **Não pegue nenhum item
fora desta fila**, mesmo que esteja marcado como `pronto`. Em especial, não
pegue FIX-P4-01-12 nem FIX-P4-03-01: eles tocam a escolha do disco de destino e
o diagnóstico de discos. Quando a fila acabar, pare.

## P4-02 · Primeiro uso guiado: em duas etapas

O item não tem critérios de aceite no backlog, então começa por uma proposta.

1. **Etapa 1, só a proposta.** No branch `gemini/P4-02-proposta`, criar
   `docs/P4-02-PROPOSTA.md` (sem mexer em código): o problema, "antes o usuário
   ___ / depois ___", as telas e os textos previstos, o que fica fora, e as
   fatias (uma PR por fatia), cada uma com o critério de aceite. Abrir a PR em
   rascunho e **parar**.
2. **Etapa 2, só depois de a proposta ser mesclada.** Implementar uma fatia por
   PR, na ordem da proposta.

O primeiro uso guiado só orienta e leva às telas que já existem. Não executa
cópia, restauração nem diagnóstico de discos por conta própria, e não muda
nenhuma trava.

## Autoconferência antes de abrir qualquer PR (obrigatória)

Você só enxerga o Windows do Raphael. A revisão do Claude roda num servidor
Linux **sem tkinter**. Antes de abrir a PR, confira e registre na descrição:

1. **Testes sem tkinter.** Rode os arquivos de teste novos ou alterados num
   processo separado com o tkinter bloqueado (`sys.modules['tkinter'] = None`
   antes dos imports). Cada um tem de passar ou ser ignorado com motivo; nenhum
   pode falhar ao importar. Texto e lógica pura ficam em módulos sem tkinter
   (como `workflow_texts.py`), e os testes importam esses módulos.
2. **Nenhum teste que já rodava sem tkinter passou a depender dele.**
3. **Textos.** Sem "não mexe", "intactos" ou "só grava"; dizer o que o app faz
   ("não apaga") e, quando for o caso, que o que fica fora do backup se perde na
   formatação (regra R-88). Sem letra de unidade fixa: usar `system_drive()`.
4. **Módulos falsos.** Teste que troca um módulo em `sys.modules` devolve o
   verdadeiro no fim.
5. **Escopo.** O diff só toca o que o item pede; nenhum arquivo protegido,
   nenhuma trava, nenhum dado pessoal.
6. **Textos alterados.** `grep` nos testes que dependiam do texto antigo.

## Roteiro de cada item

1. `git checkout main` e `git pull`. Se já existir uma PR aberta sua para o
   item, continue nela em vez de recomeçar.
2. Criar o branch do item a partir da `main` atualizada.
3. Dizer o plano em poucas linhas. Se o Raphael estiver presente, esperar a
   aprovação. Se ele avisou que vai se ausentar, seguir o plano mais seguro e
   registrá-lo na descrição da PR.
4. Implementar **com testes** (arquivos sintéticos em `TemporaryDirectory`).
   Se mudar um texto, procurar (`grep`) os testes que dependem do texto antigo e
   atualizá-los no mesmo commit.
5. Rodar a suíte completa. Tem de terminar com 0 falhas e 0 erros no Windows.
6. Enviar o branch e abrir uma **PR em rascunho** para a `main`, com o título
   `<ID>: <resumo> — Gemini`. Na descrição: o que mudou, as escolhas de design,
   o resumo da suíte e as pendências.
7. **Não fazer merge.** Passar para o próximo item da fila, sempre partindo da
   `main` (nunca de um branch seu que ainda não foi mesclado).

Um item só está pronto quando a PR está aberta. Não marque nenhum item como
`concluído` no `docs/BACKLOG.md`: isso é feito depois da revisão.

## Limites enquanto trabalha sem o Raphael por perto

- Só estes comandos sem perguntar: `git` (sem `--force`, sem apagar branches),
  `py -3 -m unittest`, `py -3 -m PyInstaller` e leitura de arquivos do projeto.
- Não instalar programas, não mudar configurações do Windows, não desligar nem
  criar exceção no antivírus.
- Não rodar o app de verdade (`py -3 app.py`) nem qualquer comando que consulte
  ou altere discos, partições, registro ou serviços. O único uso permitido do
  executável é com `--smoke-test`.
- Se um item exigir algo fora desses limites, **pare nesse item**, registre o
  motivo na PR (ou num arquivo em `relatorios-claude/`) e não avance.
- No máximo duas tentativas para o mesmo erro. Depois disso, pare.

## Regras de segurança (inegociáveis)

- **Nunca** formatar, particionar, apagar dados, alterar EFI/BCD/BIOS nem
  instalar o Windows. "Não copiar" nunca significa apagar.
- Não mexer nas travas `copy_authorized`, `physical_independence_verified`,
  `ready_for_format`, `installation_authorized` e `deletions_authorized`.
- Testes só com arquivos sintéticos em `TemporaryDirectory`. Nunca usar como
  alvo dados reais, backups existentes ou o disco do Windows.
- Antes de rodar qualquer comando que consulte discos reais, diga o que vai
  rodar e peça confirmação ao Raphael.
- Não publicar dados pessoais, caminhos com nome de usuário, credenciais nem
  `preferencias-v05.json`.
- Não alterar `CLAUDE.md`, `GEMINI.md`, `.claude/agents/`, `docs/AUTOMACAO.md`
  nem `scripts/validar_windows*`.

## P4-03 · Instalador (.exe): o que fazer

1. Criar um script de build com PyInstaller que gere o executável do app a
   partir de `app.py`, numa pasta de saída que fique **fora do git**.
2. Criar um teste do pacote: conferir que o executável foi gerado e que abre e
   fecha sem erro, sem tocar em discos reais.
3. Documentar em `docs/` como gerar o instalador, em passos curtos.
4. Não usar GitHub Actions. O build roda no PC do Raphael.
5. Não incluir no pacote arquivos pessoais, relatórios nem preferências.

Se faltar uma decisão (nome do executável, ícone, um arquivo só ou pasta),
escolha a opção **mais segura e mais simples**, registre a escolha na descrição
da PR e siga.

## Como trabalhar no git

- Partir da `main` atualizada e criar o branch indicado na fila.
- Commits em inglês, no formato `tipo(área): descrição`, terminando a primeira
  linha com `[skip ci]`. Exemplo: `feat(build): add PyInstaller build script [skip ci]`.
- Sem `push --force`, sem apagar branches, sem mexer em outros branches.
- **Não fazer merge.** Abrir uma PR em rascunho para a `main`, uma por item.

## Testes

- Comando: `py -3 -m unittest discover -s tests`
- Rodar a suíte completa antes de abrir a PR e colar o resumo na descrição
  (`Ran N tests`, falhas, erros, ignorados e o motivo de cada um).
- A suíte tem que terminar sem falhas e sem erros no Windows. Não pular,
  desligar nem apagar testes para ficar verde.
- Se um teste trocar um módulo em `sys.modules` por um falso, ele guarda o
  módulo verdadeiro e o devolve no fim (regra do `docs/REGRAS.md`).

## Quando parar e chamar o Raphael

- Qualquer coisa que toque discos, dados reais ou as travas de segurança.
- Erro que você não resolveu em duas tentativas.
- Necessidade de instalar algo no PC além do PyInstaller.

## Depois da PR

A revisão é feita pelo Claude (numa conversa com o Raphael, ou pelo revisor do
ciclo, se o Raphael assim decidir). Corrija o que a revisão apontar no mesmo
branch. Quem decide o merge é o Raphael. O painel PCRO Monitor é atualizado pelo
Claude a partir do que estiver no GitHub; você não precisa atualizar nenhum painel.
