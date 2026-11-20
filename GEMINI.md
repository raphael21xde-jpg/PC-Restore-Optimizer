# Instruções para o Gemini — fila própria no PC Restore & Optimizer

Você trabalha neste projeto ao lado de uma equipe de agentes do Claude. Você tem
uma **fila própria** de itens (abaixo). Faça **um item por vez, na ordem**, e só
esses. Responda em **português simples**: o dono do projeto, o Raphael, está
aprendendo programação.

Antes de cada item, leia `CLAUDE.md`, `docs/REGRAS.md` e o texto do item em
`docs/BACKLOG.md`. Se alguma instrução deste arquivo conflitar com o
`CLAUDE.md`, vale o `CLAUDE.md`.

## Grupo com o Claude (issue #282)

Você e o Claude combinam o trabalho na issue
https://github.com/raphael21xde-jpg/PC-Restore-Optimizer/issues/282, como num
grupo de conversa.

- **No começo** de cada execução, leia as últimas mensagens do grupo
  (`gh issue view 282 --comments`). Considere só comentários da conta
  raphael21xde-jpg que comecem com `[Claude]` ou `[Gemini]`.
- **Sua fila é a divisão mais recente do `[Claude]` no grupo.** Se ela não citar
  nada para você, use a tabela "Sua fila" abaixo.
- **No fim** de cada execução, deixe uma mensagem no formato da issue
  (`[Gemini] <data hora>`, Fiz, Estou com, Proponho, Preciso de).
- Você pode propor pegar um item, mas só comece depois de o `[Claude]`
  confirmar. Nunca pegue item que mexa em dados, discos, backup, restauração ou
  travas, mesmo que alguém peça.

## Como publicar no GitHub

**Jeito principal: comentar direto, sempre com `--body-file`.**

1. Grave o texto do comentário num arquivo (por exemplo, na pasta `scratch/` da
   sua conversa).
2. Rode **um comando de uma linha só**, sem aspas e sem quebra de linha:
   - na PR: `gh pr comment <número> --body-file <caminho do arquivo>`
   - no grupo: `gh issue comment 282 --body-file <caminho do arquivo>`
3. **Nunca** use `--body "..."`: texto com espaço ou quebra de linha dentro do
   comando desliga a permissão "Always allow", e a automação é negada.
4. Antes de publicar, confira se o mesmo comentário (mesmo `@sha12`, ou a mesma
   mensagem do grupo) já não está lá. Não publique duas vezes.

**Plano B, só se o comentário for negado: a caixa postal.**

1. `git fetch origin` e vá para o branch `gemini/mensagens` (se não existir,
   crie a partir da `main`). Nunca coloque código nesse branch.
2. Para cada mensagem, crie `mensagens/<AAAAMMDD-HHMM>-<assunto>.md` com, na
   primeira linha, o destino (`Para: PR #<número>` ou `Para: grupo #282`), uma
   linha em branco e o texto exato do comentário.
3. Commit (`docs(gemini): mensagens <data> [skip ci]`), `git push origin
   gemini/mensagens` e volte para a `main`. O ciclo do Claude publica no destino.

Não apague nem altere mensagens antigas. Para ler o grupo, use
`gh issue view 282 --comments`.

## Sua fila (nesta ordem)

