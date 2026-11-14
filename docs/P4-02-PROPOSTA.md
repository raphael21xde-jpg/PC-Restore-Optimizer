# P4-02 · Primeiro uso guiado — Proposta

> **Etapa 1 (somente documentação):** este documento define o escopo, os textos previstos e o fatiamento do item **P4-02 · Primeiro uso guiado** antes de qualquer alteração no código do app (`GEMINI.md`).

---

## 1. O problema

Quando uma pessoa abre o **PC Restore & Optimizer** pela primeira vez, ela encontra no menu lateral diversas áreas ("Visão geral", "Meu computador", "Preservação", "Seleção avançada", "Instalar Windows", "Recuperação", "Depois de formatar", "Central de recuperação", "Cópia protegida para outro disco", "Otimização", "Diagnóstico" e "Histórico e relatórios").

Embora o assistente **"Depois de formatar"** (`after_format_ui.py`) já guie passo a passo quem acabou de reinstalar o Windows, falta um guia equivalente para quem está **começando do zero** (preparando o PC antes da formatação, ou querendo apenas conhecer e usar o app pela primeira vez sem pular etapas importantes como diagnosticar os discos, escolher o que manter no disco do Windows, criar o backup verificado e testar a restauração).

---

## 2. Antes × Depois

- **Antes, o usuário** abre o app pela primeira vez e precisa descobrir sozinho, entre os vários itens do menu lateral ou lendo o manual (`docs/MANUAL.md`), qual é a ordem recomendada das telas antes de reinstalar o Windows (olhar os discos → varrer e escolher o que manter → revisar e copiar → testar a restauração → conferir o checklist de instalação).
- **Depois, o usuário** conta com um assistente **"Primeiro uso guiado"** acessível pela tela **"Visão geral"** e pelo menu lateral: uma janela única, somente de orientação, com etapas numeradas em linguagem simples. Em cada etapa, o botão **"Abrir"** leva diretamente para a tela que já existe no app, e os botões **"Feito"** e **"Pular"** permitem acompanhar o próprio progresso sem executar nada escondido.

---

## 3. O que fica fora (limites inegociáveis)

Para manter o app 100% seguro e simples:

1. **Não executa operações por conta própria:** o primeiro uso guiado **só orienta e leva às telas que já existem**. Ele não roda diagnóstico de discos, não inicia varredura, não faz cópia de backup, não restaura arquivos, não aplica ajustes de otimização e não executa comandos do sistema.
2. **Não altera nenhuma trava de segurança:** `copy_authorized`, `physical_independence_verified`, `ready_for_format`, `installation_authorized` e `deletions_authorized` continuam intocadas.
3. **Não formata, não particiona e não apaga nada:** mantém os avisos claros de que o app nunca apaga arquivos e de que o que não for copiado do disco do Windows não entra no backup e se perde quando o instalador oficial da Microsoft formatar esse disco (R-88).
4. **Não substitui o assistente "Depois de formatar":** a última etapa apenas apresenta o caminho para o "Depois de formatar" e a "Otimização" quando o usuário já tiver terminado o preparo ou a reinstalação.
5. **Não bloqueia o uso livre do app:** a janela não trava o aplicativo e qualquer etapa pode ser marcada como "Pular" ou aberta na ordem que a pessoa preferir.

---

## 4. Telas e textos previstos

### 4.1. Onde o usuário encontra o guia
- Na página **"Visão geral"** (`app.py` / `workflow_ui.py`): botão **"Primeiro uso guiado  →"** ao lado do botão existente **"Depois de formatar  →"**.
- No **menu lateral** (`app.py`, `_build_sidebar`): ação **"Primeiro uso guiado"** (`_nav_action`, abrindo a janela sem alterar a contagem das 9 páginas de `nav_buttons`).

### 4.2. Janela "Primeiro uso guiado" (`first_use_ui.py` + `first_use.py`)

**Título da janela:** `Primeiro uso guiado`

**Cabeçalho e introdução (`FIRST_USE_INTRO_TEXT`):**
> Bem-vindo ao PC Restore & Optimizer. Este guia mostra a ordem recomendada para usar o aplicativo com segurança, passo a passo.
>
> O guia só orienta e abre cada tela para você: nenhuma cópia, restauração ou leitura de discos começa sozinha ao clicar em "Abrir". O app não apaga nenhum arquivo; lembre-se de que o que não for copiado do {drive} não entra no backup e se perde quando o instalador formatar o {drive}.

