"""Opt-in, read-only disk safety dialog attached to the Diagnostics page.

The dialog never starts a hardware query on opening. It accepts explicit drive
letters chosen by the operator and uses only a privacy-minimal report. It does
NOT back up files, format disks, install Windows or approve copying.
"""
from __future__ import annotations

from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from drive_safety_report import _normalize_letters, inspect_fresh_drive_safety
from drive_safety_export import safe_drive_report_json
from runtime_volumes import discover_drive_letters
from ui_timers import WindowTimers

HARDWARE_LABELS = {
    'not_applicable': 'não se aplica',
    'not_confirmed': 'não confirmado',
    'ambiguous': 'associação ambígua',
    'incomplete': 'evidência incompleta',
    'members_reported_unverified': 'membros relatados (não verificados fisicamente)',
    'reported': 'reportado pela fonte',
    'not_reported': 'não reportado pela fonte',
}

CROSSCHECK_LABELS = {
    'unavailable': 'Sem dados suficientes do Get-Partition',
    'inconclusive': 'Partições com registros inválidos',
    'extent_only': 'Somente IOCTL retornou associação',
    'partition_only': 'Somente Get-Partition retornou associação',
    'conflict': 'CONFLITO entre Get-Partition e IOCTL',
    'limited_match': 'Associação lógica coincidente, com ressalvas',
    'logical_match': 'Associação lógica coincidente (não física)',
}

EXTENT_LABELS = {
    'incomplete': 'Mapeamento inconclusivo',
    'observed_logical_only': 'Disco lógico observado',
    'disk_not_listed': 'Disco ausente no Get-Disk',
    'virtual_spaces': 'Storage Spaces / virtual',
    'multi_disk': 'Vários discos lógicos',
}


