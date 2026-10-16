# Desenvolvimento v0.7.0-dev

A versão disponibilizada em ZIP anteriormente contém a base v0.6.9 e alterações preliminares. O repositório está sendo populado progressivamente; **não considere os arquivos atualmente publicados como todo o aplicativo**.

## Princípios
- Compatibilidade com diferentes computadores Windows suportados.
- Nunca pressupor letras C:, D:, F: e G: ou destino G:.
- Seleção destrutiva não deve ser reativada automaticamente.
- Backups e restaurações precisam de validação antes do lançamento.
- Separar descobertas, interface, tarefas longas e operações de disco.

## Pendências prioritárias
- Publicar todos os módulos de código da versão auditada.
- Auditar entradas e dependências; verificar vazamento de dados antes da publicação.
- Testes integrados do motor de backup, restauração e hashes.
- Testes em máquinas virtuais Windows com múltiplas topologias de armazenamento.
- Projeto e implementação do design gamer do Figma.
- Instalador e documentação de suporte.

**Proibido tratar testes sintáticos ou mocks como validação de formatação real.**