*(onde `{drive}` vem de `workflow_texts.system_drive()`, nunca `"C:"` fixo no código).*

**Aviso de modo de execução (`FIRST_USE_MODE_NOTE`):**
> Dica: use o aplicativo aberto do jeito normal (sem "Executar como administrador") para fazer backup e restaurar. Só abra como administrador, com a sua própria conta, se for aplicar ajustes nas abas "4  Energia reversível", "8  Ajustes seguros" ou "9  Ajustes avançados" de "Otimização".

**As 6 etapas (`FIRST_USE_STEPS`):**

| Nº | ID | Título da etapa | Texto de orientação na tela | O que o botão "Abrir" faz |
|---|---|---|---|---|
| 1 | `diagnostico` | **Conhecer os discos (só leitura)** | Veja na tela "Diagnóstico" quais discos existem no seu PC e qual é o disco do Windows. O backup precisará ir para outro disco físico, que não será formatado. | Navega para a página **"Diagnóstico"** (`app.navigate(app.diagnostic)`). |
| 2 | `explorar` | **Varrer e escolher o que manter** | Na tela "Meu computador", examine as unidades desejadas e marque jogos, aplicativos e pastas como "Manter selecionados" ou "Não preservar" (não copiar nunca apaga nada). Para adicionar pastas avulsas ou criar o cofre do navegador, use "Seleção avançada". | Navega para a página **"Meu computador"** (`app.navigate(app.home)`). |
| 3 | `preservacao` | **Revisar o plano de preservação** | Na tela "Preservação", confira tudo o que foi marcado e os saves de jogos que estão no {drive}. O que ficar desmarcado ou pendente no {drive} não entra no backup e se perde quando o instalador formatar o {drive}. | Navega para a página **"Preservação"** (`app.navigate(app.preservation)`). |
| 4 | `backup` | **Escolher destino e fazer o backup** | Na tela de revisão do backup (aberta por "Próximo: revisar backup dos arquivos escolhidos →" em "Preservação"), use "Escolher destino" para apontar para outro disco, clique em "1. Recalcular plano e espaço" e depois em "2. Iniciar backup (confirmação dupla)". | Navega para a página de revisão do backup (`app.navigate(app.review)`). |
| 5 | `testar` | **Testar o backup antes de formatar** | Nunca formate sem testar o backup. Na tela "Histórico e relatórios", escolha o backup criado e use "Testar restauração de arquivo pequeno" para comprovar que os arquivos podem ser lidos. | Navega para a página **"Histórico e relatórios"** (`app.navigate(app.history)`). |
| 6 | `proximos` | **Instalar o Windows, restaurar ou otimizar** | Com o backup testado, veja o checklist em "Instalar Windows" (quem formata e instala é o instalador oficial da Microsoft, operado por você). No Windows novo, use "Depois de formatar" para trazer tudo de volta e "Otimização" para medir e ajustar o PC com segurança. | Navega para a página **"Instalar Windows"** (`app.navigate(app.installation)`). |

**Controles por etapa:**
- Rótulo de situação: `Pendente`, `Feito` ou `Pulado` (`STATUS_TEXT`).
- Botões: `"Abrir"`, `"Feito"` e `"Pular"` (clicar de novo no mesmo botão volta para `Pendente`, igual ao assistente "Depois de formatar").
- Rodapé da janela: botão `"Recomeçar marcações"` (volta todas as etapas para `Pendente`) e botão `"Fechar"`.

