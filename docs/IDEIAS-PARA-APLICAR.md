# Ideias para aplicar no projeto

Caderno de ideias que o Raphael trouxe de fora (tweets, artigos, vídeos) para
aplicar no PC Restore & Optimizer. Cada ideia tem: de onde veio, o resumo, como
se aplica aqui e a situação.

**Como usar este arquivo**
- Isto é uma lista de ideias, **não** de regras. Uma ideia só vira regra quando o
  Raphael aprova e ela entra em `docs/REGRAS.md`, no `CLAUDE.md` ou no
  `docs/BACKLOG.md`.
- Os agentes do ciclo **não** implementam nada daqui por conta própria.
- Situações possíveis: `anotada` → `aprovada` → `aplicada` (ou `descartada`).

**Decisão do Raphael (13/11/2026):** quando o ciclo chegar ao item
**P4-04 · Interface moderna** do `docs/BACKLOG.md`, as ideias de interface deste
caderno devem ser aplicadas no app. Para o app Tkinter isso significa os
princípios (escala de espaçamento, alturas padronizadas, hierarquia por
proximidade, tipografia, contraste, teste das telas com dados ruins); os
componentes e skills feitos para web ficam para a central de projetos.
Enquanto este arquivo não estiver na `main` e o P4-04 não apontar para ele, os
agentes do ciclo não enxergam esta decisão.

---

## 1. Regra dos 8 pontos: espaçamento consistente na interface

- **Fonte:** artigo de Magdiel Silva (@magdiel_rb), "Seu Claude Code faz
  interfaces com cara de projeto amador? O problema pode estar em apenas 8
  pixels." — https://x.com/magdiel_rb/status/2120593918056108341 (11/11/2026)
- **Anotada em:** 13/11/2026
- **Situação:** anotada
- **Onde encaixa:** Fase 4 (interface moderna). Vale principalmente para telas
  novas; não é para reformar as telas atuais agora.

### Resumo da ideia

1. **Escala fixa de espaçamento.** Usar só valores de uma lista curta
   (4, 8, 16, 24, 32, 48, 64) em vez de inventar um número em cada tela.
2. **Proximidade comunica.** Espaço pequeno dentro de um grupo (rótulo e campo:
   8) e espaço maior entre grupos (24). Isso organiza a tela sem precisar de
   bordas nem caixas.
3. **Alturas padronizadas.** Botões, campos e seletores equivalentes com a mesma
   altura (32, 40 ou 48), para alinharem quando ficam lado a lado.
4. **Variantes de bloco.** Três tamanhos de espaço interno para cartões e
   painéis: compacto (16), padrão (24) e espaçoso (32).
5. **Tokens.** Guardar os valores em constantes com nome, de preferência pelo
   papel (`ESPACO_ENTRE_SECOES`), e não espalhar números soltos pelo código.
6. **Exceções.** Tamanho de fonte, bordas de 1 px, ícones e cantos arredondados
   não precisam ser múltiplos de 8. Ajustes de 1 ou 2 px para alinhamento visual
   são aceitáveis. A regra existe para ajudar, não para engessar.
7. **Para agentes de IA.** "Bonito", "clean" e "premium" não são instruções.
   É preciso escrever regras objetivas no arquivo de instruções dos agentes e
   proibir a criação de tokens novos sem necessidade.
8. **Em projeto que já existe.** Fazer um inventário dos valores usados, definir
   a escala oficial, trocar os valores antigos olhando o contexto (sem
   substituição cega), começar pelos componentes compartilhados e conferir o
   resultado visualmente.

### Como aplicar no PCRO (Tkinter)

O artigo fala de sites (CSS e Tailwind). No nosso app o equivalente é:

- **Espaçamento:** os parâmetros `padx`, `pady`, `ipadx` e `ipady` de `pack` e
  `grid`, e o `padding` dos estilos `ttk`.
- **Tokens:** um módulo pequeno de constantes, por exemplo:

  ```python
  ESPACO_MINIMO = 4    # ajuste fino
  ESPACO_P = 8         # dentro de um grupo (rótulo e campo, botões vizinhos)
  ESPACO_M = 16        # entre itens de um mesmo bloco
  ESPACO_G = 24        # entre grupos; espaço interno padrão de um painel
  ESPACO_GG = 32       # margem da janela; antes da barra de ações
  ESPACO_SECAO = 48    # entre seções grandes
  ```

