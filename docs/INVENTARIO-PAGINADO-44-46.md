# Inventário paginado — bateria #44–#46

Esta entrega acrescenta um motor de **varredura de metadados somente leitura**
com paginação e cursor de sessão, em lugar de apenas aumentar o teto estático
da auditoria #41. O scanner pode caminhar por mais de 12.000 entradas de uma
unidade, em páginas de 2.000 entradas, sem reler páginas anteriores enquanto
a janela e a sessão permanecem abertas.

## O que a nova varredura faz

- Descobre unidades Windows fixas/removíveis locais de forma dinâmica.
- Usa `os.scandir` e `stat(follow_symlinks=False)`, não abre conteúdo dos
  arquivos, não acompanha junctions, links ou outros reparse points.
- Mostra as contagens por unidade, erros de acesso, desaparecimentos, pontos
  redirecionados, quantidade de páginas e diretórios pendentes.
- Expõe três ações na aba **Novos #44–46**: `NOVA sessão de leitura`,
  `CONTINUAR próxima página` e `CONTINUAR até terminar (cancelável)`.
- Varreduras são executadas fora da thread Tk e podem ser interrompidas;
  o cursor sobrevive à pausa/cancelamento **enquanto a janela permanecer
  aberta**, mas não sobrevive ao fechamento do programa, atualização do disco
  ou reinicialização do computador.
- Não captura lista de caminhos pessoais no relatório: apenas a identificação
  das unidades e números agregados.

### Limites e advertências

Mesmo se todas as filas terminarem, a varredura **não certifica todo o
conteúdo do computador**: locais inacessíveis, reparse points, volumes sem
letra, arquivos ocultos por outros mecanismos, mudanças simultâneas e saves
dentro de locais especiais requerem verificação adicional. Não enumera ACLs
NTFS nem autoriza formatação. Não executa backup, restauração nem exclusão.

## Autotestes

- **#44**: paginação de arquivos fictícios e pastas, contagens exatas,
  progresso além de uma página e preservação dos originais.
- **#45**: interrupção entre páginas e retomada em memória, sem duplicações.
- **#46**: injeção de acesso negado e links artificiais, mantendo lacunas
  explícitas e preservando conteúdo.

Para atualizar a cópia aprovada via PowerShell **depois** da integração à
`main` e fechar a janela anterior:

```powershell
Set-Location "$HOME\PCRO-testes-38-40"
git pull --ff-only origin main
py -3 -m unittest discover -s tests -p "test_inventory_paged_v044_v046.py" -v
.\INICIAR.bat
```

Na tela de Preservação → Backup seletivo, escolha **Novos #44–46**, rode
os autotestes sintéticos e exporte cada JSON. Em seguida, a opção de
inventário por páginas é um **ensaio separado em dados reais somente leitura**.
Interromper a varredura não deve alterar ou remover arquivos.

Todos os relatórios de autoteste continuam com
`ready_for_format=false` e `installation_authorized=false`.
