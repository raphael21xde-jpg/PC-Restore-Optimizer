"""P4-04 (Fatia 0): constantes puras de espaçamento, tipografia, tamanhos e cores (sem tkinter).

Implementa a escala visual de `docs/P4-04-PROPOSTA.md` e `docs/IDEIAS-PARA-APLICAR.md`
(regra dos 8 pontos, hierarquia tipográfica, paleta única do tema escuro e funções
puras para geometria segura em telas com escala de 125% e 150% no Windows).

Este módulo não importa `tkinter` nem toca em discos, rede ou sistema operacional.
"""
from __future__ import annotations

# 1. Escala base de espaçamento (Regra dos 8 pontos — docs/IDEIAS-PARA-APLICAR.md)
ESPACO_ZERO = 0
ESPACO_FINO = 2       # Exceção permitida: ajuste visual fino de 1–2 px (ex.: item da sidebar)
ESPACO_MINIMO = 4     # Entre rótulo e seu campo; ajuste compacto
ESPACO_P = 8          # Dentro de um grupo (botões vizinhos, itens de mesma linha)
ESPACO_M = 16         # Entre itens de um mesmo bloco; margem padrão de diálogo compacto
ESPACO_G = 24         # Entre grupos diferentes; espaço interno padrão de painel/aba
ESPACO_GG = 32        # Margem ampla; separação antes de barra principal de ações
ESPACO_SECAO = 48     # Entre seções grandes da página

ESCALA_ESPACAMENTO = (
    ESPACO_ZERO,
    ESPACO_FINO,
    ESPACO_MINIMO,
    ESPACO_P,
    ESPACO_M,
    ESPACO_G,
    ESPACO_GG,
    ESPACO_SECAO,
)

# 2. Tokens semânticos de espaçamento (nomes pelo papel na tela)
PADDING_DIALOGO = ESPACO_M                      # 16 px — margem interna de janelas Toplevel
PADDING_PAINEL_COMPACTO = ESPACO_M              # 16 px — variante compacta de cartão/painel
PADDING_PAINEL = ESPACO_G                       # 24 px — variante padrão de cartão/painel/aba
PADDING_PAINEL_ESPACOSO = ESPACO_GG             # 32 px — variante espaçosa (ex.: hero)
PADDING_ABA_NOTEBOOK = ESPACO_P                 # 8 px  — espaço interno de sub-aba de Notebook
PADDING_CAIXA_TEXTO = (ESPACO_M, ESPACO_P)      # (16, 8) — padx=16, pady=8 em tk.Text
ESPACO_ENTRE_BOTOES = (0, ESPACO_P)             # (0, 8) — botões lado a lado alinhados à esquerda
ESPACO_ROTULO_CAMPO = (0, ESPACO_MINIMO)        # (0, 4) — rótulo acima do campo/tabela
ESPACO_DENTRO_GRUPO = (0, ESPACO_P)             # (0, 8) — elementos do mesmo grupo
ESPACO_ENTRE_BLOCOS = (0, ESPACO_M)             # (0, 16) — blocos dentro da mesma seção
ESPACO_ENTRE_GRUPOS = (0, ESPACO_G)             # (0, 24) — separação clara entre grupos

# 3. Alturas e preenchimentos padronizados de controles (ttk.Style)
PADDING_BOTAO = (ESPACO_M, ESPACO_P)            # (16, 8) — mesma altura para TButton, Primary e Secondary
PADDING_CAMPO_ENTRADA = ESPACO_P                # 8 px — TEntry e TCombobox alinhados aos botões
PADDING_TITULO_ABA = (ESPACO_M, ESPACO_P)       # (16, 8) — TNotebook.Tab
PADDING_CABECALHO_TABELA = (ESPACO_P, ESPACO_P)  # (8, 8)  — Treeview.Heading
ALTURA_LINHA_TABELA = 32                        # Múltiplo de 8 para rowheight do Treeview
ALTURA_MINIMA_TABELA_LINHAS = 6                 # Evita tabelas espremidas com height=2

# 4. Tipografia padronizada (6 papéis claros em vez de 15 tamanhos soltos)
FONTE_UI = 'Segoe UI'
FONTE_MONO = 'Consolas'
FONTE_SIMBOLO = 'Segoe UI Symbol'

