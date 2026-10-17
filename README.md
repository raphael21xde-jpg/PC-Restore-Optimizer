# PC Restore & Optimizer

> **Ponto de retomada do desenvolvimento (17/10/2026):** [estado consolidado, testes já aprovados e próximos marcos](docs/ESTADO-DO-PROJETO-E-PROXIMOS-MARCOS.md). Consulte esse documento antes de criar novos testes ou repetir etapas. O próximo marco é integrar evidências de cobertura, backup e restauração por caminho, não reconstruir o motor.

Base histórica v0.6.9, preservada a partir do arquivo disponibilizado pelo autor. **Não é a versão v0.8.1.** Não executar em produção operações de disco, instalação ou restauração sem testes.

## Objetivo
Ferramenta para computadores Windows de diferentes configurações, com inventário de volumes, seleção explícita de preservação, backup verificável, recuperação, orientação de reinstalação do Windows e otimizações seguras.

## Princípios inegociáveis
- Examinar volumes presentes e permitir seleção de arquivos/pastas/programas/jogos/saves sem apagamentos implícitos.
- Não confundir 'não copiar' com 'apagar'. Nenhuma exclusão a partir de inventário/seleção.
- Detectar dependências entre unidades e preservar a seleção do usuário.
- Verificação de integridade SHA-256 e recuperação testável; registrar erros e progresso.
- Operações destrutivas exigem etapa independente de confirmação e auditoria; desabilitadas por padrão.
- Sem garantia de reinstalação automática de softwares licenciados, passkeys, credenciais ou programas sem instaladores.

## Estado
Código Python e testes históricos importados da v0.6.9; não certificados em hardware real. As funcionalidades descritas em `docs/ESPECIFICACAO.md` são requisitos de produto, **não** alegações de implementação.

## Executar e testar no Windows
Inspecione `requirements.txt` antes de instalar dependências. Crie um ambiente virtual e execute `python -m unittest discover -s tests` no ambiente apropriado. Confira também `INICIAR.bat` antes de executar o aplicativo. Nunca aponte os primeiros testes para dados únicos ou para o disco do Windows.
