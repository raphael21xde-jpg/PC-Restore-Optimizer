# PC Restore & Optimizer v0.6.2 — Correção de varredura e escolhas (PRÉVIA)

## Alterações

### 1. Varredura de unidades
- Marque apenas C:, apenas D:, apenas F:, apenas G: ou qualquer combinação e clique em **Examinar unidades marcadas**.
- A varredura profunda percorre somente as raízes selecionadas. Cada aba apresenta apenas os dados da respectiva unidade.
- Os inventários são mantidos por unidade: reexaminar D: não apaga C:. As abas exibem **atual**, **salvo** (dados anteriores, possivelmente desatualizados) ou **não examinado**.
- Os relatórios são salvos em `deteccao-detalhada-v062.json`. São metadados, não backups.
- Metadados de programas do registro do Windows podem ser consultados, mas âncoras e registros fora das unidades selecionadas são filtrados do relatório de varredura.
- A busca ampla **Pesquisar jogos e apps (todas as unidades)** é separada e NÃO roda automaticamente ao abrir o programa. Use-a conscientemente se quiser um catálogo global.

### 2. Preservação e escolhas
- **Preservação** apresenta agora uma seção de jogos e aplicativos marcados para manter, mesmo quando seus saves ou dados locais ainda não foram confirmados. Esses itens aparecem claramente como **DADOS NÃO CONFIRMADOS**.
- Jogos instalados em D: podem ter saves em C:, por exemplo. A visualização mostra o volume do jogo quando conhecido e os volumes dos dados associados, sem prometer que todos os saves foram encontrados.
- Selecionar um jogo ou aplicativo para manter NÃO garante que poderá executá-lo sem reinstalação nem que o save tenha sido protegido.
- Uma cópia independente verificada continua obrigatória para qualquer dado que só exista na partição a formatar (normalmente C:).
- O painel traz primeiro os jogos/apps escolhidos, e toda a tela de Preservação pode ser rolada para alcançar as outras tabelas.

### 3. Migração de escolhas anteriores
As preferências de cada versão ficam na pasta da própria versão. Para migrar decisões antigas:
1. Abra **Preservação** nesta v0.6.2.
2. Clique **Importar escolhas da versão anterior**.
3. Selecione o `preferencias-v05.json` da pasta da v0.6.1.
4. Confirme e revise as escolhas. Somente decisões, caminhos e dados de catálogo são importados; **não** são importadas opções de formatação ou destino de backup. O arquivo antigo permanece intacto.
5. Se precisar apenas consultar um inventário anterior, a v0.6.2 cria novos relatórios a partir das unidades que você escolher. Não confunda um inventário salvo com leitura atualizada.

## Teste recomendado com seus discos
1. Extraia este ZIP em pasta NOVA, sem sobrescrever a v0.6.1. Abra `INICIAR.bat`.
2. Marque **somente C:** e execute `Examinar unidades marcadas`. Verifique que os resultados de C: são exclusivos e as outras abas indicam não examinadas ou salvas.
3. Em seguida marque **somente D:**. Verifique que D: ganha inventário atual e C: permanece na aba com status salvo, sem misturar itens.
4. Marque um aplicativo da unidade D: na Seleção avançada e clique em **Manter + dados**. Na Preservação, veja a escolha no quadro **Jogos e aplicativos escolhidos para manter** — mesmo que apareça o aviso de dados não confirmados.
5. Repita com C: + F: ou qualquer outra combinação. Abra e feche o aplicativo, conferindo que as decisões permanecem após carregar as preferências.
6. Se ocorrer erro, exporte relatório e informe a combinação, o resultado esperado e o resultado observado; omita dados sensíveis do arquivo antes de compartilhá-lo.

## Segurança e limites
- Este aplicativo NÃO executa exclusões, formatação, reinstalação do Windows nem manipulação da EFI nesta versão. A limpeza é só prévia.
- **Não formatar o PC ainda.** Os testes automatizados são simulações e testes locais; a recuperação integral pós-formatação ainda não foi validada.
- Saves de jogos e credenciais do navegador podem existir fora dos locais identificados. Relações incertas requerem revisão manual.
- No equipamento em análise, a EFI está no SSD SATA associado a F:, o G: é Storage Spaces Simple e existe um disco dinâmico antigo ausente. A instalação limpa exigirá plano e cópia segura previamente verificados.

## Testes automatizados
190 testes aprovados em Linux com ambiente gráfico virtual, incluindo C: → D: com inventário persistente, múltiplas combinações de discos, seleção de aplicativo fora de C:, migração segura de escolhas e regressões anteriores. Isso **não comprova** automaticamente funcionamento perfeito no Windows real.