- **Alturas:** definir o tamanho dos botões e campos uma vez só, num
  `ttk.Style`, em vez de configurar cada widget.
- **Atenção à escala do Windows (DPI):** em telas com 125% ou 150%, pixels fixos
  ficam menores do que o esperado. Avaliar o uso de unidades do Tk que
  acompanham a escala (por exemplo `"6p"`, em pontos) ou multiplicar pelo fator
  de escala da janela.

### Regras candidatas (para o Raphael aprovar antes de valerem)

- Usar a escala de espaçamento do módulo de constantes; não escrever números
  soltos em `padx`/`pady` sem justificativa.
- Espaço menor dentro de um grupo e maior entre grupos.
- Controles equivalentes com a mesma altura em todas as telas.
- Reutilizar as constantes existentes; não criar constantes novas sem necessidade.
- Não mudar cores, fontes nem a estrutura de uma tela ao ajustar espaçamento.
- Conferir o resultado visualmente (captura de tela), inclusive em janela pequena.

### Próximos passos sugeridos

1. Inventário (somente leitura) dos valores de `padx`/`pady` usados hoje no app.
2. Raphael aprova a escala e as regras candidatas.
3. Criar o módulo de constantes e aplicar primeiro numa tela só, comparando
   antes e depois.

---

## 2. Mascotes para os agentes (open-bot-avatar)

- **Fonte:** tweet de Robson Collaneri (@yrobhc) —
  https://x.com/yrobhc/status/2120577593262985611 (11/11/2026). A skill é a
  `generate-avatar`, do projeto de código aberto
  https://github.com/DominikScholz/open-bot-avatar (licença MIT).
- **Anotada em:** 13/11/2026
- **Situação:** anotada
- **Onde encaixa:** PCRO Monitor (painel web dos agentes). No app Tkinter, só
  como imagem parada, e apenas na Fase 4.

### Resumo da ideia

- Cada mascote é um arquivo JSON pequeno: um contorno (um caminho SVG numa área
  de 100×100) e a posição dos olhos. Exemplo: foguete, escudo, lupa, caneca.
- A skill recebe uma descrição ("um ajudante para backup") e devolve esse JSON,
  conferido por um validador do próprio projeto.
- Um renderizador em JavaScript, sem dependências, desenha o mascote com volume,
  cor, olhos que seguem o mouse e três humores: `idle`, `thinking` e `happy`.
  Também gera um SVG parado.

### Como aplicar no PCRO

- **PCRO Monitor:** um mascote por agente (Coordenador, Planejador,
  Desenvolvedor, Testador, Revisor, Integrador, Validador Windows). O humor pode
  refletir o estado que o painel já guarda: `thinking` enquanto trabalha,
  `happy` quando deu certo, `idle` em espera.
- **App Tkinter:** o renderizador é JavaScript e não roda no Tkinter. Só daria
  para usar o SVG parado convertido em imagem, como ícone.

### Cuidados

- É enfeite: não muda o que o app faz. Não deve passar na frente da Fase 1.
- Projeto novo (primeiras versões em novembro de 2026): fixar a versão usada e
  preferir o SVG parado embutido na página, em vez de carregar o script de fora.
- Não instalar a skill nos agentes do ciclo: gerar os mascotes uma vez, numa
  conversa com o Raphael, e guardar os JSON.
- A cor e o humor não podem ser o único sinal de erro no painel; o texto do
  estado continua obrigatório.

---

## 3. Dev Design Library: catálogo de componentes, referências e skills de design

- **Fonte:** https://devlibraries.com (indicado pelo Raphael em 13/11/2026)
- **Situação:** anotada
- **Onde encaixa:** principalmente na **central de projetos** e no PCRO Monitor,
  que são páginas web. No app Tkinter valem só os princípios (ver abaixo).

### O que o site tem

- Cerca de 13 mil componentes de interface de 110 bibliotecas de código aberto
  (quase todas para web: React, Tailwind, HTML/CSS), com código e licença.
