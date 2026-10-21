"""P2-04 (fatia 1): janela "Programas do backup".

Mostra a lista salva pelo `winget export`, agrupada por categoria, com caixas
de seleção. Só leitura: esta janela não instala nada e não chama o winget.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from restore_jobs import Job
from ui_timers import WindowTimers
from winget_programs import CATEGORIES, default_selection, group_by_category, load_export

CHECKED, UNCHECKED, LOCKED = '[x]', '[ ]', '—'


def show_programs(parent, backup_folder):
    dlg = tk.Toplevel(parent)
    dlg.title('Programas do backup')
    dlg.geometry('900x620')
    dlg.minsize(640, 420)
    timers = WindowTimers(dlg)
    state = {'packages': [], 'selected': set(), 'groups': {}, 'loaded': False, 'error': None}
    dlg.program_state = state

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Programas que estavam instalados quando o backup foi feito',
              font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(frame, wraplength=850, text=(
        'Marque os programas que você quer reinstalar depois de formatar. Nesta versão o '
        'aplicativo só mostra e guarda a sua escolha nesta janela; nada é instalado. '
        'Itens com "—" precisam ser instalados de outro jeito (veja a observação).'
    )).pack(anchor='w', pady=(4, 6))
    status = tk.StringVar(value='Lendo a lista de programas em segundo plano…')
    ttk.Label(frame, textvariable=status, wraplength=850).pack(fill='x', pady=(0, 6))

    grid = ttk.Frame(frame)
    grid.pack(fill='both', expand=True)
    tree = ttk.Treeview(grid, columns=('mark', 'version', 'note'), show='tree headings',
                        selectmode='browse')
    tree.heading('#0', text='Categoria / programa')
    tree.heading('mark', text='Reinstalar')
    tree.heading('version', text='Versão')
    tree.heading('note', text='Observação')
    tree.column('#0', width=300, stretch=True)
    tree.column('mark', width=90, anchor='center', stretch=False)
    tree.column('version', width=110, stretch=False)
    tree.column('note', width=360, stretch=True)
    bar = ttk.Scrollbar(grid, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.grid(row=0, column=0, sticky='nsew')
    bar.grid(row=0, column=1, sticky='ns')
    grid.rowconfigure(0, weight=1)
    grid.columnconfigure(0, weight=1)

    counter = tk.StringVar(value='')
    ttk.Label(frame, textvariable=counter, font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(6, 4))

    def package_iid(index):
        return f'pkg:{index}'

    def category_iid(name):
        return f'cat:{CATEGORIES.index(name)}'

    def refresh_marks():
        packages = state['packages']
        for name, items in state['groups'].items():
            chosen = sum(1 for p in items if p['_index'] in state['selected'])
            usable = sum(1 for p in items if p['selectable'])
            tree.item(category_iid(name), text=f'{name} ({chosen} de {usable} marcados)')
            for p in items:
                mark = LOCKED if not p['selectable'] else (
                    CHECKED if p['_index'] in state['selected'] else UNCHECKED)
                tree.set(package_iid(p['_index']), 'mark', mark)
        usable = sum(1 for p in packages if p['selectable'])
        counter.set(f'{len(state["selected"])} de {usable} programa(s) marcados · '
                    f'{len(packages)} na lista')

    def set_marks(indexes, value):
        for index in indexes:
            if not state['packages'][index]['selectable']:
                continue
            if value:
                state['selected'].add(index)
            else:
                state['selected'].discard(index)
        refresh_marks()

    def current_category():
        focus = tree.focus()
        if not focus:
            return None
        if focus.startswith('pkg:'):
            focus = tree.parent(focus)
        if focus.startswith('cat:'):
            return CATEGORIES[int(focus[4:])]
        return None

    def mark_category():
        name = current_category()
        if name is None:
            status.set('Clique numa categoria (ou num programa dela) e depois em "Marcar categoria".')
            return
        set_marks([p['_index'] for p in state['groups'][name]], True)

    def mark_all():
        set_marks(range(len(state['packages'])), True)

    def unmark_all():
        set_marks(range(len(state['packages'])), False)

    def on_click(event):
        if not state['loaded'] or tree.identify_column(event.x) != '#1':
            return
        iid = tree.identify_row(event.y)
        if iid.startswith('pkg:'):
            index = int(iid[4:])
            set_marks([index], index not in state['selected'])
        elif iid.startswith('cat:'):
            items = [p['_index'] for p in state['groups'][CATEGORIES[int(iid[4:])]]
                     if p['selectable']]
            set_marks(items, not all(i in state['selected'] for i in items))

    tree.bind('<Button-1>', on_click, add='+')

    tools = ttk.Frame(frame)
    tools.pack(fill='x')
    buttons = [ttk.Button(tools, text='Marcar categoria', command=mark_category),
               ttk.Button(tools, text='Marcar tudo', command=mark_all),
               ttk.Button(tools, text='Desmarcar tudo', command=unmark_all)]
    for button in buttons:
        button.pack(side='left', padx=(0, 7))
        button.state(['disabled'])
    ttk.Button(tools, text='Fechar', command=dlg.destroy).pack(side='right')

    def loaded(packages):
        for index, package in enumerate(packages):
            package['_index'] = index
        state['packages'] = packages
        state['groups'] = group_by_category(packages)
        state['selected'] = set(default_selection(packages))
        for name in CATEGORIES:
            cat = category_iid(name)
            tree.insert('', 'end', iid=cat, text=name, open=bool(state['groups'][name]))
            for p in state['groups'][name]:
                tree.insert(cat, 'end', iid=package_iid(p['_index']), text=p['id'],
                            values=('', p['version'], p['note']))
        state['loaded'] = True
        for button in buttons:
            button.state(['!disabled'])
        refresh_marks()
        status.set(f'{len(packages)} programa(s) na lista. Nada foi marcado automaticamente.')

    job = Job(lambda cancelled, progress: load_export(backup_folder))

    def poll():
        result = job.poll()
        if result is None:
            timers.after(80, poll)
            return
        kind, value = result
        if kind == 'done':
            loaded(value)
        else:
            state['error'] = value
            status.set(value)

    timers.after(10, poll)
    return dlg
