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

## Marco M2 — Preservação para qualquer PC  ← ATUAL
### P2-07 · Estabilidade da interface Tk — `pronto`
- Eliminar `invalid command name`, `Tcl interpreter is leaked` e os prints soltos dos testes.
- Precisa de ambiente com Tk para conferir; os agentes na nuvem (Linux sem Tk) pulam para o próximo item testável.
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

### FIX-P2-11-03 · Salvar o progresso do assistente fora da thread da interface
- **Status:** `pronto` (ressalva 1 da revisão da PR #76).
- **Problema:** `save_progress` pode esperar até ~2 s tentando trocar o arquivo (espera crescente no Windows) e hoje roda na thread do Tk, então a janela pode congelar nesse tempo.
- **Aceite:** "Feito"/"Pular" gravam o progresso num `Job` (voltando ao Tk por `WindowTimers.after`), sem gravações fora de ordem (a última marcação vence); fechar a janela não perde a última marcação já pedida; testes com dados simulados.
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
