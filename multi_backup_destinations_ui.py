"""Tk dialog for opt-in multiple destination folders.

Destination KIND is user supplied (no automatic hardware classification).
The cloud-synced folder is only a local directory; provider API/OAuth is not
available and upload remains unverified. Never format or remove files.
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

KINDS = {
    'local': 'Outro disco do computador (tipo declarado)',
    'external': 'HD/SSD/pendrive externo (tipo declarado)',
    'synced_folder': 'Pasta de nuvem já sincronizada (envio não verificado)',
}


def open_destination_picker(parent, initial, on_save):
    """Set user-selected paths only, no I/O. Calls on_save on explicit click."""
    w = tk.Toplevel(parent)
    w.title('Destinos múltiplos do backup • seleção explícita')
    w.geometry('790x490')
    w.minsize(650, 410)
    w.transient(parent)
    w.grab_set()
    body = ttk.Frame(w, padding=14)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='Para onde copiar o backup?',
              font=('Segoe UI', 15, 'bold')).pack(anchor='w')
    ttk.Label(body, text=(
        'Selecione de 1 a 8 pastas existentes em discos diferentes de C:. '
        'Cada destino terá uma cópia local com SHA-256. '
        'As etiquetas abaixo são informadas por você, não verificam o tipo físico.'),
        wraplength=745).pack(anchor='w', pady=(6, 8))
    ttk.Label(body, text=(
        'Nuvem: escolha uma pasta de um cliente sincronizador já instalado. '
        'O aplicativo NÃO conecta Google Drive/OneDrive por API nesta versão e '
        'NÃO pode atestar que a sincronização para o servidor terminou. '
        'Se essa pasta estiver no C:, esta etapa não permitirá o backup nela.'),
        wraplength=745, foreground='#C79229').pack(anchor='w', pady=(0, 8))
    kind = tk.StringVar(value='local')
    ttk.Combobox(body, textvariable=kind, state='readonly', width=38,
                 values=tuple(KINDS.keys())).pack(anchor='w', pady=(0, 5))
    ttk.Label(body, text='local = disco interno; external = dispositivo removível; '
              'synced_folder = pasta de nuvem sincronizada',
              wraplength=730).pack(anchor='w')
    listbox = tk.Listbox(body, height=11, exportselection=False)
    listbox.pack(fill='both', expand=True, pady=(10, 8))
    entries = [dict(p) for p in initial if isinstance(p, dict)
               and p.get('kind') in KINDS and isinstance(p.get('path'), str)]

    def refresh():
        listbox.delete(0, 'end')
        for i, item in enumerate(entries):
            listbox.insert('end', f'{i+1}. {KINDS[item["kind"]]} — {item["path"]}')

    def add():
        if len(entries) >= 8:
            return messagebox.showwarning('Limite', 'Máximo de 8 destinos.', parent=w)
        selected = filedialog.askdirectory(parent=w, title='Escolha uma pasta existente para backup')
        if selected:
            entries.append({'path': str(Path(selected)), 'kind': kind.get()})
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

    row = ttk.Frame(body)
    row.pack(fill='x')
    ttk.Button(row, text='Adicionar pasta escolhida', command=add).pack(side='left', padx=(0, 8))
    ttk.Button(row, text='Remover selecionada', command=remove).pack(side='left')
    ttk.Button(row, text='Cancelar', command=w.destroy).pack(side='right')
    ttk.Button(row, text='Usar estes destinos', command=save).pack(side='right', padx=(0, 8))
    refresh()
    return w
