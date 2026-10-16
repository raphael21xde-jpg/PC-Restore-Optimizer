# PC Restore & Optimizer v0.6.7 — Auditoria de dados do C: e EFI (PRÉVIA)

Esta é uma **prévia de segurança não destrutiva** baseada na v0.6.6. Ela acrescenta uma auditoria por metadados para localizar possíveis dados do usuário que ainda não foram selecionados para cópia e diagnosticar a topologia das partições EFI. Ela **não garante inventário completo** nem autoriza formatação.

## Como executar e recuperar as escolhas

1. Extraia este ZIP **em uma nova pasta** no Windows. Execute `INICIAR.bat` com Python 3 instalado.
2. Abra **Preservação**. Se God of War Ragnarök, Forza ou outras escolhas não aparecerem, use **Importar escolhas da versão anterior** e selecione o arquivo `preferencias-v05.json` da pasta da v0.6.6. As pastas de versões diferentes não compartilham automaticamente o estado.
3. Clique em **Atualizar plano**. Confira se estão presentes os caminhos que você deseja proteger no C:.
4. Clique em **Auditar dados do C: e situação EFI • v0.6.7**. A mesma auditoria está disponível em **Instalar Windows → Auditoria C: / EFI**.
5. Aguarde a consulta de metadados. Consulte as cinco abas: **Locais de dados**, **Erros do C:**, **Discos e EFI**, **Mapa de recuperação**, **Checklist pendente**.
6. Use **Exportar auditoria JSON** para salvar o relatório e incluí-lo no vídeo. O arquivo pode conter caminhos locais pessoais; não o compartilhe publicamente.

## Como interpretar

- **REVISAR — NÃO SELECIONADO**: localização potencialmente relevante que existe e não está coberta por nenhum caminho explicitamente selecionado. A existência da pasta não garante que seja um save importante. Confira manualmente antes de decidir preservar.
- **SELECIONADO — NÃO COMPROVADO**: existe uma seleção que cobre o caminho, mas esta auditoria **não** verifica backup, hashes ou recuperação.
- **OUTRA UNIDADE — REVISAR**: local pessoal redirecionado para D:, F: ou G:, fora do C:. Não deve ser apagado nem formatado automaticamente.
- **AUSENTE / VAZIO**: localização não encontrada ou sem entradas diretas; isso não garante que outros locais estejam protegidos.
- **REVISAR LINK / SEM ACESSO / ERRO**: não confie na cobertura automática; reveja manualmente.
- **EFI: DEPENDÊNCIA POSSÍVEL**: a consulta identificou uma EFI em disco diferente do que contém C:. **Não altere a EFI do outro SSD**. Se a consulta detectar EFI no mesmo disco do Windows, isso **ainda não comprova boot independente**.
- **Erros do C:**: mostra os caminhos registrados no inventário; um inventário antigo ou com acesso negado pode deixar dados importantes fora da seleção.
- **Mapa de recuperação**: lista caminhos do C: a rever posteriormente para retornar à localização original. Não é uma restauração nem prova de preservação.

## Segurança e limites

- Não executa `format`, `diskpart`, `bcdboot`, comandos de exclusão, alterações em EFI/BCD/partições ou mudanças nas seleções.
- A consulta de partições usa somente comandos PowerShell `Get-Partition` e `Get-Disk`; os números dos discos podem mudar entre sessões. Confirme pela identidade física dos SSDs antes de qualquer decisão futura.
- A auditoria de pastas é rápida e **não recursiva**; usa metadados e verifica se há alguma entrada imediata. Não audita arquivos dentro das pastas, nem identifica todos os programas, saves ou perfis.
- As senhas, passkeys e sessões de navegador não são necessariamente restauráveis por cópia de pasta. Confirme backup/sincronização pelo método oficial do navegador.
- O backup da v0.6.6 (42 arquivos / 21,9 MiB, se foi o ensaio realizado) deve permanecer **intacto** no G:. Esta versão não o abre nem altera. O G: é Storage Spaces simples, **sem redundância**; a proteção contra falha do SSD requer outra cópia independente.
- **`ready_for_format`, `installation_authorized` e `deletions_authorized` permanecem `false` no JSON**, independentemente do resultado.
- A situação EFI anterior informada pelo usuário sugere inicialização dependente de outro SSD. Esta versão apenas observa; não tenta repará-la.

## Roteiro para um único vídeo

1. Abrir v0.6.7 → Preservação → importar preferências da v0.6.6 se necessário → Atualizar plano.
2. Mostrar God of War e Forza com os caminhos do C: e as escolhas preservadas.
3. Abrir **Auditar dados do C: e situação EFI • v0.6.7**; aguardar conclusão.
4. Percorrer **Locais de dados** (mostrando as entradas *revisar* e *selecionado*).
5. Percorrer **Erros do C:** (mostrar contagem e alguns exemplos, sem analisar um por um).
6. Percorrer **Discos e EFI** (mostrar o disco do C: e partições EFI identificadas, ou falha da consulta).
7. Percorrer **Mapa de recuperação** e **Checklist pendente**.
8. Exportar a auditoria como `auditoria-preservacao-c-efi-v067.json` e enviar vídeo + JSON para revisão. Não é necessário repetir backup de 42 arquivos ou varredura de 893 mil arquivos.

## Mudanças técnicas

- `completeness_audit_v067.py`: verificação de cobertura de caminhos selecionados, locais candidatos do perfil atual, lacunas do C:, inventário de discos e EFI em somente leitura, mapa de recuperação não autorizado.
- `completeness_audit_ui_v067.py`: janela com cinco abas, consulta em segundo plano e exportação JSON; a interface gráfica não é manipulada diretamente pela thread de trabalho.
- `workflow_ui.py`: integração em Preservação e Instalar Windows.
- `tests/test_completeness_audit_v067.py` e `tests/test_completeness_ui_v067.py`: testes de caminho, segurança, erros, EFI e interface.