- Listas curadas: ferramentas, sites de referência visual e materiais de estudo.
- 64 skills para agentes de programação, em 9 grupos: direção de design (11),
  revisão e acabamento (11), animação (12), experimentar e construir (8),
  gráficos e vídeo (7), engenharia (5), Figma (4), mobile (4), produtividade (2).
- Um servidor MCP próprio, que pede login numa conta do site (não é necessário).

### Skills que mais combinam com o que o Raphael pediu

Seleção inicial, a confirmar lendo cada uma antes de instalar:

| Para quê | Skills candidatas |
|---|---|
| Dar direção visual e fugir da "cara de IA" | Frontend Design (Anthropic), Impeccable, Design Taste Frontend, Unslop |
| Revisar uma tela pronta | Better Interface, Better Layout, Better Typography, Better Colors |
| Testar a tela com dados ruins (nomes longos, lista vazia) | Break UI |
| Acessibilidade | Accessibility / Better Accessibility |
| Comparar versões antes de escolher | Prototype, Variant |
| Diagramas do sistema | Archify |
| Mascotes dos agentes | Generate Avatar (ideia 2) |
| Gastar menos tokens | Caveman |

Duas já estão no nosso processo: **Grill Me** (as "perguntas do Grill" do gate
`intent`) e a ideia do **Caveman** (respostas curtas).

### Como aplicar

- **Central de projetos (web):** escolher de 3 a 5 skills, não todas. Cada skill
  instalada ocupa contexto e gasta tokens em toda conversa, o que vai contra a
  meta de economia.
- **App Tkinter:** componentes React e skills de CSS/animação não se aplicam.
  Servem os princípios: escala de espaçamento, hierarquia, tipografia, contraste
  e o teste com dados ruins.

### Leitura das skills candidatas (13/11/2026)

Li o texto real das skills (cópia só para leitura; nada foi instalado).
Correção ao que está em "Como aplicar": o que fica sempre no contexto é só a
descrição curta de cada skill. O texto completo é carregado quando a skill é
usada. O custo, portanto, aparece no uso, e cresce com o tamanho da skill.

| Skill | O que faz de verdade | Tamanho | Roda scripts? | Avaliação |
|---|---|---|---|---|
| Frontend Design (Anthropic) | Faz o agente planejar cor, tipografia e layout a partir do assunto do produto antes de escrever código, e lista os "vícios" de página gerada por IA para evitar | ~1.500 palavras | Não | **Recomendo** |
| Better Interface + família `better-*` (Jakub Krehel) | Revisa uma tela pronta em 6 áreas (acessibilidade, layout, texto, tipografia, cor, acabamento) e devolve um relatório único, ordenado por impacto, com arquivo e linha de cada problema | ~1.400 palavras + 6 skills de ~1.500 | Não | **Recomendo** |
| Break UI (Emil Kowalski) | Monta dados "do pior caso real" (nome longo, campo vazio, lista com 0, 1 e 1.000 itens) e mostra o que quebra; relata antes de corrigir | ~2.400 palavras | Não | **Recomendo** |
| Unslop (heydamir) | Conserta uma tela com cara de IA em 9 passadas, na ordem (espaçamento primeiro), depois de definir a direção e esperar o "sim" do usuário | ~5.700 palavras | Sim (captura de página, vídeo); licença CC BY exige crédito | Opcional, para reformar o Monitor |
| Impeccable (Paul Bakaus) | Conjunto grande de comandos de design (planejar, criticar, auditar, polir) | ~70.000 palavras em 58 arquivos | Sim, um script próprio a cada sessão | Não agora: pesado e repete o Frontend Design |
| Design Taste Frontend (leonxlnx) | Direção de arte com imagens de referência | ~81.000 palavras, mais de 1.600 arquivos | — | Não agora: pesado |
| Archify | Gera diagramas interativos | ~38.000 palavras, 206 arquivos | — | Só se precisarmos de diagramas |
| Prototype / Variant | Geram várias versões de uma peça para escolher | ~1.200 palavras cada | Não | Opcional, mais tarde |

