"""Read-only v0.6.7 audit dialog, with background disk metadata collection."""
from __future__ import annotations
import threading
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from backup_core import atomic_json
from completeness_audit_v067 import build_completeness_report


def show_completeness_audit(app, plan):
    window = tk.Toplevel(app)
    window.title('v0.6.7 • Auditoria de preservação do C: e situação EFI')
    window.geometry('1120x745')
    window.minsize(870, 590)
    window.transient(app)
    frame = ttk.Frame(window, padding=15)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Auditoria de dados do C: — somente leitura',
              font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(0, 5))
    ttk.Label(frame, text=('Verifica locais que podem conter dados importantes e consulta a relação entre '
                          'o disco do Windows e as partições EFI. NÃO lê todos os arquivos, '
                          'não altera escolhas e NÃO libera formatação.'),
              wraplength=1050, foreground='#F3BE67').pack(anchor='w', pady=(0, 8))
    status = tk.StringVar(value='Conferindo caminhos e consultando discos; aguarde...')
    ttk.Label(frame, textvariable=status, wraplength=1050).pack(anchor='w', pady=(0, 7))
    notebook = ttk.Notebook(frame)
    notebook.pack(fill='both', expand=True)

    paths_tab = ttk.Frame(notebook, padding=8)
    gaps_tab = ttk.Frame(notebook, padding=8)
    boot_tab = ttk.Frame(notebook, padding=8)
    recovery_tab = ttk.Frame(notebook, padding=8)
    tasks_tab = ttk.Frame(notebook, padding=8)
    for tab, label in ((paths_tab, 'Locais de dados'),
                       (gaps_tab, 'Erros do C:'),
                       (boot_tab, 'Discos e EFI'),
                       (recovery_tab, 'Mapa de recuperação'),
                       (tasks_tab, 'Checklist pendente')):
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
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        return tree

    paths_tree = make_table(paths_tab, [('status', 'Situação'), ('detail', 'Categoria / observação')])
    gaps_tree = make_table(gaps_tab, [('type', 'Categoria'), ('detail', 'Motivo')])
    efi_tree = make_table(boot_tab, [('type', 'Tipo'), ('detail', 'Detalhes')])
    recovery_tree = make_table(recovery_tab, [('status', 'Situação'), ('detail', 'Destino após reinstalação')])
    notes = tk.Text(tasks_tab, wrap='word', font=('Segoe UI', 10), relief='flat',
                    bg='#192438', fg='#EFF4FF', padx=14, pady=14)
    notes.pack(fill='both', expand=True)
    notes.insert('1.0', 'Carregando checklist...')
    notes.configure(state='disabled')

    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(9, 0))
    export_button = ttk.Button(controls, text='Exportar auditoria JSON', state='disabled')
    export_button.pack(side='left', padx=(0, 8))
    ttk.Button(controls, text='Ver escolhas em Meu Computador',
               command=lambda: (window.destroy(), app.navigate(app.home))).pack(side='left', padx=(0, 8))
    ttk.Button(controls, text='Fechar', command=window.destroy).pack(side='right')
    result = {'report': None}

    def draw(report):
        result['report'] = report
        counts = report['counts']
        status.set(f"{counts['locations_reviewed']} local(is) conferido(s) por metadados · "
                   f"{counts['locations_needing_review']} exigem revisão · "
                   f"{counts['c_scan_errors']} falhas + {counts['c_scan_skipped']} exclusões no C: · "
                   'FORMATAÇÃO NÃO AUTORIZADA')
        for t in (paths_tree, gaps_tree, efi_tree, recovery_tree):
            t.delete(*t.get_children())
        for p in report['candidate_locations']:
            paths_tree.insert('', 'end', text=f"{p['name']}  •  {p['path']}",
                              values=(p['status'], f"{p['category']} · {p['detail']}"))
        if not report['candidate_locations']:
            paths_tree.insert('', 'end', text='Perfil do usuário não identificado neste ambiente.',
                              values=('NÃO VERIFICADO', 'Conferir usuário atual e caminhos redirecionados'))
        for kind, rows in (('ERRO', report['scan_c']['errors']),
                           ('NÃO EXAMINADO', report['scan_c']['skipped'])):
            for row in rows[:2000]:
                gaps_tree.insert('', 'end', text=row['path'], values=(kind, row['reason']))
        if not report['scan_c']['errors'] and not report['scan_c']['skipped']:
            gaps_tree.insert('', 'end', text='Nenhuma falha registrada neste inventário.',
                             values=('A CONFERIR', 'Ausência de registros não certifica varredura completa'))
        boot = report['boot']
        efi_tree.insert('', 'end', text='Diagnóstico EFI',
                        values=(boot['status'], boot['note']))
        data = report['disk_evidence'].get('data', {})
        for disk in data.get('disks', ()):
            if not isinstance(disk, dict):
                continue
            efi_tree.insert('', 'end', text=f"Disco {disk.get('number', '?')} • {disk.get('friendly_name', '')}",
                            values=(str(disk.get('bus_type', '')), 'Números podem mudar após reinício; confira o modelo e serial.'))
        for efi in data.get('efi_partitions', ()):
            if isinstance(efi, dict):
                efi_tree.insert('', 'end', text=f"Partição EFI • disco {efi.get('disk_number', '?')}",
                                values=('EFI GPT', f"Partição {efi.get('partition_number', '?')} · {efi.get('size_bytes', '?')} bytes"))
        for error in data.get('errors', ()):
            efi_tree.insert('', 'end', text='Consulta Windows', values=('FALHA', error))
        for row in report.get('recovery_map', []):
            recovery_tree.insert('', 'end', text=row['source_path'],
                                 values=('PENDENTE — SEM PROVA DE BACKUP', row['restore_target_after_windows']))
        if not report.get('recovery_map'):
            recovery_tree.insert('', 'end', text='Nenhum caminho do C: selecionado.',
                                 values=('REVISAR', 'Escolha dados antes de planejar recuperação'))
        notes.configure(state='normal')
        notes.delete('1.0', 'end')
        notes.insert('1.0', ('AUDITORIA INFORMATIVA — NÃO AUTORIZA FORMATAR\n\n'
                             + '\n\n'.join(f'[ ] {n+1:02d}. {task}' for n, task in enumerate(report['manual_tasks']))
                             + '\n\nO backup anterior de 42 arquivos não comprova cobertura dos demais dados. '
                               'Locais selecionados exigem cópias verificadas; links, perfis de navegadores, '
                               'EFI e arquivos não examinados precisam de revisão manual.'))
        notes.configure(state='disabled')
        export_button.configure(state='normal')

    def save_report():
        if result['report'] is None:
            return
        filename = filedialog.asksaveasfilename(parent=window,
                        title='Salvar auditoria do C: (contém caminhos pessoais)',
                        initialfile='auditoria-preservacao-c-efi-v067.json',
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

    scan_report = getattr(app, 'deep_scan_report', {}) or {}
    saved_scans = getattr(app, 'scan_reports_by_drive', {}) or {}
    results_queue = Queue()
    def background():
        try:
            report = build_completeness_report(plan, scan_report, saved_scans)
            results_queue.put((report, None))
        except Exception as exc:
            results_queue.put((None, str(exc)))

    def poll():
        if not window.winfo_exists():
            return
        try:
            report, error = results_queue.get_nowait()
        except Empty:
            window.after(150, poll)
            return
        if error:
            status.set('Auditoria incompleta: ' + error)
            messagebox.showerror('Auditoria incompleta', error, parent=window)
        else:
            draw(report)

    threading.Thread(target=background, daemon=True, name='PCRO-v067-completeness').start()
    window.after(150, poll)
    return window
