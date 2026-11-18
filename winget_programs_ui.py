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
from ui_scale import (
    COR_BORDA,
    COR_PAINEL,
    COR_SELECAO,
    COR_TEXTO,
    ESPACO_ENTRE_BOTOES,
    ESPACO_MINIMO,
    ESPACO_P,
    FONTE_MONO,
    FONTE_UI,
    PADDING_CAIXA_TEXTO,
    PADDING_DIALOGO,
    TAMANHO_CORPO,
    TAMANHO_SUBTITULO,
    safe_window_geometry,
    safe_wraplength,
)
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
    win.geometry(safe_window_geometry(
        600,
        480,
        win.winfo_screenwidth() or 0,
        win.winfo_screenheight() or 0,
        min_w=460,
        min_h=360,
    ))
    win.minsize(460, 360)
    win.transient(parent)
    state = {'ok': False}
    frame = ttk.Frame(win, padding=PADDING_DIALOGO)
    frame.pack(fill='both', expand=True)
    title_label = ttk.Label(
        frame,
        wraplength=520,
        font=(FONTE_UI, TAMANHO_SUBTITULO, 'bold'),
        text=f'Estes {len(ids)} programa(s) serão baixados da internet e instalados pelo winget:',
    )
    title_label.pack(anchor='w')

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

    buttons.pack(side='bottom', fill='x')
    cancel_button.pack(side='right')
    install.pack(side='right', padx=ESPACO_ENTRE_BOTOES)

    ttk.Checkbutton(
        frame,
        text=CONFIRM_CHECK_TEXT,
        variable=agreed,
        command=toggled,
    ).pack(side='bottom', anchor='w', pady=(0, ESPACO_P))
    uac_label = ttk.Label(frame, wraplength=520, text=UAC_TEXT)
    uac_label.pack(side='bottom', anchor='w', pady=(0, ESPACO_P))
    warn_label = ttk.Label(
        frame,
        wraplength=520,
        text=(
            'O Windows pode mostrar avisos de alguns instaladores. Programas que precisam de '
            'administrador podem falhar: o resultado explica o que fazer. Os programas já '
            'instalados não são atualizados nem removidos. A instalação pode demorar; não '
            'desligue o computador.'
        ),
    )
    warn_label.pack(side='bottom', anchor='w', pady=(0, ESPACO_MINIMO))

    box = tk.Text(
        frame,
        height=min(max(len(ids), 3), 14),
        width=60,
        wrap='none',
        bg=COR_PAINEL,
        fg=COR_TEXTO,
        insertbackground=COR_TEXTO,
        selectbackground=COR_SELECAO,
        highlightthickness=1,
        highlightbackground=COR_BORDA,
        highlightcolor=COR_BORDA,
        bd=0,
        relief='flat',
        font=(FONTE_MONO, TAMANHO_CORPO),
        padx=PADDING_CAIXA_TEXTO[0],
        pady=PADDING_CAIXA_TEXTO[1],
    )
    box.insert('1.0', '\n'.join(ids))
    box.configure(state='disabled')  # só leitura
    box.pack(fill='both', expand=True, pady=ESPACO_P)

    def _update_wrap(event):
        if event.widget is frame and event.width > 1:
            wrap = safe_wraplength(event.width, padding=PADDING_DIALOGO)
            title_label.configure(wraplength=wrap)
            warn_label.configure(wraplength=wrap)
            uac_label.configure(wraplength=wrap)

    frame.bind('<Configure>', _update_wrap)

    win.bind('<Return>', lambda _e: cancel())
    win.bind('<Escape>', lambda _e: cancel())
    win.protocol('WM_DELETE_WINDOW', cancel)
    cancel_button.focus_set()
    win.confirm_state = state
    win.confirm_box = box
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
    win.geometry(safe_window_geometry(
        820,
        420,
        win.winfo_screenwidth() or 0,
        win.winfo_screenheight() or 0,
        min_w=560,
        min_h=340,
    ))
    win.minsize(560, 340)
    frame = ttk.Frame(win, padding=PADDING_DIALOGO)
    frame.pack(fill='both', expand=True)
    msg_label = ttk.Label(frame, wraplength=780, text=result.get('message', ''))
    msg_label.pack(anchor='w', pady=(0, ESPACO_P))
    frame.bind(
        '<Configure>',
        lambda event: (
            msg_label.configure(wraplength=safe_wraplength(event.width, padding=PADDING_DIALOGO))
            if event.widget is frame and event.width > 1 else None
        ),
    )
    ttk.Button(frame, text='Fechar', command=win.destroy).pack(
        side='bottom', anchor='e', pady=(ESPACO_P, 0))
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
    return win


