"""Tk dialog for opt-in multiple destination folders.

Destination KIND is user supplied (no automatic hardware classification).
The cloud-synced folder is only a local directory; provider API/OAuth is not
available and upload remains unverified. Never format or remove files.
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ui_scale import (
    COR_ALERTA,
    COR_BORDA,
    COR_PAINEL,
    COR_SELECAO,
    COR_TEXTO,
    ESPACO_DENTRO_GRUPO,
    ESPACO_ENTRE_BOTOES,
    ESPACO_MINIMO,
    ESPACO_P,
    FONTE_UI,
    PADDING_DIALOGO,
    TAMANHO_CORPO,
    TAMANHO_TITULO_MODAL,
    safe_window_geometry,
    safe_wraplength,
)

DESIRED_WIDTH = 790
DESIRED_HEIGHT = 490
MIN_WIDTH = 650
MIN_HEIGHT = 410

KINDS = {
    'local': 'Outro disco do computador (tipo declarado)',
    'external': 'HD/SSD/pendrive externo (tipo declarado)',
    'synced_folder': 'Pasta de nuvem já sincronizada (envio não verificado)',
}


def open_destination_picker(parent, initial, on_save):
    """Set user-selected paths only, no I/O. Calls on_save on explicit click."""
    w = tk.Toplevel(parent)
    w.title('Destinos múltiplos do backup • seleção explícita')
    w.geometry(safe_window_geometry(
        DESIRED_WIDTH,
        DESIRED_HEIGHT,
        w.winfo_screenwidth(),
        w.winfo_screenheight(),
        min_w=MIN_WIDTH,
        min_h=MIN_HEIGHT,
    ))
    w.minsize(MIN_WIDTH, MIN_HEIGHT)
    w.transient(parent)
    w.grab_set()
    body = ttk.Frame(w, padding=PADDING_DIALOGO)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='Para onde copiar o backup?',
              font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold')).pack(anchor='w')
    intro_label = ttk.Label(body, text=(
        'Selecione de 1 a 8 pastas existentes em discos diferentes de C:. '
        'Cada destino terá uma cópia local com SHA-256. '
        'As etiquetas abaixo são informadas por você, não verificam o tipo físico.'),
        wraplength=745)
    intro_label.pack(anchor='w', pady=ESPACO_P)
    cloud_label = ttk.Label(body, text=(
        'Nuvem: escolha uma pasta de um cliente sincronizador já instalado. '
        'O aplicativo NÃO conecta Google Drive/OneDrive por API nesta versão e '
        'NÃO pode atestar que a sincronização para o servidor terminou. '
        'Se essa pasta estiver no C:, esta etapa não permitirá o backup nela.'),
        wraplength=745, foreground=COR_ALERTA)
    cloud_label.pack(anchor='w', pady=ESPACO_DENTRO_GRUPO)
    kind_label = tk.StringVar(value=KINDS['local'])
    ttk.Combobox(body, textvariable=kind_label, state='readonly', width=65,
                 values=tuple(KINDS.values())).pack(
                     anchor='w', fill='x', pady=(0, ESPACO_MINIMO))
    label_to_kind = {label: key for key, label in KINDS.items()}
    safety_label = ttk.Label(
        body,
        text='O dispositivo ainda será avaliado pelas verificações de segurança.',
        wraplength=730,
    )
    safety_label.pack(anchor='w', pady=(0, ESPACO_P))
    entries = [dict(p) for p in initial if isinstance(p, dict)
               and p.get('kind') in KINDS and isinstance(p.get('path'), str)]

    def _update_wrap(event):
        if event.widget is body and event.width > 1:
            wrap = safe_wraplength(event.width, padding=PADDING_DIALOGO)
            intro_label.configure(wraplength=wrap)
            cloud_label.configure(wraplength=wrap)
            safety_label.configure(wraplength=wrap)

    body.bind('<Configure>', _update_wrap)

    row = ttk.Frame(body)
    row.pack(side='bottom', fill='x')

    listbox = tk.Listbox(
        body,
        height=11,
        exportselection=False,
        bg=COR_PAINEL,
        fg=COR_TEXTO,
        selectbackground=COR_SELECAO,
        selectforeground=COR_TEXTO,
        relief='flat',
        highlightthickness=1,
        highlightbackground=COR_BORDA,
        font=(FONTE_UI, TAMANHO_CORPO),
    )
    listbox.pack(fill='both', expand=True, pady=(0, ESPACO_P))

    def refresh():
        listbox.delete(0, 'end')
        for i, item in enumerate(entries):
            listbox.insert('end', f'{i+1}. {KINDS[item["kind"]]} — {item["path"]}')

    def add():
        if len(entries) >= 8:
            return messagebox.showwarning('Limite', 'Máximo de 8 destinos.', parent=w)
        selected = filedialog.askdirectory(parent=w, title='Escolha uma pasta existente para backup')
        if selected:
            entries.append({'path': str(Path(selected)),
                            'kind': label_to_kind[kind_label.get()]})
            refresh()

    def remove():
        index = listbox.curselection()
        if index:
            entries.pop(index[0])
            refresh()

    def save():
        if not entries:
            return messagebox.showwarning('Seleção vazia', 'Escolha ao menos uma pasta.', parent=w)
        on_save([dict(item) for item in entries])
        w.destroy()

    ttk.Button(row, text='Adicionar pasta escolhida', command=add).pack(
        side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(row, text='Remover selecionada', command=remove).pack(side='left')
    ttk.Button(row, text='Cancelar', command=w.destroy).pack(side='right')
    ttk.Button(row, text='Usar estes destinos', command=save).pack(
        side='right', padx=ESPACO_ENTRE_BOTOES)
    refresh()
    return w
