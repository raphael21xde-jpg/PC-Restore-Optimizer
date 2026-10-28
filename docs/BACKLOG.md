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
- **Funcionalidade nova** só entra aqui depois que o Raphael aprovar o `intent` e o `fatiamento` no PCRO Monitor (veja `docs/AUTOMACAO.md`). Cada fatia aprovada entra como `pronto`, com o id do pedido.

---

## Marco M1 — Restauração completa pelo app
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
  - busca em largura com `os.scandir`; cada entrada usa `DirEntry.is_symlink()` e `DirEntry.stat(follow_symlinks=False)` (no Windows os atributos vêm da própria listagem, sem chamada extra), e links simbólicos e pontos de reparse/junções são pulados (mesma regra de `game_saves._safe_directory`); na raiz de cada unidade pula `Windows`, `Users`, `ProgramData` (evita falso positivo de Riot/Rockstar), `$Recycle.Bin`, `System Volume Information`, `Recovery` e `$WinREAgent`; não entra numa biblioteca já encontrada; profundidade máxima 4 a partir da raiz (uma `steamapps` 4 pastas abaixo da raiz é achada, 5 não; alcança `C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games`);
  - limite de `max_dirs` pastas **por unidade** (revisão da PR #71): se uma unidade passa do limite, a busca para nela e segue para as outras; `truncated=True` e o aviso diz qual unidade ficou incompleta;
  - cancelamento: `detect_launchers(cancelled=...)` aceita `threading.Event` ou função e confere a cada pasta; cancelado → para, `truncated=True` e aviso "interrompida"; fechar a janela liga o cancelamento;
  - bibliotecas na unidade do Windows (`%SystemDrive%`, parâmetro `system_drive` para teste) recebem `on_system_drive=True`: a tabela mostra "Disco do Windows" na coluna Aviso e o guia começa com "Está no disco do Windows: se você formatar este disco, esta pasta será apagada pelo instalador — faça backup antes.";
  - marcas: Steam = pasta `steamapps` com `libraryfolders.vdf` ou `appmanifest_*.acf` (o caminho mostrado é a pasta que contém `steamapps`, a que se escolhe em "Adicionar unidade"); Epic = pasta com `.egstore`; EA = pasta com `__Installer`; Ubisoft = pasta com `uplay_install.state` ou `Ubisoft Game Launcher\games` — todas com confiança "alta"; Riot = pasta `Riot Games` (subpastas viram jogos, menos `Riot Client`) e Rockstar = pasta `Rockstar Games` (menos `Launcher` e `Social Club`) — confiança "provável";
  - Epic, EA e Ubisoft (por jogo) são agrupados pela pasta-mãe: uma linha por pasta de jogos, com a lista de jogos dentro;
  - o único conteúdo lido é o campo `"name"` dos `appmanifest_*.acf` da Steam: no máximo 64 KiB por arquivo (maior é ignorado) e 300 arquivos no total (passou disso, aviso);
  - guias em `LAUNCHER_GUIDES`/`guide_for`: Steam → Configurações > Armazenamento > "Adicionar unidade"; Epic → avisa que pode baixar de novo, truque de não mexer no `.egstore` e instalar apontando para a pasta-mãe, e "se começar a baixar tudo, cancele: nada se perde"; EA, Ubisoft, Riot e Rockstar → "Localizar jogo" na página do jogo. Nenhum guia manda apagar, renomear ou desinstalar (há teste);
  - a janela não tem botão para abrir launcher ou pasta e não executa nada: tabela (launcher, pasta, nº de jogos, confiança), guia em texto só leitura ao clicar numa linha, "Pesquisar de novo", "Copiar caminho" (área de transferência) e "Fechar"; a busca roda num `Job` (thread) e volta ao Tk por `after`; o aviso de busca incompleta fica numa linha própria, que não some ao copiar um caminho.

### P2-11 · Assistente "Depois de formatar"
- **Status:** `concluído` (fatia 1, branch `auto/P2-11-depois-de-formatar`).
- **Aceite:** uma tela única, passo a passo, com 5 etapas:
  1. conferir discos e letras (somente leitura, com a orientação "trocar letra" se precisar);
  2. restaurar;
  3. programas;
  4. launchers;
  5. navegador e senhas.

  Cada etapa tem um "feito / pular", e o assistente salva o progresso.
- **Escolhas de design (21/10/2026, a opção mais segura):**
  - módulo novo `windows_drive.py` (sem imports do projeto, só lê o ambiente): `windows_drive(environ=None)` devolve a letra da unidade de `%SystemRoot%` (ou `%windir%`) só se ela for igual à de `%SystemDrive%` (sem diferenciar maiúsculas); faltando alguma ou divergindo, devolve `None` com o aviso "Não deu para confirmar qual é o disco do Windows";
  - `game_launchers` passa a usar `windows_drive()`: se não der para confirmar no Windows, as bibliotecas recebem `on_system_drive=None` (nenhuma é tratada como fora do disco do Windows), a coluna Aviso mostra "Confira" e há um aviso geral na linha de avisos da janela; fora do Windows continua sem marcar nada e sem aviso;
  - módulo novo `after_format.py` (sem Tk, só leitura nas unidades): `STEPS` com as 5 etapas; `check_drives(manifest, roots=None, usage=shutil.disk_usage, environ=None, drive_type=...)` lista as letras atuais com tipo (GetDriveTypeW, só leitura), tamanho, espaço livre e "Disco do Windows", e compara com as letras dos `source` de `verified_entries(manifest)`; letra do backup ausente agora → aviso e orientação "trocar letra" (Gerenciamento de Disco > botão direito > "Alterar letra de unidade e caminho"), feita à mão pela pessoa; o app nunca troca letra; se a lista de unidades falhar, devolve vazio com aviso e não acusa letra sumida;
  - aviso de senhas: `password_alert(manifest)` usa `plaintext_passwords.scan_paths` nos caminhos do backup e mostra **só os nomes** dos arquivos (sem pastas, para não expor o nome de usuário);
  - progresso: `%LOCALAPPDATA%\PC-Restore-Optimizer\depois-de-formatar\progresso-<12 primeiros do SHA-256 do caminho do manifesto>.json` (um por backup), com `schema` e só os valores `pendente`, `feito` e `pulado`; gravação atômica (`.parcial` + `os.replace`); arquivo estragado, maior que 64 KiB, com valor desconhecido ou que seja link fica **intocado**: o assistente avisa, começa do zero e grava em `-2`, `-3`… (até 50); `save_progress` recusa gravar por cima de link; um `.parcial` que sobrou é ignorado na leitura; nada é apagado;
  - janela nova `after_format_ui.py` (`show_after_format(app, *, manifest=None, base=None, ask_manifest=None, checker=None)`): pede o `manifest.json`; cada etapa tem "Abrir", "Feito" e "Pular" (clicar de novo no mesmo botão volta a "pendente"); "Feito" é só marcação; "Abrir" só chama as janelas públicas que já existem — 1) conferência das unidades num `Job`, voltando ao Tk por `after`; 2) `show_restore(app, manifest)`; 3) `show_programs(dlg, pasta do backup)`; 4) `show_launchers(dlg)`; 5) `show_recovery(dlg)` com o aviso de senhas — sem passar `allow_elevated`/`allow_protected`; pular não bloqueia; abrir a etapa 2 com a 1 pendente mostra um lembrete; fechar a janela cancela o `Job`;
  - `app.py`: só o botão "Depois de formatar" na Visão geral e o item no menu lateral (abre a janela; fica fora de `nav_buttons`, que continua com 8 páginas);
  - textos das etapas sem mandar formatar, apagar ou desinstalar (teste confere).

