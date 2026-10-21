# Backlog do PC Restore & Optimizer

Fonte da verdade do **ciclo automático** (veja `docs/AUTOMACAO.md`). O ciclo
pega o **primeiro item `pronto`** cujas dependências já estão na `main`.

**Campos de cada item:**
- **Status:** `pronto` (o ciclo pode pegar), `bloqueado` (precisa de algo antes) ou `concluído`.
  "Em andamento" não é escrito aqui. Um item está em andamento quando existe uma PR aberta com o ID dele no título.
- **Depende de:** itens que precisam estar na `main` antes.
- **Raphael:** o que só o Raphael pode fazer (decidir, testar no hardware real, aprovar). `—` = nada além de revisar a PR.

Só o Raphael (ou uma PR aprovada por ele) muda este arquivo. Ao terminar um
item, a própria PR do item muda o status dele para `concluído`.

---

## Fase 2 — Preservação pronta pra qualquer PC

### P2-01 · Restaurar no lugar original, dentro do app
- **Status:** pronto · **Depende de:** — · **Raphael:** testar no Windows com uma pasta de teste
- **O que é:** levar para o motor e para a tela de restauração a etapa "colocar". Hoje ela só existe no script `restaurar_pos_formatacao.py`, usado em 20/10.
- **Aceite:**
  - função no motor que move da pasta de conferência para o destino original;
  - SHA-256 conferido depois de mover;
  - arquivo diferente que já existe → renomeado com `.antes-pcro-AAAAMMDD` (**nunca apagado**);
  - `desktop.ini` ignorado;
  - Program Files e ProgramData só com confirmação e sem administrador implícito;
  - DACL desprotegida, herdando da pasta (lição do osu!);
  - retomável e com relatório;
  - prévia obrigatória mostrando o que existe, o que é igual, o que é renomeado e o que precisa de administrador;
  - testes só com `TemporaryDirectory`.

### P2-02 · Avisar e recusar restauração como administrador
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - a tela de restauração detecta processo elevado e mostra aviso claro;
  - o motor recusa, a menos que o chamador passe `allow_elevated=True` explicitamente;
  - testes com detecção simulada.

### P2-03 · Verificar caminhos longos (LongPathsEnabled)
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - leitura (somente leitura) da chave `LongPathsEnabled`;
  - o plano de restauração conta quantos destinos passam de 259 caracteres;
  - se a chave estiver desligada, o app orienta o comando de administrador (não muda o registro sozinho);
  - testes com registro simulado.

### P2-04 · Lista de programas para reinstalar depois da formatação
- **Status:** pronto · **Depende de:** — · **Raphael:** testar a importação real no PC
- **Aceite:**
  - o backup guarda o `winget export`;
  - a tela pós-instalação lista os pacotes por categoria (runtimes, launchers, periféricos, dia a dia, dev, outros), com seleção;
  - gera o JSON filtrado e roda `winget import --ignore-unavailable` só depois de confirmação;
  - depois confere pacote a pacote (`winget list -e --id`);
  - mostra o que falhou e por quê (ex.: hash diferente → "instale pelo site oficial");
  - testes com executor simulado (nunca chamar o winget de verdade nos testes).

### P2-05 · Guia de launchers e bibliotecas de jogos em outros discos
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - detecção (somente leitura) de `SteamLibrary`, pastas da Epic (`.egstore`), EA, Ubisoft, Riot e Rockstar em todas as unidades;
  - guia pós-instalação por launcher (Steam: "Adicionar unidade"; Epic: avisar que pode baixar de novo; outros: "Localizar jogo");
  - testes com árvores sintéticas.

### P2-06 · Senhas de navegador em texto puro
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - a prévia do backup e a pós-restauração detectam arquivos como `*password*.csv` / `*senha*.csv` em Documentos/Downloads/Área de Trabalho;
  - mostra alerta e recomenda apagar depois de importar ou sincronizar;
  - **o app nunca apaga sozinho**;
  - testes sintéticos.

