# PC Restore & Optimizer 0.6.9 — prévia de auditoria

Base: versão 0.6.8.1. Esta atualização melhora a auditoria; não é uma versão final para reinstalação do Windows.

## Instalar e abrir

1. Extraia o ZIP em uma pasta nova. Mantenha a versão anterior e os backups.
2. Execute INICIAR.bat com o mesmo Python usado anteriormente.
3. Se suas escolhas não aparecerem, use Importar escolhas da versão anterior e selecione preferencias-v05.json da pasta anterior.
4. Abra Preservação > Auditar dados do C: — revisão e EFI v0.6.9.

## O que mudou

- Pastas com filhos selecionados mostram SELEÇÃO PARCIAL — REVISAR RESTANTE. Os filhos selecionados são registrados no JSON; nenhuma pasta é adicionada automaticamente.
- O mapa de recuperação separa caminhos sem prova de backup de caminhos com arquivos verificados no manifesto. A quantidade verificada aparece por caminho. Arquivos verificados não certificam a cobertura inteira da pasta.
- Seleção, evidência de backup, cobertura e restauração são campos distintos. Restauração permanece não comprovada nesta auditoria; não foi adicionado importador de provas de restauração.
- Itens ignorados da varredura não são mais chamados de exclusões no resumo da auditoria.
- A consulta de discos usa as letras encontradas no Windows, em vez da lista fixa C/D/F/G, e consulta a unidade do Windows pela variável do sistema.
- Uma consulta adicional de metadados associa volumes aos números de disco, inclusive volumes sem letra. Usa IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, abre o volume sem acesso de leitura/escrita e não monta nem modifica partições. A consulta roda em processo separado com prazo de 25 segundos; falhas ficam explícitas no relatório.
- Volumes que abrangem mais de um disco mantêm todas as associações. A presença de FAT32 não é tratada como prova de EFI. Volume de sistema mapeado não comprova boot independente.
- Tabelas da auditoria têm rolagem horizontal para consultar textos longos.
- O seletor de inventário descreve o arquivo esperado sem usar o nome fictício v0xx.

## Teste curto no Windows

1. Confira em Locais de dados se uma pasta com apenas alguns filhos marcados aparece como seleção parcial (os exemplos usados anteriormente continuam válidos).
2. Abra Discos e EFI. Confira o volume marcado Sistema e a coluna Disco(s). Se não houver associação, o aplicativo deve mostrar a limitação, não inventar o disco.
3. Para conferir os estados por caminho, use Conferir manifest.json anterior. Isso relê o backup existente, mas não o sobrescreve e não cria nova cópia. A evidência não é guardada como prova permanente entre sessões.
4. Se quiser incluir o histórico de varredura, importe o mesmo inventário já usado. Não execute nova varredura completa para esse teste.
5. Exporte auditoria-inteligente-c-efi-v069.json. Envie o JSON e, se houver erro ou texto ilegível, um print.

Não é necessário refazer backup, gravar todos os testes anteriores ou mudar suas escolhas.

## Validação realizada

- Compilação dos módulos Python aprovada.
- 278 testes encontrados: 250 passaram, 14 ignorados pela suíte, 14 com erro por ausência de tela gráfica ($DISPLAY). Não se declara a suíte completa aprovada.
- Os 13 testes novos passaram. Cobrem seleção parcial, limites da evidência de backup, nomes de caminhos semelhantes, erros da varredura, leitura de extensões, múltiplos discos, falhas parciais e fechamento do handle nativo.
- A chamada nativa foi testada com uma API simulada. A execução real no Windows e a interface gráfica precisam de validação nesta prévia.
- O relatório enviado foi usado para análise local da seleção parcial; dados pessoais, relatórios e vídeos do usuário não estão incluídos no ZIP.

## Limites existentes

Esta atualização não transforma o aplicativo em produto universal pronto: a tela de preservação ainda é voltada ao C:, e as demais configurações de Windows precisam de evolução e testes. A detecção de discos foi generalizada, mas não há garantia de suporte a todo controlador, volume dinâmico ou Storage Spaces. Números de disco são da sessão e devem ser conferidos com modelo e serial. Um dispositivo Storage Spaces pode ser virtual; seu número não identifica necessariamente cada unidade física integrante.

Formatação, exclusão e alterações de EFI continuam indisponíveis nesta etapa. O motor de cópia/restauração não foi alterado.

## Referências técnicas

- https://learn.microsoft.com/windows/win32/api/winioctl/ni-winioctl-ioctl_volume_get_volume_disk_extents
- https://learn.microsoft.com/windows/win32/api/winioctl/ns-winioctl-volume_disk_extents
- https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