**Recomendação para a central:** Frontend Design (para desenhar), Better
Interface com a família `better-*` (para revisar) e Break UI (para testar com
dados ruins). O Unslop entra só se formos reformar o PCRO Monitor.

No app Tkinter nenhuma delas se instala; do Break UI se aproveita a lista de
dados do pior caso para os testes de tela.

### Cuidados

- Uma skill é um texto de instruções escrito por terceiros que o agente passa a
  obedecer. **Ler cada uma antes de instalar** e não instalar nos agentes do
  ciclo sem aprovação do Raphael.
- Componentes mantêm a licença da biblioteca de origem: conferir antes de copiar.
- Instalar por comando (`npx skills add ...`) baixa código de fora: fixar a
  versão e revisar o que entrou.

---

## 4. agentes.chat: espaço de trabalho onde pessoas e agentes dividem os canais

- **Fonte:** https://x.com/agentes_chat/status/2120655002335064125 (11/11/2026),
  site https://agentes.chat, código em
  https://github.com/agentes-chat/agentes-chat (licença AGPL-3.0)
- **Anotada em:** 13/11/2026
- **Situação:** anotada
- **Onde encaixa:** é a referência mais próxima da central de projetos
  (`docs/CENTRAL-DE-PROJETOS-RASCUNHO.md`).

### O que é

Um produto pronto, em beta aberto, parecido com o Slack: canais e conversas onde
pessoas e agentes de IA trabalham juntos. Pelo README e pelo anúncio:

- Cada agente tem papel, rosto, modelo, orçamento mensal e uma pessoa responsável.
- Mencionar o agente (`@nome`) faz ele trabalhar; um "roteador" barato decide
  quem responde quando ninguém foi mencionado.
- **Aprovações:** merge, deploy e ações sensíveis esperam o clique de uma pessoa,
  num cartão dentro da conversa.
- Quadro de tarefas, rotinas agendadas, memória, wiki e um "Drive" com tudo o que
  os agentes produzem.
- Funciona no navegador e em aplicativo de desktop. Pode ser usado na nuvem deles
  (pago) ou instalado num servidor Linux próprio (gratuito).

### O que serve para a central

Muito do que o Raphael descreveu como "escritório" já existe ali. Ideias a
aproveitar no nosso desenho:

- Agente com papel, rosto e responsável (combina com os mascotes, ideia 2).
- Cartão de aprovação dentro da conversa (o PCRO Monitor já faz algo parecido em
  "Precisa de você").
- **Orçamento por agente**, conferido antes de cada chamada: é exatamente o
  controle de gasto que estamos montando à mão.
- Roteador barato na entrada: é a ideia do "porteiro" da Fase 1.
- Um lugar único para os resultados (relatórios, PRs, páginas).

### Dois caminhos

1. **Usar o produto** como a central. Vantagem: já está pronto. Custos: é beta e
   tem falhas (os autores avisam); instalar por conta própria exige um servidor
   Linux ligado o tempo todo; os agentes passariam a rodar no sistema deles, e
   não nas tarefas agendadas do Claude Code, então o ciclo do PCRO teria de ser
   refeito lá.
2. **Construir a nossa central e usar o agentes.chat como referência** de
   organização e de telas. Mantém o ciclo atual do PCRO como está.

Recomendação: caminho 2 por enquanto. O PCRO está perto do fim e não vale trocar
a base do ciclo agora. Vale o Raphael abrir o beta com um projeto de brinquedo
para sentir como é.

### Cuidados

- **Licença AGPL-3.0:** usar é livre. Copiar código deles para dentro do nosso
  projeto obriga o nosso código a ter a mesma licença. Inspirar-se nas ideias e
  nas telas não tem essa obrigação.
- **"Use o plano do Claude que você já paga":** o anúncio diz isso; o README diz
  que cada organização cadastra a própria chave de modelo. Confirmar como
  funciona de verdade, e se é permitido, antes de contar com isso.
- **Acesso:** ligar o produto ao GitHub dá a um sistema de terceiros acesso ao
  repositório privado. Só com decisão do Raphael, e de preferência na versão
  instalada em servidor próprio.
- As travas de segurança do PCRO continuam valendo em qualquer central.
