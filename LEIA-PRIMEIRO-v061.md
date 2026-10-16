# PC Restore & Optimizer v0.6.1 — Fluxo Unificado (PRÉVIA)

## Objetivo
Reorganizar a navegação e a preservação por unidade, usando a v0.6.0 como base, **sem operações destrutivas**.

## Alterações desta versão

1. **Menu reorganizado:** Visão geral, Meu computador, Preservação, Instalar Windows, Recuperação, Otimização, Diagnóstico e Histórico.
2. **Correção do escopo da varredura:** quando somente C: é selecionado, o relatório e as abas pertencem somente ao C:. A regra também vale para qualquer combinação de unidades e pastas adicionais; registros do Windows/catálogo são filtrados antes de exibição. A consulta global de aplicativos pode usar metadados do registro, mas não percorre silenciosamente outros volumes.
3. **Telas mais objetivas:** painel inicial com três etapas, métricas resumidas e checklist visual de reinstalação.
4. **Decisões independentes por volume:** itens em D:/F:/G: são previstos para permanecer na origem; dados preservados do C: requerem cópia verificada antes de apagar o Windows.
5. **Candidatos explícitos à limpeza:** é possível **marcar** um arquivo como candidato a remoção, mas o programa não executa nenhuma exclusão. “Não preservar” tampouco significa “Excluir”.
6. **Vínculos com saves:** mostra associações já identificadas entre jogos e arquivos de dados em outros discos. São candidatos para revisão, não garantias de recuperação automática.
7. **Ferramenta de backup legado:** o botão de backup agora prepara somente as seleções feitas no volume do Windows C:, sem copiar os jogos dos discos que permanecerão intactos.
8. **Exportação JSON do plano:** registra escolhas, caminhos e alertas. Não é uma prova de backup, pois não contém os arquivos.

## Antes de testar
- Descompacte em uma **nova pasta** e mantenha a v0.6.0 intacta.
- Windows 11, Python 3.10+ e dependências do `requirements.txt`.
- Para transportar decisões anteriores, copie `preferencias-v05.json` da pasta da versão antiga para a nova **com o programa fechado**. Faça uma cópia dessa preferência antes de sobrescrevê-la. Isso não transporta os backups em si.
- Para iniciar: execute `INICIAR.bat`.

## Teste recomendado
1. Em **Meu computador**, marque somente **C:** e execute a varredura. Somente C: deve aparecer no relatório atual e nas abas.
2. Repita marcando **C: e D:**. Somente C: e D: devem aparecer.
3. Marque um arquivo para **Manter** em D: e outro em C:. Abra **Preservação** e confira: D: = manter no local; C: = exige cópia.
4. Marque um caminho de teste não protegido como *candidato a remoção*. Confirme que ele **não foi apagado**. Se mudar de ideia, retire a sinalização.
5. Abra **Instalar Windows**: a tela deve somente apresentar os cuidados; não há botões para formatar ou limpar discos.
6. Confira o relatório exportado e os vínculos de saves apresentados. Dados não identificados ou erros de varredura NÃO são seguros para apagar.

## O que ainda não está implementado / aprovado
- NÃO executa formatação, alteração da EFI, limpeza seletiva, atualização do BCD nem instalação automatizada do Windows.
- NÃO garante encontrar todos os saves, licenças, programas ou senhas dos navegadores.
- NÃO determina sozinho que a cópia do C: está completa e recuperável; a conferência manual e uma restauração ensaiada continuam necessárias.
- O computador estudado tem uma EFI no disco SATA relacionado a F:, Storage Spaces G: e histórico de disco dinâmico ausente: **não formatar** até solucionar as dependências e confirmar os backups independentes.
- Para instalação limpa no SSD WD, preparar mídia oficial do Windows e reconstrução de boot com assistência, somente depois de backup verificado e decisão humana.

## Segurança
Todas as ações novas desta versão são de leitura, classificação ou exportação de plano. A rotina de backup existente copia e verifica, mas não apaga originais. Os programas podem requerer reinstalação e os saves devem voltar aos seus caminhos de origem.

## Testes
182 testes automatizados aprovados em ambiente Linux com servidor gráfico virtual (inclui teste da janela C: somente). Não substituem validação no Windows real.