**Persistência do progresso (somente marcações):**
- Arquivo `primeiro-uso-progresso.json` dentro de `choices_store.app_data_dir()` (`%LOCALAPPDATA%\PC-Restore-Optimizer\` ou pasta configurada nos testes), gravado fora da thread do Tk (reaproveitando o padrão de gravação atômica com `.parcial` único `O_CREAT|O_EXCL`, `fsync`, `os.replace`, recusa de link/atalho, limite de 64 KiB e `ProgressSaver` em thread própria, conforme R-09 e R-10).
- Se o arquivo estiver estragado, não for comum ou for link, fica intocado: o assistente avisa em linha própria (sem caminho completo, R-07) e segue em memória ou num candidato `-2`, `-3`...

---

## 5. Fatiamento proposto (uma PR por fatia na Etapa 2)

A implementação na **Etapa 2** só começa depois que esta proposta for revisada e mesclada na `main`. Será dividida em **2 fatias pequenas**, sempre partindo da `main` atualizada:

### Fatia 1 — Módulo puro `first_use.py` (sem `tkinter`) + testes
- **Branch:** `gemini/P4-02-fatia-1-modulo-primeiro-uso`
- **Escopo:**
  - Criar `first_use.py` (sem importar `tkinter`), contendo:
    - `FIRST_USE_STEPS(drive=None)`, `FIRST_USE_INTRO_TEXT(drive=None)` e `FIRST_USE_MODE_NOTE`, usando `workflow_texts.system_drive()`;
    - validação das marcações (`pendente`, `feito`, `pulado`), leitura segura (`load_first_use_progress`) e gravação atômica em segundo plano (`save_first_use_progress` / `FirstUseProgressSaver`), recusando links/atalhos e nunca apagando arquivos;
    - mensagens de erro fixas sem expor caminho completo nem nome de usuário (R-07).
  - Criar `tests/test_first_use_p4_02.py` (100% sem `tkinter`, usando `TemporaryDirectory`).
- **Critérios de aceite da Fatia 1:**
  1. `first_use.py` importa e passa em todos os testes com `sys.modules['tkinter'] = None`.
  2. Todos os textos seguem a R-88 (dizem que o app não apaga nenhum arquivo e que o que não for copiado do disco do Windows se perde na formatação, sem `"C:"` fixo e sem `"não mexe"`, `"intactos"` ou `"só grava"`).
  3. Todos os nomes de telas, abas e botões citados entre aspas nos textos das etapas existem de verdade nas funções que montam essas telas (conferidos por teste com `ast`, R-62 / R-74).
  4. Leitura e gravação do progresso testadas em `TemporaryDirectory` (incluindo arquivo corrompido, grande demais, link/reparse simulado e concorrência no gravador em segundo plano, R-09, R-10 e R-29).

### Fatia 2 — Janela `first_use_ui.py`, ligação em `app.py`, manual e testes de tela
- **Branch:** `gemini/P4-02-fatia-2-janela-primeiro-uso`
- **Escopo:**
  - Criar `first_use_ui.py` (`show_first_use(app, *, base=None)`): janela única por instância (`deiconify()` + `lift()`), usando `WindowTimers` (R-11), com as 6 etapas, botões `"Abrir"`, `"Feito"`, `"Pular"`, `"Recomeçar marcações"` e `"Fechar"`.
  - Ligar em `app.py`: botão `"Primeiro uso guiado  →"` na Visão geral e item `"Primeiro uso guiado"` no menu lateral (`_nav_action`).
  - Atualizar `docs/MANUAL.md` e `tests/test_manual.py` (`UI_LABELS`) para citar o `"Primeiro uso guiado"` (respeitando o limite de linhas do manual e a R-62).
  - Criar `tests/test_first_use_gui_p4_02.py` (testando ações de cada botão — `"Abrir"`, `"Feito"`, `"Pular"`, `"Recomeçar marcações"` e `"Fechar"` — tanto sem `tkinter` com objetos falsos/R-87 quanto com janela Tk real usando `track_tk_root`, R-11 e R-18).
- **Critérios de aceite da Fatia 2:**
  1. Clicar em `"Abrir"` em cada uma das 6 etapas apenas navega para a respectiva página existente (`diagnostic`, `home`, `preservation`, `review`, `history`, `installation`), sem disparar varredura, cópia, restauração ou diagnóstico automático.
  2. Clicar em `"Feito"`, `"Pular"` e `"Recomeçar marcações"` atualiza o rótulo na hora e agenda a gravação fora da thread do Tk (`FirstUseProgressSaver` + `WindowTimers`).
  3. Abrir `"Primeiro uso guiado"` duas vezes reaproveita a mesma janela aberta (`deiconify` + `lift`), e fechar a janela espera a gravação pendente nos testes (`addCleanup` + `join`, R-29).
  4. `tests/test_manual.py` e a suíte completa (`py -3 -m unittest discover -s tests`) passam com 0 falhas e 0 erros no Windows e com `sys.modules['tkinter'] = None` para os testes sem Tk.
