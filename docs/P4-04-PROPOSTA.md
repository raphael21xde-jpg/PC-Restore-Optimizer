# P4-04 · Interface moderna — Etapa 1: Inventário e Proposta

Este documento entrega a **Etapa 1** do item **P4-04 · Interface moderna**, conforme definido em `GEMINI.md` e nas diretrizes de `docs/IDEIAS-PARA-APLICAR.md` (ideias 1, 3 e 5, e a decisão do Raphael de 13/11/2026).

Nesta etapa **nenhum arquivo `.py` foi alterado** e o aplicativo não foi executado. Todo o levantamento abaixo foi feito exclusivamente por leitura estática dos 21 arquivos de interface do projeto (`app.py` e todos os módulos `*_ui*.py`).

---

## 1. Inventário (somente leitura do código)

Foram inspecionados todos os **21 arquivos de tela** do repositório:

1. `after_format_ui.py`
2. `app.py`
3. `app_recovery_ui.py`
4. `backup_preflight_scenario_ui.py`
5. `browser_recovery_ui.py`
6. `completeness_audit_ui_v067.py`
7. `completeness_audit_ui_v068.py`
8. `deep_discovery_ui.py`
9. `drive_safety_ui.py`
10. `file_index_ui.py`
11. `launcher_guide_ui.py`
12. `multi_backup_destinations_ui.py`
13. `multi_source_offline_reopen_ui.py`
14. `multi_source_recovery_center_ui.py`
15. `optimization_ui.py`
16. `real_copy_ui.py`
17. `recovery_center_ui.py`
18. `restore_ui.py`
19. `selective_backup_ui.py`
20. `winget_programs_ui.py`
21. `workflow_ui.py`

---

### 1.1 Tabela de espaçamento por arquivo (`padx`, `pady`, `ipadx`, `ipady` e `padding`)

> **Observação:** Os parâmetros `ipadx` e `ipady` não são usados em nenhum arquivo do projeto (**0 ocorrências**). Todo o espaçamento interno e externo hoje é feito com `padx`, `pady` (em `pack`, `grid` e construtores `tk.Label`/`tk.Button`/`tk.Text`) e `padding` (em `ttk.Frame`, `ttk.LabelFrame` e `ttk.Style`).

