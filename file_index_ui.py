"""Tk GUI for durable, opt-in file-metadata indexing and manual review.

The source volumes are read-only. Database/choice exports are created only in
locations selected by the user. Backups and deletions are never triggered.
"""
from __future__ import annotations

from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from inventory_index import FileMetadataIndex, index_roots
from inventory_paged import discover_local_roots


def show_file_index(parent):
    win = tk.Toplevel(parent)
    win.title("PCRO | Índice detalhado e escolhas — nenhuma exclusão")
    win.geometry("990x660")
    win.minsize(620, 430)
    win.resizable(True, True)
    win.transient(parent)
    status = tk.StringVar(value="Crie um índice novo ou abra um existente. Nenhum backup será realizado.")
    search = tk.StringVar()
    q = Queue()
    cancel = threading.Event()
    state = {"busy": False, "db": None, "rows": [], "offset": 0, "path": None}

    header = ttk.Frame(win, padding=10)
    header.pack(fill="x")
    ttk.Label(header, text="Inventário detalhado — somente metadados",
              font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(header, text=(
        "Os nomes de arquivos podem ser privados: salve o índice apenas em uma pasta sua. "
        "Não abre arquivos, não copia dados e NÃO apaga nada."), wraplength=790).pack(anchor="w", pady=(3, 7))
    actions = ttk.Frame(header)
    actions.pack(fill="x")
    def add_action(title, command):
        b = ttk.Button(actions, text=title, command=command)
        b.pack(side="left", padx=(0, 6), pady=3)
        return b

    main = ttk.Frame(win, padding=(10, 2))
    main.pack(fill="both", expand=True)
    lookup = ttk.Frame(main)
    lookup.pack(fill="x", pady=(6, 3))
    ttk.Label(lookup, text="Filtrar caminho:").pack(side="left")
    ttk.Entry(lookup, textvariable=search, width=55).pack(side="left", fill="x", expand=True, padx=6)
    columns = ("path", "kind", "size", "decision")
    tree = ttk.Treeview(main, columns=columns, show="headings", selectmode="browse")
    for name, label, width in (
        ("path", "Caminho observado", 550), ("kind", "Tipo", 80),
        ("size", "Bytes", 90), ("decision", "Escolha", 100)):
        tree.heading(name, text=label)
        tree.column(name, width=width, stretch=(name == "path"))
    tree_scroll = ttk.Scrollbar(main, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=tree_scroll.set)
    tree_scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    controls = ttk.Frame(win, padding=10)
    controls.pack(fill="x", side="bottom")
    ttk.Label(controls, textvariable=status, wraplength=800).pack(anchor="w", pady=(0, 4))
    row = ttk.Frame(controls)
    row.pack(fill="x")
    def refresh(reset=False):
        db = state["db"]
        if db is None:
            return
        if reset:
            state["offset"] = 0
        selected = db.search(search.get(), offset=state["offset"], limit=100)
        state["rows"] = selected
        for item in tree.get_children():
            tree.delete(item)
        for index, entry in enumerate(selected):
            tree.insert("", "end", iid=str(index),
                        values=(entry["path"], entry["kind"], entry["bytes"],
                                entry["decision"]))
        meta = db.metadata()
        counts = db.decision_counts()
        status.set(f'Índice: {meta.get("state", "parcial")}. '
                   f'Preservar: {counts.get("preservar", 0)}; '
                   f'Não copiar: {counts.get("nao_copiar", 0)}. '
                   'São intenções, não backup verificado.')

    def load_index(path):
        if state["db"] is not None:
            state["db"].close()
            state["db"] = None
        state["db"] = FileMetadataIndex(path)
        state["path"] = path
        search.set("")
        refresh(reset=True)

    def open_existing():
        if state["busy"]:
            return
        path = filedialog.askopenfilename(
            parent=win, title="Abrir índice PCRO existente",
            filetypes=[("Índice SQLite", "*.sqlite3"), ("Todos", "*.*")])
        if path:
            try:
                load_index(path)
            except (OSError, ValueError, Exception) as err:
                messagebox.showerror("Índice não aberto", str(err), parent=win)

    def start_scan():
        if state["busy"]:
            return
        path = filedialog.asksaveasfilename(
            parent=win, title="Escolha um NOME NOVO para o índice (não sobrescreve)",
            defaultextension=".sqlite3",
            initialfile="inventario-pcro.sqlite3",
            filetypes=[("Índice SQLite", "*.sqlite3")])
        if not path:
            return
        if Path(path).exists():
            messagebox.showerror("Índice já existe",
                                 "Escolha um nome novo. Nada será sobrescrito.", parent=win)
            return
        try:
            roots = discover_local_roots()
            if not roots:
                raise ValueError("Nenhuma unidade local acessível.")
        except (OSError, ValueError, RuntimeError) as err:
            messagebox.showerror("Não iniciou", str(err), parent=win)
            return
        state["busy"] = True
        cancel.clear()
        for button in (start_button, open_button, export_button):
            button.configure(state="disabled")
        stop_button.configure(state="normal")
        status.set(f"Examinando metadados de {len(roots)} unidade(s); "
                   "destino selecionado, sem excluir nada.")
        def work():
            try:
                report = index_roots(
                    roots, path, cancelled=cancel,
                    progress=lambda seen, pending: q.put(("progress", (seen, pending))))
                q.put(("complete", (path, report)))
            except Exception as err:
                q.put(("error", (path, str(err))))
        threading.Thread(target=work, daemon=True).start()

    def stop_scan():
        cancel.set()

    def choose(decision):
        db = state["db"]
        selection = tree.selection()
        if db is None or not selection or state["busy"]:
            return
        row = state["rows"][int(selection[0])]
        try:
            db.set_decision(row["path"], decision)
            refresh()
        except (OSError, ValueError) as err:
            messagebox.showerror("Decisão não registrada", str(err), parent=win)

    def export_choices():
        db = state["db"]
        if db is None or state["busy"]:
            return
        target = filedialog.asksaveasfilename(
            parent=win, defaultextension=".json",
            initialfile="escolhas-inventario-pcro.json",
            filetypes=[("JSON", "*.json")])
        if target:
            try:
                result = db.export_choices(target)
                messagebox.showinfo(
                    "Escolhas exportadas",
                    f'{len(result["choices"])} escolhas salvas. '
                    "NENHUM arquivo foi copiado ou excluído.", parent=win)
            except (OSError, ValueError) as err:
                messagebox.showerror("Exportação bloqueada", str(err), parent=win)

    start_button = add_action("CRIAR índice detalhado (somente leitura das fontes)", start_scan)
    open_button = add_action("ABRIR índice anterior", open_existing)
    export_button = add_action("Exportar escolhas JSON", export_choices)
    stop_button = add_action("Parar varredura", stop_scan)
    stop_button.configure(state="disabled")
    ttk.Button(lookup, text="Pesquisar", command=lambda: refresh(reset=True)).pack(side="left")
    ttk.Button(row, text="Marcar PRESERVAR", command=lambda: choose("preservar")).pack(side="left", padx=4)
    ttk.Button(row, text="NÃO COPIAR (não apaga)", command=lambda: choose("nao_copiar")).pack(side="left", padx=4)
    ttk.Button(row, text="Revisar depois", command=lambda: choose("revisar")).pack(side="left", padx=4)
    ttk.Button(row, text="Anterior 100", command=lambda: (
        state.update(offset=max(0, state["offset"]-100)), refresh())).pack(side="right", padx=4)
    ttk.Button(row, text="Próximos 100", command=lambda: (
        state.update(offset=state["offset"]+100), refresh())).pack(side="right", padx=4)

    def poll():
        if not win.winfo_exists():
            return
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "progress":
                    status.set(f"Leitura: {payload[0]} entradas, {payload[1]} pastas pendentes. "
                               "Clique em Parar se necessário.")
                else:
                    state["busy"] = False
                    stop_button.configure(state="disabled")
                    for button in (start_button, open_button, export_button):
                        button.configure(state="normal")
                    path, details = payload
                    if kind == "complete":
                        try:
                            load_index(path)
                            status.set(f'Índice criado com {details["indexed_files"]} arquivos. '
                                       "Ainda não é um backup.")
                        except Exception as err:
                            messagebox.showerror("Índice criado, mas não aberto",
                                                 str(err), parent=win)
                    else:
                        status.set("Varredura interrompida ou falhou. Índice parcial, "
                                   "caso criado, pode ser aberto apenas para revisão.")
                        messagebox.showwarning("Inventário incompleto", details, parent=win)
        except Empty:
            pass
        win.after(150, poll)

    def close():
        if state["busy"]:
            cancel.set()
            messagebox.showinfo("Interrompendo",
                                "Cancelamento solicitado. Feche depois que a tarefa parar.",
                                parent=win)
            return
        if state["db"] is not None:
            state["db"].close()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", close)
    win.after(150, poll)
    return win
