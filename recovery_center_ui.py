"""P2-08 (fatias 1 e 2): janela "Central de recuperação" (Tk fino, somente leitura).

Lista os backups de uma pasta (recovery_center.scan, num Job) e, para o
backup escolhido, permite "Conferir integridade" (opcional, num Job) e
"Restaurar…", que só abre a janela de restauração que já existe
(restore_ui.show_restore). Nada aqui grava, apaga ou restaura sozinho.
A tela mostra só o nome da pasta de cada backup, nunca o caminho completo.
Fatia 2: "Restaurar só os conferidos…" (só para backup parcial liberado por
recovery_center.partial_restore_info) pede uma confirmação separada e abre a
mesma janela no modo only_verified=True (sempre pasta nova).
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import recovery_center as rc
from recovery_center import scan, verify_backup
from restore_jobs import Job
from restore_ui import show_restore
from ui_timers import WindowTimers

TITLE = 'Central de recuperação'
INTRO_TEXT = (
    'Escolha a pasta onde estão os seus backups (ou a pasta de um backup). O aplicativo '
    'mostra cada backup encontrado e diz se ele pode ser restaurado. Nada é alterado aqui: '
    '"Conferir integridade" só lê os arquivos, e "Restaurar…" abre a janela de restauração, '
    'onde você escolhe o que trazer de volta.')
EMPTY_TEXT = 'Nenhum backup foi encontrado nesta pasta.'
PICK_TEXT = 'Clique em "Escolher pasta" para procurar os seus backups.'
SELECT_TEXT = 'Clique num backup da tabela primeiro.'


def _ask_folder(parent):
    path = filedialog.askdirectory(parent=parent, title='Pasta dos backups')
    return Path(path) if path else None


def show_recovery_center(app, *, folder=None, ask_folder=None, scanner=None, verifier=None):
    """Abre a central (uma janela por vez).

    scanner(pasta, cancelled) -> resultado de recovery_center.scan;
    verifier(manifest, cancelled) -> (aprovado, texto).
    """
    previous = getattr(app, 'recovery_center_dialog', None)
    if previous is not None:
        try:
            alive = previous.winfo_exists()
        except tk.TclError:
            alive = False
        if alive:
            previous.deiconify()  # traz de volta se estiver minimizada
            previous.lift()
            return previous
    run_scan = scanner or (lambda chosen, cancelled: scan(chosen, cancelled=cancelled))
    run_verify = verifier or (lambda manifest, cancelled: verify_backup(manifest, cancelled))
    choose = ask_folder or _ask_folder

    dlg = tk.Toplevel(app)
    app.recovery_center_dialog = dlg
    dlg.title(TITLE)
    dlg.geometry('1100x620')
    dlg.minsize(760, 440)
    timers = WindowTimers(dlg)
    state = {'rows': [], 'busy': False, 'job': None, 'folder': None}
    dlg.center_state = state

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=TITLE, font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(frame, wraplength=1050, text=INTRO_TEXT).pack(anchor='w', pady=(4, 6))
    status = tk.StringVar(master=dlg, value=PICK_TEXT)
    dlg.center_status = status
    ttk.Label(frame, textvariable=status, wraplength=1050).pack(fill='x', pady=(0, 2))
    warning = tk.StringVar(master=dlg, value='')
    dlg.center_warning = warning
    ttk.Label(frame, textvariable=warning, wraplength=1050,
              font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(0, 6))

    grid = ttk.Frame(frame)
    grid.pack(fill='both', expand=True)
    columns = ('folder', 'date', 'situation', 'files', 'size', 'restore', 'reason')
    tree = ttk.Treeview(grid, columns=columns, show='tree headings', selectmode='browse')
    dlg.center_tree = tree
    tree.heading('#0', text='Backup')
    for column, text, width, stretch in (
            ('folder', 'Pasta', 200, True), ('date', 'Data', 120, False),
            ('situation', 'Situação', 150, False), ('files', 'Arquivos', 80, False),
            ('size', 'Tamanho', 100, False), ('restore', 'Pode restaurar?', 110, False),
            ('reason', 'Motivo', 300, True)):
        tree.heading(column, text=text)
        tree.column(column, width=width, stretch=stretch)
    tree.column('#0', width=200, stretch=True)
    bar = ttk.Scrollbar(grid, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.grid(row=0, column=0, sticky='nsew')
    bar.grid(row=0, column=1, sticky='ns')
    grid.rowconfigure(0, weight=1)
    grid.columnconfigure(0, weight=1)
    # FIX-P2-08-01: motivo completo abaixo da tabela, com quebra de linha (só leitura)
    detail = tk.StringVar(master=dlg, value=rc.NO_SELECTION_TEXT)
    dlg.center_detail = detail
    detail_label = ttk.Label(grid, textvariable=detail, wraplength=1050, justify='left')
    detail_label.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 0))

    def fit_detail(event):
        detail_label.configure(wraplength=max(200, event.width - 20))

    grid.bind('<Configure>', fit_detail, add='+')

    def current():
        ids = tree.selection()
        if not ids or not ids[0].startswith('row:'):
            return None
        index = int(ids[0][4:])
        rows = state['rows']
        return rows[index] if index < len(rows) else None

    def update_buttons(_event=None):
        row = current()
        busy = state['busy']
        choose_button.state(['disabled'] if busy else ['!disabled'])
        verify_button.state(['disabled'] if busy or row is None else ['!disabled'])
        restore_button.state(['disabled'] if busy or row is None or not row['restorable']
                             else ['!disabled'])
        partial_button.state(['disabled'] if busy or row is None or not row.get('partial_ok')
                             else ['!disabled'])
        text = rc.reason_detail_text(row)
        counts = rc.counts_text(row)
        detail.set(f'{text}\n{counts}' if counts else text)
        if row is not None and not busy:
            status.set(f'{row["name"]}: {row["reason"]}')

    tree.bind('<<TreeviewSelect>>', update_buttons, add='+')

    def wait_job(job, done):
        def poll():
            result = job.poll()
            if result is None:
                timers.after(150, poll)
                return
            done(*result)
        timers.after(10, poll)

    def loaded(result):
        rows = list(result.get('rows', []))
        state['rows'] = rows
        tree.delete(*tree.get_children(''))
        detail.set(rc.NO_SELECTION_TEXT)
        for index, row in enumerate(rows):
            tree.insert('', 'end', iid=f'row:{index}', text=row['name'],
                        values=(row['folder'], row['date'], row['status_text'], row['files'],
                                row['size_text'], 'Sim' if row['restorable'] else 'Não',
                                row['reason']))
        warning.set(' '.join(result.get('warnings', [])))
        status.set(f'{len(rows)} backup(s) encontrado(s). Clique num deles.' if rows
                   else EMPTY_TEXT)

    def search(folder):
        if state['busy']:
            return
        state['busy'] = True
        state['folder'] = Path(folder)
        state['rows'] = []
        tree.delete(*tree.get_children(''))
        warning.set('')
        # texto genérico: o nome da pasta escolhida pode ser o nome de usuário
        status.set('Procurando backups na pasta escolhida… (só leitura)')
        update_buttons()
        job = Job(lambda cancelled, progress: run_scan(Path(folder), cancelled))
        state['job'] = job

        def finished(kind, value):
            state['busy'] = False
            if kind == 'done':
                loaded(value)
            else:
                status.set('Não foi possível procurar os backups. Nada foi alterado. '
                           'Tente "Escolher pasta" de novo.')
            update_buttons()

        wait_job(job, finished)

    def pick_folder():
        if state['busy']:
            return
        chosen = choose(dlg)
        if chosen:
            search(chosen)

    def verify():
        row = current()
        if row is None:
            status.set(SELECT_TEXT)
            return
        if state['busy']:
            return
        state['busy'] = True
        status.set(f'Conferindo "{row["folder"]}"… (só leitura; pode demorar em backups grandes)')
        update_buttons()
        manifest = row['manifest']
        job = Job(lambda cancelled, progress: run_verify(manifest, cancelled))
        state['job'] = job

        def finished(kind, value):
            state['busy'] = False
            update_buttons()
            if kind == 'done':
                status.set(value[1])
            else:
                status.set('Não foi possível conferir este backup. Nada foi alterado.')

        wait_job(job, finished)

    def restore():
        row = current()
        if row is None:
            status.set(SELECT_TEXT)
            return
        if not row['restorable']:
            status.set(f'Este backup não pode ser restaurado: {row["reason"]}')
            return
        show_restore(app, row['manifest'])

    def restore_partial():
        """P2-08 (fatia 2): confirmação separada e janela no modo "só os conferidos"."""
        row = current()
        if row is None:
            status.set(SELECT_TEXT)
            return
        if state['busy']:
            return
        if not row.get('partial_ok'):
            status.set('Não dá para restaurar só os conferidos deste backup: '
                       f'{row.get("partial_reason") or row["reason"]}')
            return
        if not messagebox.askyesno('Restaurar só os conferidos', rc.partial_confirmation_text(row),
                                   parent=dlg):
            status.set('Restauração não iniciada. Nada foi alterado.')
            return
        show_restore(app, row['manifest'], only_verified=True)

    dlg.center_search = search
    tools = ttk.Frame(frame)
    tools.pack(fill='x', pady=(8, 0))
    choose_button = ttk.Button(tools, text='Escolher pasta', command=pick_folder)
    choose_button.pack(side='left')
    verify_button = ttk.Button(tools, text='Conferir integridade', command=verify)
    verify_button.pack(side='left', padx=(7, 0))
    restore_button = ttk.Button(tools, text='Restaurar…', command=restore)
    restore_button.pack(side='left', padx=(7, 0))
    partial_button = ttk.Button(tools, text='Restaurar só os conferidos…', command=restore_partial)
    partial_button.pack(side='left', padx=(7, 0))
    ttk.Button(tools, text='Fechar', command=dlg.destroy).pack(side='right')
    dlg.center_buttons = {'Escolher pasta': choose_button, 'Conferir integridade': verify_button,
                          'Restaurar…': restore_button,
                          'Restaurar só os conferidos…': partial_button}

    def on_destroy(event):
        if event.widget is not dlg:
            return
        if getattr(app, 'recovery_center_dialog', None) is dlg:
            app.recovery_center_dialog = None
        if state['job'] is not None:
            state['job'].cancelled.set()  # fechar pede para a busca/conferência parar

    dlg.bind('<Destroy>', on_destroy, add='+')
    update_buttons()
    if folder is not None:
        search(folder)
    return dlg