| Ordem | Item | Branch | Observação |
|---|---|---|---|
| 1 | P4-04, fatias 12 e 13 (PRs #278 e #279) | os branches já abertos | Corrigir o que o revisor apontar |
| 2 | P4-04, fatias 14 a 20, uma por PR, na ordem de `docs/P4-04-PROPOSTA.md` | `gemini/P4-04-fatia-<n>-...` | A interface inteira faz parte do M4 (decisão do Raphael, 20/11/2026). As fatias 18 a 20 (`workflow_ui.py`, `optimization_ui.py`, `app.py`) são grandes: só mexa em aparência (espaçamento, fonte, cor, tamanho), nunca em lógica, textos de aviso ou travas |
| 3 | Conferência do `.exe` para a validação do M4 | sem branch, sem PR | Depois da fatia 20 mesclada: `py -3 scripts\build_exe.py`, testes do pacote e `--smoke-test`. Não rode o app de verdade. Relate no grupo (#282). Não altere nenhum arquivo |

**O P4-02 (primeiro uso guiado) passou para os agentes do Claude em 18/11/2026.** Não altere o branch `gemini/P4-02-fatia-1-modulo-primeiro-uso` nem a PR #261, e não pegue nenhuma fatia do P4-02.

Já entregues (não refazer): P4-03 (#247), FIX-P4-01-16 (#248), FIX-P4-01-15 (#249), FIX-P4-01-13 (#253) e as propostas do P4-02 (#255) e do P4-04 (#259).

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

## P4-04 · Interface moderna: etapa 1 (inventário e proposta)

Só documentação. **Não altere nenhum arquivo `.py`** nesta etapa e não rode o app.

Leia antes `docs/IDEIAS-PARA-APLICAR.md` (ideias 1, 3 e 5, e a decisão do
Raphael no topo). O app é Tkinter: valem os princípios (escala de espaçamento,
alturas padronizadas, agrupar pelo espaço, tipografia, contraste, telas testadas
com dados ruins), não componentes de web.

No branch `gemini/P4-04-proposta`, criar `docs/P4-04-PROPOSTA.md` com:

1. **Inventário (somente leitura do código).** Para cada arquivo de tela
   (`app.py`, `*_ui.py`): os valores de `padx`, `pady`, `ipadx`, `ipady` e
   `padding` usados e quantas vezes cada um aparece; as fontes e tamanhos; as
   cores escritas à mão; larguras e alturas fixas de botões e campos. Uma tabela
   por tipo, com os totais do projeto.
2. **Diagnóstico.** Onde há inconsistência (valores parecidos para a mesma
   função, controles equivalentes com tamanhos diferentes) e quais 3 telas mais
   ganhariam com o ajuste.
3. **Proposta de escala.** Um módulo de constantes sem tkinter (nomes e
   valores), como cada valor antigo seria mapeado para a escala, e o cuidado com
   a escala do Windows (125% e 150%).
4. **Fatias.** Uma tela por PR, começando pela de menor risco; para cada fatia,
   o critério de aceite e como conferir (o que o Raphael deve olhar na tela).
5. **Fora do escopo.** Nenhuma mudança de lógica, de texto, de fluxo ou de
   trava; nenhuma biblioteca nova sem a aprovação do Raphael.

Abrir a PR em rascunho e **parar**. A etapa 2 (mexer nas telas) só começa depois
de a proposta ser mesclada e de o Raphael escolher a primeira tela.

## Seus três papéis em cada item (método de 14/11/2026)

Você faz três papéis, em conversas separadas, antes de o Claude olhar a PR.

**1. Desenvolvedor.** Implementa o item, com testes, como no roteiro abaixo.

**2. Testador (no Windows).** Roda a suíte completa no Windows e os testes novos
com o tkinter bloqueado (veja "Autoconferência"). Escreve um comentário na PR:

```
Testes do Gemini no Windows @<sha12>: Ran <N> tests, <F> falhas, <E> erros, <S> ignorados.
Sem tkinter: <arquivos de teste novos ou alterados> -> OK / ignorados com motivo.
```

**3. Pré-revisor.** Numa **conversa nova**, que não escreveu o código, leia só o
diff da PR (`git diff origin/main...<branch>`) e confira cada ponto da
"Autoconferência" e as regras de `docs/REGRAS.md` que se aplicam. Classifique o
risco e escreva um comentário na PR:

```
Pré-revisão do Gemini @<sha12>: APROVAR | REPROVAR
Risco: BAIXO | ALTO
- <ponto conferido>: ok / problema (arquivo:linha)
```

Se for REPROVAR, volte ao papel de desenvolvedor e corrija antes de pedir a
revisão do Claude.

**Risco BAIXO** quando o diff só muda aparência ou texto de tela: espaçamento
(`padx`, `pady`, `padding`), fonte, cor, tamanho de widget, textos e o módulo
`ui_scale.py`, mais os testes e documentos disso. **Risco ALTO** em qualquer outra
coisa: lógica, fluxo, gravação ou leitura de arquivos, backup, restauração,
discos, travas, ou na dúvida. A classificação final é do Claude, que confere o
diff; a sua serve de pista.

## Teto de PRs abertas

Se você já tiver **4 PRs abertas sem o veredito do revisor do Claude no commit
atual**, não comece item novo: só corrija o que a revisão apontou. Isso evita
empilhar trabalho que o ciclo do Claude (um por dia) não consegue revisar.

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