| Arquivo | Valores de `padx` (valor: vezes) | Valores de `pady` (valor: vezes) | `ipadx` / `ipady` | Valores de `padding` (valor: vezes) | Total de chamadas no arquivo |
|---|---|---|---|---|---|
| `after_format_ui.py` | `6`: 1, `(4, 0)`: 1 | `(4, 2)`: 1, `(0, 4)`: 1, `(0, 2)`: 1, `(0, 6)`: 1, `8`: 1, `(2, 4)`: 1, `(6, 6)`: 1 | 0 / 0 | `14`: 1, `(0, 4)`: 1 | `padx`: 2, `pady`: 7, `padding`: 2 (**11**) |
| `app.py` | `18`: 35, `(0, 8)`: 22, `12`: 11, `(0, 9)`: 11, `14`: 8, `(0, 10)`: 6, `24`: 5, `22`: 4, `8`: 4, `(8, 0)`: 4, `17`: 3, `(0, 12)`: 3, `(10, 0)`: 3, `16`: 2, `13`: 4, `10`: 2, `(12, 0)`: 1, `20`: 1, `26`: 1, `(22, 22)`: 1, `15`: 1, `(16, 4)`: 1, `(18, 4)`: 1, `(9, 0)`: 1 | `8`: 16, `6`: 8, `(0, 8)`: 6, `(0, 10)`: 5, `12`: 5, `4`: 4, `5`: 4, `10`: 4, `2`: 2, `11`: 2, `(0, 12)`: 2, `(15, 5)`: 2, `(2, 6)`: 2, `(15, 7)`: 2, `(4, 2)`: 1, `(20, 14)`: 1, `(28, 30)`: 1, `(0, 18)`: 1, `(12, 5)`: 1, `(0, 17)`: 1, `(4, 11)`: 1, `(3, 16)`: 1, `(6, 8)`: 1, `(0, 16)`: 1, `(22, 6)`: 1, `(8, 17)`: 1, `(0, 22)`: 1, `(4, 10)`: 1, `(0, 20)`: 1, `(15, 6)`: 1, `(6, 12)`: 1, `(18, 2)`: 1, `(16, 6)`: 1, `(8, 10)`: 1, `(0, 7)`: 1, `(19, 8)`: 1, `14`: 1, `9`: 1, `(0, 5)`: 1, `(0, 15)`: 1, `(4, 6)`: 1, `(9, 6)`: 1, `(3, 0)`: 1, `(5, 7)`: 1, `(3, 8)`: 1, `(2, 7)`: 1, `(4, 12)`: 1, `(3, 10)`: 1, `(16, 8)`: 1, `16`: 1, `(0, 14)`: 1, `(3, 8)`: 1, `(4, 12)`: 1, `(0, 6)`: 1, `(0, 4)`: 1 | 0 / 0 | `(14, 10)`: 1, `(16, 11)`: 1, `(13, 10)`: 1, `7`: 1, `(18, 11)`: 1, `(8, 10)`: 1 | `padx`: 135, `pady`: 107, `padding`: 6 (**248**) |
| `app_recovery_ui.py` | `3`: 7, `4`: 2, `6`: 2 | `5`: 3, `7`: 2, `8`: 1, `6`: 1, `4`: 1 | 0 / 0 | `12`: 1 | `padx`: 11, `pady`: 8, `padding`: 1 (**20**) |
| `backup_preflight_scenario_ui.py` | `(5, 20)`: 1, `(7, 25)`: 1, `(7, 9)`: 1, `(10, 0)`: 1 | `(8, 11)`: 1, `(0, 9)`: 1, `(0, 10)`: 1, `(0, 8)`: 1, `(10, 0)`: 1 | 0 / 0 | `14`: 1, `8`: 1, `5`: 1 | `padx`: 4, `pady`: 5, `padding`: 3 (**12**) |
| `browser_recovery_ui.py` | `(0, 8)`: 3 | `8`: 2, `10`: 2, `6`: 1, `(10, 4)`: 1 | 0 / 0 | `16`: 1 | `padx`: 3, `pady`: 6, `padding`: 1 (**10**) |
| `completeness_audit_ui_v067.py` | `(0, 8)`: 2, `14`: 1 | `(0, 5)`: 1, `(0, 8)`: 1, `(0, 7)`: 1, `14`: 1, `(9, 0)`: 1 | 0 / 0 | `15`: 1, `8`: 5 | `padx`: 3, `pady`: 5, `padding`: 6 (**14**) |
| `completeness_audit_ui_v068.py` | `4`: 6, `(0, 8)`: 5, `(0, 9)`: 2, `6`: 2, `14`: 1, `(0, 6)`: 1 | `(0, 7)`: 3, `(0, 6)`: 2, `(8, 0)`: 2, `(0, 5)`: 1, `(0, 8)`: 1, `14`: 1, `(0, 9)`: 1, `(9, 0)`: 1 | 0 / 0 | `15`: 1, `8`: 7 | `padx`: 17, `pady`: 12, `padding`: 8 (**37**) |
| `deep_discovery_ui.py` | `4`: 11, `8`: 2, `(0, 14)`: 1, `5`: 1 | `5`: 6, `6`: 2, `2`: 2, `7`: 2, `4`: 1, `(8, 4)`: 1, `(7, 12)`: 1, `(0, 9)`: 1, `(4, 12)`: 1, `(5, 7)`: 1, `(2, 8)`: 1 | 0 / 0 | `12`: 2, `5`: 2, `18`: 1 | `padx`: 15, `pady`: 19, `padding`: 5 (**39**) |
| `drive_safety_ui.py` | `(10, 0)`: 5 | `4`: 6, `(6, 8)`: 1, `(0, 9)`: 1, `(9, 7)`: 1, `(2, 8)`: 1, `(0, 10)`: 1, `(12, 0)`: 1 | 0 / 0 | `16`: 1 | `padx`: 5, `pady`: 12, `padding`: 1 (**18**) |
| `file_index_ui.py` | `4`: 5, `14`: 2, `(0, 6)`: 1, `6`: 1, `18`: 1, `(0, 8)`: 1 | `2`: 4, `(0, 4)`: 2, `(3, 7)`: 1, `(6, 3)`: 1, `(12, 9)`: 1, `10`: 1 | 0 / 0 | `10`: 2, `(10, 2)`: 1 | `padx`: 11, `pady`: 10, `padding`: 3 (**24**) |
| `launcher_guide_ui.py` | `(7, 0)`: 1 | `(4, 6)`: 1, `(0, 2)`: 1, `(0, 6)`: 1, `(8, 6)`: 1 | 0 / 0 | `14`: 1 | `padx`: 1, `pady`: 4, `padding`: 1 (**6**) |
| `multi_backup_destinations_ui.py` | `(0, 8)`: 2 | `(0, 8)`: 2, `(6, 8)`: 1, `(0, 5)`: 1, `(10, 8)`: 1 | 0 / 0 | `14`: 1 | `padx`: 2, `pady`: 5, `padding`: 1 (**8**) |
| `multi_source_offline_reopen_ui.py` | `(0, 6)`: 1, `(7, 3)`: 1, `10`: 1 | `(7, 8)`: 1, `(0, 9)`: 1, `(12, 10)`: 1 | 0 / 0 | `15`: 1 | `padx`: 3, `pady`: 3, `padding`: 1 (**7**) |
| `multi_source_recovery_center_ui.py` | `(0, 8)`: 2, `(14, 5)`: 1 | `5`: 1, `(5, 8)`: 1, `(0, 8)`: 1, `(3, 10)`: 1, `(6, 0)`: 1, `(3, 5)`: 1, `(8, 0)`: 1 | 0 / 0 | `14`: 1 | `padx`: 3, `pady`: 7, `padding`: 1 (**11**) |
| `optimization_ui.py` | `12`: 14, `(0, 8)`: 8, `16`: 7, `(9, 0)`: 7, `(0, 9)`: 3, `(0, 6)`: 3, `(0, 7)`: 2, `(8, 0)`: 2, `14`: 2, `(15, 5)`: 1, `(0, 4)`: 1, `(7, 0)`: 1, `(0, 12)`: 1, `(0, 10)`: 1, `(0, 16)`: 1 | `11`: 7, `(0, 4)`: 7, `(0, 5)`: 4, `(2, 8)`: 4, `12`: 2, `(0, 12)`: 3, `(0, 10)`: 2, `(12, 6)`: 2, `(13, 5)`: 1, `(0, 14)`: 1, `(8, 0)`: 1, `13`: 1, `(3, 5)`: 1, `(4, 0)`: 1, `(10, 1)`: 1, `(6, 0)`: 1, `(10, 3)`: 1, `(6, 4)`: 1, `6`: 1, `(0, 8)`: 1, `8`: 1, `(1, 4)`: 1, `(5, 7)`: 1, `(2, 7)`: 1, `9`: 1, `(2, 6)`: 1, `(0, 3)`: 1, `(3, 4)`: 1, `(1, 3)`: 1, `(7, 9)`: 1, `(8, 9)`: 1 | 0 / 0 | 0 | `padx`: 54, `pady`: 56, `padding`: 0 (**110**) |
| `real_copy_ui.py` | `(0, 7)`: 1 | `(0, 6)`: 2, `(4, 8)`: 1, `(0, 4)`: 1, `(8, 0)`: 1, `(6, 0)`: 1 | 0 / 0 | `14`: 1 | `padx`: 1, `pady`: 6, `padding`: 1 (**8**) |
| `recovery_center_ui.py` | `(7, 0)`: 3 | `(4, 6)`: 1, `(0, 2)`: 1, `(0, 6)`: 1, `(6, 0)`: 1, `(8, 0)`: 1 | 0 / 0 | `14`: 1 | `padx`: 3, `pady`: 5, `padding`: 1 (**9**) |
| `restore_ui.py` | `(0, 7)`: 2, `(9, 0)`: 3, `(7, 0)`: 2, `(0, 8)`: 1, `10`: 1, `12`: 1 | `4`: 1, `8`: 1, `10`: 1, `(6, 2)`: 1, `(5, 2)`: 1, `(2, 2)`: 1, `(5, 6)`: 1, `(0, 8)`: 1, `(5, 4)`: 1, `(0, 7)`: 1, `(0, 10)`: 1 | 0 / 0 | `14`: 1 | `padx`: 10, `pady`: 11, `padding`: 1 (**22**) |
| `selective_backup_ui.py` | `(8, 0)`: 17, `8`: 1, `(0, 8)`: 1 | `(0, 10)`: 1, `(0, 8)`: 1, `3`: 1, `2`: 1, `(5, 6)`: 1, `(4, 10)`: 1, `(1, 10)`: 1, `(5, 2)`: 1, `(2, 8)`: 1, `(4, 6)`: 1, `(0, 5)`: 1 | 0 / 0 | `8`: 6, `(12, 5)`: 1, `18`: 1 | `padx`: 19, `pady`: 11, `padding`: 8 (**38**) |
| `winget_programs_ui.py` | `(0, 7)`: 2, `(7, 7)`: 1, `(7, 0)`: 1 | `(0, 6)`: 2, `(0, 8)`: 2, `(6, 6)`: 1, `(0, 4)`: 1, `(0, 10)`: 1, `(8, 0)`: 1, `(4, 6)`: 1, `(6, 4)`: 1 | 0 / 0 | `14`: 3 | `padx`: 4, `pady`: 10, `padding`: 3 (**17**) |
| `workflow_ui.py` | `5`: 7, `(0, 10)`: 5, `18`: 3, `16`: 4, `17`: 3, `(0, 8)`: 3, `14`: 2, `(0, 9)`: 1, `(0, 13)`: 1 | `(0, 9)`: 4, `(0, 12)`: 2, `(10, 5)`: 2, `(9, 0)`: 2, `(0, 7)`: 1, `(0, 8)`: 1, `(0, 10)`: 1, `(15, 4)`: 1, `(7, 12)`: 1, `(0, 15)`: 1, `(8, 8)`: 1, `(0, 23)`: 1, `(12, 0)`: 1, `(10, 3)`: 1, `12`: 1, `(4, 7)`: 1, `(14, 12)`: 1, `(12, 1)`: 1, `(3, 10)`: 2, `(6, 11)`: 1, `(8, 3)`: 1, `(5, 10)`: 1, `(9, 8)`: 1, `(0, 16)`: 1, `(14, 7)`: 1, `(6, 13)`: 1, `(4, 0)`: 1 | 0 / 0 | `16`: 4, `15`: 1 | `padx`: 29, `pady`: 33, `padding`: 5 (**67**) |
| **TOTAL DO PROJETO** | **335 chamadas de `padx`** (36 valores distintos) | **343 chamadas de `pady`** (84 valores distintos) | **0 / 0** | **50 chamadas de `padding`** (15 valores distintos) | **728 chamadas de espaçamento** |

