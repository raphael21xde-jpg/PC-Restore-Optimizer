"""P2-04: janela "Programas do backup".

Mostra a lista salva pelo `winget export`, agrupada por categoria, com caixas
de seleção. Esta janela nunca chama o winget diretamente: a instalação é feita
só pelo `winget_install.run_install`, depois de uma confirmação explícita
(`confirm_install`), e o "Salvar lista agora" usa o `winget_programs.save_export`.
"""
from __future__ import annotations

import gc
import tkinter as tk
from tkinter import messagebox, ttk

from elevation_guard import is_process_elevated
from restore_jobs import Job
from ui_timers import WindowTimers
from winget_install import BUSY_TEXT, installation_running, run_install
from winget_programs import (CATEGORIES, default_selection, group_by_category, load_export,
                             save_export)

CHECKED, UNCHECKED, LOCKED = '[x]', '[ ]', '—'
INSTALL_TEXT = 'Instalar marcados…'
SAVE_NOW_TEXT = 'Salvar lista agora'
CONFIRM_CHECK_TEXT = 'Entendi que estes programas serão baixados e instalados neste PC'
UAC_TEXT = ('Alguns instaladores podem mostrar o aviso de administrador do Windows; '
            'você decide em cada um.')
WAIT_TEXT = 'Aguarde, a instalação continua. A janela poderá ser fechada quando ela terminar.'
ADMIN_TEXT = ('O aplicativo está aberto como administrador, por isso a instalação está '
              'desligada. Feche e abra de novo pelo atalho normal para instalar.')
INTRO_TEXT = (
    'Marque os programas que você quer reinstalar e clique em "Instalar marcados…". Antes de '
    'instalar, o aplicativo mostra a lista e pede a sua confirmação; depois confere um por um. '
    'As marcações valem só enquanto esta janela estiver aberta; ao fechar, elas se perdem. '
    'Itens com "—" precisam ser instalados de outro jeito (veja a observação).'
)
SAVE_NOW_QUESTION = (
    'Salvar a lista de programas agora?\n\n'
    'Isto só faz sentido no Windows antigo, ANTES de formatar: a lista mostra os programas '
    'instalados neste computador agora. Num Windows recém-instalado ela sairia quase vazia.\n\n'
    'A lista é gravada numa pasta nova dentro do backup; nada do backup é apagado ou substituído.'
)


def build_confirm(parent, ids):
    """Monta a janela de confirmação. Devolve (janela, estado); estado['ok'] começa False."""
    ids = list(ids)
    win = tk.Toplevel(parent)
    win.title('Confirmar instalação')
    win.transient(parent)
    state = {'ok': False}
    frame = ttk.Frame(win, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, wraplength=520, font=('Segoe UI', 11, 'bold'),
              text=f'Estes {len(ids)} programa(s) serão baixados da internet e instalados '
                   'pelo winget:').pack(anchor='w')
    box = tk.Text(frame, height=min(max(len(ids), 3), 14), width=60, wrap='none')
    box.insert('1.0', '\n'.join(ids))
    box.configure(state='disabled')  # só leitura
    box.pack(fill='both', expand=True, pady=(6, 6))
    ttk.Label(frame, wraplength=520, text=(
        'O Windows pode mostrar avisos de alguns instaladores. Programas que precisam de '
        'administrador podem falhar: o resultado explica o que fazer. Os programas já '
        'instalados não são atualizados nem removidos. A instalação pode demorar; não '
        'desligue o computador.')).pack(anchor='w', pady=(0, 4))
    ttk.Label(frame, wraplength=520, text=UAC_TEXT).pack(anchor='w', pady=(0, 8))
    agreed = tk.BooleanVar(master=win, value=False)
    buttons = ttk.Frame(frame)

    def cancel():
        state['ok'] = False
        win.destroy()

    def accept():
        if not agreed.get():
            return
        state['ok'] = True
        win.destroy()

    install = ttk.Button(buttons, text=f'Instalar {len(ids)} programa(s)', command=accept)
    install.state(['disabled'])
    cancel_button = ttk.Button(buttons, text='Cancelar', command=cancel, default='active')

    def toggled():
        install.state(['!disabled'] if agreed.get() else ['disabled'])

    ttk.Checkbutton(frame, text=CONFIRM_CHECK_TEXT, variable=agreed,
                    command=toggled).pack(anchor='w', pady=(0, 10))
    buttons.pack(fill='x')
    cancel_button.pack(side='right')
    install.pack(side='right', padx=(0, 7))
    win.bind('<Return>', lambda _e: cancel())
    win.bind('<Escape>', lambda _e: cancel())
    win.protocol('WM_DELETE_WINDOW', cancel)
    cancel_button.focus_set()
    win.confirm_state = state
    return win, state


