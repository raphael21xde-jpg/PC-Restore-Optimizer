# Integração da auditoria com as escolhas do inventário SQLite

**Marco A — continuação da PR #50.** Não altera os motores de backup/restauração, não realiza varredura, nem executa ações destrutivas.

## Por que é necessária

O inventário detalhado registra as escolhas individuais diretamente em um banco `inventario-pcro.sqlite3` (índice de metadados). A auditoria v0.6.9 já usava `app.choices`, ou seja, apenas as decisões que o usuário havia importado para o plano. Assim, a auditoria podia mostrar 1 caminho selecionado apesar de existirem outras escolhas salvas no SQLite.

## Fluxo

1. Entre em **Histórico e relatórios** ou **Preservação**, abra a **Auditoria de dados do C: / EFI** já existente.
2. Abra a nova aba **Escolhas do índice SQLite** e clique **Abrir índice SQLite existente**.
3. Selecione o banco antigo, sem recriar índice. O aplicativo lê **somente decisões explícitas** (`preservar`/`nao_copiar`) e o estado do índice. A consulta é feita numa thread SQLite read-only; o restante dos milhões de registros não é aberto como conteúdo.
4. Confira a prévia: até 200 linhas na tela (com contagem de todas as decisões válidas, limitado a 4.000 por integração), preservação/não copiar no C:, escolhas em outros discos e **conflitos com o plano atual**. Nada é aplicado automaticamente.
5. **Somente se quiser incorporar decisões:** clique **Aplicar escolhas ao plano (confirmar)** e confirme o aviso que explica que o SQLite prevalecerá sobre decisões atuais quando houver conflito. A aplicação usa o **importador validado preexistente**, não cria uma nova lógica de seleção.
6. A auditoria atualiza os caminhos escolhidos, mas mantém **SHA-256 não comprovado, restauração não comprovada e reinstalação bloqueada** até haver evidências independentes.

Não usar este caminho para importar automaticamente uma escolha desconhecida. Um índice antigo registra **intenções históricas**, não garante existência/atualidade dos arquivos.

## Segurança e limitações

- Consulta SQLite por URI `mode=ro`, transação encerrada e conexão fechada; não lê os bytes dos arquivos de origem, não revisita discos e não mexe no índice.
- Só são aceitos o schema PCRO e caminhos locais Windows validados. Máximo de 4.000 escolhas não revisadas por operação; excedentes exigem revisão/exportação por grupos.
- O estado `terminado_com_lacunas` não é garantia de cobertura total; acesso negado e links permanecem como lacunas.
- O importador preserva o significado de `nao_copiar`: **não inclui na cópia, NUNCA apaga**.
- Depois de aplicar novas escolhas, o plano de backup é invalidado e precisa ser recalculado pela lógica já existente.
- A auditoria e os diagnósticos de EFI continuam somente leitura, sem autorizar formatação ou reinstalação.

## Testes proporcionais

`py -3 -m unittest discover -s tests -p "test_index_audit_bridge.py" -v`

Os testes usam um **banco SQLite sintético pequeno**, não um novo inventário real ou teste pesado de backup. Conferem escolhas, conflitos, prévia sem importação, confirmação por mecanismo existente, preservação dos bytes do SQLite e rejeição de índices inválidos.
