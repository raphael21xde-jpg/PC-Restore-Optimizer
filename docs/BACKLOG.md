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
- **Status:** `concluído` (fatia única, 21/10/2026).
- **Aceite:**
  - leitura (somente leitura) do registro;
  - a prévia de restauração conta os destinos com mais de 259 caracteres;
  - se a opção estiver desligada, mostra o aviso com o comando de administrador para ligar (o app **não** muda o registro sozinho);
  - testes com registro simulado.
- **Escolhas de design (mais seguras):**
  - módulo `long_paths.py` sem imports do projeto; lê `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled` só com `OpenKey(..., KEY_READ)` + `QueryValueEx`; nunca cria, grava ou apaga nada no registro;
  - valor ausente conta como desligado; erro de permissão, tipo errado ou fora do Windows → "não deu para ler", e o app **avisa** como se estivesse desligado;
  - o aviso **não bloqueia** a restauração nem a colocação (o motor não muda); sem botão para ligar: só o texto do comando `reg add ... /v LongPathsEnabled /t REG_DWORD /d 1 /f`, para rodar num Terminal de administrador e depois reiniciar;
  - restaurar para pasta nova: conta o tamanho exato dentro da pasta nova (`TESTE-RESTAURACAO-v05-` + 8 caracteres) e mostra o aviso na pergunta de confirmação; colocar no lugar original: o registro é lido uma vez em segundo plano, junto com a prévia;
  - sem destino longo, os textos existentes ficam iguais;
  - `target_map` na tela e o cofre do navegador ficam fora desta fatia.

### P2-06 · Senhas de navegador em texto puro
- **Status:** `concluído` (fatia única, `auto/P2-06-senhas-texto-puro`).
- **Escolhas de design:**
  - detecta **só pelo nome** (`plaintext_passwords.py`), sem abrir nem ler o arquivo; o alerta mostra nome e pasta, nunca o conteúdo;
  - **não bloqueia** o backup nem a restauração: só avisa, e na prévia diz quais desses arquivos entram na cópia (o backup não é criptografado);
  - **sem botão de apagar nem de abrir**: a recomendação é importar no navegador ou num gerenciador de senhas e apagar à mão, também da Lixeira;
  - a busca não segue links simbólicos nem junções, desce no máximo 2 níveis e olha no máximo 20 mil itens (se bater no teto, avisa que a busca ficou incompleta);
  - só `.csv` nesta fatia (padrões `*password*`, `*senha*`, `*logins*`, `*credenciais*`, `*credentials*`, sem diferenciar maiúsculas);
  - pastas: Documentos, Downloads e Área de Trabalho a partir de `USERPROFILE`, inclusive as variantes do OneDrive;
  - na restauração, olha **só os caminhos restaurados conhecidos** (pasta nova e destinos colocados no lugar original), sem varrer o disco.
- **Aceite:**
  - detecta `*password*.csv`, `*senha*.csv` e parecidos em Documentos, Downloads e Área de Trabalho, na prévia do backup e depois da restauração;
  - mostra alerta e recomendação;
  - **o app nunca apaga sozinho**.

### P2-04 · Reinstalar programas (winget)
- **Status:** `concluído` (fatias 1 e 2).
- **Aceite:**
  - o backup guarda o `winget export`;
  - a tela lista os pacotes por categoria (runtimes, launchers, periféricos, dia a dia, dev, outros), com seleção;
  - `winget import --ignore-unavailable` só depois de confirmar;
  - depois confere pacote a pacote;
  - explica as falhas (por exemplo, "hash diferente → instale pelo site oficial");
  - nos testes, o winget é sempre simulado.
- **Fatia 1 (salvar e listar):** `concluído` (branch `auto/P2-04-lista-programas-winget`). Módulos novos `winget_programs.py` e `winget_programs_ui.py`; no fim de um backup `concluido` o app pergunta se salva a lista; na tela de restauração, botão "Programas do backup". Nada é instalado. **Escolhas de design (21/10/2026, a opção mais segura):**
  - o `winget export` só roda com o "Sim" da pessoa, depois do backup concluído (parcial/cancelado não pergunta); uma falha nunca muda o resultado do backup;
  - comando fixo `export --output … --source winget --include-versions --disable-interactivity`, sem shell, `stdin` fechado, tempo-limite de 180 s; **sem** `--accept-source-agreements`: se o winget pedir os termos, a mensagem explica que é preciso abrir o winget uma vez;
  - grava só numa subpasta **nova** `programas-winget/` da pasta do backup (exige `manifest.json` ao lado); recusa se a subpasta já existir (não sobrescreve) ou for link/junção; `manifest.json` e os arquivos copiados ficam intocados;
  - gravação em `winget-export.json.parcial` → `os.replace` → `info.json` atômico (sha256, quantidade, data); em falha o `.parcial` fica onde está, é ignorado e nada é apagado (para tentar de novo é preciso renomear a subpasta);
  - leitura confere o sha256 do `info.json` ("lista alterada" se não bater), limite de 5 MB e 5000 pacotes, cada ID validado com `package_id` (Microsoft Store: 12 letras/números), duplicados removidos;
  - pacotes da Microsoft Store aparecem mas não são marcáveis ("instale pela Microsoft Store"); `ppy.osu` não é marcável (o winget instala o osu!lazer, não o clássico); fonte desconhecida também não;
  - nada vem pré-marcado; categorias por tabela ordenada de prefixos de ID + termos de `program_catalog.PERIPHERAL_TERMS` (Dev antes de Periféricos), sem diferenciar maiúsculas; o resto vai para "Outros";
  - a escolha feita na janela ainda não é salva: isso e o `winget import` com confirmação ficam para a fatia 2.
