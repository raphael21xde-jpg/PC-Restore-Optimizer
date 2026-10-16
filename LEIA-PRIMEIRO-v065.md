# PC Restore & Optimizer v0.6.5 — Vínculos, importação e conferência do C: (PRÉVIA)

**ATENÇÃO:** Esta versão **não está autorizada a formatar ou excluir arquivos**. Os comandos de instalação do Windows, exclusão de arquivos e alterações na EFI permanecem desabilitados. A versão 0.6.5 ainda não verifica backups de saves nem recupera dados efetivamente.

## Novidades

1. **Vínculos de dados conferidos:** a seção Preservação mostra as associações aprovadas em uma ficha mesmo quando o catálogo classificou um jogo como aplicativo. Nesses casos, indica que o tipo do item precisa ser revisto. Um caminho sugerido sem confirmação NÃO aparece como associação confirmada. Um caminho confirmado pelo usuário NÃO é uma cópia de segurança.
2. **Importação mais clara:** ao selecionar por engano `preferencias-v05.json` ou `plano-preservacao-previa.json` em **Meu Computador > Importar inventário anterior**, uma mensagem mostra que o tipo está errado e indica a opção correta. Importações aceitas continuam sem sobrescrever inventários já carregados. Suporta inventários `pcro-discovery-v1` das versões anteriores.
3. **Conferir fontes do C: (sem copiar):** botão na seção **Preservação**, abaixo dos controles principais. Lê apenas metadados dos caminhos marcados no C: (até 500 por execução), identifica AUSENTE, SEM ACESSO, REVISAR LINK e LOCALIZADO, com relatório exportável. Não abre conteúdos, não percorre todas as subpastas, não calcula tamanho integral e não garante integridade.
4. **Indicadores de preservação:** permanecem separados jogos/apps selecionados, pastas/arquivos marcados, caminhos do C: que precisam de backup e sinalizações de remoção apenas para planejamento.
5. Os inventários novos são salvos em `deteccao-detalhada-v065.json`, preservando a compatibilidade de importação com `v064` / `v063`.

## Como instalar sem perder dados de versões anteriores

- Extraia o ZIP **inteiro em pasta nova**, diferente da v0.6.4. Execute `INICIAR.bat` no Windows.
- Para reaproveitar decisões antigas, use **Preservação > Importar escolhas da versão anterior** e indique `preferencias-v05.json` da pasta anterior. Não confunda com arquivo de varredura.
- Em **Meu Computador > Importar inventário anterior**, escolha `deteccao-detalhada-v064.json` da v0.6.4 ou `deteccao-detalhada-v063.json` da v0.6.3. Se não houver arquivo, use a varredura seletiva mais tarde; não invente um relatório. Inventários importados são históricos.
- Confira um jogo selecionado em D: com caminho aprovado no C:. Em **Preservação > Atualizar plano**, o vínculo deve aparecer; se o item tiver sido classificado como aplicativo, deve indicar **Tipo do item a conferir**.
- Clique em **Conferir fontes do C: (sem copiar)** e confira as linhas: LOCALIZADO apenas significa que o arquivo ou pasta existe. Use **Exportar conferência JSON** se desejar compartilhar o relatório sem capturar todo o desktop.
- Abra **Revisar erros de varredura**, confira os caminhos com acesso negado, ignorados e unidades com varredura parcial.
- Feche e abra o aplicativo, verifique se escolhas e relações continuam visíveis.

## Segurança indispensável

- **Não preservar** ≠ apagar. Ausência de seleção ≠ autorização para excluir.
- **C:** contém o Windows e seus dados devem ser realmente copiados para armazenamento independente, verificados por hash e recuperados em teste **antes** de reinstalar.
- **F:** contém uma EFI utilizada pelo boot atual. **G:** usa Storage Spaces Simples, sem redundância. Não altere partições nem inicialização com esta versão.
- O novo botão de conferência verifica os caminhos de origem **sem** criar backup. Nenhuma linha de resultado significa “pronto para formatar”.

## Testes de desenvolvimento

- 218 testes automatizados da suíte `python -m unittest discover -s tests -p 'test_*.py' -q` (rodados no ambiente Linux com display virtual). O funcionamento com os discos reais do usuário ainda precisa ser testado no Windows.
