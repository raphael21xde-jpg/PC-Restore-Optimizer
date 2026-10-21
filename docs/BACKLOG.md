# Backlog do PC Restore & Optimizer

Fila de trabalho dos agentes (roteiro em `docs/AUTOMACAO.md`). O trabalho é
organizado em **marcos**. Cada marco é um pedaço do app que o Raphael
consegue usar e testar de verdade. Os agentes fazem os itens de um marco em
ordem e, quando o marco fica pronto, pedem **uma** validação ao Raphael, com o
passo a passo, por notificação no celular.

**Status:** `pronto` (os agentes podem pegar) · `bloqueado` (falta algo; o motivo está escrito) · `concluído`.
Um item está "em andamento" quando existe uma PR aberta com o ID dele no título.

**Regras do backlog:**
- Os agentes pegam o **primeiro `pronto` do marco atual**. Só passam para o próximo marco quando o atual estiver todo `concluído`, ou com o restante `bloqueado`.
- Quando um item tiver uma escolha de design, o agente escolhe a opção **mais segura** e registra a escolha na PR e no resumo. Ele **não para** pra perguntar.
- A PR de cada item muda o status dele para `concluído`.
- Os agentes podem acrescentar itens de correção (`FIX-...`) quando a validação Windows ou os testes acharem um erro.

---

## Marco M1 — Restauração completa pelo app  ← ATUAL
**Objetivo:** tudo o que foi feito à mão no PC do Raphael em 20/10 (restaurar, corrigir permissões, programas, launchers, navegador) passa a ser feito **pelo app**, com botões e prévia, sem Terminal.

