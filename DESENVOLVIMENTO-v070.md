# PC Restore & Optimizer v0.7.0-dev

Base: código fornecido v0.6.9. Este pacote é uma versão de desenvolvimento, não uma versão pronta para reinstalar Windows.

## Implementado nesta etapa
- Descoberta das letras de unidades via API GetLogicalDrives do Windows, sem letras C/D/F/G predeterminadas.
- Nenhum destino de backup pré-selecionado: cada usuário precisa selecionar um local e validar espaço/risco.
- Uma seleção de disco para formatação anteriormente salva não é reativada automaticamente ao carregar preferências.
- Testes unitários para descoberta em ambiente não Windows e ausência de destino presumido.
- Nenhum mecanismo novo de exclusão ou formatação foi introduzido.

## Ainda obrigatório antes de uma versão pública
- Inventário dos volumes sem letra/montagens NTFS e gerenciamento de hotplug após inicialização.
- Pré-checagem de destino em outro volume físico, verificação SHA-256 real e testes de recuperação sob interrupção.
- Auditoria de dependências entre volumes e detecção generalizada de apps/jogos.
- Testes de integração e GUI em Windows, com cenários de discos EFI/UEFI e BIOS.
- Reinstalação do Windows deve permanecer sujeita a confirmação específica e validação real.
- Interface gamer moderna desenhada no Figma e implementada gradualmente no desktop.
