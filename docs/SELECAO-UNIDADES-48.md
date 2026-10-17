# Inventário #48 — escolher unidades locais

Na janela **Inventário DETALHADO**, o botão **ESCOLHER unidades**
permite marcar os discos que entrarão **somente no próximo índice novo**.
A seleção padrão continua sendo *todas as unidades locais detectadas*.
Se não houver seleção disponível, a criação será bloqueada.

1. Clique em **ESCOLHER unidades** e desmarque as unidades que não
   deseja examinar.
2. Confirme com **Confirmar unidades**.
3. Clique em **CRIAR índice detalhado** e indique um arquivo SQLite **novo**
   em uma pasta privada. Aguarde a leitura de metadados.
4. Pesquise arquivos, selecione pastas e marque decisões sem excluir nada.

**Não precisa refazer o índice que já foi criado:** use o botão
**ABRIR índice anterior** para continuar a pesquisa e a seleção.
Alterar a lista de unidades não altera um índice existente.

Para validar o seletor em um Windows, sem examinar discos reais:

```powershell
py -3 -m unittest discover -s tests -p "test_file_index_ui.py" -v
```

O teste de interface cria duas pastas temporárias simulando unidades,
escolhe apenas uma delas, verifica os registros do SQLite e confirma que
os arquivos fictícios nas duas origens permaneceram intactos.

A criação de índice ainda é **somente metadados**, com lacunas de
permissão e de links registradas; não cria backup, não restaura fontes,
não formata discos e não autoriza reinstalação do Windows.
