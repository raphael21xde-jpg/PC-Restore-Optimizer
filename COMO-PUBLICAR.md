# Publicar código-fonte no GitHub
1. Extraia o ZIP em uma pasta normal, sem backups pessoais dentro dela.
2. Instale Git for Windows e autentique-se no GitHub, se necessário.
3. No PowerShell, nessa pasta, execute `powershell -ExecutionPolicy Bypass -File .\PUBLICAR-NO-GITHUB.ps1`.
4. Confira a lista de arquivos apresentada antes de digitar `PUBLICAR`.
5. Confirme o resultado em https://github.com/raphael21xde-jpg/PC-Restore-Optimizer/actions

O script clona o repositório existente antes de adicionar o restante do código, sem apagar commits anteriores. Não formata discos nem executa backup/restauração.