### P2-07 · Estabilidade da interface Tk
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - eliminar `invalid command name` e `Tcl interpreter is leaked` nos testes;
  - eliminar os prints soltos do teste do publicador;
  - a suíte do Windows sem esse ruído.

### P2-08 · Central de recuperação ligada ao app principal
- **Status:** pronto · **Depende de:** P2-01 · **Raphael:** —
- **Aceite:** a central abre manifestos reais (só leitura) e usa o fluxo do P2-01 para restaurar; continua funcionando com fixtures.

### P2-09 · Executor multi-disco real
- **Status:** bloqueado · **Depende de:** P2-01 · **Raphael:** **decisão explícita** para mexer nas travas `copy_authorized` / `physical_independence_verified`
- **Aceite:** ver a Etapa 31 (bloqueador P0). O ciclo **não** pega este item sem uma decisão registrada aqui.

### P2-10 · Estratégia de cópia com hardware real
- **Status:** pronto (só a parte de código) · **Depende de:** — · **Raphael:** rodar o benchmark no PC real
- **Aceite:**
  - script de medição (só leitura na origem, escrita só numa pasta de teste escolhida) com relatório;
  - o ciclo entrega o script e os testes;
  - a medição real é do Raphael.

---

## Fase 3 — Otimização universal

### P3-01 · Perfil de hardware (somente leitura)
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - coleta de CPU, GPU, RAM (quantidade, velocidade efetiva e dual channel), discos (tipo, saúde), notebook/desktop, bateria e versão do Windows;
  - classificação básico / intermediário / gamer / alto desempenho / notebook;
  - testes com dados simulados de várias máquinas.

### P3-02 · Medição antes e depois
- **Status:** pronto · **Depende de:** P3-01 · **Raphael:** medir no PC real
- **Aceite:**
  - linha de base (boot, RAM/CPU em repouso, disco, frametime via PresentMon se existir);
  - comparação com a medição seguinte;
  - testes simulados.

### P3-03 · Registro de alterações e "desfazer tudo"
- **Status:** pronto · **Depende de:** — · **Raphael:** —
- **Aceite:**
  - diário de alterações (o que mudou, valor antigo e valor novo);
  - desfazer individual e desfazer tudo;
  - ponto de restauração antes de cada lote (executor simulado nos testes);
  - **nenhum ajuste sem passar pelo diário**.

### P3-04 · Ajustes nível seguro (1 clique)
- **Status:** bloqueado · **Depende de:** P3-01, P3-03 · **Raphael:** aprovar a lista de ajustes
- **Aceite:**
  - plano de energia, programas na inicialização, Modo de Jogo, agendamento de GPU por hardware, temporários, efeitos visuais em PC fraco;
  - cada um com aplicar/desfazer e teste;
  - **nunca** desligar Defender ou Windows Update.

### P3-05 · Ajustes avançados (com confirmação)
- **Status:** bloqueado · **Depende de:** P3-04 · **Raphael:** aprovar a lista

### P3-06 · BIOS: só orientação
- **Status:** pronto · **Depende de:** P3-01 · **Raphael:** —
- **Aceite:**
  - verifica (somente leitura) se a RAM está abaixo da velocidade nominal (XMP/EXPO), Resizable BAR e versão da BIOS;
  - mostra o passo a passo por fabricante;
  - **nunca altera a BIOS**.

---

## Fase 4 — Produto

### P4-01 · Manual curto em português
- **Status:** pronto · **Depende de:** — · **Raphael:** revisar o texto

### P4-02 · Primeiro uso guiado (assistente)
- **Status:** bloqueado · **Depende de:** P2-01, P2-04 · **Raphael:** aprovar o fluxo

### P4-03 · Instalador (.exe)
- **Status:** bloqueado · **Depende de:** P4-02 · **Raphael:** decidir onde gerar (PC dele ou GitHub Actions no Windows)

### P4-04 · Interface moderna
- **Status:** bloqueado · **Raphael:** decidir manter o Tkinter ou migrar