---

### 1.2 Tabela de fontes e tamanhos por arquivo

O aplicativo define a fonte base `('Segoe UI', 10)` no `ttk.Style` em `app.py:93`, e além disso possui **114 declarações explícitas de `font=`** e **22 chamadas a helpers com `size=`** (`self.label` em `app.py` e `self._label` em `optimization_ui.py`).

| Família e tamanho | Estilo | Onde aparece (arquivo: vezes) | Papel atual no código | Total |
|---|---|---|---|---|
| `Segoe UI`, `8` | normal / bold | `app.py`: 5 (`2` normal, `3` bold), `optimization_ui.py`: 1 (normal) | Subtítulo de marca, avisos na barra lateral, eixo do gráfico | **6** |
| `Segoe UI`, `9` | normal / bold | `app.py`: 15 (`12` normal, `3` bold), `optimization_ui.py`: 11 (`10` normal, `1` bold), `workflow_ui.py`: 4 (`1` normal, `3` bold), `deep_discovery_ui.py`: 1 (bold) | Rótulos secundários, etiquetas de cartões, notas de status, texto do anel | **31** |
| `Segoe UI`, `10` | normal / bold | `app.py`: 16 (`12` normal + default `size=10`, `4` bold), `after_format_ui.py`: 4 (bold), `completeness_audit_ui_v067.py`: 1, `completeness_audit_ui_v068.py`: 1, `deep_discovery_ui.py`: 1 (bold), `launcher_guide_ui.py`: 1 (bold), `multi_source_recovery_center_ui.py`: 1 (bold), `optimization_ui.py`: 9 (`6` normal, `3` bold via `_label`), `real_copy_ui.py`: 2 (bold), `recovery_center_ui.py`: 1 (bold), `restore_ui.py`: 3 (bold), `winget_programs_ui.py`: 2 (bold), `workflow_ui.py`: 4 (`2` normal, `2` bold) | Texto padrão de controles, cabeçalhos de subseção e tabelas | **46** |
| `Segoe UI`, `11` | normal / bold | `app.py`: 1 (normal), `multi_source_recovery_center_ui.py`: 2 (bold), `optimization_ui.py`: 3 (`1` normal, `2` bold), `winget_programs_ui.py`: 1 (bold) | Subtítulos de seções, `Listbox` de recuperação | **7** |
| `Segoe UI`, `12` | bold | `after_format_ui.py`: 1, `app.py`: 3, `deep_discovery_ui.py`: 1, `launcher_guide_ui.py`: 1, `optimization_ui.py`: 1, `real_copy_ui.py`: 1, `recovery_center_ui.py`: 1, `winget_programs_ui.py`: 1 | Títulos de diálogos e cabeçalhos de cartões | **10** |
| `Segoe UI`, `13` | normal / bold | `app.py`: 3 (`2` via `size=13`, `1` bold), `drive_safety_ui.py`: 1 (bold), `file_index_ui.py`: 1 (bold), `multi_source_offline_reopen_ui.py`: 1 (bold), `restore_ui.py`: 1 (bold), `workflow_ui.py`: 1 (bold) | Títulos de diálogos e seções | **8** |
| `Segoe UI`, `14` | normal / bold | `app.py`: 3 (`2` via `size=14`, `1` bold), `backup_preflight_scenario_ui.py`: 1 (bold), `multi_source_recovery_center_ui.py`: 1 (bold), `workflow_ui.py`: 1 (bold) | Nome do app na barra lateral, títulos de diálogos e abas | **6** |
| `Segoe UI`, `15` | normal / bold | `app.py`: 3 (`2` via `size=15`, `1` bold), `multi_backup_destinations_ui.py`: 1 (bold), `workflow_ui.py`: 1 (bold) | Títulos de abas (`review`, `history`), números de cartões e diálogos | **5** |
| `Segoe UI`, `16` | bold | `app_recovery_ui.py`: 1, `browser_recovery_ui.py`: 1, `completeness_audit_ui_v067.py`: 1, `completeness_audit_ui_v068.py`: 1, `deep_discovery_ui.py`: 1, `selective_backup_ui.py`: 1, `workflow_ui.py`: 3 | Títulos de diálogos e abas principais (`preservation`, `installation`) | **9** |
| `Segoe UI`, `17` | bold | `deep_discovery_ui.py`: 1 | Título da ficha individual de jogo/aplicativo | **1** |
| `Segoe UI`, `18` | bold | `workflow_ui.py`: 1 | Título da aba Visão Geral (`overview`) | **1** |
| `Segoe UI`, `19` | bold | `app.py`: 1 | Título do bloco principal (hero) da aba Início | **1** |
| `Segoe UI`, `21` | bold | `app.py`: 1 | Título dinâmico no cabeçalho da janela principal | **1** |
| `Segoe UI`, `22` | bold | `workflow_ui.py`: 1 | Valor numérico nos cartões de métricas da Preservação | **1** |
| `Segoe UI`, `23` | bold | `app.py`: 1 | Valor numérico nos cartões de métricas da aba Início | **1** |
| `Segoe UI Symbol`, `24` | normal | `app.py`: 1 | Ícone `◈` na barra lateral | **1** |
| `Consolas`, `9` | normal | `selective_backup_ui.py`: 2 | Caixa de caminhos de origem e log de backup seletivo | **2** |
| `Consolas`, `10` | normal | `app.py`: 4, `backup_preflight_scenario_ui.py`: 1, `optimization_ui.py`: 2, `workflow_ui.py`: 1 | Relatórios técnicos em `tk.Text` e `tk.Listbox` | **8** |
| `Consolas`, `11` | normal | `app.py`: 1 | `Listbox` do histórico de backups (`self.backup_list`) | **1** |
| **TOTAL DO PROJETO** | **19 combinações** | **21 arquivos (6 arquivos sem `font=` explícito usam apenas o default `ttk`)** | — | **146 definições** |

---

### 1.3 Tabela de cores escritas à mão (`#RRGGBB`)

Existem **73 ocorrências de códigos hexadecimais (`#RRGGBB`)** distribuídas pelos arquivos de tela, divididas entre constantes repetidas em 3 módulos (`app.py`, `optimization_ui.py`, `workflow_ui.py`) e literais escritos diretamente nos widgets.

