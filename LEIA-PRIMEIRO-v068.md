# PC Restore & Optimizer v0.6.8 — Auditoria Inteligente e Diagnóstico de Discos (PRÉVIA)

Versão construída sobre a v0.6.7. **Não executa formatação, remoção de dados, alterações em partições, EFI, BCD ou instalação do Windows.** Não autoriza reinstalação. O motor de backup seletivo da v0.6.6 permanece disponível e separado da auditoria.

## Como começar

1. Extraia todo o ZIP **em uma pasta nova**. Abra `INICIAR.bat` com Python 3 instalado.
2. Em **Preservação**, confira as escolhas antigas. Se os jogos e saves não aparecerem, use **Importar escolhas da versão anterior** e escolha `preferencias-v05.json` da pasta v0.6.7 (ou de outra versão com as seleções válidas). A importação das escolhas é diferente da importação do inventário.
3. Clique em **Auditar dados do C: • revisão e EFI v0.6.8**.
4. Na aba **Locais de dados**, escolha uma das pastas listadas e clique em **Examinar selecionado (sem copiar)**. Em **Revisar pasta**, é possível visualizar até 100 entradas por página, abrir subpastas e marcar um arquivo/pasta individual como **Manter** ou **Não preservar (não exclui)**. As escolhas só são registradas após confirmação e serão refletidas na Preservação.
5. Revise especialmente **osu! clássico**, `Documents\My Games`, Steam `userdata` e perfis locais de navegadores. Não marque automaticamente todo `AppData` como backup: escolha dados relevantes por aplicativo. Metadados não certificam que um save é válido.
6. Clique em **Importar inventário do C: (histórico)** se a aba **Erros do C:** disser que não há inventário. Escolha um arquivo `deteccao-detalhada-v0xx.json` **do computador**, que contenha a varredura de C:. Unidades já carregadas não serão substituídas. Importação ocorre em segundo plano.
7. Clique em **Conferir manifest.json anterior** e selecione o `manifest.json` da pasta de backup no G: usada no ensaio v0.6.6. O programa recalcula hashes SHA-256 dos arquivos do manifesto. Esse resultado **não comprova** que todos os dados do C: estão selecionados ou recuperáveis.
8. Confira **Discos e EFI**. Agora há duas consultas independentes: `Get-Disk/Get-Partition` e `Win32_DiskDrive/Win32_Volume`. Discos dinâmicos podem não mapear letra → partição; a interface mostrará **MAPEAMENTO INCOMPLETO** em vez de anunciar ausência da EFI. Não faça nenhuma mudança no SSD Kingston, WD NVMe ou G:.
9. Confira **Mapa de recuperação** e **Checklist pendente**. Exporte `auditoria-inteligente-c-efi-v068.json` e envie junto ao **vídeo único** para análise.

## Como interpretar as evidências

- **Selecionado / manter**: intenção registrada. Nenhuma cópia ocorre automaticamente.
- **Não preservar**: o item sai do plano de preservação, **mas NÃO é permissão de excluir**.
- **Manifesto verificado**: prova apenas que cada arquivo listado no manifesto ainda corresponde ao SHA-256 registrado. O plano geral pode continuar incompleto.
- **Inventário antigo**: carrega erros históricos, mas não prova o estado atual dos arquivos e não cria novas escolhas.
- **EFI não mapeada**: a consulta não encontrou associação confiável; **não** significa que a partição EFI deixou de existir. A inicialização independente do WD precisa ser planejada e comprovada em outra fase.
- **Perfis de navegador**: copiar pastas não garante restaurar senhas, cookies, passkeys ou sessões. Use exportações, sincronização ou mecanismos oficiais quando necessário.

## Segurança

- Não apague nem altere `G:\PCRO-Backups-Teste` nem o manifesto do backup validado na v0.6.6.
- O G: usa Storage Spaces simples sem redundância. Isso não substitui uma cópia adicional independente antes de qualquer operação destrutiva.
- Não formate C:, D:, F: ou G:. Não remova EFI ou desconecte discos durante esses testes.
- JSON da auditoria pode conter caminhos, nomes de usuário e inventário de discos; compartilhe apenas em ambiente privado.
- A análise de pastas é paginada, **não recursiva**. Não identifica automaticamente todos os arquivos importantes.
- `ready_for_format`, `installation_authorized`, `deletions_authorized`, `backup_verified` e `restore_verified` permanecem **false** na auditoria geral. O detalhe do manifesto aparece em `backup_evidence`, com escopo limitado.

## Modificações técnicas

- `audit_v068.py`: consulta de discos via Storage e CIM, tratamento conservador de volumes dinâmicos, leitura paginada das subpastas, importação de inventários antigos e revalidação real de manifestos.
- `completeness_audit_ui_v068.py`: seis abas, seleção explícita por local ou arquivo, navegação de subpastas, importações e hash em threads, relatório JSON.
- `workflow_ui.py`, `app.py`: integração nas telas Preservação / Instalar Windows e versão atualizada.
- `tests/test_audit_v068.py`, `tests/test_audit_ui_v068.py`: testes de segurança, regressão e interface.

**Os testes automatizados rodaram em um ambiente Linux com display virtual; é indispensável testar o diagnóstico real de EFI no seu Windows antes de interpretar seus resultados.**
