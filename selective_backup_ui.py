"""v0.6.6 single, user-driven staging flow: inventory -> backup -> test restore.

Tk widgets only updated on the GUI thread via a queue. No deletion APIs.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from backup_core import human_size, atomic_json
from selective_recovery import (prepare_selected_c, run_selected_backup,
                                run_isolated_restore_test, verify_complete_manifest)


def show_selective_backup(app, plan):
    sources = list(plan.get('requires_verified_backup', []))
    current_choices = dict(getattr(app, 'choices', {}))
    window = tk.Toplevel(app)
    window.title('v0.6.6 • Backup seletivo e teste de recuperação do C:')
    window.geometry('1050x735')
    window.minsize(840, 580)
    window.transient(app)
    container = ttk.Frame(window, padding=18)
    container.pack(fill='both', expand=True)
    ttk.Label(container, text='Preservação real — fontes selecionadas do C:',
              font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(container, text=(
        'Analise os arquivos, escolha uma pasta no D:/F:/G:, copie e confira o SHA-256. '
        'Depois teste a recuperação em OUTRA pasta. Nenhuma operação escreve nos saves originais.'),
        wraplength=990).pack(anchor='w', pady=(5, 6))
    ttk.Label(container, text=(
        'ATENÇÃO: O G: é Storage Spaces sem redundância. Mesmo após os testes, '
        'uma única cópia não garante recuperação caso o SSD de destino falhe. '
        'Esta tela NUNCA libera a formatação do Windows.'),
        foreground='#F3BE67', wraplength=980).pack(anchor='w', pady=(0, 10))
    ttk.Label(container, text=f'{len(sources)} caminho(s) selecionado(s) no C:').pack(anchor='w')
    source_box = tk.Text(container, height=3, wrap='none', font=('Consolas', 9),
                         bg='#192438', fg='#EFF4FF', relief='flat')
    source_box.pack(fill='x', pady=(4, 10))
    source_box.insert('1.0', '\n'.join(sources) if sources else '(Nada selecionado no plano)')
    source_box.configure(state='disabled')

    summary = tk.StringVar(value='Etapa 1: analisar arquivos e tamanhos. Nenhuma cópia realizada.')
    ttk.Label(container, textvariable=summary, wraplength=960, foreground='#9C85FF').pack(anchor='w', pady=(0, 8))
    controls = ttk.Frame(container)
    controls.pack(fill='x', pady=(1, 10))
    row1 = ttk.Frame(controls); row1.pack(fill='x', pady=3)
    row2 = ttk.Frame(controls); row2.pack(fill='x', pady=3)
    destination = tk.StringVar(value='Nenhuma pasta de backup escolhida')
    manifest_label = tk.StringVar(value='Manifesto: ainda não existe')
    ttk.Label(container, textvariable=destination, wraplength=980).pack(anchor='w')
    ttk.Label(container, textvariable=manifest_label, wraplength=980).pack(anchor='w', pady=(2, 8))
    bar = ttk.Progressbar(container, maximum=100, mode='determinate')
    bar.pack(fill='x', pady=(4, 6))
    stage = tk.StringVar(value='Aguardando análise.')
    ttk.Label(container, textvariable=stage, wraplength=960).pack(anchor='w', pady=(0, 5))

    text_frame = ttk.Frame(container)
    text_frame.pack(fill='both', expand=True)
    log = tk.Text(text_frame, wrap='word', height=8, bg='#192438', fg='#EFF4FF',
                  relief='flat', font=('Consolas', 9))
    scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=log.yview)
    log.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y'); log.pack(side='left', fill='both', expand=True)

    commands = []
    event_queue = Queue()
    cancelled = threading.Event()
    state = {'busy': False, 'plan': None, 'manifest': None, 'backup_dir': None,
             'report': None, 'dest': None, 'worker': None}

    def write_log(line):
        log.configure(state='normal')
        log.insert('end', str(line) + '\n')
        log.see('end')
        log.configure(state='disabled')

    def toggle_busy(busy, label=''):
        state['busy'] = busy
        for b in commands:
            b.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')
        if busy:
            stage.set(label)
            bar.configure(mode='indeterminate')
            bar.start(12)
        else:
            bar.stop()
            bar.configure(mode='determinate')

    def process_events():
        if not window.winfo_exists():
            return
        try:
            while True:
                typ, data = event_queue.get_nowait()
                if typ == 'progress':
                    try:
                        args = data
                        if len(args) == 5:  # backup: index, total, bytes done, total bytes, filename
                            idx, total, done, size, filename = args
                            detail = f'{idx}/{total} • {human_size(done)} / {human_size(size)} • {Path(filename).name}'
                            ratio = 100*done/max(1, size)
                        elif len(args) == 6:  # restore: stage, index, total, file, done, file bytes
                            phase, idx, total, filename, done, size = args
                            detail = f'{phase}: {idx}/{total} • {Path(filename).name} • {human_size(done)} / {human_size(size)}'
                            ratio = 100*(idx / max(1, total))
                        else:
                            continue
                        stage.set(detail)
                        bar.stop(); bar.configure(mode='determinate', value=min(100, ratio))
                    except (TypeError, ValueError, IndexError):
                        pass
                elif typ == 'done':
                    job, outcome = data
                    toggle_busy(False)
                    if job == 'scan':
                        state['plan'] = outcome
                        summary.set(f'Plano examinado: {outcome.count} arquivo(s), {human_size(outcome.total)}. '
                                    'Ainda não foi feita nenhuma cópia.')
                        write_log(f'[ANÁLISE] {outcome.count} arquivo(s) • {human_size(outcome.total)}.')
                    elif job == 'backup':
                        state['report'] = outcome
                        state['manifest'] = outcome['manifest']
                        state['backup_dir'] = outcome['backup_folder']
                        manifest_label.set('Backup verificado: ' + outcome['manifest'])
                        summary.set(f'Backup realizado e verificado: {outcome["files_verified"]} arquivos, '
                                    f'{human_size(outcome["bytes_verified"])}. Recuperação NÃO testada.')
                        write_log('[BACKUP] SHA-256 aprovado. ' + outcome['manifest'])
                    elif job == 'verify':
                        state['report'] = outcome
                        state['manifest'] = outcome['manifest']
                        manifest_label.set('Manifesto conferido: ' + outcome['manifest'])
                        summary.set(f'Backup anterior conferido: {outcome["files_verified"]} arquivo(s). '
                                    'Ainda falta testar recuperação neste fluxo.')
                        write_log('[MANIFESTO] Hashes conferidos; restauração pendente.')
                    elif job == 'restore':
                        state['report'] = outcome
                        summary.set(f'RECUPERAÇÃO DE TESTE APROVADA: {outcome["files_verified"]} arquivos, '
                                    f'{human_size(outcome["bytes_verified"])} • {outcome["restored_folder"]}. '
                                    'Formatação continua bloqueada.')
                        write_log('[RESTAURAÇÃO] Concluída e conferida em: ' + outcome['restored_folder'])
                    stage.set('Operação concluída. Leia o resultado acima.')
                elif typ == 'error':
                    toggle_busy(False)
                    job, exception = data
                    stage.set('Falha/cancelamento na etapa: ' + job)
                    write_log(f'[FALHA {job}] {exception}')
                    messagebox.showerror('Operação não aprovada', str(exception), parent=window)
        except Empty:
            pass
        window.after(150, process_events)

    def start_job(kind, fn):
        if state['busy']:
            return
        cancelled.clear()
        toggle_busy(True, 'Iniciando ' + kind + '...')
        def run():
            try:
                outcome = fn()
                event_queue.put(('done', (kind, outcome)))
            except Exception as exc:
                event_queue.put(('error', (kind, str(exc))))
        state['worker'] = threading.Thread(target=run, name='PCRO-v066-' + kind, daemon=True)
        state['worker'].start()

    def analyze():
        start_job('scan', lambda: prepare_selected_c(sources, choices=current_choices,
                                                     cancelled=cancelled))

    def choose_dest():
        selected = filedialog.askdirectory(parent=window, title='Escolha uma pasta no D:, F: ou G: para BACKUP')
        if selected:
            state['dest'] = selected
            destination.set('Destino para o backup: ' + selected)

    def do_backup():
        if state['plan'] is None:
            return messagebox.showwarning('Análise pendente', 'Primeiro clique em Analisar arquivos do C:.', parent=window)
        if not state['dest']:
            return messagebox.showwarning('Destino pendente', 'Selecione uma pasta de destino.', parent=window)
        if not messagebox.askyesno('Confirmar criação de cópia',
                 f'Copiar {state["plan"].count} arquivo(s) ({human_size(state["plan"].total)}) para '
                 f'{state["dest"]}?\n\nNão apaga originais. Não autoriza formatar.', parent=window):
            return
        def copy():
            # Changes to the source tree since the preview require a fresh scan.
            new_plan = prepare_selected_c(sources, choices=current_choices, cancelled=cancelled)
            old = [(p.source, p.size, p.mtime_ns) for p in state['plan'].files]
            new = [(p.source, p.size, p.mtime_ns) for p in new_plan.files]
            if old != new:
                raise ValueError('Fontes mudaram desde a análise. Analise novamente antes de copiar.')
            return run_selected_backup(new_plan, state['dest'], cancelled=cancelled,
                                       progress=lambda *args: event_queue.put(('progress', args)))
        start_job('backup', copy)

    def choose_manifest():
        location = filedialog.askopenfilename(parent=window, title='Escolha manifest.json de backup anterior',
                                               filetypes=[('Manifesto JSON','*.json')])
        if location:
            start_job('verify', lambda: verify_complete_manifest(location, cancelled=cancelled))

    def do_restore():
        if not state['manifest']:
            return messagebox.showwarning('Falta backup', 'Conclua um backup ou confira manifesto anterior.', parent=window)
        location = filedialog.askdirectory(parent=window,
                           title='Escolha OUTRA pasta no D:, F: ou G: para restauração de teste')
        if not location:
            return
        if not messagebox.askyesno('Recuperação de teste isolada',
                    'Restaurar TODOS os arquivos do manifesto em uma nova subpasta de teste?\n'
                    'Não modifica o C: nem substitui saves originais.', parent=window):
            return
        start_job('restore', lambda: run_isolated_restore_test(state['manifest'], location,
              cancelled=cancelled, progress=lambda *args: event_queue.put(('progress', args))))

    def export_report():
        if state['report'] is None:
            return messagebox.showinfo('Sem relatório', 'Execute uma etapa para gerar resultado.', parent=window)
        location = filedialog.asksaveasfilename(parent=window, defaultextension='.json',
                          initialfile='resultado-backup-restauracao-v066.json',
                          filetypes=[('JSON','*.json')])
        if location:
            try:
                atomic_json(Path(location), state['report'])
                messagebox.showinfo('Relatório salvo', 'Dados registrados. Isso não autoriza formatação.', parent=window)
            except OSError as exc:
                messagebox.showerror('Erro de gravação', str(exc), parent=window)

    def add_button(row, label, cmd):
        b = ttk.Button(row, text=label, command=cmd)
        b.pack(side='left', padx=(0, 8), pady=2)
        commands.append(b)
        return b

    add_button(row1, '1. Analisar arquivos do C:', analyze)
    add_button(row1, '2. Escolher pasta para backup', choose_dest)
    add_button(row1, '3. Copiar e verificar SHA-256', do_backup)
    add_button(row2, 'Conferir backup anterior', choose_manifest)
    add_button(row2, '4. Recuperação de TESTE (pasta nova)', do_restore)
    add_button(row2, 'Exportar relatório', export_report)
    stop = ttk.Button(row2, text='Cancelar operação', command=cancelled.set, state='disabled')
    stop.pack(side='right')
    def close():
        if state['busy']:
            cancelled.set()
            messagebox.showinfo('Cancelamento solicitado',
                'Aguarde a operação parar antes de fechar. Dados parciais não são considerados verificados.', parent=window)
            return
        window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    write_log('Nenhuma exclusão ou formatação será realizada.')
    write_log('O backup grava em uma pasta nova. A recuperação também grava em outra pasta nova.')
    window.after(150, process_events)
    return window
