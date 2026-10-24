# Fluxo: Implementação de feature

## Quando usar

Use este fluxo quando existe uma spec aprovada e o objetivo é entregar código, testes e documentação. Se a spec não existir, volte para `flow-design-feature`.

## Entradas

- Spec aprovada e ADR relacionado.
- Arquivos/módulos afetados.
- Critérios de aceite e restrições.

## Passos

1. **Ler a spec** — confirme escopo, unidades, critérios de aceite e não-objetivos. Se houver lacuna bloqueante, pare e pergunte.
2. **Planejar** — liste arquivos, contratos e ordem de implementação. Prefira domínio → aplicação → infraestrutura → interface.
3. **Implementar o domínio** — funções puras, tipos imutáveis, validação e testes de borda.
4. **Implementar a aplicação** — casos de uso, portas e coordenação; sem UI ou SO.
5. **Implementar a infraestrutura** — backend, store, relógio; mantenha o contrato e adicione testes de contrato.
6. **Atualizar a interface** — CLI/GUI apenas como adaptador; sem regra de calibração.
7. **Validar com hardware** — peça a `controller-hardware` para revisar semântica, unidades e critérios de aceite. Use captura/replay quando possível.
8. **Testar** — unitários, integração com fakes, replay e casos de erro. Rode lint, tipos e testes.
9. **Sincronizar assets** — se alterou `ai/`, rode `python scripts/sync_ai_assets.py` e `--check`.
10. **Revisar o diff** — escopo, erros, concorrência, performance, segurança e documentação.
11. **Encerrar** — atualize README/ADR/changelog quando necessário e resuma riscos.

## Como delegar

- OpenCode: `subagent`.
- Claude Code: Agent.
- Codex: subagente.

A revisão de hardware pode ser assíncrona, mas não ignore os achados. Um blocker de hardware impede o "pronto".

## Formato de saída

```markdown
## Plano executado
## Mudanças por arquivo
## Testes e validações
## Revisão de hardware
## Riscos e limitações
## Próximos passos
```

## Critérios de pronto

- [ ] A implementação segue a spec e a arquitetura.
- [ ] O domínio permanece puro.
- [ ] Há testes para caminho feliz, bordas e erros.
- [ ] Lint, tipos e testes passam.
- [ ] A semântica de hardware foi revisada.
- [ ] `sync_ai_assets.py --check` está limpo.
- [ ] Documentação/ADR foi atualizada.
- [ ] Riscos e trabalho não coberto estão explícitos.
