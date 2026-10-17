# Backups em múltiplos destinos — implementação incremental

**Estado:** implementação inicial de múltiplos destinos **locais** no fluxo seletivo de preservação do **C:**. Não equivale à conclusão de backup em nuvem via API nem à certificação de independência do backup.

## Modos na interface

| Modalidade escolhida | Suporte nesta etapa | Limitações |
| --- | --- | --- |
| Outra pasta/unidade do computador | Cópia com manifesto e SHA-256 | Não prova independência física; verificar discos dinâmicos e Storage Spaces |
| HD/SSD externo ou pendrive | Pasta escolhida pelo usuário, cópia com SHA-256 | O rótulo “externo” é declarado pelo usuário; USB e identidade física ainda precisam de evidências |
| Pasta já sincronizada por cliente de nuvem | Cópia **local** para pasta do cliente, com SHA-256 | Não autentica na nuvem nem verifica upload, download, versão remota, cota, arquivos sob demanda ou restauração após formatação |
| Google Drive/OneDrive por API | **Não implementado** | OAuth com PKCE, consentimento, guarda segura de tokens, upload retomável, throttling, verificação remota e restauração pendentes |

O fluxo atual aceita somente origens explicitamente selecionadas do C:, com até oito destinos existentes **fora do C:**. Uma pasta de OneDrive/Google Drive no C: NÃO é um destino admissível neste fluxo porque a própria reinstalação poderia eliminá-la. Backups cloud via API, inclusive sem clientes instalados e sem volume local separado, são objetivos da fase seguinte.

## Como testar sem arriscar dados

Abra o fluxo **Backup seletivo e teste de recuperação do C:**, clique em **Analisar arquivos**, depois **2b. Vários destinos**. Marque uma ou mais pastas de destino em volumes não envolvidos na reinstalação e confirme. O aplicativo revalida existência, sobreposição de pastas, espaço livre com reserva e conflitos de discos lógicos conhecidos antes de chamar o motor de cópia. Cada cópia recebe uma pasta nova, um manifesto separado e SHA-256 próprio.

**Importante:** um plano sem conflitos conhecidos pode não possuir independência física. A interface pede confirmação humana e nunca declara o Windows pronto para reinstalar. O teste de restauração permanece separado. Não use arquivos únicos para os primeiros ensaios.

## Próximas entregas

1. Substituir o fluxo limitado ao C: por seleção de arquivos/saves/aplicativos em quaisquer discos presentes (sem exclusão por padrão).
2. Classificar e confirmar dispositivos internos/externos por bus USB, serial, enumeração e topologia real, sem assumir que uma letra é um disco físico.
3. Selecionar arquivos por destino (por exemplo jogos grandes para HD externo; saves e documentos para armazenamento remoto) e registrar conjunto/hash de cada destino.
4. Implementar conectores diretos Google Drive e OneDrive por API, com OAuth seguro, chaves gerenciadas pelo usuário, envio/download fragmentado retomável, tratamento de cotas, cifragem configurável e validação remota.
5. Provar restauração isolada e integridade por destino, inclusive após simular uma reinstalação numa VM descartável.
6. Exigir cópia independente adicional e confirmação explícita de risco antes de considerar qualquer operação potencialmente destrutiva.

**Não incluído:** formatação, manipulação EFI/BCD, atribuição de letras, exclusão de originais, migração automática de contas, garantia de restauração de passkeys/senhas, ou qualquer aprovação automática de reinstalação.
