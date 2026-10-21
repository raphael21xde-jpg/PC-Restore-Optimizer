"""P2-11: janela "Depois de formatar" (assistente passo a passo).

Uma tela com as 5 etapas de after_format.STEPS. Cada etapa tem "Abrir" (que
só chama a janela pública que já existe: restauração, programas, launchers e
navegador), "Feito" e "Pular". "Feito" é só uma marcação da pessoa; nada é
conferido nem executado por ela. Pular não bloqueia nenhuma etapa.

A conferência das unidades roda num Job (segundo plano, só leitura) e volta ao
Tk por after. Fechar a janela cancela o Job.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from after_format import (DONE, PENDING, SKIPPED, STEPS, check_drives, load_progress,
                          password_alert, progress_error_text, save_progress, window_key)
from browser_recovery_ui import show_recovery
from launcher_guide_ui import show_launchers
from restore_jobs import Job
from restore_ui import show_restore
from ui_timers import WindowTimers
from winget_programs_ui import show_programs

TITLE = 'Depois de formatar'
INTRO_TEXT = (
    'Siga as etapas na ordem que preferir. "Abrir" leva para a tela de cada etapa; quando '
    'terminar, clique em "Feito". Se não precisar de uma etapa, clique em "Pular". As '
    'marcações ficam salvas para este backup, mesmo se você fechar o aplicativo.')
STATUS_TEXT = {PENDING: 'Pendente', DONE: 'Feito', SKIPPED: 'Pulado'}
DRIVES_PENDING_TEXT = ('Lembrete: a etapa 1 (conferir discos e letras) ainda está pendente. '
                       'Se uma letra mudou, a restauração pode não achar o lugar certo.')


def _ask_manifest(parent):
    path = filedialog.askopenfilename(
        parent=parent, title='Escolha o arquivo manifest.json do backup',
        filetypes=[('Manifesto do backup', 'manifest.json'), ('JSON', '*.json')])
    return Path(path) if path else None


def show_after_format(app, *, manifest=None, base=None, ask_manifest=None, checker=None):
    """Abre o assistente. checker(manifest, cancelled) -> (check_drives, aviso de senhas)."""
    if manifest is None:
        manifest = (ask_manifest or _ask_manifest)(app)
        if not manifest:
            return None
    manifest = Path(manifest)
    # FIX-P2-11-02: uma janela por backup (a mesma chave vale em qualquer letra)
    key = window_key(manifest)
    dialogs = getattr(app, 'after_format_dialogs', None)
    if not isinstance(dialogs, dict):
        dialogs = app.after_format_dialogs = {}
    previous = dialogs.get(key)
    if previous is not None:
        try:
            alive = previous.winfo_exists()
        except tk.TclError:
            alive = False
        if alive:
            previous.deiconify()  # traz de volta se estiver minimizada
            previous.lift()
            return previous
        dialogs.pop(key, None)
    run_check = checker or (lambda chosen, cancelled: (check_drives(chosen),
                                                       password_alert(chosen)))
    progress = load_progress(manifest, base)

    dlg = tk.Toplevel(app)
    dlg.title(TITLE)
    dlg.geometry('1000x760')
    dlg.minsize(720, 520)
    dialogs[key] = dlg
    timers = WindowTimers(dlg)
    state = {'steps': dict(progress['steps']), 'path': progress['path'], 'job': None,
             'backup': progress.get('backup'), 'key': key,
             'busy': False, 'drives': None, 'passwords': '', 'manifest': manifest}
    dlg.after_format_state = state

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Depois de formatar: passo a passo',
              font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(frame, wraplength=950, text=INTRO_TEXT).pack(anchor='w', pady=(4, 2))
    ttk.Label(frame, wraplength=950,
              text=f'Backup escolhido: {manifest.parent.name}').pack(anchor='w', pady=(0, 4))
    # FIX-P2-11-01: aviso do progresso numa linha própria, que "Abrir" não apaga
    progress_warning = tk.StringVar(master=dlg, value=' '.join(progress['warnings']))
    dlg.after_format_progress_warning = progress_warning
    ttk.Label(frame, textvariable=progress_warning, wraplength=950,
              font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(0, 2))
    notice = tk.StringVar(master=dlg, value='')
    dlg.after_format_notice = notice
    ttk.Label(frame, textvariable=notice, wraplength=950,
              font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(0, 6))

    buttons = {}
    status_vars = {}
    dlg.after_format_buttons = buttons
    dlg.after_format_status = status_vars
    steps_box = ttk.Frame(frame)
    steps_box.pack(fill='x')
    password_var = tk.StringVar(master=dlg, value='')
    dlg.after_format_passwords = password_var

    def refresh_step(step_id):
        status_vars[step_id].set(STATUS_TEXT[state['steps'][step_id]])

    def mark(step_id, value):
        # clicar de novo no mesmo botão volta para "pendente"
        if state['steps'][step_id] == value:
            value = PENDING
        state['steps'][step_id] = value
        refresh_step(step_id)
        if state['path'] is None:
            return
        try:
            save_progress(state['path'], state['steps'], state['backup'])
        except (OSError, ValueError) as exc:
            progress_warning.set(progress_error_text(exc))

    for number, step in enumerate(STEPS, 1):
        row = ttk.Frame(steps_box, padding=(0, 4))
        row.pack(fill='x')
        text_box = ttk.Frame(row)
        text_box.pack(side='left', fill='x', expand=True)
        ttk.Label(text_box, text=f'{number}. {step["title"]}',
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(text_box, text=step['text'], wraplength=640).pack(anchor='w')
        if step['id'] == 'navegador':
            ttk.Label(text_box, textvariable=password_var, wraplength=640).pack(anchor='w')
        status_vars[step['id']] = tk.StringVar(master=dlg, value='')
        ttk.Label(row, textvariable=status_vars[step['id']], width=10).pack(side='left', padx=6)
        own = {}
        own['Abrir'] = ttk.Button(row, text='Abrir', command=lambda s=step['id']: open_step(s))
        own['Feito'] = ttk.Button(row, text='Feito', command=lambda s=step['id']: mark(s, DONE))
        own['Pular'] = ttk.Button(row, text='Pular',
                                  command=lambda s=step['id']: mark(s, SKIPPED))
        for name in ('Abrir', 'Feito', 'Pular'):
            own[name].pack(side='left', padx=(4, 0))
        buttons[step['id']] = own
        refresh_step(step['id'])

    ttk.Separator(frame).pack(fill='x', pady=8)
    ttk.Label(frame, text='Unidades deste computador agora (só leitura)',
              font=('Segoe UI', 10, 'bold')).pack(anchor='w')
    drive_status = tk.StringVar(master=dlg, value='')
    dlg.after_format_drive_status = drive_status
    ttk.Label(frame, textvariable=drive_status, wraplength=950).pack(fill='x', pady=(2, 4))
    grid = ttk.Frame(frame)
    grid.pack(fill='both', expand=True)
    tree = ttk.Treeview(grid, columns=('type', 'total', 'free', 'note'),
                        show='tree headings', selectmode='browse', height=5)
    tree.heading('#0', text='Unidade')
    tree.heading('type', text='Tipo')
    tree.heading('total', text='Tamanho')
    tree.heading('free', text='Livre')
    tree.heading('note', text='Observação')
    tree.column('#0', width=110, stretch=False)
    tree.column('type', width=230, stretch=True)
    tree.column('total', width=120, anchor='e', stretch=False)
    tree.column('free', width=120, anchor='e', stretch=False)
    tree.column('note', width=170, stretch=True)
    bar = ttk.Scrollbar(grid, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.grid(row=0, column=0, sticky='nsew')
    bar.grid(row=0, column=1, sticky='ns')
    grid.rowconfigure(0, weight=1)
    grid.columnconfigure(0, weight=1)
    dlg.after_format_tree = tree
    guide = tk.Text(frame, height=7, wrap='word')
    guide.pack(fill='both', expand=False, pady=(6, 6))
    dlg.after_format_guide = guide

    def show_guide(text):
        guide.configure(state='normal')
        guide.delete('1.0', 'end')
        guide.insert('1.0', text)
        guide.configure(state='disabled')  # só leitura

    def loaded(result):
        drives, passwords = result
        state['drives'] = drives
        state['passwords'] = passwords or ''
        password_var.set(state['passwords'])
        tree.delete(*tree.get_children(''))
        for index, drive in enumerate(drives.get('drives', [])):
            tree.insert('', 'end', iid=f'drive:{index}', text=drive['letter'],
                        values=(drive['type'], drive['total_text'], drive['free_text'],
                                'Disco do Windows' if drive.get('windows') else ''))
        count = len(drives.get('drives', []))
        drive_status.set(f'{count} unidade(s) encontrada(s).' if count else
                         'Nenhuma unidade foi listada.')
        parts = list(drives.get('warnings', []))
        if drives.get('guidance'):
            parts.append(drives['guidance'])
        if not parts:
            parts.append('As letras de onde vieram os arquivos do backup estão presentes. '
                         'Nada precisa ser trocado.')
        show_guide('\n\n'.join(parts))

    def wait_job(job, done):
        def poll():
            result = job.poll()
            if result is None:
                timers.after(150, poll)
                return
            done(*result)
        timers.after(10, poll)

    def run_drive_check():
        if state['busy']:
            return
        state['busy'] = True
        drive_status.set('Conferindo as unidades… (só leitura)')
        job = Job(lambda cancelled, progress_cb: run_check(manifest, cancelled))
        state['job'] = job

        def finished(kind, value):
            state['busy'] = False
            if kind == 'done':
                loaded(value)
            else:
                drive_status.set('Não foi possível conferir as unidades. Nada foi alterado. '
                                 'Clique em "Abrir" na etapa 1 para tentar de novo.')

        wait_job(job, finished)

    def open_step(step_id):
        notice.set('')
        if step_id == 'discos':
            run_drive_check()
        elif step_id == 'restaurar':
            if state['steps']['discos'] == PENDING:
                notice.set(DRIVES_PENDING_TEXT)
            show_restore(app, manifest)
        elif step_id == 'programas':
            show_programs(dlg, manifest.parent)
        elif step_id == 'launchers':
            show_launchers(dlg)
        elif step_id == 'navegador':
            if state['passwords']:
                notice.set(state['passwords'])
            show_recovery(dlg)

    dlg.after_format_open = open_step
    ttk.Button(frame, text='Fechar', command=dlg.destroy).pack(anchor='e')

    def on_destroy(event):
        if event.widget is not dlg:
            return
        if dialogs.get(key) is dlg:
            del dialogs[key]
        if state['job'] is not None:
            state['job'].cancelled.set()

    dlg.bind('<Destroy>', on_destroy, add='+')
    run_drive_check()
    return dlg