### FIX-P2-11-01 · Avisos do progresso do assistente
- **Status:** `concluído` (branch `auto/FIX-P2-11-01-avisos-progresso`; ressalvas 2 e 3 da revisão da PR #72).
- **Aceite:** a falha ao salvar o progresso não mostra o caminho completo (que pode ter o nome de usuário); o aviso "o progresso salvo não pôde ser usado" não some ao clicar em "Abrir".
- **Escolhas de design (21/10/2026, a opção mais segura):**
  - `after_format.progress_error_text(exc)` (sem Tk): texto fixo "Não deu para salvar o progresso (<nome do arquivo>, <tipo do erro>). As marcações valem só até fechar a janela."; leva no máximo `exc.filename` reduzido ao nome do arquivo (sem pastas) e o nome da classe do erro, nunca a mensagem do sistema nem o caminho completo;
  - a janela ganhou uma linha própria para os avisos do progresso (`after_format_progress_warning`), separada da linha de lembretes (`after_format_notice`), que "Abrir" continua limpando; a falha ao salvar também vai para essa linha própria, para não sumir no próximo "Abrir" (mesmo padrão da linha de aviso da janela de launchers do P2-05).

### FIX-P2-11-02 · Progresso do assistente: letra trocada e duas janelas
- **Status:** `concluído` (branch `auto/FIX-P2-11-02-progresso-estavel`; ressalvas 1 e 4 da revisão da PR #72).
- **Problema 1:** o arquivo de progresso usa o SHA-256 do caminho completo do manifesto; se a letra da unidade do backup mudar depois de formatar (ex.: `E:` vira `F:`), o assistente não acha o progresso salvo e começa do zero.
- **Problema 2:** duas janelas do assistente abertas para o mesmo backup gravam o mesmo `.parcial`, e uma pode atrapalhar a outra.
- **Aceite:** o progresso continua achado quando só a letra muda (chave estável do backup, sem depender da letra); duas janelas não disputam o mesmo `.parcial` (ex.: nome temporário único ou uma janela por backup); nada é apagado; testes com dados simulados.
- **Escolhas de design (21/10/2026, a opção mais segura):**
  - identidade do backup: `backup_identity(manifest)` lê só o nome da pasta do backup (em minúsculas) e os campos de topo `started` e `plan_fingerprint` do `manifest.json` (os nomes que o `backup_core` grava); manifesto até 8 MiB é lido inteiro; maior que isso (muitos arquivos), lê só o primeiro 1 MiB e procura esses dois campos no nível de topo (o `atomic_json` grava com `indent=2` e eles vêm antes de `files`); valor ausente, vazio ou com mais de 200 caracteres → sem identidade;
  - chave estável = `sha256("v2|" + pasta + "|" + started + "|" + plan_fingerprint)[:12]`; arquivo `progresso-b-<chave>.json`, que não muda quando a letra da unidade muda; o arquivo grava junto o bloco `backup` (a identidade) e só é aceito se esse bloco for igual ao do backup aberto — senão fica intocado e o assistente passa para `-2`, `-3`…;
  - sem identidade (manifesto ilegível ou antigo, sem esses campos): continua a chave antiga pelo caminho (`progresso-<chave do caminho>.json`), com o aviso "Não deu para identificar este backup…";
  - compatibilidade: sem progresso novo, o arquivo antigo do P2-11 (`progresso-<chave do caminho>.json`) é lido só para leitura; o próximo "Feito"/"Pular" grava no arquivo novo; o antigo nunca é reescrito nem apagado;
  - gravação: `.parcial` com nome único (`<arquivo>.parcial-<8 letras>`) criado com `os.open(O_CREAT|O_EXCL|O_WRONLY)` (nunca por cima de nada, nem de link), `fsync` e `os.replace` (se o Windows recusar a troca porque outra janela ou um leitor está com o arquivo aberto, tenta de novo com espera crescente — 5 ms, 10 ms, 20 ms… até 200 ms por vez e cerca de 2 s no total; revisão da PR #76); se falhar, o `.parcial` fica (nada é apagado); `.parcial` antigo de nome fixo é ignorado; recusa de gravar por cima de link mantida;
  - uma janela por backup: `window_key(manifest)` (a chave estável, ou o caminho normalizado sem identidade); `app.after_format_dialogs = {chave: janela}`; abrir de novo o mesmo backup (mesmo por outra letra) traz a janela aberta para a frente (`deiconify()` para voltar se estiver minimizada, depois `lift()`; revisão da PR #76), como a restauração; ao fechar, ela sai do dicionário; backups diferentes abrem janelas separadas;
  - **limite conhecido:** um progresso antigo (P2-11, pelo caminho) cuja letra já mudou não é achado; ele fica intocado e o assistente começa do zero.

### ✅ Validação do Raphael — M1
Quando P2-01 a P2-11 estiverem `concluído`, os agentes abrem a issue **"Validar M1"** (etiqueta `precisa-do-raphael`) com o passo a passo:
1. Atualizar e abrir o app.
2. Restaurar um backup de teste numa pasta de teste.
3. Usar o assistente "Depois de formatar".
4. Responder na issue "aprovado" ou o que mudar.

---

## Marco M2 — Preservação para qualquer PC (P2-09 desbloqueado em 23/10; P3-01 fatia 1 já feita)
### P2-07 · Estabilidade da interface Tk
- **Status:** `concluído` (fatias 1 e 2). A confirmação com Tk fica com a validação Windows a cada 3 h; se `invalid command name` e `Tcl interpreter is leaked` voltarem, vira um FIX novo.
- Eliminar `invalid command name`, `Tcl interpreter is leaked` e os prints soltos dos testes.
- Precisa de ambiente com Tk para conferir; os agentes na nuvem (Linux sem Tk) pulam para o próximo item testável.
- **Fatia 1 (só nos testes):** `concluído` (branch `auto/P2-07-estabilidade-tk`). **Confirmar na validação Windows; se as mensagens continuarem, nova fatia.**
- **Escolhas de design (22/10/2026, a opção mais segura):**
  - mexer **só nos testes**; o comportamento do app não mudou;
  - ajudante comum `tests/tk_helpers.py` (não é um arquivo de teste e importa sem `tkinter`): `close_tk_root(root)` cancela **todos** os `after` pendentes do interpretador (`after info` + `after cancel` direto do Tcl, um por um; um erro num deles não para os outros) e depois chama `destroy()`; não usa `after_cancel` do tkinter, porque ele também apaga o comando (`deletecommand`), o que pode dar erro com a raiz já destruída e apagar comandos do próprio Tk (ajuste da revisão da PR #80); os comandos Python que sobram são apagados pelo `destroy()`; pode ser chamado de novo sem erro; `track_tk_root(self, root)` substitui `addCleanup(root.destroy)` (e o antigo `addCleanup(gc.collect)`, que rodava **antes** do `destroy` e com a raiz ainda presa no teste): no fim do teste fecha a raiz, espera até 1 s pelas threads criadas durante o teste, troca por `None` os atributos do teste que são objetos Tk e roda `gc.collect()` na thread principal;
  - motivo das mensagens do log da `main` b0f669f: os `after` (`poll` e `warn_slow` de `completeness_audit_ui_v068`, `quit` de `test_audit_ui_hotfix_v0681`) ficam na fila de eventos da **thread** e disparam no teste seguinte que roda o laço do Tk, depois que o comando Python já foi apagado → `invalid command name`; os objetos Tk vivem em ciclos de referência e, sem um `gc.collect()` na thread principal, o coletor podia rodar numa thread de trabalho → `Variable.__del__ ... main thread is not in main loop` e `Tcl interpreter is leaked`;
  - aplicado em todos os 41 módulos de teste que criam uma raiz Tk (`App()` ou `tk.Tk()`); onde o `tearDown` destruía a raiz antes de apagar a pasta temporária, ele agora chama `close_tk_root` no mesmo lugar (a ordem continua a mesma);
  - prints soltos: `test_local_test_reporter` e `test_validar_windows` agora capturam a saída das ferramentas (`redirect_stdout`); os scripts não foram alterados;
  - teste sem Tk: `tests/test_tk_helpers_p2_07.py` usa uma raiz falsa.
- **Fatia 2 (no app):** `concluído` (branch `auto/P2-07-timers-auditoria`). Confirmar na validação Windows. `completeness_audit_ui_v068` agenda `poll` e `warn_slow` com `window.after` e eles ficam pendentes depois de fechar a janela; trocar por `WindowTimers` (`ui_timers.py`), que cancela os agendamentos da própria janela ao fechar. Testar com Tk (validação Windows).
- **Escolhas de design da fatia 2 (23/10/2026, a opção mais segura):**
  - reaproveitar `WindowTimers` (`ui_timers.py`) **sem alterar**; `timers = WindowTimers(window)` logo depois de criar a janela e as 5 chamadas (4 de `poll`, 1 de `warn_slow`) passam a usar `timers.after`; textos, fila, threads e lógica não mudaram;
  - não parar threads que já estão consultando uma pasta: a resposta que chegar depois de fechar a janela é descartada (ninguém mais lê a fila);
  - manter a conferência `winfo_exists()` dentro de `warn_slow` (proteção dupla);
  - teste `tests/test_audit_timers_p2_07.py`: parte sem Tk lê o código com `ast` (roda no Linux); parte com Tk abre a janela com o leitor de discos e o relatório simulados, arma `warn_slow`, fecha a janela e confere que nenhum agendamento dela sobra nem dispara;
  - a prova final com Tk fica para a validação Windows.
### P2-08 · Central de recuperação ligada ao app
- **Status:** `concluído` (fatia 1, branch `auto/P2-08-central-recuperacao`).
- A central abre manifestos reais (somente leitura) e restaura pelo fluxo do P2-01.
- **Escolhas de design (21/10/2026, a opção mais segura):**
  - módulo novo `recovery_center.py` (sem Tk, nunca grava nada): `find_backups(pasta, *, max_entries=500, cancelled=None)` procura `manifest.json` na própria pasta e nas subpastas de 1 nível (não desce mais), com `os.scandir`, pulando links, junções e pontos de reparse; a pasta escolhida que seja link é recusada; passou de 500 itens olhados, para e avisa; cancelamento conferido a cada item;
  - `inspect_backup(manifest)`: recusa `manifest.json` que seja link, que não seja arquivo comum ou maior que 256 MiB; mostra nome amigável (`friendly_backup_name` + `backup_labels`, só leitura), data (`started`), situação (`status`), quantidade e tamanho dos arquivos verificados; `restorable` só se `status == 'concluido'`, sem `errors`, com a quantidade igual a `file_count_expected` (e sem entradas duplicadas ou não verificadas) e o tamanho igual a `bytes_expected` — as mesmas regras de `selective_recovery.verify_complete_manifest`; parcial, interrompido, com erros, contagem/tamanho errado, JSON estragado, schema desconhecido ou caminhos/SHA-256 inválidos → `restorable=False` com o motivo em português; usa `after_format.backup_identity` para reconhecer cópias do mesmo backup;
  - `group_copies(linhas)`: junta cópias do mesmo backup (mesma identidade) em pastas diferentes; se a assinatura (lista de caminho, bytes e SHA-256) for diferente, todas ficam sem "restaurar" com o motivo "cópias diferentes"; não altera as linhas de entrada;
  - `verify_backup(manifest, cancelled)`: conferência **opcional** (não é exigida para restaurar), que usa `selective_recovery.verify_complete_manifest` (relê o SHA-256 de cada arquivo); devolve (aprovado, texto); o texto nunca leva caminhos nem a mensagem original do erro (que pode ter o caminho de dentro do backup), só o nome da pasta do backup;
  - janela nova `recovery_center_ui.py` (`show_recovery_center(app, *, folder=None, ...)`): tabela (backup, pasta, data, situação, arquivos, tamanho, pode restaurar?, motivo) e os botões "Escolher pasta", "Conferir integridade", "Restaurar…" e "Fechar"; busca e conferência num `Job`, voltando ao Tk por `WindowTimers.after`; uma janela por vez (`deiconify()` + `lift()`); fechar cancela o `Job`; "Restaurar…" fica desligado se o backup não pode ser restaurado e só chama `show_restore(app, manifest)`, sem `allow_elevated`/`allow_protected`;
  - `app.py`: só o botão "Central de recuperação" no Histórico e o item no menu lateral (fora de `nav_buttons`, que continua com 8 páginas); a central começa pela pasta de destino dos backups, se ela existir; a central de várias cópias (`multi_source_recovery_center*`) ficou como estava;
  - a tela e os erros mostram só o nome da pasta do backup, nunca o caminho completo nem o nome de usuário; a mensagem "procurando" é genérica e não mostra o nome da pasta escolhida (que pode ser o nome de usuário);
  - correções da revisão da PR #77:
    - `st_file_attributes` pode vir `None` num `stat` incompleto no Windows: a checagem de link usa `(getattr(info, 'st_file_attributes', 0) or 0)` em `recovery_center.py`, `after_format.py`, `copy_bench.py` e `game_launchers.py`; em `verify_backup`, a checagem de link fica dentro do tratamento de erro (qualquer falha → "não foi possível abrir", sem quebrar);
    - cada inspeção lê o `manifest.json` uma vez só (até 256 MiB): a lista de arquivos verificados (mesmas regras de `verified_entries`, com `safe_relative`) e a identidade (`after_format.identity_from`) saem do mesmo JSON já lido;
    - manifesto de versão antiga, sem `file_count_expected` ou `bytes_expected`: motivo calmo "Backup de uma versão antiga do aplicativo…" e `restorable=False` (a opção mais segura: sem a contagem planejada não dá para confirmar que está completo; os arquivos continuam guardados);
    - `app.py` não confere mais se a pasta de destino existe na thread da tela: passa o caminho para a central, e a busca (num `Job`) avisa se ela não existir.

### FIX-20261022-launchers-caminho-minusculo · Caminhos dos launchers com a grafia original
- **Status:** `concluído` (branch `auto/FIX-20261022-launchers-caminho-minusculo`).
- **Problema:** a validação Windows da `main` falhou (4 FAIL em `tests/test_game_launchers_p2_05.py`, `DetectionTests`, desde a PR #71): no Windows os caminhos das bibliotecas saíam em minúsculas (`...\appdata\local\temp\...\a\SteamLibrary`), porque `detect_launchers` usava `os.path.normcase(os.path.abspath(root))` como raiz da busca.
- **Aceite:** `path`, `root` e o aviso "incompleta em:" mostram a grafia original; a mesma unidade escrita de dois jeitos é buscada uma vez só e a biblioteca não aparece duplicada; `on_system_drive` continua certo; testes em `tests/test_game_launchers_fix_caminho.py` simulam o Windows trocando `_case_key` por uma versão em minúsculas (pastas sintéticas em `TemporaryDirectory`).
- **Escolhas de design (22/10/2026, a opção mais segura):**
  - função nova `_case_key(path)` = `normcase(abspath(path))`, ponto único de normalização, usada **só para comparar**; `seen_roots` guarda (chave, raiz original) e a busca usa `os.path.abspath(raiz)` sem `normcase`; `add()` deduplica por (launcher, `_case_key(path)`) e fica a primeira grafia achada;
  - `_drive_key` continua com `normcase` (só comparação, nunca mostrado);
  - a grafia mostrada é a que foi passada (ou devolvida por `local_drives()`), sem consultar o disco para descobrir a grafia "verdadeira".

### FIX-P2-11-03 · Salvar o progresso do assistente fora da thread da interface
- **Status:** `concluído` (fatia 1, branch `auto/FIX-P2-11-03-progresso-em-segundo-plano`; ressalva 1 da revisão da PR #76).
- **Problema:** `save_progress` pode esperar até ~2 s tentando trocar o arquivo (espera crescente no Windows) e hoje roda na thread do Tk, então a janela pode congelar nesse tempo.
- **Aceite:** "Feito"/"Pular" gravam o progresso num `Job` (voltando ao Tk por `WindowTimers.after`), sem gravações fora de ordem (a última marcação vence); fechar a janela não perde a última marcação já pedida; testes com dados simulados.
- **Escolhas de design (22/10/2026, a opção mais segura):**
  - em vez de um `Job` por clique, um gravador `ProgressSaver(path, backup, *, save=None)` em `after_format.py` (sem Tk) com **uma única thread de gravação (não-daemon)** por backup: `request(steps)` guarda uma cópia do pedido mais recente e volta na hora; a thread grava sempre o último pedido e junta os intermediários, então nunca há gravação fora de ordem e a última marcação vence; a thread termina quando não há nada a gravar e é recriada no próximo pedido (nunca duas ao mesmo tempo);
  - a gravação continua sendo o `save_progress` de antes (`.parcial` único com `O_EXCL`, `fsync`, `os.replace` com espera, recusa de link); o erro vira o texto fixo de `progress_error_text` (sem caminho completo), lido pela tela com `poll_error()` num `WindowTimers.after(150, ...)` e mostrado na linha `after_format_progress_warning`; a thread de gravação nunca toca no Tk;
  - `close()` só avisa que a janela fechou: **não cancela** a gravação pendente (por ser não-daemon, sair do app também espera essa gravação);
  - revisão da PR #79: `poll_error()` não é mais consumido; diz o erro da **última gravação terminada** e uma gravação posterior que dá certo o limpa. A tela monta a linha de aviso com `progress_warning_text(avisos_da_abertura, erro)`, então volta ao normal quando tudo foi salvo (nunca diz "Não deu para salvar" com tudo salvo);
  - revisão da PR #79: ao reabrir, `load_with_pending(manifest, base, saver)` lê `pending_steps()` **antes** do arquivo; se a gravação terminar entre as duas leituras, o arquivo já tem o pendente e a marcação nova não é trocada pela antiga;
  - o gravador fica em `app.after_format_savers[chave]` (a mesma chave de `window_key`); ao reabrir o mesmo backup, as marcações ainda não gravadas (`pending_steps()`) valem mais que as lidas do arquivo, e a janela nova usa o mesmo gravador (nunca dois gravando o mesmo arquivo); se a gravação falhar, vale o que está no arquivo;
  - nada é apagado.
### P2-10 · Medição de cópia com hardware real (script)
- **Status:** `concluído` (fatia 1, branch `auto/P2-10-medicao-copia`). Falta só o Raphael rodar 1 vez no PC, como pedido na validação do M2.
- Script de benchmark que só lê a origem e só escreve numa pasta de teste, com relatório.
- **Como rodar:** `py -3 scripts\medir_copia.py --origem <pasta> --destino <pasta-pai>` (opcionais: `--max-mib`, `--max-arquivos`, `--blocos 1,4,8`). Ctrl+C para parar.
- **Escolhas de design (21/10/2026, a opção mais segura):**
  - módulo novo `copy_bench.py` (sem Tk, sem imports do projeto, sem PowerShell e sem consulta de hardware): `pick_sample(origem, max_bytes, max_files, cancelled)`, `run_bench(origem, destino_pai, *, chunks=(1, 4, 8), max_bytes=1 GiB, max_files=5000, usage=shutil.disk_usage, clock=time.monotonic, cancelled=None)` e `bench_report(result) -> (texto, dados_json)`;
  - a origem só é aberta com `"rb"`; a amostra usa `os.scandir` em ordem de nome, sem seguir links, junções nem outros reparse points (são pulados e contados); arquivo sozinho maior que o limite fica de fora; a amostra para no primeiro arquivo que passaria do limite (padrão 1 GiB / 5000 arquivos) e no máximo 200 mil itens listados;
  - recusa (sem gravar nada): origem ou destino que é link/junção, destino dentro da origem (ou a mesma pasta), origem dentro do destino, bloco fora de 1–256 MiB, origem sem arquivos e espaço livre menor que **amostra × nº de tamanhos de bloco + 2 GiB** (cada tamanho de bloco grava uma cópia, porque nada é apagado entre as rodadas);
  - só grava numa pasta nova `PCRO-MEDICAO-AAAAMMDD-HHMMSS` criada com `os.mkdir` (se existir, `-2`, `-3`… até 50), com uma subpasta `bloco-<N>MiB` por rodada; as cópias têm nome numérico (`00001.bin`), são abertas com `"xb"` (nunca por cima), gravadas como `.parcial`, com `fsync`, e renomeadas no fim; cada cópia é relida e conferida por SHA-256;
  - um fluxo por vez (um arquivo de cada vez); por tamanho de bloco mede leitura (ler a origem + SHA-256), escrita (gravar + `fsync`) e conferência (reler a cópia + SHA-256); só arquivos conferidos entram nas velocidades (arquivo com erro ou SHA-256 diferente não soma nem tempo nem bytes);
  - cache (revisão da PR #75): não dá para eliminar com segurança sem ferramentas de sistema, então o relatório (texto e JSON, campo `aviso_cache`) diz que a conferência e as rodadas 2 e 3 podem ler da memória e sair otimistas; a sugestão escolhe o bloco pela maior velocidade de **escrita** (a que menos sofre com o cache) e a estimativa para 120 GiB usa a **primeira rodada** (origem fria): cópia (leitura + escrita) mais uma releitura de tudo na velocidade de leitura dessa rodada, no lugar da conferência medida;
  - **nada é apagado**, nem a pasta de medição: o relatório informa o tamanho dela e diz que pode ser apagada à mão;
  - `relatorio.txt` e `relatorio.json` ficam dentro da pasta de medição e não têm caminhos (só letra da unidade, quantidades, tamanhos e velocidades); o script também não repete caminhos nas mensagens de erro;
  - Ctrl+C ou `cancelled` (Event ou função) param no próximo bloco: o arquivo pela metade fica `.parcial` e o relatório diz "interrompida"; cancelado antes de começar a copiar, nada é gravado;
  - se algo falha depois de criada a pasta de medição (subpasta da rodada → relatório "interrompida" com o motivo; relatório que não grava → `BenchStopped` com o nome da pasta), o script diz "MEDIÇÃO INTERROMPIDA" e que a pasta ficou e pode ser apagada à mão, sem mostrar caminho; "MEDIÇÃO NÃO FEITA" só aparece nas recusas, quando nada foi gravado;
  - o relatório diz "nenhum arquivo da origem foi gravado ou apagado" (ler pode atualizar a data de último acesso, que é só metadado);
  - `scripts/medir_copia.py`: só `argparse` chamando `copy_bench`; código de saída 0 (concluída), 1 (interrompida) e 2 (recusada ou erro do sistema).
### P2-09 · Executor multi-disco real — `concluído` (fatias 1, 2a, 2b, 3a, 3b-1 e 3b-2; validado pelo Raphael em 24/10/2026, issue #110)
- **Desbloqueado pelo Raphael em 23/10/2026**, por pedido explícito numa conversa ("pode começar o P2-09"). Mexe nas travas de segurança (`copy_authorized` / `physical_independence_verified`), por isso vai em 3 fatias, cada uma com testador, revisor e validação Windows.
- Base que já existe: `multi_source_fixture_runner.py` (só roda dentro de `test_root`), `multi_source_plan.py`, `multi_source_recheck.py`, `multi_source_targets.py` e `drive_safety_report.py`. Não recomeçar o motor de backup.
- O que **nunca** muda, em nenhuma fatia: `deletions_authorized`, `ready_for_format` e `installation_authorized` continuam `False`. "Não copiar" nunca significa apagar. A origem só é lida.
- **Fatia 1 (executor protegido, só em teste):** `concluído` (branch `auto/P2-09-executor-protegido`). Executor de produção num módulo novo, chamado pelo app só depois das duas travas; nesta fatia ele roda **só** em pastas sintéticas de `TemporaryDirectory`, e o app continua sem chamá-lo. Escopo explícito de origem e destino, recusa de junction/link/reparse em qualquer ancestral, destino nunca dentro da origem (nem o contrário), prévia, cancelamento, retomada, conferência SHA-256 de cada arquivo e relatório em português simples. **O diff não pode tocar em linhas com as travas** (o integrador recusa).
- **Escolhas de design da fatia 1 (23/10/2026, a opção mais segura):**
  - módulo novo `multi_source_executor.py` (sem Tk): `preview_execution(...)` (prévia, não grava nada), `run_protected_copy(...)` e `format_report_pt(result)`; sem `test_root` recusa com "Executor ainda não liberado"; o módulo não lê nem grava nenhuma trava, e o resultado não copia o dicionário do ensaio antigo (`multi_source_fixture_runner`);
  - reaproveita o motor sem reescrever: `backup_core.copy_backup` (uma pasta e um manifesto por destino), `verify_complete_manifest` (relê o SHA-256 de cada arquivo), `recheck_multi_source_preview`, `_any_reparse_ancestor`, `validate_target(..., forbidden=...)` e `_under`;
  - recusa antes da 1ª gravação: caminho relativo, fora da área de teste ou igual a ela, link/junção em qualquer ancestral (inclusive da própria área de teste), destino dentro de uma pasta de origem ou que contenha uma origem; a revalidação roda antes do 1º destino **e antes de cada destino seguinte** (origem mudou no meio → para);
  - retomada: `resume_manifests = {pasta do destino: manifest.json}`, no máximo um por destino, o manifesto tem de estar numa subpasta direta daquele destino; o pedido de retomada é conferido antes da revalidação; origem modificada → recusa sem tocar no manifesto;
  - para no primeiro problema; destinos seguintes ficam `nao_iniciado`; situações: `verificado`, `parcial`, `nao_verificado`; por destino: `verificado`, `nao_verificado`, `interrompido`, `incompleto`, `falha`, `cancelado`, `nao_iniciado`;
  - cancelamento (`threading.Event`) conferido antes de cada destino e repassado à cópia e à conferência; o progresso chega como `progress(numero_do_destino, ...)`;
  - privacidade: o resultado e o relatório nunca levam a mensagem original do erro (pode ter caminho com nome de usuário), só um motivo curto em português; o relatório mostra "Destino N (unidade X:)", nunca caminhos;
  - nenhuma chamada de apagar no módulo (um teste confere o código); `app.py` e as telas `*_ui.py` não importam o executor (outro teste confere).
- **Fatia 2 (prova do disco físico, somente leitura):** `bloqueado` até a fatia 1 estar `concluído`. Descobrir, só lendo, o disco físico por trás de cada letra (número do disco e extents); `physical_independence_verified` só vira `True` quando origem e destino estão em discos físicos diferentes, e qualquer dúvida ou falha do coletor deixa `False`. Testes com dados simulados; a consulta real roda só na validação Windows, com aviso antes. Como toca na linha da trava, **o merge é do Raphael** (issue `precisa-do-raphael`).
- **Fatia 2a (avaliador puro):** `concluído` (branch `auto/P2-09-avaliador-disco-fisico`). Novo `physical_disk_check.py` (sem Tk, sem comandos): `judge_physical_disks(relatorio, discos)` e `format_verdict_pt(resultado)`. Testes: `tests/test_physical_disk_check_p2_09.py`.
  - reaproveita o coletor existente: lê só o resultado de `drive_safety_report.inspect_fresh_drive_safety` (`source_volumes`, `destinations`, `boot_related_logical_disks`) e a lista Get-Disk do mesmo inventário; não roda nenhuma consulta;
  - "independentes" só se, para cada origem e destino: `extent_status` = `observed_logical_only` com 1 número de disco, conferência de partições `logical_match`, destino `requires_review`, nenhum disco do destino igual a um da origem ou de inicialização/EFI, e tipo de ligação NVMe/SATA/ATA/USB (desde a fatia 2b, SCSI/SAS e nome de disco com "virtual", "vmware", "vbox", "qemu" ou "msft" dão `duvida`);
  - dúvida é o padrão: RAID, Spaces, iSCSI, disco virtual, tipo numérico, vazio ou desconhecido, disco ausente ou repetido na lista, lista de inicialização ausente e entrada malformada viram "duvida", nunca erro;
  - disco compartilhado com a origem (por extents ou por partições, ou mesma letra) = "mesmo_disco", mesmo havendo outras dúvidas; destino no disco de inicialização que não é origem = "duvida";
  - veredito geral = o pior entre os destinos (mesmo_disco > duvida > independentes);
  - saída só com letra, veredito e motivo em português simples: sem número de série, modelo nem caminho; o módulo não lê nem grava trava, e `app.py`, as telas `*_ui.py` e `multi_source_executor.py` não o importam (testes conferem).
- **Fatia 2b (ligar o avaliador ao executor e à trava de independência física):** `concluído` na PR (branch `auto/P2-09-trava-independencia-fisica`); **o merge é do Raphael** (toca na trava `physical_independence_verified`). Testes: `tests/test_physical_independence_p2_09.py` (inventário falso em `tests/fake_disks_p2_09.py`).
  - novo `physical_independence.py` (sem Tk, sem comandos próprios): `verify_physical_independence(origens, destinos, *, collector)`; `collector` obrigatório, sem padrão; chama o collector **uma vez**, faz cópia profunda e usa o mesmo retrato em `inspect_fresh_drive_safety` e em `judge_physical_disks`; devolve `physical_independence_verified`, `veredito`, `destinos` e `texto` (`format_verdict_pt`);
  - a trava só fica `True` numa única expressão: veredito `independentes` **e** inventário `fresh_collected` **e** letras de origem e destino iguais às pedidas, na mesma ordem e sem repetição; qualquer erro (collector, inspeção, avaliador ou até a montagem do texto) dá `False` com motivo genérico, sem caminho, série ou modelo;
  - avaliador (opção mais segura, ressalva Hyper-V/VMware): SCSI e SAS saem da lista aceita e dão `duvida`; nome do disco com "virtual", "vmware", "vbox", "qemu" ou "msft" (qualquer caixa) dá `duvida` em qualquer barramento; **escolha extra:** nome ausente ou que não é texto também dá `duvida`; a mensagem é genérica e nunca cita o modelo;
  - executor: `preview_execution` e `run_protected_copy` exigem `disk_collector` (só por nome, sem padrão); letras de origem vêm de `source_volumes` da revalidação e as de destino de `rows[*]['volume']`; a conferência roda antes do 1º destino (falhou → `ValueError` "Cópia recusada…", nada gravado) e antes de cada destino seguinte, junto com a revalidação (falhou → destino `nao_iniciado` com `PROBLEMS['discos']`); a prévia mostra `physical_check` (veredito e texto) sem gravar; o executor só **lê** a resposta, nunca grava a chave da trava e não aceita resposta pronta de fora;
  - relatório: "Isto não prova…" foi trocado pelo texto do último veredito (**escolha extra:** a frase final do avaliador "nada foi copiado…" fica fora do relatório da cópia, para não contradizê-lo; sem conferência, aparece "A conferência dos discos não foi feita.");
  - sem mudança: as linhas `False` de `drive_safety_report.py` e as travas `copy_authorized`, `deletions_authorized`, `ready_for_format` e `installation_authorized`; `app.py` e as telas `*_ui.py` não importam o executor nem a ponte (testes conferem); nenhum script de consulta real foi criado;
  - pendência para a fatia 3: a primeira consulta real dos discos (com aviso e confirmação antes) acontece na tela da fatia 3 e na validação do Raphael.
- **Situação em 24/10/2026:** a fatia 2b está `concluído` (merge do Raphael, PR #95, 23/10/2026). A fatia 3 foi dividida em 3a e 3b: a 3a (autorização de cópia, só em teste) está `concluído` (merge do Raphael, PR #98, 24/10/2026); a 3b (tela, modo real) foi dividida em 3b-1 e 3b-2. As ressalvas da revisão da 3a ficaram no FIX-P2-09-04. A 3b-1 está `concluído` (merge do Raphael, PR #103, 24/10/2026); a 3b-2 está `concluído` (merge do Raphael, PR #106, 24/10/2026); falta a validação dele no Windows. As ressalvas da revisão da 3b-1 ficaram no FIX-P2-09-05; as da revisão da 3b-2, no FIX-P2-09-07. Validado em 24/10/2026 (issue #110).
- **Fatia 3 (cópia real com confirmação):** dividida em 3a e 3b (24/10/2026). Tela com a prévia completa e o botão de confirmar; `copy_authorized` só vira `True` depois do clique do usuário e vale só para **copiar**. **O merge é do Raphael.** Depois, validação: copiar uma pasta de teste do C: para outro disco físico e conferir o relatório.
- **Fatia 3a (autorização de cópia, lógica pura, só em teste):** `concluído` (merge do Raphael, PR #98, 24/10/2026; branch `auto/P2-09-autorizacao-copia`); cria a trava de cópia (nome na linha abaixo). Novo `copy_authorization.py`: `preview_fingerprint`, `authorize_copy`, `consume_authorization`; `run_protected_copy` exige `authorization` (só por nome). Escolhas (opção mais segura): `test_root` continua obrigatório; confirmação só com `True`; validade de 5 min (relógio monotônico); token de uso único; fingerprint sem `free_bytes`; BusType numérico continua sem mapear. Testes: `tests/test_copy_authorization_p2_09.py`.
  - trava criada nesta fatia: `copy_authorized`;
  - a trava só fica `True` numa única expressão: `user_confirmed is True`, schema `pcro-multi-source-executor-preview-v1`, `copies >= 1` (e igual ao número de destinos) e veredito `independentes`; qualquer erro dá `False` com motivo genérico, sem caminho;
  - fingerprint: SHA-256 do JSON canônico com schema, origens, destinos (`path`, `volume`, `resume`), `files_per_copy`, `bytes_per_copy`, `copies` e `physical_check.veredito`; ficam fora `free_bytes`, `texto` e `bytes_total` (este é derivado dos outros);
  - **escolhas extras (opção mais segura):** o módulo guarda, para cada token emitido, o fingerprint e a hora de emissão (num dicionário protegido por lock), e confere os dois contra a autorização recebida, o que recusa token, fingerprint ou hora forjados; a cada token emitido, as entradas com mais de 5 min são descartadas; relógio que andou para trás também recusa; exatamente 5 min ainda vale, 5 min e 1 s não;
  - quando o token é gasto (revisão da PR, regra R-15): `consume_authorization` gasta o token em toda chamada que recebe um token registrado, aceita ou recusada (trava diferente de `True`, prévia diferente, validade vencida, fingerprint ou hora que não conferem); `run_protected_copy` também gasta o token (`discard_authorization`) quando recusa **antes** da conferência da autorização: área de teste inválida, caminhos, revalidação, conferência dos discos ou discos não separados (essa recusa continua vindo primeiro, com a mesma mensagem). O único caso que não gasta nada é uma chamada malformada (erro de programação, `TypeError` levantado pelo Python antes de a função rodar: argumento obrigatório faltando, como `authorization` ou `clock`, ou passado por posição), no executor ou em `consume_authorization`, ou um token que já não está registrado. Depois de qualquer recusa, o usuário refaz a prévia e confirma de novo;
  - executor: depois de `_check` e `_disk_check` (a recusa por discos continua vindo primeiro, com a mesma mensagem), remonta a prévia e consome a autorização antes do 1º byte; falhou → `ValueError` com `REFUSED_CONFIRM` ("Cópia recusada: falta a sua confirmação para esta prévia, ou ela mudou ou expirou. Faça a prévia e confirme de novo. Nada foi gravado."); `test_root` e `_sandbox` não mudaram; o resultado da cópia não leva a chave da trava;
  - sem mudança: `deletions_authorized`, `ready_for_format`, `installation_authorized` e as linhas `False` de `drive_safety_report.py`; `app.py` e as telas `*_ui.py` não importam o módulo nem o executor (testes conferem); o módulo não tem comandos, Tk, leitura de arquivo nem chamada de apagar.
- **Fatia 3b (tela com aviso e confirmação, modo real):** dividida em 3b-1 e 3b-2 (24/10/2026). Aviso e confirmação antes da 1ª consulta real (`disk_inventory`), prévia completa, botão de confirmar e liberação fora da área de teste só com autorização válida; validação do Raphael copiando uma pasta de teste do C: para outro disco físico.
- **Fatia 3b-1 (liberação fora da área de teste e controlador da tela, sem Tk):** `concluído` (merge do Raphael, PR #103, 24/10/2026) (branch `auto/P2-09-liberacao-real-controlador`). A 3b-1 já libera a cópia real como biblioteca (`run_real_copy`), mas nenhuma tela a usa; a validação do Raphael no Windows ficou na 3b-2. Testes: `tests/test_real_copy_flow_p2_09.py` (inventário falso em `tests/fake_disks_p2_09.py`).
  - trava lida (só lida, nunca gravada) pelo controlador nesta fatia: `copy_authorized`;
  - executor: funções novas com outro nome, `preview_real_execution(...)` e `run_real_copy(...)` (mesma assinatura de `run_protected_copy`, sem `test_root`; `disk_collector` e `authorization` só por nome, sem padrão); `preview_execution` e `run_protected_copy` não mudaram (`test_root=None` continua dando "Executor ainda não liberado");
  - `_check` recebe o verificador de caminho (`_inside` na área de teste, `_real_path` no modo real) e o `test_root` que vai para `validate_target`; a lógica não foi duplicada (`_preview_with` e `_run_with` servem os dois modos);
  - `_real_path`: caminho absoluto, sem link/junção em nenhum ancestral, existente (`resolve(strict=True)`) e que não é a raiz de uma unidade, conferido na origem, nas pastas escolhidas, nos destinos e no manifesto de retomada; no modo real o destino passa por `validate_target(..., test_root=None, forbidden=...)`, que recusa C: e sistema que não é Windows;
  - ordem: caminhos e revalidação → nova conferência dos discos → autorização consumida → cópia; toda recusa antes da autorização gasta o token (regra R-15); a chamada malformada (`TypeError` do Python) continua sem gastar nada; a docstring do módulo diz isso;
  - novo `real_copy_flow.py` (sem Tk, sem comandos próprios): `RealCopyFlow(plan, target_preview, *, volume_lookup, usage, disk_collector)`; estados `inicio` → `aviso_consulta` (texto "vou só ler a lista de discos… nada é gravado, formatado nem apagado") → `previa` → `confirmado` → `concluido` ou `recusado`; a consulta só acontece com `confirm_disk_check(True)` (identidade) depois do aviso; qualquer outro valor volta para `inicio` sem consultar;
  - **escolhas extras (opção mais segura):** `run()` sem confirmação válida recusa com a mesma mensagem do executor ("Cópia recusada: falta a sua confirmação…") **sem chamar o executor** (nenhuma nova consulta, nada gravado); nova confirmação gasta o token anterior; `run()` é síncrono e entrega a autorização uma vez só (copiar de novo pede nova prévia); o estado `confirmado` foi acrescentado para a futura tela saber quando ligar o botão de copiar; a prévia mostra só a quantidade de origens (e a letra da unidade, quando há), "Destino N (unidade X:)", arquivos, tamanho e o veredito, sem caminhos (R-07); erro do motor vira um motivo curto escolhido por uma lista fixa (link, raiz, sobreposição, unidade, mudança, discos, confirmação) e nunca repassa a mensagem original; erro inesperado diz "trate a cópia como não verificada" (não promete "nada foi gravado"); o coletor com erro dá dúvida, a prévia abre, mas a confirmação é recusada; raiz de unidade recusada também na origem; BusType numérico continua sem mapear (`duvida`);
  - correções da revisão (f8f2ed9): testes do modo real para chamada malformada (o token continua registrado), caminho inexistente (origem e destino), link do lado da origem, manifesto de retomada (fora do destino, com link, inexistente) e origem modificada depois do plano (regra R-17); no controlador, pasta que sumiu (`FileNotFoundError`/`NotADirectoryError`) vira "A origem ou o destino não existe mais… Nada foi gravado."; `concluido` só quando todas as cópias foram verificadas, senão o estado `incompleto` com mensagem curta e o relatório; se o relatório falhar depois de uma cópia verificada, o resultado fica guardado e aparece um texto curto de sucesso sem relatório; a docstring de `run_real_copy` diz que quem chama nunca mostra `str(erro)`;
  - pendências para a 3b-2 (da revisão): o fluxo ter um `Event` de cancelamento próprio e uma trava de estado (impedir duas chamadas ao mesmo tempo quando a cópia for para um `Job`); trocar a busca por pedaços de texto em `_reason` por exceções com tipo ou constantes do executor;
  - sem mudança: as linhas com o nome das travas em `multi_source_executor.py`, `copy_authorization.py`, `physical_independence.py` e as linhas `False` de `drive_safety_report.py`; `app.py` e as telas `*_ui.py` não importam o controlador nem o executor (testes conferem).
- **Fatia 3b-2 (janela Tk e botão no app):** `concluído` (merge do Raphael, PR #106, 24/10/2026; branch `auto/P2-09-janela-copia-real`). Falta: validação do Raphael copiando uma pasta de teste do C: para outro disco físico. Testes: `tests/test_real_copy_ui_p2_09.py` (os da janela pulam sem Tk; os de código e do fluxo rodam em qualquer sistema).
  - `real_copy_flow.py` (pendências da revisão da 3b-1): `cancel_event` (um `threading.Event` do próprio fluxo) é repassado por `run()` ao executor; `run()` não recebe mais `cancelled` de fora. Trava `_busy` (`threading.Lock` sem espera): enquanto uma etapa roda, qualquer outra chamada (`request_disk_check`, `confirm_disk_check`, `confirm_copy`, `run`, `reset`) devolve `OCUPADO` sem ler discos, sem gravar, sem mudar o estado e sem gastar a confirmação;
  - `cancel()` com uma etapa rodando só aciona o `Event` (devolve `OCUPADO`); o estado final vem do resultado (cópia cancelada termina `incompleto`). Sem nada rodando, `cancel()` volta ao começo e gasta a confirmação, como antes;
  - **escolhas extras (opção mais segura):** cancelar durante a leitura dos discos descarta a prévia que chegar (volta ao começo com "Cancelado. Nada foi gravado."); `request_disk_check()` limpa o `Event` (nova tentativa); `close()` (janela fechada) aciona o `Event`, marca o fluxo como fechado e, se nada estiver rodando, gasta a confirmação na hora; durante a cópia, o executor já gastou a confirmação antes do 1º byte; depois do `close()`, toda etapa é recusada sem fazer nada;
  - o `_reason` (busca por pedaços de texto) e o executor não mudaram nesta fatia: ficaram para o FIX-P2-09-06;
  - nova `real_copy_ui.py`: `show_real_copy(app, *, collector=None, ask_folder=None, volume_lookup=None, usage=None)`; padrão `collector=diagnostics.disk_inventory` (só referenciado; quem chama é o fluxo, e só depois de `confirm_disk_check(True)`); os testes injetam o inventário falso; uma janela por vez (`app.real_copy_dialog`);
  - etapas e botões: "Adicionar origem"/"Adicionar destino" (escolha de pasta) → "Ler discos" (monta a lista de arquivos num `Job`, com `prepare_multi_source_preview(origens, pastas-mãe)` e `preview_multi_source_targets`, e mostra o aviso) → "Sim, pode ler" (lê os discos num `Job` e mostra a prévia) ou "Não" (volta ao começo sem ler) → "Confirmo esta cópia" → "Copiar agora" (num `Job`) e "Cancelar"; cada botão só fica ligado no estado certo; trocar as pastas descarta a prévia e a confirmação;
  - tudo que pode esperar roda num `Job` e volta ao Tk por `WindowTimers.after` (R-10/R-11); fechar a janela cancela o `Job`, chama `flow.close()` e não deixa `after` pendente;
  - a tela mostra só `flow.message`, `preview_text()`, o relatório e textos fixos dela; nunca a mensagem original de um erro (R-07: a tela não guarda exceção nenhuma) nem caminhos (as pastas escolhidas aparecem só como quantidade e letra da unidade);
  - a tela não importa o executor nem o módulo de autorização, não tem nome de trava nem chamada de apagar (testes conferem); `app.py` ganhou só o item "Cópia protegida para outro disco" no menu (`_nav_action`, fora de `nav_buttons`), com import tardio de `real_copy_ui`; o teste antigo de guarda agora permite `real_copy_flow` só em `real_copy_ui.py`.
  - correções da revisão da PR #106 (regra R-18): cada ação da tela ganhou teste de janela próprio: trocar as escolhas ("Adicionar origem", "Limpar escolhas") com a confirmação feita gasta o token e desliga "Copiar agora"; "Cancelar" durante a cópia mostra "Parando…" e depois o relatório (`incompleto`); durante "Sim, pode ler" descarta a prévia; durante a montagem da lista de arquivos mostra "Cancelado" e o aviso não aparece; em `recusado` e `concluido`, "Cancelar" e "Copiar agora" ficam desligados;
  - "Cancelar" logo depois de "Copiar agora" (antes de a etapa pegar a trava): a tela guarda que a pessoa cancelou e, quando a etapa termina, mostra "Cancelado. Nada foi gravado." (o fluxo recusa a cópia sem chamar o executor);
  - o aviso antes da leitura dos discos agora diz que a lista de arquivos das pastas escolhidas e o espaço livre dos destinos já foram lidos (só leitura), e que o aviso é sobre ler a lista de discos;
  - **decisão pendente:** a janela não recusa rodar como administrador (R-13 cobre só restauração); arquivos copiados como admin podem ficar inacessíveis — a decidir com o Raphael na validação. **Decidido na validação do M2: recusar (feito no FIX-P2-09-08).**

### FIX-P2-09-09 · Ressalvas da revisão da recusa como administrador (PR #111)
- **Status:** `concluído` (PR #117, branch `auto/FIX-P2-09-09-ressalvas-admin-copia-real`, issue #112). O executor não mudou; nenhuma linha com o nome de uma trava foi tocada.
- Problema (regra R-19): se o aplicativo passasse a rodar como administrador depois de uma cópia real já feita no mesmo fluxo, a recusa mostrava `MSG_ADMIN`, que termina com "Nada foi copiado nem gravado no destino.", o que podia ser falso.
- `real_copy_flow.py`: nova constante `MSG_ADMIN_INCERTO` (mesmo começo de `MSG_ADMIN`, terminando com "A cópia anterior pode ter ficado incompleta: trate-a como não verificada."; sem "Nada foi"). Em `_guarded`, com `executor_called` `True` a recusa usa `MSG_ADMIN_INCERTO`; com `False`, nada muda (continua `MSG_ADMIN`). O tipo da recusa (`KIND_ADMIN`) e a ordem das conferências não mudaram.
- **Escolhas de design (opção mais segura):** `MSG_ADMIN_INCERTO` é montada a partir de `MSG_ADMIN` (corta antes de " Nada foi"), para as duas nunca divergirem no começo; a escolha do texto fica só em `_guarded` (a tabela `_BY_KIND` continua com `MSG_ADMIN`); `elevation_guard` e a ordem prévia/janela não mudaram.
- Testes: `tests/test_real_copy_admin_p2_09.py` — cópia sem administrador até o fim e depois administrador → `MSG_ADMIN_INCERTO`, sem "Nada foi", executor não chamado de novo; recusa antes do executor continua `MSG_ADMIN` com `executor_called` `False`; texto simples e seguro (sem caminho, sem nome de usuário, sem "Nada foi"); janela (R-18, pula sem Tk): como administrador, "Limpar escolhas" mantém o status de cópia desligada, "Ler discos" desligado, nenhum disco lido e nada gravado.

### FIX-P2-09-08 · Recusar a cópia real como administrador
- **Status:** `concluído` (branch `auto/FIX-P2-09-08-recusar-admin-copia-real`). Nenhuma linha com o nome de uma trava foi tocada; o executor não mudou.
- Origem: validação do M2 (pedido `marco-20261024-p2-09-copia-real`, aprovado pelo Raphael), 25/10/2026. A pergunta "a janela de cópia protegida real deve recusar rodar como administrador, como já faz a restauração?" ficou com a proposta dos agentes: **sim**, porque arquivos copiados como administrador podem ficar sem acesso para o usuário normal.
- `real_copy_flow.py`: nova função `process_elevated(probe)` (só repassa para `elevation_guard.is_process_elevated`, sem detecção nova) e novo parâmetro `elevated_probe=` do `RealCopyFlow` (padrão `None` = conferência real). `request_disk_check`, `confirm_disk_check`, `confirm_copy` e `run` conferem **antes** de qualquer outra coisa: elevado → `CopyRefusal(KIND_ADMIN, MSG_ADMIN)` → estado `recusado` com `MSG_ADMIN`, sem ler discos, sem autorizar, sem chamar o executor (`executor_called` continua `False`) e com o token gasto.
- `copy_refusal.py`: novo `KIND_ADMIN = 'administrador'` em `KINDS`; o `_reason` acha `MSG_ADMIN` pela tabela `_BY_KIND` (não depende do texto). O teste antigo `test_fix_p2_09_06` passou a ignorar só esse `kind` novo na comparação com as mensagens convertidas.
- `real_copy_ui.py`: com o aplicativo aberto como administrador a janela mostra o aviso `ADMIN_TEXT` (em negrito, abaixo da introdução), a linha de status diz que a cópia está desligada e "Ler discos" fica sempre desligado (e o comando não faz nada mesmo se for chamado). A janela usa `rcf.process_elevated` (não importa módulo novo) e passa o mesmo probe ao fluxo: se a tela falhar, o fluxo recusa sozinho (defesa dupla).
- **Escolhas (opção mais segura):** a conferência roda de novo em cada etapa (não só ao abrir), para recusar mesmo que a resposta mude no meio; um probe que falha (exceção) conta como "não elevado", que é o comportamento já documentado do `elevation_guard` (a conferência é só de leitura e informativa; o Windows continua barrando o que o usuário normal não pode fazer); "Adicionar origem/destino" continuam ligados porque só escolhem pastas, sem ler nada nem gravar.
- Testes: `tests/test_real_copy_admin_p2_09.py` — elevado recusa antes de ler discos e antes de qualquer gravação (destinos vazios, executor e prévia nunca chamados); elevado depois da prévia recusa antes de autorizar; elevado antes de copiar recusa, gasta o token e não chama o executor; não elevado → fluxo igual ao de hoje (copia e confere, probe consultado nas 4 etapas); probe com exceção → não elevado; padrão usa o guard real (trocado no teste); recusa tem `kind`; textos simples e sem caminho; janela (pula sem Tk): aviso visível e "Ler discos" desligado como administrador, sem aviso quando não é. Os testes antigos da tela e do fluxo agora passam `elevated_probe` "não elevado", para não depender de como o teste foi aberto. Nova regra R-20 em `docs/REGRAS.md`.

### FIX-P2-09-07 · Ressalvas da revisão da janela de cópia real (PR #106)
- **Status:** `concluído` (branch `auto/FIX-P2-09-07-ressalvas-janela-copia`). Nenhuma linha com o nome de uma trava foi tocada; o executor e o `_reason` não mudaram.
- Problema: com "Cancelar" clicado durante a cópia, se a etapa terminava com erro (recusa depois de chamar o executor, ou erro inesperado da etapa), a janela mostrava "Cancelado. Nada foi gravado." mesmo podendo já ter gravado algo.
- `real_copy_flow.py`: novo `executor_called` (vira `True` logo antes de `run()` entregar a cópia ao executor e nunca volta a `False`), novo texto `CANCELADO_INCERTO` ("Cancelado. A cópia pode ter ficado incompleta: trate-a como não verificada.") e nova função pura `cancel_text(flow)`: dá "Cancelado. Nada foi gravado." só sem fluxo ou quando `executor_called is False`; qualquer outro valor dá o texto incerto. `cancel()`, `close()` e as etapas recusadas depois de fechar a janela usam essa função.
- `real_copy_ui.py`: os três lugares que mostravam "Cancelado" (fim de uma etapa depois de "Cancelar", "Cancelar" sem etapa rodando e cancelamento da montagem da lista de arquivos) usam `cancel_text`; se a cópia terminou `concluido` ou `incompleto`, continua aparecendo o relatório.
- **Escolhas (opção mais segura):** `executor_called` não é zerado por `reset()`/`request_disk_check()`: depois que o executor foi chamado, o mesmo fluxo nunca mais promete "nada foi gravado"; valores que não sejam exatamente `False` contam como "pode ter gravado".
- Testes: `tests/test_real_copy_ui_p2_09.py` — função pura e fluxo sem Tk (executor com erro, `incompleto` e `verificado` → texto incerto; cópia recusada antes do executor → "Nada foi gravado"); janela (pula sem Tk): "Cancelar" durante a cópia com erro do executor e com erro inesperado da etapa não mostra "Nada foi gravado"; subteste "Adicionar destino" no teste de trocar escolhas (regra R-18). Nova regra R-19 em `docs/REGRAS.md`.
- Fora deste FIX: renomear o botão "Ler discos", o `_reason` (FIX-P2-09-06) e a decisão sobre rodar como administrador (do Raphael).

### FIX-P2-09-06 · `_reason` por exceções com tipo (ressalva da 3b-1)
- **Status:** `concluído` (branch `auto/FIX-P2-09-06-reason-com-tipo`). Nenhuma linha com o nome de uma trava foi tocada; as mensagens curtas mostradas e a ordem das recusas não mudaram.
- Trocar, em `real_copy_flow._reason`, a busca por pedaços de texto da mensagem do executor por exceções com tipo (ou constantes do executor), sem mudar as mensagens curtas mostradas nem a ordem das recusas. Nenhuma linha com o nome de uma trava pode mudar.
- Novo `copy_refusal.py` (não importa nada do projeto, então não cria import circular): `CopyRefusal(kind, mensagem)`, subclasse de `ValueError`, e as constantes `KIND_CONFIRM`, `KIND_DISKS`, `KIND_UNIDADE`, `KIND_RAIZ`, `KIND_LINK`, `KIND_SOBREPOR`, `KIND_MUDOU` (lista em `KINDS`). O texto de cada recusa ficou idêntico, e quem já fazia `except ValueError` não mudou.
- Recusas convertidas (só as que o `_reason` já reconhecia pelo texto): `multi_source_executor.py` (confirmação, discos, raiz da unidade nos dois lugares, "Destino precisa ser uma pasta existente", sobreposição, "Quantidade de destinos mudou", "Destino divergente"); `selective_recovery.py` (link/junção, destino inexistente, destino no C: ou fora do Windows, sobreposição); `multi_source_recheck.py` (diagnóstico alterado, fonte desapareceu, fonte modificada, unidades de origem mudaram, destino ou unidade mudou).
- `_reason`: depois de `FileNotFoundError`/`NotADirectoryError` e da checagem de `ValueError` (sem mudança), uma `CopyRefusal` com `kind` conhecido escolhe o motivo pela tabela `_BY_KIND`; sem `kind` conhecido (ou `ValueError` comum) cai na busca por texto antiga, mantida como reserva.
- **Escolhas (opção mais segura):** cada `kind` dá exatamente o motivo que o texto daquela mensagem já dava (teste compara os dois caminhos para todas as mensagens convertidas); `kind` que não seja texto conhecido (inclusive `None` ou número) cai na busca por texto sem erro; erro que não é `ValueError` continua "erro inesperado", mesmo com um atributo `kind`.
- Ficaram na busca por texto (não convertidos): a recusa de `multi_source_recheck.py` que fica numa linha com o nome de uma trava (o texto dela já caía em `MSG_PREVIA`); "Arquivo de backup ausente, alterado ou SHA-256 divergente" (`verify_complete_manifest`) e os `OSError` de `backup_core.py`, porque o executor os captura durante a cópia e eles não chegam ao `_reason`.
- Ressalva da revisão da PR #108 ("Nada foi gravado" só quando é verdade): conferido que, depois de o executor ser chamado, nenhuma recusa mostrada promete isso indevidamente (erros durante a cópia viram `incompleto` ou "erro inesperado"; as recusas tipadas que escapam do executor acontecem antes do 1º byte). Nada precisou ser corrigido.
- Testes: `tests/test_fix_p2_09_06.py` — para cada `kind`, o mesmo motivo de antes; `ValueError` comum ainda usa o texto; `kind` desconhecido cai no texto/`MSG_PREVIA`; caminhos reais do executor com pastas temporárias levantam o `kind` certo (raiz, sobreposição, não é pasta, C:, link, origem modificada, revalidação, discos e confirmação); fluxo sem Tk: recusas antes do executor têm `executor_called` `False` e "Nada foi gravado"; depois de o executor gravar algo e falhar (vários tipos de erro, inclusive na revalidação do 2º destino), a mensagem e o texto de cancelar não prometem "Nada foi gravado".

### FIX-P2-09-05 · Ressalvas da revisão da liberação real (PR #103)
- **Status:** `concluído` (branch `auto/FIX-P2-09-05-ressalvas-liberacao-real`). Nenhuma lógica de segurança mudou; nenhuma linha com o nome de uma trava foi tocada.
- `_any_reparse_ancestor` (`selective_recovery.py`) agora usa `(getattr(info, 'st_file_attributes', 0) or 0)` (regra R-12): um atributo `None` não vira mais `TypeError` ("erro inesperado") e não é tratado como link. Testes sintéticos em `tests/test_fix_p2_09_05.py`: `lstat` falso com `None` não recusa; com o bit de link recusa com "Link/junção proibido"; pelo modo real (`preview_real_execution`, com o `os` trocado só dentro de `selective_recovery`), o `None` não vira erro.
- Fora do caminho do modo real, outros módulos ainda usam o padrão antigo (ex.: `multi_backup_destinations._resolved_folder`, `backup_core.is_reparse`); ficaram de fora deste FIX para não aumentar o escopo.
- `test_refusals_become_short_reasons`, caso "sem invólucro": `volume_of` de `selective_recovery` é trocado para responder `C:`, então a recusa não depende mais de o TEMP estar no C:.
- `test_drive_root_is_refused_as_target_and_source`: comentário dizendo que `anchor` é a raiz da unidade do TEMP, que o teste só espera a recusa e que nada é gravado nela.
- Fora deste FIX: `_reason` por pedaços de texto (pendência da 3b-2) e a docstring longa (não identificada com certeza; mantida para não perder o que a R-15 exige). A regra R-18 proposta não foi registrada porque o texto dela não está em nenhum arquivo.
- Status escrito sem nome de trava (R-16).

### FIX-P2-09-04 · Ressalvas da revisão da autorização de cópia (PR #98)
- **Status:** `concluído` (branch `auto/FIX-P2-09-04-ressalvas-autorizacao`). Nenhuma lógica mudou; nenhuma linha com o nome de uma trava foi tocada.
- Texto de quando o token é gasto (regra R-15): as docstrings de `consume_authorization` e de `multi_source_executor.py` agora dizem que uma chamada malformada (`TypeError`: argumento faltando ou passado por posição) não gasta o token; novo teste `test_malformed_call_does_not_use_the_token_up` prova isso e que o mesmo token ainda copia depois.
- O teste de autorização vencida troca só o relógio do executor (`patch.object(executor, 'time', ...)`), não mais `time.monotonic` do processo inteiro; o que ele prova não mudou.
- `docs/REGRAS.md`: o contador da poda passou a 2 (R-14 e R-15 desde a lista inicial de 23/10/2026); nenhuma regra mudou.

### FIX-P2-09-03 · Ressalvas da revisão da ponte de discos (PR #95)
- **Status:** `concluído` (branch `auto/FIX-P2-09-03-ressalvas-trava-disco`). A condição que deixa a resposta positiva não mudou; só ficaram mais claros os motivos das recusas.
- Dois destinos na mesma unidade (ex.: `T:\a` e `T:\b`, ou `T:` e `t`): a recusa continua e agora diz o motivo: "Dois ou mais destinos ficam na mesma unidade (T:). Escolha cada destino numa unidade diferente." (helper `_repeated_letter`, chamado antes de `_letters`; o collector nem é chamado).
- Inventário que não foi coletado agora: recusa própria ("A conferência dos discos não foi feita agora, na hora…"), com veredito `duvida` e sem destinos, mesmo se o avaliador disse `independentes`. E se a resposta final ficou negativa com veredito `independentes`, a ponte devolve a recusa genérica (defesa extra, que hoje não chega a ser usada): um resultado negativo nunca afirma que os discos são separados nem mostra o título "Discos separados"; negações como "nada foi considerado separado" são permitidas (regra R-14).
- Collector ausente ou que não é chamável (`None`, `'x'`): recusa com "O app não recebeu a conferência dos discos. Por segurança, a cópia foi recusada para estes destinos.", sem exceção. No executor, `disk_collector=None` dá prévia com `duvida` e a cópia é recusada com "Cópia recusada…" antes do 1º byte (sem mudança de código no executor).
- Texto do barramento: "disco de servidor" saiu de `MSG_BUS` e `MSG_SOURCE_BUS`; agora é "(por exemplo RAID, disco virtual ou tipo desconhecido)".
- **Escolha de design (coordenador, opção mais segura):** os códigos numéricos de BusType (ex.: 17 = NVMe, 11 = SATA) **não** foram mapeados, porque isso faria mais casos chegarem a "independentes" e afrouxaria a conferência. Um teste documenta que número, texto numérico (`'11'`), `True`, vazio ou ausente continuam `duvida`.
- **Pendência para a fatia 3:** decidir o mapeamento dos códigos numéricos de BusType com a consulta real dos discos (o merge da fatia 3 é do Raphael).
- Testes: `tests/test_physical_independence_p2_09.py` (mesma unidade na ponte e no executor, inventário não novo, collector ausente, BusType numérico, texto antigo fora do código).

### FIX-P2-09-01 · Ressalvas da revisão do executor (PR #85)
- **Status:** `concluído` (branch `auto/FIX-P2-09-01-executor-ressalvas`).
- Cancelar durante a conferência deixa o destino `cancelado` ("conferência cancelada ... pode ser conferida de novo"), nunca "arquivo diferente" nem "pode ser retomado" (o manifesto já está concluído e não se retoma).
- Revalidação antes do 2º destino em diante trata também erro de disco (ex.: desconectado): para, o destino fica `nao_iniciado` e o motivo é genérico ("a origem ou o destino mudou desde a prévia, ou um disco ficou inacessível").
- Novo teste: origem muda depois do destino 1 conferido → destino 2 `nao_iniciado` com motivo, nada gravado nele.
- A área de teste não pode ser a raiz de uma unidade e precisa ficar estritamente dentro da pasta temporária do sistema (escolha mais segura).
- Plano sem a lista de pastas escolhidas recusa com mensagem em português, sem erro interno.

### FIX-P2-09-02 · Ressalvas da revisão do avaliador (PR #87)
- **Status:** `concluído` (branch `auto/FIX-P2-09-02-avaliador-ressalvas`).
- Lista de discos de inicialização vazia agora dá `duvida`: num Windows em uso sempre há disco de inicialização, então a ausência não é prova.
- Status do destino: só `requires_review` é aceito; status ausente, desconhecido ou `blocked` dá `duvida` (escolha mais segura).
- Conferência com as partições: só `logical_match` é aceito; `limited_match` passa a dar `duvida` (igual ao `partition_extent_crosscheck.py`).
- SCSI/SAS foram aceitos nesta correção, mas discos virtuais de Hyper-V/VMware podem aparecer como SCSI/SAS. **Revisto na fatia 2b:** SCSI/SAS e nomes de disco virtuais ("virtual", "vmware", "vbox", "qemu", "msft") agora dão `duvida`.

### FIX-P2-08-01 · Central: motivo cortado na tabela
- **Status:** `concluído` (branch `auto/FIX-P2-08-01-motivo-completo`; achado na validação do M2 no PC do Raphael, 23/10/2026).
- Na janela "Central de recuperação", a coluna do motivo fica cortada à direita e o usuário precisa rolar a tabela para ler por que um backup não pode ser restaurado.
- Pronto quando: ao selecionar uma linha, o motivo completo aparece num texto abaixo da tabela (com quebra de linha), sem rolagem lateral; a coluna continua existindo. Só leitura, sem mudar regras de "pode restaurar".
- Sem linha selecionada, o espaço mostra "Nenhum backup selecionado".
- Teste: a função que monta o texto do motivo (sem Tk) devolve o texto completo, sem caminhos.
- Escolhas de design (feitas): o texto (`recovery_center.reason_detail_text`) usa só "pode restaurar" e o motivo, **sem o nome da pasta** (ele pode ter o nome de usuário); é um rótulo só de leitura (`ttk.Label`), não um campo editável; a quebra de linha acompanha a largura da janela (mínimo de 200 px); a coluna "Motivo" da tabela foi mantida. Testes em `tests/test_recovery_center_fix_p2_08_01.py`.

### P2-08 · Fatia 2 — Restaurar só os arquivos conferidos de um backup com poucos erros
- **Status:** `concluído` (branch `auto/P2-08-restaurar-conferidos`; pedido do Raphael na validação do M2, 23/10/2026).
- Problema: os backups reais de 20/10 tiveram 1 e 23 arquivos com erro (arquivo removido pelo Defender, arquivos travados por programas abertos). Por isso a Central marca todos como "Pode restaurar: Não", mesmo com 99,99% conferido, e o usuário fica sem saída pelo app.
- Pronto quando: a Central mostra, para um backup parcial, quantos arquivos foram conferidos e quantos falharam; um botão "Restaurar só os conferidos…" pede uma confirmação separada que diz quantos arquivos ficam de fora e leva ao fluxo de restauração já existente, **sempre numa pasta nova** (não oferece "Colocar no lugar original" nesse caso).
- Regras de segurança (as mais seguras): só entram arquivos com `verified: true` e SHA-256 no manifesto, e cada um é conferido de novo ao restaurar; backup sem lista de arquivos legível, com manifesto inválido ou com cópias diferentes continua recusado; nada é apagado nem sobrescrito; o relatório diz em português quantos arquivos ficaram de fora e por quê, sem caminhos com nome de usuário.
- A exceção vale **só** para o botão "Restaurar só os conferidos…": a coluna "Pode restaurar?" e o botão "Restaurar…" continuam com a regra de hoje.
- Fica de fora (escolha mais segura): arquivo `verified: true` sem SHA-256; manifesto antigo sem `verified` por arquivo → a restauração parcial é recusada inteira.
- Testes com backups sintéticos em `TemporaryDirectory`, um para cada regra:
  - backup parcial com 1 arquivo faltando → restaura só os outros;
  - a confirmação diz quantos arquivos ficam de fora;
  - o fluxo parcial não oferece "Colocar no lugar original";
  - manifesto inválido, manifesto antigo ou "cópias diferentes" → recusa;
  - arquivo alterado depois do backup (SHA-256 diferente) nunca é restaurado;
  - o relatório não leva caminhos com nome de usuário.
- **Escolhas de design (23/10/2026, a opção mais segura):**
  - o motor de restauração **não mudou**: `restore_selected` já usa só os `verified: true` com SHA-256 válido, confere o SHA-256 na leitura, no `.partial` e depois de publicar, grava sempre numa pasta nova (`new_restore_folder`) e recusa destino ocupado;
  - `recovery_center.partial_restore_info(doc, entradas)` → (liberado, conferidos, falharam, motivo): libera **só** `status == 'parcial_com_erros'` (backup interrompido ou em andamento deve ser terminado/retomado, não restaurado pela metade); exige `file_count_expected` e `bytes_expected` inteiros; todo item da lista precisa ter `verified` (faltou em um → manifesto antigo, recusa inteira); `verified: true` sem SHA-256 válido → recusa; precisa de 1 ≤ conferidos < esperados e tamanho somado ≤ `bytes_expected`; falharam = esperados − conferidos;
  - `inspect_backup` ganhou `verified_files`, `failed_files`, `partial_ok` e `partial_reason`, **sem mudar** `restorable` nem `reason` (a coluna "Pode restaurar?" e o botão "Restaurar…" seguem a regra da fatia 1); toda recusa que já existia (link, JSON estragado, schema, caminhos/SHA-256 inválidos) também deixa `partial_ok=False`; `group_copies` com "cópias diferentes" também desliga o parcial;
  - a lista `errors` do manifesto (que tem caminhos com nome de usuário) **nunca é mostrada**: a tela só diz quantos falharam;
  - confirmação em **dois passos**: o botão "Restaurar só os conferidos…" pede uma confirmação separada (`partial_confirmation_text`: quantos entram, quantos ficam de fora e por quê, "sempre numa pasta NOVA", "conferido de novo pelo SHA-256", "nada é apagado nem sobrescrito") e depois a janela de restauração pede a confirmação normal da pasta de destino;
  - a janela abre com `show_restore(..., only_verified=True)`, que **relê o manifesto** ao abrir (`load_partial_keys`/`load_partial_info`); se ele mudou e não passa mais, avisa e não lista nada; os conferidos já vêm marcados; os botões "Colocar no lugar original" e "Retomar colocação interrompida" e a caixa de Program Files **não são criados** (um teste `ast` confere que `staging_info`, `plan_placement` e `run_placement` só existem fora desse modo); continua por `guarded_restore_selected`, sem `allow_elevated`; "Retomar restauração interrompida" continua disponível (só aceita chaves da lista carregada);
  - arquivo alterado no backup depois de feito (SHA-256 diferente) para a restauração inteira com erro (comportamento do motor, sem mudança), sem deixar o arquivo nem `.partial` no destino;
  - o resultado (`partial_report_text`) mostra só quantidades e o **nome** da pasta nova (nunca o caminho); se algum arquivo restaurado parecer senha exportada do navegador, o aviso diz só quantos, sem caminho;
  - a Central mostra "Conferidos: X · Falharam: Y" numa linha separada abaixo do motivo (`counts_text`); `reason_detail_text` não mudou;
  - testes em `tests/test_recovery_center_p2_08_fatia2.py` (backups sintéticos em `TemporaryDirectory`; um deles feito pelo `copy_backup` real com uma falha simulada na leitura).

### ✅ Validação do Raphael — M2
Issue "Validar M2": rodar o benchmark e abrir a central de recuperação com um backup real (somente leitura).
- A issue "Validar M2" pode ser aberta já, para o que está pronto (benchmark e central). O P2-09 ganha uma validação própria no fim da fatia 3.
- **Validado pelo Raphael no PCRO Monitor em 24/10/2026 (issue #110)**, pedido `marco-20261024-p2-09-copia-real`. A pergunta sobre rodar como administrador ficou com a proposta dos agentes (recusar): FIX-P2-09-08.

---

## Marco M3 — Otimização universal (carro-chefe)  ← ATUAL
### P3-01 · Perfil de hardware (somente leitura) — `concluído` (fatias 1 e 2)
- CPU, GPU, RAM (velocidade e dual channel), discos, notebook ou desktop, Windows.
- Classificação em básico / intermediário / gamer / alto desempenho / notebook.
- Testes com dados simulados.
- **Fatia 1 — `concluído`** (branch `auto/P3-01-perfil-hardware`): novo `hardware_profile.py` (funções puras, sem comandos) monta o perfil a partir do que `inspect_pc()` já lê; `inspect_pc()` devolve `profile` (também fora do Windows) e o JSON exportado leva o perfil; a aba "1 Diagnóstico" mostra a seção "PERFIL DO SEU PC". Testes: `tests/test_hardware_profile_p3_01.py`.
  - Escolhas de design (as mais seguras): nenhuma consulta nova ao sistema; sem CPU ou RAM legível a classe é "indefinido"; notebook vem antes da potência (PCSystemType 2 = notebook, 1/3 = desktop, ausente ou outro = "desconhecido", nunca "desktop"); limites fixos: alto desempenho = GPU dedicada + 16 threads + 32 GiB; gamer = GPU dedicada + 6 núcleos + 16 GiB; intermediário = 4 núcleos + 8 GiB; básico = o resto.
  - GPU dedicada pelo nome: GeForce, RTX, GTX, Quadro, Radeon RX/Pro e Arc A/B contam; "Microsoft Basic Display Adapter", UHD/HD Graphics, Iris, Vega, "Radeon Graphics" e nome vazio não; nome desconhecido = não identificado.
  - Dual channel nunca é "confirmado" nesta fatia: 2 ou mais módulos de mesma capacidade = "provável (não confirmado)"; 1 módulo = "não (1 módulo)"; tamanhos diferentes = "não confirmado".
  - Privacidade: o perfil não guarda número de série, nome do PC, usuário nem caminhos (textos com cara de caminho são descartados); placa-mãe e BIOS ficam fora. Entrada malformada (lista/dicionário, texto, None, negativos, bool, NaN) vira "desconhecido", nunca erro. Nada de BIOS.
- **Fatia 2 — `concluído`** (branch `auto/P3-01-perfil-hardware-fatia2`): discos (NVMe/SSD/HDD/externo ou virtual/desconhecido), gabinete e bateria (notebook x desktop) e dual channel confirmado (DeviceLocator/BankLabel). "Analisar este PC" agora pede confirmação antes de qualquer consulta. Testes: `tests/test_hardware_profile_p3_01_fatia2.py`.
  - Escolhas de design (26/10/2026, as mais seguras):
    - **não** reaproveitar `diagnostics.disk_inventory` (roda mais comandos e lê número de série); em vez disso, uma consulta só de leitura `Get-PhysicalDisk | Select-Object MediaType,BusType,Size`; novas consultas `Win32_SystemEnclosure` (só `ChassisTypes`) e `Win32_Battery` (só `BatteryStatus`); a consulta da RAM passa a trazer `DeviceLocator` e `BankLabel`; fora do Windows continua sem nenhum comando;
    - discos: barramento USB (7), virtual (15) ou Spaces (16) = "externo/virtual" (vem antes de tudo); NVMe (17 ou "NVMe") = NVMe; MediaType 4/"SSD" = SSD; 3/"HDD" = HDD; qualquer outro (0, SCM, vazio, valor estranho) = "desconhecido", nunca SSD; o perfil guarda só `type`, `bus` (nome curto de uma lista fixa) e `size_gib`; tamanho abaixo de 0,05 GiB = não disponível; sem discos, `disks` entra em `unknown`;
    - notebook: PCSystemType 2, **ou** gabinete 8/9/10/14/30/31/32, **ou** bateria presente (um nobreak listado como bateria também vira notebook: erra para o lado mais cuidadoso); desktop exige as três provas: PCSystemType 1 ou 3, **todos** os gabinetes em 3/4/5/6/7/15/16/35/36 e o Windows não listar nenhuma bateria (consulta respondida vazia); se a consulta de bateria falhou ou veio estranha, "desconhecido"; por isso um PC com só o PCSystemType 1 deixou de ser "desktop" (o teste da fatia 1 que só roda no Windows ganhou gabinete e bateria simulados);
    - dual channel "sim (confirmado)" só com 2+ módulos do mesmo tamanho **e** todos com "Channel X"/"ChannelX" em DeviceLocator ou BankLabel, em pelo menos 2 canais diferentes; "BANK 0/1", "DIMM 1/2", canal repetido (A/A) ou algum módulo sem canal = "provável (não confirmado)"; os rótulos nunca entram no perfil;
    - confirmação: `hardware_profile.SCAN_CONFIRMATION` (texto fixo) num `messagebox.askyesno`; "Não" não roda nada e só avisa "Análise cancelada. Nada foi lido nem alterado."
### P3-03 · Registro de alterações e "desfazer tudo" — `pronto`
- Diário de cada alteração, desfazer individual e desfazer tudo, ponto de restauração antes de cada lote (simulado nos testes).
- Nenhum ajuste passa por fora do diário.
- **Fatia 1 — `concluído`** (branch `auto/P3-03-diario-alteracoes`): novo `change_journal.py` (sem Tk, sem comandos) com o diário (`pcro-journal-1`, gravação atômica), aplicar lote com ponto de restauração antes (função injetável), desfazer um item, desfazer tudo em ordem inversa e recuperação de alteração interrompida. Testes: `tests/test_change_journal_p3_03.py`.
  - Escolhas de design (27/10/2026, as mais seguras): sem ponto de restauração o lote é recusado; desfazer só se o valor atual for o que o app gravou (nunca sobrescreve mudança feita por outro programa); "desfazer tudo" para na primeira falha; pendência ou estado desconhecido bloqueia novos lotes; diário ilegível, de schema errado ou que seja link bloqueia tudo; só valores simples, sem caminhos; entradas nunca são apagadas.
  - Detalhes do desenvolvedor: o adaptador recebe a chave (`read(key)`, `apply(key, valor)`, `revert(key, valor)`), porque um mesmo tipo pode ter vários ajustes; a chave é um nome simples (letras, números, `_ . -`), nunca um caminho; a comparação é estrita (`True` não é igual a `1`); se desfazer um item do lote com falha não se confirmar, ele vira "desconhecido" e bloqueia novos lotes; `recover_interrupted` só lê, nunca aplica nem desfaz.
- **Fatia 2a — `concluído`** (branch `auto/P3-03-tela-alteracoes`): o plano de energia passa pelo diário, com desfazer item a item. `optimization_engine.py` ganhou `PowerPlanAdapter` (tipo `power_plan`, chave `active_scheme`), `create_restore_point` e `legacy_power_pending`; a aba "Energia reversível" usa o diário `otimizacao-diario.json` numa thread, com retorno por `WindowTimers`. Testes: `tests/test_change_journal_p3_03_fatia2.py`.
  - Escolhas de design (28/10/2026, as mais seguras): o adaptador só roda `powercfg /setactive` com um GUID que esteja na lista atual do Windows (aplicar e desfazer); o ponto de restauração só conta como criado se o maior número de sequência aumentou, com descrição fixa (o texto do diário é ignorado), e nunca liga a Proteção do sistema; sem administrador ele devolve "não criado" sem rodar nada.
  - Na tela: sem administrador a troca é recusada antes de perguntar, e o texto explica como abrir o app com "Executar como administrador" (o app nunca pede elevação); desfazer funciona sem administrador e não cria ponto novo; escolher o plano que já está ativo não cria ponto nem entrada; "Desfazer minha última mudança" desfaz só a última troca aplicada (clicar de novo desfaz a anterior); diário ilegível desliga Aplicar e Desfazer; abrir o painel só lê arquivos, não roda comando; se uma troca ficou interrompida, o app só confere (`recover_interrupted`) antes do próximo lote.
  - Registro antigo (`otimizacao-energia-reversao.json`, `pcro-power-1`): se estiver aplicado, interrompido ou ilegível, novas trocas ficam bloqueadas e aparece "Desfazer alteração antiga". Só o caso "aplicado" roda `revert_power_plan` (que marca o arquivo como desfeito); interrompido ou ilegível só mostram o que conferir e o bloqueio continua (nenhum botão para "liberar" à força). O arquivo antigo nunca é apagado nem convertido. `safe_change_power_plan` continua no motor, mas a tela não usa mais.
  - Textos sem caminhos nem mensagens cruas do Windows (R-07): a lista de planos que falha mostra um texto fixo.
  - **Risco para o "Validar M3":** o Windows não cria um ponto de restauração novo se já criou um nas últimas 24 horas (regra do próprio Windows). Nesse caso o número não sobe e a troca é recusada, com a explicação na tela. Na validação, pode ser preciso esperar 24 h entre testes de troca, ou usar um PC sem ponto recente. A Proteção do sistema precisa estar ligada no disco do Windows (o app não liga).
- **Fatia 2b — `pronto`**: subaba "Alterações feitas" (lista do diário com `summary_lines`) + botão "Desfazer tudo" (`undo_all`), na aba de otimização.
### P3-06 · BIOS: só orientação — `pronto` (depois de P3-01)
- Verifica XMP/EXPO, Resizable BAR e versão da BIOS, só lendo.
- Mostra o passo a passo por fabricante. **Nunca altera.**
### P3-07 · Check-up de segurança (somente leitura) — `pronto` (depois de P3-01)
- **Pedido do Raphael em 23/10/2026.** Procura sinais de minerador escondido e de programas suspeitos. **Não é antivírus:** o app nunca apaga, nunca encerra processos, nunca muda o Defender e nunca coloca nada em quarentena. Se achar algo, explica e recomenda a "Verificação offline" do Defender e uma segunda opinião (Malwarebytes, só do site oficial).
- **O que olha (só leitura):**
  - programas que abrem com o Windows (chaves `Run`/`RunOnce` e pastas de Inicialização);
  - tarefas agendadas que não são da Microsoft;
  - processos com o caminho de onde rodam (nome de sistema, como `svchost.exe`, rodando fora de `System32` = suspeito; executável em pasta temporária ou `AppData` = atenção);
  - situação do Defender: proteção em tempo real ligada e **exclusões** (malware costuma se excluir); se ler as exclusões exigir administrador, dizer que não foi possível conferir, sem pedir elevação;
  - uso de CPU e GPU com o PC parado, medido por alguns minutos (uso alto sem nenhum programa aberto = atenção);
  - conexões de rede para portas típicas de mineração (3333, 4444, 5555, 7777, 14444, `stratum`).
- **Resultado:** cada item como **OK / atenção / suspeito**, com o motivo em português simples e o que fazer. Nada é marcado como "vírus" com certeza.
- **Aceite:** módulo sem Tk com funções puras que recebem os dados já lidos (testes 100% com dados simulados, nenhum comando real nos testes); consulta real só depois de o usuário confirmar na tela; relatório sem nome de usuário nem caminhos pessoais (pasta do usuário vira `%USERPROFILE%`); botão na aba de otimização.
- **Escolha de design já feita (a mais segura):** em dúvida, o item fica "atenção", nunca "OK"; e o app nunca oferece botão de remover.
### P3-02 · Medição antes e depois — `pronto` (depois de P3-01)
### P3-04 · Ajustes nível seguro (1 clique) — `pronto` (depois de P3-01 e P3-03)
- Só ajustes da lista segura do `CLAUDE.md`, cada um com aplicar e desfazer.
- **Nunca** desligar Defender ou Windows Update.
### P3-05 · Ajustes avançados (com confirmação) — `pronto` (depois de P3-04)

### ✅ Validação do Raphael — M3
Issue "Validar M3": rodar o check-up de segurança, medir, aplicar os ajustes seguros, medir de novo e desfazer tudo, no PC dele.

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