| Código Hex | Nome / Papel atual | Onde é definido como constante | Onde é escrito direto no widget (sem constante) | Total de ocorrências `#...` |
|---|---|---|---|---|
| `#0C1220` | `BG` (Fundo principal escuro) | `app.py:57`, `optimization_ui.py:310`, `workflow_ui.py:26` | — | **3** (usado via `BG` 48 vezes) |
| `#192438` | `PANEL` (Fundo de painel, cartão e `tk.Text`/`tk.Listbox`) | `app.py:58`, `optimization_ui.py:310`, `workflow_ui.py:27` | `completeness_audit_ui_v067.py:64`, `completeness_audit_ui_v068.py:121`, `deep_discovery_ui.py:78,135,604,610`, `drive_safety_ui.py:112,145`, `selective_backup_ui.py:104,152` (**10 vezes inline**) | **13** (mais 49 usos via `PANEL`) |
| `#EFF4FF` | `TEXT` (Texto principal claro) | `app.py:59`, `optimization_ui.py:310`, `workflow_ui.py:28` | `completeness_audit_ui_v067.py:64`, `completeness_audit_ui_v068.py:121`, `deep_discovery_ui.py:82,135,136,604,611`, `drive_safety_ui.py:113,145`, `selective_backup_ui.py:104,152` (**13 vezes inline**) | **16** (mais 40 usos via `TEXT`) |
| `#9CAAC0` | `MUTED` (Texto secundário acinzentado) | `app.py:60`, `optimization_ui.py:310`, `workflow_ui.py:29` | — | **3** (usado via `MUTED` 46 vezes) |
| `#9C85FF` | `ACCENT` (Roxo de destaque / ação primária) | `app.py:61`, `optimization_ui.py:310`, `workflow_ui.py:30` | `deep_discovery_ui.py:81`, `selective_backup_ui.py:110` (**2 vezes inline**) | **5** (mais 22 usos via `ACCENT`) |
| `#5DDEB1` | `GREEN` (Verde de confirmação / seguro) | `app.py:62`, `optimization_ui.py:311`, `workflow_ui.py:32` | — | **3** (usado via `GREEN` 6 vezes) |
| `#10192A` | `SIDEBAR` (Fundo da barra lateral e rodapé) | `app.py:63` | — | **1** (usado via `SIDEBAR` 18 vezes) |
| `#2B3952` | `BORDER` (Borda de painéis, cartões e campos) | `app.py:64`, `optimization_ui.py:311`, `workflow_ui.py:31` | `drive_safety_ui.py:114,147` (**2 vezes inline**) | **5** (mais 26 usos via `BORDER`) |
| `#27334A` | `HOVER` (Fundo de item sob o cursor / cabeçalho de tabela) | `app.py:65` | — | **1** (usado via `HOVER` 7 vezes) |
| `#FFFFFF` | `WHITE` (Branco puro) | `app.py:66` | — | **1** (usado via `WHITE` 1 vez) |
| `#F3BE67` | `AMBER` (Amarelo/âmbar de aviso e atenção) | `app.py:67`, `optimization_ui.py:311`, `workflow_ui.py:33` | `completeness_audit_ui_v067.py:26`, `completeness_audit_ui_v068.py:59,64,146`, `deep_discovery_ui.py:617`, `selective_backup_ui.py:101` (**6 vezes inline**) | **9** (mais 25 usos via `AMBER`) |
| `#B2A2FF` | Roxo claro de botão primário ativo (`active`) | — | `app.py:100` | **1** |
| `#394C75` | Azul de linha selecionada em `Treeview` e `Listbox` | — | `app.py:122`, `deep_discovery_ui.py:611` | **2** |
| `#235781` | Azul de linha selecionada em `Listbox` (`backup_list` e recuperação) | — | `app.py:1176,2088` | **2** |
| `#334155` | Cinza-azulado do trilho do anel de progresso (`Canvas`) | — | `deep_discovery_ui.py:80` | **1** |
| `#314052` | Cinza-azulado das linhas de grade do gráfico térmico (`Canvas`) | — | `optimization_ui.py:774` | **1** |
| `#9a1c1c` | Vermelho escuro de alerta de privilégio elevado na restauração | — | `restore_ui.py:78` | **1** |
| `#C79229` | Âmbar escuro de aviso em múltiplos destinos | — | `multi_backup_destinations_ui.py:42` | **1** |
| **TOTAL** | **18 cores distintas** | **27 definições de constantes** (8 constantes repetidas em 3 arquivos) | **42 literais `#RRGGBB` direto nos widgets** | **69 literais `#RRGGBB`** |

---

### 1.4 Tabela de larguras, alturas e geometrias fixas por arquivo

| Arquivo | Geometria da janela (`geometry` / `minsize`) | Campos e seletores (`Entry` / `Combobox` `width`) | Áreas de texto e listas (`Text` / `Listbox` / `Canvas`) | Tabelas (`Treeview` `height`, `rowheight`, `column width`) | Quebra de linha fixa (`wraplength`) |
|---|---|---|---|---|---|
| `after_format_ui.py` | `1000x760`, min `720x520` | `Label(width=10)`: 1 | `Text(height=7)`: 1 | `height=5`: 1; cols: `110`, `230`, `120`, `120`, `170` | `950`: 2 |
| `app.py` | Principal: `1400x875` (min `1050x660`); Toplevels: `950x620`, `970x530`, `700x420`; Smoke: `320x120`; Sidebar: `width=244`; Footer: `height=39`; Stripe: `width=4` (2x) | `Entry(width=88)`: 1, `Entry(width=53)`: 1, `Entry(width=49)`: 1; `Combobox(width=38)`: 1 | `Text(height=19)`: 1 | `rowheight=34`; `height=2`: 3 (`tree`, `games_tree`, `apps_tree`); cols: `(220, 560, 145)`, `(180, 420, 140)`, `(220, 130, 110, 290, 130)` | `820`: 1, `190`: 1, `960`: 1, `1030`: 3, `920`: 2 |
| `app_recovery_ui.py` | `1080x780` (sem `minsize`) | `Entry(width=45)`: 1, `Entry(width=40)`: 1 | `Text(height=14)`: 1 | `height=7`: 1; cols: `110`, `280`, `520` | `1000`: 2 |
| `backup_preflight_scenario_ui.py` | `910x680`, min `730x560` | `Combobox(width=8)`: 1, `Entry(width=14)`: 1 | `Text(height=15)`: 1 | — | `850`: 2 |
| `browser_recovery_ui.py` | `880x680` (sem `minsize`) | `Combobox(width=105)`: 1 | `Text(height=10)`: 1 | — | `820`: 2 |
| `completeness_audit_ui_v067.py` | `1120x745`, min `870x590` | — | `Text` (sem `height` fixo): 1 | cols: `#0=300`, `status=220`, demais=`440` (4 tabelas) | `1050`: 2 |
| `completeness_audit_ui_v068.py` | `1210x790`, min `870x590` | — | `Text` (sem `height` fixo): 1 | cols: `#0=300`, `status=220`, demais=`440` (6 tabelas) | `1050`: 3, `1100`: 2, `1000`: 1 |
| `deep_discovery_ui.py` | Standalone: `1220x800`; Popups: `850x460`, `850x610` (sem `minsize`) | — | `Canvas(90x90)`: 1; `Text(height=5)`: 1; `Listbox(height=8)`: 1 | cols: `#0=275`, `(120, 70, 95, 135, 360, 110)` | `1160`: 1, `800`: 1, `770`: 1, `765`: 1, `1150`: 1 |
| `drive_safety_ui.py` | `975x680`, min `720x480` | — | `Text(height=9)`: 1 | `height=8`: 1; cols: `120`, `140`, `200`, `300` | `920`: 3 |
| `file_index_ui.py` | Dinâmica até `1040x690` (min `620x420`); Popup: `510x340` (min `410x260`) | `Entry(width=55)`: 1 | — | cols: `(85, 85, 110, 140, 110, 420)` | `790`: 2, `800`: 1, `465`: 1 |
| `launcher_guide_ui.py` | `960x620`, min `640x440` | — | `Text(height=11)`: 1 | `height=8`: 1; cols: `150`, `420`, `70`, `90`, `130` | `900`: 2 |
| `multi_backup_destinations_ui.py` | `790x490`, min `650x410` | `Combobox(width=65)`: 1 | `Listbox(height=11)`: 1 | — | `745`: 2 |
| `multi_source_offline_reopen_ui.py` | `880x540`, min `660x420` | — | — | `height=9`: 1; cols: `720`, `70` | `830`: 1 |
| `multi_source_recovery_center_ui.py` | `1050x710`, min `750x510` | — | — | `height=5` (cols `560, 250, 150`), `height=11` (cols `690, 105, 140`), `height=4` (cols `650, 190, 140`) | `1000`: 1 |
| `optimization_ui.py` | Popups: sem `geometry`, usam `Text(width=80, height=22)` e `Text(width=90, height=26)` | `Entry(width=16)`: 1, `Entry(width=6)`: 1; `Combobox(width=78)`: 1 | `Text(height=14)`: 6 (via `_output`), `Text(height=9)`: 1, `Text(80x22)`: 1, `Text(90x26)`: 1; `Canvas(height=125)`: 1 | — | `830`: 2, `900`: 8, `950`: 1, `850`: 1, `860`: 3 |
| `real_copy_ui.py` | `900x640`, min `680x460` | — | `Text(height=16)`: 1 | — | `850`: 1 |
| `recovery_center_ui.py` | `1100x620`, min `760x440` | — | — | cols: `#0=200`, `(130, 80, 90, 90, 95, 190)` | `1050`: 2 + dinâmico em `fit_detail` |
| `restore_ui.py` | `1130x740` (min `800x500`); Popup: `820x480` | — | — | cols: `660` (min `300`), `105` (min `90`), `140` (min `120`), `120` (min `100`) | `1080`: 3 |
| `selective_backup_ui.py` | Dinâmica até `1060x780` (min `640x480`) | — | `Text(height=3)`: 1, `Text(height=8)`: 1 | — | `990`: 1, `980`: 2, `960`: 2, `470`: 2, `430`: 4, `390`: 1, `410`: 5, `440`: 3, `475`: 2 |
| `winget_programs_ui.py` | `900x640` (min `640x440`); Popup resultado: `820x420`; Popup confirmação: sem `geometry` | — | `Text(width=60, height=3..14)`: 1 | `table` cols: `220, 110, 450`; `tree` cols: `300, 90, 110, 360` | `520`: 3, `780`: 1, `850`: 2 |
| `workflow_ui.py` | Pré-checagem: `1050x600`; Auditoria instalação: `1080x640` (sem `minsize`) | `Combobox(width=15)`: 1 | `Text(height=18)`: 1, `Text(height=10)`: 1 | `chosen` (`height=5`, cols `350, 110, 80, 420`), `tree` (`height=4`, cols `175, 95, 95, 95, 110, 340`), `linked` (`height=5`, cols `180, 250, 290, 200`), preflight (cols `390, 165, 120, 290`), audit (`height=12`, cols `125, 210, 430, 240`) | `880`: 1, `910`: 1, `900`: 1, `1000`: 2, `950`: 1, `990`: 1 |
| **TOTAL DO PROJETO** | **28 chamadas `geometry`**, **15 chamadas `minsize`** | **14 `Entry`/`Combobox` com `width` fixo** | **24 `Text`/`Listbox`/`Canvas` com tamanho fixo** | **29 tabelas `Treeview`** (`rowheight=34` global, 13 com `height` fixo) | **72 `wraplength` fixos** |

