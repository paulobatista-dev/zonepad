---
name: flow-review-calibration
description: "Revisão multiagente de código e medições de calibração: hardware valida semântica, Python valida implementação/testes e prompt valida instruções. Use em PRs, diffs ou antes de release."
disable-model-invocation: true
argument-hint: "[diff/PR/branch] [foco]"
---

<!-- Gerado por scripts/sync_ai_assets.py. Edite a fonte em ai/. -->

# Fluxo: Revisão de calibração

## Quando usar

Use este fluxo para revisar um diff, PR, branch ou conjunto de capturas antes de merge/release. Não use para implementar a correção; a menos que o usuário peça, apenas reporte achados.

## Entradas

- Diff, PR ou branch.
- Spec/ADR e critérios de aceite.
- Capturas/replay, se houver.
- Foco da revisão (segurança, performance, compatibilidade etc.).

## Passos

1. **Delimitar** — confirme o escopo e liste os arquivos alterados. Se necessário, rode `git diff`/`git status`.
2. **Revisão de hardware** — delegue a `controller-hardware`:
   - unidades, ranges e normalização;
   - ordem das transformações;
   - deadzone, curvas e triggers;
   - quirks de dispositivo/plataforma;
   - validade das capturas e critérios de aceite.
3. **Revisão Python** — delegue a `python-engineer`:
   - arquitetura e acoplamentos;
   - concorrência, timeouts e desconexão;
   - erros, validação e segurança;
   - testes, determinismo e performance;
   - legibilidade e manutenção.
4. **Revisão de instruções** — delegue a `prompt-engineer`:
   - agentes/skills/fluxos afetados;
   - consistência com `AGENTS.md`;
   - arquivos gerados sincronizados;
   - custo de contexto e clareza.
5. **Sintetizar** — consolide os achados, remova duplicatas e resolva conflitos com base na spec.
6. **Priorizar** — classifique como `blocker`, `high`, `medium` ou `low`, com arquivo:linha, impacto e correção sugerida.
7. **Concluir** — entregue o relatório. Só aplique correções se o usuário pedir explicitamente.

## Como delegar

- OpenCode: `subagent`.
- Claude Code: Agent.
- Codex: subagente.

Peça a cada revisor que não edite arquivos durante a revisão. Isso evita conflitos entre revisões paralelas.

## Formato do relatório

```markdown
## Escopo revisado
## Resumo
## Achados
### Blocker
- [arquivo:linha] Problema. Impacto. Correção sugerida.
### High
### Medium
### Low
## Validações executadas
## Riscos residuais
## Recomendação
```

## Critérios de pronto

- [ ] O escopo e a spec foram considerados.
- [ ] Hardware, Python e instruções foram revisados.
- [ ] Cada achado tem arquivo:linha e impacto.
- [ ] Achados duplicados foram consolidados.
- [ ] A recomendação final é explícita (aprovar, aprovar com ressalvas, bloquear).
- [ ] Nenhum arquivo foi alterado sem pedido.
