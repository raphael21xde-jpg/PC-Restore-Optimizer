# PC Restore & Optimizer

Software Windows em desenvolvimento para inventariar discos, arquivos, programas, jogos e saves; permitir seleção individual; preservar dados; apoiar reinstalação segura do Windows; recuperar informações e otimizar o sistema.

## Objetivo
Produto para diferentes computadores Windows — **não limitado à máquina de testes**. Nenhum disco, letra de unidade, layout EFI ou destino de backup deve ser presumido.

## Estado
**Prévia de desenvolvimento (v0.7.0-dev). Não utilizar para formatação ou reinstalação em computador com dados importantes.** As rotinas de backup e restauração precisam de testes adicionais de integridade, interrupção e recuperação.

## Regras
- Nenhuma exclusão ou formatação automática.
- Operações destrutivas requerem validação e confirmação específicas.
- Nunca incluir backups, dados pessoais, segredos ou exports de navegador no Git.
- Distinguir implementado, testado automaticamente e validado em equipamentos Windows.
- Interface gamer moderna, mas acessível; Figma para design, GitHub para código e testes.

## Próximas atividades
1. Incorporar o código-fonte v0.7.0-dev auditado.
2. Validar arquitetura, dependências e testes automatizados.
3. Generalizar descoberta de volumes, aplicativos, jogos e saves.
4. Fortalecer seleção, integridade SHA-256, retomada e restauração.
5. Integrar interface, preparar instalador e homologação Windows.

> O histórico de testes em uma máquina não comprova compatibilidade universal.
