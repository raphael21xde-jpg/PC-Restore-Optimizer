# Autotestes #38–#40: próximos ensaios

Todos os três ensaios são não destrutivos. Nenhum formata, apaga dados de usuário,
modifica EFI ou autoriza reinstalar o Windows.

## #38 — 2.048 arquivos pequenos (sintéticos)

- Cria até 2.048 arquivos fictícios em 32 grupos, em pasta temporária exclusiva.
- Mede cópia, restauração e confere SHA-256 em ambas as direções.
- Verifica que os arquivos artificiais originais permaneceram intactos.
- Regressões de CI usam 128 arquivos para reduzir custo; teste manual usa 2.048.
- Não extrapolar taxa obtida para discos lentos, muitos milhões de arquivos ou
  operações reais.

## #39 — Auditoria limitada de metadados (somente leitura)

- Acionado somente pelo botão específico na interface.
- No Windows observa unidades fixas e removíveis enumeradas dinamicamente; não
  usa letras de drive codificadas nem sonda destinos de rede ou unidades ópticas.
- Faz somente observação de nomes de pastas e metadados com `os.scandir`,
  `DirEntry.stat(follow_symlinks=False)` e verificação de diretórios.
- Limites **por volume**: 3.000 entradas e profundidade 2; reparse points e
  junções não são percorridos. Caminhos originais são resumidos por volume.
- Relata contagens, erros de leitura e limites de cobertura. Nomes de pasta
  reconhecidos são apenas **candidatos**; não confirma automaticamente jogos,
  instalações de programas, saves nem vínculos entre discos.
- Não abre conteúdo de arquivos, não cria backup nem faz qualquer escrita durante
  a auditoria. No CI recebe somente raízes sintéticas explicitamente passadas.

## #40 — Seleção e restauração ponta a ponta, isoladas

- Monta três grupos de arquivos fictícios, seis itens no total.
- Marca cinco como preservar e um como `não copiar`.
- Confere manifesto de cinco arquivos e faz restauração em subpasta temporária nova.
- Verifica SHA-256, ausência de item excluído e preservação de marcador preexistente.
- Testa rejeição de `../` como caminho inválido.
- Não reinstala aplicativos e não testa ACL/NTFS de uma máquina real.

## Execução no Windows via PowerShell

Após a validação do pull request e a integração na `main`, atualizar usando
Git e worktree em pasta separada. **Não sobrescrever a cópia aprovada**:

```powershell
git fetch origin
git worktree add ..\PCRO-testes-38-40 origin/main
Set-Location ..\PCRO-testes-38-40
py -3 -m unittest discover -s tests -p "test_autotestes_bateria_v038_v040.py" -v
.\INICIAR.bat
```

Na tela Preservação → Backup seletivo e TESTE de recuperação do C:,
executar #38, #39 e #40 individualmente. Após cada um, selecionar
**Exportar relatório** para criar `resultado-autoteste38.json`,
`resultado-autoteste39.json` e `resultado-autoteste40.json`.

O #39 só faz um levantamento raso e pode indicar cobertura parcial; não deve
ser apresentado como inventário completo. Todos continuam com
`ready_for_format=false`, `installation_authorized=false` e
`physical_independence_verified=false`.