- **Fatia 2 (instalar e conferir):** `concluído` (branch `auto/P2-04-instalar-programas-winget`). Módulo novo `winget_install.py` (o **único** que roda `winget import`); na janela "Programas do backup", botão "Instalar marcados…", confirmação e tabela de resultado. **Escolhas de design (21/10/2026, a opção mais segura):**
  - o arquivo de importação é montado pelo app, só com os IDs marcados que são da fonte `winget`, marcáveis e válidos (`package_id` de novo); nunca Microsoft Store, nunca `ppy.osu`; fonte fixa no código (não copia a do backup) e **sem versões** (instala a atual); lista vazia → recusa;
  - ordem de instalação = a ordem em que a lista aparece na tela (a de `parse_export`: por categoria e, dentro de cada uma, por ID, sem diferenciar maiúsculas), não a ordem em que a pessoa clicou;
  - pasta de trabalho **nova** a cada instalação: `%LOCALAPPDATA%\PC-Restore-Optimizer\instalacoes-winget\AAAAMMDD-HHMMSS\` via `os.mkdir` (se já existir, usa `-2`, `-3`…; nunca reaproveita); `importar.json`, `relatorio.json` e `relatorio.txt` gravados de forma atômica; **nada** vai para dentro do backup e nada é apagado;
  - comando fixo `import --import-file … --ignore-unavailable --no-upgrade --disable-interactivity`, **sem** `--accept-package-agreements`/`--accept-source-agreements`, sem shell, `stdin` fechado, nunca pede elevação; recusa se o app estiver como administrador (`elevation_guard`), fora do Windows ou sem winget (o winget nem é chamado);
  - antes do import, `winget list --id X --exact` por pacote: os já instalados saem do arquivo e ficam "já instalado"; se todos já estiverem, o import nem roda;
  - tempo-limite de 2 h que **não** encerra o winget nem os instaladores (só para de esperar); a saída vai para `saida-winget.txt` na pasta de trabalho; a conferência roda mesmo se o tempo acabar ou o winget não abrir;
  - só um `winget import` por vez: trava no `winget_install` (sem esperar); outra tentativa é recusada com "Já existe uma instalação em andamento" e o botão fica desligado; se o tempo-limite acabar com o winget ainda vivo, a trava continua presa até ele terminar de fato (a tela avisa);
  - depois do import, confere de novo pacote a pacote: "instalado" só com código 0, sem "No installed package found"/"Nenhum pacote instalado" e com o ID na saída do `winget list` (inteiro, ou cortado com "…" quando o pedaço tem pelo menos 8 letras e é o começo exato do ID); senão "não instalado" com explicação (hash **diferente** → site oficial — só mensagens de divergência, como "hash does not match" ou 0x8a150011; a linha de sucesso "Successfully verified installer hash" não conta; não encontrado; precisa de administrador → instale sozinho pelo site oficial e aceite o aviso do Windows; já instalado; termos de uso; resto → "não deu para confirmar, instale pelo site oficial"), procurando só no trecho da saída entre esse ID e o próximo ID marcado;
  - relatório com uma linha por pacote (ID, resultado, explicação), sem caminhos; o caminho da pasta só aparece na tela;
  - `run_install` nunca levanta exceção: erro de pasta, do winget ou inesperado vira texto em português;
  - tela: botão ativo só com ≥1 marcado e app não-administrador; confirmação com a lista só para leitura, frase "Alguns instaladores podem mostrar o aviso de administrador do Windows; você decide em cada um.", caixa "Entendi que estes programas serão baixados e instalados neste PC" desmarcada, botão "Instalar N programa(s)" desligado até marcar, "Cancelar" é o padrão (Enter/Esc cancelam); durante a instalação os botões ficam travados, sem "cancelar", e fechar a janela mostra "aguarde, a instalação continua"; a instalação roda num `Job` (thread) e volta ao Tk por `after`;
  - as marcações **não** são salvas: a tela avisa que valem só enquanto a janela estiver aberta;
  - ressalvas da PR #69: `load_export` com erro de leitura (arquivo em uso/sem permissão) → mensagem em português; termos de periférico com até 5 letras (ex.: "sonar", "swarm", "razer") só contam como pedaço inteiro do ID; o texto de "falta a lista" explica que backups anteriores não têm a lista e quem já formatou deve usar o site oficial;
  - "Salvar lista agora" (aparece quando a lista falta ou falhou; desligado enquanto a lista está sendo lida), com pergunta Sim/Não (padrão Não) avisando que só faz sentido no Windows antigo, ANTES de formatar; grava numa pasta nova `programas-winget-2`, `-3`… sem tocar nas anteriores; `load_export` lê a pasta íntegra de número mais alto (cai para a anterior se a mais nova estiver incompleta ou alterada).

### P2-05 · Launchers e bibliotecas de jogos em outros discos
- **Status:** `concluído` (fatia única, branch `auto/P2-05-launchers-jogos`).
- **Aceite:**
  - detecção (somente leitura) de `SteamLibrary`, Epic (`.egstore`), EA, Ubisoft, Riot e Rockstar em todas as unidades;
  - guia pós-instalação por launcher. Steam: "Adicionar unidade". Epic: avisar que pode baixar de novo, com o truque do `.egstore`. Os outros: "Localizar jogo";
  - testes com árvores sintéticas.
- **Escolhas de design (21/10/2026, a opção mais segura):**
  - módulo novo `game_launchers.py` (sem Tk, só leitura) e janela `launcher_guide_ui.py`, aberta pelo botão "Launchers de jogos" da janela de restauração, ao lado de "Programas do backup";
  - `detect_launchers(roots=None, max_depth=4, max_dirs=20000, max_manifests=300)`: sem `roots`, no Windows usa `deep_discovery.local_drives()` (unidades com letra); fora do Windows devolve vazio; se a lista de unidades falhar, devolve vazio com aviso (não inventa unidades);
  - busca em largura com `os.scandir` + `lstat`; links simbólicos e pontos de reparse/junções são pulados (mesma regra de `game_saves._safe_directory`); na raiz de cada unidade pula `Windows`, `Users`, `$Recycle.Bin`, `System Volume Information`, `Recovery` e `$WinREAgent`; não entra numa biblioteca já encontrada; profundidade máxima 4 a partir da raiz (alcança `C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games`); passou de `max_dirs` pastas → para, `truncated=True` e aviso na tela;
  - marcas: Steam = pasta `steamapps` com `libraryfolders.vdf` ou `appmanifest_*.acf` (o caminho mostrado é a pasta que contém `steamapps`, a que se escolhe em "Adicionar unidade"); Epic = pasta com `.egstore`; EA = pasta com `__Installer`; Ubisoft = pasta com `uplay_install.state` ou `Ubisoft Game Launcher\games` — todas com confiança "alta"; Riot = pasta `Riot Games` (subpastas viram jogos, menos `Riot Client`) e Rockstar = pasta `Rockstar Games` (menos `Launcher` e `Social Club`) — confiança "provável";
  - Epic, EA e Ubisoft (por jogo) são agrupados pela pasta-mãe: uma linha por pasta de jogos, com a lista de jogos dentro;
  - o único conteúdo lido é o campo `"name"` dos `appmanifest_*.acf` da Steam: no máximo 64 KiB por arquivo (maior é ignorado) e 300 arquivos no total (passou disso, aviso);
  - guias em `LAUNCHER_GUIDES`/`guide_for`: Steam → Configurações > Armazenamento > "Adicionar unidade"; Epic → avisa que pode baixar de novo, truque de não mexer no `.egstore` e instalar apontando para a pasta-mãe, e "se começar a baixar tudo, cancele: nada se perde"; EA, Ubisoft, Riot e Rockstar → "Localizar jogo" na página do jogo. Nenhum guia manda apagar, renomear ou desinstalar (há teste);
  - a janela não tem botão para abrir launcher ou pasta e não executa nada: tabela (launcher, pasta, nº de jogos, confiança), guia em texto só leitura ao clicar numa linha, "Pesquisar de novo", "Copiar caminho" (área de transferência) e "Fechar"; a busca roda num `Job` (thread) e volta ao Tk por `after`; o aviso de busca incompleta fica numa linha própria, que não some ao copiar um caminho.

### P2-11 · Assistente "Depois de formatar"
- **Status:** `pronto` (as dependências P2-01 fatia 2, P2-04 e P2-05 estão `concluído`).
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
