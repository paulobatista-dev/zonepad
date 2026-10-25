# Fluxo: Design de feature

## Quando usar

Use este fluxo quando uma feature ainda é uma ideia ou um pedido vago e precisa virar uma especificação aprovada. Não implemente código durante este fluxo, exceto protótipos descartáveis explicitamente pedidos.

## Entradas

- História do usuário ou problema.
- Dispositivo/plataforma afetados.
- Restrições de UX, performance e compatibilidade.
- Critérios de sucesso e não-objetivos.

## Passos

1. **Clarificar** — reformule o problema, o usuário e o resultado esperado. Liste o que está fora de escopo.
2. **Mapear impacto** — identifique camadas, módulos, perfis, métricas e dispositivos afetados.
3. **Delegar ao hardware** — peça a `controller-hardware`:
   - grandezas e unidades envolvidas;
   - impacto em normalização, deadzone, curvas ou triggers;
   - quirks de dispositivo/plataforma;
   - protocolo de validação e critérios de aceite.
4. **Delegar ao Python** — peça a `python-engineer`:
   - contratos e mudanças de modelo;
   - fluxo de dados e concorrência;
   - impacto em persistência/migração;
   - estratégia de testes e arquivos afetados.
5. **Delegar ao prompt** — peça a `prompt-engineer` se a feature mudar instruções, skills ou fluxos.
6. **Escrever a spec** — use o formato abaixo, com critérios verificáveis.
7. **Revisar** — peça aos especialistas para apontar conflitos e lacunas. Resolva antes de aprovar.
8. **Aprovar** — apresente ao usuário e aguarde aprovação. Não avance para implementação sem isso.

## Formato da spec

```markdown
## Problema
## Usuário e contexto
## Resultado esperado
## Escopo
## Fora de escopo
## Requisitos funcionais
## Requisitos não funcionais
## Modelo de dados e unidades
## Impacto por camada
## Impacto em hardware/dispositivos
## Plano de testes
## Riscos
## Critérios de aceite
## Decisões pendentes
```

## Como delegar

Use o mecanismo de subagentes da ferramenta atual:

- OpenCode: `subagent`.
- Claude Code: Agent.
- Codex: subagente.

Inclua no handoff: problema, restrições, arquivos relevantes, formato de retorno e critério de aceite.

## Critérios de pronto

- [ ] O problema e o usuário estão claros.
- [ ] O escopo e o fora de escopo estão explícitos.
- [ ] Unidades e camadas estão definidas.
- [ ] O impacto em hardware e Python foi revisado.
- [ ] Há critérios de aceite verificáveis.
- [ ] O plano de testes cobre bordas e erros.
- [ ] Riscos e decisões pendentes estão registrados.
- [ ] A spec foi aprovada pelo usuário.