def show_programs(parent, backup_folder, *, runner=None, state_dir=None, elevated_probe=None,
                  confirm=None, ask_save=None):
    dlg = tk.Toplevel(parent)
    dlg.title('Programas do backup')
    dlg.geometry(safe_window_geometry(
        900,
        640,
        dlg.winfo_screenwidth() or 0,
        dlg.winfo_screenheight() or 0,
        min_w=640,
        min_h=440,
    ))
    dlg.minsize(640, 440)
    timers = WindowTimers(dlg)
    elevated = is_process_elevated(elevated_probe)
    state = {'packages': [], 'selected': set(), 'groups': {}, 'loaded': False, 'error': None,
             'busy': False, 'loading': False, 'elevated': elevated, 'result': None}
    dlg.program_state = state

    frame = ttk.Frame(dlg, padding=PADDING_DIALOGO)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Programas que estavam instalados quando o backup foi feito',
              font=(FONTE_UI, TAMANHO_SUBTITULO, 'bold')).pack(anchor='w')
    intro_label = ttk.Label(frame, wraplength=850, text=INTRO_TEXT)
    intro_label.pack(anchor='w', pady=(ESPACO_MINIMO, ESPACO_P))
    admin_label = None
    if elevated:
        admin_label = ttk.Label(
            frame,
            wraplength=850,
            text=ADMIN_TEXT,
            font=(FONTE_UI, TAMANHO_CORPO, 'bold'),
        )
        admin_label.pack(anchor='w', pady=(0, ESPACO_P))
    status = tk.StringVar(value='Lendo a lista de programas em segundo plano…')
    status_label = ttk.Label(frame, textvariable=status, wraplength=850)
    status_label.pack(fill='x', pady=(0, ESPACO_P))

    def _update_wrap(event):
        if event.widget is frame and event.width > 1:
            wrap = safe_wraplength(event.width, padding=PADDING_DIALOGO)
            intro_label.configure(wraplength=wrap)
            status_label.configure(wraplength=wrap)
            if admin_label is not None:
                admin_label.configure(wraplength=wrap)

    frame.bind('<Configure>', _update_wrap)

    grid = ttk.Frame(frame)
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
    counter_label = ttk.Label(frame, textvariable=counter, font=(FONTE_UI, TAMANHO_CORPO, 'bold'))

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
    tools.pack(side='bottom', fill='x')
    counter_label.pack(side='bottom', fill='x', pady=(ESPACO_P, ESPACO_MINIMO))
    grid.pack(fill='both', expand=True)
    mark_buttons = [ttk.Button(tools, text='Marcar categoria', command=mark_category),
                    ttk.Button(tools, text='Marcar tudo', command=mark_all),
                    ttk.Button(tools, text='Desmarcar tudo', command=unmark_all)]
    for button in mark_buttons:
        button.pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    install_button = ttk.Button(tools, text=INSTALL_TEXT, command=install_selected)
    install_button.pack(side='left', padx=ESPACO_ENTRE_BOTOES)
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
                save_button.pack(side='left', padx=ESPACO_ENTRE_BOTOES)
                update_buttons()

        wait_job(job, finished)

    start_loading()
    return dlg
