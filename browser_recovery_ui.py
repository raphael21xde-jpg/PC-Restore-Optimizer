"""Guided import; browser imports remain explicit user actions."""
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import webbrowser
from browser_recovery import (inspect_recovery, prepare_bookmarks, destination_supported,
                              bookmark_import_steps, password_import_steps, help_url)
from browser_vault import discover_profiles, restore_to_staging
from browser_guard import extract_to_staging


def show_recovery(parent):
    win = tk.Toplevel(parent)
    win.title('Restaurar navegador — v0.5.12')
    win.geometry('880x680')
    frame = ttk.Frame(win, padding=16)
    frame.pack(fill='both', expand=True)
    state = {'root': None, 'info': None, 'busy': False}
    status = tk.StringVar(value='Escolha o cofre ou a pasta já recuperada no teste anterior.')
    ttk.Label(frame, text='Restaurar navegador', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Favoritos e senhas por importação no próprio navegador. Nenhum perfil instalado é sobrescrito.', wraplength=820).pack(anchor='w', pady=8)
    profiles = discover_profiles()
    names = [f'{p.browser} — {p.label} — {p.path}' for p in profiles]
    ttk.Label(frame, text='1. Perfil de destino (abra o navegador uma vez para ele aparecer):').pack(anchor='w')
    choice = ttk.Combobox(frame, state='readonly', values=names, width=105)
    choice.pack(fill='x', pady=6)
    if names: choice.current(0)
    else: ttk.Label(frame, text='Nenhum perfil localizado. Instale/abra o navegador e reabra este assistente.').pack(anchor='w')
    ttk.Label(frame, text='2. Origem dos dados:').pack(anchor='w', pady=(10, 4))
    row = ttk.Frame(frame); row.pack(fill='x')
    details = tk.Text(frame, height=10, wrap='word')
    def describe(root):
        state.update(root=None, info=None)
        checked.set(False)
        try:
            info = inspect_recovery(root)
            state.update(root=Path(root), info=info)
            text = f"Origem: {root}\nNavegador no cofre: {info['browser']}\n\n"
            text += 'Favoritos: ' + ('disponíveis para importação' if info['bookmarks_html'] or info['bookmarks_json'] else 'ausentes neste formato; usar sincronização/exportação oficial') + '\n'
            text += 'Senhas CSV: ' + ('exportação manual encontrada' if info['password_csv'] else 'ausente; usar sincronização ou exportar no navegador original antes de formatar') + '\n\n'
            text += 'Histórico, extensões, abas e preferências: não aplicados automaticamente nesta versão. Use a sincronização quando disponível. Cookies, passkeys e sessões autenticadas não são recuperados por este assistente.'
            details.configure(state='normal'); details.delete('1.0', 'end'); details.insert('1.0', text); details.configure(state='disabled')
            status.set('Origem pronta. A importação ainda NÃO foi executada.')
        except Exception as exc: messagebox.showerror('Origem inválida', str(exc), parent=win)
    def folder():
        if state['busy']: return
        path = filedialog.askdirectory(parent=win, title='Pasta CONFERIR-NAVEGADOR que contém profile e/ou manual-export')
        if path: describe(path)
    def vault():
        if state['busy']: return
        path = filedialog.askopenfilename(parent=win, filetypes=[('Cofres', '*.pcbrowser *.opgx')])
        if not path: return
        dest = filedialog.askdirectory(parent=win, title='Pasta privada para extrair os dados (fora do perfil instalado)')
        if not dest: return
        d = Path(dest).resolve()
        if any(d == p.path.resolve() or p.path.resolve() in d.parents for p in profiles):
            messagebox.showerror('Destino inválido', 'Escolha uma pasta fora dos perfis instalados.', parent=win); return
        if not messagebox.askyesno('Recuperação privada', 'A extração pode conter um CSV de senhas legíveis. Use uma pasta privada. Continuar?', parent=win): return
        pw = simpledialog.askstring('Senha do cofre', 'Frase-senha (não será salva):', show='*', parent=win)
        if not pw: return
        state['busy'] = True; status.set('Autenticando e extraindo o cofre…')
        def finish(out=None, error=None):
            state['busy'] = False
            if error:
                status.set('Falha na recuperação.'); messagebox.showerror('Não foi possível abrir', error, parent=win)
            else: describe(out)
        def worker():
            try:
                out = (extract_to_staging(path, dest, pw) if path.lower().endswith('.opgx') else restore_to_staging(path, dest, pw))
                parent.after(0, lambda: finish(out=out))
            except Exception as exc:
                parent.after(0, lambda e=str(exc): finish(error=e))
        threading.Thread(target=worker, daemon=True).start()
    ttk.Button(row, text='Abrir cofre com senha', command=vault).pack(side='left', padx=(0, 8))
    ttk.Button(row, text='Usar pasta já recuperada', command=folder).pack(side='left')
    details.pack(fill='both', expand=True, pady=10); details.configure(state='disabled')
    protect = tk.BooleanVar()
    ttk.Checkbutton(frame, text='Já protegi os dados atuais do destino (cofre/exportação), ou este perfil é novo e vazio.', variable=protect).pack(anchor='w')
    ttk.Label(frame, text='3. Escolha o que importar. Os botões preparam os arquivos; você confirma a importação no navegador.', wraplength=820).pack(anchor='w', pady=8)
    actions = ttk.Frame(frame); actions.pack(fill='x')
    def ready():
        if not state['info'] or choice.current() < 0:
            messagebox.showwarning('Seleção necessária', 'Selecione uma origem e um perfil instalado.', parent=win); return False
        if not protect.get():
            messagebox.showwarning('Proteja o destino', 'Use Criar cofre na tela Navegadores para proteger o perfil atual antes de importar, ou confirme que ele é novo e vazio.', parent=win); return False
        if not destination_supported(profiles[choice.current()].browser):
            messagebox.showinfo('Navegador sem passo a passo', 'Este assistente orienta a importação no Opera, Opera GX, Google Chrome, Microsoft Edge e Mozilla Firefox. Para os outros navegadores, entre na conta e ligue a sincronização, ou importe o CSV de senhas pelo próprio navegador e depois apague o CSV.', parent=win); return False
        return True
    def copy_path(path):
        win.clipboard_clear(); win.clipboard_append(str(path))
    def bookmarks():
        if not ready(): return
        dest = filedialog.askdirectory(parent=win, title='Pasta privada para o HTML de favoritos')
        if not dest: return
        d = Path(dest).resolve()
        if any(d == p.path.resolve() or p.path.resolve() in d.parents for p in profiles):
            messagebox.showerror('Destino inválido', 'Escolha uma pasta fora do perfil instalado.', parent=win); return
        try:
            out, count = prepare_bookmarks(state['root'], dest)
            copy_path(out)
            messagebox.showinfo('Importar favoritos', bookmark_import_steps(profiles[choice.current()].browser, out), parent=win)
            status.set('HTML preparado. Confirme a importação e confira os favoritos no navegador.')
        except Exception as exc: messagebox.showerror('Falha na preparação', str(exc), parent=win)
    def passwords():
        if not ready(): return
        path = state['info']['password_csv']
        if not path:
            messagebox.showinfo('Sem CSV de senhas', 'Este cofre não contém exportação manual de senhas. Use a sincronização. Se ainda tiver o Windows original, exporte as senhas pelo navegador e crie um novo cofre incluindo esse CSV.', parent=win); return
        copy_path(path)
        messagebox.showinfo('Importar senhas', password_import_steps(profiles[choice.current()].browser), parent=win)
        status.set('Caminho do CSV preparado. A importação precisa ser confirmada no navegador.')
    ttk.Button(actions, text='Preparar favoritos', command=bookmarks).pack(side='left', padx=(0, 8))
    ttk.Button(actions, text='Orientar importação de senhas', command=passwords).pack(side='left', padx=(0, 8))
    def official_help():
        url = help_url(profiles[choice.current()].browser) if choice.current() >= 0 else ''
        if url: webbrowser.open(url)
        else: messagebox.showinfo('Ajuda oficial', 'Escolha um perfil de destino para abrir a ajuda do navegador.', parent=win)
    ttk.Button(actions, text='Ajuda oficial do navegador', command=official_help).pack(side='left')
    checked = tk.BooleanVar()
    ttk.Checkbutton(frame, text='Conferi no navegador os dados importados (confirmação manual).', variable=checked).pack(anchor='w', pady=10)
    ttk.Label(frame, textvariable=status, wraplength=820).pack(anchor='w')
    def close():
        if state['busy']: messagebox.showinfo('Aguarde', 'Aguarde a extração terminar.', parent=win)
        else: win.destroy()
    win.protocol('WM_DELETE_WINDOW', close)