def confirm_install(parent, ids):
    """Pergunta antes de instalar. True só se a pessoa marcar a caixa e clicar em Instalar."""
    win, state = build_confirm(parent, ids)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return state['ok'] is True


def show_results(parent, result):
    win = tk.Toplevel(parent)
    win.title('Resultado da instalação')
    win.geometry('820x420')
    frame = ttk.Frame(win, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, wraplength=780, text=result.get('message', '')).pack(anchor='w', pady=(0, 8))
    table = ttk.Treeview(frame, columns=('status', 'explanation'), show='tree headings')
    table.heading('#0', text='Programa')
    table.heading('status', text='Resultado')
    table.heading('explanation', text='O que fazer')
    table.column('#0', width=220)
    table.column('status', width=110, stretch=False)
    table.column('explanation', width=450)
    for row in result.get('results', []):
        table.insert('', 'end', text=row['id'], values=(row['status'], row['explanation']))
    table.pack(fill='both', expand=True)
    ttk.Button(frame, text='Fechar', command=win.destroy).pack(anchor='e', pady=(8, 0))
    return win


def show_programs(parent, backup_folder, *, runner=None, state_dir=None, elevated_probe=None,
                  confirm=None, ask_save=None):
    dlg = tk.Toplevel(parent)
    dlg.title('Programas do backup')
    dlg.geometry('900x640')
    dlg.minsize(640, 440)
    timers = WindowTimers(dlg)
    elevated = is_process_elevated(elevated_probe)
    state = {'packages': [], 'selected': set(), 'groups': {}, 'loaded': False, 'error': None,
             'busy': False, 'loading': False, 'elevated': elevated, 'result': None}
    dlg.program_state = state

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Programas que estavam instalados quando o backup foi feito',
              font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(frame, wraplength=850, text=INTRO_TEXT).pack(anchor='w', pady=(4, 6))
    if elevated:
        ttk.Label(frame, wraplength=850, text=ADMIN_TEXT,
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 6))
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

    def update_buttons():
        idle = state['loaded'] and not state['busy']
        for button in mark_buttons:
            button.state(['!disabled'] if idle else ['disabled'])
        can_install = (idle and bool(state['selected']) and not state['elevated']
                       and not installation_running())
        install_button.state(['!disabled'] if can_install else ['disabled'])
        # "Salvar lista agora" fica desligado enquanto a lista está sendo lida
        can_save = not state['busy'] and not state['loading']
        save_button.state(['!disabled'] if can_save else ['disabled'])
        close_button.state(['disabled'] if state['busy'] else ['!disabled'])

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
        update_buttons()

    def set_marks(indexes, value):
        if state['busy']:
            return
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
        if not state['loaded'] or state['busy'] or tree.identify_column(event.x) != '#1':
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

    def wait_job(job, done):
        def poll():
            result = job.poll()
            if result is None:
                timers.after(150, poll)
                return
            done(*result)
        timers.after(10, poll)

    def install_selected():
        if state['busy'] or state['elevated'] or not state['selected']:
            return
        if installation_running():
            status.set(BUSY_TEXT)
            update_buttons()
            return
        packages = list(state['packages'])
        ids = [packages[i]['id'] for i in sorted(state['selected'])]
        if not (confirm or confirm_install)(dlg, ids):
            status.set('Instalação cancelada. Nada foi instalado.')
            return
        # A janela de confirmação acabou de fechar: o lixo dela (variáveis do Tk)
        # é recolhido aqui, na thread da tela, e não dentro da thread de trabalho.
        gc.collect()
        state['busy'] = True
        update_buttons()
        status.set(f'Instalando {len(ids)} programa(s) com o winget… Isto pode demorar. '
                   'Não feche o aplicativo.')
        job = Job(lambda cancelled, progress: run_install(
            packages, ids, runner=runner, state_dir=state_dir, elevated_probe=elevated_probe))

        def finished(kind, value):
            state['busy'] = False
            if kind == 'done':
                state['result'] = value
                status.set(value.get('message', ''))
                show_results(dlg, value)
            else:
                status.set('Não foi possível concluir a instalação. Nada mais será feito.')
            update_buttons()

        wait_job(job, finished)

    def save_now():
        if state['busy'] or state['loading']:
            return
        ask = ask_save or (lambda: messagebox.askyesno('Salvar lista agora', SAVE_NOW_QUESTION,
                                                       parent=dlg, default='no'))
        if not ask():
            return
        state['busy'] = True
        update_buttons()
        status.set('Salvando a lista de programas deste computador…')
        job = Job(lambda cancelled, progress: save_export(backup_folder, new_folder=True))

        def finished(kind, value):
            state['busy'] = False
            if kind == 'done' and value.get('status') == 'salvo':
                status.set(value['message'] + ' Lendo a lista…')
                start_loading()
            else:
                status.set(value.get('message', '') if kind == 'done' else
                           'Não foi possível salvar a lista. O backup continua válido.')
            update_buttons()

        wait_job(job, finished)

    def on_close():
        if state['busy']:
            status.set(WAIT_TEXT)
            messagebox.showinfo('Aguarde', WAIT_TEXT, parent=dlg)
            return
        dlg.destroy()

    tools = ttk.Frame(frame)
    tools.pack(fill='x')
    mark_buttons = [ttk.Button(tools, text='Marcar categoria', command=mark_category),
                    ttk.Button(tools, text='Marcar tudo', command=mark_all),
                    ttk.Button(tools, text='Desmarcar tudo', command=unmark_all)]
    for button in mark_buttons:
        button.pack(side='left', padx=(0, 7))
    install_button = ttk.Button(tools, text=INSTALL_TEXT, command=install_selected)
    install_button.pack(side='left', padx=(7, 7))
    save_button = ttk.Button(tools, text=SAVE_NOW_TEXT, command=save_now)
    close_button = ttk.Button(tools, text='Fechar', command=on_close)
    close_button.pack(side='right')
    dlg.protocol('WM_DELETE_WINDOW', on_close)

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
        state['error'] = None
        save_button.pack_forget()
        refresh_marks()
        status.set(f'{len(packages)} programa(s) na lista. Nada foi marcado automaticamente.')

    def start_loading():
        if state['loading']:
            return
        tree.delete(*tree.get_children(''))
        state.update(packages=[], selected=set(), groups={}, loaded=False, error=None,
                     loading=True)
        counter.set('')
        update_buttons()
        job = Job(lambda cancelled, progress: load_export(backup_folder))

        def finished(kind, value):
            state['loading'] = False
            if kind == 'done':
                loaded(value)
            else:
                state['error'] = value
                status.set(value + ' Se este é o Windows antigo, ANTES de formatar, você pode '
                                   f'usar "{SAVE_NOW_TEXT}".')
                save_button.pack(side='left', padx=(7, 0))
                update_buttons()

        wait_job(job, finished)

    start_loading()
    return dlg