TAMANHO_APOIO = 9            # Avisos curtos, rodapé, etiquetas de cartão
TAMANHO_CORPO = 10           # Texto padrão, botões, tabelas, relatórios técnicos
TAMANHO_SUBTITULO = 12       # Subtítulo de seção ou cartão
TAMANHO_TITULO_MODAL = 14    # Título de janela modal (Toplevel)
TAMANHO_TITULO_ABA = 16      # Título principal de aba
TAMANHO_TITULO_HERO = 20     # Destaque principal / métricas numéricas

# 5. Paleta única do tema escuro (elimina repetição entre app.py, workflow_ui.py e optimization_ui.py)
COR_FUNDO = '#0C1220'
COR_PAINEL = '#192438'
COR_BARRA_LATERAL = '#10192A'
COR_TEXTO = '#EFF4FF'
COR_TEXTO_SECUNDARIO = '#9CAAC0'
COR_DESTAQUE = '#9C85FF'
COR_DESTAQUE_ATIVO = '#B2A2FF'
COR_SUCESSO = '#5DDEB1'
COR_ALERTA = '#F3BE67'
COR_PERIGO = '#9A1C1C'
COR_BORDA = '#2B3952'
COR_HOVER = '#27334A'
COR_SELECAO = '#394C75'
COR_GRADE_GRAFICO = '#314052'
COR_BRANCO = '#FFFFFF'

# Apelidos compatíveis com os módulos existentes (app.py, workflow_ui.py, optimization_ui.py)
BG = COR_FUNDO
PANEL = COR_PAINEL
SIDEBAR = COR_BARRA_LATERAL
TEXT = COR_TEXTO
MUTED = COR_TEXTO_SECUNDARIO
ACCENT = COR_DESTAQUE
GREEN = COR_SUCESSO
AMBER = COR_ALERTA
BORDER = COR_BORDA
HOVER = COR_HOVER
WHITE = COR_BRANCO


def safe_window_size(
    desired_w: int,
    desired_h: int,
    screen_w: int,
    screen_h: int,
    margin: int = 80,
    min_w: int = 320,
    min_h: int = 240,
) -> tuple[int, int]:
    """Limita `(desired_w, desired_h)` à área útil da tela (125% e 150% no Windows).

    Se `screen_w` ou `screen_h` forem inválidos (`<= 0`), mantém o tamanho
    desejado (respeitando `min_w` e `min_h`).
    """
    dw = max(int(min_w), int(desired_w))
    dh = max(int(min_h), int(desired_h))
    sw = int(screen_w)
    sh = int(screen_h)
    pad = max(0, int(margin))
    if sw > 0:
        avail_w = max(int(min_w), sw - pad)
        dw = min(dw, avail_w)
    if sh > 0:
        avail_h = max(int(min_h), sh - pad)
        dh = min(dh, avail_h)
    return dw, dh


def safe_window_geometry(
    desired_w: int,
    desired_h: int,
    screen_w: int,
    screen_h: int,
    margin: int = 80,
    min_w: int = 320,
    min_h: int = 240,
) -> str:
    """Devolve a string `'LxA'` segura para `window.geometry(...)`."""
    w, h = safe_window_size(
        desired_w,
        desired_h,
        screen_w,
        screen_h,
        margin=margin,
        min_w=min_w,
        min_h=min_h,
    )
    return f'{w}x{h}'


def scale_px(value: int, factor: float = 1.0) -> int:
    """Converte um valor em pixels pelo fator de escala, mantendo número par."""
    v = int(value)
    if v <= 0:
        return 0
    f = max(1.0, float(factor))
    if f == 1.0:
        return v
    scaled = int(round(v * f))
    if scaled % 2 != 0:
        scaled += 1
    return scaled


def safe_wraplength(
    container_width: int,
    padding: int = PADDING_DIALOGO,
    min_wrap: int = 320,
) -> int:
    """Calcula `wraplength` adaptável para evitar texto cortado em janelas estreitas."""
    cw = int(container_width)
    pad = max(0, int(padding))
    mw = max(120, int(min_wrap))
    return max(mw, cw - 2 * pad)
