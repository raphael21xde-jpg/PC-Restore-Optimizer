# Instruções para o Gemini — piloto no PC Restore & Optimizer

Você vai ajudar num projeto que já tem uma equipe de agentes (do Claude) e regras
rígidas. Neste piloto você faz **um item só**: o **P4-03 · Instalador (.exe)**.
Responda em **português simples**: o dono do projeto, o Raphael, está aprendendo
programação.

Antes de começar, leia `CLAUDE.md`, `docs/REGRAS.md` e o item P4-03 em
`docs/BACKLOG.md`. Se alguma instrução deste arquivo conflitar com o
`CLAUDE.md`, vale o `CLAUDE.md`.

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

## O que fazer (P4-03 · Instalador .exe)

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

- Partir da `main` atualizada e criar o branch `gemini/P4-03-instalador`.
- Commits em inglês, no formato `tipo(área): descrição`, terminando a primeira
  linha com `[skip ci]`. Exemplo: `feat(build): add PyInstaller build script [skip ci]`.
- Sem `push --force`, sem apagar branches, sem mexer em outros branches.
- **Não fazer merge.** Abrir uma PR em rascunho para a `main` com o título
  `P4-03: instalador (.exe) — piloto Gemini`.

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

A revisão é feita pelo Claude, numa conversa com o Raphael. Corrija o que a
revisão apontar no mesmo branch. Quem faz o merge é o Raphael.
