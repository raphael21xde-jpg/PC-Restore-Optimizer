"""Tk-only review dialog for simulated backup destinations; never writes files."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from backup_preflight_scenario import scenario_text, simulate_backup_preflight
from ui_scale import (
    COR_BORDA,
    COR_PAINEL,
    COR_SELECAO,
    COR_TEXTO,
    ESPACO_G,
    ESPACO_M,
    ESPACO_MINIMO,
    ESPACO_P,
    FONTE_MONO,
    FONTE_UI,
    PADDING_ABA_NOTEBOOK,
    PADDING_CAIXA_TEXTO,
    PADDING_DIALOGO,
    TAMANHO_CORPO,
    TAMANHO_TITULO_MODAL,
    safe_window_geometry,
    safe_wraplength,
)

DESIRED_WIDTH = 910
DESIRED_HEIGHT = 680
MIN_WIDTH = 730
MIN_HEIGHT = 560


def show_backup_preflight_scenario(app):
    """Use a previously collected inventory. All computations are in memory."""
    report = getattr(app, 'diagnostic_data', None) or {}
    snapshot = report.get('disks') if isinstance(report, dict) else None
    volumes = snapshot.get('volumes', []) if isinstance(snapshot, dict) else []
    volumes = volumes if isinstance(volumes, list) else []
    letters = sorted({str(row.get('DriveLetter') or '').strip().upper().rstrip(':')
                      for row in volumes if isinstance(row, dict)
                      and isinstance(row.get('DriveLetter'), str)
                      and len(row.get('DriveLetter').strip().rstrip(':')) == 1})
    letters = [x for x in letters if len(x) == 1 and x.isascii() and x.isalpha()]
    if not letters:
        messagebox.showwarning('Simulação indisponível',
            'Execute Analisar computador e discos antes de simular.', parent=app)
        return None

    window = tk.Toplevel(app)
    window.title('Atualização #20 • Simular segurança de destino (somente leitura)')
    window.geometry(safe_window_geometry(
        DESIRED_WIDTH,
        DESIRED_HEIGHT,
        window.winfo_screenwidth() or 0,
        window.winfo_screenheight() or 0,
        min_w=MIN_WIDTH,
        min_h=MIN_HEIGHT,
    ))
    window.minsize(MIN_WIDTH, MIN_HEIGHT)
    window.transient(app)
    window.grab_set()
    body = ttk.Frame(window, padding=PADDING_DIALOGO)
    body.pack(fill='both', expand=True)
    ttk.Label(
        body,
        text='Simular um plano de backup sem copiar arquivos',
        font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold'),
    ).pack(anchor='w')
    intro_label = ttk.Label(
        body,
        text=(
            'Escolha as unidades de origem, o destino e um tamanho aproximado em GiB. '
            'O aplicativo reutiliza os metadados do último diagnóstico, sem novas '
            'operações em disco. Mesmo um cenário sem bloqueios não fica aprovado.'),
        wraplength=850,
    )
    intro_label.pack(anchor='w', pady=ESPACO_P)
    choices = ttk.LabelFrame(
        body,
        text='1. Quais unidades contêm dados de origem?',
        padding=PADDING_ABA_NOTEBOOK,
    )
    choices.pack(fill='x', pady=(0, ESPACO_P))
    selected = {}
    for letter in letters:
        var = tk.BooleanVar(value=False)
        selected[letter] = var
        ttk.Checkbutton(choices, text=letter+':', variable=var).pack(
            side='left',
            padx=(ESPACO_MINIMO, ESPACO_M),
        )

    options = ttk.Frame(body)
    options.pack(fill='x', pady=(0, ESPACO_P))
    ttk.Label(options, text='2. Destino:').pack(side='left')
    target = tk.StringVar(value='')
    combo = ttk.Combobox(options, textvariable=target, values=tuple(x+':' for x in letters),
                         state='readonly', width=8)
    combo.pack(side='left', padx=(ESPACO_P, ESPACO_G))
    ttk.Label(options, text='3. Tamanho estimado (GiB):').pack(side='left')
    size = tk.StringVar(value='')
    ttk.Entry(options, textvariable=size, width=14).pack(side='left', padx=ESPACO_P)
    ttk.Label(options, text='Ex.: 20 ou 20,5').pack(side='left')

    capacity_label = ttk.Label(
        body,
        text=(
            'A capacidade considera uma reserva aproximada de 10 GiB ou 10% do espaço '
            'livre. O destino no mesmo disco lógico pode ser bloqueado. Storage Spaces, '
            'discos dinâmicos e BOOTMGR exigem revisão independente.'),
        wraplength=850,
    )
    capacity_label.pack(anchor='w', pady=(0, ESPACO_P))

    def _update_wrap(event):
        if event.widget is body and event.width > 1:
            wrap = safe_wraplength(event.width, padding=PADDING_DIALOGO)
            intro_label.configure(wraplength=wrap)
            capacity_label.configure(wraplength=wrap)

    body.bind('<Configure>', _update_wrap)

    final = ttk.Frame(body)
    final.pack(side='bottom', fill='x', pady=(ESPACO_P, 0))

    section = ttk.LabelFrame(
        body,
        text='Resultado da simulação',
        padding=PADDING_ABA_NOTEBOOK,
    )
    section.pack(fill='both', expand=True)
    scroller = ttk.Scrollbar(section)
    scroller.pack(side='right', fill='y')
    output = tk.Text(
        section,
        height=15,
        wrap='word',
        bg=COR_PAINEL,
        fg=COR_TEXTO,
        insertbackground=COR_TEXTO,
        selectbackground=COR_SELECAO,
        selectforeground=COR_TEXTO,
        relief='flat',
        highlightthickness=1,
        highlightbackground=COR_BORDA,
        padx=PADDING_CAIXA_TEXTO[0],
        pady=PADDING_CAIXA_TEXTO[1],
        font=(FONTE_MONO, TAMANHO_CORPO),
        yscrollcommand=scroller.set,
    )
    output.pack(fill='both', expand=True)
    scroller.config(command=output.yview)
    output.insert('1.0', 'Selecione as origens, o destino e um tamanho estimado. '
                        'Nenhuma cópia será realizada.')
    output.configure(state='disabled')

    state = {'last_text': ''}

    def invalidate_result(*_):
        # A displayed preview is tied to exactly the input that produced it.
        # After edits, do not allow copying the previous plan as the new one.
        state['last_text'] = ''
        output.configure(state='normal')
        output.delete('1.0', 'end')
        output.insert('1.0', 'Dados alterados. Clique em Simular para gerar '
                            'um relatório atualizado (somente leitura).')
        output.configure(state='disabled')

    for variable in (*selected.values(), target, size):
        variable.trace_add('write', invalidate_result)

    def calculate():
        # Erase previous copy eligibility even if validation raises.
        state['last_text'] = ''
        origins = [letter for letter, var in selected.items() if var.get()]
        try:
            result = simulate_backup_preflight(
                snapshot, source_letters=origins,
                target_letter=target.get(), estimate_gib=size.get())
            content = scenario_text(result)
            state['last_text'] = content
            output.configure(state='normal')
            output.delete('1.0', 'end')
            output.insert('1.0', content)
            output.configure(state='disabled')
        except ValueError as exc:
            output.configure(state='normal')
            output.delete('1.0', 'end')
            output.insert('1.0', 'Simulação não realizada: '+str(exc))
            output.configure(state='disabled')
            messagebox.showwarning('Preencha a simulação', str(exc), parent=window)

    def copy_text():
        if not state['last_text']:
            return messagebox.showinfo('Sem resultado', 'Simule primeiro.', parent=window)
        window.clipboard_clear()
        window.clipboard_append(state['last_text'])
        window.update()
        messagebox.showinfo('Texto copiado', 'Cole o relatório no chat para análise.', parent=window)

    ttk.Button(final, text='Simular — somente leitura', command=calculate).pack(side='left')
    ttk.Button(final, text='Copiar relatório', command=copy_text).pack(side='left', padx=(ESPACO_P, 0))
    ttk.Button(final, text='Fechar', command=window.destroy).pack(side='right')
    return window