---

## 2. Diagnóstico

### 2.1 Valores parecidos para a mesma função (fragmentação de espaçamento)

1. **Margem interna da janela ou aba (`padding` do container raiz):**
   - Cada tela usa um número diferente para a mesma margem: `10` (`file_index_ui.py`), `12` (`app_recovery_ui.py`, `deep_discovery_ui.py`, `optimization_ui.py`), `14` (`after_format_ui.py`, `backup_preflight_scenario_ui.py`, `launcher_guide_ui.py`, `multi_backup_destinations_ui.py`, `multi_source_recovery_center_ui.py`, `real_copy_ui.py`, `recovery_center_ui.py`, `restore_ui.py`, `winget_programs_ui.py`), `15` (`completeness_audit_ui_v067.py`, `completeness_audit_ui_v068.py`, `multi_source_offline_reopen_ui.py`, `workflow_ui.py:99`), `16` (`browser_recovery_ui.py`, `drive_safety_ui.py`, `workflow_ui.py:50,367,414,463`), `18` (`selective_backup_ui.py`, `deep_discovery_ui.py:597`, abas de `app.py`) e `24` (aba Início de `app.py`).
2. **Espaço horizontal entre botões vizinhos na mesma barra (`padx`):**
   - Foram encontradas **20 variações diferentes** para separar botões lado a lado: `padx=3` (`app_recovery_ui.py`), `padx=4` (`completeness_audit_ui_v068.py`, `deep_discovery_ui.py`, `file_index_ui.py`), `padx=5` (`workflow_ui.py`), `padx=6` (`completeness_audit_ui_v068.py`), `padx=(0, 6)`, `padx=(0, 7)`, `padx=(7, 0)`, `padx=(7, 7)`, `padx=(7, 3)`, `padx=(0, 8)`, `padx=(8, 0)`, `padx=8`, `padx=(0, 9)`, `padx=(9, 0)`, `padx=(0, 10)`, `padx=(10, 0)`, `padx=10`, `padx=(0, 12)` e `padx=12`.
   - Em `workflow_ui.py:313-319`, a mesma barra de botões mistura `padx=(0, 8)` no primeiro botão com `padx=5` nos botões seguintes (o que gera `8 px` entre o 1º e o 2º, ou `13 px` somados, e `10 px` entre os demais).
3. **Espaçamento vertical (`pady`) sem relação de grupo:**
   - Existem **84 combinações diferentes de `pady`**, incluindo dezenas de valores ímpares (`1`, `3`, `5`, `7`, `9`, `11`, `13`, `15`, `17`, `19`, `23`).
   - Em várias telas, a distância entre um título de seção e a sua própria tabela é igual ou maior do que a distância entre duas seções diferentes, enfraquecendo a hierarquia por proximidade (ideia 1 do `docs/IDEIAS-PARA-APLICAR.md`).

### 2.2 Controles equivalentes com tamanhos, fontes e cores diferentes

1. **Caixas de texto (`tk.Text`) e listas (`tk.Listbox`) com e sem tema escuro:**
   - Como `tk.Text` e `tk.Listbox` são widgets clássicos do Tk (e não `ttk`), eles não herdam o `ttk.Style`.
   - Em `app.py`, `workflow_ui.py`, `optimization_ui.py`, `completeness_audit_ui_v067.py`, `completeness_audit_ui_v068.py`, `deep_discovery_ui.py`, `drive_safety_ui.py` e `selective_backup_ui.py`, eles recebem `bg='#192438', fg='#EFF4FF', relief='flat'` e `padx=14..16, pady=12..14`.
   - Já em **`after_format_ui.py`, `app_recovery_ui.py`, `backup_preflight_scenario_ui.py`, `browser_recovery_ui.py`, `launcher_guide_ui.py`, `multi_backup_destinations_ui.py`, `real_copy_ui.py` e `winget_programs_ui.py`**, os mesmos controles `tk.Text` e `tk.Listbox` são criados **sem `bg`, `fg`, `relief` nem `padx`/`pady`**, aparecendo com fundo branco padrão do Tk, borda 3D antiga e texto colado na borda (`0 px` de margem interna).
2. **Campos de entrada (`Entry`) e seletores (`Combobox`):**
   - `drive_safety_ui.py` coloca dois `ttk.Combobox` (linhas 101 e 103) e logo abaixo um `tk.Entry` puro (`size_input`, linha 111) estilizado manualmente com `highlightthickness=1, highlightbackground='#2B3952'`, resultando em alturas e bordas diferentes no mesmo formulário.
   - As larguras em caracteres (`width=8`, `14`, `15`, `16`, `38`, `40`, `45`, `49`, `53`, `55`, `65`, `78`, `88`, `105`) foram definidas caso a caso, mesmo quando o widget já usa `fill='x', expand=True`.