def show_drive_safety_dialog(parent, *, available_letters=None):
    """Show a read-only diagnostic UI; no collection until explicit click."""
    # Tk widgets may expose a callable `busy` method. Only the App's
    # explicit boolean busy=True means an operation is actually running.
    if getattr(parent, 'busy', False) is True:
        messagebox.showinfo('Diagnóstico em andamento',
                            'Aguarde a análise anterior terminar.', parent=parent)
        return None
    available = (discover_drive_letters() if available_letters is None
                 else available_letters)
    if not isinstance(available, (list, tuple)):
        available = ()
    known = sorted(set(x.upper() for x in available
                       if isinstance(x, str) and len(x) == 1
                       and 'A' <= x.upper() <= 'Z'))

    dialog = tk.Toplevel(parent)
    dialog.title('Conferir discos e destinos — SOMENTE LEITURA')
    dialog.geometry('975x680')
    dialog.minsize(720, 480)
    timers = WindowTimers(dialog)
    queue = Queue()
    state = {'busy': False, 'close_requested': False, 'result': None}

    outer = ttk.Frame(dialog, padding=16)
    outer.pack(fill='both', expand=True)
    ttk.Label(
        outer, text='Conferência de discos lógicos e destinos',
        font=('Segoe UI', 13, 'bold'),
    ).pack(anchor='w')
    ttk.Label(
        outer,
        text=('Digite as letras das unidades escolhidas, separadas por vírgula. '
              'Nenhuma unidade é presumida como segura. A verificação não '
              'faz backups, exclusões, ajustes EFI ou formatação.'),
        wraplength=900,
    ).pack(anchor='w', pady=(6, 8))
    ttk.Label(
        outer, text='Unidades detectadas com letra: ' +
        (', '.join(x + ':' for x in known) if known else
         'nenhuma identificada; confira as unidades manualmente.'),
        wraplength=900,
    ).pack(anchor='w', pady=(0, 9))

    fields = ttk.Frame(outer)
    fields.pack(fill='x')
    ttk.Label(fields, text='Origens a preservar:').grid(
        row=0, column=0, sticky='w', pady=4)
    ttk.Label(fields, text='Destinos candidatos:').grid(
        row=1, column=0, sticky='w', pady=4)
    source = tk.StringVar(master=dialog)
    target = tk.StringVar(master=dialog)
    source_input = ttk.Entry(fields, textvariable=source)
    target_input = ttk.Entry(fields, textvariable=target)
    source_input.grid(row=0, column=1, sticky='ew', padx=(10, 0), pady=4)
    target_input.grid(row=1, column=1, sticky='ew', padx=(10, 0), pady=4)
    fields.columnconfigure(1, weight=1)
    ttk.Label(
        outer,
        text=('Exemplo de formato: C:,D:  |  G:. '
              'São exemplos, não escolhas automáticas. '
              'O diagnóstico identifica conflitos, mas não prova '
              'independência física entre dispositivos.'),
        wraplength=900,
    ).pack(anchor='w', pady=(9, 7))

    status = tk.StringVar(master=dialog, value='Aguardando solicitação. Nenhum disco analisado.')
    ttk.Label(outer, textvariable=status, wraplength=900).pack(
        anchor='w', pady=(2, 8))
    items = ttk.Treeview(
        outer, columns=('kind', 'state', 'disks'), show='tree headings',
        height=8,
    )
    items.heading('#0', text='Unidade')
    items.heading('kind', text='Tipo')
    items.heading('state', text='Diagnóstico')
    items.heading('disks', text='Discos lógicos relatados')
    items.column('#0', width=120, stretch=False)
    items.column('kind', width=140, stretch=False)
    items.column('state', width=200)
    items.column('disks', width=300)
    items.pack(fill='both', expand=True, pady=(0, 10))

    details = tk.Text(outer, wrap='word', height=9,
                      bg='#192438', fg='#EFF4FF', insertbackground='#EFF4FF',
                      relief='flat', highlightthickness=1,
                      highlightbackground='#2B3952')
    details.pack(fill='both', expand=True)
    details.insert('1.0', 'Nenhuma unidade foi aprovada para backup ou formatação.')
    details.configure(state='disabled')
    controls = ttk.Frame(outer)
    controls.pack(fill='x', pady=(12, 0))

    def show_details(text):
        details.configure(state='normal')
        details.delete('1.0', 'end')
        details.insert('1.0', text)
        details.configure(state='disabled')

    def display(report):
        for key in items.get_children(''):
            items.delete(key)
        notes = []
        for item in report['source_volumes']:
            notes.append(item['letter'] + ' — ' + CROSSCHECK_LABELS.get(
                item.get('partition_crosscheck'), 'Conferência não disponível'))
            hw = item.get('hardware_evidence') or {}
            if item['extent_status'] == 'disk_not_listed':
                notes.append('  Win32_DiskDrive: ' + HARDWARE_LABELS.get(
                    hw.get('wmi_diskdrive_status'), 'não confirmado'))
                notes.append('  Win32_DiskPartition: ' + HARDWARE_LABELS.get(
                    hw.get('wmi_partition_status'), 'não confirmado'))
                if type(hw.get('wmi_partition_count')) is int:
                    notes.append('  Partições WMI relatadas: ' +
                                 str(hw['wmi_partition_count']))
            items.insert(
                '', 'end', text=item['letter'],
                values=('Origem', EXTENT_LABELS.get(item['extent_status'], 'Inconclusivo'),
                        ', '.join(str(x) for x in item['logical_disk_numbers'])
                        or 'Não identificado'))
        for item in report['destinations']:
            items.insert(
                '', 'end', text=item['letter'],
                values=('Destino', item['status'],
                        ', '.join(str(x) for x in item['logical_disk_numbers'])
                        or 'Não identificado'))
            notes.append(item['letter'] + ' — ' + item['status'] +
                         ' | ' + EXTENT_LABELS.get(item['extent_status'], 'Inconclusivo'))
            notes.append('  Partições/IOCTL: ' + CROSSCHECK_LABELS.get(
                item.get('partition_crosscheck'), 'Conferência não disponível'))
            hw = item.get('hardware_evidence') or {}
            if item['extent_status'] == 'virtual_spaces':
                notes.append('  Storage Spaces: ' + HARDWARE_LABELS.get(
                    hw.get('spaces_membership_status'), 'não confirmado'))
                if type(hw.get('spaces_members_count')) is int:
                    notes.append('  Membros relatados (não independência física): ' +
                                 str(hw['spaces_members_count']))
                notes.append('  Resiliência informada: ' +
                             str(hw.get('spaces_resiliency') or 'unknown'))
            elif item['extent_status'] == 'disk_not_listed':
                notes.append('  Win32_DiskDrive: ' + HARDWARE_LABELS.get(
                    hw.get('wmi_diskdrive_status'), 'não confirmado'))
                notes.append('  Win32_DiskPartition: ' + HARDWARE_LABELS.get(
                    hw.get('wmi_partition_status'), 'não confirmado'))
            notes.extend('  BLOQUEIO: ' + msg for msg in item['blockers'])
            notes.extend('  REVISÃO: ' + msg for msg in item['issues'])
        notes.extend([
            '',
            'NUNCA aprovado automaticamente:',
            '  Independência física: NÃO VERIFICADA',
            '  Backup e cópia: NÃO AUTORIZADOS',
            '  Formatação ou instalação do Windows: NÃO AUTORIZADAS',
        ])
        show_details('\n'.join(notes))
        status.set(
            'DIAGNÓSTICO CONCLUÍDO — ' + report['status'].upper() +
            '. Esta análise não autoriza qualquer operação em disco.')

    def enable(enabled):
        state['busy'] = not enabled
        verify_btn.configure(state='normal' if enabled else 'disabled')
        source_input.configure(state='normal' if enabled else 'disabled')
        target_input.configure(state='normal' if enabled else 'disabled')
        copy_btn.configure(state='normal' if enabled and state['result'] is not None
                           else 'disabled')

    def verify():
        if state['busy']:
            return
        # Validate the selection before initiating ANY hardware access.
        try:
            src = _normalize_letters(
                [p.strip() for p in source.get().split(',')],
                maximum=32, field='Origens')
            dst = _normalize_letters(
                [p.strip() for p in target.get().split(',')],
                maximum=8, field='Destinos')
            if set(src) & set(dst):
                raise ValueError('Destino coincide com uma unidade de origem.')
        except ValueError:
            state['result'] = None
            copy_btn.configure(state='disabled')
            for row in items.get_children(''):
                items.delete(row)
            show_details('Seleção inválida. Informe unidades diferentes e revise as letras.')
            status.set('Entrada recusada; inventário não consultado.')
            return

        state['result'] = None
        for row in items.get_children(''):
            items.delete(row)
        show_details('Consultando discos, sem modificar arquivos ou partições…')
        enable(False)
        status.set('Coletando novo inventário de discos, somente leitura…')
        def worker():
            try:
                report = inspect_fresh_drive_safety(src, dst)
                queue.put(('ok', report))
            except Exception:
                # Never expose PowerShell or device details in the UI on error.
                queue.put(('error', None))
        threading.Thread(target=worker, daemon=True).start()

    def close():
        if state['busy']:
            state['close_requested'] = True
            status.set('Aguardando a consulta terminar para fechar com segurança…')
        else:
            dialog.destroy()

    def copy_safe_summary():
        if state['busy'] or state['result'] is None:
            return
        try:
            serialized = safe_drive_report_json(state['result'])
            # Clipboard is changed only after an EXPLICIT user click.
            dialog.clipboard_clear()
            dialog.clipboard_append(serialized)
        except (ValueError, TypeError, tk.TclError):
            status.set('Não foi possível copiar um resumo seguro.')
            return
        status.set(
            'Resumo filtrado copiado para a área de transferência. '
            'Revise antes de compartilhar; nenhuma ação em disco autorizada.')

    verify_btn = ttk.Button(
        controls, text='Conferir discos (SOMENTE LEITURA)', command=verify)
    verify_btn.pack(side='left')
    copy_btn = ttk.Button(
        controls, text='Copiar resumo seguro', command=copy_safe_summary,
        state='disabled')
    copy_btn.pack(side='left', padx=(10, 0))
    ttk.Button(controls, text='Fechar', command=close).pack(side='right')

    def invalidate_on_edit(*_):
        # Editing even one letter invalidates any previous snapshot before
        # the user can copy a report for the wrong selected drives.
        if state['result'] is None:
            return
        state['result'] = None
        copy_btn.configure(state='disabled')
        for row in items.get_children(''):
            items.delete(row)
        show_details('Seleção alterada. Faça nova conferência somente leitura.')
        status.set('Seleção modificada; diagnóstico anterior não é mais válido.')

    source.trace_add('write', invalidate_on_edit)
    target.trace_add('write', invalidate_on_edit)

    def poll():
        if timers.closed:
            return
        for _ in range(8):
            try:
                result, payload = queue.get_nowait()
            except Empty:
                break
            if state['close_requested']:
                state['busy'] = False
                dialog.destroy()
                return
            if result == 'ok':
                state['result'] = payload
                display(payload)
            else:
                state['result'] = None
                status.set('Diagnóstico indisponível; nenhuma operação autorizada.')
                show_details('Não foi possível completar a leitura. Revise o sistema '
                             'e o PowerShell antes de tentar novamente.')
            enable(True)
        if not timers.closed:
            timers.after(100, poll)

    timers.after(100, poll)
    dialog.protocol('WM_DELETE_WINDOW', close)
    return dialog
