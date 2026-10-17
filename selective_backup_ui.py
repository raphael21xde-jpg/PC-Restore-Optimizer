"""v0.6.6 single, user-driven staging flow: inventory -> backup -> test restore.

Tk widgets only updated on the GUI thread via a queue. No deletion APIs.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from queue import Queue, Empty
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from backup_core import human_size, atomic_json
from selective_recovery import (prepare_selected_c, run_selected_backup,
                                run_isolated_restore_test, verify_complete_manifest)
from multi_backup_destinations import make_multi_backup_plan, run_multiple_backups
from multi_backup_destinations_ui import open_destination_picker
from autoteste_integridade import run_integrity_autotest
from autoteste_completude import run_completeness_autotest
from autoteste_interrupcao import run_interruption_autotest
from autotestes_resiliencia import (run_midfile_autotest, run_repair_autotest,
                                    run_resume_guard_autotest)
from autotestes_falhas import (run_large_transfer_autotest, run_many_files_autotest,
                              run_storage_fault_autotest, run_restart_recovery_autotest)

from autotestes_escala import (run_gigabyte_autotest, run_abrupt_exit_autotest,
                                run_responsiveness_autotest)
from autotestes_bateria import (run_tiny_files_stress_autotest,
                               run_readonly_inventory_autotest,
                               run_isolated_full_restore_autotest)
from autotestes_41_43 import (run_inventory_permissions_autotest,
                              run_cross_volume_links_autotest,
                              run_restore_write_recovery_autotest)
from inventory_paged import PagedMetadataScanner, discover_local_roots
from file_index_ui import show_file_index
from autotestes_44_46 import (run_paged_inventory_autotest,
                              run_pause_resume_inventory_autotest,
                              run_gaps_inventory_autotest)


def show_selective_backup(app, plan):
    sources = list(plan.get('requires_verified_backup', []))
    current_choices = dict(getattr(app, 'choices', {}))
    window = tk.Toplevel(app)
    window.title('v0.6.6 • PC Restore & Optimizer • Backup e testes de recuperação')
    # A transient dialog on Windows may lose its maximize control. Keep a normal,
    # independently resizable window instead of binding its size to the parent.
    window.resizable(True, True)
    screen_width, screen_height = window.winfo_screenwidth(), window.winfo_screenheight()
    window.minsize(min(640, max(360, screen_width-80)),
                   min(420, max(280, screen_height-100)))
    window.geometry(f'{min(1060, max(360, screen_width-80))}x'
                    f'{min(780, max(280, screen_height-100))}')
    # A persistent footer makes Cancel and Export reachable on every tab.
    toolbar = ttk.Frame(window, padding=(12, 5))
    toolbar.pack(side='bottom', fill='x')
    # The main content may scroll independently when the screen is small.
    viewport = tk.Canvas(window, highlightthickness=0)
    page_scroll = ttk.Scrollbar(window, orient='vertical', command=viewport.yview)
    viewport.configure(yscrollcommand=page_scroll.set)
    page_scroll.pack(side='right', fill='y')
    viewport.pack(side='left', fill='both', expand=True)
    container = ttk.Frame(viewport, padding=18)
    page_item = viewport.create_window((0, 0), window=container, anchor='nw')
    container.bind('<Configure>', lambda e: viewport.configure(scrollregion=viewport.bbox('all')))
    viewport.bind('<Configure>', lambda e: viewport.itemconfigure(page_item, width=e.width))

    def wheel_scroll(event):
        # Do not steal wheel events from the log or other native scrolling widgets.
        if event.widget.winfo_class() in ('Text', 'Treeview', 'Listbox'):
            return
        if getattr(event, 'num', None) == 4:
            amount = -1
        elif getattr(event, 'num', None) == 5:
            amount = 1
        else:
            delta = getattr(event, 'delta', 0)
            amount = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1 if delta < 0 else 0)
        if amount:
            viewport.yview_scroll(amount, 'units')

    # Bind at the window level (not bind_all) so other program windows are unaffected.
    window.bind('<MouseWheel>', wheel_scroll, add='+')
    window.bind('<Button-4>', wheel_scroll, add='+')
    window.bind('<Button-5>', wheel_scroll, add='+')
    window.bind('<Prior>', lambda _: viewport.yview_scroll(-4, 'units'), add='+')
    window.bind('<Next>', lambda _: viewport.yview_scroll(4, 'units'), add='+')
    ttk.Label(container, text='Preservação real — fontes selecionadas do C:',
              font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(container, text=(
        'Analise os arquivos, escolha uma ou várias pastas fora do C: e confira SHA-256. '
        'Depois teste a recuperação em OUTRA pasta. Nenhuma operação escreve nos saves originais.'),
        wraplength=990).pack(anchor='w', pady=(5, 6))
    ttk.Label(container, text=(
        'ATENÇÃO: unidades internas, externas e pastas sincronizadas podem compartilhar '
        'hardware. Uma pasta sincronizada NÃO prova envio à nuvem. '
        'Esta tela NUNCA libera formatação do Windows.'),
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
    ttk.Label(controls, text='Escolha uma aba: operações, segurança, desempenho ou novos testes.').pack(anchor='w')
    tabs = ttk.Notebook(controls)
    tabs.pack(fill='x', expand=True, pady=(5, 2))
    operations_tab = ttk.Frame(tabs, padding=8)
    integrity_tab = ttk.Frame(tabs, padding=8)
    performance_tab = ttk.Frame(tabs, padding=8)
    recent_tab = ttk.Frame(tabs, padding=8)
    next_tab = ttk.Frame(tabs, padding=8)
    paged_tab = ttk.Frame(tabs, padding=8)
    tabs.add(operations_tab, text='Backup')
    tabs.add(integrity_tab, text='#25–30')
    tabs.add(performance_tab, text='#31–37')
    tabs.add(recent_tab, text='Novos #38–40')
    tabs.add(next_tab, text='#41–43')
    tabs.add(paged_tab, text='Novos #44–46')
    rows = []
    for number in range(1, 29):
        parent = (operations_tab if number <= 2 else
                  integrity_tab if number <= 8 else
                  performance_tab if number <= 15 else
                  recent_tab if number <= 18 else
                  next_tab if number <= 21 else paged_tab)
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=3)
        rows.append(row)
    (row1, row2, row3, row4, row5, row6, row7, row8, row9, row10, row11, row12, row13, row14, row15, row16, row17, row18, row19, row20, row21, row22, row23, row24, row25, row26, row27, row28) = rows
    # Open directly to the newest battery when requested by keyboard.
    window.bind('<Alt-n>', lambda _: tabs.select(paged_tab), add='+')
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
             'report': None, 'dest': None, 'multi_targets': [], 'worker': None, 'job': None,
             'probe': None, 'metadata_scanner': None}

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
        probe = state.get('probe')
        if state['busy'] and state.get('job') == 'autotest37' and probe is not None:
            now = time.monotonic()
            probe['gaps'].append(now - probe['last'])
            probe['last'] = now
            probe['ticks'] += 1
            if probe['armed']:
                probe['armed_ticks'] += 1
                stage.set(f"Teste da interface: {probe['ticks']} atualizações; cancelamento automático em andamento.")
                if probe['armed_ticks'] == 8:
                    probe_button.invoke()  # dispatch the actual Tk button command on the GUI thread
        try:
            while True:
                typ, data = event_queue.get_nowait()
                if typ == 'autotest_note':
                    stage.set(str(data))
                    if state.get('job') == 'autotest37' and state.get('probe'):
                        state['probe']['armed'] = True
                elif typ == 'progress':
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
                    elif job == 'backup_multi':
                        state['report'] = outcome
                        passed = outcome.get('copies_verified_locally', 0)
                        total = outcome.get('copies_requested', 0)
                        valid = [x for x in outcome.get('destinations', [])
                                 if x.get('status') == 'local_copy_verified']
                        if valid:
                            state['manifest'] = valid[0]['manifest']
                            state['backup_dir'] = valid[0]['backup_folder']
                            manifest_label.set('Manifesto da 1ª cópia: ' + valid[0]['manifest'])
                        summary.set(f'Cópias locais verificadas: {passed}/{total}. '
                                    'Sincronização na nuvem e independência física NÃO verificadas. '
                                    'Restauração pendente; formatação bloqueada.')
                        for item in outcome.get('destinations', []):
                            write_log('['+str(item.get('status'))+'] ' +
                                      str(item.get('path'))+
                                      (' | '+str(item.get('error')) if item.get('error') else ''))
                        if passed != total:
                            messagebox.showwarning('Cópias incompletas',
                                'Nem todos os destinos foram verificados. Consulte o relatório.',
                                parent=window)
                    elif job == 'verify':
                        state['report'] = outcome
                        state['manifest'] = outcome['manifest']
                        manifest_label.set('Manifesto conferido: ' + outcome['manifest'])
                        summary.set(f'Backup anterior conferido: {outcome["files_verified"]} arquivo(s). '
                                    'Ainda falta testar recuperação neste fluxo.')
                        write_log('[MANIFESTO] Hashes conferidos; restauração pendente.')
                    elif job == 'autotest25':
                        state['report'] = outcome
                        summary.set('AUTOTESTE #25 APROVADO: corrupção detectada pelo SHA-256; '
                                    'restauração insegura bloqueada. Somente dados fictícios foram usados.')
                        write_log('[AUTOTESTE #25] Arquivo fictício alterado (mesmo tamanho).')
                        write_log('[AUTOTESTE #25] SHA-256 divergente; restauração recusada antes de escrever arquivos.')
                        write_log('[AUTOTESTE #25] Originais fictícios preservados; dados temporários removidos.')
                        write_log('[AUTOTESTE #25] Não verifica backups reais nem autoriza formatação.')
                    elif job == 'autotest26':
                        state['report'] = outcome
                        summary.set('AUTOTESTE #26 APROVADO: arquivo ausente e backups incompletos '
                                    'detectados; restaurações inseguras bloqueadas.')
                        write_log('[AUTOTESTE #26] Arquivo fictício ausente: detectado.')
                        write_log('[AUTOTESTE #26] Manifesto interrompido: rejeitado.')
                        write_log('[AUTOTESTE #26] Manifesto incompleto: rejeitado.')
                        write_log('[AUTOTESTE #26] Nenhuma restauração insegura gerou arquivos.')
                        write_log('[AUTOTESTE #26] Fontes fictícias intactas; área temporária removida.')
                        write_log('[AUTOTESTE #26] Nenhum backup real examinado; formatação bloqueada.')
                    elif job == 'autotest27':
                        state['report'] = outcome
                        summary.set('AUTOTESTE #27 APROVADO: backup e restauração cancelados, '
                                    'retomados e conferidos por SHA-256 em ambiente isolado.')
                        write_log('[AUTOTESTE #27] Backup fictício interrompido e recusado como completo.')
                        write_log('[AUTOTESTE #27] Backup retomado e verificado com SHA-256.')
                        write_log('[AUTOTESTE #27] Restauração fictícia cancelada com diário parcial.')
                        write_log('[AUTOTESTE #27] Restauração retomada; arquivos verificados por SHA-256.')
                        write_log('[AUTOTESTE #27] Originais preservados; arquivos temporários removidos.')
                        write_log('[AUTOTESTE #27] Não examina backups reais nem autoriza formatação.')
                    elif job in ('autotest28', 'autotest29', 'autotest30'):
                        number = job[-2:]
                        state['report'] = outcome
                        summary.set(f'AUTOTESTE #{number} APROVADO: ' +
                                    ('cancelamento dentro do arquivo e retomada com SHA-256.'
                                     if number == '28' else
                                     'cópias adulteradas corrigidas com SHA-256.'
                                     if number == '29' else
                                     'retomadas incompatíveis foram bloqueadas.'))
                        write_log(f'[AUTOTESTE #{number}] Testes sintéticos concluídos e validados.')
                        write_log(f'[AUTOTESTE #{number}] Arquivos temporários removidos.')
                        write_log(f'[AUTOTESTE #{number}] Backups reais não acessados; formatação bloqueada.')
                    elif job in ('autotest31', 'autotest32', 'autotest33', 'autotest34'):
                        number = job[-2:]
                        state['report'] = outcome
                        summaries = {
                            '31': '32 MiB sintéticos copiados/restaurados com SHA-256.',
                            '32': '1.024 arquivos sintéticos verificados e restaurados.',
                            '33': 'Falhas sintéticas de espaço e I/O recusadas com segurança.',
                            '34': 'Checkpoints incompletos identificados; retomada conferida.',
                        }
                        summary.set(f'AUTOTESTE #{number} APROVADO: ' + summaries[number])
                        write_log(f'[AUTOTESTE #{number}] ' + summaries[number])
                        write_log(f'[AUTOTESTE #{number}] Área temporária eliminada.')
                        write_log(f'[AUTOTESTE #{number}] Sem acesso a backups reais; formatação bloqueada.')
                    elif job in ('autotest35', 'autotest36', 'autotest37'):
                        number = int(job[-2:])
                        if number == 37:
                            probe = state['probe']
                            maximum = max(probe['gaps'], default=999)
                            valid = (probe['ticks'] >= 8 and maximum <= 1.0 and probe['invoked'])
                            outcome.update(tk_event_loop_ticks=probe['ticks'],
                                maximum_tk_gap_seconds=round(maximum, 4),
                                tk_gap_limit_seconds=1.0, tk_cancel_button_invoked=probe['invoked'],
                                tk_event_loop_passed=valid)
                            probe_button.configure(state='disabled')
                            if not valid:
                                outcome['status'] = 'reprovado'
                        state['report'] = outcome
                        summary.set(f"AUTOTESTE #{number}: {outcome['status'].upper()}. Exporte o relatório.")
                        write_log(f"[AUTOTESTE #{number}] " + json.dumps(outcome, ensure_ascii=False))
                    elif job in ('autotest38', 'autotest39', 'autotest40'):
                        number = int(job[-2:])
                        state['report'] = outcome
                        summaries = {
                            38: 'Carga de arquivos pequenos, restauração e SHA-256.',
                            39: 'Leitura limitada de metadados; inventário NÃO completo.',
                            40: 'Seleção granular e restauração fictícia em pasta isolada.',
                        }
                        summary.set(f"AUTOTESTE #{number}: {outcome['status'].upper()}. "
                                    + summaries[number] + ' Exporte o JSON.')
                        write_log(f'[AUTOTESTE #{number}] ' +
                                  json.dumps(outcome, ensure_ascii=False))
                        write_log(f'[AUTOTESTE #{number}] Não autoriza formatação.')
                    elif job in ('autotest41', 'autotest42', 'autotest43'):
                        number = int(job[-2:])
                        state['report'] = outcome
                        summaries = {
                            41: 'Metadados locais ampliados; cobertura parcial e erros classificados.',
                            42: 'Relações sintéticas entre discos; associações não são backups.',
                            43: 'Falha de gravação detectada; recuperação fictícia com SHA-256.',
                        }
                        summary.set(f"AUTOTESTE #{number}: {outcome['status'].upper()}. "
                                    + summaries[number] + ' Exporte o relatório.')
                        write_log(f'[AUTOTESTE #{number}] ' +
                                  json.dumps(outcome, ensure_ascii=False))
                        write_log(f'[AUTOTESTE #{number}] Nenhuma formatação autorizada.')
                    elif job in ('autotest44', 'autotest45', 'autotest46'):
                        number = int(job[-2:])
                        state['report'] = outcome
                        summaries = {
                            44: 'Páginas sintéticas sem duplicar arquivos.',
                            45: 'Pausa e retomada de cursor em memória.',
                            46: 'Acesso negado e links registrados como lacunas.',
                        }
                        summary.set(f"AUTOTESTE #{number}: {outcome['status'].upper()}. " +
                                    summaries[number] + ' Exporte o relatório.')
                        write_log(f'[AUTOTESTE #{number}] ' +
                                  json.dumps(outcome, ensure_ascii=False))
                    elif job == 'paged_scan':
                        state['report'] = outcome
                        count = outcome['entries_examined']
                        remaining = outcome['directories_pending']
                        summary.set(f'Inventário paginado: {count} entradas; ' +
                                    f'{remaining} diretórios pendentes. ' +
                                    ('Sessão terminou com escopo limitado. ' if outcome['finished_current_session']
                                     else 'Clique em continuar para mais uma página. ') +
                                    'Não autoriza formatação.')
                        write_log('[INVENTÁRIO POR PÁGINAS] ' +
                                  f'{count} entradas, {remaining} diretórios pendentes; ' +
                                  f"estado={outcome['status']}.")
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
                    probe_button.configure(state='disabled')
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
        state['job'] = kind
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
        selected = filedialog.askdirectory(parent=window,
                  title='Escolha uma pasta existente fora do C: para backup local')
        if selected:
            state['dest'] = selected
            state['multi_targets'] = []
            destination.set('Destino único para o backup: ' + selected)

    def choose_multiple():
        def selected(items):
            state['multi_targets'] = items
            state['dest'] = None
            destination.set('Destinos múltiplos: ' +
                            ' | '.join(item['kind']+': '+item['path'] for item in items))
        open_destination_picker(window, state['multi_targets'], selected)

    def do_backup():
        if state['plan'] is None:
            return messagebox.showwarning('Análise pendente',
                                          'Primeiro clique em Analisar arquivos do C:.', parent=window)
        if not state['dest'] and not state['multi_targets']:
            return messagebox.showwarning('Destino pendente',
                                          'Selecione um ou mais destinos.', parent=window)
        multi = [dict(x) for x in state['multi_targets']]
        diagnostic = (getattr(app, 'diagnostic_data', None) or {}).get('disks')
        if multi:
            try:
                staged = make_multi_backup_plan(state['plan'], multi,
                                                disk_diagnostic=diagnostic)
            except (OSError, ValueError) as exc:
                return messagebox.showerror('Destinos não aprovados', str(exc), parent=window)
            question = (f'Copiar {state["plan"].count} arquivos ({human_size(state["plan"].total)}) '
                        f'em {len(multi)} destino(s)?\n\n'
                        'Cada destino terá verificação SHA-256 própria.\n'
                        'Discos físicos e sincronização em nuvem NÃO comprovados.\n'
                        'Não apaga fontes nem autoriza formatar.')
        else:
            question = (f'Copiar {state["plan"].count} arquivo(s) '
                        f'({human_size(state["plan"].total)}) para {state["dest"]}?\n\n'
                        'Não apaga originais. Não autoriza formatar.')
        if not messagebox.askyesno('Confirmar criação de cópias', question, parent=window):
            return
        def copy():
            # Changes to the source tree since the preview require a fresh scan.
            new_plan = prepare_selected_c(sources, choices=current_choices, cancelled=cancelled)
            old = [(p.source, p.size, p.mtime_ns) for p in state['plan'].files]
            new = [(p.source, p.size, p.mtime_ns) for p in new_plan.files]
            if old != new:
                raise ValueError('Fontes mudaram desde a análise. Analise novamente antes de copiar.')
            if multi:
                # Recheck capacity/path conflicts immediately before each group of copies.
                new_staged = make_multi_backup_plan(new_plan, multi,
                                                    disk_diagnostic=diagnostic)
                return run_multiple_backups(new_plan, new_staged, cancelled=cancelled,
                    progress=lambda index, total, *args:
                        event_queue.put(('progress', args)))
            return run_selected_backup(new_plan, state['dest'], cancelled=cancelled,
                                       progress=lambda *args: event_queue.put(('progress', args)))
        start_job('backup_multi' if multi else 'backup', copy)

    def choose_manifest():
        location = filedialog.askopenfilename(parent=window, title='Escolha manifest.json de backup anterior',
                                               filetypes=[('Manifesto JSON','*.json')])
        if location:
            start_job('verify', lambda: verify_complete_manifest(location, cancelled=cancelled))

    def do_restore():
        if not state['manifest']:
            return messagebox.showwarning('Falta backup', 'Conclua um backup ou confira manifesto anterior.', parent=window)
        location = filedialog.askdirectory(parent=window,
                           title='Escolha OUTRA pasta fora do C: para restauração de teste')
        if not location:
            return
        if not messagebox.askyesno('Recuperação de teste isolada',
                    'Restaurar TODOS os arquivos do manifesto em uma nova subpasta de teste?\n'
                    'Não modifica o C: nem substitui saves originais.', parent=window):
            return
        start_job('restore', lambda: run_isolated_restore_test(state['manifest'], location,
              cancelled=cancelled, progress=lambda *args: event_queue.put(('progress', args))))

    def run_autotest25():
        # Isolated synthetic data only; does not use the current plan or real backups.
        start_job('autotest25', lambda: run_integrity_autotest(cancelled=cancelled))

    def run_autotest26():
        # Synthetic temporary data only. Does not use the user's backup selection.
        start_job('autotest26', lambda: run_completeness_autotest(cancelled=cancelled))

    def run_autotest27():
        # Does not touch the current plan, selected backups or installed applications.
        state['report'] = None
        start_job('autotest27', lambda: run_interruption_autotest(cancelled=cancelled))

    def run_resilience_autotest(number, runner):
        # Three separate buttons; never use current plan or any real backup path.
        state['report'] = None
        start_job('autotest' + str(number), lambda: runner(cancelled=cancelled))

    def run_fault_autotest(number, runner):
        # Uses private temporary synthetic files only, not the user's current plan.
        state['report'] = None
        start_job('autotest' + str(number), lambda: runner(cancelled=cancelled))

    def run_scale_autotest(number, runner):
        if state['busy']:
            return
        state['report'] = None
        start_job('autotest' + str(number), lambda: runner(cancelled=cancelled,
                    progress=lambda note: event_queue.put(('autotest_note', note))))

    def invoke_probe_cancel():
        probe = state.get('probe')
        if state['busy'] and state.get('job') == 'autotest37' and probe and probe['armed']:
            probe['invoked'] = True
            probe['cancel'].set()
            probe_button.configure(state='disabled')

    def run_ui_autotest():
        if state['busy']:
            return
        state['report'] = None
        state['probe'] = dict(last=time.monotonic(), ticks=0, gaps=[], armed=False,
                              armed_ticks=0, invoked=False, cancel=threading.Event())
        start_job('autotest37', lambda: run_responsiveness_autotest(cancelled=cancelled,
                    ui_cancel=state['probe']['cancel'],
                    progress=lambda note: event_queue.put(('autotest_note', note))))
        probe_button.configure(state='normal')

    def export_report():
        if state['report'] is None:
            return messagebox.showinfo('Sem relatório', 'Execute uma etapa para gerar resultado.', parent=window)
        location = filedialog.asksaveasfilename(parent=window, defaultextension='.json',
                          initialfile=(f"resultado-autoteste{state['report']['schema'].rsplit('v', 1)[-1]}.json"
                                       if state['report'].get('schema') in {f'pcro-autoteste-bateria-v{n}' for n in range(38,47)}
                                       else f"resultado-autoteste{state['report']['schema'].rsplit('v', 1)[-1]}.json"
                                        if state['report'].get('schema') in {f'pcro-autoteste-escala-v{n}' for n in (35, 36, 37)}
                                        else 'resultado-autoteste31.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-falhas-v31'
                                        else 'resultado-autoteste32.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-falhas-v32'
                                        else 'resultado-autoteste33.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-falhas-v33'
                                        else 'resultado-autoteste34.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-falhas-v34'
                                        else 'resultado-autoteste28.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-resiliencia-v28'
                                        else 'resultado-autoteste29.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-resiliencia-v29'
                                        else 'resultado-autoteste30.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-resiliencia-v30'
                                        else 'resultado-autoteste27.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-interrupcao-v1'
                                        else 'resultado-autoteste26.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-completude-v1'
                                        else 'resultado-autoteste25.json'
                                        if state['report'].get('schema') == 'pcro-autoteste-integridade-v1'
                                        else 'resultado-inventario-paginado.json'
                                        if state['report'].get('schema') == 'pcro-inventario-paginado-v1'
                                        else 'resultado-backup-restauracao-v066.json'),
                          filetypes=[('JSON','*.json')])
        if location:
            try:
                atomic_json(Path(location), state['report'])
                messagebox.showinfo('Relatório salvo', 'Dados registrados. Isso não autoriza formatação.', parent=window)
            except OSError as exc:
                messagebox.showerror('Erro de gravação', str(exc), parent=window)

    def add_button(row, label, cmd):
        b = ttk.Button(row, text=label, command=cmd)
        # Stack buttons vertically; horizontal stacking clipped the far-right
        # actions on common laptop resolutions and high-DPI Windows settings.
        b.pack(anchor='w', pady=2)
        commands.append(b)
        return b

    add_button(row1, '1. Analisar arquivos do C:', analyze)
    add_button(row1, '2. Escolher pasta única', choose_dest)
    add_button(row1, '2b. Vários destinos', choose_multiple)
    add_button(row2, '3. Copiar e verificar SHA-256', do_backup)
    add_button(row2, 'Conferir backup anterior', choose_manifest)
    add_button(row2, '4. Recuperação de TESTE (pasta nova)', do_restore)
    add_button(row3, '5. Autoteste #25: corrupção SHA-256 (isolado)', run_autotest25)
    ttk.Label(row3, text='Dados fictícios temporários; nenhum backup real será alterado.',
              wraplength=470).pack(anchor='w', padx=(8, 0))
    add_button(row4, '6. Autoteste #26: arquivos ausentes e incompletos', run_autotest26)
    ttk.Label(row4, text='Somente dados fictícios; não escreve nos backups reais.',
              wraplength=470).pack(anchor='w', padx=(8, 0))
    add_button(row5, '7. Autoteste #27: cancelar e retomar (isolado)', run_autotest27)
    ttk.Label(row5, text='Backup/restauração fictícios; SHA-256 na retomada.',
              wraplength=430).pack(anchor='w', padx=(8, 0))
    add_button(row6, '8. Autoteste #28: interromper arquivo grande',
               lambda: run_resilience_autotest(28, run_midfile_autotest))
    ttk.Label(row6, text='Cancela durante a cópia; retoma com SHA-256.',
              wraplength=430).pack(anchor='w', padx=(8, 0))
    add_button(row7, '9. Autoteste #29: reparar arquivo adulterado',
               lambda: run_resilience_autotest(29, run_repair_autotest))
    ttk.Label(row7, text='Corrupção sintética; recópia segura ao retomar.',
              wraplength=430).pack(anchor='w', padx=(8, 0))
    add_button(row8, '10. Autoteste #30: impedir retomada insegura',
               lambda: run_resilience_autotest(30, run_resume_guard_autotest))
    ttk.Label(row8, text='Bloqueia fontes, destinos e manifestos incompatíveis.',
              wraplength=430).pack(anchor='w', padx=(8, 0))
    add_button(row9, '11. Autoteste #31: transferência 32 MiB (isolado)',
               lambda: run_fault_autotest(31, run_large_transfer_autotest))
    add_button(row10, '12. Autoteste #32: 1.024 arquivos pequenos (isolado)',
               lambda: run_fault_autotest(32, run_many_files_autotest))
    add_button(row11, '13. Autoteste #33: falhas de espaço e I/O (simuladas)',
               lambda: run_fault_autotest(33, run_storage_fault_autotest))
    add_button(row12, '14. Autoteste #34: checkpoint e retomada (simulado)',
               lambda: run_fault_autotest(34, run_restart_recovery_autotest))
    add_button(row13, '15. Autoteste #35: 2 GiB e pico de memória',
               lambda: run_scale_autotest(35, run_gigabyte_autotest))
    add_button(row14, '16. Autoteste #36: encerramento abrupto de subprocesso',
               lambda: run_scale_autotest(36, run_abrupt_exit_autotest))
    add_button(row15, '17. Autoteste #37: resposta da interface e cancelamento', run_ui_autotest)
    probe_button = ttk.Button(row15, text='Cancelar cópia fictícia (#37)',
                              command=invoke_probe_cancel, state='disabled')
    probe_button.pack(side='left', padx=8)
    add_button(row16, '18. Autoteste #38: 2.048 arquivos pequenos',
               lambda: run_fault_autotest(38, run_tiny_files_stress_autotest))
    ttk.Label(row16, text='Somente arquivos temporários; SHA-256.',
              wraplength=390).pack(anchor='w', padx=(8, 0))
    add_button(row17, '19. Autoteste #39: auditoria limitada somente leitura',
               lambda: run_fault_autotest(39, run_readonly_inventory_autotest))
    ttk.Label(row17, text='Lê metadados de volumes locais; não é varredura completa.',
              wraplength=410).pack(anchor='w', padx=(8, 0))
    add_button(row18, '20. Autoteste #40: recuperação integral isolada',
               lambda: run_fault_autotest(40, run_isolated_full_restore_autotest))
    ttk.Label(row18, text='Seleção sintética, exclusões e restauração em pasta nova.',
              wraplength=410).pack(anchor='w', padx=(8, 0))
    add_button(row19, '21. Autoteste #41: inventário ampliado (metadados)',
               lambda: run_fault_autotest(41, run_inventory_permissions_autotest))
    ttk.Label(row19, text='Até 12.000 entradas/unidade; somente leitura e erros classificados.',
              wraplength=410).pack(anchor='w', padx=(8, 0))
    add_button(row20, '22. Autoteste #42: vínculos entre unidades (sintético)',
               lambda: run_fault_autotest(42, run_cross_volume_links_autotest))
    ttk.Label(row20, text='Distingue suspeitas e aprovações sem afirmar backup feito.',
              wraplength=410).pack(anchor='w', padx=(8, 0))
    add_button(row21, '23. Autoteste #43: falha e retomada de restauração',
               lambda: run_fault_autotest(43, run_restore_write_recovery_autotest))
    ttk.Label(row21, text='Dados fictícios; falha controlada e conferência SHA-256.',
              wraplength=410).pack(anchor='w', padx=(8, 0))
    add_button(row22, '24. Autoteste #44: páginas sem limite total',
               lambda: run_fault_autotest(44, run_paged_inventory_autotest))
    ttk.Label(row22, text='Somente dados sintéticos; não repete nem perde arquivos.',
              wraplength=440).pack(anchor='w', padx=(8, 0))
    add_button(row23, '25. Autoteste #45: pausar e continuar leitura',
               lambda: run_fault_autotest(45, run_pause_resume_inventory_autotest))
    ttk.Label(row23, text='Cursor em memória; retomada apenas na mesma sessão.',
              wraplength=440).pack(anchor='w', padx=(8, 0))
    add_button(row24, '26. Autoteste #46: acesso negado e junções',
               lambda: run_fault_autotest(46, run_gaps_inventory_autotest))
    ttk.Label(row24, text='Lacunas nunca equivalem a inventário completo.',
              wraplength=440).pack(anchor='w', padx=(8, 0))

    def run_paged_scan(new_session=False, until_finished=False):
        if state['busy']:
            return
        scanner = state.get('metadata_scanner')
        if new_session or scanner is None:
            try:
                roots = discover_local_roots()
                scanner = PagedMetadataScanner(roots)
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showerror('Inventário não iniciado', str(exc), parent=window)
                return
            previous = state.get('metadata_scanner')
            if previous is not None:
                previous.close()
            state['metadata_scanner'] = scanner
            write_log(f'[INVENTÁRIO] {len(roots)} unidades locais acessíveis; leitura somente de metadados.')
        if scanner.snapshot()['finished_current_session']:
            messagebox.showinfo('Análise concluída',
                                'Para iniciar outra análise escolha Nova sessão.', parent=window)
            return
        state['report'] = None
        def execute_page_or_complete():
            def progress(count):
                event_queue.put(('autotest_note',
                                 f'Inventário: {count} entradas examinadas; somente leitura.'))
            while True:
                outcome = scanner.step(page_size=2000, cancelled=cancelled,
                                       progress=progress)
                if not until_finished or outcome['finished_current_session']:
                    return outcome
        start_job('paged_scan', execute_page_or_complete)

    add_button(row25, 'Inventário real: NOVA sessão de leitura',
               lambda: run_paged_scan(new_session=True))
    add_button(row26, 'Inventário real: CONTINUAR próxima página',
               lambda: run_paged_scan(new_session=False))
    add_button(row27, 'Inventário real: CONTINUAR até terminar (cancelável)',
               lambda: run_paged_scan(new_session=False, until_finished=True))
    ttk.Label(row27, text=('Cada página examina 2.000 entradas. A análise longa roda fora '
                           'da interface e pode ser interrompida. Não lê conteúdo nem '
                           'certifica todos os saves ou arquivos protegidos.'),
              wraplength=475).pack(anchor='w', padx=(8, 0))
    add_button(row28, 'Inventário DETALHADO: pesquisar arquivos e marcar escolhas',
               lambda: show_file_index(window))
    ttk.Label(row28, text=('Cria um índice SQLite somente de metadados. '
                           'As escolhas não apagam nem copiam arquivos automaticamente.'),
              wraplength=475).pack(anchor='w', padx=(8, 0))
    export_button = ttk.Button(toolbar, text='Exportar relatório', command=export_report)
    export_button.pack(side='left', padx=(0, 8))
    commands.append(export_button)
    stop = ttk.Button(toolbar, text='Cancelar operação', command=cancelled.set, state='disabled')
    stop.pack(side='right')
    def close():
        if state['busy']:
            cancelled.set()
            messagebox.showinfo('Cancelamento solicitado',
                'Aguarde a operação parar antes de fechar. Dados parciais não são considerados verificados.', parent=window)
            return
        scanner = state.get('metadata_scanner')
        if scanner is not None:
            scanner.close()
        window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    write_log('Nenhuma exclusão ou formatação será realizada.')
    write_log('O backup grava em uma pasta nova. A recuperação também grava em outra pasta nova.')
    window.after(150, process_events)
    return window

