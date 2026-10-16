# PC Restore & Optimizer — Especificação UX/UI v0.5.4

## Objetivo
Uma experiência de proteção e recuperação de dados **orientada por tarefas**, não por módulos técnicos. Inspirada nos princípios apresentados em [Lovable for Designers](https://lovable.dev/designers): fluxos reais, estados vazios, caminhos de exceção, comportamentos de sistemas funcionais, não apenas telas bonitas. Não é uma reprodução da marca nem da interface do site.

## Público e problema
Pessoas com muitos jogos, saves, aplicativos de periféricos e discos diferentes querem preparar uma futura reinstalação do Windows sem perder progresso ou arquivos. Seu principal desafio é distinguir **detectado**, **selecionado**, **copiado**, **verificado** e **restaurado**. A interface deve impedir interpretações perigosas.

## Arquitetura de informação

| Área | Tarefa do usuário | Resultado esperado |
| --- | --- | --- |
| Visão geral | Entender o que fazer | Próximo passo e estado do projeto |
| Jogos e aplicativos | Descobrir e selecionar | Decisões e caminhos associados |
| Arquivos e pastas | Escolher dados extras | Seleções explícitas |
| Revisar backup | Conferir tamanho, espaço, destino, alertas | Prévia validada antes de copiar |
| Backups e testes | Confirmar cópia e testar integridade | SHA-256 e restauração isolada |
| Navegador e contas | Proteger perfil Opera GX | Cópia criptografada e orientação Sync |
| Discos e diagnóstico | Entender o hardware | Diagnóstico somente leitura |
| Após reinstalar Windows | Exportar plano e recuperar | Plano JSON e cópia de saves para conferência |

## Modelo de estados
- **Não pesquisado:** mostrar instrução e ação de detecção.
- **Pesquisando:** status textual, sem afirmar que encontrou dados.
- **Conhecido:** local detectado, **não** significa backup concluído.
- **Possível / conferir:** requer verificação humana; nunca é aprovado automaticamente.
- **Selecionado:** intenção registrada e persistida, **não** implica cópia.
- **Prévia não calculada ou alterada:** botão de cópia desabilitado.
- **Prévia com bloqueios:** botão de cópia desabilitado e razão no relatório.
- **Prévia sem bloqueios:** botão habilitado; manter confirmação explícita antes da cópia.
- **Cópia em andamento:** barra de progresso e aviso para não desligar.
- **Cópia parcial/com erros:** não apresentar como backup confiável.
- **Restauração:** sempre para diretório novo sem substituir originais.

## Sistema visual
- Painel escuro de alto contraste, menu lateral profundo e cartões discretamente contornados.
- Ação principal em violeta, segurança em verde e avisos em âmbar.
- Tipografia Segoe UI com títulos bem separados dos controles.
- Texto explicativo em linguagem comum e ações com verbo no início.
- Botões e campos maiores, barras de rolagem em listagens compridas.
- Navegação pelo mouse e por teclado: **Ctrl+1** até **Ctrl+8**; Tab para menu, Enter/Espaço para abrir.

## Regras que não podem ser rompidas
1. Não executar comandos de exclusão, partição, conversão, formatação ou reinstalação.
2. Nunca sugerir que G: seja formatável; F: contém EFI e exige cautela extra.
3. Não confundir armazenamento no G: sem resiliência com cópia independente.
4. Não marcar como garantidos candidatos inferidos de nome ou locais de dados em nuvem.
5. Sempre exigir confirmação para qualquer cópia e verificar antes de informar sucesso.
6. Não garantir recuperação de senhas, licenças, contas ou sessões.
7. Preferências anteriores devem ser importadas em cópia; nunca sobrescrever originais.

## Escopo e limitações
Esta entrega refaz o visual e os fluxos do aplicativo Tkinter para Windows, **não** converte o projeto para web/React nem conecta o aplicativo aos servidores da Lovable. Não foi testada diretamente no computador do usuário; telas podem variar conforme escala e fontes do Windows. Prioridade futura: testes de usabilidade reais, acessibilidade completa e seleção de aplicativos por agrupamentos.
