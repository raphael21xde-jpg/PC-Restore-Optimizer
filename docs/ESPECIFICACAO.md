# Especificação consolidada (base de trabalho)

## Escopo universal
O aplicativo deve usar detecção dinâmica, não caminhos fixos `C:`, `D:`, `F:` e `G:`. Essas letras são exemplos da máquina de testes. Identificar unidades, partições, pontos de montagem, capacidade e arquivos, respeitando acessos negados e a privacidade.

## Inventário e seleção
- Inventariar arquivos e diretórios com tamanho, metadados, caminho de origem e unidade.
- Distinguir programas, jogos, bibliotecas e saves com confiança de detecção e vínculos entre volumes; permitir correções manuais.
- Permitir preservar, não copiar e selecionar granularmente. `Não copiar` nunca implica exclusão.
- Explicitar o que será copiado, o que não será e quais dependências permanecem desprotegidas.

## Backup
- Cópia seletiva em streaming (sem carregar jogos inteiros na RAM), progresso responsivo, cancelamento seguro, retomada ou reinício idempotente, logs e verificação SHA-256.
- Identidade da origem, destino, espaço livre, colisões, arquivos bloqueados e permissões verificadas.
- Testes de integridade e restauração com arquivos sintéticos grandes e falhas simuladas.

## Restauração
- Prévia da recuperação, mapeamento de caminhos, conflitos, permissões, verificação pós-cópia e relatório.
- Separar dados restauráveis de aplicativos que exigem instaladores e autenticação. Backups de navegadores nunca prometerão restauração universal de senhas, sessões ou passkeys.

## Windows / EFI
- Inventariar modo de boot, layout de disco, disco de sistema e partição EFI, com diagnóstico e avisos sobre riscos.
- Antes de qualquer formatação, exigir backup verificado, teste de recuperação, identificação inequívoca do disco-alvo e confirmação explícita.
- Preparar fluxo de reinstalação guiada e validar inicialização independente; não executar formatação silenciosa.

## Otimização
- Medição antes/depois, reversibilidade, configurações conservadoras e autorização específica. Evitar remoções ou alterações agressivas sem auditoria.

## Entregas por fases
1. Baseline e regressões (importar e executar testes da v0.6.9 no Windows).
2. Inventário universal, seleção e dependências.
3. Motor de backup escalável, com hash e retomada.
4. Restauração escalável e validação independente.
5. Preparação de reinstalação/EFI e testes em máquina virtual.
6. Otimizações seguras, empacotamento e matriz de compatibilidade.

## Critérios para chamar algo de pronto
Teste automatizado + teste real em Windows + resultados registrados + ausência de perda de dados em cenários de falha e cancelamento. Nenhuma versão é considerada aprovada apenas por abrir a interface.