### P2-01 · Restaurar no lugar original
- **Fatia 1 (motor + prévia):** `concluído` (PR #58). Decisão registrada: **copiar e manter a pasta de conferência**, sem mover nem apagar.
- **Fatia 2 (tela):** `concluído` (branch `auto/P2-01-colocar-no-lugar-original`).
  - Na tela de restauração: botão "Colocar no lugar original";
  - prévia com contagem de novo / igual / renomear / precisa de administrador / bloqueado;
  - confirmação;
  - progresso, cancelamento e retomada;
  - relatório em português simples (sem nomes internos);
  - itens de Program Files e ProgramData só com caixa de confirmação separada;
  - tratar as ressalvas do revisor da #58: raiz do `target_map` com junção, retomada de `.pcro-partial` em `in_progress`.
  - **Escolhas de design (21/10/2026, a opção mais segura):**
    - só aceita uma pasta de conferência criada pelo app (`TESTE-RESTAURACAO-v05-…`), do mesmo backup, com a restauração **concluída** e **todos** os arquivos conferidos (`verified_keys` igual a `keys`); parcial, cancelada ou de outro backup é recusada;
    - a prévia usa só as chaves restauradas nessa pasta (`plan_placement(keys=…)`), para os arquivos do backup que não foram restaurados não aparecerem como "bloqueado";
    - o diário da colocação tem caminho fixo, ao lado da pasta de conferência e fora dela (`COLOCAR-NO-LUGAR-<pasta>.json`); se ele for um atalho/link, nada é feito; abrir a mesma pasta de novo retoma sem duplicar;
    - Program Files/ProgramData: caixa **desmarcada** por padrão e, se marcada, uma segunda confirmação própria; só o valor `True` libera;
    - como administrador, a colocação é recusada antes de gravar qualquer coisa (mesma trava do P2-02);
    - a raiz do mapeamento também é conferida: raiz que é link/junção deixa o item bloqueado;
    - a identidade (st_ino, st_dev) do `.pcro-partial` é gravada no diário logo depois de criá-lo; na retomada ele só é descartado se a identidade bater; senão é **conservado** e o item vira falha;
    - nesta fatia a tela **não** oferece `target_map` (colocar em outra raiz): o destino é sempre o caminho original do manifesto.

### P2-02 · Recusar restauração como administrador
- **Fatia 1:** `concluído` (PR #59).
- **Fatia 2:** `concluído` (branch `auto/P2-02-trava-admin-motores`). A trava agora fica dentro de `restore_selected` (backup_features), `restore_test` (backup_core) e `restore_to_staging` (navegadores). Escolhas de design:
  - a trava é a **primeira instrução** de cada motor: vem antes do cancelamento, de resolver caminhos, de ler o manifesto/cofre (`verify_vault`) e de criar qualquer pasta; recusado, o destino fica como estava (também na retomada);
  - novo módulo `elevation_guard.py` **sem importar nada do projeto** (evita import circular entre os motores); `restore_elevation.py` reexporta os mesmos objetos, com os mesmos textos;
  - só o literal `True` em `allow_elevated` libera (1, 'yes', 'True' e None continuam recusados);
  - `guarded_restore_selected` repassa `allow_elevated` e `elevation_probe` ao motor, para os dois usarem a mesma resposta; `run_placement` (P2-01) continua usando `require_not_elevated`, agora vindo do módulo novo;
  - pendente para uma fatia futura: `restore_legacy_opera` e `extract_to_staging` (`.opgx`) ainda não têm a trava dentro do motor.

### P2-03 · Caminhos longos (LongPathsEnabled)
- **Status:** `pronto`.
- **Aceite:**
  - leitura (somente leitura) do registro;
  - a prévia de restauração conta os destinos com mais de 259 caracteres;
  - se a opção estiver desligada, mostra o aviso com o comando de administrador para ligar (o app **não** muda o registro sozinho);
  - testes com registro simulado.

### P2-06 · Senhas de navegador em texto puro
- **Status:** `pronto`.
- **Aceite:**
  - detecta `*password*.csv`, `*senha*.csv` e parecidos em Documentos, Downloads e Área de Trabalho, na prévia do backup e depois da restauração;
  - mostra alerta e recomendação;
  - **o app nunca apaga sozinho**.

### P2-04 · Reinstalar programas (winget)
- **Status:** `pronto`.
- **Aceite:**
  - o backup guarda o `winget export`;
  - a tela lista os pacotes por categoria (runtimes, launchers, periféricos, dia a dia, dev, outros), com seleção;
  - `winget import --ignore-unavailable` só depois de confirmar;
  - depois confere pacote a pacote;
  - explica as falhas (por exemplo, "hash diferente → instale pelo site oficial");
  - nos testes, o winget é sempre simulado.

### P2-05 · Launchers e bibliotecas de jogos em outros discos
- **Status:** `pronto`.
- **Aceite:**
  - detecção (somente leitura) de `SteamLibrary`, Epic (`.egstore`), EA, Ubisoft, Riot e Rockstar em todas as unidades;
  - guia pós-instalação por launcher. Steam: "Adicionar unidade". Epic: avisar que pode baixar de novo, com o truque do `.egstore`. Os outros: "Localizar jogo";
  - testes com árvores sintéticas.

### P2-11 · Assistente "Depois de formatar"
- **Status:** `bloqueado` até P2-01 fatia 2, P2-04 e P2-05 estarem `concluído`.
- **Aceite:** uma tela única, passo a passo, com 5 etapas:
  1. conferir discos e letras (somente leitura, com a orientação "trocar letra" se precisar);
  2. restaurar;
  3. programas;
  4. launchers;
  5. navegador e senhas.

  Cada etapa tem um "feito / pular", e o assistente salva o progresso.

### ✅ Validação do Raphael — M1
Quando P2-01 a P2-11 estiverem `concluído`, os agentes abrem a issue **"Validar M1"** (etiqueta `precisa-do-raphael`) com o passo a passo:
1. Atualizar e abrir o app.
2. Restaurar um backup de teste numa pasta de teste.
3. Usar o assistente "Depois de formatar".
4. Responder na issue "aprovado" ou o que mudar.

---

## Marco M2 — Preservação para qualquer PC
### P2-07 · Estabilidade da interface Tk — `pronto`
- Eliminar `invalid command name`, `Tcl interpreter is leaked` e os prints soltos dos testes.
### P2-08 · Central de recuperação ligada ao app — `pronto` (depois do M1)
- A central abre manifestos reais (somente leitura) e restaura pelo fluxo do P2-01.
### P2-10 · Medição de cópia com hardware real (script) — `pronto`
- Script de benchmark que só lê a origem e só escreve numa pasta de teste, com relatório.
- **Raphael:** rodar 1 vez no PC. Vai como pedido na validação do M2.
### P2-09 · Executor multi-disco real — `bloqueado`
- Mexe nas travas de segurança (`copy_authorized` / `physical_independence_verified`). Só com pedido explícito do Raphael.

### ✅ Validação do Raphael — M2
Issue "Validar M2": rodar o benchmark e abrir a central de recuperação com um backup real (somente leitura).

---

## Marco M3 — Otimização universal (carro-chefe)
### P3-01 · Perfil de hardware (somente leitura) — `pronto`
- CPU, GPU, RAM (velocidade e dual channel), discos, notebook ou desktop, Windows.
- Classificação em básico / intermediário / gamer / alto desempenho / notebook.
- Testes com dados simulados.
### P3-03 · Registro de alterações e "desfazer tudo" — `pronto`
- Diário de cada alteração, desfazer individual e desfazer tudo, ponto de restauração antes de cada lote (simulado nos testes).
- Nenhum ajuste passa por fora do diário.
### P3-06 · BIOS: só orientação — `pronto` (depois de P3-01)
- Verifica XMP/EXPO, Resizable BAR e versão da BIOS, só lendo.
- Mostra o passo a passo por fabricante. **Nunca altera.**
### P3-02 · Medição antes e depois — `pronto` (depois de P3-01)
### P3-04 · Ajustes nível seguro (1 clique) — `pronto` (depois de P3-01 e P3-03)
- Só ajustes da lista segura do `CLAUDE.md`, cada um com aplicar e desfazer.
- **Nunca** desligar Defender ou Windows Update.
### P3-05 · Ajustes avançados (com confirmação) — `pronto` (depois de P3-04)

### ✅ Validação do Raphael — M3
Issue "Validar M3": medir, aplicar os ajustes seguros, medir de novo e desfazer tudo, no PC dele.

---

## Marco M4 — Produto final
### P4-01 · Manual curto em português — `pronto`
### P4-02 · Primeiro uso guiado — `pronto` (depois do M1)
### P4-03 · Instalador (.exe) — `pronto` (depois de P4-02)
- Script de build (PyInstaller) e teste do pacote.
- O build roda no PC do Raphael pela validação Windows. GitHub Actions só se ele pedir.
### P4-04 · Interface moderna — `pronto` (depois do M3)
- Proposta visual primeiro, em PR com capturas de tela.

### ✅ Validação do Raphael — M4
Issue "Validar M4": instalar pelo .exe num PC e seguir o manual.
