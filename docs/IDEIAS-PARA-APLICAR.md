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
