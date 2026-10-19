"""First-launch test-only picker: reopen saved fixture backups without a plan.

This Toplevel never changes the production app or searches real drives.
Users explicitly choose existing backup base folders inside one isolated
test root; all paths are revalidated by the offline manifest importer.
No copy, checksum or restore begins merely by opening this window.
"""
from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from multi_source_fixture_restore import _inside, _overlaps
from multi_source_offline_import import reopen_fixture_backup_session
from multi_source_recovery_center_ui import show_fixture_recovery_center
from selective_recovery import _any_reparse_ancestor
from ui_timers import WindowTimers


def show_fixture_offline_reopen(parent, *, test_root, restore_parent,
                                initial_backup_roots=()):
    """Pick up to eight sandbox backups and launch their verification window.

    Reopening is metadata-only. The child recovery center requires a separate
    user click to hash backup copies and another confirmation to restore.
    """
    if test_root is None:
        raise ValueError('A reabertura exige uma raiz isolada de testes.')
    _any_reparse_ancestor(Path(test_root))
    sandbox = Path(test_root).resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Raiz de testes inválida.')
    restore_dir = _inside(sandbox, restore_parent)
    if not restore_dir.is_dir():
        raise ValueError('Pasta de recuperação inválida.')
    if not isinstance(initial_backup_roots, (list, tuple)):
        raise ValueError('Seleção de pastas inválida.')

    validated = []
    for raw in initial_backup_roots:
        path = _inside(sandbox, raw)
        if (not path.is_dir() or _overlaps(path, restore_dir) or
                any(_overlaps(path, other) for other in validated)):
            raise ValueError('Pasta de cópia duplicada ou sobreposta.')
        validated.append(path)
        if len(validated) > 8:
            raise ValueError('Limite de oito cópias de teste.')

    dlg = tk.Toplevel(parent)
    dlg.title('PC Restore & Optimizer — Reabrir backups (SOMENTE TESTES)')
    dlg.geometry('880x540')
    dlg.minsize(660, 420)
    timers = WindowTimers(dlg)
    pending = Queue()
    cancelled = threading.Event()
    state = {'busy': False, 'closing': False, 'paths': validated,
             'child': None}

    frame = ttk.Frame(dlg, padding=15)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Reabrir cópias após reinstalação — demonstração',
              font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    ttk.Label(
        frame,
        text=('Escolha as pastas que CONTÊM um backup-... cada. '
              'Somente diretórios fictícios da raiz de testes são aceitos. '
              'Não é necessário ter o inventário ou arquivos originais.'),
        wraplength=820,
    ).pack(anchor='w', pady=(7, 8))
    status = tk.StringVar(master=dlg, value='Nenhuma cópia aberta ou verificada.')
    ttk.Label(frame, textvariable=status, wraplength=820).pack(
        fill='x', pady=(0, 9))

    entry_row = ttk.Frame(frame)
    entry_row.pack(fill='x')
    ttk.Label(entry_row, text='Pasta de backup de teste:').pack(
        side='left', padx=(0, 6))
    path_text = tk.StringVar(master=dlg)
    location = ttk.Entry(entry_row, textvariable=path_text)
    location.pack(side='left', fill='x', expand=True)
    listview = ttk.Treeview(
        frame, columns=('index',), show='tree headings',
        height=9, selectmode='browse')
    listview.heading('#0', text='Pastas escolhidas')
    listview.heading('index', text='Ordem')
    listview.column('#0', width=720)
    listview.column('index', width=70, anchor='center', stretch=False)
    listview.pack(fill='both', expand=True, pady=(12, 10))

    def refresh():
        for item in listview.get_children(''):
            listview.delete(item)
        for index, path in enumerate(state['paths'], 1):
            listview.insert('', 'end', iid=f'folder:{index}',
                            text=str(path), values=(str(index),))
        open_btn.configure(state='normal' if (
            state['paths'] and not state['busy']) else 'disabled')

    def add_path(raw):
        if state['busy']:
            return
        try:
            selected = _inside(sandbox, raw)
            if not selected.is_dir():
                raise ValueError('A cópia deve ser uma pasta existente.')
            if _overlaps(selected, restore_dir) or any(
                    _overlaps(selected, x) for x in state['paths']):
                raise ValueError('Pasta repetida ou sobreposta.')
            if len(state['paths']) >= 8:
                raise ValueError('No máximo oito cópias de teste.')
            state['paths'].append(selected)
            path_text.set('')
            refresh()
            status.set(
                f"{len(state['paths'])} pasta(s) selecionada(s). "
                'Nenhuma verificação executada.')
        except (OSError, ValueError, TypeError) as exc:
            status.set(f'Pasta recusada: {exc}')

    def browse():
        if state['busy']:
            return
        value = filedialog.askdirectory(
            parent=dlg, initialdir=str(sandbox),
            title='Escolher pasta de backup da raiz de testes')
        if value:
            add_path(value)

    def remove():
        if state['busy']:
            return
        chosen = listview.selection()
        if not chosen:
            return
        index = int(chosen[0].split(':', 1)[1]) - 1
        state['paths'].pop(index)
        refresh()
        status.set('Pasta retirada da seleção; cópias não foram modificadas.')

    def set_busy(value):
        state['busy'] = value
        for control in (add_btn, browse_btn, remove_btn):
            control.configure(state='disabled' if value else 'normal')
        open_btn.configure(state='disabled' if value or not state['paths']
                           else 'normal')

    def reopen():
        if state['busy'] or not state['paths']:
            return
        cancelled.clear()
        set_busy(True)
        status.set('Lendo manifestos selecionados; nenhuma cópia aprovada ainda.')
        roots = [str(path) for path in state['paths']]

        def worker():
            try:
                result = reopen_fixture_backup_session(
                    roots, str(restore_dir), test_root=str(sandbox),
                    cancelled=cancelled)
                pending.put(('ok', result))
            except InterruptedError:
                pending.put(('cancelled', None))
            except Exception as exc:
                pending.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def close():
        if state['busy']:
            state['closing'] = True
            cancelled.set()
            status.set('Aguardando interrupção segura da leitura…')
        else:
            dlg.destroy()

    add_btn = ttk.Button(entry_row, text='Adicionar',
                         command=lambda: add_path(path_text.get()))
    add_btn.pack(side='left', padx=(7, 3))
    browse_btn = ttk.Button(entry_row, text='Escolher pasta…', command=browse)
    browse_btn.pack(side='left')
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x')
    remove_btn = ttk.Button(buttons, text='Remover pasta', command=remove)
    remove_btn.pack(side='left')
    open_btn = ttk.Button(buttons, text='Reabrir backups de teste',
                          command=reopen, state='disabled')
    open_btn.pack(side='left', padx=10)
    ttk.Button(buttons, text='Cancelar / Fechar', command=close).pack(
        side='right')

    def poll():
        if timers.closed:
            return
        for _ in range(8):
            try:
                outcome, result = pending.get_nowait()
            except Empty:
                break
            if state['closing']:
                state['busy'] = False
                dlg.destroy()
                return
            set_busy(False)
            if outcome == 'cancelled':
                status.set('Reabertura interrompida. Nenhum arquivo restaurado.')
            elif outcome == 'error':
                status.set(f'Reabertura bloqueada: {result}')
            else:
                # The import has NOT verified copy integrity; the child starts
                # with all verification/restore buttons safely disabled.
                try:
                    child = show_fixture_recovery_center(
                        dlg, result['plan'], result['copies_report'],
                        test_root=str(sandbox),
                        restore_parent=result['restore_parent'])
                except (OSError, ValueError, tk.TclError) as exc:
                    status.set(f'Não foi possível abrir a conferência: {exc}')
                    continue
                state['child'] = child
                status.set(
                    'Inventário reencontrado. Verifique SHA-256 na próxima tela.')
                dlg.withdraw()

                def when_child_closes(event):
                    if event.widget is child and dlg.winfo_exists():
                        state['child'] = None
                        dlg.deiconify()
                child.bind('<Destroy>', when_child_closes, add='+')
        if not timers.closed:
            timers.after(100, poll)

    refresh()
    dlg.protocol('WM_DELETE_WINDOW', close)
    timers.after(100, poll)
    return dlg