3. **Tabelas (`ttk.Treeview`) comprimidas:**
   - Na janela principal (`app.py`), `self.tree` (Documentos), `self.games_tree` (Jogos) e `self.apps_tree` (Aplicativos) têm `height=2` fixo (`app.py:514, 1298, 1315`). Mesmo que a área tenha `expand=True`, em janelas menores ou com escala de 125%/150% a tabela nasce reservando apenas 2 linhas de altura.
4. **Hierarquia tipográfica pulverizada:**
   - Há **15 tamanhos diferentes** de `Segoe UI` (`8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23`). Títulos de janelas modais equivalentes usam `12` num arquivo (`launcher_guide_ui.py`), `13` noutro (`restore_ui.py`), `14` noutro (`multi_source_recovery_center_ui.py`), `15` noutro (`multi_backup_destinations_ui.py`) e `16` noutro (`browser_recovery_ui.py`).

### 2.3 As 3 telas que mais ganhariam com o ajuste

1. **`workflow_ui.py` (Visão Geral, Preservação, Instalação do Windows, Pré-checagem e Auditoria):**
   - **Por que mais ganha:** É o coração do fluxo guiado do aplicativo. Hoje mistura `padding=15` e `padding=16`, usa dezenas de espaçamentos quebrados (`pady=(0, 23)`, `padx=(0, 13)`, `padx=17`, `pady=(14, 7)`, `padx=5`), repete as constantes de cor de `app.py` e empilha **5 barras horizontais seguidas de botões** na aba Preservação (`bar`, `checkbar`, `backupbar`, `backup_extra`, `auditbar`) com espaçamentos diferentes entre si. Organizar os grupos com a escala de 8 pontos (`8 px` dentro do grupo, `24 px` entre grupos) deixará a leitura imediata.
2. **`app.py` (Janela principal, barra lateral e as 7 abas nativas):**
   - **Por que mais ganha:** Concentra **248 chamadas de espaçamento** (34% de todo o projeto) e a configuração global do `ttk.Style`. Padronizar o `ttk.Style`, unificar a margem das abas (hoje dividida entre `14`, `16`, `18`, `22`, `24` e `26`), corrigir a altura mínima das tabelas (`height=2`) e substituir os `wraplength` fixos por ajuste dinâmico melhora todas as telas de uma vez.
3. **`optimization_ui.py` (Painel de Otimização e Telemetria — 9 sub-abas):**
   - **Por que mais ganha:** Tem **110 chamadas de espaçamento** com 31 variações de `pady` e 14 variações de `padx`, repete as constantes de cor no topo do módulo, usa `wraplength` fixos (`830`, `850`, `860`, `900`, `950`) e abre janelas de diagnóstico com `tk.Text(width=80, height=22)` e `tk.Text(width=90, height=26)` sem `minsize`, que podem estourar ou cortar botões em monitores com escala de 150%.

---

## 3. Proposta de escala

### 3.1 Módulo de constantes puro sem `tkinter` (`ui_scale.py`)

Para cumprir a regra de ouro do projeto (os testes rodam em servidor Linux **sem `tkinter`**), todas as constantes visuais ficarão num módulo Python puro (`ui_scale.py`), sem importar `tkinter` nem nenhum módulo de sistema.

```python
# ui_scale.py — Constantes puras de espaçamento, tipografia, tamanhos e cores (sem tkinter)

# 1. Escala base de espaçamento (Regra dos 8 pontos — docs/IDEIAS-PARA-APLICAR.md)
ESPACO_ZERO = 0
ESPACO_FINO = 2       # Exceção permitida: ajuste visual fino de 1–2 px (ex.: item da sidebar)
ESPACO_MINIMO = 4     # Entre rótulo e seu campo; ajuste compacto
ESPACO_P = 8          # Dentro de um grupo (botões vizinhos, itens de mesma linha)
ESPACO_M = 16         # Entre itens de um mesmo bloco; margem padrão de diálogo compacto
ESPACO_G = 24         # Entre grupos diferentes; espaço interno padrão de painel/aba
ESPACO_GG = 32        # Margem ampla; separação antes de barra principal de ações
ESPACO_SECAO = 48     # Entre seções grandes da página

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
PADDING_CABECALHO_TABELA = (ESPACO_P, ESPACO_P) # (8, 8)  — Treeview.Heading
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
```

---

### 3.2 Mapeamento dos valores antigos para a nova escala (por contexto)

Seguindo a diretriz de `docs/IDEIAS-PARA-APLICAR.md` (*"trocar os valores antigos olhando o contexto, sem substituição cega"*):

| Contexto de uso na tela | Valores antigos encontrados no código | Novo token e valor na escala |
|---|---|---|
| Ajuste visual fino entre itens colados na barra lateral | `pady=2` | `ESPACO_FINO` (`2`) |
| Distância vertical entre um rótulo/título e o seu próprio campo ou tabela | `pady=1`, `2`, `3`, `4`, `5`, `(0, 2)`, `(0, 4)`, `(0, 5)`, `(2, 2)`, `(4, 2)` | `ESPACO_MINIMO` (`4`) ou `ESPACO_ROTULO_CAMPO` (`(0, 4)`) |
| Espaço horizontal entre botões ou controles vizinhos na mesma linha | `padx=3`, `4`, `5`, `6`, `8`, `(0, 6)`, `(0, 7)`, `(0, 8)`, `(0, 9)`, `(0, 10)`, `(7, 0)`, `(8, 0)`, `(9, 0)`, `(10, 0)` | `ESPACO_P` (`8`) — `padx=(0, 8)` para alinhamento à esquerda ou `(8, 0)` à direita |
| Distância vertical entre linhas/itens que pertencem ao mesmo grupo | `pady=6`, `7`, `8`, `9`, `10`, `(0, 6)`, `(0, 7)`, `(0, 8)`, `(0, 9)`, `(2, 6)`, `(3, 8)` | `ESPACO_P` (`8`) ou `ESPACO_DENTRO_GRUPO` (`(0, 8)`) |
| Espaço interno (`padding`) de sub-abas de `ttk.Notebook` e `LabelFrame` compacto | `padding=5`, `8`, `(10, 2)`, `(12, 5)` | `PADDING_ABA_NOTEBOOK` (`8`) |
| Margem interna de janelas `Toplevel` e painéis compactos | `padding=10`, `12`, `14`, `15`, `16`, `18`; `padx=12`, `14`, `15` | `PADDING_DIALOGO` (`16`) |
| Espaço interno de caixas `tk.Text` | `padx=14, pady=12`, `padx=14, pady=14`, `padx=16, pady=13`, `padx=16, pady=6`, ou sem `padx`/`pady` | `padx=ESPACO_M` (`16`), `pady=ESPACO_P` (`8`) |
| Distância vertical entre blocos de uma mesma seção | `pady=11`, `12`, `13`, `14`, `15`, `16`, `(0, 12)`, `(0, 14)`, `(0, 15)`, `(0, 16)`, `(12, 10)` | `ESPACO_M` (`16`) ou `ESPACO_ENTRE_BLOCOS` (`(0, 16)`) |
| Margem interna de abas principais (`app.py`, `workflow_ui.py`) e separação entre grupos distintos | `padx=18`, `20`, `22`, `24`, `26`; `pady=18`, `19`, `20`, `22`, `23` | `PADDING_PAINEL` / `ESPACO_G` (`24`) |
| Margem ampla de cabeçalho de marca ou bloco hero | `pady=(28, 30)`, `pady=(0, 22)` | `ESPACO_GG` (`32`) |
| Preenchimento de botões (`TButton`, `Primary.TButton`, `Secondary.TButton`) | `padding=(14, 10)`, `(16, 11)`, `(13, 10)` (alturas desiguais) | `PADDING_BOTAO = (16, 8)` (mesma altura nos 3 estilos) |

