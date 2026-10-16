# Publicar a base completa

A base de código da v0.7.0-dev está no pacote ZIP entregue no chat, e **não está integralmente publicada no GitHub ainda**.

1. Extraia o arquivo `PC-Restore-Optimizer-v0.7.0-GitHub-ready.zip`.
2. Na pasta extraída, abra o PowerShell.
3. Execute `powershell -ExecutionPolicy Bypass -File .\PUBLICAR-NO-GITHUB.ps1`.
4. Revise a lista de arquivos e digite `PUBLICAR` apenas se não houver backups, senhas ou dados pessoais.
5. Confirme os resultados em **Actions**.

O script clona este repositório antes de adicionar os arquivos. Ele requer Git for Windows e uma sessão autenticada. Não executa formatação.
