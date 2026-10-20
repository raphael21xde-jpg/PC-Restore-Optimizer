# Etapa 30 — fluxo completo de recuperação após reinstalação simulada

## Escopo

Ensaio exclusivamente em `TemporaryDirectory` com arquivos fictícios e dois
destinos de backup. **Não realiza nem autoriza formatação**, instalação do
Windows, alterações na EFI, inspeção de discos reais, restauração de usuários
reais ou qualquer exclusão fora da pasta temporária do teste.

Esta etapa é uma validação de **integração**, não a disponibilização de um
restaurador multidisco de produção.

## Fluxo verificado

1. Um inventário temporário seleciona um documento e um save fictício em
   origens distintas.
2. Duas cópias independentes (somente pastas simuladas) são criadas e
   verificadas pelo motor de testes.
3. Os arquivos de origem fictícios podem deixar de existir; a janela inicial
   abre as cópias apenas pelos manifestos persistidos.
4. A nova sessão não herda nenhuma autorização de backup ou instalação.
5. Na central, o usuário escolhe **Verificar cópias (SHA-256)**; o botão de
   restaurar permanece desabilitado até uma seleção explícita.
6. Após confirmar, somente os arquivos escolhidos são copiados para uma
   **nova pasta de teste** e reverificados; a interface informa arquivo,
   resultado SHA-256 e cópia efetivamente utilizada.
7. A verificação independente confere também o
   `ESTADO-RESTAURACAO.json`, os bytes dos dados recuperados e as restrições
   de segurança.

Os testes adicionais cobrem troca para a segunda cópia, recusa de
confirmação, duas cópias corrompidas, manifestos incompatíveis e reabertura
de outra sessão (que exige nova inspeção SHA-256).

## Teste focado no Windows

```powershell
py -3 scripts\test_reporter.py --pattern "test_offline_complete_recovery_e2e.py" --publish
```

**Revise a prévia sanitizada antes de usar `--publish` em um PR público.**
O publicador usa GitHub CLI; a execução local não consome GitHub Actions e
o commit desta etapa inclui `[skip ci]`.

A interface manual, também limitada a dados fictícios, é aberta com:

```powershell
py -3 scripts\demo_multi_source_recovery_center.py
```

## Fora do escopo / pendente

- Executar o fluxo em dados reais de vários discos e certificados de
  independência física, inclusive compartilhamento de dispositivos.
- Permitir que a interface principal controle execução ou formatação reais.
- Tornar a recuperação de programas e jogos realmente instalados equivalente
  à mera cópia de arquivos.
- Automatizar instalação do Windows, EFI, restauro de contas/credenciais e
  otimizações de firmware/hardware.

Um teste aprovado demonstra os cenários implementados e **não prova**
ausência geral de falhas/races TOCTOU privilegiadas.