---

### 3.3 Cuidado com a escala do Windows (125% e 150%) e dados ruins (Break UI)

Em monitores modernos com escala de **125% (120 DPI)** ou **150% (144 DPI)** no Windows:
- As fontes em pontos (`('Segoe UI', 10)`) crescem automaticamente com o DPI do Windows, mas geometrias em pixels fixos (`geometry('900x640')`, `wraplength=1050`) não crescem na mesma proporção se a janela ultrapassar a área útil da tela (`winfo_screenwidth()` / `winfo_screenheight()`).
- **Consequência prática:** Em 150% num monitor Full HD (1920×1080 equivalendo a 1280×720 lógicos), uma janela fixa de `1400x875` ou `1220x800` nasce maior que a tela, escondendo a barra inferior de botões atrás da barra de tarefas do Windows.

**Medidas propostas no `ui_scale.py` e nas fatias:**
1. **Função pura de geometria segura (`safe_window_geometry(desired_w, desired_h, screen_w, screen_h, margin=80)`):**
   - Calcula largura e altura limitadas à área útil da tela (como `file_index_ui.py:30` e `selective_backup_ui.py:55` já fazem bem, mas levando para todas as 21 telas). Testável sem `tkinter` passando inteiros `(1400, 875, 1280, 720)`.
2. **Função pura de escala (`scale_px(value, factor=1.0)`):**
   - Permite converter valores da escala base quando o fator de escala da janela for maior que `1.0`, mantendo múltiplos inteiros pares.
3. **Quebra de linha (`wraplength`) dinâmica em vez de pixel fixo:**
   - Substituir gradualmente os 72 `wraplength` fixos pelo padrão já usado com sucesso em `recovery_center_ui.py:107` (`<Configure>` ajustando `wraplength = max(320, event.width - 2 * PADDING_DIALOGO)`), evitando tanto texto cortado em janela estreita quanto espaço vazio em janela maximizada.
4. **Barras de ação inferiores sempre visíveis:**
   - Empacotar barras de botões de rodapé com `side='bottom', fill='x'` antes do widget expansível (`Treeview` ou `Text` com `fill='both', expand=True`), garantindo que em 125%/150% quem encolhe é a área de rolagem, e nunca os botões de ação.
5. **Teste com "dados ruins" (Princípio Break UI — ideia 3 de `docs/IDEIAS-PARA-APLICAR.md`):**
   - Em cada fatia, conferir a tela com:
     - Caminho muito longo (mais de 180 caracteres, sem espaços);
     - Nome de jogo/aplicativo longo com acentos e símbolos;
     - Lista vazia (`0` itens), lista com `1` item e lista com `1.000` itens.

---

## 4. Fatias (uma tela por PR, da menor para a maior)

A implementação na **Etapa 2** só começará depois que esta proposta for revisada e mesclada e o Raphael escolher a primeira tela. Cada fatia será uma PR separada em rascunho.

