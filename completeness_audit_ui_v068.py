"""v0.6.8: reviewed choices, imported history, verified evidence, read-only disk diagnosis."""
from __future__ import annotations
import threading
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from backup_core import atomic_json
from completeness_audit_v067 import build_completeness_report
from audit_v068 import (collect_disk_evidence_068, classify_boot_068,
    inspect_children_once, safe_review_choice, import_snapshot_068,
    inspect_verified_manifest, enhance_report_068)
from audit_v069 import (collect_disk_evidence_069 as collect_disk_evidence_068,
    classify_boot_069 as classify_boot_068, enhance_report_069 as enhance_report_068)
from index_audit_bridge import read_saved_index_choices
from index_choices_bridge import preview_import, apply_imported_choices
from scan_sessions import merge_cache
from backup_core import norm
from drive_catalog import safe_to_mark
from volume_paths import volume_of
import os
import ntpath


def show_completeness_audit(app, plan, *, history_manifest=None):
    window = tk.Toplevel(app)
    window.title('v0.6.9 • Auditoria inteligente e discos / EFI')
    window.geometry('1210x790')
    window.minsize(870, 590)
    window.transient(app)
    frame = ttk.Frame(window, padding=15)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Auditoria de dados do C: — revisão assistida',
              font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(0, 5))
    ttk.Label(frame, text=('Verifica locais que podem conter dados importantes e consulta a relação entre '
                          'o disco do Windows e as partições EFI. NÃO lê todos os arquivos, '
                          'escolhas só por confirmação explícita e NÃO libera formatação.'),
              wraplength=1050, foreground='#F3BE67').pack(anchor='w', pady=(0, 8))
    status = tk.StringVar(value='Conferindo caminhos e consultando discos; aguarde...')
    ttk.Label(frame, textvariable=status, wraplength=1050).pack(anchor='w', pady=(0, 7))
    readiness_status = tk.StringVar(value='Preservação: evidências ainda não avaliadas. Formatação bloqueada.')
    ttk.Label(frame, textvariable=readiness_status, wraplength=1050,
              foreground='#F3BE67').pack(anchor='w', pady=(0, 7))
    if history_manifest is not None:
        ttk.Label(frame, text='Backup escolhido no Histórico: ' + str(history_manifest)
                  + ' (ainda não verificado nesta sessão).',
                  wraplength=1050).pack(anchor='w', pady=(0, 6))
    notebook = ttk.Notebook(frame)
    notebook.pack(fill='both', expand=True)

    paths_tab = ttk.Frame(notebook, padding=8)
    review_tab = ttk.Frame(notebook, padding=8)
    gaps_tab = ttk.Frame(notebook, padding=8)
    boot_tab = ttk.Frame(notebook, padding=8)
    recovery_tab = ttk.Frame(notebook, padding=8)
    tasks_tab = ttk.Frame(notebook, padding=8)
    index_tab = ttk.Frame(notebook, padding=8)
    for tab, label in ((paths_tab, 'Locais de dados'),
                       (review_tab, 'Revisar pasta'),
                       (gaps_tab, 'Erros do C:'),
                       (boot_tab, 'Discos e EFI'),
                       (recovery_tab, 'Mapa de recuperação'),
                       (tasks_tab, 'Checklist pendente'),
                       (index_tab, 'Escolhas do índice SQLite')):
        notebook.add(tab, text=label)

    def make_table(parent, cols):
        area = ttk.Frame(parent)
        area.pack(fill='both', expand=True)
        tree = ttk.Treeview(area, columns=[k for k, _ in cols], show='tree headings')
        tree.heading('#0', text='Item / caminho')
        tree.column('#0', width=300, stretch=True)
        for key, label in cols:
            tree.heading(key, text=label)
            tree.column(key, width=220 if key == 'status' else 440, stretch=True)
        scroll = ttk.Scrollbar(area, orient='vertical', command=tree.yview)
        horizontal = ttk.Scrollbar(area, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        return tree

    paths_tree = make_table(paths_tab, [('status', 'Situação'), ('detail', 'Categoria / observação')])
    gaps_tree = make_table(gaps_tab, [('type', 'Categoria'), ('detail', 'Motivo')])
    review_tree = make_table(review_tab, [('type', 'Tipo'), ('size', 'Tamanho aproximado')])
    review_status = tk.StringVar(value='Selecione um local na aba Locais de dados e clique em Examinar selecionado.')
    ttk.Label(review_tab, textvariable=review_status, wraplength=1100).pack(anchor='w')
    review_controls = ttk.Frame(review_tab)
    review_controls.pack(fill='x', pady=(8,0))
    view_state = {'root': None, 'initial_root': None, 'offset': 0, 'more': False, 'paths': {}, 'busy': False, 'request_id': 0}
    proof_state = {'proof': None}
    index_state = {'parsed': None, 'filename': None, 'status': 'NÃO CONSULTADO'}
    chosen_paths = {}
    efi_tree = make_table(boot_tab, [('type', 'Tipo'), ('detail', 'Detalhes')])
    recovery_tree = make_table(recovery_tab, [('status', 'Situação'), ('detail', 'Destino após reinstalação')])
    notes = tk.Text(tasks_tab, wrap='word', font=('Segoe UI', 10), relief='flat',
                    bg='#192438', fg='#EFF4FF', padx=14, pady=14)
    notes.pack(fill='both', expand=True)
    notes.insert('1.0', 'Carregando checklist...')
    notes.configure(state='disabled')

    ttk.Label(index_tab, text=(
        'Reaproveite as escolhas de um inventário detalhado SQLite já criado. '
        'A consulta é somente leitura, não repete varreduras e não importa nada '
        'automaticamente. Índices são históricos e NÃO comprovam cópias ou recuperação.'),
        wraplength=1100).pack(anchor='w', pady=(0, 9))
    index_controls = ttk.Frame(index_tab)
    index_controls.pack(fill='x', pady=(0, 7))
    index_load_button = ttk.Button(index_controls, text='Abrir índice SQLite existente')
    index_load_button.pack(side='left', padx=(0, 9))
    index_apply_button = ttk.Button(index_controls, text='Aplicar escolhas ao plano (confirmar)',
                                    state='disabled')
    index_apply_button.pack(side='left', padx=(0, 9))
    index_status = tk.StringVar(value='Nenhum índice conectado; o plano atual permanece inalterado.')
    ttk.Label(index_tab, textvariable=index_status, wraplength=1100).pack(anchor='w', pady=(0, 6))
    index_tree = make_table(index_tab, [('decision', 'Escolha no índice'),
                                       ('current', 'Situação no plano atual')])

    path_actions = ttk.Frame(paths_tab)
    path_actions.pack(fill='x', pady=(8, 0))
    ttk.Label(paths_tab, text='Escolher Manter adiciona somente a pasta explicitamente marcada, NÃO copia arquivos.',
              foreground='#F3BE67', wraplength=1000).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(9, 0))
    import_button = ttk.Button(controls, text='Importar inventário do C: (histórico)')
    import_button.pack(side='left', padx=(0, 8))
    proof_button = ttk.Button(controls, text='Conferir manifest.json anterior')
    proof_button.pack(side='left', padx=(0, 8))
    history_proof_button = ttk.Button(
        controls, text='Conferir SHA-256 do backup no Histórico',
        state='normal' if history_manifest is not None else 'disabled')
    history_proof_button.pack(side='left', padx=(0, 8))
    export_button = ttk.Button(controls, text='Exportar auditoria JSON', state='disabled')
    export_button.pack(side='left', padx=(0, 8))
    ttk.Button(controls, text='Ver escolhas em Meu Computador',
               command=lambda: (window.destroy(), app.navigate(app.home))).pack(side='left', padx=(0, 8))
    ttk.Button(controls, text='Fechar', command=window.destroy).pack(side='right')
    result = {'report': None, 'base': None}

    def draw(report):
        report = enhance_report_068(report, proof=proof_state['proof'])
        report['review_decisions'] = [{'path': p, 'decision': c}
                                       for p, c in sorted(app.choices.items())
                                       if volume_of(p) == 'C:' and c in ('keep', 'skip')]
        if index_state['parsed'] is not None:
            snap = preview_import(app, index_state['parsed'])
            report['index_choices_evidence'] = {
                'source_file': index_state['filename'],
                'index_state': snap['source_state'],
                'reviewed_choice_count': snap['total'],
                'conflicts_with_current_plan': snap['conflicts'],
                'unchanged_in_current_plan': snap['unchanged'],
                'applied_to_current_plan': index_state['status'] == 'APLICADO AO PLANO',
                'source_is_backup': False,
                'read_only_preview': True,
                'note': ('Decisões históricas são intenções; não provam que os arquivos '
                         'ainda existam ou estejam protegidos.'),
            }
        result['report'] = report
        counts = report['counts']
        readiness = report['preservation_readiness']
        readiness_status.set(
            f"PRONTIDÃO: {readiness['state']} · "
            f"{readiness['selected_paths']} caminho(s) selecionado(s) no C: · "
            f"{readiness['paths_with_verified_manifest_files']} com algum arquivo SHA-256 verificado · "
            f"{readiness['paths_without_manifest_proof']} sem prova vinculada · "
            f"{readiness['scan_gaps_overlapping_choices']} lacuna(s) cruzando escolhas · "
            f"Boot/EFI: {readiness['boot_status']}. "
            "Cobertura integral e restauração pós-Windows NÃO comprovadas.")
        if index_state['parsed'] is not None:
            snap = preview_import(app, index_state['parsed'])
            readiness_status.set(
                readiness_status.get() +
                f" Índice histórico: {snap['total']} escolha(s), {snap['conflicts']} conflito(s); "
                "estas escolhas só entram no plano após confirmação.")
        status.set(f"{counts['locations_reviewed']} local(is) conferido(s) por metadados · "
                   f"{counts['locations_needing_review']} exigem revisão · "
                   f"Inventário C: {report['scan_c']['status']} · {counts['c_scan_errors']} falhas + {counts['c_scan_skipped']} itens ignorados (não apagados) · "
                   'FORMATAÇÃO NÃO AUTORIZADA')
        for t in (paths_tree, gaps_tree, efi_tree, recovery_tree):
            t.delete(*t.get_children())
        chosen_paths.clear()
        for idx, p in enumerate(report['candidate_locations']):
            iid = f'loc-{idx}'
            chosen_paths[iid] = p
            decision = app.choices.get(norm(p['path']))
            shown = 'NÃO PRESERVAR (NÃO APAGA)' if decision == 'skip' else p['status']
            paths_tree.insert('', 'end', iid=iid,
                              text=f"{p['name']}  •  {p['path']}",
                              values=(shown, f"{p['category']} · {p['detail']}"))
        if not report['candidate_locations']:
            paths_tree.insert('', 'end', text='Perfil do usuário não identificado neste ambiente.',
                              values=('NÃO VERIFICADO', 'Conferir usuário atual e caminhos redirecionados'))
        for kind, rows in (('ERRO', report['scan_c']['errors']),
                           ('NÃO EXAMINADO', report['scan_c']['skipped'])):
            for row in rows[:2000]:
                gaps_tree.insert('', 'end', text=row['path'], values=(kind, row['reason']))
        if not report['scan_c']['errors'] and not report['scan_c']['skipped']:
            gaps_tree.insert('', 'end', text='Sem erros carregados — confira se há inventário do C:.',
                             values=('A CONFERIR', 'Ausência de registros não certifica varredura completa'))
        boot = report['boot']
        efi_tree.insert('', 'end', text='Diagnóstico EFI',
                        values=(boot['status'], boot['note']))
        data = report['disk_evidence'].get('data', {})
        for pd in data.get('physical_disks', ()):
            if isinstance(pd, dict):
                efi_tree.insert('', 'end', text=f"Disco físico CIM {pd.get('index', '?')} • {pd.get('model', '')}",
                                values=('DISPOSITIVO FÍSICO', f"Barramento {pd.get('interface_type', '?')} · conferir serial no Windows"))
        for disk in data.get('disks', ()):
            if not isinstance(disk, dict):
                continue
            efi_tree.insert('', 'end', text=f"Disco {disk.get('number', '?')} • {disk.get('friendly_name', '')}",
                            values=(str(disk.get('bus_type', '')), 'Números podem mudar após reinício; confira o modelo e serial.'))
        for efi in data.get('efi_partitions', ()):
            if isinstance(efi, dict):
                efi_tree.insert('', 'end', text=f"Partição EFI • disco {efi.get('disk_number', '?')}",
                                values=('EFI GPT', f"Partição {efi.get('partition_number', '?')} · {efi.get('size_bytes', '?')} bytes"))
        for vol in data.get('legacy_volumes', ()):
            if isinstance(vol, dict) and (vol.get('letter') or vol.get('system_volume')):
                numbers = vol.get('disk_numbers', [])
                association = 'Disco(s): ' + ', '.join(map(str, numbers)) if numbers else 'DISCO NÃO CONFIRMADO'
                efi_tree.insert('', 'end', text=f"Volume {vol.get('letter', '') or 'SEM LETRA'} • {vol.get('label') or ''}",
                                values=('VOLUME MAPEADO' if numbers else 'REVISAR',
                                        f"FS {vol.get('filesystem', '?')} · Sistema {vol.get('system_volume', '?')} · {association}"))
                if vol.get('mapping_error'):
                    efi_tree.insert('', 'end', text='Detalhe da associação', values=('NÃO MAPEADO', vol['mapping_error']))
        for warning in data.get('warnings', ()):
            efi_tree.insert('', 'end', text='Mapeamento parcial', values=('REVISAR', warning))
        for error in data.get('errors', ()):
            efi_tree.insert('', 'end', text='Consulta Windows', values=('FALHA', error))
        evidence = report.get('backup_evidence', {})
        recovery_tree.insert('', 'end', text='Prova de backup anterior',
                             values=(evidence.get('status', 'NÃO CONFERIDO'),
                                     f"{evidence.get('files_verified', 0)} arquivos do manifesto. Cobertura completa NÃO comprovada."))
        for row in report.get('recovery_map', []):
            count = row.get('verified_manifest_files', 0)
            detail = (row['restore_target_after_windows']
                      + f' · {count} arquivo(s) do manifesto verificado(s) neste caminho.'
                      + ' Cobertura integral e restauração NÃO comprovadas.')
            recovery_tree.insert('', 'end', text=row['source_path'],
                                 values=(row['status'], detail))
        if not report.get('recovery_map'):
            recovery_tree.insert('', 'end', text='Nenhum caminho do C: selecionado.',
                                 values=('REVISAR', 'Escolha dados antes de planejar recuperação'))
        notes.configure(state='normal')
        notes.delete('1.0', 'end')
        notes.insert('1.0', ('AUDITORIA INFORMATIVA — NÃO AUTORIZA FORMATAR\n\n'
                             + '\n\n'.join(f'[ ] {n+1:02d}. {task}' for n, task in enumerate(report['manual_tasks']))
                             + '\n\nUm manifesto verificado comprova somente os arquivos nele listados. '
                               'Locais selecionados exigem cópias verificadas; links, perfis de navegadores, '
                               'EFI e arquivos não examinados precisam de revisão manual.'))
        notes.configure(state='disabled')
        export_button.configure(state='normal')

    def save_report():
        if result['report'] is None:
            return
        filename = filedialog.asksaveasfilename(parent=window,
                        title='Salvar auditoria do C: (contém caminhos pessoais)',
                        initialfile='auditoria-inteligente-c-efi-v069.json',
                        defaultextension='.json', filetypes=[('JSON', '*.json')])
        if not filename:
            return
        try:
            atomic_json(Path(filename), result['report'])
            messagebox.showinfo('Relatório salvo',
                                'Relatório exportado. Nenhum dado foi copiado; formatação continua bloqueada.',
                                parent=window)
        except OSError as exc:
            messagebox.showerror('Erro ao salvar', str(exc), parent=window)
    export_button.configure(command=save_report)

    results_queue = Queue()
    def background():
        try:
            evidence = collect_disk_evidence_068()
            report = build_completeness_report(
                {'requires_verified_backup': [p for p, choice in app.choices.items()
                                               if choice == 'keep' and volume_of(p) == 'C:']},
                getattr(app, 'deep_scan_report', {}) or {},
                getattr(app, 'scan_reports_by_drive', {}) or {},
                disk_evidence=evidence)
            report['boot'] = classify_boot_068(evidence)
            results_queue.put(('audit', report, None))
        except Exception as exc:
            results_queue.put(('audit', None, str(exc)))

    def poll():
        if not window.winfo_exists():
            return
        try:
            kind, report, error = results_queue.get_nowait()
        except Empty:
            window.after(150, poll)
            return
        # An asynchronous response may arrive after the user switched folders or
        # cancelled a review. Ignore it instead of overwriting the current view.
        if kind == 'review' and report['request_id'] != view_state['request_id']:
            window.after(150, poll)
            return
        if kind == 'index':
            index_load_button.configure(state='normal')
        if kind == 'proof':
            proof_button.configure(state='normal')
            history_proof_button.configure(
                state='normal' if history_manifest is not None else 'disabled')
        if error:
            if kind == 'index':
                index_status.set('Não foi possível ler o índice: ' + error)
            if kind == 'review':
                review_status.set('Não foi possível consultar a pasta: ' + error)
            else:
                status.set('Operação incompleta: ' + error)
            messagebox.showerror('Operação incompleta', error, parent=window)
        elif kind == 'audit':
            result['base'] = report
            draw(report)
        elif kind == 'index':
            filename, parsed = report
            index_state.update(parsed=parsed, filename=filename, status='SOMENTE PRÉVIA')
            render_index_preview()
            index_apply_button.configure(state='normal' if parsed['choices'] else 'disabled')
            if result['base']:
                draw(result['base'])
            notebook.select(index_tab)
        elif kind == 'import':
            merged, added = report
            if not added:
                messagebox.showinfo('Inventário já carregado',
                    'As unidades desse arquivo já constam no inventário. Nada foi substituído.', parent=window)
            else:
                app.scan_reports_by_drive = merged
                app.deep_scan_report = merge_cache(merged)
                messagebox.showinfo('Histórico importado',
                    'Inventários antigos (não reexaminados): ' + ', '.join(sorted(added)) +
                    '. Escolhas existentes preservadas.', parent=window)
                launch_audit()
        elif kind == 'proof':
            proof_state['proof'] = report
            if result['base']:
                draw(result['base'])
            messagebox.showinfo('Manifesto verificado',
                f"SHA-256 aprovado para {report['files_verified']} arquivo(s). "
                'Cobertura de todos os dados do C: NÃO comprovada.', parent=window)
        elif kind == 'review':
            # Report is tagged with the request whose directory was read.
            payload = report['data']
            root_for_page = report['root']
            review_tree.delete(*review_tree.get_children())
            view_state['paths'].clear()
            for i, row in enumerate(payload['rows']):
                iid = f'child-{i}'
                view_state['paths'][iid] = row
                review_tree.insert('', 'end', iid=iid, text=row['name'],
                                   values=(row['type'], str(row['bytes']) if row.get('bytes') is not None else '—'))
            view_state['more'] = payload['has_more']
            view_state['offset'] = payload['next_offset'] if payload['has_more'] else 0
            suffix = 'Há mais páginas' if payload['has_more'] else 'Última página'
            review_status.set(f"Pasta: {root_for_page} · {len(payload['rows'])} item(ns) · {suffix}")
        # CRITICAL: keep polling after *every* completed result, not only when
        # the queue was empty. The old code stopped after the initial audit,
        # leaving later folder previews visibly stuck forever.
        if window.winfo_exists():
            window.after(150, poll)

    def launch_audit():
        status.set('Atualizando auditoria e consultando discos (somente leitura)...')
        threading.Thread(target=background, daemon=True, name='PCRO-v068-audit').start()

    def selected_candidate():
        ids = paths_tree.selection()
        return chosen_paths.get(ids[0]) if ids else None

    def inspect_candidate():
        item = selected_candidate()
        if not item:
            return messagebox.showinfo('Selecione um local', 'Selecione primeiro uma pasta na tabela.', parent=window)
        view_state['root'] = item['path']
        view_state['initial_root'] = item['path']
        view_state['offset'] = 0
        notebook.select(review_tab)
        load_review_page(0)

    def load_review_page(offset):
        root = view_state.get('root')
        if not root:
            return
        view_state['request_id'] += 1
        request_id = view_state['request_id']
        view_state['more'] = False
        review_status.set(f'Consultando entradas imediatas de {root}...')
        def work():
            try:
                data = inspect_children_once(root, offset=offset)
                results_queue.put(('review', {'request_id': request_id, 'root': root, 'data': data}, None))
            except (OSError, ValueError) as exc:
                results_queue.put(('review', {'request_id': request_id, 'root': root, 'data': None}, str(exc)))
        threading.Thread(target=work, daemon=True, name='PCRO-v068-preview').start()
        def warn_slow():
            if window.winfo_exists() and request_id == view_state['request_id'] \
                    and 'Consultando entradas' in review_status.get():
                review_status.set('A consulta está demorando mais que o esperado. '
                                  'Você pode cancelar a visualização e tentar uma subpasta menor. '
                                  'Nenhum arquivo foi modificado.')
        window.after(15000, warn_slow)

    def cancel_review():
        # Abandons the request in the UI. An OS directory call already in flight
        # cannot be forcibly interrupted, but its response will be discarded.
        view_state['request_id'] += 1
        view_state['more'] = False
        review_status.set('Visualização cancelada. Nenhum arquivo foi alterado.')

    def selected_child():
        rows = review_tree.selection()
        return view_state['paths'].get(rows[0]) if rows else None

    def open_child():
        item = selected_child()
        if not item or item.get('type') != 'PASTA':
            return messagebox.showinfo('Selecione uma pasta',
                'Somente pastas comuns podem ser abertas. Links/junções não são seguidos.', parent=window)
        from completeness_audit_v067 import _within
        if not _within(item['path'], view_state['initial_root']):
            return messagebox.showerror('Caminho bloqueado', 'Subpasta fora do local auditado.', parent=window)
        view_state['root'] = item['path']
        view_state['offset'] = 0
        load_review_page(0)

    def back_child():
        root = view_state['root']
        top = view_state['initial_root']
        if not top or not root or ntpath.normcase(ntpath.normpath(root)) == ntpath.normcase(ntpath.normpath(top)):
            return
        parent = ntpath.dirname(ntpath.normpath(root))
        from completeness_audit_v067 import _within
        if _within(parent, top):
            view_state['root'] = parent
            load_review_page(0)

    def mark_path(chosen, *, choice='keep'):
        if not chosen:
            return
        try:
            from drive_catalog import safe_to_mark
            if not safe_to_mark(chosen) or volume_of(chosen) != 'C:':
                raise ValueError('Seleção insegura ou fora do C:.')
            from selective_recovery import _any_reparse_ancestor
            _any_reparse_ancestor(chosen)
            if not os.path.exists(chosen):
                raise ValueError('Pasta/arquivo não existe mais.')
            label = 'manter e copiar posteriormente' if choice == 'keep' else 'não incluir no plano de backup'
            if not messagebox.askyesno('Escolha explícita',
                f'Marcar apenas este caminho para {label}?\n\n{chosen}\n\n'
                'Essa decisão NÃO apaga nem copia arquivos. Confirme após revisar o conteúdo.', parent=window):
                return
            key = norm(chosen)
            app.choices[key] = choice
            app.personal_paths.add(key)
            app._on_change()
            launch_audit()
        except (ValueError, OSError) as exc:
            messagebox.showerror('Não selecionado', str(exc), parent=window)

    def mark_candidate():
        item = selected_candidate()
        if not item:
            return
        if item['category'] in ('CONFIGURAÇÕES', 'APLICATIVOS', 'NAVEGADORES'):
            if not messagebox.askyesno('Pasta ampla: revisar primeiro',
                'Essa pasta pode conter caches, arquivos enormes e dados temporários. '
                'É preferível escolher uma subpasta pelo botão Examinar selecionado.\n\n'
                'Deseja mesmo marcar a pasta inteira?', parent=window):
                return
        mark_path(item['path'])

    def mark_child(*, choice='keep'):
        item = selected_child()
        if item and item.get('type') not in ('LINK — NÃO SEGUIR', 'SEM ACESSO'):
            root = view_state['root']
            from completeness_audit_v067 import _within
            if _within(item['path'], root) and item['path'] != root:
                mark_path(item['path'], choice=choice)
        else:
            messagebox.showinfo('Escolha um item', 'Selecione uma pasta ou arquivo válido.', parent=window)

    def import_old():
        filename = filedialog.askopenfilename(parent=window, title='Selecione o relatório de detecção de uma versão anterior (JSON)',
                                              filetypes=[('JSON de inventário', '*.json')])
        if not filename:
            return
        prior = dict(getattr(app, 'scan_reports_by_drive', {}) or {})
        status.set('Importando inventário em segundo plano; escolhas existentes serão mantidas...')
        def work():
            try:
                results_queue.put(('import', import_snapshot_068(filename, prior), None))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                results_queue.put(('import', None, str(exc)))
        threading.Thread(target=work, daemon=True, name='PCRO-v068-import').start()

    def render_index_preview():
        parsed = index_state['parsed']
        if parsed is None:
            return
        preview = preview_import(app, parsed)
        current = {ntpath.normcase(ntpath.normpath(p)): choice
                   for p, choice in app.choices.items()}
        choices = parsed['choices']
        c_keep = sum(volume_of(p) == 'C:' and v == 'keep' for p, v in choices.items())
        c_skip = sum(volume_of(p) == 'C:' and v == 'skip' for p, v in choices.items())
        index_status.set(
            f"Índice: {index_state['filename']} · estado: {preview['source_state']} · "
            f"{preview['total']} escolha(s): {preview['keep']} preservar, "
            f"{preview['skip']} não copiar · {preview['conflicts']} conflito(s) "
            f"com o plano atual · C: {c_keep} preservar, {c_skip} não copiar · "
            f"estado: {index_state['status']}. "
            "Nenhum arquivo foi copiado; a origem não foi examinada novamente.")
        index_tree.delete(*index_tree.get_children())
        # A bounded preview keeps Tk responsive; every choice is still applied
        # through the existing validated importer upon explicit confirmation.
        entries = sorted(choices.items(), key=lambda x: (volume_of(x[0]) != 'C:', x[0]))
        for p, decision in entries[:200]:
            old = current.get(ntpath.normcase(ntpath.normpath(p)))
            conflict = 'CONFLITO — escolha diferente' if old and old != decision else (
                'JÁ IGUAL' if old == decision else 'NÃO IMPORTADO')
            index_tree.insert('', 'end', text=p,
                              values=('PRESERVAR' if decision == 'keep' else 'NÃO COPIAR (não apaga)',
                                      conflict))
        if len(entries) > 200:
            index_tree.insert('', 'end', text=f"... {len(entries) - 200} escolhas adicionais",
                              values=('PRÉVIA LIMITADA', 'Serão consideradas na confirmação'))

    def load_saved_index():
        filename = filedialog.askopenfilename(
            parent=window, title='Escolher índice SQLite PCRO existente (somente leitura)',
            filetypes=[('Índice SQLite', '*.sqlite3'), ('Todos os arquivos', '*.*')])
        if not filename:
            return
        index_load_button.configure(state='disabled')
        index_apply_button.configure(state='disabled')
        index_state.update(parsed=None, filename=None, status='AGUARDANDO LEITURA')
        index_status.set('Lendo somente escolhas registradas; não varre discos...')
        def work():
            try:
                parsed = read_saved_index_choices(filename)
                results_queue.put(('index', (filename, parsed), None))
            except (OSError, ValueError, TypeError) as exc:
                results_queue.put(('index', None, str(exc)))
        threading.Thread(target=work, daemon=True, name='PCRO-read-index-choices').start()

    def apply_index_to_current_plan():
        parsed = index_state['parsed']
        if not parsed:
            return
        summary = preview_import(app, parsed)
        if not messagebox.askyesno(
                'Confirmar importação das escolhas históricas',
                f"Preservar: {summary['keep']} · Não copiar: {summary['skip']}\\n"
                f"Conflitos com o plano atual: {summary['conflicts']}\\n"
                f"Estado histórico: {summary['source_state']}\\n\\n"
                "As escolhas do SQLite terão prioridade nos conflitos. "
                "Não copiar nunca significa apagar. Arquivos antigos podem ter mudado "
                "e o backup precisará de nova prévia antes de qualquer cópia. "
                "Importar NÃO verifica backup, restauração ou EFI.\\n\\n"
                "Aplicar essas escolhas ao plano de preservação?",
                parent=window):
            return
        try:
            outcome = apply_imported_choices(app, parsed)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            messagebox.showerror('Não foi possível aplicar escolhas', str(exc), parent=window)
            return
        index_state['status'] = 'APLICADO AO PLANO'
        index_apply_button.configure(state='disabled')
        render_index_preview()
        launch_audit()
        messagebox.showinfo(
            'Escolhas importadas',
            f"{outcome['applied']} escolha(s) recebida(s) no plano. "
            "Nada foi copiado ou apagado. Revise a preservação antes de iniciar backup.",
            parent=window)

    index_load_button.configure(command=load_saved_index)
    index_apply_button.configure(command=apply_index_to_current_plan)

    def verify_manifest_path(filename):
        # This is an explicit request by the user, never executed on opening
        # the audit or on selecting an entry in Histórico.
        proof_button.configure(state='disabled')
        history_proof_button.configure(state='disabled')
        proof_state['proof'] = None
        if result['base']:
            draw(result['base'])
        status.set('Verificando SHA-256 dos arquivos do manifesto. Isso pode demorar; nenhuma cópia será criada.')
        def work():
            try:
                results_queue.put(('proof', inspect_verified_manifest(filename), None))
            except Exception as exc:
                results_queue.put(('proof', None, str(exc)))
        threading.Thread(target=work, daemon=True, name='PCRO-v069-proof').start()

    def verify_old():
        filename = filedialog.askopenfilename(parent=window, title='Selecione manifest.json do backup real',
                                              filetypes=[('JSON do manifesto', '*.json')])
        if filename:
            verify_manifest_path(filename)

    def verify_history():
        if history_manifest is not None:
            verify_manifest_path(history_manifest)

    import_button.configure(command=import_old)
    proof_button.configure(command=verify_old)
    history_proof_button.configure(command=verify_history)
    ttk.Button(path_actions, text='Examinar selecionado (sem copiar)', command=inspect_candidate).pack(side='left', padx=(0,6))
    ttk.Button(path_actions, text='Marcar esta pasta para manter', command=mark_candidate).pack(side='left', padx=6)
    ttk.Button(path_actions, text='Não preservar esta pasta (não exclui)',
               command=lambda: mark_path(selected_candidate()['path'], choice='skip') if selected_candidate() else None).pack(side='left', padx=6)
    ttk.Button(review_controls, text='Abrir subpasta', command=open_child).pack(side='left', padx=4)
    ttk.Button(review_controls, text='Voltar à pasta anterior', command=back_child).pack(side='left', padx=4)
    ttk.Button(review_controls, text='Próxima página', command=lambda: load_review_page(view_state['offset']) if view_state['more'] else None).pack(side='left', padx=4)
    ttk.Button(review_controls, text='Cancelar consulta', command=cancel_review).pack(side='left', padx=4)
    ttk.Button(review_controls, text='Manter item selecionado', command=mark_child).pack(side='left', padx=4)
    ttk.Button(review_controls, text='Não preservar (não exclui)',
               command=lambda: mark_child(choice='skip')).pack(side='left', padx=4)
    launch_audit()
    window.after(150, poll)
    return window
