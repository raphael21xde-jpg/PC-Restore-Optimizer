# Índice detalhado de arquivos — prévia de preservação

**Estado:** desenvolvimento experimental. Não é backup, não é recuperação do
Windows e não autoriza formatação.

## Funcionalidade

A janela **Preservação → Backup seletivo → Novos #44–46 → Inventário DETALHADO**
permite:

- Criar um banco de índice SQLite **novo e escolhido pelo usuário**, examinando
  metadados das unidades locais encontradas em Windows (nome/caminho, tipo,
  tamanho e data). Arquivos não são abertos para leitura de conteúdo.
- Consultar nomes de arquivos e pastas, exibir 100 itens por página e navegar
  entre páginas de resultados, com barra horizontal para caminhos longos.
- Marcar individualmente arquivos como **Preservar**, **Não copiar (não apaga)**
  ou **Revisar depois**. As marcações permanecem no SQLite após fechar a janela.
- Exportar um JSON novo de escolhas para futura revisão no fluxo de backup.
  Ele **não inicia backup** nem importa automaticamente as decisões à seleção
  central do aplicativo.
- Abrir e revisar novamente um índice SQLite criado anteriormente.
- Cancelar varredura em andamento. O banco parcial, se criado, continua
  identificado como parcial/interrompido.

## Avisos e limites

- O SQLite e os JSONs podem conter nomes e caminhos pessoais; são **dados
  locais sem criptografia**. Escolha uma pasta privada, não envie esses índices
  publicamente e não confunda metadados com um backup seguro.
- O scanner não segue junções nem links (reparse points), não acessa
  conteúdo, não lê diretórios protegidos, não cria snapshot consistente
  durante mudanças no disco. Mesmo terminado, é cobertura parcial.
- O arquivo do próprio índice, quando salvo dentro de um volume sendo
  inventariado, **não é incluído** entre os arquivos escolhíveis.
- Esse módulo não classifica automaticamente o vínculo real entre
  aplicativos, saves e instalações. Essas relações exigem mais desenvolvimento.
- **Não copiar jamais significa apagar**; nenhuma exclusão/formatação ocorre.
- Exportar escolhas não comprova origem atual, capacidade de restaurar,
  integridade SHA-256, independência física ou segurança para formatar.

## Atualização pelo PowerShell — branch de desenvolvimento

A versão de testes da interface e do índice fica em
`feature/indice-arquivos-selecao`. Ela depende do inventário paginado
ainda em revisão, e por isso **não deve ser incorporada manualmente à main**.

Feche o aplicativo antes. Se a worktree `PCRO-dev-indice` já existir, **não**
repita `git worktree add`. Confira alterações locais antes de atualizá-la:

```powershell
Set-Location "$HOME\PCRO-dev-indice"
git status --short
git fetch origin
git switch --detach origin/feature/indice-arquivos-selecao
py -3 -m unittest discover -s tests -p "test_inventory_file_index.py" -v
py -3 -m unittest discover -s tests -p "test_inventory_paged_v044_v046.py" -v
py -3 -m unittest discover -s tests -p "test_file_index_ui.py" -v
.\INICIAR.bat
```

Se `git status --short` mostrar arquivos modificados, não descarte dados:
revise a saída antes do `git switch`.

Os testes usam somente dados fictícios temporários. A execução de varredura
em unidades reais só ocorre se o usuário clicar expressamente para criá-la.

Por enquanto a franquia gratuita do GitHub Actions do repositório privado
está esgotada; **falhas automáticas de execução sem etapa iniciada não
equivalem a reprovação do código**. Rodar os testes localmente não modifica
essa limitação do CI.