| Ordem | Fatia / Branch sugerido | Escopo (1 módulo por PR) | Risco | Critério de aceite | Como o Raphael deve conferir na tela |
|---|---|---|---|---|---|
| **0** | `gemini/P4-04-fatia-0-escala` | Criar `ui_scale.py` (sem `tkinter`) + `tests/test_ui_scale.py` | Mínimo (não toca em nenhuma tela) | Módulo importa e passa nos testes com `sys.modules['tkinter'] = None`; valida constantes, múltiplos da escala e `safe_window_geometry`. | Não muda nenhuma tela ainda; conferir apenas os testes verdes. |
| **1** | `gemini/P4-04-fatia-1-launcher-guide` | `launcher_guide_ui.py` (6 chamadas de espaço, somente leitura) | Muito baixo | Usa `PADDING_DIALOGO`, `ESPACO_P` e `ESPACO_MINIMO`; `guide` (`tk.Text`) recebe tema escuro (`COR_PAINEL`, `COR_TEXTO`, `PADDING_CAIXA_TEXTO`); geometria segura. | Abrir "Orientação de launchers": caixa de texto no tema escuro, margens uniformes de 16 px, botões inferiores visíveis ao reduzir a janela. |
| **2** | `gemini/P4-04-fatia-2-multi-destinos` | `multi_backup_destinations_ui.py` (8 chamadas de espaço) | Muito baixo | Usa constantes de `ui_scale.py`; `listbox` no tema escuro; `Combobox` alinhado; sem cor `#C79229` solta (usa `COR_ALERTA`). | Abrir "Múltiplos destinos de backup": lista no tema escuro, botões alinhados, aviso legível e janela redimensionável sem cortar botões. |
| **3** | `gemini/P4-04-fatia-3-reabertura-offline` | `multi_source_offline_reopen_ui.py` (7 chamadas de espaço) | Muito baixo | Substitui `padding=15`, `padx=(7, 3)`, `pady=(7, 8)` pelos tokens de `ui_scale.py`; geometria segura. | Abrir "Reabrir cópias salvas": botões "Escolher pasta", "Adicionar à lista" e "Abrir" com espaçamento uniforme de 8 px. |
| **4** | `gemini/P4-04-fatia-4-copia-real` | `real_copy_ui.py` (8 chamadas de espaço) | Baixo | Substitui `padding=14` e `padx=(0, 7)` por `PADDING_DIALOGO` e `ESPACO_ENTRE_BOTOES`; `text` (`tk.Text`) recebe tema escuro e `PADDING_CAIXA_TEXTO`. | Abrir diálogo de cópia: área de relatório no tema escuro com margem interna, barra de botões inferior alinhada. |
| **5** | `gemini/P4-04-fatia-5-centro-recuperacao` | `recovery_center_ui.py` (9 chamadas de espaço) | Baixo | Substitui `padding=14` e `padx=(7, 0)` por tokens da escala; título usa `TAMANHO_TITULO_MODAL`. | Abrir "Centro de recuperação" pelo Histórico: tabela, detalhes e botões inferiores alinhados na grade de 8 px. |
| **6** | `gemini/P4-04-fatia-6-restaurar-navegador` | `browser_recovery_ui.py` (10 chamadas de espaço) | Baixo | `details` (`tk.Text`) recebe tema escuro e `PADDING_CAIXA_TEXTO`; espaçamentos na escala de 8 pontos; geometria com `minsize`. | Na aba Navegadores, clicar em "Restaurar favoritos e senhas": caixa de detalhes escura e grupos espaçados em 8/16/24 px. |
| **7** | `gemini/P4-04-fatia-7-centro-multi-origem` | `multi_source_recovery_center_ui.py` (11 chamadas de espaço) | Baixo | Substitui `padding=14`, `padx=(14, 5)` e `pady=(3, 10)` por tokens de `ui_scale.py`; hierarquia entre as 3 tabelas. | Abrir centro de recuperação multi-origem: separação clara entre "Cópias disponíveis", "Arquivos selecionáveis" e "Arquivos já restaurados". |
| **8** | `gemini/P4-04-fatia-8-pos-formatacao` | `after_format_ui.py` (11 chamadas de espaço) | Baixo | Substitui `padding=14`, `padx=6`, `pady=(6, 6)` pelos tokens; `guide` (`tk.Text`) no tema escuro. | Clicar em "Acabei de formatar o PC": passos numerados alinhados, guia inferior no tema escuro, botões sempre visíveis. |
| **9** | `gemini/P4-04-fatia-9-cenario-preflight` | `backup_preflight_scenario_ui.py` (12 chamadas de espaço) | Baixo | Padroniza `LabelFrame` e espaçamentos; `output` (`tk.Text`) recebe tema escuro e `PADDING_CAIXA_TEXTO`. | Na aba Diagnóstico, abrir "Simular cenário de pré-checagem": caixas de unidades e resultado alinhados e relatório escuro. |
| **10** | `gemini/P4-04-fatia-10-winget` | `winget_programs_ui.py` (17 chamadas de espaço) | Baixo | Padroniza os 3 diálogos do módulo com `ui_scale.py`; `box` (`tk.Text`) no tema escuro; `minsize` nos popups. | Na restauração, abrir "Programas para reinstalar (WinGet)": tabela, confirmação e resultado com margens de 16 px e botões espaçados em 8 px. |
| **11** | `gemini/P4-04-fatia-11-seguranca-unidades` | `drive_safety_ui.py` (18 chamadas de espaço) | Baixo | Substitui cores hex inline (`#192438`, `#EFF4FF`, `#2B3952`) por constantes de `ui_scale.py`; alinha campos do formulário e botões. | Na aba Diagnóstico, abrir "Diagnóstico de independência física": campos de origem/destino/tamanho alinhados e detalhes com margem interna. |
| **12** | `gemini/P4-04-fatia-12-recuperar-apps` | `app_recovery_ui.py` (20 chamadas de espaço) | Baixo | Substitui `padding=12`, `padx=3`, `padx=4`, `pady=5`, `pady=7` pela escala; `output` (`tk.Text`) no tema escuro; adiciona `minsize`. | Na aba Recuperação, abrir assistente de aplicativos/jogos: barras de botões com espaço de 8 px e painel de saída no tema escuro. |
| **13** | `gemini/P4-04-fatia-13-restauracao` | `restore_ui.py` (22 chamadas de espaço) | Médio-baixo | Substitui `padding=14`, `padx=(0, 7)`, `padx=(9, 0)` e `#9a1c1c` pelos tokens de `ui_scale.py`; garante rodapé visível. | Abrir restauração de um backup: barra de filtro, árvore de arquivos e botões inferiores alinhados mesmo reduzindo a janela. |
| **14** | `gemini/P4-04-fatia-14-indice-arquivos` | `file_index_ui.py` (24 chamadas de espaço) | Médio-baixo | Padroniza `header`, `main`, `controls` e popup com `ui_scale.py`; botões de unidade e paginação com `ESPACO_P`. | Abrir "Índice completo de arquivos": botões de unidades no topo, busca e paginação alinhados na grade de 8 px. |
| **15** | `gemini/P4-04-fatia-15-auditoria-v067-v068` | `completeness_audit_ui_v067.py` e `completeness_audit_ui_v068.py` (14 + 37 chamadas) | Médio | Substitui `padding=15`, `padx=4`, `padx=6`, `(0, 9)` e cores hex inline por `ui_scale.py`; padroniza abas internas. | Abrir "3. Auditar completude antes de formatar": abas da auditoria, tabelas e barras de botões inferiores alinhadas. |
| **16** | `gemini/P4-04-fatia-16-backup-seletivo` | `selective_backup_ui.py` (38 chamadas de espaço) | Médio | Substitui cores hex inline e `padx=(8, 0)` repetido 17 vezes por tokens de `ui_scale.py`; `wraplength` adaptável nas abas. | Abrir "Backup seletivo com verificação": barra superior, caixa de origem, abas de telemetria e log inferior alinhados. |
| **17** | `gemini/P4-04-fatia-17-varredura-detalhada` | `deep_discovery_ui.py` (39 chamadas de espaço) | Médio | Substitui `padding=12`, `padding=18`, `padx=4` e 11 cores hex inline por `ui_scale.py`; padroniza popup de volumes e ficha do item. | Na aba Início (ou Varredura detalhada): anel de progresso, abas de categoria, barra de ações e ficha do jogo/app alinhados. |
| **18** | `gemini/P4-04-fatia-18-workflow` | `workflow_ui.py` (67 chamadas de espaço) | Médio-alto | Remove constantes de cor duplicadas (importa de `ui_scale.py`); padroniza Visão Geral, Preservação, Instalação e diálogos; organiza as barras de botões da Preservação com `ESPACO_P` e `ESPACO_G`. | Conferir abas Visão Geral, Preservação e Instalação: cartões de métricas alinhados, barras de botões da Preservação com espaçamento limpo e uniforme. |
| **19** | `gemini/P4-04-fatia-19-otimizacao` | `optimization_ui.py` (110 chamadas de espaço) | Médio-alto | Remove constantes de cor duplicadas; padroniza as 9 sub-abas (`padx=16, pady=16`), barras de botões (`ESPACO_ENTRE_BOTOES`) e janelas de relatório com ` safe_window_geometry` e `minsize`. | Na aba Otimização: percorrer as 9 sub-abas conferindo alinhamento de botões, campos de cenário/PresentMon e janelas de check-up. |
| **20** | `gemini/P4-04-fatia-20-app-principal` | `app.py` (248 chamadas de espaço + `ttk.Style`) | Alto (por último) | Conecta `ttk.Style` ao `ui_scale.py` (`PADDING_BOTAO`, `PADDING_CAMPO_ENTRADA`, `ALTURA_LINHA_TABELA`); unifica margens das abas; corrige `height=2` das `Treeview` para `ALTURA_MINIMA_TABELA_LINHAS`; aplica `safe_window_geometry`. | Conferir a barra lateral, cabeçalho, rodapé e as abas Início, Documentos, Revisão, Navegadores, Histórico, Jogos e Apps, Diagnóstico e Recuperação em janela normal e reduzida (e em 125%/150%). |

---

## 5. Fora do escopo

Para garantir segurança total e respeito às regras do projeto (`CLAUDE.md`, `GEMINI.md` e `docs/REGRAS.md`), ficam **estritamente fora do escopo** de todas as fatias do P4-04:

1. **Nenhuma mudança nas travas de segurança:**
   - As travas `copy_authorized`, `physical_independence_verified`, `ready_for_format`, `installation_authorized` e `deletions_authorized` não serão tocadas em nenhuma hipótese.
2. **Nenhuma mudança de lógica ou de fluxo:**
   - Nenhum comando, callback, thread, cálculo de plano, leitura de disco, manifesto ou verificação SHA-256 será alterado. "Não copiar" nunca significa apagar.
3. **Nenhuma mudança nos textos exibidos ao usuário:**
   - Nenhuma string de interface, aviso de segurança ou módulo `*_texts.py` será alterado (preservando integralmente as regras R-03, R-62, R-74 e R-88 e todos os testes que conferem textos).
4. **Nenhuma biblioteca externa nova:**
   - Não serão instaladas bibliotecas como `customtkinter`, `ttkbootstrap` ou pacotes de ícones externos sem aprovação explícita do Raphael. Todo o ajuste usa o `tkinter` / `ttk` padrão da biblioteca do Python.
5. **Nenhum componente de web no app desktop:**
   - Componentes React, Tailwind, CSS ou animações em JavaScript (ideias 2, 3, 4 e 5 de `docs/IDEIAS-PARA-APLICAR.md`) pertencem exclusivamente à central de projetos web / PCRO Monitor e não entram no aplicativo Tkinter.
