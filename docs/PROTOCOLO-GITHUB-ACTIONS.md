# Protocolo econômico de GitHub Actions — PC Restore & Optimizer

Este protocolo mantém todos os testes e preserva o bloqueio de formatação,
mas evita executar a suíte pesada a cada `git push`. O repositório é privado;
minutos de runners hospedados têm franquia e cobrança conforme o plano vigente.
**Badges não consomem minutos**: são as execuções que consomem.

## Eventos e responsabilidades

| Situação | Onde | O que roda |
|---|---|---|
| Codificar, alterar tela, corrigir pequeno erro | PC / PowerShell | Sintaxe e testes focados |
| Abrir ou atualizar PR com destino à `main` | GitHub Actions automático | `syntax.yml` (análise AST) + `quality.yml` (testes rápidos no **Windows**) |
| Atualizar branch com `push` sem PR | Local | **Nenhum** Actions automático |
| Integrar mudança relevante de motor, inventário, recuperação ou lançamento importante | `quality.yml` → **Run workflow** | Suíte completa Windows + Linux (solicitada manualmente para o **HEAD atual da PR**) |
| Publicar tag de versão `v*` | GitHub Actions automático | Suíte completa Windows + Linux |
| PR recebe um commit novo | GitHub Actions | Execuções rápidas anteriores dessa PR são canceladas; **nunca** cancela a suíte manual ou de release |

O workflow `quality.yml` conserva **todos** os testes pesados pré-existentes,
incluindo 2 GiB, falhas sintéticas, event loop Tk, verificações SHA-256 e
regressão completa. Apenas o gatilho mudou. `syntax.yml` roda em runner
Ubuntu com Python já instalado, sem instalar ferramentas adicionais; o job
rápido funcional roda em **Windows**, que é a plataforma-alvo.

A validação rápida de PR é intencionalmente parcial: testa a lógica essencial no
**Windows**, mas não substitui os testes de integração, backup de grande porte,
interface Tk nem validação completa do sistema. **Aprovação de PR importante exige**
realizar e conferir o workflow manual **Full regression** na branch exata que
será integrada. Se novos commits forem adicionados após esse teste, repita a
verificação completa pertinente ao código modificado. A política é operacional;
a existência de um botão manual por si só não impõe bloqueio no GitHub.

## Execução local — PowerShell

Abra o repositório/worktree correto, confirme que tem a versão desejada e
execute antes de enviar alterações:

```powershell
py -3 -m compileall -q .
py -3 -m unittest discover -s tests -p "test_inventory_file_index.py" -v
py -3 -m unittest discover -s tests -p "test_inventory_paged_v044_v046.py" -v
py -3 -m unittest discover -s tests -p "test_index_choices_bridge.py" -v
py -3 -m unittest discover -s tests -p "test_safe_features.py" -v
```

Para validar alterações grandes no Windows, executar separadamente a regressão
local e verificar seus relatórios:

```powershell
py -3 tests/run_full_suite.py --timeout 420
```

Os testes de 2 GiB permanecem **opt-in**: não acione em máquinas com pouco
espaço nem sem conhecimento do consumo temporário de disco. Nenhum teste
deste protocolo deve executar formatação ou exclusão de dados de usuário.

## Como executar a bateria completa no GitHub

1. Abra **Actions → Quality checks**.
2. Selecione **Run workflow**.
3. Selecione a branch da PR **na revisão que será integrada**, não outra versão.
4. Clique em **Run workflow** e aguarde os dois jobs de Windows e Linux.
5. Integre ou publique somente quando os relatórios necessários estiverem aprovados.

A tag `v*` executa a mesma bateria novamente para validar a publicação.
Não crie tags apenas para testar pequenas alterações.

## Cache e futuras melhorias

`quality.yml` usa cache `pip` com chave baseada em `requirements.txt`.
Isso evita downloads repetidos quando houver acerto de cache, mas **não**
elimina o tempo de provisionamento do runner nem garante que o `pip` dispense
todas as instalações. São preservados os testes completos e o ambiente
isolado de cada execução.

Para economizar ainda mais, poderá ser adotado CI com detecção de arquivos
alterados e categorias de teste, sem dispensar a suíte completa de segurança
em alterações importantes.
